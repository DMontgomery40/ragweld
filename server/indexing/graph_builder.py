from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass

from server.db.neo4j import Neo4jClient
from server.models.graph import Entity, GraphStats, Relationship
from server.models.index import Chunk


@dataclass(frozen=True)
class _ParsedEntity:
    entity: Entity
    # Parent entity_id for containment relationships (module -> class/function, class -> method)
    parent_id: str | None


class GraphBuilder:
    """Build a lightweight code knowledge graph and store it in Neo4j.

    This implementation is intentionally conservative:
    - Extracts module/class/function entities from Python AST
    - Adds simple containment and import relationships
    - Leaves deeper semantic extraction (LLM descriptions, cross-file resolution) for later
    """

    def __init__(self, neo4j: Neo4jClient | None):
        self.neo4j = neo4j

    async def build_graph_for_files(
        self,
        repo_id: str,
        files: list[tuple[str, str]],
        *,
        batch_size: int = 100,
    ) -> GraphStats:
        if self.neo4j is None:
            raise ValueError("neo4j client is required to build and persist a graph")
        bs = max(1, int(batch_size))
        entities_batch: list[Entity] = []
        rels_batch: list[Relationship] = []

        for file_path, content in files:
            file_entities, file_rels = self._parse_python_file(repo_id, file_path, content)
            entities_batch.extend(file_entities)
            rels_batch.extend(file_rels)

            if len(entities_batch) >= bs or len(rels_batch) >= bs:
                await self.neo4j.upsert_entities(repo_id, entities_batch)
                await self.neo4j.upsert_relationships(repo_id, rels_batch)
                entities_batch.clear()
                rels_batch.clear()

        if entities_batch:
            await self.neo4j.upsert_entities(repo_id, entities_batch)
        if rels_batch:
            await self.neo4j.upsert_relationships(repo_id, rels_batch)

        await self.neo4j.detect_communities(repo_id)
        return await self.neo4j.get_graph_stats(repo_id)

    def _parse_python_file(self, repo_id: str, file_path: str, content: str) -> tuple[list[Entity], list[Relationship]]:
        """Parse a Python file and return entities + relationships."""
        module_id = self._stable_id(repo_id, file_path, "module", file_path)
        entities: dict[str, Entity] = {
            module_id: Entity(
                entity_id=module_id,
                name=file_path,
                entity_type="module",
                file_path=file_path,
                description=None,
                properties={},
            )
        }
        rels: list[Relationship] = []

        try:
            tree = ast.parse(content or "", filename=file_path)
        except Exception:
            return list(entities.values()), rels

        builder = self

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.current_class_id: str | None = None
                self.current_function_id: str | None = None

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                class_id = builder._stable_id(repo_id, file_path, "class", node.name)
                entities[class_id] = Entity(
                    entity_id=class_id,
                    name=node.name,
                    entity_type="class",
                    file_path=file_path,
                    description=None,
                    properties={
                        "start_line": getattr(node, "lineno", None),
                        "end_line": getattr(node, "end_lineno", None),
                    },
                )
                rels.append(
                    Relationship(
                        source_id=module_id,
                        target_id=class_id,
                        relation_type="contains",
                        weight=1.0,
                        properties={},
                    )
                )

                # Inheritance edges (by name, best-effort)
                for base in node.bases or []:
                    base_name = builder._format_name(base)
                    if not base_name:
                        continue
                    base_id = builder._stable_id(repo_id, "", "class", base_name)
                    entities.setdefault(
                        base_id,
                        Entity(
                            entity_id=base_id,
                            name=base_name,
                            entity_type="class",
                            file_path=None,
                            description=None,
                            properties={},
                        ),
                    )
                    rels.append(
                        Relationship(
                            source_id=class_id,
                            target_id=base_id,
                            relation_type="inherits",
                            weight=1.0,
                            properties={},
                        )
                    )

                prev = self.current_class_id
                self.current_class_id = class_id
                self.generic_visit(node)
                self.current_class_id = prev

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                fn_id = builder._stable_id(repo_id, file_path, "function", node.name)
                entities[fn_id] = Entity(
                    entity_id=fn_id,
                    name=node.name,
                    entity_type="function",
                    file_path=file_path,
                    description=None,
                    properties={
                        "start_line": getattr(node, "lineno", None),
                        "end_line": getattr(node, "end_lineno", None),
                    },
                )

                parent = self.current_class_id or module_id
                rels.append(
                    Relationship(
                        source_id=parent,
                        target_id=fn_id,
                        relation_type="contains",
                        weight=1.0,
                        properties={},
                    )
                )

                prev_fn = self.current_function_id
                self.current_function_id = fn_id
                self.generic_visit(node)
                self.current_function_id = prev_fn

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                # Treat async defs like functions
                self.visit_FunctionDef(node)  # type: ignore[arg-type]

            def visit_Import(self, node: ast.Import) -> None:
                for alias in node.names or []:
                    mod = alias.name
                    if not mod:
                        continue
                    mod_id = builder._stable_id(repo_id, "", "module", mod)
                    entities.setdefault(
                        mod_id,
                        Entity(
                            entity_id=mod_id,
                            name=mod,
                            entity_type="module",
                            file_path=None,
                            description=None,
                            properties={},
                        ),
                    )
                    rels.append(
                        Relationship(
                            source_id=module_id,
                            target_id=mod_id,
                            relation_type="imports",
                            weight=1.0,
                            properties={},
                        )
                    )

            def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
                mod = node.module or ""
                if not mod:
                    return
                mod_id = builder._stable_id(repo_id, "", "module", mod)
                entities.setdefault(
                    mod_id,
                    Entity(
                        entity_id=mod_id,
                        name=mod,
                        entity_type="module",
                        file_path=None,
                        description=None,
                        properties={},
                    ),
                )
                rels.append(
                    Relationship(
                        source_id=module_id,
                        target_id=mod_id,
                        relation_type="imports",
                        weight=1.0,
                        properties={},
                    )
                )

            def visit_Call(self, node: ast.Call) -> None:
                if not self.current_function_id:
                    return
                callee = builder._format_name(node.func)
                if not callee:
                    return
                callee_id = builder._stable_id(repo_id, "", "function", callee)
                entities.setdefault(
                    callee_id,
                    Entity(
                        entity_id=callee_id,
                        name=callee,
                        entity_type="function",
                        file_path=None,
                        description=None,
                        properties={},
                    ),
                )
                rels.append(
                    Relationship(
                        source_id=self.current_function_id,
                        target_id=callee_id,
                        relation_type="calls",
                        weight=1.0,
                        properties={},
                    )
                )
                self.generic_visit(node)

        Visitor().visit(tree)
        return list(entities.values()), rels

    # ---------------------------------------------------------------------
    # Unit-test helpers (lightweight extraction/inference)
    # ---------------------------------------------------------------------
    def _extract_code_entities(self, chunk: Chunk) -> list[Entity]:
        """Extract module/class/function entities from a single chunk.

        This helper is used by unit tests and by future graph-building extensions.
        It does not require a Neo4j connection.
        """

        repo_id = "unit-test"
        entities, _rels = self._parse_python_file(repo_id, chunk.file_path, chunk.content)
        return entities

    def _extract_semantic_entities(self, chunk: Chunk) -> list[Entity]:
        """Extract coarse semantic concept entities from docstrings.

        Current implementation is intentionally minimal and safe: it never raises
        on malformed code and may return an empty list.
        """

        try:
            tree = ast.parse(chunk.content or "", filename=chunk.file_path)
        except Exception:
            return []

        concepts: set[str] = set()
        for node in ast.walk(tree):
            doc = ast.get_docstring(node) if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) else None
            if not doc:
                continue
            for token in doc.split():
                t = token.strip(".,:;()[]{}\"'").lower()
                # Keep simple, discriminative terms
                if len(t) < 4:
                    continue
                if not t.isalpha():
                    continue
                concepts.add(t)

        # Emit as "concept" entities; IDs are stable within the chunk/file.
        out: list[Entity] = []
        repo_id = "unit-test"
        for name in sorted(concepts):
            ent_id = self._stable_id(repo_id, chunk.file_path, "concept", name)
            out.append(
                Entity(
                    entity_id=ent_id,
                    name=name,
                    entity_type="concept",
                    file_path=chunk.file_path,
                    description=None,
                    properties={},
                )
            )
        return out

    def _infer_relationships(self, entities: list[Entity]) -> list[Relationship]:
        """Infer lightweight relationships based on entity metadata.

        This is a best-effort heuristic for unit tests and early prototypes.
        """

        if not entities:
            return []

        modules_by_name = {e.name: e for e in entities if e.entity_type == "module" and e.name}
        rels: list[Relationship] = []

        for ent in entities:
            desc = (ent.description or "").lower()
            if "imported from " in desc:
                # Example: "imported from module_a"
                mod_name = desc.split("imported from ", 1)[1].strip().split()[0]
                target = modules_by_name.get(mod_name)
                if target:
                    rels.append(
                        Relationship(
                            source_id=ent.entity_id,
                            target_id=target.entity_id,
                            relation_type="imports",
                            weight=1.0,
                            properties={},
                        )
                    )

        return rels

    @staticmethod
    def _stable_id(repo_id: str, file_path: str, kind: str, name: str) -> str:
        raw = f"{repo_id}|{file_path}|{kind}|{name}".encode()
        return hashlib.sha1(raw).hexdigest()

    @staticmethod
    def _format_name(node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parts = []
            cur: ast.AST | None = node
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                parts.append(cur.id)
            return ".".join(reversed(parts))
        return ""
