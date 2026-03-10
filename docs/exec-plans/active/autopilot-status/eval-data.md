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

## Active Milestone (2026-03-10)

Seed-dataset compatibility fallback for eval-oriented synthetic recipes:
when generated `eval_dataset_json` is empty, hydrate from the corpus seed dataset
(`data/eval_datasets/<corpus>.json`) so the quality gate and downstream eval UI
run on non-empty, product-compatible artifacts.

## Current Blocker

`synthetic_data_kit` still stages inputs but does not execute an OSS-backed
generator/evaluator pipeline end-to-end; this lane still needs a true Distilabel/Ragas/Promptfoo-backed default path.

## Replacement Path Default?

No. The fallback is active as a stabilizer, but internal synthetic generation
is still the default producer when it yields rows.
