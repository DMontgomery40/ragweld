#!/usr/bin/env python3
"""
Generate MkDocs architecture pages with Mermaid diagrams drawn from the real system.

The LLM lane of the docs autopilot draws placeholder diagrams when nothing pins
it to the code: six boxes for a retrieval pipeline that has three Qdrant/Neo4j
legs, weighted fusion, scoring boosts, a reranker, a semantic cache and a
confidence gate. These pages are derived from the sources below on every run,
so they are complete and current by construction, and the prompt base tells
the model to link them instead of redrawing them.

Sources of truth:
  - docker-compose.yml, infra/docker-compose.observability.yml,
    deploy/proxmox/docker-compose.yml         -> runtime topology
  - server/main.py + server/api/*.py           -> API surface (every route)
  - server/models/tribrid_config_model.py      -> retrieval pipeline + config tree
  - server/retrieval/*, server/indexing/*      -> module names (must exist)

Output:
  - mkdocs/docs/reference/architecture/index.md
  - mkdocs/docs/reference/architecture/runtime-topology.md
  - mkdocs/docs/reference/architecture/api-surface.md
  - mkdocs/docs/reference/architecture/retrieval-pipeline.md
  - mkdocs/docs/reference/architecture/config-model.md

`mkdocs/**` is docs-autopilot output; this script is one of its inputs.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "mkdocs" / "docs" / "reference" / "architecture"

COMPOSE_FILES: tuple[tuple[str, str], ...] = (
    ("docker-compose.yml", "base"),
    ("infra/docker-compose.observability.yml", "observability overlay"),
    ("deploy/proxmox/docker-compose.yml", "pve1 production overlay"),
)

# Subgraph placement for the topology diagram. A service missing from this map
# is still drawn (under "Other services"); it is never dropped.
SERVICE_GROUPS: dict[str, tuple[str, ...]] = {
    "Application": ("api",),
    "Data stores": ("postgres", "postgres-exporter", "neo4j", "qdrant"),
    "Generation gateway": ("litellm",),
    "Orchestration and training": ("flyte", "mlflow"),
    "Metrics, logs, traces, profiling": (
        "prometheus",
        "alertmanager",
        "mimir",
        "loki",
        "promtail",
        "tempo",
        "alloy",
        "pyroscope",
        "grafana",
    ),
    "Langfuse": (
        "langfuse",
        "langfuse-worker",
        "langfuse-postgres",
        "langfuse-clickhouse",
        "langfuse-redis",
        "langfuse-minio",
    ),
    "Production ingress (pve1)": ("cloudflared", "caddy", "authelia"),
}

# Retrieval modules the pipeline page names. Generation fails if one is gone,
# so a deleted lane cannot keep living in the docs (the pgvector lesson).
RETRIEVAL_MODULES: tuple[str, ...] = (
    "server/retrieval/fusion.py",
    "server/retrieval/rerank.py",
    "server/retrieval/gateway_reranker.py",
    "server/retrieval/scoring_boosts.py",
    "server/retrieval/cache.py",
    "server/retrieval/qdrant_store.py",
    "server/services/answer_service.py",
    "server/indexing/loader.py",
    "server/indexing/chunker.py",
    "server/indexing/embedder.py",
    "server/indexing/official_graphrag.py",
)

RETRIEVAL_SECTIONS: tuple[str, ...] = (
    "semantic_cache",
    "retrieval",
    "embedding",
    "vector_search",
    "sparse_search",
    "graph_search",
    "graph_storage",
    "fusion",
    "scoring",
    "layer_bonus",
    "reranking",
    "hydration",
    "generation",
)

ROUTE_METHODS = ("get", "post", "put", "patch", "delete")
_ENV_DEFAULT_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


# --------------------------------------------------------------------------- utils


def _resolve_env(value: str) -> str:
    """`${VAR:-default}` -> `default`; bare `${VAR}` -> `$VAR`."""

    def sub(m: re.Match[str]) -> str:
        return m.group(2) if m.group(2) is not None else f"${m.group(1)}"

    return _ENV_DEFAULT_RE.sub(sub, value or "")


def _mermaid_label(text: str) -> str:
    # Mermaid labels are quoted; double quotes inside must become entities.
    return (text or "").replace('"', "#quot;")


def _node_id(name: str) -> str:
    return "n_" + re.sub(r"[^A-Za-z0-9]", "_", name)


def _edge_count(mermaid: str) -> int:
    return len(re.findall(r"-->|-\.->|==>|---", mermaid))


class _TolerantLoader(yaml.SafeLoader):
    """SafeLoader that accepts compose merge tags (`!override`, `!reset`)."""


def _construct_any(loader: yaml.SafeLoader, _suffix: str, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_TolerantLoader.add_multi_constructor("!", _construct_any)


# ------------------------------------------------------------------ topology


@dataclass
class Service:
    name: str
    image: str = ""
    ports: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def load_services(root: Path) -> dict[str, Service]:
    """Merge the compose files the way `docker compose -f a -f b -f c` does."""
    services: dict[str, Service] = {}
    for rel, label in COMPOSE_FILES:
        path = root / rel
        if not path.exists():
            raise RuntimeError(f"compose file missing: {rel}")
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_TolerantLoader) or {}
        for name, raw in (data.get("services") or {}).items():
            raw = raw or {}
            svc = services.setdefault(name, Service(name=name))
            svc.files.append(label)
            if raw.get("image"):
                svc.image = _resolve_env(str(raw["image"]))
            elif raw.get("build") and not svc.image:
                svc.image = "(built from repo)"
            if raw.get("ports"):
                ports: list[str] = []
                for p in raw["ports"]:
                    text = _resolve_env(str(p))
                    parts = text.split(":")
                    # 127.0.0.1:3301:3000 -> 3301->3000 ; 3000 -> 3000
                    if len(parts) >= 2:
                        ports.append(f"{parts[-2]}->{parts[-1]}")
                    else:
                        ports.append(parts[0])
                svc.ports = ports
            dep = raw.get("depends_on")
            dep_names = list(dep.keys()) if isinstance(dep, dict) else list(dep or [])
            for d in dep_names:
                if d not in svc.depends_on:
                    svc.depends_on.append(str(d))
    return services


def render_topology(services: dict[str, Service]) -> str:
    placed: set[str] = set()
    lines = ["flowchart LR"]
    for group, members in SERVICE_GROUPS.items():
        present = [m for m in members if m in services]
        if not present:
            continue
        lines.append(f'    subgraph {_node_id(group)}["{_mermaid_label(group)}"]')
        for name in present:
            svc = services[name]
            label = name
            if svc.image:
                label += f"\\n{svc.image}"
            if svc.ports:
                label += "\\nports " + ", ".join(svc.ports)
            lines.append(f'        {_node_id(name)}["{_mermaid_label(label)}"]')
            placed.add(name)
        lines.append("    end")
    others = sorted(set(services) - placed)
    if others:
        lines.append('    subgraph n_other["Other services"]')
        for name in others:
            svc = services[name]
            label = name + (f"\\n{svc.image}" if svc.image else "")
            lines.append(f'        {_node_id(name)}["{_mermaid_label(label)}"]')
        lines.append("    end")
    for name in sorted(services):
        for dep in services[name].depends_on:
            if dep in services:
                lines.append(f"    {_node_id(name)} --> {_node_id(dep)}")
    return "\n".join(lines)


def build_topology_page(root: Path) -> str:
    services = load_services(root)
    mermaid = render_topology(services)
    rows = ["| Service | Image | Host ports | Depends on | Defined in |", "|---|---|---|---|---|"]
    for name in sorted(services):
        s = services[name]
        rows.append(
            f"| `{name}` | `{s.image or '-'}` | {', '.join(s.ports) or '-'} | "
            f"{', '.join(f'`{d}`' for d in s.depends_on) or '-'} | {', '.join(s.files)} |"
        )
    return "\n".join(
        [
            "# Runtime topology",
            "",
            "!!! info \"Generated page\"",
            "    Drawn from `docker-compose.yml`, `infra/docker-compose.observability.yml` and",
            "    `deploy/proxmox/docker-compose.yml` on every docs-autopilot run. Edit the compose files, not this page.",
            "",
            f"{len(services)} services; an arrow means *depends on*. Host ports are the defaults from the compose files",
            "(`HOST->CONTAINER`), all bound to `127.0.0.1`; the pve1 overlay exposes the app only through Cloudflare Tunnel -> Caddy -> Authelia.",
            "",
            "```mermaid",
            mermaid,
            "```",
            "",
            "## Every service",
            "",
            *rows,
            "",
        ]
    )


# ----------------------------------------------------------------- api surface


@dataclass(frozen=True)
class Route:
    router: str
    method: str
    path: str
    handler: str
    response_model: str


def _router_prefix(module_src: str) -> str:
    m = re.search(r'APIRouter\((?:[^)]*?)prefix\s*=\s*"([^"]+)"', module_src)
    return m.group(1) if m else ""


def _mount_prefixes(root: Path) -> dict[str, str]:
    """`app.include_router(<name>_router, prefix="/api")` from server/main.py."""
    src = (root / "server" / "main.py").read_text(encoding="utf-8")
    prefixes: dict[str, str] = {}
    for m in re.finditer(r"app\.include_router\((\w+)_router(?:,\s*prefix\s*=\s*\"([^\"]*)\")?", src):
        prefixes[m.group(1)] = m.group(2) or ""
    return prefixes


def _decorator_route(dec: ast.expr) -> tuple[str, str, str] | None:
    """(method, path, response_model) for `@router.<method>("/path", response_model=X)`."""
    if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
        return None
    if not (isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"):
        return None
    method = dec.func.attr
    if method not in ROUTE_METHODS or not dec.args:
        return None
    first = dec.args[0]
    if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
        return None
    response_model = ""
    for kw in dec.keywords:
        if kw.arg == "response_model":
            response_model = ast.unparse(kw.value)
    return method.upper(), first.value, response_model


def load_routes(root: Path) -> list[Route]:
    mounts = _mount_prefixes(root)
    routes: list[Route] = []
    for path in sorted((root / "server" / "api").glob("*.py")):
        if path.name.startswith("_"):
            continue
        src = path.read_text(encoding="utf-8")
        if "APIRouter(" not in src:
            continue
        router_name = path.stem
        prefix = mounts.get(router_name, "") + _router_prefix(src)
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                found = _decorator_route(dec)
                if found:
                    method, rel, resp = found
                    routes.append(Route(router_name, method, prefix + rel, node.name, resp))
    return routes


def render_api_overview(routes: list[Route]) -> str:
    by_router: dict[str, list[Route]] = {}
    for r in routes:
        by_router.setdefault(r.router, []).append(r)
    lines = ["flowchart LR", '    app["FastAPI app\\nserver/main.py"]']
    for router in sorted(by_router):
        rs = by_router[router]
        methods = sorted({r.method for r in rs})
        label = f"{router}\\n{len(rs)} routes: {', '.join(methods)}"
        lines.append(f'    {_node_id(router)}["{_mermaid_label(label)}"]')
        lines.append(f"    app --> {_node_id(router)}")
    return "\n".join(lines)


def render_router_diagram(router: str, routes: list[Route]) -> str:
    lines = ["flowchart LR", f'    {_node_id(router)}["{_mermaid_label(router)}\\nserver/api/{router}.py"]']
    for i, r in enumerate(sorted(routes, key=lambda x: (x.path, x.method))):
        nid = f"{_node_id(router)}_{i}"
        label = f"{r.method} {r.path}"
        if r.response_model:
            label += f"\\n-> {r.response_model}"
        lines.append(f'    {nid}["{_mermaid_label(label)}"]')
        lines.append(f"    {_node_id(router)} --> {nid}")
    return "\n".join(lines)


def build_api_page(root: Path) -> str:
    routes = load_routes(root)
    if not routes:
        raise RuntimeError("no routes found under server/api; refusing to write an empty API page")
    by_router: dict[str, list[Route]] = {}
    for r in routes:
        by_router.setdefault(r.router, []).append(r)
    out = [
        "# API surface",
        "",
        "!!! info \"Generated page\"",
        "    Every route below is read from the `@router.<method>` decorators under `server/api/` and the",
        "    mount prefixes in `server/main.py` on every docs-autopilot run. The wire schemas are the registered",
        "    Pydantic models; see the configuration reference for their fields.",
        "",
        f"{len(routes)} routes across {len(by_router)} routers, all served by the FastAPI app in `server/main.py`.",
        "",
        "```mermaid",
        render_api_overview(routes),
        "```",
        "",
        "## Routers",
        "",
    ]
    for router in sorted(by_router):
        rs = sorted(by_router[router], key=lambda x: (x.path, x.method))
        out += [
            f"### `{router}` ({len(rs)} routes)",
            "",
            "```mermaid",
            render_router_diagram(router, rs),
            "```",
            "",
            "| Method | Path | Handler | Response model |",
            "|---|---|---|---|",
        ]
        for r in rs:
            out.append(f"| `{r.method}` | `{r.path}` | `{r.handler}` | `{r.response_model or '-'}` |")
        out.append("")
    return "\n".join(out)


# ------------------------------------------------------------ retrieval pipeline


def _config_cls():
    sys.path.insert(0, str(ROOT))
    from server.models.tribrid_config_model import TriBridConfig  # noqa: PLC0415

    return TriBridConfig


def _section_fields(cfg: BaseModel, section: str) -> list[tuple[str, Any, str]]:
    model = getattr(cfg, section)
    rows: list[tuple[str, Any, str]] = []
    for name, info in type(model).model_fields.items():
        rows.append((name, getattr(model, name), info.description or ""))
    return rows


def _kv(cfg: BaseModel, section: str, *names: str) -> str:
    model = getattr(cfg, section)
    parts = []
    for n in names:
        if hasattr(model, n):
            v = getattr(model, n)
            parts.append(f"{n}={v!r}" if not isinstance(v, str) else f"{n}={v}")
    return "\\n".join(parts)


def render_retrieval_pipeline(cfg: BaseModel) -> str:
    lab = _mermaid_label

    def node(nid: str, title: str, body: str) -> str:
        return f'    {nid}["{lab(title)}' + (f"\\n{lab(body)}" if body else "") + '"]'
    lines = ["flowchart TB"]
    lines += [
        '    subgraph s_in["Request"]',
        node("q", "Query", "POST /api/search, /api/chat/stream, /api/answer"),
        node("cache", "Semantic cache (server/retrieval/cache.py)", _kv(cfg, "semantic_cache", "enabled", "mode", "similarity_threshold_search", "similarity_threshold_chat", "ttl_seconds_search", "max_entries")),
        node("expand", "Query expansion", _kv(cfg, "retrieval", "query_expansion_enabled", "multi_query_m", "max_query_rewrites", "use_semantic_synonyms")),
        "    end",
        '    subgraph s_legs["Three retrieval legs"]',
        node("embed", "Embedder (server/indexing/embedder.py)", _kv(cfg, "embedding", "embedding_backend", "embedding_type", "embedding_model", "embedding_dim")),
        node("dense", "Dense leg -> Qdrant dense generation", _kv(cfg, "vector_search", "enabled", "top_k") + "\\n" + _kv(cfg, "retrieval", "topk_dense", "min_score_vector")),
        node("sparse", "Sparse leg -> Qdrant sparse generation (BM25)", _kv(cfg, "sparse_search", "enabled", "top_k", "bm25_k1", "bm25_b") + "\\n" + _kv(cfg, "retrieval", "topk_sparse", "min_score_sparse")),
        node("graph", "Graph leg -> Neo4j (Document/Chunk lexical graph)", _kv(cfg, "graph_search", "enabled", "mode", "max_hops", "top_k", "chunk_neighbor_window", "include_communities") + "\\n" + _kv(cfg, "retrieval", "min_score_graph")),
        "    end",
        '    subgraph s_stores["Stores"]',
        node("qdrant", "Qdrant (server/retrieval/qdrant_store.py)", _kv(cfg, "qdrant", "url")),
        node("pg", "Postgres chunk rows + generation manifests", _kv(cfg, "indexing", "postgres_url")),
        node("neo4j", "Neo4j (server/db/neo4j.py)", _kv(cfg, "graph_storage", "neo4j_uri", "neo4j_database_mode", "community_algorithm")),
        "    end",
        '    subgraph s_fuse["Fusion and shaping (server/retrieval/fusion.py)"]',
        node("fusion", "Weighted RRF fusion", _kv(cfg, "fusion", "vector_weight", "sparse_weight", "graph_weight", "rrf_k") + "\\n" + _kv(cfg, "retrieval", "rrf_k_div", "bm25_weight", "vector_weight")),
        node("boost", "Scoring boosts (server/retrieval/scoring_boosts.py)", _kv(cfg, "scoring", "chunk_summary_bonus", "filename_boost_exact", "filename_boost_partial", "vendor_mode") + "\\n" + _kv(cfg, "layer_bonus", "gui", "retrieval", "indexer", "vendor_penalty", "freshness_bonus")),
        node("shape", "Dedup / MMR / neighbours", _kv(cfg, "retrieval", "dedup_by", "max_chunks_per_file", "neighbor_window", "enable_mmr", "mmr_lambda", "chunk_summary_search_enabled")),
        "    end",
        '    subgraph s_rerank["Reranking (server/retrieval/rerank.py, gateway_reranker.py)"]',
        node("rerank", "Reranker", _kv(cfg, "reranking", "reranker_mode", "reranker_cloud_provider", "reranker_cloud_model", "reranker_cloud_top_n", "tribrid_reranker_alpha", "tribrid_reranker_topn", "reranker_timeout")),
        "    end",
        '    subgraph s_out["Answer"]',
        node("conf", "Confidence gate", _kv(cfg, "retrieval", "conf_top1", "conf_avg5", "conf_any", "fallback_confidence", "final_k", "eval_final_k")),
        node("hydrate", "Hydration", _kv(cfg, "hydration", "mode", "max_chars") or _kv(cfg, "retrieval", "hydration_mode", "hydration_max_chars")),
        node("gen", "Generation via LiteLLM gateway (server/services/answer_service.py)", _kv(cfg, "generation", "gen_model", "gen_max_tokens", "gen_temperature")),
        node("trace", "Trace + cost accounting", "server/services/traces.py -> Tempo / Langfuse"),
        "    end",
    ]
    edges = [
        ("q", "cache"), ("cache", "expand"), ("expand", "embed"), ("expand", "sparse"), ("expand", "graph"),
        ("embed", "dense"), ("dense", "qdrant"), ("sparse", "qdrant"), ("graph", "neo4j"), ("qdrant", "pg"), ("neo4j", "pg"),
        ("dense", "fusion"), ("sparse", "fusion"), ("graph", "fusion"),
        ("fusion", "boost"), ("boost", "shape"), ("shape", "rerank"), ("rerank", "conf"), ("conf", "hydrate"),
        ("hydrate", "gen"), ("gen", "trace"), ("gen", "cache"),
    ]
    lines += [f"    {a} --> {b}" for a, b in edges]
    return "\n".join(lines)


def build_retrieval_page(root: Path) -> str:
    missing = [m for m in RETRIEVAL_MODULES if not (root / m).exists()]
    if missing:
        raise RuntimeError("retrieval pipeline page names modules that no longer exist: " + ", ".join(missing))
    cfg = _config_cls()()
    mermaid = render_retrieval_pipeline(cfg)
    out = [
        "# Retrieval pipeline",
        "",
        "!!! info \"Generated page\"",
        "    Node labels are the real configuration keys and defaults from `server/models/tribrid_config_model.py`;",
        "    module paths are checked to exist when this page is generated. Tune values in the config UI or",
        "    `tribrid_config.json`; corpus-scoped overrides apply per corpus.",
        "",
        "The three legs (dense and sparse from Qdrant generations, graph from the Neo4j lexical graph) are fused with",
        "weighted RRF, boosted, deduplicated, optionally reranked, gated on confidence and hydrated before generation",
        "through the LiteLLM gateway. Every value shown is the shipped default.",
        "",
        "```mermaid",
        mermaid,
        "```",
        "",
        "## Every knob on the path",
        "",
    ]
    for section in RETRIEVAL_SECTIONS:
        if not hasattr(cfg, section):
            continue
        out += [f"### `{section}`", "", "| Field | Default | What it does |", "|---|---|---|"]
        for name, value, desc in _section_fields(cfg, section):
            shown = repr(value) if not isinstance(value, str) else value
            if len(shown) > 60:
                shown = shown[:57] + "..."
            out.append(f"| `{name}` | `{shown.replace('|', '/')}` | {(desc or '').replace('|', '/')} |")
        out.append("")
    return "\n".join(out)


# ----------------------------------------------------------------- config model


def build_config_page(root: Path) -> str:
    cfg_cls = _config_cls()
    cfg = cfg_cls()
    lines = ["flowchart LR", '    root["TriBridConfig\\nserver/models/tribrid_config_model.py"]']
    rows = ["| Section | Fields | Purpose | Reference |", "|---|---|---|---|"]
    for name, info in cfg_cls.model_fields.items():
        value = getattr(cfg, name)
        if not isinstance(value, BaseModel):
            continue
        count = len(type(value).model_fields)
        desc = (info.description or type(value).__doc__ or "").strip().splitlines()[0] if (info.description or type(value).__doc__) else ""
        lines.append(f'    {_node_id(name)}["{_mermaid_label(name)}\\n{count} fields"]')
        lines.append(f"    root --> {_node_id(name)}")
        rows.append(f"| `{name}` | {count} | {desc.replace('|', '/')} | [{name}](../config/{name}.md) |")
    return "\n".join(
        [
            "# Configuration model",
            "",
            "!!! info \"Generated page\"",
            "    The composition root is `TriBridConfig`; every section is a Pydantic model whose fields are the",
            "    public wire contract (regenerated into `web/src/types/generated.ts`). Field-level pages live under the",
            "    configuration reference.",
            "",
            "```mermaid",
            "\n".join(lines),
            "```",
            "",
            *rows,
            "",
        ]
    )


# ------------------------------------------------------------------------ main


def build_index_page() -> str:
    return "\n".join(
        [
            "# Architecture reference (generated)",
            "",
            "These pages are regenerated from the code, compose files and configuration model on every",
            "docs-autopilot run. They are the authoritative diagrams; narrative pages link here rather than",
            "redrawing the system by hand.",
            "",
            "- [Runtime topology](runtime-topology.md) - every service, dependency and port across the base,",
            "  observability and pve1 compose files",
            "- [API surface](api-surface.md) - every route, grouped by router, with handler and response model",
            "- [Retrieval pipeline](retrieval-pipeline.md) - the three legs, fusion, boosts, reranking, gating and",
            "  generation with the real configuration keys and defaults",
            "- [Configuration model](config-model.md) - the `TriBridConfig` composition root",
            "",
        ]
    )


PAGES = {
    "index.md": lambda root: build_index_page(),
    "runtime-topology.md": build_topology_page,
    "api-surface.md": build_api_page,
    "retrieval-pipeline.md": build_retrieval_page,
    "config-model.md": build_config_page,
}


def generate(root: Path, out_dir: Path, *, clean: bool = False) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        for old in out_dir.glob("*.md"):
            old.unlink()
    written: list[Path] = []
    for name, builder in PAGES.items():
        content = builder(root)
        path = out_dir / name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate MkDocs architecture diagrams from the real system")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--clean", action="store_true", help="Delete existing .md files in the output directory first")
    args = ap.parse_args(argv)
    for path in generate(ROOT, args.out, clean=args.clean):
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
