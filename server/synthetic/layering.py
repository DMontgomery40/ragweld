from __future__ import annotations

from typing import Literal

LayerName = Literal["gui", "retrieval", "indexing", "graph", "unknown"]


def infer_layer_from_path(file_path: str) -> LayerName:
    path = str(file_path or "").replace("\\", "/").strip().lower().lstrip("/")
    if not path:
        return "unknown"

    if path.startswith("web/") or path.startswith("src/components/") or "/components/" in path:
        return "gui"

    if path.startswith("server/retrieval/") or path.startswith("server/api/search") or path.startswith("server/api/chat"):
        return "retrieval"

    if path.startswith("server/indexing/") or path.startswith("server/api/index") or "/chunking/" in path:
        return "indexing"

    if path.startswith("server/graph/") or path.startswith("server/api/graph") or "neo4j" in path:
        return "graph"

    return "unknown"
