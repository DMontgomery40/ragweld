# Autopilot Status: Eval/Data

## Mission

Replace the current brittle synthetic/eval lane with a better corpus and better data, not another compatibility bandage around a bad dataset.

## This Lane Owns

- `server/synthetic`
- eval dataset generation
- replacement corpus sourcing and materialization
- regression harnesses for eval quality
- migration toward Distilabel, Ragas, and Promptfoo

## Replacement Rule

If the current dataset is bad, replace it and fresh-index the better one.

- Do not preserve a bad dataset for continuity.
- Do not treat corpus compatibility with the old House Oversight dump as a design goal.
- On this branch, better source wins and the worse path should stop being the active truth.

## Gate

- non-empty generated artifacts
- eval run ids created successfully
- compare and drilldown still usable

## Current Priority

Keep this file updated with the replacement milestone, current blocker, and whether the new path is already default.

## Active Milestone (2026-03-26)

Replace the current `epstein-files-1` source dataset with a fresh Hugging Face
Epstein corpus and regenerate eval data from that replacement source before any
training continues.

## Current Blocker

The mounted 18-row synthetic artifact for `epstein-files-1` is garbage:

- it only hits `top1_accuracy=0.0556` in real Eval Analysis
- many rows are over-pinned to a single page/file identity
- several rows are underspecified or semantically wrong

The next honest move is to source a better Epstein dataset, materialize it as a
fresh corpus, repoint the active corpus path, and reindex.

That replacement path now assumes:

- OpenAI dense embeddings
- official Neo4j GraphRAG semantic extraction
- no reuse of the old heuristic semantic-KG path

## Replacement Path Default?

Partially. The replacement corpus/materialization path is now the active target,
and the graph/indexing target for that lane is OpenAI embeddings plus official
Neo4j GraphRAG. Any remaining heuristic semantic-KG references should be treated
as stale branch debt, not the desired end state.
