"""The generated architecture pages must be drawn from the real system, densely, and fail loudly on drift."""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "docs_ai" / "generate_architecture_diagrams.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_architecture_diagrams_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _mermaid_blocks(markdown: str) -> list[str]:
    return re.findall(r"```mermaid\n(.*?)```", markdown, re.S)


@pytest.fixture(scope="module")
def pages(tmp_path_factory: pytest.TempPathFactory) -> dict[str, str]:
    module = _load_module()
    out = tmp_path_factory.mktemp("arch")
    written = module.generate(REPO_ROOT, out, clean=True)
    return {p.name: p.read_text(encoding="utf-8") for p in written}


def test_generation_is_deterministic(tmp_path: Path) -> None:
    module = _load_module()
    first = {p.name: p.read_bytes() for p in module.generate(REPO_ROOT, tmp_path / "a", clean=True)}
    second = {p.name: p.read_bytes() for p in module.generate(REPO_ROOT, tmp_path / "b", clean=True)}
    assert first == second
    assert set(first) == {"index.md", "runtime-topology.md", "api-surface.md", "retrieval-pipeline.md", "config-model.md"}


def test_topology_draws_every_compose_service_and_dependency(pages: dict[str, str]) -> None:
    module = _load_module()
    page = pages["runtime-topology.md"]
    (mermaid,) = _mermaid_blocks(page)
    services = module.load_services(REPO_ROOT)
    # Ground truth read independently: the merged service set of all three files.
    expected = set()
    for rel, _ in module.COMPOSE_FILES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        in_services = False
        for line in text.splitlines():
            if line.startswith("services:"):
                in_services = True
                continue
            if in_services and re.match(r"^[a-z]", line):
                in_services = False
            m = re.match(r"^  ([a-z0-9-]+):\s*$", line)
            if in_services and m:
                expected.add(m.group(1))
    assert set(services) == expected
    for name, svc in services.items():
        assert f'{module._node_id(name)}["' in mermaid, f"{name} missing from the topology diagram"
        assert f"| `{name}` |" in page
        for dep in svc.depends_on:
            assert f"{module._node_id(name)} --> {module._node_id(dep)}" in mermaid, f"{name} -> {dep} edge missing"
    # The locked observability stack is present by name, with resolved defaults, not env placeholders.
    for must in ("tempo", "alloy", "mimir", "pyroscope", "loki", "langfuse", "litellm", "flyte", "mlflow", "qdrant", "neo4j"):
        assert must in services
    assert "${" not in mermaid
    # Every depends_on edge is asserted above; the floor only guards against an empty drawing.
    assert module._edge_count(mermaid) >= 15


def test_api_page_lists_every_route_decorator(pages: dict[str, str]) -> None:
    module = _load_module()
    page = pages["api-surface.md"]
    routes = module.load_routes(REPO_ROOT)
    # Independent count: every decorator call on a router method with a literal first arg.
    expected = 0
    for path in (REPO_ROOT / "server" / "api").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if (
                        isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id == "router"
                        and dec.func.attr in module.ROUTE_METHODS
                        and dec.args
                        and isinstance(dec.args[0], ast.Constant)
                    ):
                        expected += 1
    assert len(routes) == expected
    assert expected > 100
    table_rows = [ln for ln in page.splitlines() if re.match(r"^\| `(GET|POST|PUT|PATCH|DELETE)` \| `/", ln)]
    assert len(table_rows) == expected
    # Mount prefixes are honoured: /api for most routers, router-owned prefixes for the others.
    paths = {r.path for r in routes}
    assert "/api/search" in paths
    assert "/api/index/estimate" in paths
    assert any(p.startswith("/api/models") for p in paths)
    assert any(p.startswith("/api/observability/") for p in paths)
    assert all(p.startswith("/api/") for p in paths), sorted(p for p in paths if not p.startswith("/api/"))
    blocks = _mermaid_blocks(page)
    assert len(blocks) == 1 + len({r.router for r in routes})


def test_retrieval_page_uses_real_config_keys_and_is_dense(pages: dict[str, str]) -> None:
    module = _load_module()
    page = pages["retrieval-pipeline.md"]
    (mermaid,) = _mermaid_blocks(page)
    cfg = module._config_cls()()
    for section in ("fusion", "vector_search", "sparse_search", "graph_search", "reranking", "semantic_cache"):
        for name in type(getattr(cfg, section)).model_fields:
            assert f"| `{name}` |" in page, f"{section}.{name} missing from the knob table"
    for key in ("vector_weight", "sparse_weight", "graph_weight", "rrf_k", "bm25_k1", "bm25_b", "reranker_mode", "conf_top1"):
        assert key in mermaid
    for module_path in module.RETRIEVAL_MODULES[:6]:
        assert module_path.split("/")[-1] in page
    assert module._edge_count(mermaid) >= 20
    assert len(re.findall(r"^\s+subgraph ", mermaid, re.M)) >= 5
    assert "pgvector" not in page.lower()


def test_config_page_covers_every_section(pages: dict[str, str]) -> None:
    module = _load_module()
    page = pages["config-model.md"]
    cfg_cls = module._config_cls()
    from pydantic import BaseModel

    instance = cfg_cls()
    sections = [n for n in cfg_cls.model_fields if isinstance(getattr(instance, n), BaseModel)]
    for name in sections:
        assert f"| `{name}` |" in page
        assert f"root --> {module._node_id(name)}" in page
    assert len(sections) >= 25


def test_retrieval_page_fails_loudly_when_a_named_module_disappears(tmp_path: Path) -> None:
    module = _load_module()
    fake_root = tmp_path / "root"
    for rel in module.RETRIEVAL_MODULES[1:]:
        dst = fake_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)
    with pytest.raises(RuntimeError, match=module.RETRIEVAL_MODULES[0]):
        module.build_retrieval_page(fake_root)


def test_no_stale_components_anywhere(pages: dict[str, str]) -> None:
    blob = "\n".join(pages.values()).lower()
    # `pgvector/pgvector:pg16` is the Postgres image name and is allowed; pgvector as a *component* is not.
    assert not re.search(r"pgvector(?![/:])", blob)
    for stale in ("crossencoder", "golden question", "profiles"):
        assert stale not in blob
