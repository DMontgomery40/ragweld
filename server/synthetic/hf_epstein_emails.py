from __future__ import annotations

import json
import re
import shutil
from datetime import UTC, datetime
from html import unescape
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from server.models.tribrid_config_model import EvalDatasetItem

HF_DATASET = "to-be/epstein-emails"
HF_CONFIG = "default"
HF_SPLIT = "train"
HF_DATASETS_SERVER = "https://datasets-server.huggingface.co"
GENERIC_SUBJECTS = {
    "",
    "email subject of the thread",
    "re:",
    "fwd:",
}

_BREAK_TAG_RE = re.compile(r"(?i)<\s*(?:br|/p|/div|/li|/tr|/td|/th|hr)\s*/?\s*>")
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")


def _json_get(url: str) -> dict[str, Any]:
    with urlopen(url) as resp:  # noqa: S310 - controlled HF datasets server endpoint
        return json.loads(resp.read().decode("utf-8"))


def fetch_dataset_info(
    *,
    dataset: str = HF_DATASET,
    config: str = HF_CONFIG,
    split: str = HF_SPLIT,
) -> dict[str, Any]:
    query = urlencode({"dataset": dataset, "config": config, "split": split})
    payload = _json_get(f"{HF_DATASETS_SERVER}/info?{query}")
    dataset_info = payload.get("dataset_info")
    if not isinstance(dataset_info, dict):
        raise RuntimeError(f"Missing dataset_info for {dataset}")
    return dataset_info


def fetch_dataset_rows(
    *,
    dataset: str = HF_DATASET,
    config: str = HF_CONFIG,
    split: str = HF_SPLIT,
    offset: int,
    length: int,
) -> list[dict[str, Any]]:
    length = max(1, min(int(length), 100))
    query = urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": offset,
            "length": length,
        }
    )
    payload = _json_get(f"{HF_DATASETS_SERVER}/rows?{query}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError(f"Missing rows payload for {dataset}")
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = row.get("row")
        if isinstance(item, dict):
            out.append(item)
    return out


def iter_dataset_rows(
    *,
    dataset: str = HF_DATASET,
    config: str = HF_CONFIG,
    split: str = HF_SPLIT,
    batch_size: int = 100,
    limit: int | None = None,
) -> Iterable[dict[str, Any]]:
    info = fetch_dataset_info(dataset=dataset, config=config, split=split)
    splits = info.get("splits") or {}
    split_info = splits.get(split) if isinstance(splits, dict) else None
    if not isinstance(split_info, dict):
        raise RuntimeError(f"Missing split metadata for {dataset}:{split}")
    total = int(split_info.get("num_examples") or 0)
    if limit is not None:
        total = min(total, int(limit))

    for offset in range(0, total, batch_size):
        length = min(batch_size, total - offset)
        for row in fetch_dataset_rows(
            dataset=dataset,
            config=config,
            split=split,
            offset=offset,
            length=length,
        ):
            yield row


def strip_html_message(value: str | None) -> str:
    text = unescape(str(value or "")).replace("\xa0", " ")
    if not text.strip():
        return ""
    text = _BREAK_TAG_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = text.replace("\r", "\n")
    text = _SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    text = _MULTI_NL_RE.sub("\n\n", text)
    return text.strip()


def _safe_source_stem(row: dict[str, Any]) -> str:
    source_filename = str(row.get("source_filename") or "").strip()
    if source_filename:
        return Path(source_filename).stem
    document_id = str(row.get("document_id") or "").strip()
    if document_id:
        return document_id
    return f"email-{int(row.get('id') or 0):06d}"


def materialized_filename(row: dict[str, Any]) -> str:
    stem = _safe_source_stem(row)
    message_order = int(row.get("message_order") or 0)
    row_id = int(row.get("id") or 0)
    return f"{stem}__msg_{message_order:03d}__row_{row_id:06d}.txt"


def render_materialized_email(row: dict[str, Any], *, dataset: str = HF_DATASET) -> str:
    message_text = strip_html_message(str(row.get("message_html") or ""))
    timestamp_iso = str(row.get("timestamp_iso") or "").strip()
    lines = [
        f"Source dataset: {dataset}",
        f"Source filename: {str(row.get('source_filename') or '').strip()}",
        f"Document id: {str(row.get('document_id') or '').strip()}",
        f"Email document id: {str(row.get('email_document_id') or '').strip()}",
        f"Message order: {int(row.get('message_order') or 0)}",
        f"Timestamp ISO: {timestamp_iso}",
        f"From: {str(row.get('from_address') or '').strip()}",
        f"To: {str(row.get('to_address') or '').strip()}",
        f"Other recipients: {str(row.get('other_recipients') or '').strip()}",
        f"Subject: {str(row.get('subject') or '').strip()}",
        "",
        "Message",
        "-------",
        message_text or "(no extracted message body available)",
        "",
    ]
    return "\n".join(lines)


def _is_generic_subject(subject: str) -> bool:
    normalized = str(subject or "").strip().lower()
    return normalized in GENERIC_SUBJECTS


def build_eval_item(
    row: dict[str, Any],
    *,
    filename: str,
    variant: int = 0,
    dataset: str = HF_DATASET,
) -> EvalDatasetItem | None:
    subject = str(row.get("subject") or "").strip()
    from_address = str(row.get("from_address") or "").strip()
    to_address = str(row.get("to_address") or "").strip()
    timestamp_iso = str(row.get("timestamp_iso") or "").strip()

    if not subject or _is_generic_subject(subject):
        return None
    if not from_address or not to_address:
        return None

    day = timestamp_iso[:8]
    question_type = "sender"
    if variant % 3 == 1:
        question = f'Who received the email with subject "{subject}" from {from_address}?'
        expected_answer = to_address
        question_type = "recipient"
    elif variant % 3 == 2 and len(day) == 8 and day.isdigit():
        date_display = f"{day[0:4]}-{day[4:6]}-{day[6:8]}"
        question = f"What was the subject of the email sent from {from_address} to {to_address} on {date_display}?"
        expected_answer = subject
        question_type = "subject"
    else:
        question = f'Who sent the email with subject "{subject}" to {to_address}?'
        expected_answer = from_address

    return EvalDatasetItem(
        question=question,
        expected_paths=[filename],
        expected_answer=expected_answer,
        tags=["huggingface", dataset.replace("/", ":"), "email", question_type],
        created_at=datetime.now(UTC),
    )


def materialize_epstein_email_dataset(
    *,
    output_dir: Path,
    eval_output_path: Path | None = None,
    dataset: str = HF_DATASET,
    config: str = HF_CONFIG,
    split: str = HF_SPLIT,
    batch_size: int = 500,
    max_eval_rows: int = 200,
    limit: int | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    if replace and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if eval_output_path is not None:
        eval_output_path.parent.mkdir(parents=True, exist_ok=True)

    eval_items: list[EvalDatasetItem] = []
    manifest_rows: list[dict[str, Any]] = []
    written = 0

    for row in iter_dataset_rows(
        dataset=dataset,
        config=config,
        split=split,
        batch_size=batch_size,
        limit=limit,
    ):
        filename = materialized_filename(row)
        output_path = output_dir / filename
        output_path.write_text(render_materialized_email(row, dataset=dataset), encoding="utf-8")
        written += 1

        manifest_rows.append(
            {
                "row_id": int(row.get("id") or 0),
                "document_id": str(row.get("document_id") or "").strip(),
                "source_filename": str(row.get("source_filename") or "").strip(),
                "materialized_filename": filename,
                "subject": str(row.get("subject") or "").strip(),
                "from_address": str(row.get("from_address") or "").strip(),
                "to_address": str(row.get("to_address") or "").strip(),
                "timestamp_iso": str(row.get("timestamp_iso") or "").strip(),
            }
        )

        if len(eval_items) < max_eval_rows:
            item = build_eval_item(
                row,
                filename=filename,
                variant=len(eval_items),
                dataset=dataset,
            )
            if item is not None:
                eval_items.append(item)

    manifest = {
        "dataset": dataset,
        "config": config,
        "split": split,
        "materialized_at": datetime.now(UTC).isoformat(),
        "written_files": written,
        "eval_rows": len(eval_items),
        "rows": manifest_rows,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    if eval_output_path is not None:
        eval_output_path.write_text(
            json.dumps([item.model_dump(mode="json") for item in eval_items], indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return manifest
