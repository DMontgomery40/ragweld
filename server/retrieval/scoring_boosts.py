from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.models.tribrid_config_model import ChunkMatch, TriBridConfig
from server.synthetic.layering import infer_layer_from_path

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]{2,64}")


def _tokenize(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN_RE.finditer(str(text or ""))}


def _is_vendor_path(path: str) -> bool:
    p = str(path or "").replace("\\", "/").lower()
    vendor_markers = (
        "/vendor/",
        "/third_party/",
        "/third-party/",
        "/node_modules/",
        "/site-packages/",
        "/dist-packages/",
        "/.venv/",
    )
    return any(marker in p for marker in vendor_markers)


def _parse_path_boosts(raw: str) -> list[str]:
    return [x.strip().strip("/") for x in str(raw or "").split(",") if x.strip()]


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except Exception:
        return None


def apply_scoring_boosts(
    matches: list[ChunkMatch],
    query: str,
    cfg: TriBridConfig,
    corpus_meta_by_id: dict[str, Any],
) -> list[ChunkMatch]:
    if not matches:
        return []

    query_lc = str(query or "").lower()
    query_terms = _tokenize(query_lc)
    path_boosts = _parse_path_boosts(getattr(cfg.scoring, "path_boosts", ""))
    keyword_boost = float(getattr(cfg.keywords, "keywords_boost", 1.0) or 1.0)
    exact_boost = float(getattr(cfg.scoring, "filename_boost_exact", 1.0) or 1.0)
    partial_boost = float(getattr(cfg.scoring, "filename_boost_partial", 1.0) or 1.0)
    vendor_mode = str(getattr(cfg.scoring, "vendor_mode", "prefer_first_party") or "prefer_first_party").lower()
    vendor_penalty = float(getattr(cfg.layer_bonus, "vendor_penalty", 0.0) or 0.0)
    freshness_bonus = float(getattr(cfg.layer_bonus, "freshness_bonus", 0.0) or 0.0)

    now = datetime.now(UTC)
    boosted: list[ChunkMatch] = []

    for m in matches:
        meta = dict(m.metadata or {})
        corpus_id = str(meta.get("corpus_id") or "")
        corpus_meta = corpus_meta_by_id.get(corpus_id) or {}
        corpus_meta_payload = corpus_meta.get("meta") if isinstance(corpus_meta, dict) else {}
        if not isinstance(corpus_meta_payload, dict):
            corpus_meta_payload = {}

        path_norm = str(m.file_path or "").replace("\\", "/").strip().lower()
        path_parts = [p for p in path_norm.split("/") if p]
        filename = path_parts[-1] if path_parts else ""
        stem = Path(filename).stem.lower() if filename else ""

        multiplier = 1.0
        reasons: list[dict[str, Any]] = []

        if filename in query_terms or stem in query_terms:
            multiplier *= max(1.0, exact_boost)
            reasons.append({"kind": "filename_exact", "value": exact_boost})
        elif any(t for t in query_terms if t and (t in filename or t in path_parts)):
            multiplier *= max(1.0, partial_boost)
            reasons.append({"kind": "filename_partial", "value": partial_boost})

        if path_boosts:
            for boost_path in path_boosts:
                b = boost_path.lower()
                if not b:
                    continue
                if path_norm.startswith(b) or path_norm.startswith(f"/{b}") or f"/{b}/" in f"/{path_norm}/":
                    multiplier *= max(1.0, partial_boost)
                    reasons.append({"kind": "path_boost", "value": partial_boost, "path": b})
                    break

        layer = infer_layer_from_path(m.file_path)
        if layer == "gui":
            lv = float(getattr(cfg.layer_bonus, "gui", 0.0) or 0.0)
            if lv > 0:
                layer_mult = 1.0 + lv
                multiplier *= layer_mult
                reasons.append({"kind": "layer_gui", "value": layer_mult})
        elif layer == "retrieval":
            lv = float(getattr(cfg.layer_bonus, "retrieval", 0.0) or 0.0)
            if lv > 0:
                layer_mult = 1.0 + lv
                multiplier *= layer_mult
                reasons.append({"kind": "layer_retrieval", "value": layer_mult})
        elif layer == "indexing":
            lv = float(getattr(cfg.layer_bonus, "indexer", 0.0) or 0.0)
            if lv > 0:
                layer_mult = 1.0 + lv
                multiplier *= layer_mult
                reasons.append({"kind": "layer_indexing", "value": layer_mult})

        if _is_vendor_path(path_norm):
            if vendor_mode == "prefer_first_party":
                vendor_mult = max(0.1, 1.0 + vendor_penalty)
                multiplier *= vendor_mult
                reasons.append({"kind": "vendor_penalty", "value": vendor_mult})
            elif vendor_mode == "prefer_vendor":
                vendor_mult = 1.0 + abs(vendor_penalty)
                multiplier *= vendor_mult
                reasons.append({"kind": "vendor_preferred", "value": vendor_mult})

        if freshness_bonus > 0:
            file_dt = _parse_dt(meta.get("modified_at") or meta.get("mtime") or meta.get("updated_at"))
            if file_dt is not None:
                age_days = (now - file_dt).total_seconds() / 86400.0
                if age_days <= 30:
                    fresh_mult = 1.0 + freshness_bonus
                    multiplier *= fresh_mult
                    reasons.append({"kind": "fresh_file", "value": fresh_mult})
            else:
                corpus_last_indexed = _parse_dt(corpus_meta.get("last_indexed"))
                if corpus_last_indexed is not None:
                    age_days = (now - corpus_last_indexed).total_seconds() / 86400.0
                    if age_days <= 30:
                        fresh_mult = 1.0 + (freshness_bonus * 0.5)
                        multiplier *= fresh_mult
                        reasons.append({"kind": "fresh_corpus", "value": fresh_mult})

        if keyword_boost > 1.0:
            keywords = corpus_meta_payload.get("keywords")
            if isinstance(keywords, list):
                normalized_kw = [str(k).strip().lower() for k in keywords if str(k).strip()]
            else:
                normalized_kw = []
            if any(kw for kw in normalized_kw if kw and kw in query_lc):
                multiplier *= keyword_boost
                reasons.append({"kind": "keyword", "value": keyword_boost})

        score_before = float(m.score)
        score_after = float(score_before * multiplier)
        new_meta = {
            **meta,
            "layer": layer,
            "score_before_boosts": score_before,
            "score_multiplier": multiplier,
            "score_after_boosts": score_after,
            "boosts_applied": reasons,
        }
        boosted.append(m.model_copy(update={"score": score_after, "metadata": new_meta}))

    boosted.sort(key=lambda item: float(item.score), reverse=True)
    return boosted
