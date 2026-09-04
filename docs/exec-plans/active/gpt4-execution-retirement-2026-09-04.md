# GPT-4 execution retirement and resumed Ragweld audit

Date: 2026-09-04
Status: source verified; deployment pending

## Operator decision

Block GPT-4-class models everywhere, including deliberate manual selections.
This covers GPT-4, GPT-4o, GPT-4.1 and dated, size, batch and ChatGPT variants.
Other vendors' fourth-generation models are outside this restriction.

## Reconciled starting state

- Local main: bde5d1c9; deployed LXC100 source: c4e73ca9. The difference is
  Fable's closing documentation commit. Production readiness was healthy.
- The linked Codex task explicitly selected GPT-4o-mini for NASA on September 1
  after other schema/extraction routes failed. It was not merely a log example.
- Fable subsequently completed the cross-corpus implementation and follow-ups.
  NASA's current saved extraction selection is Luna; its completed run
  3054ecc26d3649a086758e04ece30488 has an empty extraction model alias. Do not
  infer complete run provenance from the current config.
- Epstein run a512c3ac4d2a4ba88da1e2427833341d records Luna, 3,126 successful
  chunks, no failed chunks and a promoted non-partial graph.
- NASA still had active cloud reranking through GPT-4.1-nano. The global and
  other corpus configs also retained that selection while reranking was disabled.
- No operator corpus was indexing at the initial audit.

## Replacement

- A shared execution policy rejects the retired family at config, catalog,
  gateway routing, generation transport, GraphRAG SDK, figure SDK, evaluation
  runner and direct docs-automation boundaries.
- Remove 18 generation routes and the retired reranker row from the canonical
  catalog, generated frontend mirror and generated LiteLLM configuration.
  Catalog refresh cannot reintroduce rejected aliases. Immutable historical
  records keep their original identifiers.
- Remove the hidden cloud reranker default in the schema, checked config and UI.
  Empty selection stays empty until the operator selects a catalog model.
  Changing providers clears the model; unavailable values display explicitly.
- Migrate only retired live model selections before deploying validation that
  rejects them. Preserve corpus embedding contracts and indexed generations.

## Verification and review

All execution, generation, tests, builds and browser checks run on LXC100;
source changes are made on the Mac. Disposable overlay:
`/var/tmp/astra-model-policy`.

- Initial family regression: 26 failures on the original implementation.
- Evaluation/docs boundary regression: 20 failures before guards, then 50 tests
  passed across the two affected suites.
- Independent review caught a duplicate catalog row, silent first-model UI
  selection and stale model retention on provider changes. All three were fixed.
- Final source review approved the provider-transition correction.
- Focused policy and transport suite: 222 passed; additional fixture migrations:
  64 passed. Frontend unit suite: 21 passed. Remote browser suite: five passed,
  covering blank selection, explicit selection/save/reload, provider changes,
  retired-model API rejection and reranker status.
- Docs ownership, banned patterns, generated types, runtime capability catalog,
  frontend lint/build and changed Python strict typing passed.
- Initial full suite: 2,244 passed, 10 skipped, 26 failed. Failure triage found
  obsolete positive model fixtures, saved corpus configs, missing overlay `.env`,
  and two timing assertions tied to an older machine speed. The configuration
  redaction sweep passes after migration. Replace the timing assertions with
  fresh-process cold/warm endpoint contracts, retaining the 10-second response
  budget; both replacement tests pass.
- Final full run: 2,279 passed, nine skipped, two paid Apollo tests deselected,
  and one fixture failure. The newly added non-GPT positive case named a Qwen
  serving ID already retired by another policy. It now uses the current local
  Qwen ID; all 50 tests across the policy and clean-start suites pass on rerun.
  No exercised failure remains unresolved. The full run itself is not reported
  as zero-failure, and the two deselected Apollo checks remain unverified.
- A real Luna reranker request using only three assistant-written public-knowledge
  sentences returned scores `[10, 0, 0]` in 1.26 seconds. This proves transport
  and score parsing, not NASA retrieval quality.
- GitNexus change detection reports HIGH impact across shared model selection,
  graph proposal, evaluation and UI flows; the identified scope matches this
  replacement.
- Logs: `/tmp/astra-full-pytest.log`, `/tmp/astra-final-focused.log`,
  `/tmp/astra-standard-gates.log`, `/tmp/astra-model-policy-browser4.log`,
  `/tmp/astra-full-final.log`.

## Live configuration migration

The existing API migrated all five config scopes before source deployment.
Global, ragweld_code, recall_default and Epstein now have an empty cloud-model
selection with reranking still disabled. NASA retains cloud reranking and now
selects `openai.gpt-5.6-luna`. Embedding contracts, graph indexing configs and
reranker modes were compared before/after and preserved. No corpus was indexing.
A mode-0600 redacted config backup is at
`/root/astra-model-policy-config-backup-20260904.json` on LXC100.

## Separate unfinished work from Fable's session

Do not declare these fixed by the execution-policy change:

- Measured cost attribution through LiteLLM/Langfuse/OTel and Grafana. Fable's
  record reports heuristic indexing cost, missing model/usage/cost observations,
  and no cost panel. NASA's missing run alias is confirmed in the live API.
- Cost design decisions previously parked: authoritative per-call ledger,
  Cohere routing, embedding gateway routing and per-run cost contracts.
- Config scope alias ambiguity and test/config ownership (S15/S17), obsolete
  disabled MLX/vLLM config (S27), document-corpus exclusion defaults (S32), and
  dock navigation state (S45) need fresh reproductions before repairs.
- The prior chat cross-store consistency concern was explicitly accepted as
  a best-effort derived-record contract; it is not an unimplemented transactional
  guarantee to claim as done or silently reintroduce into this slice.

## Pending closeout

Finish deployed browser acceptance,
deployment, gateway route inventory and blocked-request proof. A bounded paid
NASA/Luna reranker probe was rejected by automatic approval review as private
corpus transmission; explicit operator approval was requested. Do not send those
excerpts unless approval arrives.
