from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import EvalDatasetItem

_MESSAGE_DIVIDER = re.compile(r"^\s*Message\s*$", re.IGNORECASE)
_SEPARATOR_LINE = re.compile(r"^\s*-{3,}\s*$")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class MaterializedCorpusRow:
    materialized_filename: str
    source_filename: str
    document_id: str
    from_address: str
    to_address: str
    subject: str
    timestamp_iso: str
    message_preview: str


def _normalize_text(value: Any) -> str:
    text = _WHITESPACE_RE.sub(" ", str(value or "")).strip()
    return text


def _trim(text: str, limit: int) -> str:
    value = _normalize_text(text)
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def _clean_label(value: str, *, fallback: str) -> str:
    cleaned = _normalize_text(value)
    if not cleaned:
        return fallback
    return cleaned


def _extract_message_preview(message_path: Path) -> str:
    try:
        lines = message_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""

    in_message = False
    saw_divider = False
    for raw_line in lines:
        line = raw_line.strip()
        if not in_message:
            if _MESSAGE_DIVIDER.match(line):
                in_message = True
            continue
        if not saw_divider:
            if _SEPARATOR_LINE.match(line):
                saw_divider = True
            continue
        if line:
            return _trim(line, 120)
    return ""


def load_materialized_corpus_rows(repo_path: str | Path) -> list[MaterializedCorpusRow]:
    root = Path(repo_path).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.exists():
        return []

    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []

    rows_payload = raw.get("rows")
    if not isinstance(rows_payload, list):
        return []

    rows: list[MaterializedCorpusRow] = []
    for item in rows_payload:
        if not isinstance(item, dict):
            continue
        materialized_filename = _normalize_text(item.get("materialized_filename"))
        if not materialized_filename:
            continue
        message_path = root / materialized_filename
        rows.append(
            MaterializedCorpusRow(
                materialized_filename=materialized_filename,
                source_filename=_normalize_text(item.get("source_filename")),
                document_id=_normalize_text(item.get("document_id")),
                from_address=_normalize_text(item.get("from_address")),
                to_address=_normalize_text(item.get("to_address")),
                subject=_normalize_text(item.get("subject")),
                timestamp_iso=_normalize_text(item.get("timestamp_iso")),
                message_preview=_extract_message_preview(message_path) if message_path.exists() else "",
            )
        )
    return rows


def build_materialized_candidate_paths(rows: list[MaterializedCorpusRow]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for row in rows:
        path = _normalize_text(row.materialized_filename)
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def _build_expected_answer(row: MaterializedCorpusRow) -> str:
    parts = [
        f"Subject: {_clean_label(row.subject, fallback='(no subject)')}",
        f"From: {_clean_label(row.from_address, fallback='unknown sender')}",
        f"To: {_clean_label(row.to_address, fallback='unknown recipient')}",
    ]
    if row.timestamp_iso:
        parts.append(f"Timestamp: {row.timestamp_iso}")
    if row.message_preview:
        parts.append(f"Preview: {row.message_preview}")
    return _trim("; ".join(parts), 400)


def _question_templates(row: MaterializedCorpusRow) -> list[str]:
    subject = _clean_label(row.subject, fallback="(no subject)")
    sender = _clean_label(row.from_address, fallback="unknown sender")
    recipient = _clean_label(row.to_address, fallback="unknown recipient")
    timestamp = row.timestamp_iso
    preview = row.message_preview
    document_id = row.document_id
    source_filename = _clean_label(row.source_filename, fallback="unknown source file")

    candidates = [
        f'Which email from {sender} to {recipient} has the subject "{subject}"?',
        f'Find the message sent to {recipient} from {sender} with subject "{subject}".',
    ]
    if timestamp:
        candidates.append(f'Which email from {sender} to {recipient} was sent at {timestamp}?')
    if preview:
        candidates.append(f'Which email with subject "{subject}" includes the line "{preview}"?')
        candidates.append(f'Find the message from {sender} that says "{preview}".')
    if document_id:
        candidates.append(f'Which materialized email row from document {document_id} has subject "{subject}"?')
    if source_filename:
        candidates.append(f'Which email from source file "{source_filename}" has subject "{subject}"?')

    out: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        question = _trim(candidate, 180)
        if not question or question in seen:
            continue
        seen.add(question)
        out.append(question)
    return out


def build_materialized_eval_items(
    *,
    rows: list[MaterializedCorpusRow],
    max_pairs: int,
    pairs_per_source: int,
    include_expected_answer: bool,
    include_tags: bool,
) -> list[EvalDatasetItem]:
    if max_pairs <= 0 or pairs_per_source <= 0:
        return []

    tags = ["synthetic", "source:materialized_manifest", "artifact:eval_dataset"] if include_tags else []
    items: list[EvalDatasetItem] = []
    for row in rows:
        expected_path = _normalize_text(row.materialized_filename)
        if not expected_path:
            continue
        expected_answer = _build_expected_answer(row) if include_expected_answer else None
        for question in _question_templates(row)[:pairs_per_source]:
            items.append(
                EvalDatasetItem(
                    question=question,
                    expected_paths=[expected_path],
                    expected_answer=expected_answer,
                    tags=list(tags),
                    created_at=datetime.now(UTC),
                )
            )
            if len(items) >= max_pairs:
                return items
    return items
