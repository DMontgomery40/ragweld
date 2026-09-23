# System One decisions across ragweld (2026-09-23)

## Goal

Replace ad hoc LLM-emitted JSON judgments and regex heuristics with typed System One
decisions (Choice / Noul / Score with calibrated probabilities). All of them go through
one ragweld client that speaks `POST /v1/systemone` to a configured provider:

- **`typesafe`**: TypeSafe **Jev** (`jev-latest`, cloud). This is the default.
- **`laya`**: **Laya** (Convai Innovations, Apache 2.0, HF `convaiinnovations/laya`,
  421M ModernBERT). It runs locally on LXC100 at 127.0.0.1:58180 for offline
  operation.

The provider is an explicit operator choice and fails closed. There is no silent
switching between providers.

## Scope (ordered by value)

1. **Reranker.** One Noul per (query, chunk), run concurrently. Measured against
   fusion-only, the current gateway LLM reranker and Laya on the chunk-level eval
   before any replacement. The current gateway reranker has a rerank-stage p95 of
   8.45 s.
2. **Synthetic judge.** Nouls: `reader_question`, `answer_supported`, and optionally
   `answer_cued_in_question`, replacing the LLM verdict JSON. A live audit of the
   Apollo dataset with Jev separated cover-page trivia (0.07–0.61) from real
   questions (0.92–0.96) for 7,573 input tokens.
3. **Answer grounding check.** For each chat answer and cited chunk, a Choice of
   supports / contradicts / says_nothing. Surfaced in the UI and as a Grafana
   groundedness metric.
4. **Chat model router.** A Choice over the gateway aliases, driven by the query
   plus a cost/latency policy held in code. For example, send short factual
   lookups to a fast non-reasoning alias and hard synthesis to a reasoning alias.
   This also keeps GLM's 60–110 s reasoning stalls off simple questions.
5. **Recall gate.** A Choice of skip / light / standard / deep, replacing the regex
   rules in `server/chat/retrieval_gate.py`.
6. **Evals and benchmarks.**
   - Promptfoo answer grading as a Noul ("answer satisfies the expected answer"),
     via a custom assertion or provider.
   - A benchmark judge that scores answers per model, so benchmarks report quality
     and not only latency.
7. **Alerts.** When an alert fires, classify likely cause and severity from its
   labels plus recent Loki lines, and put that triage in the Discord message.
   Everything else in the alert stays deterministic.
8. **Reranker teacher labels** for the deferred Hugging Face GPU training. These
   are chunk relevance Scores on logged real queries.

## Non-goals

- Using System One for text generation. It only returns decisions.
- Training Laya or Jev.
- Changing thresholds without measuring on ragweld data.

## Acceptance criteria

- Each adopted decision has a before/after measurement on ragweld data: quality,
  latency and cost.
- Each has a ratchet test.
- Each has provider-labelled metrics (`tribrid_system_one_requests_total`,
  `tribrid_system_one_latency_seconds`).
- The Laya lane is proven by running the same eval with `provider=laya`.

## Risks / failure modes

- **Laya: short context.** English context is 512 tokens, so passages must be
  trimmed and the truncation reported.
- **Laya: weak spots.**
  - Choices with more than 20 options, and ordinal Scores.
  - A Noul can follow the label text instead of the input. Use neutral wording.
  - It ships over-confident, so calibrate before using its thresholds.
- **Laya: CPU cost.** About 0.2–0.5 s per question on CPU, with a hard memory cap
  on the container.
- **Jev: cloud dependency.** Needs a network connection, the rate limit of 1,200
  requests per minute and a 64k context. Output tokens are free and input is
  $42 per billion tokens.

## Verification

- A live A/B harness on LXC100 for each adopted decision.
- `/api/ready` includes Laya only when the provider is `laya`.
- The Grafana "System One" row shows provider, latency and outcome.
