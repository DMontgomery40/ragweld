# Autopilot Status: Eval/Data

## Mission

Replace the current brittle synthetic/eval path with real tooling while keeping current UI surfaces alive.

## This Lane Owns

- `server/synthetic`
- eval dataset generation
- artifact compatibility
- regression harnesses for eval quality
- migration toward Distilabel, Ragas, and Promptfoo

## Compatibility Rule

New generation/eval paths must continue to emit artifacts the current product can consume until the UI is upgraded.

## Gate

- non-empty generated artifacts
- eval run ids created successfully
- compare and drilldown still usable

## Current Priority

Keep this file updated with the replacement milestone, current blocker, and whether the new path is already default.

## Active Milestone (2026-03-26)

Manifest-backed eval/triplet materialization for corpora that already ship a
structured `manifest.json` plus materialized files. This lane now prefers the
corpus manifest adapter over the brittle LLM-only synthetic path for
`eval_dataset`, `triplets`, and `autotune_retrieval`, while preserving the
existing product artifact shapes.

## Current Blocker

This is still a compatibility adapter, not the final OSS generation/eval stack.
`synthetic_data_kit` and the internal provider still need a true
Distilabel/Ragas/Promptfoo-backed end-to-end default once that toolchain is
available in-repo.

## Replacement Path Default?

Partially. Materialized corpora with a usable manifest now bypass the old
LLM-generated eval row path for eval-oriented recipes, but corpora without that
manifest still fall back to the legacy synthetic generator.
