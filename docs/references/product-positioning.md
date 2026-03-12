# Product Positioning

Use this page as the repo-local source of truth for public-facing positioning.

## What We Can Honestly Sell Today

- Versioned source-of-truth config
- Versioned prompts and config-driven behavior
- Executable specs
- Manifest-backed training artifacts
- Repo-local system-of-record docs
- Provenance-minded eval and training workflows

## What We Should Not Claim Yet

- Full DSV compliance
- End-to-end version control and lineage across prompts, datasets, evals, and runs
- Complete dataset/eval artifact governance
- Fully realized DSV-style tracking across the whole loop

## Why

The current repo state does not support those stronger claims end to end:

- eval dataset directories are not a clean, governed versioned layer
- synthetic/eval fallback docs explicitly acknowledge missing materialized datasets in some flows
- run artifacts exist conceptually and at runtime, but not as one complete governed versioned system across everything

## Copy Guidance

Prefer wording like:

- Versioned config, prompts, and specs
- Manifest-backed training artifacts
- Provenance-minded eval and training workflows
- Repo-local system of record for agents and operators

Avoid wording like:

- Fully DSV-compliant
- Versioned prompts, datasets, evals, and artifacts end to end
- Complete lineage across the entire model/data/eval lifecycle
