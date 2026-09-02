"""The reaper's prefix rail: what counts as test residue, in every store's naming.

The reaper deletes from the operator's live Postgres, Neo4j and Qdrant on every
pytest session, so this pins the classification in both directions and in every
form a corpus id takes on the way through the stores:

- the plain registry id (``pytest_x``, and the names of the tests that leaked);
- its staged Neo4j/Postgres generation (``__staging__<corpus>__<run>``);
- its Qdrant collection prefix (``ragweld_chunks_<slug>_<hash>``).

The operator's real corpora must be rejected in all three forms.

The last test is the guard the rail depends on: every id a test under ``tests/``
hands to a store-writing call must carry a reapable prefix, otherwise the
residue it leaves on failure can never be reaped (``seed-due-graph-91b4a3`` and
``qdrant-store-*`` were exactly such leaks).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from server.indexing.generations import STAGING_REPO_PREFIX, staging_repo_id
from server.retrieval.qdrant_store import corpus_collection_prefix
from tests.corpus_reaper import (
    TEST_CORPUS_PREFIX,
    TEST_CORPUS_PREFIXES,
    is_test_corpus_id,
    qdrant_test_collection_prefixes,
    staged_corpus_of,
)

OPERATOR_CORPORA = ("epstein-files-public", "nasa-apollo-11", "ragweld_code", "recall_default")
RUN_ID = "0123456789abcdef0123456789abcdef"


@pytest.mark.parametrize(
    "repo_id",
    [
        "promoted-lane-x",  # tests/integration/test_index_promoted_lane.py (pre-rename leak)
        "relroot_x",  # tests/api/test_index_relative_corpus_root.py (pre-rename leak)
        "pytest_x",
        "test_x",
        "test-x",
        "recall_test_x",
        "ragweld-exhaustive-x",
        "heartbeat-x",
    ],
)
def test_test_corpus_names_are_reap_eligible_plain_and_staged(repo_id: str) -> None:
    assert is_test_corpus_id(repo_id), repo_id
    assert is_test_corpus_id(staging_repo_id(repo_id, RUN_ID)), (
        "a staged generation of a test corpus is test residue too"
    )


@pytest.mark.parametrize("repo_id", OPERATOR_CORPORA)
def test_operator_corpora_are_never_reap_eligible_plain_or_staged(repo_id: str) -> None:
    assert not is_test_corpus_id(repo_id), repo_id
    assert not is_test_corpus_id(staging_repo_id(repo_id, RUN_ID)), repo_id


@pytest.mark.parametrize(
    "repo_id",
    [
        "",
        "__staging____",  # empty corpus and run
        "__staging__pytest_x",  # no run separator: not a staging id at all
        "operator-live",
        "__staging__operator-live__run",  # staged, but the corpus has no test prefix
        "Pytest_x",  # prefixes are case-sensitive on purpose
    ],
)
def test_unparseable_or_unprefixed_names_are_kept(repo_id: str) -> None:
    assert not is_test_corpus_id(repo_id), repo_id


def test_staged_corpus_of_takes_everything_before_the_last_separator() -> None:
    # Run ids never contain ``__`` (delete_staged_graphs and the Postgres staging
    # sweep rely on the same fact), so a corpus id may.
    assert staged_corpus_of(staging_repo_id("a__b", "run")) == "a__b"
    assert staged_corpus_of(staging_repo_id("pytest_x", RUN_ID)) == "pytest_x"
    assert staged_corpus_of("pytest_x") is None
    assert staged_corpus_of("__staging____") is None
    assert staged_corpus_of("__staging__pytest_x__") is None
    assert staged_corpus_of("__staging____run") is None


def test_qdrant_collection_prefixes_track_the_store_naming_rule() -> None:
    """The reaper's Qdrant match set is derived from the same slug rule the store uses.

    ``corpus_collection_prefix`` rewrites the corpus id before hashing it, so the
    reaper cannot compare raw prefixes; it must map them exactly the way the
    store does. Every test prefix's collections (with any generation suffix)
    match, and no operator corpus's collection does.
    """
    mapped = qdrant_test_collection_prefixes()
    assert len(mapped) == len(TEST_CORPUS_PREFIXES)
    assert all(prefix.startswith("ragweld_chunks_") for prefix in mapped), mapped
    for prefix in TEST_CORPUS_PREFIXES:
        for sample in (f"{prefix}abc", f"{prefix}Abc-Def.ghi", f"{prefix}{'x' * 60}"):
            expected = corpus_collection_prefix(sample)
            assert expected.startswith(mapped), (sample, expected, mapped)
            assert f"{expected}__{RUN_ID}".startswith(mapped)
    for real in OPERATOR_CORPORA:
        assert not corpus_collection_prefix(real).startswith(mapped), real


# --------------------------------------------------------------------------------------
# Guard: every corpus/graph id a test writes to a store must be reap-eligible.
#
# A static scan of ``tests/**/*.py``. It finds each call that leaves a registry row,
# a Qdrant collection or a Neo4j graph behind, resolves the id argument back to the
# string literal or f-string it was built from (through local variables, loop
# targets, comprehension targets and module-local helper functions), and fails when
# that literal's fixed head does not start with a reapable prefix. Ids the scan
# cannot read statically (fixture parameters, values computed at runtime) are
# outside its reach and are not judged; a fixture that creates a corpus is judged
# where it creates it, in its own conftest.
# --------------------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"

# Store-writing entry points and which argument names the corpus (or graph):
# (positional index, keyword name). Positional index None = keyword-only.
_STORE_SINKS: dict[str, tuple[tuple[int | None, str | None], ...]] = {
    # PostgresClient: registry row, scoped config, meta and the generation manifest
    "upsert_corpus": ((0, "repo_id"),),
    "upsert_corpus_config_json": ((0, "repo_id"),),
    "update_corpus_meta": ((0, "repo_id"),),
    "set_generation": ((0, "repo_id"),),
    "promote_staging_index": ((None, "active_repo_id"), (None, "staging_repo_id")),
    # QdrantChunkStore: a physical collection
    "create_generation": ((0, "corpus_id"),),
    # Neo4j graph writers: the id handed to a writer's constructor is the graph it
    # writes under (``write_lexical_graph_with_graphrag`` only builds in memory)
    "ScopedNeo4jWriter": ((None, "repo_id"),),
    "build_semantic_pipeline": ((None, "repo_id"),),
}
_CORPORA_ROUTE = "/api/corpora"
_CORPUS_ID_KEYS = frozenset({"corpus_id", "repo_id"})
_WRITE_CYPHER = ("CREATE", "MERGE")

# Ids a test writes WITHOUT a reapable prefix on purpose, per file: the residue the
# reaper must leave alone. Each one is created and removed by its own test.
_DELIBERATELY_UNREAPABLE: frozenset[tuple[str, str]] = frozenset(
    {
        # The control corpus: proves the reaper never touches unprefixed residue.
        ("tests/integration/test_corpus_reaper_live.py", "reaper-control-"),
    }
)


@dataclass(frozen=True)
class _Head:
    """The fixed leading text of an id literal (`complete` when the whole literal is fixed)."""

    text: str
    complete: bool
    line: int


def _scope_nodes(root: ast.AST) -> list[ast.AST]:
    """Every node inside ``root`` without descending into nested function bodies."""
    found: list[ast.AST] = []
    stack: list[ast.AST] = [root]
    while stack:
        node = stack.pop()
        found.append(node)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
                continue
            stack.append(child)
    return found


def _bindings_in(nodes: list[ast.AST]) -> dict[str, list[ast.expr]]:
    """Name -> the expressions bound to it (assignments, loop and comprehension targets)."""
    bound: dict[str, list[ast.expr]] = {}

    def bind(target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            bound.setdefault(target.id, []).append(value)
        elif isinstance(target, ast.Tuple | ast.List) and isinstance(value, ast.Tuple | ast.List):
            if len(target.elts) == len(value.elts):
                for sub_target, sub_value in zip(target.elts, value.elts, strict=True):
                    bind(sub_target, sub_value)

    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, node.value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            bind(node.target, node.value)
        elif isinstance(node, ast.For | ast.AsyncFor):
            bind(node.target, node.iter)
        elif isinstance(node, ast.comprehension):
            bind(node.target, node.iter)
    return bound


class _Scope:
    """One function (or the module body) with what it binds and what it receives."""

    def __init__(
        self,
        name: str,
        nodes: list[ast.AST],
        module_bindings: dict[str, list[ast.expr]],
        params: frozenset[str],
        fixture_heads: dict[str, list[_Head]],
    ) -> None:
        self.name = name
        self.nodes = nodes
        self.params = params
        self._local = _bindings_in(nodes)
        self._module = module_bindings
        self._fixtures = fixture_heads

    def heads(self, node: ast.expr, _seen: frozenset[str] = frozenset()) -> list[_Head]:
        """The fixed heads ``node`` can evaluate to, or [] when it cannot be read statically."""
        if isinstance(node, ast.Constant):
            return [_Head(node.value, True, node.lineno)] if isinstance(node.value, str) else []
        if isinstance(node, ast.JoinedStr):
            return self._joined_heads(node, _seen)
        if isinstance(node, ast.Name):
            if node.id in _seen:
                return []
            if node.id in self.params:
                # A parameter: a fixture's id when the module defines that fixture,
                # otherwise judged at the call site (helper) or unreadable.
                return self._fixtures.get(node.id, [])
            bound = self._local.get(node.id) or self._module.get(node.id) or []
            seen = _seen | {node.id}
            return [head for value in bound for head in self.heads(value, seen)]
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            return [head for element in node.elts for head in self.heads(element, _seen)]
        return []

    def _joined_heads(self, node: ast.JoinedStr, seen: frozenset[str]) -> list[_Head]:
        heads = [_Head("", True, node.lineno)]
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                heads = [replace(head, text=head.text + part.value) for head in heads]
                continue
            inner = (
                self.heads(part.value, seen)
                if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name)
                else []
            )
            if not inner:
                heads = [replace(head, complete=False) for head in heads]
                break
            heads = [
                _Head(head.text + item.text, head.complete and item.complete, head.line)
                for head in heads
                for item in inner
            ]
            if not all(item.complete for item in inner):
                break
        return [head for head in heads if head.text]


def _callee(call: ast.Call) -> tuple[str, list[ast.expr]]:
    """The called name and its positional arguments (unwrapping ``asyncio.to_thread(fn, ...)``)."""
    func = call.func
    name = (
        func.id
        if isinstance(func, ast.Name)
        else func.attr
        if isinstance(func, ast.Attribute)
        else ""
    )
    positional = list(call.args)
    if name == "to_thread" and positional and isinstance(positional[0], ast.Name):
        return positional[0].id, positional[1:]
    return name, positional


def _constant_text(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and all(
        isinstance(part, ast.Constant) and isinstance(part.value, str) for part in node.values
    ):
        return "".join(str(part.value) for part in node.values if isinstance(part, ast.Constant))
    return None


def _sink_arguments(
    call: ast.Call, local_sinks: dict[str, tuple[tuple[int | None, str | None], ...]]
) -> list[tuple[str, ast.expr]]:
    """(sink label, id expression) for every corpus id ``call`` hands to a store."""
    name, positional = _callee(call)
    keywords = {kw.arg: kw.value for kw in call.keywords if kw.arg}
    found: list[tuple[str, ast.expr]] = []
    for index, keyword in _STORE_SINKS.get(name, ()) + local_sinks.get(name, ()):
        if index is not None and index < len(positional):
            found.append((name, positional[index]))
        elif keyword is not None and keyword in keywords:
            found.append((name, keywords[keyword]))
    if name == "post" and positional:
        route = _constant_text(positional[0]) or ""
        payload = keywords.get("json")
        if route.endswith(_CORPORA_ROUTE) and isinstance(payload, ast.Dict):
            for key, value in zip(payload.keys, payload.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in _CORPUS_ID_KEYS:
                    found.append((f"POST {_CORPORA_ROUTE}", value))
    if name == "run" and positional and "repo_id" in keywords:
        cypher = (_constant_text(positional[0]) or "").upper()
        if any(verb in cypher for verb in _WRITE_CYPHER):
            found.append(("cypher CREATE", keywords["repo_id"]))
    return found


def _parameters(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[int | None, str]]:
    """(positional index or None, name) for every parameter of ``fn``."""
    args = fn.args
    positional = [(index, arg.arg) for index, arg in enumerate(args.posonlyargs + args.args)]
    keyword_only: list[tuple[int | None, str]] = [(None, arg.arg) for arg in args.kwonlyargs]
    return positional + keyword_only


def _is_fixture(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in fn.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = _callee(ast.Call(func=target, args=[], keywords=[]))[0]
        if name == "fixture":
            return True
    return False


def _scopes(
    module: ast.Module,
) -> list[tuple[_Scope, ast.FunctionDef | ast.AsyncFunctionDef | None]]:
    module_nodes = _scope_nodes(module)
    module_bindings = _bindings_in(module_nodes)
    # ``TEST_CORPUS_PREFIX`` is the one imported name fixtures build ids from.
    module_bindings.setdefault("TEST_CORPUS_PREFIX", []).append(
        ast.Constant(value=TEST_CORPUS_PREFIX, lineno=0, col_offset=0)
    )
    fixture_heads: dict[str, list[_Head]] = {}
    scopes: list[tuple[_Scope, ast.FunctionDef | ast.AsyncFunctionDef | None]] = [
        (_Scope("<module>", module_nodes, module_bindings, frozenset(), fixture_heads), None)
    ]
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            params = frozenset(name for _, name in _parameters(node))
            scope = _Scope(node.name, _scope_nodes(node), module_bindings, params, fixture_heads)
            scopes.append((scope, node))
    # A fixture's returned (or yielded) id reaches tests as a parameter of that name.
    for scope, fn in scopes:
        if fn is None or not _is_fixture(fn):
            continue
        for node in scope.nodes:
            if isinstance(node, ast.Return | ast.Yield) and node.value is not None:
                fixture_heads.setdefault(fn.name, []).extend(scope.heads(node.value))
    return scopes


def _corpus_of(head: str) -> str | None:
    """The corpus a head names: itself, or the corpus segment of a ``__staging__`` id."""
    if not head.startswith(STAGING_REPO_PREFIX):
        return head
    corpus = head[len(STAGING_REPO_PREFIX) :].split("__", 1)[0]
    return corpus or None


def unreapable_store_ids_in_source(source: str, relative_path: str) -> list[str]:
    """Every statically readable id ``source`` writes to a store without a reapable prefix."""
    module = ast.parse(source, filename=relative_path)
    scopes = _scopes(module)
    calls = [
        (scope, fn, node)
        for scope, fn in scopes
        for node in scope.nodes
        if isinstance(node, ast.Call)
    ]
    # Module-local helpers whose parameter flows into a sink become sinks themselves,
    # so ``_create_corpus(client, corpus_id)`` is judged at its call sites.
    local_sinks: dict[str, tuple[tuple[int | None, str | None], ...]] = {}
    for _ in range(4):
        before = dict(local_sinks)
        for _scope, fn, call in calls:
            if fn is None:
                continue
            for _label, expr in _sink_arguments(call, local_sinks):
                if isinstance(expr, ast.Name):
                    for index, name in _parameters(fn):
                        if name == expr.id and (index, name) not in local_sinks.get(fn.name, ()):
                            local_sinks[fn.name] = local_sinks.get(fn.name, ()) + ((index, name),)
        if local_sinks == before:
            break
    offenders: set[str] = set()
    for scope, _fn, call in calls:
        for label, expr in _sink_arguments(call, local_sinks):
            for head in scope.heads(expr):
                corpus = _corpus_of(head.text)
                if corpus is None or is_test_corpus_id(corpus):
                    continue
                if any(
                    relative_path == path and head.text.startswith(prefix)
                    for path, prefix in _DELIBERATELY_UNREAPABLE
                ):
                    continue
                offenders.add(f"{relative_path}:{head.line}: {head.text!r} -> {label}")
    return sorted(offenders)


def unreapable_store_ids(tests_root: Path) -> list[str]:
    offenders: list[str] = []
    for path in sorted(tests_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(_REPO_ROOT).as_posix()
        offenders.extend(unreapable_store_ids_in_source(path.read_text(encoding="utf-8"), relative))
    return offenders


_SCANNER_SAMPLE = """\
import asyncio
import uuid
import pytest
from tests.corpus_reaper import TEST_CORPUS_PREFIX


@pytest.fixture
def leaked_corpus() -> str:
    return f"fixture-corpus-{uuid.uuid4().hex[:8]}"


async def _create_corpus(client, corpus_id: str) -> None:
    await client.post("/api/corpora", json={"corpus_id": corpus_id, "name": corpus_id, "path": "."})


async def _plant(neo4j, staged_id: str) -> None:
    await session.run("CREATE (:__Entity__ {repo_id: $repo_id})", repo_id=staged_id)


async def test_sample(client, pg, store, driver, leaked_corpus: str, external_corpus: str) -> None:
    corpus_id = f"qdrant-store-{uuid.uuid4().hex[:8]}"
    graph = f"seed-due-graph-{uuid.uuid4().hex[:6]}"
    other = f"seed-shared-graph-{uuid.uuid4().hex[:6]}"
    kept = f"{TEST_CORPUS_PREFIX}reaper_kept_{uuid.uuid4().hex[:8]}"
    staged = f"__staging__{corpus_id}__{uuid.uuid4().hex}"
    literal_staged = f"__staging__neo4j-live__{uuid.uuid4().hex}"
    corpus_ids = [f"fusion-a-{uuid.uuid4().hex[:8]}", f"fusion-b-{uuid.uuid4().hex[:8]}"]
    await pg.upsert_corpus(corpus_id, name=corpus_id, root_path=".")
    await pg.upsert_corpus(kept, name=kept, root_path=".")
    await pg.upsert_corpus(leaked_corpus, name=leaked_corpus, root_path=".")
    await _create_corpus(client, "replay-corpus")
    await _plant(neo4j, staged)
    for gid in (graph, other):
        await session.run("CREATE (:__Entity__ {repo_id: $repo_id})", repo_id=gid)
    for cid in corpus_ids:
        await store.create_generation(cid, embedding_dim=4)
    await asyncio.to_thread(ScopedNeo4jWriter, driver=driver, repo_id=literal_staged, run_id="r")
    await store.create_generation(external_corpus, embedding_dim=4)
    await session.run("MATCH (n {repo_id: $repo_id}) RETURN n", repo_id="nasa-apollo-11")
    await client.get("/api/corpora/nasa-apollo-11")
"""


def test_store_id_scanner_reads_every_id_form_and_ignores_reads_and_unknowns() -> None:
    """The scanner itself, on one source with every id form the suite uses.

    It must catch literals through locals, loop and comprehension targets, helper
    parameters, module-local fixtures, ``asyncio.to_thread`` writers and staged ids
    (both a literal corpus segment and one built from a local), accept
    ``TEST_CORPUS_PREFIX`` ids, and stay silent on read-only calls and on ids it
    cannot read (a parameter no fixture in the module produces).
    """
    found = unreapable_store_ids_in_source(_SCANNER_SAMPLE, "tests/sample.py")
    assert found == [
        "tests/sample.py:21: 'qdrant-store-' -> upsert_corpus",
        "tests/sample.py:22: 'seed-due-graph-' -> cypher CREATE",
        "tests/sample.py:23: 'seed-shared-graph-' -> cypher CREATE",
        "tests/sample.py:25: '__staging__qdrant-store-' -> _plant",
        "tests/sample.py:26: '__staging__neo4j-live__' -> ScopedNeo4jWriter",
        "tests/sample.py:27: 'fusion-a-' -> create_generation",
        "tests/sample.py:27: 'fusion-b-' -> create_generation",
        "tests/sample.py:31: 'replay-corpus' -> _create_corpus",
        "tests/sample.py:9: 'fixture-corpus-' -> upsert_corpus",
    ], found
    renamed = _SCANNER_SAMPLE
    for old, new in (
        ("qdrant-store-", "pytest_qdrant_store_"),
        ("seed-due-graph-", "pytest_seed_due_graph_"),
        ("seed-shared-graph-", "pytest_seed_shared_graph_"),
        ("neo4j-live", "pytest_neo4j_live"),
        ("fusion-a-", "pytest_fusion_a_"),
        ("fusion-b-", "pytest_fusion_b_"),
        ("replay-corpus", "pytest_replay_corpus"),
        ("fixture-corpus-", "pytest_fixture_corpus_"),
    ):
        renamed = renamed.replace(old, new)
    assert unreapable_store_ids_in_source(renamed, "tests/sample.py") == []


def test_every_id_a_test_writes_to_a_store_is_reap_eligible() -> None:
    """No test under ``tests/`` may write a corpus or graph the reaper cannot reap.

    Fix an offender by renaming the id to start with ``TEST_CORPUS_PREFIX`` (keep
    the descriptive remainder), never by widening ``TEST_CORPUS_PREFIXES``: every
    prefix added there is one the reaper will delete from the live stores.
    """
    offenders = unreapable_store_ids(_TESTS_ROOT)
    assert not offenders, "ids written to a store without a reapable prefix:\n" + "\n".join(
        offenders
    )
