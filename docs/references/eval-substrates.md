# Evaluation Substrates: Ragas and Promptfoo

Date: 2026-08-21

Both locked-target eval substrates now execute for real. Neither is inferred
from configuration: readiness performs functional presence checks, and runs
fail closed with typed 503 details when the substrate cannot execute.

## Ragas (generation quality on eval runs)

- Enable with `evaluation.ragas_enabled`. During `POST /api/eval/run`, every
  dataset entry is answered through the LiteLLM gateway using the retrieved
  context (same formatter/system prompts as chat), then Ragas scores
  `faithfulness` and `answer_relevancy` (`evaluation.ragas_metrics`).
- Judge: the LiteLLM alias in `evaluation.ragas_judge_model` (empty = chat
  default alias), called with reasoning disabled and capped at
  `chat.max_tokens`; per-call timeout `evaluation.ragas_judge_timeout_s`.
  Judge calls are serialized for single-stream local serving.
- Embeddings for answer relevancy come from the operator's local
  sentence-transformers model (`embedding.effective_model`); a non-local
  embedding provider fails preflight.
- Results persist on the eval run: `EvalResult.generated_answer`,
  `EvalResult.ragas`, and the run-level means in `EvalMetrics.ragas`; the Eval
  drill-down renders a Ragas card when present.
- Implementation: `server/evaluation/ragas_runner.py` (Ragas's
  `LangchainLLMWrapper` adapter over an OpenAI-compatible client is confined to
  that module). Dependency pins keep `langchain*<1` because ragas 0.3 targets
  the pre-1.0 API.

## Promptfoo (regression over the eval dataset)

- `POST /api/eval/promptfoo/run` generates a Promptfoo config from the corpus
  eval dataset: each entry with an `expected_answer` becomes a test whose
  provider is ragweld's own `/api/answer` for that corpus (the grounded answer
  path is the system under test, not a bare model) and whose assertion is an
  `llm-rubric` graded by `evaluation.promptfoo_grader_model` (empty = chat
  default alias) through LiteLLM with reasoning disabled.
- The real CLI (`web/node_modules/.bin/promptfoo`) runs with caching off and
  concurrency 1; results are parsed into `PromptfooRun` and persisted under
  `data/eval_runs/promptfoo/`. `GET /api/eval/promptfoo/runs` lists them and
  the Eval Analysis surface shows the latest run with per-test pass/fail,
  score, response, and grader reason.
- Node runtime: promptfoo refuses unsupported Node versions; set
  `RAGWELD_NODE_BIN` to a supported `node` binary when the default `PATH` node
  is too old. The exact refusal is surfaced in the typed 503.
- Entries without `expected_answer` are counted as `skipped_entries`, never
  silently passed.

## Evidence (aurora acceptance corpus, 2026-08-21)

- Ragas eval run: `faithfulness 1.0`, `answer_relevancy 0.966` over two
  entries, generated answers persisted; a judge timeout and a token-budget
  overrun earlier in the day each produced the typed 503 with the exact reason
  instead of missing scores.
- Promptfoo run: 3/3 passed against `/api/answer`, promptfoo 0.122.0,
  provider and grader `ragweld-local` via LiteLLM.
