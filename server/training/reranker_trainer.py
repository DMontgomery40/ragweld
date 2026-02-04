from __future__ import annotations

import json
import math
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Triplet:
    query: str
    positive: str
    negative: str


@dataclass(frozen=True)
class MaterializedTriplet:
    query: str
    positive_text: str
    negative_text: str


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []

    def _gen() -> Iterable[dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                ln = line.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj

    return _gen()


def load_triplets(path: Path, *, limit: int | None = None) -> list[Triplet]:
    out: list[Triplet] = []
    for obj in _iter_jsonl(path):
        q = obj.get("query")
        p = obj.get("positive")
        n = obj.get("negative")
        if not isinstance(q, str) or not isinstance(p, str) or not isinstance(n, str):
            continue
        q = q.strip()
        p = p.strip()
        n = n.strip()
        if not q or not p or not n:
            continue
        out.append(Triplet(query=q, positive=p, negative=n))
        if limit is not None and limit > 0 and len(out) >= limit:
            break
    return out


def _resolve_doc_path(*, corpus_root: Path, doc_id: str) -> Path | None:
    p = Path(str(doc_id or "").strip())
    if not str(p):
        return None

    # Security: triplets must only reference corpus-relative paths. Absolute paths and
    # path traversal (.. segments) are rejected so training cannot read arbitrary files.
    if p.is_absolute():
        return None

    try:
        root = corpus_root.resolve()
        resolved = (corpus_root / p).resolve()
    except Exception:
        return None

    try:
        resolved.relative_to(root)
    except Exception:
        return None
    return resolved


def _read_text(path: Path, *, max_chars: int) -> str:
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if max_chars <= 0:
        return ""
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars]


def materialize_triplets(
    triplets: list[Triplet],
    *,
    corpus_root: Path,
    snippet_chars: int,
    max_triplets: int | None = None,
) -> tuple[list[MaterializedTriplet], dict[str, int]]:
    """Load file contents for (positive, negative) doc_ids and return materialized triplets.

    Returns (materialized_triplets, stats) where stats includes counts of skipped items.
    """
    out: list[MaterializedTriplet] = []
    missing_pos = 0
    missing_neg = 0
    empty_pos = 0
    empty_neg = 0

    for t in triplets:
        pos_path = _resolve_doc_path(corpus_root=corpus_root, doc_id=t.positive)
        neg_path = _resolve_doc_path(corpus_root=corpus_root, doc_id=t.negative)

        if pos_path is None:
            missing_pos += 1
            continue
        if neg_path is None:
            missing_neg += 1
            continue

        if not pos_path.exists():
            missing_pos += 1
            continue
        if not neg_path.exists():
            missing_neg += 1
            continue

        pos_text = _read_text(pos_path, max_chars=snippet_chars).strip()
        neg_text = _read_text(neg_path, max_chars=snippet_chars).strip()
        if not pos_text:
            empty_pos += 1
            continue
        if not neg_text:
            empty_neg += 1
            continue

        out.append(MaterializedTriplet(query=t.query, positive_text=pos_text, negative_text=neg_text))
        if max_triplets is not None and max_triplets > 0 and len(out) >= max_triplets:
            break

    return out, {
        "triplets_in": len(triplets),
        "triplets_out": len(out),
        "missing_positive": missing_pos,
        "missing_negative": missing_neg,
        "empty_positive": empty_pos,
        "empty_negative": empty_neg,
    }


def _pair_metrics_from_scores(pos_scores: list[float], neg_scores: list[float]) -> dict[str, float]:
    if not pos_scores or not neg_scores or len(pos_scores) != len(neg_scores):
        return {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}

    rr_vals: list[float] = []
    ndcg_vals: list[float] = []
    ap_vals: list[float] = []

    for ps, ns in zip(pos_scores, neg_scores, strict=True):
        rank: float
        if ps > ns:
            rank = 1.0
        elif ps < ns:
            rank = 2.0
        else:
            # Stable tie handling (midpoint)
            rank = 1.5

        rr = 1.0 / float(rank)
        rr_vals.append(rr)
        ap_vals.append(rr)

        # One relevant item => nDCG depends only on the rank.
        # rank=1 => 1.0; rank=2 => 1/log2(3); rank=1.5 => linear interpolation.
        if rank == 1:
            ndcg = 1.0
        elif rank == 2:
            ndcg = 1.0 / math.log2(3.0)
        else:
            ndcg = (1.0 + (1.0 / math.log2(3.0))) / 2.0
        ndcg_vals.append(float(ndcg))

    return {
        "mrr": float(sum(rr_vals) / len(rr_vals)),
        "ndcg": float(sum(ndcg_vals) / len(ndcg_vals)),
        "map": float(sum(ap_vals) / len(ap_vals)),
    }


def _safe_rm_tree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass


def train_pairwise_reranker(
    *,
    base_model: str,
    output_dir: Path,
    triplets: list[MaterializedTriplet],
    epochs: int,
    batch_size: int,
    lr: float,
    warmup_ratio: float,
    max_length: int,
    dev_split: float = 0.1,
    seed: int = 0,
    emit: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, object]:
    """Train a local cross-encoder on pairwise triplets and save to output_dir.

    This is intentionally CPU-first and lightweight. It emits best-effort progress
    callbacks for UI streaming (SSE) via `emit`.
    """
    if not triplets:
        raise ValueError("No materialized triplets to train on")

    # Lazy imports (keep API startup fast)
    import torch
    from torch.utils.data import DataLoader, Dataset
    from torch.optim import AdamW
    from transformers import AutoModelForSequenceClassification, AutoTokenizer, get_linear_schedule_with_warmup

    def _binary_logit(logits: torch.Tensor) -> torch.Tensor:
        # Support common cross-encoder heads:
        # - num_labels=1: logits shape (batch, 1)
        # - num_labels=2: logits shape (batch, 2) (use class1-class0 logit)
        if logits.ndim == 2 and int(logits.shape[1]) == 1:
            return logits[:, 0]
        if logits.ndim == 2 and int(logits.shape[1]) == 2:
            return logits[:, 1] - logits[:, 0]
        if logits.ndim == 1:
            return logits
        raise ValueError(f"Unsupported logits shape for binary scoring: {tuple(int(x) for x in logits.shape)}")

    r = random.Random(int(seed))
    shuffled = list(triplets)
    r.shuffle(shuffled)

    dev_split = float(dev_split)
    dev_split = max(0.0, min(0.5, dev_split))
    dev_n = int(round(len(shuffled) * dev_split))
    dev_n = max(1, dev_n) if len(shuffled) >= 10 else min(dev_n, max(0, len(shuffled) - 1))
    dev = shuffled[:dev_n] if dev_n > 0 else []
    train = shuffled[dev_n:] if dev_n > 0 else shuffled

    if not train:
        train = shuffled
        dev = []

    tokenizer = AutoTokenizer.from_pretrained(base_model, use_fast=True)  # type: ignore[no-untyped-call]
    model = AutoModelForSequenceClassification.from_pretrained(base_model)
    model.train()

    device = torch.device("cpu")
    model.to(device)

    # Expand triplets into binary pairs.
    pairs: list[tuple[str, str, float]] = []
    for t in train:
        pairs.append((t.query, t.positive_text, 1.0))
        pairs.append((t.query, t.negative_text, 0.0))

    dev_pairs: list[tuple[str, str, float]] = []
    for t in dev:
        dev_pairs.append((t.query, t.positive_text, 1.0))
        dev_pairs.append((t.query, t.negative_text, 0.0))

    class _Pairs(Dataset[dict[str, torch.Tensor]]):
        def __init__(self, rows: list[tuple[str, str, float]]):
            self._rows = rows

        def __len__(self) -> int:
            return len(self._rows)

        def __getitem__(self, idx: int) -> dict[str, torch.Tensor]:
            q, d, y = self._rows[idx]
            enc = tokenizer(
                q,
                d,
                truncation=True,
                max_length=int(max_length),
                padding="max_length",
                return_tensors="pt",
            )
            item: dict[str, torch.Tensor] = {k: v.squeeze(0) for k, v in enc.items()}
            item["labels"] = torch.tensor(float(y), dtype=torch.float32)
            return item

    def _collate(batch: list[dict[str, torch.Tensor]]) -> dict[str, torch.Tensor]:
        keys = [k for k in batch[0].keys() if k != "labels"]
        out: dict[str, torch.Tensor] = {}
        for k in keys:
            out[k] = torch.stack([b[k] for b in batch])
        out["labels"] = torch.stack([b["labels"] for b in batch])
        return out

    train_loader = DataLoader(_Pairs(pairs), batch_size=int(batch_size), shuffle=True, collate_fn=_collate)

    total_steps = max(1, len(train_loader) * int(epochs))
    warmup_steps = int(round(total_steps * float(warmup_ratio)))

    optimizer = AdamW(model.parameters(), lr=float(lr))
    scheduler = get_linear_schedule_with_warmup(  # type: ignore[no-untyped-call]
        optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=total_steps,
    )
    loss_fn = torch.nn.BCEWithLogitsLoss()

    def _score(rows: list[tuple[str, str]]) -> list[float]:
        model.eval()
        scores: list[float] = []
        with torch.no_grad():
            for q, d in rows:
                enc = tokenizer(
                    q,
                    d,
                    truncation=True,
                    max_length=int(max_length),
                    padding="max_length",
                    return_tensors="pt",
                )
                enc = {k: v.to(device) for k, v in enc.items()}
                logits = model(**enc).logits
                scores.append(float(_binary_logit(logits).view(-1)[0].cpu().item()))
        model.train()
        return scores

    history: list[dict[str, float]] = []

    global_step = 0
    best_primary: float | None = None
    best_step: int | None = None

    for epoch_idx in range(int(epochs)):
        for batch in train_loader:
            global_step += 1
            labels = batch.pop("labels")
            labels_t = labels.to(device)
            batch_t = {k: v.to(device) for k, v in batch.items()}

            out = model(**batch_t)
            logits = _binary_logit(out.logits).view(-1)
            loss = loss_fn(logits, labels_t.view(-1))

            loss.backward()
            optimizer.step()
            scheduler.step()
            optimizer.zero_grad(set_to_none=True)

            if emit and (global_step == 1 or global_step % 10 == 0 or global_step == total_steps):
                pct = (float(global_step) / float(total_steps)) * 100.0
                emit(
                    "progress",
                    {
                        "step": int(global_step),
                        "epoch": float(epoch_idx) + (float(global_step % max(1, len(train_loader))) / float(max(1, len(train_loader)))),
                        "percent": float(min(100.0, max(0.0, pct))),
                        "message": f"step {global_step}/{total_steps} loss={float(loss.detach().cpu().item()):.4f}",
                    },
                )

        # End-of-epoch evaluation on dev (proxy metrics).
        if dev:
            pos_rows = [(t.query, t.positive_text) for t in dev]
            neg_rows = [(t.query, t.negative_text) for t in dev]
            pos_scores = _score(pos_rows)
            neg_scores = _score(neg_rows)
            metrics = _pair_metrics_from_scores(pos_scores, neg_scores)
        else:
            metrics = {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}

        history.append({k: float(v) for k, v in metrics.items()})
        primary_val = float(metrics.get("mrr") or 0.0)
        if best_primary is None or primary_val > best_primary:
            best_primary = primary_val
            best_step = global_step

        if emit:
            emit(
                "metrics",
                {
                    "step": int(global_step),
                    "epoch": float(epoch_idx + 1),
                    "metrics": {k: float(v) for k, v in metrics.items()},
                },
            )

    # Save (atomic-ish): write to temp dir then move into place.
    tmp = output_dir.parent / f".tmp_{output_dir.name}"
    _safe_rm_tree(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(tmp))
    tokenizer.save_pretrained(str(tmp))

    _safe_rm_tree(output_dir)
    tmp.rename(output_dir)

    # Return training summary for callers to persist in run.json and logs.
    final_metrics = history[-1] if history else {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}
    return {
        "ok": True,
        "train_triplets": int(len(train)),
        "dev_triplets": int(len(dev)),
        "total_steps": int(total_steps),
        "history": history,
        "best_step": int(best_step or 0),
        "best_mrr": float(best_primary or 0.0),
        "final": final_metrics,
        "output_dir": str(output_dir),
    }


def evaluate_pairwise_reranker(
    *,
    model_dir: Path,
    triplets: list[MaterializedTriplet],
    max_length: int,
) -> dict[str, float]:
    """Evaluate a saved cross-encoder on pairwise triplets (proxy metrics)."""
    if not triplets:
        return {"mrr": 0.0, "ndcg": 0.0, "map": 0.0}

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    def _binary_logit(logits: torch.Tensor) -> torch.Tensor:
        if logits.ndim == 2 and int(logits.shape[1]) == 1:
            return logits[:, 0]
        if logits.ndim == 2 and int(logits.shape[1]) == 2:
            return logits[:, 1] - logits[:, 0]
        if logits.ndim == 1:
            return logits
        raise ValueError(f"Unsupported logits shape for binary scoring: {tuple(int(x) for x in logits.shape)}")

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir), use_fast=True)  # type: ignore[no-untyped-call]
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    model.eval()
    device = torch.device("cpu")
    model.to(device)

    def _score(rows: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        with torch.no_grad():
            for q, d in rows:
                enc = tokenizer(
                    q,
                    d,
                    truncation=True,
                    max_length=int(max_length),
                    padding="max_length",
                    return_tensors="pt",
                )
                enc = {k: v.to(device) for k, v in enc.items()}
                logits = model(**enc).logits
                scores.append(float(_binary_logit(logits).view(-1)[0].cpu().item()))
        return scores

    pos_rows = [(t.query, t.positive_text) for t in triplets]
    neg_rows = [(t.query, t.negative_text) for t in triplets]
    pos_scores = _score(pos_rows)
    neg_scores = _score(neg_rows)
    return _pair_metrics_from_scores(pos_scores, neg_scores)
