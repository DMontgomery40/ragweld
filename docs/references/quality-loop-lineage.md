# Quality-Loop Lineage

This page is the engineering source of truth for lineage/governance in the v1 quality loop.

## What Exists In v1

- immutable per-asset versions for quality-loop assets
- corpus-scoped bundles that pin the exact set of versions used together
- mutable aliases that only point to immutable bundles

## Bundle Shape

Each bundle pins one current version of:

- prompt set
- config snapshot
- spec snapshot
- model catalog snapshot
- runtime model set
- eval dataset version when available

Each bundle can also attach:

- benchmark runs
- eval runs
- synthetic runs and artifacts
- published synthetic artifacts
- reranker training runs and model artifacts
- agent training runs and model artifacts

## Alias Rules

- `current`: refreshed by prompt/config saves and by publish/promote/run attachment flows
- `promoted`: moved when an active model artifact is promoted
- `baseline`: explicit operator action
- `canary`: explicit operator action

Aliases never point to mutable runtime state directly.

## Non-Goals

This does **not** yet claim:

- raw corpus versioning
- Postgres/pgvector snapshot governance
- Neo4j graph snapshot governance
- full end-to-end DSV compliance across every artifact in the platform
