from __future__ import annotations

import ast
import json
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
# can only be reset in the context that set it. An async generator's body can resume in a
# different task from the one that started it -- a StreamingResponse body is driven first by
# the endpoint coroutine's priming `anext` and then by the response's own anyio task, which
# holds a COPY of the context -- so a block that stays open across a `yield` there detaches
# in the wrong task and OpenTelemetry logs `Failed to detach context` for every request.
#
# Two of these existed at once (`/api/chat/stream` + `/api/answer/stream` through
# `server/api/*`, and `generation.gateway_stream` in the streaming generator itself), which
# is why this is an invariant over the tree rather than one more regression test.
CONTEXT_ATTACHING_HELPERS = frozenset(
    {
        "stage_span",
        "start_as_current_span",
        "start_request_observation",
        "use_span",
    }
)


def _context_helper_name(item: ast.withitem) -> str | None:
    call = item.context_expr
    if not isinstance(call, ast.Call):
        return None
    func = call.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
    return name if name in CONTEXT_ATTACHING_HELPERS else None


def _offending_blocks(tree: ast.AST) -> list[tuple[str, int, int]]:
    """(helper, with-line, yield-line) for every context-attaching block held over a yield.

    Scoped to `async def` bodies: a `@contextmanager`-decorated sync generator yields as
    part of the context-manager protocol, in the caller's own task, which is not this
    hazard.
    """
    found: list[tuple[str, int, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for block in ast.walk(node):
            if not isinstance(block, (ast.With, ast.AsyncWith)):
                continue
            helpers = [name for name in map(_context_helper_name, block.items) if name]
            if not helpers:
                continue
            for inner in ast.walk(block):
                if isinstance(inner, (ast.Yield, ast.YieldFrom)):
                    found.append((helpers[0], block.lineno, inner.lineno))
                    break
    return found


def test_no_async_generator_holds_a_span_context_across_a_yield() -> None:
    offenders: list[str] = []
    for path in sorted((ROOT / "server").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for helper, with_line, yield_line in _offending_blocks(tree):
            offenders.append(
                f"{path.relative_to(ROOT)}:{with_line}: `{helper}` stays open across the "
                f"yield at line {yield_line}; use `stage_span_detached`"
            )
    assert not offenders, "\n".join(offenders)
