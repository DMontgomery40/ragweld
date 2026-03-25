from __future__ import annotations

import importlib.util
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.config import load_config
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder
from server.indexing.loader import FileLoader
from server.indexing.text_extractors import extract_text_for_path
from server.models.tribrid_config_model import (
    RetrievalPilotExportResponse,
    RetrievalPilotIngestResponse,
    RetrievalPilotPackageStatus,
    RetrievalPilotSearchResponse,
    RetrievalPilotSearchResult,
    RetrievalPilotSearchPreviewResponse,
    RetrievalPilotSearchPreviewResult,
    RetrievalPilotStatusResponse,
    TriBridConfig,
)
from server.services.config_store import get_config as load_scoped_config

_ROOT = Path(__file__).resolve().parents[2]
_PILOT_ROOT = _ROOT / "data" / "retrieval_pilot"
_QUERY_TERM_RE = re.compile(r"[A-Za-z0-9_./-]{2,64}")
_PROVENANCE_FIELDS = [
    "corpus_id",
    "repo_path",
    "file_path",
    "source_path",
    "start_line",
    "end_line",
    "language",
    "token_count",
    "chunk_ordinal",
    "parent_doc_id",
    "char_start",
    "char_end",
    "graph_parity_mode",
]
_PILOT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("docling", "Docling"),
    ("haystack", "Haystack"),
    ("qdrant_client", "Qdrant client"),
)


def _pilot_dir(corpus_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(corpus_id or "").strip()).strip("_") or "unknown"
    return _PILOT_ROOT / safe


def _documents_path(corpus_id: str) -> Path:
    return _pilot_dir(corpus_id) / "documents.jsonl"


def _manifest_path(corpus_id: str) -> Path:
    return _pilot_dir(corpus_id) / "manifest.json"


def _qdrant_path(corpus_id: str) -> Path:
    return _pilot_dir(corpus_id) / "qdrant"


def _collection_name(corpus_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", str(corpus_id or "").strip()).strip("_") or "unknown"
    return f"pilot_chunks_{safe}".lower()


def _package_statuses() -> list[RetrievalPilotPackageStatus]:
    statuses: list[RetrievalPilotPackageStatus] = []
    for package, label in _PILOT_PACKAGES:
        available = importlib.util.find_spec(package) is not None
        detail = "available in environment" if available else "install to enable the full OSS backend target"
        statuses.append(
            RetrievalPilotPackageStatus(
                package=package,
                label=label,
                available=available,
                detail=detail,
            )
        )
    return statuses


async def _load_effective_config(corpus_id: str) -> TriBridConfig:
    try:
        return await load_scoped_config(repo_id=corpus_id)
    except Exception:
        return load_config()


def _ignore_patterns(cfg: TriBridConfig) -> list[str]:
    patterns: list[str] = []
    for ext in str(cfg.indexing.index_excluded_exts or "").split(","):
        value = str(ext or "").strip()
        if not value:
            continue
        if not value.startswith("."):
            value = "." + value
        patterns.append(f"*{value}")
    return patterns


def _pilot_embedder(cfg: TriBridConfig) -> Embedder:
    """Use deterministic embeddings for the pilot execution lane.

    The current goal is to prove the Haystack/Qdrant mechanics and provenance
    contract without coupling pilot hydration to whichever provider-backed
    embedding runtime happens to be configured on the machine.
    """
    pilot_embedding_cfg = cfg.embedding.model_copy(update={"embedding_backend": "deterministic"})
    return Embedder(pilot_embedding_cfg, cfg.tokenization)


def _parse_manifest(corpus_id: str) -> dict[str, Any]:
    path = _manifest_path(corpus_id)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def _operator_hint(
    *,
    repo_path: str,
    export_exists: bool,
    package_status: list[RetrievalPilotPackageStatus],
    execution_ready: bool,
) -> str:
    if not repo_path:
        return "Select a corpus with a valid path before preparing the OSS retrieval pilot export."
    if not export_exists:
        return (
            "Prepare the pilot export to materialize provenance-preserving chunks for the Docling/Haystack/Qdrant seam."
        )
    missing = [pkg.label for pkg in package_status if not pkg.available]
    if missing:
        joined = ", ".join(missing)
        return (
            f"Pilot export is ready. Install {joined} to advance from sidecar export/preview into the full OSS backend."
        )
    if not execution_ready:
        return "Pilot export is ready. Hydrate the local Haystack/Qdrant lane before running real OSS retrieval."
    return "Real Haystack/Qdrant pilot retrieval is ready in-product. Next step: promote this lane and retire preview-only pilot search."


async def build_retrieval_pilot_status(*, corpus_id: str, repo_path: str) -> RetrievalPilotStatusResponse:
    manifest = _parse_manifest(corpus_id)
    package_status = _package_statuses()
    export_dir = _pilot_dir(corpus_id)
    documents_path = _documents_path(corpus_id)
    manifest_path = _manifest_path(corpus_id)
    export_exists = documents_path.exists() and manifest_path.exists()
    raw_last_exported_at = manifest.get("last_exported_at")
    parsed_last_exported_at: datetime | None = None
    if isinstance(raw_last_exported_at, str) and raw_last_exported_at.strip():
        try:
            parsed_last_exported_at = datetime.fromisoformat(raw_last_exported_at.replace("Z", "+00:00"))
        except Exception:
            parsed_last_exported_at = None
    raw_last_indexed_at = manifest.get("last_indexed_at")
    parsed_last_indexed_at: datetime | None = None
    if isinstance(raw_last_indexed_at, str) and raw_last_indexed_at.strip():
        try:
            parsed_last_indexed_at = datetime.fromisoformat(raw_last_indexed_at.replace("Z", "+00:00"))
        except Exception:
            parsed_last_indexed_at = None
    execution_ready = bool(manifest.get("execution_ready") or False)

    return RetrievalPilotStatusResponse(
        repo_id=corpus_id,
        repo_path=repo_path,
        export_dir=str(export_dir),
        documents_path=str(documents_path),
        manifest_path=str(manifest_path),
        export_exists=export_exists,
        exported_file_count=int(manifest.get("exported_file_count") or 0),
        exported_chunk_count=int(manifest.get("exported_chunk_count") or 0),
        skipped_large_files=int(manifest.get("skipped_large_files") or 0),
        skipped_unreadable_files=int(manifest.get("skipped_unreadable_files") or 0),
        last_exported_at=parsed_last_exported_at,
        provenance_fields=list(_PROVENANCE_FIELDS),
        package_status=package_status,
        execution_ready=execution_ready,
        qdrant_path=str(_qdrant_path(corpus_id)),
        collection_name=_collection_name(corpus_id),
        indexed_document_count=int(manifest.get("indexed_document_count") or 0),
        last_indexed_at=parsed_last_indexed_at,
        search_preview_ready=export_exists,
        operator_hint=_operator_hint(
            repo_path=repo_path,
            export_exists=export_exists,
            package_status=package_status,
            execution_ready=execution_ready,
        ),
    )


async def export_retrieval_pilot(*, corpus_id: str, repo_path: str, force_rebuild: bool) -> RetrievalPilotExportResponse:
    cfg = await _load_effective_config(corpus_id)
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"repo_path not found: {repo_path}")

    export_dir = _pilot_dir(corpus_id)
    export_dir.mkdir(parents=True, exist_ok=True)
    documents_path = _documents_path(corpus_id)
    manifest_path = _manifest_path(corpus_id)
    if documents_path.exists() and not force_rebuild:
        status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=str(root))
        return RetrievalPilotExportResponse(ok=True, status=status, warnings=["existing pilot export reused"])

    loader = FileLoader(ignore_patterns=_ignore_patterns(cfg))
    chunker = Chunker(cfg.chunking, cfg.tokenization)
    max_indexable_bytes = min(
        int(cfg.chunking.max_indexable_file_size),
        int(cfg.indexing.index_max_file_size_mb) * 1024 * 1024,
    )

    exported_file_count = 0
    exported_chunk_count = 0
    skipped_large_files = 0
    skipped_unreadable_files = 0

    with documents_path.open("w", encoding="utf-8") as handle:
        for rel_path, abs_path in loader.iter_repo_files(str(root)):
            try:
                size_bytes = int(abs_path.stat().st_size)
            except Exception:
                size_bytes = 0
            if size_bytes > max_indexable_bytes:
                skipped_large_files += 1
                continue

            text = extract_text_for_path(
                abs_path,
                parquet_max_rows=int(cfg.indexing.parquet_extract_max_rows),
                parquet_max_chars=int(cfg.indexing.parquet_extract_max_chars),
                parquet_max_cell_chars=int(cfg.indexing.parquet_extract_max_cell_chars),
                parquet_text_columns_only=bool(int(cfg.indexing.parquet_extract_text_columns_only) == 1),
                parquet_include_column_names=bool(int(cfg.indexing.parquet_extract_include_column_names) == 1),
            )
            if text is None or not text.strip():
                skipped_unreadable_files += 1
                continue

            chunks = chunker.chunk_file(rel_path, text)
            if not chunks:
                skipped_unreadable_files += 1
                continue

            exported_file_count += 1
            for chunk in chunks:
                metadata = dict(chunk.metadata or {})
                payload = {
                    "id": chunk.chunk_id,
                    "content": chunk.content,
                    "meta": {
                        "corpus_id": corpus_id,
                        "repo_path": str(root),
                        "file_path": chunk.file_path,
                        "source_path": str(abs_path),
                        "start_line": int(chunk.start_line),
                        "end_line": int(chunk.end_line),
                        "language": chunk.language,
                        "token_count": int(chunk.token_count or 0),
                        "chunk_ordinal": metadata.get("chunk_ordinal"),
                        "parent_doc_id": metadata.get("parent_doc_id"),
                        "char_start": metadata.get("char_start"),
                        "char_end": metadata.get("char_end"),
                        "graph_parity_mode": "neo4j_v1",
                    },
                }
                handle.write(json.dumps(payload, ensure_ascii=True))
                handle.write("\n")
                exported_chunk_count += 1

    package_status = _package_statuses()
    manifest = {
        "corpus_id": corpus_id,
        "repo_path": str(root),
        "backend": "haystack_qdrant_sidecar",
        "last_exported_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "exported_file_count": exported_file_count,
        "exported_chunk_count": exported_chunk_count,
        "skipped_large_files": skipped_large_files,
        "skipped_unreadable_files": skipped_unreadable_files,
        "provenance_fields": list(_PROVENANCE_FIELDS),
        "package_status": [pkg.model_dump(mode="json") for pkg in package_status],
        "execution_ready": False,
        "indexed_document_count": 0,
        "last_indexed_at": None,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=str(root))
    warnings: list[str] = []
    if not any(pkg.available for pkg in package_status):
        warnings.append("pilot export is ready, but Docling/Haystack/Qdrant packages are not installed yet")
    return RetrievalPilotExportResponse(ok=True, status=status, warnings=warnings)


def _require_execution_packages() -> None:
    required = {
        "haystack": "haystack",
        "haystack_integrations.document_stores.qdrant": "qdrant-haystack",
        "haystack_integrations.components.retrievers.qdrant": "qdrant-haystack",
        "qdrant_client": "qdrant-client",
    }
    missing: list[str] = []
    for module_name, label in required.items():
        if importlib.util.find_spec(module_name) is None:
            missing.append(label)
    if missing:
        joined = ", ".join(sorted(set(missing)))
        raise RuntimeError(f"Missing OSS retrieval execution packages: {joined}")


async def ingest_retrieval_pilot_execution(*, corpus_id: str, repo_path: str, force_rebuild: bool) -> RetrievalPilotIngestResponse:
    _require_execution_packages()

    documents_path = _documents_path(corpus_id)
    manifest_path = _manifest_path(corpus_id)
    if not documents_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("pilot export not found; prepare the pilot export first")

    from haystack import Document
    from haystack.document_stores.types import DuplicatePolicy
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

    cfg = await _load_effective_config(corpus_id)
    embedder = _pilot_embedder(cfg)
    qdrant_path = _qdrant_path(corpus_id)
    if force_rebuild:
        shutil.rmtree(qdrant_path, ignore_errors=True)
    qdrant_path.mkdir(parents=True, exist_ok=True)

    store = QdrantDocumentStore(
        path=str(qdrant_path),
        index=_collection_name(corpus_id),
        embedding_dim=int(embedder.dim),
        recreate_index=bool(force_rebuild),
        on_disk=True,
        progress_bar=False,
    )

    lines = [line for line in documents_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    batch_size = 64
    indexed_document_count = 0
    for start in range(0, len(lines), batch_size):
        batch_lines = lines[start : start + batch_size]
        parsed_batch: list[dict[str, Any]] = []
        texts: list[str] = []
        for line in batch_lines:
            try:
                raw = json.loads(line)
            except Exception:
                continue
            if not isinstance(raw, dict):
                continue
            parsed_batch.append(raw)
            texts.append(str(raw.get("content") or ""))
        if not parsed_batch:
            continue
        embeddings = await embedder.embed_batch(texts)
        docs = [
            Document(
                id=str(raw.get("id") or ""),
                content=str(raw.get("content") or ""),
                embedding=list(emb),
                meta=dict(raw.get("meta") or {}),
            )
            for raw, emb in zip(parsed_batch, embeddings, strict=True)
        ]
        store.write_documents(docs, policy=DuplicatePolicy.OVERWRITE)
        indexed_document_count += len(docs)

    manifest = _parse_manifest(corpus_id)
    manifest.update(
        {
            "execution_ready": True,
            "indexed_document_count": int(store.count_documents()),
            "last_indexed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    )
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=repo_path)
    warnings: list[str] = []
    if indexed_document_count == 0:
        warnings.append("no pilot documents were ingested into Qdrant")
    return RetrievalPilotIngestResponse(ok=True, status=status, warnings=warnings)


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in _QUERY_TERM_RE.finditer(query or ""):
        term = str(match.group(0) or "").lower()
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _preview_score(*, content: str, file_path: str, terms: list[str]) -> float:
    haystack = f"{file_path}\n{content}".lower()
    score = 0.0
    for term in terms:
        matches = haystack.count(term)
        if matches:
            score += 10.0 + float(matches)
        if term in file_path.lower():
            score += 5.0
    return score


def _excerpt(content: str, terms: list[str], *, max_chars: int = 220) -> str:
    lowered = content.lower()
    first_idx = -1
    for term in terms:
        idx = lowered.find(term)
        if idx >= 0 and (first_idx < 0 or idx < first_idx):
            first_idx = idx
    if first_idx < 0:
        first_idx = 0
    start = max(0, first_idx - max_chars // 3)
    end = min(len(content), start + max_chars)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."
    return snippet


async def search_retrieval_pilot_preview(
    *,
    corpus_id: str,
    repo_path: str,
    query: str,
    top_k: int,
) -> RetrievalPilotSearchPreviewResponse:
    terms = _query_terms(query)
    if not terms:
        raise ValueError("query must include at least one searchable term")

    documents_path = _documents_path(corpus_id)
    if not documents_path.exists():
        raise FileNotFoundError("pilot export not found; prepare the pilot export first")

    scored: list[RetrievalPilotSearchPreviewResult] = []
    for line in documents_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except Exception:
            continue
        if not isinstance(raw, dict):
            continue
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        content = str(raw.get("content") or "")
        file_path = str(meta.get("file_path") or "")
        score = _preview_score(content=content, file_path=file_path, terms=terms)
        if score <= 0:
            continue
        scored.append(
            RetrievalPilotSearchPreviewResult(
                chunk_id=str(raw.get("id") or ""),
                file_path=file_path,
                source_path=str(meta.get("source_path") or ""),
                start_line=int(meta.get("start_line") or 1),
                end_line=int(meta.get("end_line") or 1),
                language=str(meta.get("language") or "") or None,
                score=score,
                excerpt=_excerpt(content, terms),
            )
        )

    scored.sort(key=lambda item: (-item.score, item.file_path, item.start_line))
    status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=repo_path)
    return RetrievalPilotSearchPreviewResponse(
        repo_id=corpus_id,
        query=query,
        results=scored[: int(top_k)],
        status=status,
    )


async def search_retrieval_pilot_execution(
    *,
    corpus_id: str,
    repo_path: str,
    query: str,
    top_k: int,
) -> RetrievalPilotSearchResponse:
    _require_execution_packages()
    terms = _query_terms(query)
    if not terms:
        raise ValueError("query must include at least one searchable term")

    manifest = _parse_manifest(corpus_id)
    if not bool(manifest.get("execution_ready") or False):
        raise FileNotFoundError("pilot execution lane not ready; ingest the Haystack/Qdrant lane first")

    qdrant_path = _qdrant_path(corpus_id)
    if not qdrant_path.exists():
        raise FileNotFoundError("pilot execution lane not ready; local Qdrant store is missing")

    from haystack_integrations.components.retrievers.qdrant import QdrantEmbeddingRetriever
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

    cfg = await _load_effective_config(corpus_id)
    embedder = _pilot_embedder(cfg)
    store = QdrantDocumentStore(
        path=str(qdrant_path),
        index=_collection_name(corpus_id),
        embedding_dim=int(embedder.dim),
        recreate_index=False,
        on_disk=True,
        progress_bar=False,
    )
    retriever = QdrantEmbeddingRetriever(document_store=store, top_k=int(top_k))
    query_embedding = await embedder.embed(query)
    response = retriever.run(query_embedding=query_embedding, top_k=int(top_k))
    documents = list(response.get("documents") or [])

    results = [
        RetrievalPilotSearchResult(
            chunk_id=str(doc.id or ""),
            file_path=str((doc.meta or {}).get("file_path") or ""),
            source_path=str((doc.meta or {}).get("source_path") or ""),
            start_line=int((doc.meta or {}).get("start_line") or 1),
            end_line=int((doc.meta or {}).get("end_line") or 1),
            language=str((doc.meta or {}).get("language") or "") or None,
            score=float(doc.score or 0.0),
            excerpt=_excerpt(str(doc.content or ""), terms),
        )
        for doc in documents
    ]

    status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=repo_path)
    return RetrievalPilotSearchResponse(
        repo_id=corpus_id,
        query=query,
        results=results,
        status=status,
    )
