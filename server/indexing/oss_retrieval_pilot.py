from __future__ import annotations

import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.config import load_config
from server.dependency_errors import DependencyUnavailableError
from server.indexing.chunker import Chunker
from server.indexing.embedder import Embedder
from server.indexing.loader import FileLoader
from server.indexing.text_extractors import extract_text_for_path
from server.chat.context_formatter import format_context_for_llm
from server.chat.generation import generate_chat_text
from server.chat.handler import ChatGenerationError
from server.chat.prompt_builder import get_system_prompt
from server.chat.provider_router import select_provider_route
from server.models.retrieval import ChunkMatch
from server.models.runtime_gateway import ChatProviderInfo
from server.models.tribrid_config_model import (
    RetrievalPilotAnswerResponse,
    RetrievalPilotExportResponse,
    RetrievalPilotIngestResponse,
    RetrievalPilotPackageStatus,
    RetrievalPilotSearchPreviewResponse,
    RetrievalPilotSearchPreviewResult,
    RetrievalPilotSearchResponse,
    RetrievalPilotSearchResult,
    RetrievalPilotStatusResponse,
    TriBridConfig,
)
from server.retrieval.contracts import contract_hash, dense_contract_from_config
from server.retrieval.errors import EmbeddingContractMismatchError, SparseContractMismatchError
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
    "extraction",
    "graph_parity_mode",
]
_PILOT_PACKAGES: tuple[tuple[str, str], ...] = (
    ("docling", "Docling"),
    ("haystack", "Haystack"),
    ("qdrant_client", "Qdrant client"),
)

# Rich-document formats routed through Docling during pilot export. Code and
# plain-text formats keep the direct extraction path by design.
_DOCLING_SUFFIXES: frozenset[str] = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm"})

_DOCLING_CONVERTER: Any = None

_SPARSE_MODEL = "Qdrant/bm25"
_SPARSE_DOC_EMBEDDER: Any = None
_SPARSE_TEXT_EMBEDDER: Any = None


def _sparse_doc_embedder() -> Any:
    global _SPARSE_DOC_EMBEDDER
    if _SPARSE_DOC_EMBEDDER is None:
        from haystack_integrations.components.embedders.fastembed import (
            FastembedSparseDocumentEmbedder,
        )

        embedder = FastembedSparseDocumentEmbedder(model=_SPARSE_MODEL)
        embedder.warm_up()
        _SPARSE_DOC_EMBEDDER = embedder
    return _SPARSE_DOC_EMBEDDER


def _sparse_text_embedder() -> Any:
    global _SPARSE_TEXT_EMBEDDER
    if _SPARSE_TEXT_EMBEDDER is None:
        from haystack_integrations.components.embedders.fastembed import FastembedSparseTextEmbedder

        embedder = FastembedSparseTextEmbedder(model=_SPARSE_MODEL)
        embedder.warm_up()
        _SPARSE_TEXT_EMBEDDER = embedder
    return _SPARSE_TEXT_EMBEDDER


def _sparse_contract() -> dict[str, Any]:
    return {"engine": "qdrant_sparse_idf", "model": _SPARSE_MODEL, "idf": True}


def _docling_converter() -> Any:
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is None:
        from docling.document_converter import DocumentConverter

        _DOCLING_CONVERTER = DocumentConverter()
    return _DOCLING_CONVERTER


def _extract_with_docling(abs_path: Path) -> str | None:
    """Convert a rich document to markdown via Docling; None when unparseable."""
    try:
        result = _docling_converter().convert(str(abs_path))
        text = result.document.export_to_markdown()
    except Exception:
        return None
    text = str(text or "")
    return text if text.strip() else None


def _pilot_dir(corpus_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(corpus_id or "").strip()).strip("_") or "unknown"
    return _PILOT_ROOT / safe


def _documents_path(corpus_id: str) -> Path:
    return _pilot_dir(corpus_id) / "documents.jsonl"


def _manifest_path(corpus_id: str) -> Path:
    return _pilot_dir(corpus_id) / "manifest.json"


def _qdrant_url(cfg: TriBridConfig) -> str:
    return str(cfg.qdrant.url or "").strip().rstrip("/")


def _pilot_document_store(cfg: TriBridConfig, corpus_id: str, *, embedding_dim: int, recreate: bool):
    """Open the pilot collection on the Compose-owned Qdrant service."""
    from haystack_integrations.document_stores.qdrant import QdrantDocumentStore

    return QdrantDocumentStore(
        url=_qdrant_url(cfg),
        index=_collection_name(corpus_id),
        embedding_dim=int(embedding_dim),
        recreate_index=bool(recreate),
        use_sparse_embeddings=True,
        sparse_idf=True,
        progress_bar=False,
    )


def _raise_qdrant_unavailable(exc: Exception, *, operation: str) -> None:
    from qdrant_client.http.exceptions import ResponseHandlingException

    if isinstance(exc, (ConnectionError, TimeoutError, OSError, ResponseHandlingException)):
        raise DependencyUnavailableError("qdrant", operation) from exc


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
    """Build the pilot embedder from the operator's real embedding configuration.

    The pilot lane must produce vectors under the same contract as the rest of
    the system; it records that contract in its manifest at ingest time and
    search fails closed on a mismatch.
    """
    return Embedder(cfg.embedding, cfg.tokenization)


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
        return "Pilot export is ready. Hydrate the Haystack lane on the Compose-owned Qdrant service before running real OSS retrieval."
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
        qdrant_url=_qdrant_url(await _load_effective_config(corpus_id)),
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
    docling_file_count = 0

    with documents_path.open("w", encoding="utf-8") as handle:
        for rel_path, abs_path in loader.iter_repo_files(str(root)):
            try:
                size_bytes = int(abs_path.stat().st_size)
            except Exception:
                size_bytes = 0
            if size_bytes > max_indexable_bytes:
                skipped_large_files += 1
                continue

            used_docling = abs_path.suffix.lower() in _DOCLING_SUFFIXES
            if used_docling:
                text = _extract_with_docling(abs_path)
            else:
                text = extract_text_for_path(
                    abs_path,
                    parquet_max_rows=int(cfg.indexing.parquet_extract_max_rows),
                    parquet_max_chars=int(cfg.indexing.parquet_extract_max_chars),
                    parquet_max_cell_chars=int(cfg.indexing.parquet_extract_max_cell_chars),
                    parquet_text_columns_only=cfg.indexing.parquet_extract_text_columns_only,
                    parquet_include_column_names=cfg.indexing.parquet_extract_include_column_names,
                )
            if text is None or not text.strip():
                skipped_unreadable_files += 1
                continue

            chunks = chunker.chunk_file(rel_path, text)
            if not chunks:
                skipped_unreadable_files += 1
                continue

            exported_file_count += 1
            if used_docling:
                docling_file_count += 1
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
                        "extraction": "docling" if used_docling else "direct",
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
        "docling_file_count": docling_file_count,
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


def _close_qdrant_document_store(store: Any) -> None:
    """Release the Qdrant client session owned by a Haystack document store.

    QdrantDocumentStore does not expose a public close method; closing its
    lazily-created sync client releases the HTTP session to the Compose-owned
    Qdrant service in a long-running API process.
    """
    client = getattr(store, "_client", None)
    if client is not None:
        client.close()


async def ingest_retrieval_pilot_execution(*, corpus_id: str, repo_path: str, force_rebuild: bool) -> RetrievalPilotIngestResponse:
    _require_execution_packages()

    documents_path = _documents_path(corpus_id)
    manifest_path = _manifest_path(corpus_id)
    if not documents_path.exists() or not manifest_path.exists():
        raise FileNotFoundError("pilot export not found; prepare the pilot export first")

    from haystack import Document
    from haystack.document_stores.types import DuplicatePolicy

    cfg = await _load_effective_config(corpus_id)
    embedder = _pilot_embedder(cfg)

    # Fail closed before touching the store: re-ingesting under a different
    # embedding contract requires an explicit force_rebuild.
    manifest_before = _parse_manifest(corpus_id)
    stored_contract = manifest_before.get("dense_contract")
    if (
        not force_rebuild
        and bool(manifest_before.get("execution_ready") or False)
        and isinstance(stored_contract, dict)
    ):
        current_contract = dense_contract_from_config(cfg)
        if not stored_contract or contract_hash(stored_contract) != contract_hash(current_contract):
            raise EmbeddingContractMismatchError(
                corpus_id=corpus_id,
                expected_contract={
                    "backend": str(stored_contract.get("backend") or ""),
                    "provider": str(stored_contract.get("provider") or ""),
                    "model": str(stored_contract.get("model") or ""),
                    "dimensions": int(stored_contract.get("dimensions") or 0),
                },
                current_contract={
                    "backend": str(current_contract.get("backend") or ""),
                    "provider": str(current_contract.get("provider") or ""),
                    "model": str(current_contract.get("model") or ""),
                    "dimensions": int(current_contract.get("dimensions") or 0),
                },
            )

    store = _pilot_document_store(cfg, corpus_id, embedding_dim=int(embedder.dim), recreate=bool(force_rebuild))

    try:
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
            try:
                embeddings = await embedder.embed_batch(texts)
            except RuntimeError as exc:
                raise DependencyUnavailableError("embedding_provider", "Pilot ingest embedding") from exc
            docs = [
                Document(
                    id=str(raw.get("id") or ""),
                    content=str(raw.get("content") or ""),
                    embedding=list(emb),
                    meta=dict(raw.get("meta") or {}),
                )
                for raw, emb in zip(parsed_batch, embeddings, strict=True)
            ]
            docs = list(_sparse_doc_embedder().run(documents=docs)["documents"])
            try:
                store.write_documents(docs, policy=DuplicatePolicy.OVERWRITE)
            except Exception as exc:
                _raise_qdrant_unavailable(exc, operation="Pilot Qdrant ingest")
                raise
            indexed_document_count += len(docs)
        try:
            stored_document_count = int(store.count_documents())
        except Exception as exc:
            _raise_qdrant_unavailable(exc, operation="Pilot Qdrant ingest")
            raise
    finally:
        _close_qdrant_document_store(store)

    manifest = _parse_manifest(corpus_id)
    dense_contract = dense_contract_from_config(cfg)
    manifest.update(
        {
            "execution_ready": True,
            "indexed_document_count": stored_document_count,
            "last_indexed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "dense_contract": dense_contract,
            "dense_contract_hash": contract_hash(dense_contract),
            "sparse_contract": _sparse_contract(),
            "sparse_contract_hash": contract_hash(_sparse_contract()),
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
    include_vector: bool = True,
    include_sparse: bool = True,
) -> RetrievalPilotSearchResponse:
    _require_execution_packages()
    if not include_vector and not include_sparse:
        raise ValueError("at least one retrieval leg (vector or sparse) must be requested")
    terms = _query_terms(query)
    if not terms:
        raise ValueError("query must include at least one searchable term")

    manifest = _parse_manifest(corpus_id)
    if not bool(manifest.get("execution_ready") or False):
        raise FileNotFoundError("pilot execution lane not ready; ingest the Haystack/Qdrant lane first")

    from haystack_integrations.components.retrievers.qdrant import (
        QdrantEmbeddingRetriever,
        QdrantSparseEmbeddingRetriever,
    )

    cfg = await _load_effective_config(corpus_id)
    stored_contract = manifest.get("dense_contract")
    if not isinstance(stored_contract, dict) or not stored_contract:
        # An execution-ready manifest without a recorded contract predates
        # contract enforcement; its vectors are not trustworthy. Fail closed.
        raise FileNotFoundError(
            "pilot execution lane has no recorded embedding contract; re-ingest with force_rebuild=true"
        )
    if include_sparse:
        stored_sparse = manifest.get("sparse_contract")
        if not isinstance(stored_sparse, dict) or not stored_sparse:
            raise FileNotFoundError(
                "pilot execution lane has no recorded sparse contract; re-ingest with force_rebuild=true"
            )
        if contract_hash(stored_sparse) != contract_hash(_sparse_contract()):
            raise SparseContractMismatchError(
                corpus_id=corpus_id,
                expected_contract=dict(stored_sparse),
                current_contract=_sparse_contract(),
            )
    if include_vector:
        current_contract = dense_contract_from_config(cfg)
        if contract_hash(stored_contract) != contract_hash(current_contract):
            raise EmbeddingContractMismatchError(
                corpus_id=corpus_id,
                expected_contract={
                    "backend": str(stored_contract.get("backend") or ""),
                    "provider": str(stored_contract.get("provider") or ""),
                    "model": str(stored_contract.get("model") or ""),
                    "dimensions": int(stored_contract.get("dimensions") or 0),
                },
                current_contract={
                    "backend": str(current_contract.get("backend") or ""),
                    "provider": str(current_contract.get("provider") or ""),
                    "model": str(current_contract.get("model") or ""),
                    "dimensions": int(current_contract.get("dimensions") or 0),
                },
            )
    embedder = _pilot_embedder(cfg)
    store = _pilot_document_store(cfg, corpus_id, embedding_dim=int(embedder.dim), recreate=False)
    vector_documents: list[Any] = []
    sparse_documents: list[Any] = []
    try:
        # Fix truthfulness after a data-plane reset: Haystack auto-creates a
        # missing collection, so an empty store with a "ready" manifest must
        # read as not-ready instead of returning an empty 200.
        try:
            stored_document_count = int(store.count_documents())
        except Exception as exc:
            _raise_qdrant_unavailable(exc, operation="Pilot Qdrant search")
            raise
        expected_document_count = int(manifest.get("indexed_document_count") or 0)
        if stored_document_count <= 0 and expected_document_count > 0:
            raise FileNotFoundError(
                "pilot execution lane not ready; Qdrant collection is empty or missing — re-ingest the pilot lane"
            )
        if include_vector:
            retriever = QdrantEmbeddingRetriever(document_store=store, top_k=int(top_k))
            try:
                query_embedding = await embedder.embed(query)
            except RuntimeError as exc:
                raise DependencyUnavailableError("embedding_provider", "Pilot search embedding") from exc
            try:
                response = retriever.run(query_embedding=query_embedding, top_k=int(top_k))
            except Exception as exc:
                _raise_qdrant_unavailable(exc, operation="Pilot Qdrant search")
                raise
            vector_documents = list(response.get("documents") or [])
        if include_sparse:
            sparse_retriever = QdrantSparseEmbeddingRetriever(document_store=store, top_k=int(top_k))
            try:
                sparse_query = _sparse_text_embedder().run(text=query)["sparse_embedding"]
            except Exception as exc:
                raise DependencyUnavailableError("embedding_provider", "Pilot sparse query embedding") from exc
            try:
                sparse_response = sparse_retriever.run(query_sparse_embedding=sparse_query, top_k=int(top_k))
            except Exception as exc:
                _raise_qdrant_unavailable(exc, operation="Pilot Qdrant sparse search")
                raise
            sparse_documents = list(sparse_response.get("documents") or [])
    finally:
        _close_qdrant_document_store(store)

    fused, fusion_method = _fuse_pilot_legs(
        cfg,
        vector_documents=vector_documents,
        sparse_documents=sparse_documents,
        include_vector=include_vector,
        include_sparse=include_sparse,
        top_k=int(top_k),
    )

    results = [
        RetrievalPilotSearchResult(
            chunk_id=str(doc.id or ""),
            file_path=str((doc.meta or {}).get("file_path") or ""),
            source_path=str((doc.meta or {}).get("source_path") or ""),
            start_line=int((doc.meta or {}).get("start_line") or 1),
            end_line=int((doc.meta or {}).get("end_line") or 1),
            language=str((doc.meta or {}).get("language") or "") or None,
            score=float(score),
            excerpt=_excerpt(str(doc.content or ""), terms),
            content=str(doc.content or ""),
            source=source,
            metadata={**dict(doc.meta or {}), "legs": legs},
        )
        for doc, score, source, legs in fused
    ]

    status = await build_retrieval_pilot_status(corpus_id=corpus_id, repo_path=repo_path)
    return RetrievalPilotSearchResponse(
        repo_id=corpus_id,
        query=query,
        results=results,
        status=status,
        vector_result_count=len(vector_documents),
        sparse_result_count=len(sparse_documents),
        fusion_method=fusion_method,
    )


def _fuse_pilot_legs(
    cfg: TriBridConfig,
    *,
    vector_documents: list[Any],
    sparse_documents: list[Any],
    include_vector: bool,
    include_sparse: bool,
    top_k: int,
) -> tuple[list[tuple[Any, float, str, list[str]]], str]:
    """Fuse per-leg Qdrant results with the operator's fusion configuration.

    Mirrors the native lane semantics: RRF over rank positions, or
    weighted score fusion, honoring fusion.method/rrf_k/vector_weight/
    sparse_weight. Returns (document, fused_score, primary_source, legs).
    """

    legs: list[tuple[str, list[Any]]] = []
    if include_vector:
        legs.append(("vector", vector_documents))
    if include_sparse:
        legs.append(("sparse", sparse_documents))

    if len(legs) == 1:
        source, docs = legs[0]
        return [(doc, float(doc.score or 0.0), source, [source]) for doc in docs[:top_k]], "single_leg"

    method = str(cfg.fusion.method or "rrf").strip().lower()
    doc_map: dict[str, Any] = {}
    leg_membership: dict[str, list[str]] = {}
    scores: dict[str, float] = {}

    if method == "weighted":
        weights = {"vector": float(cfg.fusion.vector_weight), "sparse": float(cfg.fusion.sparse_weight)}
        for source, docs in legs:
            for doc in docs:
                key = str(doc.id or "")
                doc_map.setdefault(key, doc)
                leg_membership.setdefault(key, []).append(source)
                scores[key] = scores.get(key, 0.0) + float(doc.score or 0.0) * weights[source]
        fusion_method = "weighted"
    else:
        k = int(cfg.fusion.rrf_k)
        for source, docs in legs:
            for rank, doc in enumerate(docs):
                key = str(doc.id or "")
                doc_map.setdefault(key, doc)
                leg_membership.setdefault(key, []).append(source)
                scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
        fusion_method = "rrf"

    ordered = sorted(scores, key=lambda key: scores[key], reverse=True)[:top_k]
    fused: list[tuple[Any, float, str, list[str]]] = []
    for key in ordered:
        membership = leg_membership.get(key, [])
        primary = membership[0] if membership else "vector"
        fused.append((doc_map[key], scores[key], primary, membership))
    return fused, fusion_method


async def answer_retrieval_pilot_execution(
    *,
    corpus_id: str,
    repo_path: str,
    query: str,
    top_k: int,
    include_vector: bool = True,
    include_sparse: bool = True,
    model_override: str = "",
) -> RetrievalPilotAnswerResponse:
    """Grounded answer produced entirely on the pilot lane: hybrid Qdrant
    retrieval, real gateway generation, citations from the retrieved chunks.

    Fails closed: no retrieval-only fallback and no generation without context.
    """

    search = await search_retrieval_pilot_execution(
        corpus_id=corpus_id,
        repo_path=repo_path,
        query=query,
        top_k=top_k,
        include_vector=include_vector,
        include_sparse=include_sparse,
    )
    if not search.results:
        raise ValueError("pilot retrieval returned no results; refusing to generate an ungrounded answer")

    chunks = [
        ChunkMatch(
            chunk_id=result.chunk_id,
            content=result.content,
            file_path=result.file_path,
            start_line=int(result.start_line),
            end_line=int(result.end_line),
            language=result.language,
            score=float(result.score),
            source=result.source,
            metadata=dict(result.metadata or {}),
        )
        for result in search.results
    ]

    cfg = await _load_effective_config(corpus_id)
    context_text = format_context_for_llm(rag_chunks=chunks, recall_chunks=[])
    system_prompt = get_system_prompt(has_rag_context=True, has_recall_context=False, config=cfg.chat)
    route = select_provider_route(config=cfg, model_override=(model_override or "").strip())
    provider_info = ChatProviderInfo(
        kind=route.kind,  # type: ignore[arg-type]
        provider_name=str(route.provider_name),
        model=str(route.model),
        base_url=str(route.base_url) if getattr(route, "base_url", None) else None,
    )

    try:
        generation = await generate_chat_text(
            route=route,
            system_prompt=system_prompt,
            user_message=query,
            images=[],
            image_detail=str(cfg.chat.multimodal.image_detail or "auto"),
            temperature=float(cfg.chat.temperature),
            max_tokens=int(cfg.chat.max_tokens),
            context_text=context_text,
            context_chunks=chunks,
            timeout_s=float(getattr(cfg.ui, "chat_stream_timeout", 120) or 120),
        )
    except Exception as exc:
        raise ChatGenerationError(str(exc)) from exc

    answer_text = str(getattr(generation, "text", "") or "").strip()
    if not answer_text:
        raise ChatGenerationError("LLM returned an empty response")

    return RetrievalPilotAnswerResponse(
        repo_id=corpus_id,
        query=query,
        answer=answer_text,
        citations=chunks,
        provider=provider_info,
        model=str(route.model),
        provider_response_id=(
            str(getattr(generation, "provider_response_id", "") or "").strip() or None
        ),
        llm_used=True,
        vector_result_count=int(search.vector_result_count),
        sparse_result_count=int(search.sparse_result_count),
        fusion_method=str(search.fusion_method or ""),
    )
