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
  default alias), capped at `evaluation.judge_max_tokens` (default 4096; the
  Promptfoo grader shares it); per-call timeout
  `evaluation.ragas_judge_timeout_s`. Judge calls are serialized for
  single-stream local serving. A verdict truncated by the budget fails the run
  closed (`LLMDidNotFinishException` surfaces in the typed 503), which is what
  happened on 2026-08-22 when the judge still borrowed `chat.max_tokens`=512.
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
  default alias) through LiteLLM.
- Judge and grader aliases must emit the structured verdict / rubric JSON
  directly (no reasoning traces in content). The local `ragweld-local`
  (`mlx-community/Qwen3.8-27B-4bit`) serves with thinking disabled at the
  serving layer (`--default-chat-template-kwargs '{"enable_thinking": false}'`
  in `start.sh`), so no per-request reasoning switch is sent; pointing the
  judge at a `…-thinking` / R1-style cloud alias is an operator error and can
  break verdict parsing.
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

## Eval dataset generation: the grounded QA provider (2026-08-22)

The Synthetic Lab (`RAG -> Synthetic Lab`, `POST /api/synthetic/run/start`)
has one provider, `grounded_qa`
(`server/synthetic/providers/grounded_qa_provider.py`). It is the only way
eval rows are generated; there is no seed hydration and no heuristic fallback.

- Sources: indexed chunk rows from Postgres, round-robin across files with a
  seeded shuffle (`max_source_chunks`, `seed`).
- Generator: the request's `generator_model` LiteLLM alias receives
  `system_prompts.synthetic_generator` (editable under Prompts; tokens
  `{num_pairs}`, `{question_max_chars}`, `{expected_answer_max_chars}`,
  `{evidence_quote_max_chars}`) plus the file path and the first
  `synthetic.generator.source_excerpt_max_lines` lines of the chunk, and must
  answer with a JSON array of `{question, expected_answer, evidence_quote}`.
- Grounding check (deterministic, in code): the quote must appear verbatim in
  the excerpt after whitespace/case/quote-mark normalization, at least half of
  the expected answer's content words must appear in the excerpt, and the
  question must end with a question mark (`?`, `？`, `؟`, Greek `;`), be at
  least four words (CJK: characters), carry a searchable anchor and not refer
  to "this email", "the excerpt", "the document above" and similar (an explicit
  multilingual list incl. "the attached/following/provided …"; the judge is
  the second line). Anchors are script-aware and source-aware: a number or
  e-mail address in any script; a quoted phrase that carries content words and
  occurs in the source excerpt; a capitalized non-initial word in a cased
  script (Latin, Cyrillic, Greek, accented letters); a capitalized
  sentence-initial word that the source itself writes capitalized mid-sentence
  (a proper noun, not a verb); and for uncased scripts (CJK, Arabic, Hebrew,
  ...) a content span the question shares with the source: a kanji/hanzi/
  katakana bigram with at least one non-grammar character (pronoun/verb/
  particle bigrams such as 她问 or 彼は never count), a hiragana chunk left
  uncovered after segmenting the run with a grammar lexicon (さくら counts,
  はどこ/ですか do not; a run after a kanji is okurigana), a Korean word stem
  of two or more syllables after particle stripping that is not a function
  word, or an Arabic/Hebrew word of at least three letters after clitic
  stripping that is not a function word. Letter count alone never anchors
  and a pronoun-only question is rejected in every script; bare discourse
  references ("what does the email say…", "in the email?") are
  self-references while a named document ("the email from Cohen") is a
  subject. Rows over the configured length limits are
  rejected. The quote
  is persisted on the row as `evidence_quote`. Counts land in the run summary
  as `items_rejected_ungrounded` / `items_rejected_malformed`.
- Judge: `system_prompts.synthetic_judge` scores every grounded row through
  the `judge_model` alias; rows under `curate_threshold` (0 is honored) are
  dropped. With `curate_enabled=false` the judge route is not resolved and
  `items_curated_in` is 0. `avg_judge_score` is reported.
- Concurrency: `synthetic.generator.concurrency` parallel gateway requests;
  the local vLLM alias is serialized process-wide (one stream across runs).
- Cancellation aborts in-flight gateway calls and the quality-gate retrieval
  pass; a failing call cancels its batch siblings.
- Failure semantics: a gateway/transport failure on either alias fails the run
  with the exact error; an unknown corpus is refused (404) instead of running
  on the global config; a store outage surfaces as the run error; a registered
  corpus with no indexed chunks fails before any call. Only the eval recipes
  run the quality gate (`semantic_cards`/`keywords` complete without it).
- Quality gate: every kept row is retrieved through the real fusion lane
  (`evaluate_dataset_entries`); the gate is top-1 over the first
  `synthetic.quality_gate.sample_size` rows against `top1_min`. Publishing the
  eval dataset or triplets requires a passed gate (409 `QUALITY_GATE_FAILED`
  otherwise).

## Reranker triplets from retrieval traces (2026-08-22)

`server/training/triplet_miner.py` mines `{"query", "positive", "negative",
"source"}` rows from two real signals and nothing else:

- Feedback events on the query log (`thumbsup`, `star4`, `star5`, `click`)
  correlated by `event_id` with the chat/search event they rate.
- Eval-run retrieval results (`EvalResult.retrieved_paths`): the labelled
  `expected_paths` are positives and the highest-ranked retrieved documents
  that do not match an expected path are hard negatives, at most
  `training.learning_reranker_negative_ratio` per question
  (`mine_triplets_from_eval_results`).

Guards: placeholder queries are rejected at mining (`server/evaluation/query_guard.py`),
the positive is written as the canonical retrieved path that matched the label
(expected labels use the boundary-aware suffix rule of
`server/evaluation/path_match.py`, never substrings), and a candidate negative
whose document text contains the entry's expected answer is skipped. Rows are
validated `TripletRow`s (`server/training/triplet_rows.py`: corpus-relative
paths, distinct documents, provenance `source`); a corrupt line fails loading
instead of being skipped. Writers (mining, synthetic publish) take an
interprocess `flock` on the sibling `.<name>.lock` file, rewrite the complete
validated file to a temp sibling and `os.replace` it (mode preserved, file and
directory fsynced), so readers see either the previous or the new complete
artifact and two API processes cannot drop each other's rows. A synthetic run's
`triplets_jsonl` artifact crosses the same boundary on publish (corrupt -> 409,
empty -> 400, the live file untouched). With
`training.tribrid_reranker_mine_reset` the reset does not read the file it
discards, which is the operator's way out of a corrupt artifact. Training
splits by *query* (a held-out question never
appears in both halves) and expands one positive pair per (query, positive)
with up to `learning_reranker_negative_ratio` distinct negatives.

Entry points: synthetic `triplets` / `full_stack` runs retrieve every generated
row (not just the gate sample) and write the mined rows as the `triplets_jsonl`
artifact; `POST /api/reranker/mine?corpus_id=…[&eval_run_id=…]` (corpus
required; serialized per process) combines the feedback events with the
corpus' latest persisted eval run whose payload names the corpus (or the named
one; 422 malformed, 404 unknown, 422 when it belongs to another corpus) and
reports written counts per source (`triplets_from_feedback`,
`triplets_from_eval_run`), `triplets_skipped_existing`,
`triplets_rejected_placeholder`, `negatives_rejected_answer_leak`,
`eval_run_id` and the validated `triplets_total`. Append mode is a union with
the rows already on disk. The same-directory-negative heuristic and the
`synthetic_data_kit` bridge (a package this repository never declared) are
gone.
