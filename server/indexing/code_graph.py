"""AST code graph for the Neo4j GraphRAG lane.

Extracts module / class / function entities and their `contains`, `inherits`,
`imports` and `calls` relationships from Python, TypeScript and JavaScript
sources with tree-sitter, links every entity to the chunk it is defined in
(`IN_CHUNK`), and returns a package-shaped ``Neo4jGraph`` so the existing
``Neo4jClient.upsert_graphrag_graph`` writes it exactly like the semantic KG.

Entity ids are corpus-relative (`path` for a module, `path::qualname` for a
symbol); uniqueness in Neo4j is scoped by ``repo_id`` so the staging id never
leaks into an entity id. Relationships whose target lives in another file are
*deferred*: they are returned separately and written once, after every file
of the run has been indexed, through a relationship-only upsert that MATCHes
both endpoints. No placeholder node is ever created for a target, so an entity
cannot arrive under two labels (a call to an imported class is a call to a
``class`` node, not to a guessed ``function`` node - the first live run failed
on exactly that uniqueness constraint).

Resolution is deliberately conservative: a name that cannot be tied to a
definition in this file or to an explicit import that resolves inside the
corpus produces no edge and is counted as unresolved rather than guessed.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from neo4j_graphrag.components.types import (
    LexicalGraphConfig,
    Neo4jGraph,
    Neo4jNode,
    Neo4jRelationship,
)
from tree_sitter import Language, Node, Parser

from server.indexing.official_graphrag import _annotate_graph, _lexical_graph_config
from server.models.index import Chunk
from server.models.tribrid_config_model import TriBridConfig

ENTITY_MODULE = "module"
ENTITY_CLASS = "class"
ENTITY_FUNCTION = "function"

REL_CONTAINS = "contains"
REL_INHERITS = "inherits"
REL_IMPORTS = "imports"
REL_CALLS = "calls"

CODE_GRAPH_LANGUAGES: frozenset[str] = frozenset({"python", "typescript", "javascript"})

_TS_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts")
_TS_INDEX_FILES = ("index.ts", "index.tsx", "index.js", "index.jsx")


def module_id(file_path: str) -> str:
    return file_path


def symbol_id(file_path: str, qualname: str) -> str:
    return f"{file_path}::{qualname}"


@dataclass
class CodeSymbol:
    qualname: str
    name: str
    kind: str  # module | class | function | method
    start_line: int
    end_line: int
    signature: str
    parent_qualname: str | None = None

    @property
    def label(self) -> str:
        if self.kind == "class":
            return ENTITY_CLASS
        if self.kind == "module":
            return ENTITY_MODULE
        return ENTITY_FUNCTION


@dataclass
class CodeGraphResult:
    graph: Neo4jGraph
    lexical_graph_config: LexicalGraphConfig
    symbols: list[CodeSymbol]
    # Edges whose target is defined in another file. Written after the whole
    # run through a relationship-only upsert; missing targets simply match
    # nothing.
    deferred_relationships: list[Neo4jRelationship]
    unresolved_imports: list[str] = field(default_factory=list)
    unresolved_calls: list[str] = field(default_factory=list)
    unresolved_bases: list[str] = field(default_factory=list)

    @property
    def relationship_count(self) -> int:
        return len(self.graph.relationships) + len(self.deferred_relationships)


# ------------------------------------------------------------------- parsers


def _language_for(language: str, file_path: str) -> Language | None:
    if language == "python":
        import tree_sitter_python  # noqa: PLC0415

        return Language(tree_sitter_python.language())
    if language == "typescript":
        import tree_sitter_typescript  # noqa: PLC0415

        if file_path.endswith(".tsx"):
            return Language(tree_sitter_typescript.language_tsx())
        return Language(tree_sitter_typescript.language_typescript())
    if language == "javascript":
        import tree_sitter_javascript  # noqa: PLC0415

        return Language(tree_sitter_javascript.language())
    return None


def _text(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


def _first_line(node: Node) -> str:
    return _text(node).splitlines()[0].strip()[:200] if _text(node) else ""


def _walk(node: Node) -> Iterator[Node]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))


# ---------------------------------------------------------------- resolution


def _resolve_python_module(root: Path, current_file: str, module: str, level: int) -> str | None:
    """`a.b.c` / `.sibling` / `..pkg.mod` -> corpus-relative path, or None if not in the corpus."""
    if level > 0:
        base = Path(current_file).parent
        for _ in range(level - 1):
            base = base.parent
        parts = [p for p in module.split(".") if p]
        candidate_base = base.joinpath(*parts) if parts else base
    else:
        parts = [p for p in module.split(".") if p]
        if not parts:
            return None
        candidate_base = Path(*parts)
    for candidate in (candidate_base.with_suffix(".py"), candidate_base / "__init__.py"):
        if (root / candidate).is_file():
            return candidate.as_posix()
    return None


def _resolve_ts_import(root: Path, current_file: str, spec: str) -> str | None:
    """Relative specifiers only (`./x`, `../y`); bare package names are external."""
    if not spec.startswith("."):
        return None
    base = Path(current_file).parent / spec
    candidates = [base]
    candidates += [base.with_name(base.name + suffix) for suffix in _TS_SUFFIXES]
    candidates += [base / name for name in _TS_INDEX_FILES]
    for candidate in candidates:
        normalized = Path(*[p for p in candidate.parts if p != "."])
        try:
            resolved = (root / normalized).resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if (root / resolved).is_file():
            return resolved.as_posix()
    return None


# ------------------------------------------------------------------ python


@dataclass
class _FileFacts:
    symbols: list[CodeSymbol]
    imported_modules: list[str]  # resolved corpus paths
    imported_names: dict[str, tuple[str, str]]  # local name -> (module path, original name)
    inherits: list[tuple[str, str]]  # (class qualname, base name as written)
    calls: list[tuple[str, str]]  # (caller qualname, callee name as written)
    unresolved_imports: list[str]


def _unwrap_decorated(node: Node) -> Node:
    if node.type == "decorated_definition":
        definition = node.child_by_field_name("definition")
        if definition is not None:
            return definition
    return node


def _python_facts(tree_root: Node, *, root: Path, file_path: str) -> _FileFacts:
    facts = _FileFacts([], [], {}, [], [], [])

    def add_import_module(module: str, level: int) -> str | None:
        resolved = _resolve_python_module(root, file_path, module, level)
        if resolved is None:
            facts.unresolved_imports.append(("." * level) + module)
            return None
        if resolved not in facts.imported_modules:
            facts.imported_modules.append(resolved)
        return resolved

    for node in _walk(tree_root):
        if node.type == "import_statement":
            for child in node.children:
                if child.type == "dotted_name":
                    add_import_module(_text(child), 0)
                elif child.type == "aliased_import":
                    add_import_module(_text(child.child_by_field_name("name")), 0)
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            level = 0
            module = ""
            if module_node is not None and module_node.type == "relative_import":
                for child in module_node.children:
                    if child.type == "import_prefix":
                        level = len(_text(child))
                    elif child.type == "dotted_name":
                        module = _text(child)
            elif module_node is not None:
                module = _text(module_node)
            resolved = add_import_module(module, level)
            for name_node in node.children_by_field_name("name"):
                if name_node.type == "aliased_import":
                    original = _text(name_node.child_by_field_name("name"))
                    local = _text(name_node.child_by_field_name("alias")) or original
                else:
                    original = local = _text(name_node)
                if resolved is not None and local:
                    facts.imported_names[local] = (resolved, original.split(".")[-1])

    def visit_definitions(container: Node, parent_qualname: str | None) -> None:
        for raw in container.children:
            node = _unwrap_decorated(raw)
            if node.type == "class_definition":
                name = _text(node.child_by_field_name("name"))
                qualname = f"{parent_qualname}.{name}" if parent_qualname else name
                facts.symbols.append(
                    CodeSymbol(qualname, name, "class", node.start_point[0] + 1, node.end_point[0] + 1, _first_line(node), parent_qualname)
                )
                superclasses = node.child_by_field_name("superclasses")
                if superclasses is not None:
                    for base in superclasses.children:
                        if base.type in ("identifier", "attribute"):
                            facts.inherits.append((qualname, _text(base).split(".")[-1]))
                body = node.child_by_field_name("body")
                if body is not None:
                    visit_definitions(body, qualname)
            elif node.type == "function_definition":
                name = _text(node.child_by_field_name("name"))
                qualname = f"{parent_qualname}.{name}" if parent_qualname else name
                kind = "method" if parent_qualname and any(s.qualname == parent_qualname and s.kind == "class" for s in facts.symbols) else "function"
                facts.symbols.append(
                    CodeSymbol(qualname, name, kind, node.start_point[0] + 1, node.end_point[0] + 1, _first_line(node), parent_qualname)
                )
                body = node.child_by_field_name("body")
                if body is not None:
                    for inner in _walk(body):
                        if inner.type == "call":
                            fn = inner.child_by_field_name("function")
                            if fn is None:
                                continue
                            if fn.type == "identifier":
                                facts.calls.append((qualname, _text(fn)))
                            elif fn.type == "attribute":
                                attr = fn.child_by_field_name("attribute")
                                obj = fn.child_by_field_name("object")
                                callee = _text(attr)
                                if obj is not None and _text(obj) in ("self", "cls") and parent_qualname:
                                    callee = f"{parent_qualname}.{callee}"
                                facts.calls.append((qualname, callee))

    visit_definitions(tree_root, None)
    return facts


# --------------------------------------------------------------- typescript


def _ts_facts(tree_root: Node, *, root: Path, file_path: str) -> _FileFacts:
    facts = _FileFacts([], [], {}, [], [], [])

    def record_calls(qualname: str, body: Node | None, parent_qualname: str | None) -> None:
        if body is None:
            return
        for inner in _walk(body):
            if inner.type != "call_expression":
                continue
            fn = inner.child_by_field_name("function")
            if fn is None:
                continue
            if fn.type == "identifier":
                facts.calls.append((qualname, _text(fn)))
            elif fn.type == "member_expression":
                prop = fn.child_by_field_name("property")
                obj = fn.child_by_field_name("object")
                callee = _text(prop)
                if obj is not None and _text(obj) == "this" and parent_qualname:
                    callee = f"{parent_qualname}.{callee}"
                facts.calls.append((qualname, callee))

    def add_symbol(node: Node, name: str, kind: str, parent_qualname: str | None) -> str:
        qualname = f"{parent_qualname}.{name}" if parent_qualname else name
        facts.symbols.append(
            CodeSymbol(qualname, name, kind, node.start_point[0] + 1, node.end_point[0] + 1, _first_line(node), parent_qualname)
        )
        return qualname

    def visit(container: Node, parent_qualname: str | None) -> None:
        for raw in container.children:
            node = raw
            if node.type == "export_statement":
                declaration = node.child_by_field_name("declaration")
                if declaration is None:
                    declaration = next((c for c in node.children if c.type.endswith("_declaration") or c.type == "function_declaration"), None)
                if declaration is None:
                    continue
                node = declaration
            if node.type == "import_statement":
                source = _text(node.child_by_field_name("source")).strip("\"'`")
                resolved = _resolve_ts_import(root, file_path, source)
                if resolved is None:
                    facts.unresolved_imports.append(source)
                    continue
                if resolved not in facts.imported_modules:
                    facts.imported_modules.append(resolved)
                for inner in _walk(node):
                    if inner.type == "import_specifier":
                        original = _text(inner.child_by_field_name("name"))
                        alias = _text(inner.child_by_field_name("alias")) or original
                        if original:
                            facts.imported_names[alias] = (resolved, original)
                    elif inner.type == "import_clause":
                        default = next((c for c in inner.children if c.type == "identifier"), None)
                        if default is not None:
                            facts.imported_names[_text(default)] = (resolved, "default")
            elif node.type in ("class_declaration", "abstract_class_declaration"):
                name = _text(node.child_by_field_name("name"))
                qualname = add_symbol(node, name, "class", parent_qualname)
                for heritage in node.children:
                    if heritage.type == "class_heritage":
                        for clause in heritage.children:
                            if clause.type == "extends_clause":
                                for base in clause.children:
                                    if base.type in ("identifier", "member_expression", "type_identifier"):
                                        facts.inherits.append((qualname, _text(base).split(".")[-1]))
                body = node.child_by_field_name("body")
                if body is not None:
                    for member in body.children:
                        if member.type == "method_definition":
                            mname = _text(member.child_by_field_name("name"))
                            mqual = add_symbol(member, mname, "method", qualname)
                            record_calls(mqual, member.child_by_field_name("body"), qualname)
            elif node.type == "function_declaration":
                name = _text(node.child_by_field_name("name"))
                qualname = add_symbol(node, name, "function", parent_qualname)
                record_calls(qualname, node.child_by_field_name("body"), None)
            elif node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in node.children:
                    if declarator.type != "variable_declarator":
                        continue
                    value = declarator.child_by_field_name("value")
                    if value is None or value.type not in ("arrow_function", "function_expression", "function"):
                        continue
                    name = _text(declarator.child_by_field_name("name"))
                    qualname = add_symbol(declarator, name, "function", parent_qualname)
                    record_calls(qualname, value.child_by_field_name("body") or value, None)

    visit(tree_root, None)
    return facts


# --------------------------------------------------------------------- graph


def extract_code_graph(
    *,
    repo_id: str,
    run_id: str,
    file_path: str,
    source: str,
    language: str | None,
    chunks: list[Chunk],
    cfg: TriBridConfig,
    root: Path,
) -> CodeGraphResult:
    lexical_graph_config = _lexical_graph_config()
    lang = _language_for(str(language or ""), file_path)
    if lang is None:
        return CodeGraphResult(Neo4jGraph(nodes=[], relationships=[]), lexical_graph_config, [], [])

    tree = Parser(lang).parse(source.encode("utf-8"))
    facts = (
        _python_facts(tree.root_node, root=root, file_path=file_path)
        if language == "python"
        else _ts_facts(tree.root_node, root=root, file_path=file_path)
    )

    weights = cfg.graph_indexing
    mod_id = module_id(file_path)
    module_end_line = max(1, source.count("\n") + 1)

    nodes: dict[str, Neo4jNode] = {}
    relationships: list[Neo4jRelationship] = []
    deferred: list[Neo4jRelationship] = []

    def rel(start: str, end: str, rel_type: str, weight: float, *, cross_file: bool) -> None:
        item = Neo4jRelationship(
            start_node_id=start,
            end_node_id=end,
            type=rel_type,
            properties={"weight": float(weight), "source": "ast", "file_path": file_path},
        )
        (deferred if cross_file else relationships).append(item)

    nodes[mod_id] = Neo4jNode(
        id=mod_id,
        label=ENTITY_MODULE,
        properties={
            "name": Path(file_path).name,
            "kind": "module",
            "file_path": file_path,
            "language": str(language),
            "start_line": 1,
            "end_line": module_end_line,
            "source": "ast",
        },
    )

    local_by_qualname = {s.qualname: s for s in facts.symbols}
    local_by_name: dict[str, list[CodeSymbol]] = {}
    for s in facts.symbols:
        local_by_name.setdefault(s.name, []).append(s)

    for s in facts.symbols:
        sid = symbol_id(file_path, s.qualname)
        if sid in nodes:
            continue  # duplicate definition (e.g. under TYPE_CHECKING); the first one wins
        nodes[sid] = Neo4jNode(
            id=sid,
            label=s.label,
            properties={
                "name": s.name,
                "kind": s.kind,
                "qualname": s.qualname,
                "file_path": file_path,
                "language": str(language),
                "start_line": s.start_line,
                "end_line": s.end_line,
                "signature": s.signature,
                "source": "ast",
            },
        )
        parent_id = symbol_id(file_path, s.parent_qualname) if s.parent_qualname else mod_id
        rel(parent_id, sid, REL_CONTAINS, weights.ast_contains_weight, cross_file=False)

    for imported in facts.imported_modules:
        rel(mod_id, module_id(imported), REL_IMPORTS, weights.ast_imports_weight, cross_file=True)

    def resolve_name(name: str, *, kinds: tuple[str, ...]) -> tuple[str, bool] | None:
        """(target id, cross_file) for a name: this file's definitions first, then explicit imports."""
        if name in local_by_qualname and local_by_qualname[name].kind in kinds:
            return symbol_id(file_path, name), False
        locals_ = [s for s in local_by_name.get(name, []) if s.kind in kinds]
        if len(locals_) == 1:
            return symbol_id(file_path, locals_[0].qualname), False
        imported = facts.imported_names.get(name)
        if imported is not None:
            target_path, original = imported
            return symbol_id(target_path, original), True
        return None

    unresolved_bases: list[str] = []
    for class_qualname, base in facts.inherits:
        target = resolve_name(base, kinds=("class",))
        if target is None:
            unresolved_bases.append(f"{class_qualname} -> {base}")
            continue
        rel(symbol_id(file_path, class_qualname), target[0], REL_INHERITS, weights.ast_inherits_weight, cross_file=target[1])

    unresolved_calls: list[str] = []
    seen_calls: set[tuple[str, str]] = set()
    for caller, callee in facts.calls:
        # A call to a class name is an instantiation: still a `calls` edge, to the class node.
        target = resolve_name(callee, kinds=("function", "method", "class"))
        if target is None:
            unresolved_calls.append(f"{caller} -> {callee}")
            continue
        caller_id = symbol_id(file_path, caller)
        if (caller_id, target[0]) in seen_calls or caller_id == target[0]:
            continue
        seen_calls.add((caller_id, target[0]))
        rel(caller_id, target[0], REL_CALLS, weights.ast_calls_weight, cross_file=target[1])

    ordered_chunks = sorted(chunks, key=lambda ch: (int(ch.start_line or 0), str(ch.chunk_id)))
    in_chunk = lexical_graph_config.node_to_chunk_relationship_type

    def chunk_for_line(line: int) -> Chunk | None:
        for ch in ordered_chunks:
            if int(ch.start_line or 0) <= line <= int(ch.end_line or 0):
                return ch
        return None

    if ordered_chunks:
        relationships.append(
            Neo4jRelationship(start_node_id=mod_id, end_node_id=str(ordered_chunks[0].chunk_id), type=in_chunk, properties={"source": "ast"})
        )
    for s in facts.symbols:
        ch = chunk_for_line(s.start_line)
        if ch is not None:
            relationships.append(
                Neo4jRelationship(
                    start_node_id=symbol_id(file_path, s.qualname),
                    end_node_id=str(ch.chunk_id),
                    type=in_chunk,
                    properties={"source": "ast", "start_line": s.start_line},
                )
            )

    graph = _annotate_graph(
        Neo4jGraph(nodes=list(nodes.values()), relationships=relationships),
        repo_id=repo_id,
        run_id=run_id,
        lexical_graph_config=lexical_graph_config,
    )
    for item in deferred:
        item.properties = {**dict(item.properties or {}), "repo_id": repo_id, "run_id": run_id}
    return CodeGraphResult(
        graph=graph,
        lexical_graph_config=lexical_graph_config,
        symbols=facts.symbols,
        deferred_relationships=deferred,
        unresolved_imports=facts.unresolved_imports,
        unresolved_calls=unresolved_calls,
        unresolved_bases=unresolved_bases,
    )
