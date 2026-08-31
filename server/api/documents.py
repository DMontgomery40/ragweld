"""Source document evidence viewer: serve the cited file back to the user.

A file is viewable exactly when the corpus indexed it (a ``chunks`` row exists for that path).
The ``documents`` row written at index time is the provenance record (sha256, size, the Docling
markdown for rich kinds); its absence is the typed ``not_captured`` state, never a fallback.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Header, HTTPException, Query, Response
from fastapi.responses import FileResponse

from server.api.dependency_errors import (
    DEPENDENCY_UNAVAILABLE_RESPONSES,
    raise_postgres_unavailable_if_applicable,
)
from server.config import load_config
from server.db.postgres import PostgresClient
from server.indexing.text_extractors import document_kind_for_path
from server.models.index import (
    DocumentKind,
    DocumentNotCapturedDetail,
    DocumentNotCapturedResponse,
    DocumentPdfView,
    DocumentProvenanceCaptured,
    DocumentProvenanceNotCaptured,
    DocumentRichView,
    DocumentTextView,
    DocumentTooLargeDetail,
    DocumentTooLargeResponse,
    DocumentView,
    IndexedDocumentRecord,
)
from server.models.tribrid_config_model import TriBridConfig, validate_corpus_id_component
from server.project_paths import resolve_project_path
from server.services.config_store import CorpusNotFoundError
from server.services.config_store import get_config as load_scoped_config
from server.services.corpus_files import file_etag, resolve_corpus_file, sha256_file
from server.services.pdf_render import (
    NotRenderableError,
    PageOutOfRangeError,
    pdf_page_sizes,
    render_page_png,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"], responses=DEPENDENCY_UNAVAILABLE_RESPONSES)

PageVariant = Literal["page", "thumb"]


@dataclass(frozen=True)
class _Resolved:
    corpus_id: str
    rel_path: str
    abs_path: Path
    kind: DocumentKind
    cfg: TriBridConfig
    record: IndexedDocumentRecord | None


def _not_found(corpus_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"File is not indexed in corpus {corpus_id}")


def _indexed_but_absent(corpus_id: str, rel_path: str) -> HTTPException:
    """The corpus scored this path but the file is not on disk.

    Distinct from `_not_found` because "not indexed" would be a lie: the chunks exist and
    retrieval still cites them. Recall conversations indexed before they were written as
    documents are exactly this state, and telling the operator the opposite sends them
    looking in the wrong place.
    """
    return HTTPException(
        status_code=404,
        detail=(
            f"Corpus {corpus_id} indexed {rel_path}, but its source file is missing on disk. "
            "Index that source again to restore the document."
        ),
    )


def _safe_relative_path(corpus_id: str, path: str) -> str:
    """Corpus-root-relative POSIX path as the indexer stored it; anything else is a 404."""
    text = str(path or "").strip()
    posix = PurePosixPath(text)
    if (
        not text
        or posix.is_absolute()
        or "\\" in text
        or "\x00" in text
        or any(part in {"..", ""} for part in posix.parts)
    ):
        logger.warning("documents: rejected path for corpus %s", corpus_id)
        raise _not_found(corpus_id)
    return posix.as_posix()


async def _resolve(corpus_id: str, path: str, *, boundary: str) -> _Resolved:
    try:
        corpus_id = validate_corpus_id_component(corpus_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rel_path = _safe_relative_path(corpus_id, path)

    global_cfg = load_config()
    pg = PostgresClient(global_cfg.indexing.postgres_url)
    try:
        await pg.connect()
        corpus = await pg.get_corpus(corpus_id)
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise
    if corpus is None:
        raise HTTPException(status_code=404, detail=f"Corpus not found: {corpus_id}")
    try:
        cfg = await load_scoped_config(repo_id=corpus_id)
    except CorpusNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise

    corpus_root = resolve_project_path(str(corpus.get("path") or ""))
    abs_path = resolve_corpus_file(corpus_root, rel_path)

    try:
        # Whether the corpus indexed the path is asked FIRST, so a file the corpus does not
        # know about and a file it does know about but cannot find get different answers.
        if not await pg.file_is_indexed(corpus_id, rel_path):
            raise _not_found(corpus_id)
        if abs_path is None or not abs_path.is_file():
            raise _indexed_but_absent(corpus_id, rel_path)
        record = await pg.get_document(corpus_id, rel_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise_postgres_unavailable_if_applicable(exc, boundary=boundary)
        raise
    return _Resolved(
        corpus_id=corpus_id,
        rel_path=rel_path,
        abs_path=abs_path,
        kind=document_kind_for_path(abs_path),
        cfg=cfg,
        record=record,
    )


def _not_captured(corpus_id: str) -> DocumentProvenanceNotCaptured:
    return DocumentProvenanceNotCaptured(
        message="This file was indexed before page provenance was captured.",
        operator_hint=f"Re-index corpus {corpus_id} to enable page and region highlights.",
    )


@router.get(
    "/corpora/{corpus_id}/documents/view",
    response_model=DocumentView,
    responses={
        409: {"model": DocumentNotCapturedResponse, "description": "Rich document not captured"},
        413: {"model": DocumentTooLargeResponse, "description": "Text document over the limit"},
        **DEPENDENCY_UNAVAILABLE_RESPONSES,
    },
)
async def view_document(
    corpus_id: str, path: str = Query(description="Corpus-root-relative file path")
) -> DocumentView:
    resolved = await _resolve(corpus_id, path, boundary="documents.view")
    byte_size = int(resolved.abs_path.stat().st_size)
    record = resolved.record

    provenance: DocumentProvenanceCaptured | DocumentProvenanceNotCaptured
    if record is not None and record.indexed_at is not None:
        current_sha = await asyncio.to_thread(sha256_file, resolved.abs_path)
        provenance = DocumentProvenanceCaptured(
            extraction=record.extraction,
            sha256=record.sha256,
            byte_size=record.byte_size,
            indexed_at=record.indexed_at,
            stale=current_sha != record.sha256,
        )
    else:
        provenance = _not_captured(resolved.corpus_id)

    content: DocumentTextView | DocumentPdfView | DocumentRichView
    if resolved.kind == "text":
        limit = int(resolved.cfg.document_viewer.max_text_bytes)
        if byte_size > limit:
            detail = DocumentTooLargeDetail(
                corpus_id=resolved.corpus_id,
                file_path=resolved.rel_path,
                byte_size=byte_size,
                max_text_bytes=limit,
                message="The file is larger than the viewer's text limit.",
                operator_hint="Raise document_viewer.max_text_bytes or open the original file.",
            )
            raise HTTPException(status_code=413, detail=detail.model_dump(mode="json"))
        # Decode exactly as the indexer does so line numbers agree.
        text = await asyncio.to_thread(
            lambda: resolved.abs_path.read_bytes().decode("utf-8", errors="ignore")
        )
        content = DocumentTextView(text=text, line_count=text.count("\n") + 1 if text else 0)
    elif resolved.kind == "pdf":
        try:
            sizes = await asyncio.to_thread(pdf_page_sizes, resolved.abs_path)
        except NotRenderableError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        content = DocumentPdfView(page_count=len(sizes), page_sizes=sizes)
    else:
        if record is None or record.markdown is None:
            missing = DocumentNotCapturedDetail(
                corpus_id=resolved.corpus_id,
                file_path=resolved.rel_path,
                message="No captured markdown exists for this document.",
                operator_hint=(
                    f"Re-index corpus {resolved.corpus_id}; rich documents are viewable only "
                    "from the markdown captured at index time."
                ),
            )
            raise HTTPException(status_code=409, detail=missing.model_dump(mode="json"))
        content = DocumentRichView(markdown=record.markdown)

    return DocumentView(
        corpus_id=resolved.corpus_id,
        file_path=resolved.rel_path,
        byte_size=byte_size,
        content=content,
        provenance=provenance,
    )


@router.get(
    "/corpora/{corpus_id}/documents/page",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "Rendered page"},
        304: {"description": "Not modified"},
        415: {"description": "Not a renderable PDF"},
        **DEPENDENCY_UNAVAILABLE_RESPONSES,
    },
)
async def render_document_page(
    corpus_id: str,
    path: str = Query(description="Corpus-root-relative file path"),
    page: int = Query(ge=1, description="1-based page number"),
    variant: PageVariant = "page",
    if_none_match: str | None = Header(default=None),
) -> Response:
    resolved = await _resolve(corpus_id, path, boundary="documents.page")
    if resolved.kind != "pdf":
        raise HTTPException(status_code=415, detail="Only PDF documents render pages")
    viewer = resolved.cfg.document_viewer
    scale = float(viewer.page_render_scale if variant == "page" else viewer.thumbnail_render_scale)
    etag = file_etag(resolved.abs_path, f"p{page}", variant, f"s{scale}")
    headers = {"ETag": etag, "Cache-Control": "private, max-age=86400"}
    if if_none_match and etag in {tag.strip() for tag in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    try:
        png = await asyncio.to_thread(render_page_png, resolved.abs_path, page, scale)
    except PageOutOfRangeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except NotRenderableError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc
    return Response(content=png, media_type="image/png", headers=headers)


@router.get(
    "/corpora/{corpus_id}/documents/raw",
    response_class=FileResponse,
    responses={200: {"description": "Original file bytes"}, **DEPENDENCY_UNAVAILABLE_RESPONSES},
)
async def raw_document(
    corpus_id: str, path: str = Query(description="Corpus-root-relative file path")
) -> FileResponse:
    resolved = await _resolve(corpus_id, path, boundary="documents.raw")
    name = resolved.abs_path.name
    ascii_name = name.encode("ascii", "ignore").decode("ascii").replace('"', "") or "document"
    disposition = "inline" if resolved.kind == "pdf" else "attachment"
    media_type = "application/pdf" if resolved.kind == "pdf" else "application/octet-stream"
    headers = {
        "Content-Disposition": (
            f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
        ),
        # Never let a corpus file execute as a page on the API origin (stored XSS via HTML).
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    return FileResponse(resolved.abs_path, media_type=media_type, headers=headers)
