"""AST code graph: real tree-sitter parses of real and synthetic sources, no mocks."""

from __future__ import annotations

from pathlib import Path

from server.indexing.code_graph import (
    CODE_GRAPH_LANGUAGES,
    ENTITY_CLASS,
    ENTITY_FUNCTION,
    ENTITY_MODULE,
    REL_CALLS,
    REL_CONTAINS,
    REL_IMPORTS,
    REL_INHERITS,
    extract_code_graph,
    module_id,
    symbol_id,
)
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def _chunks(file_path: str, source: str, *, lines_per_chunk: int) -> list[Chunk]:
    total = source.count("\n") + 1
    out: list[Chunk] = []
    start = 1
    while start <= total:
        end = min(total, start + lines_per_chunk - 1)
        body = "\n".join(source.splitlines()[start - 1 : end])
        out.append(
            Chunk(
                chunk_id=f"{file_path}:{start}-{end}:{start}",
                content=body,
                file_path=file_path,
                start_line=start,
                end_line=end,
                language="python" if file_path.endswith(".py") else "typescript",
            )
        )
        start = end + 1
    return out


def _rels(result, rel_type: str) -> set[tuple[str, str]]:
    return {(r.start_node_id, r.end_node_id) for r in result.graph.relationships if r.type == rel_type}


def _write_python_fixture(root: Path) -> tuple[str, str]:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "a.py").write_text(
        "class Base:\n    pass\n\n\ndef helper(x):\n    return x\n",
        encoding="utf-8",
    )
    b_source = (
        "import os\n"
        "from pkg.a import Base, helper as h\n"
        "from .a import Base as AliasBase\n"
        "from typing import Any\n"
        "\n"
        "\n"
        "class Child(Base):\n"
        "    def run(self, x):\n"
        "        return h(x) + self.go()\n"
        "\n"
        "    def go(self):\n"
        "        return other(1)\n"
        "\n"
        "\n"
        "def other(n):\n"
        "    return os.getcwd()\n"
    )
    (root / "pkg" / "b.py").write_text(b_source, encoding="utf-8")
    return "pkg/b.py", b_source


def test_python_graph_resolves_imports_inheritance_and_calls_inside_the_corpus(tmp_path: Path) -> None:
    file_path, source = _write_python_fixture(tmp_path)
    cfg = TriBridConfig()
    chunks = _chunks(file_path, source, lines_per_chunk=8)

    result = extract_code_graph(
        repo_id="code", run_id="run-1", file_path=file_path, source=source, language="python", chunks=chunks, cfg=cfg, root=tmp_path
    )

    mod = module_id("code", file_path)
    child = symbol_id("code", file_path, "Child")
    run = symbol_id("code", file_path, "Child.run")
    go = symbol_id("code", file_path, "Child.go")
    other = symbol_id("code", file_path, "other")
    a_mod = module_id("code", "pkg/a.py")
    a_base = symbol_id("code", "pkg/a.py", "Base")
    a_helper = symbol_id("code", "pkg/a.py", "helper")

    labels = {n.id: n.label for n in result.graph.nodes}
    assert labels[mod] == ENTITY_MODULE
    assert labels[child] == ENTITY_CLASS
    assert labels[run] == ENTITY_FUNCTION and labels[go] == ENTITY_FUNCTION and labels[other] == ENTITY_FUNCTION
    # Cross-file targets are emitted as unifiable nodes with the same ids the defining file will use.
    assert labels[a_mod] == ENTITY_MODULE and labels[a_base] == ENTITY_CLASS and labels[a_helper] == ENTITY_FUNCTION

    assert _rels(result, REL_CONTAINS) == {(mod, child), (child, run), (child, go), (mod, other)}
    assert _rels(result, REL_IMPORTS) == {(mod, a_mod)}  # os / typing are outside the corpus
    assert _rels(result, REL_INHERITS) == {(child, a_base)}
    assert _rels(result, REL_CALLS) == {(run, a_helper), (run, go), (go, other)}
    assert result.unresolved_imports == ["os", "typing"]
    assert result.unresolved_calls == ["other -> getcwd"]
    assert result.unresolved_bases == []

    in_chunk = {(r.start_node_id, r.end_node_id) for r in result.graph.relationships if r.type == result.lexical_graph_config.node_to_chunk_relationship_type}
    assert (child, f"{file_path}:1-8:1") in in_chunk  # class Child starts on line 7
    assert (go, f"{file_path}:9-16:9") in in_chunk  # def go on line 11
    assert (other, f"{file_path}:9-16:9") in in_chunk
    assert (mod, f"{file_path}:1-8:1") in in_chunk

    props = {n.id: n.properties for n in result.graph.nodes}
    assert props[run]["kind"] == "method" and props[run]["start_line"] == 8 and props[run]["signature"] == "def run(self, x):"
    assert props[child]["entity_type"] == ENTITY_CLASS and props[child]["repo_id"] == "code" and props[child]["run_id"] == "run-1"
    weights = {r.type: r.properties["weight"] for r in result.graph.relationships if "weight" in r.properties}
    assert weights[REL_CALLS] == cfg.graph_indexing.ast_calls_weight
    assert weights[REL_INHERITS] == cfg.graph_indexing.ast_inherits_weight


def test_typescript_graph_handles_aliases_arrow_functions_and_external_bases(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "client.ts").write_text("export function api(path: string) {\n  return path;\n}\n", encoding="utf-8")
    source = (
        'import { api as call } from "./client";\n'
        'import { create } from "zustand";\n'
        "export class Store extends Base {\n"
        "  run(x: string) {\n"
        "    return call(x) + this.reset();\n"
        "  }\n"
        "  reset() {\n"
        "    return 0;\n"
        "  }\n"
        "}\n"
        "export const useStore = (s: number) => helper(s);\n"
        "function helper(n: number) {\n"
        "  return create(n);\n"
        "}\n"
    )
    file_path = "src/store.ts"
    (tmp_path / file_path).write_text(source, encoding="utf-8")
    cfg = TriBridConfig()

    result = extract_code_graph(
        repo_id="web", run_id="r", file_path=file_path, source=source, language="typescript", chunks=_chunks(file_path, source, lines_per_chunk=6), cfg=cfg, root=tmp_path
    )

    mod = module_id("web", file_path)
    store = symbol_id("web", file_path, "Store")
    run = symbol_id("web", file_path, "Store.run")
    reset = symbol_id("web", file_path, "Store.reset")
    use_store = symbol_id("web", file_path, "useStore")
    helper = symbol_id("web", file_path, "helper")
    client_api = symbol_id("web", "src/client.ts", "api")

    assert {s.qualname for s in result.symbols} == {"Store", "Store.run", "Store.reset", "useStore", "helper"}
    assert _rels(result, REL_CONTAINS) == {(mod, store), (store, run), (store, reset), (mod, use_store), (mod, helper)}
    assert _rels(result, REL_IMPORTS) == {(mod, module_id("web", "src/client.ts"))}
    assert _rels(result, REL_CALLS) == {(run, client_api), (run, reset), (use_store, helper)}
    assert result.unresolved_imports == ["zustand"]
    assert result.unresolved_bases == ["Store -> Base"]
    assert result.unresolved_calls == ["helper -> create"]


def test_real_repo_file_traces_py_yields_the_trace_store_class_and_its_imports() -> None:
    file_path = "server/services/traces.py"
    source = (REPO_ROOT / file_path).read_text(encoding="utf-8")
    cfg = TriBridConfig()
    chunks = _chunks(file_path, source, lines_per_chunk=60)

    result = extract_code_graph(
        repo_id="ragweld_code", run_id="r", file_path=file_path, source=source, language="python", chunks=chunks, cfg=cfg, root=REPO_ROOT
    )

    qualnames = {s.qualname for s in result.symbols}
    assert "TraceStore" in qualnames
    assert "TraceStore.start" in qualnames and "TraceStore.add_event" in qualnames
    assert "_now_ms" in qualnames
    imports = _rels(result, REL_IMPORTS)
    assert (module_id("ragweld_code", file_path), module_id("ragweld_code", "server/models/tribrid_config_model.py")) in imports
    # Every symbol is anchored to exactly one chunk by its definition line.
    in_chunk_type = result.lexical_graph_config.node_to_chunk_relationship_type
    anchored = {r.start_node_id for r in result.graph.relationships if r.type == in_chunk_type}
    for s in result.symbols:
        assert symbol_id("ragweld_code", file_path, s.qualname) in anchored, s.qualname
    assert result.relationship_count > len(result.symbols)


def test_unsupported_language_produces_an_empty_graph(tmp_path: Path) -> None:
    result = extract_code_graph(
        repo_id="x", run_id="r", file_path="README.md", source="# hi\n", language="markdown", chunks=[], cfg=TriBridConfig(), root=tmp_path
    )
    assert result.graph.nodes == [] and result.graph.relationships == [] and result.symbols == []
    assert "markdown" not in CODE_GRAPH_LANGUAGES


def test_extraction_is_deterministic(tmp_path: Path) -> None:
    file_path, source = _write_python_fixture(tmp_path)
    cfg = TriBridConfig()
    a = extract_code_graph(repo_id="code", run_id="r", file_path=file_path, source=source, language="python", chunks=_chunks(file_path, source, lines_per_chunk=8), cfg=cfg, root=tmp_path)
    b = extract_code_graph(repo_id="code", run_id="r", file_path=file_path, source=source, language="python", chunks=_chunks(file_path, source, lines_per_chunk=8), cfg=cfg, root=tmp_path)
    assert [(n.id, n.label, n.properties) for n in a.graph.nodes] == [(n.id, n.label, n.properties) for n in b.graph.nodes]
    assert [(r.start_node_id, r.end_node_id, r.type, r.properties) for r in a.graph.relationships] == [
        (r.start_node_id, r.end_node_id, r.type, r.properties) for r in b.graph.relationships
    ]
