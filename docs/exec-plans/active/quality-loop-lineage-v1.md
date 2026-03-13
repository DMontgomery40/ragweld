# Quality-Loop Lineage v1

## Goal

Make lineage real for the quality loop, not just described in copy.

This slice introduces:

- immutable per-asset versions
- corpus-scoped bundles that pin the exact versions used together
- operator aliases (`current`, `promoted`, `baseline`, `canary`) that only target immutable bundles

## Included Assets

- prompt-set snapshots
- config snapshots
- spec snapshots
- model catalog snapshots
- runtime model-set snapshots
- eval dataset versions
- benchmark runs
- eval runs
- synthetic runs and synthetic artifacts
- published synthetic artifacts
- reranker training runs and model artifacts
- agent training runs and model artifacts

## Out Of Scope

- raw corpus contents
- pgvector/Postgres index snapshots
- Neo4j graph state snapshots
- a dedicated Lineage Studio UI

## Storage Model

- `data/lineage/assets/<kind>/<version_id>.json`
- `data/lineage/bundles/<corpus_id>/<bundle_id>.json`
- `data/lineage/aliases/<corpus_id>/<alias>.json`

All versions are content-addressed with canonical JSON or file-byte SHA-256 digests.

## Current v1 Behavior

- prompt/config saves refresh the corpus `current` bundle
- dataset CRUD and synthetic publish flows refresh the corpus `current` bundle
- benchmark/eval/synthetic/training flows capture an input bundle id, then attach final run/artifact refs to a new current bundle
- model promotion moves `promoted`, and because the promoted artifact becomes active runtime state, it also refreshes `current`

## Verification

- generated TS types must include the new lineage and benchmark models
- backend tests must cover dedupe, alias enforcement, current-bundle refresh, and run/publish/promote attachment
- repo verification gates remain unchanged:
  - `uv run python scripts/check_docs_ownership.py`
  - `uv run scripts/check_banned.py`
  - `uv run scripts/validate_types.py`
  - `uv run pytest -q`
  - `npm --prefix web run lint`
  - `npm --prefix web run build`
