# Autopilot Status: Eval/Data

## Mission

Produce real eval data and real reranker training signal from the indexed
corpus, with one generation path and no compatibility bandages around a bad
dataset.

## This Lane Owns

- `server/synthetic` (grounded QA provider, quality gate, publish)
- eval dataset generation and publication (`data/eval_datasets/<corpus>.json`)
- reranker triplet mining (`server/training/triplet_miner.py`)
- regression harnesses for eval quality (Ragas, Promptfoo)

## Replacement Rule

If the current dataset is bad, replace it and regenerate from the indexed
corpus. Do not preserve a bad dataset for continuity and do not hydrate a
failed generation run from whatever was published before.

## Gate

- a synthetic run that passes the quality gate (`top1 >= synthetic.quality_gate.top1_min`)
- published eval dataset with expected answers, published triplets
- eval run ids created successfully (retrieval metrics + Ragas), Promptfoo run
- compare and drilldown still usable

## Current State (2026-08-22)

- Generation: the `synthetic_data_kit` provider (a package this repository
  never declared or installed) and the seed-hydration fallback are deleted.
  The only provider is `grounded_qa`: gateway-generated question/answer rows
  with a verbatim `evidence_quote` that must be found in the source chunk,
  self-contained-question checks, and the configured judge
  (`docs/references/eval-substrates.md`).
- Triplets: mined from real retrieval traces. Synthetic `triplets` /
  `full_stack` runs retrieve every generated question through the fusion lane
  and pair each expected path with the highest-ranked non-expected documents
  (`learning_reranker_negative_ratio`); `POST /api/reranker/mine` does the
  same from the corpus' latest persisted eval run plus feedback events. The
  same-directory-negative heuristic is gone.
- Execution record for the slice:
  `docs/exec-plans/active/eval-data-lane-2026-08-22.md`.

## Replacement Path Default?

Yes. There is no other path: generation is gateway-backed and grounded, and
triplets only come from retrieval results or explicit feedback.
