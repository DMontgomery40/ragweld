from __future__ import annotations

import ast
import json
import textwrap
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILES = (
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / ".claude/rules/pydantic-first.md",
    ROOT / ".claude/rules/typescript-types.md",
    ROOT / "docs/design-docs/core-beliefs.md",
    ROOT / "scripts/docs_ai/docs_prompt_base.md",
    ROOT / "web/src/ARCHITECTURE.md",
)


def test_authoritative_policy_uses_boundaries_not_a_universal_pydantic_law() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in POLICY_FILES)

    assert "Pydantic is the law" not in combined
    assert "No adapters/transformers/mappers" not in combined
    assert "public API" in combined
    assert "generated" in combined
    assert "local UI" in combined
    assert "compatibility" in combined


def test_guard_does_not_ban_boundary_mapping_by_class_name() -> None:
    guards = json.loads((ROOT / ".claude/hooks/guards.json").read_text(encoding="utf-8"))
    serialized = json.dumps(guards)

    assert "class.*Adapter" not in serialized
    assert "class.*Transformer" not in serialized
    assert "class.*Mapper" not in serialized


# ==============================================================================
# Span context may not straddle a task hand-off
# ==============================================================================

# `stage_span` and friends attach an OpenTelemetry context token, and a contextvars token
# can only be reset in the context that set it. Code that runs part of a request in one task
# and the rest in another -- a StreamingResponse body is driven first by the endpoint
# coroutine's priming `anext` and then by the response's own anyio task, which holds a COPY
# of the context -- must therefore not carry an attached token across that boundary.
# OpenTelemetry logs `Failed to detach context` for every request that does.
#
# Task 17 found this shape twice at once, in two different spellings, which is why this is a
# tree invariant rather than one more regression test:
#
#   A. a context-attaching `with` held open across a `yield` of the same async function
#      (`generation.gateway_stream` in `stream_chat_text`);
#   B. `cm.__enter__()` in an async function whose matching `cm.__exit__()` runs inside a
#      nested function, i.e. in whatever task drives that callable
#      (`/api/chat/stream` and `/api/answer/stream`).
CONTEXT_ATTACHING_HELPERS = frozenset(
    {
        "stage_span",
        "start_as_current_span",
        "start_request_observation",
        "use_span",
        # `StreamingObservation.scope`, the replacement API: it attaches the same token.
        "scope",
    }
)


def _local_helper_names(tree: ast.AST) -> frozenset[str]:
    """Helper names as this module spells them, including `import ... as` aliases."""
    names = set(CONTEXT_ATTACHING_HELPERS)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                leaf = alias.name.rsplit(".", 1)[-1]
                if leaf in CONTEXT_ATTACHING_HELPERS and alias.asname:
                    names.add(alias.asname)
    return frozenset(names)


def _own_body(node: ast.AST) -> Iterator[ast.AST]:
    """Walk `node` without descending into nested callables.

    A `yield` inside a nested generator belongs to that generator, not to the block it
    happens to be written in, so descending would flag code that is fine.
    """
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(current))


def _nested_callables(node: ast.AST) -> Iterator[ast.AST]:
    """Every function defined inside `node`, at any depth."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            yield child
            yield from _nested_callables(child)
        else:
            yield from _nested_callables(child)


def _called_attr(node: ast.AST, attr: str) -> str | None:
    """The receiver name of a `<name>.<attr>(...)` call, if that is what this node is."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr != attr:
        return None
    return func.value.id if isinstance(func.value, ast.Name) else None


def _helper_name(item: ast.withitem, helpers: frozenset[str]) -> str | None:
    call = item.context_expr
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name if name in helpers else None


def _offending_blocks(tree: ast.AST) -> list[str]:
    """Every place a span context is carried across a task boundary, described."""
    helpers = _local_helper_names(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue

        # A. a context-attaching `with` held open across this function's own `yield`.
        for block in _own_body(node):
            if not isinstance(block, (ast.With, ast.AsyncWith)):
                continue
            names = [n for n in (_helper_name(i, helpers) for i in block.items) if n]
            if not names:
                continue
            for inner in _own_body(block):
                if isinstance(inner, (ast.Yield, ast.YieldFrom)):
                    found.append(
                        f"line {block.lineno}: `{names[0]}` stays open across the yield at "
                        f"line {inner.lineno}; use `stage_span_detached`"
                    )
                    break

        # B. `cm.__enter__()` here, `cm.__exit__()` inside a nested callable.
        entered = {
            name
            for name in (_called_attr(child, "__enter__") for child in _own_body(node))
            if name
        }
        if not entered:
            continue
        for nested in _nested_callables(node):
            for child in ast.walk(nested):
                name = _called_attr(child, "__exit__")
                if name in entered:
                    found.append(
                        f"line {child.lineno}: `{name}` is entered in `{node.name}` and left "
                        f"inside a nested callable; enter and leave it in the same task"
                    )
    return found


PROBES: tuple[tuple[str, bool, str], ...] = (
    (
        "with-across-yield",
        True,
        """
        async def stream():
            with stage_span("x"):
                yield 1
        """,
    ),
    (
        "scope-across-yield",
        True,
        """
        async def stream():
            with observation.scope():
                yield 1
        """,
    ),
    (
        "aliased-import",
        True,
        """
        from server.observability.runtime import stage_span as ss

        async def stream():
            with ss("x"):
                yield 1
        """,
    ),
    (
        "enter-here-exit-in-nested-callable",
        True,
        """
        async def endpoint():
            obs_cm = start_request_observation()
            obs_cm.__enter__()

            async def body():
                try:
                    yield 1
                finally:
                    obs_cm.__exit__(None, None, None)

            return body()
        """,
    ),
    (
        "yield-belongs-to-a-nested-generator",
        False,
        """
        async def caller():
            with stage_span("x"):
                async def inner():
                    yield 1
                await consume(inner())
        """,
    ),
    (
        "enter-and-exit-in-the-same-callable",
        False,
        """
        async def endpoint():
            scope = observation.scope()
            scope.__enter__()
            try:
                pass
            finally:
                scope.__exit__(None, None, None)

            async def body():
                inner = observation.scope()
                inner.__enter__()
                try:
                    yield 1
                finally:
                    inner.__exit__(None, None, None)

            return body()
        """,
    ),
    (
        "detached-stage-span-across-yield",
        False,
        """
        async def stream():
            with stage_span_detached("x"):
                yield 1
        """,
    ),
    (
        "contextmanager-generator-is-not-async",
        False,
        """
        @contextmanager
        def scope_helper(observation):
            with use_span(observation.span, end_on_exit=False):
                yield observation
        """,
    ),
)


def test_the_span_context_scan_recognises_the_shapes_it_is_written_for() -> None:
    """The invariant is only worth its commit message if it catches both spellings.

    Task 17's first version matched a `with` block only, so it saw
    `generation.gateway_stream` and missed the `__enter__()`/`__exit__()` pair in the two
    streaming endpoints -- the primary defect of that task.
    """
    for name, should_flag, source in PROBES:
        found = _offending_blocks(ast.parse(textwrap.dedent(source)))
        assert bool(found) is should_flag, (name, found)


def test_no_async_generator_holds_a_span_context_across_a_yield() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "server").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for description in _offending_blocks(tree):
            offenders.append(f"{path.relative_to(ROOT)}:{description}")
    assert not offenders, "\n".join(offenders)
