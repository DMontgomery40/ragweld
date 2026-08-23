# Eval Data Lane: grounded eval dataset + trace-mined reranker triplets

Date: 2026-08-22 (recovery session 7, handoff P1)

Status: landed on local main (session 7); proofs below

## Results (2026-08-22/23, real runs on `epstein-files-1`)

- Synthetic run `epstein-files-1__20260822_224500` (generator + judge
  `openai.gpt-5.4-mini`, 300 source chunks, concurrency 4): 224 rows generated,
  3 rejected ungrounded, 17 rejected malformed, 204 judged, 200 kept
  (avg judge 9.39); quality gate PASSED top-1 0.50 / top-k 0.82 / MRR 0.63
  over 50; 998 hard-negative triplets mined from the gate's own retrieval pass.
  Published: `data/eval_datasets/epstein-files-1.json` (200 rows with expected
  answers), `data/training/triplets.jsonl` (998).
- Eval run `epstein-files-1__20260823_025351` (50 entries, reranker none,
  answers + Ragas judge through `openai.gpt-5.6-luna`): MRR 0.631,
  recall@5 0.82, recall@10 0.90, nDCG@10 0.69, Ragas faithfulness 0.822,
  answer_relevancy 0.640. The first attempt failed closed with
  `LLMDidNotFinishException` because the judge borrowed `chat.max_tokens`=512;
  `evaluation.judge_max_tokens` (4096) fixed it.
- Promptfoo run `epstein-files-1__promptfoo__20260823_023414`: 21/25 passed
  (provider `/api/answer` via luna, grader luna, promptfoo 0.122.0).
- `POST /api/reranker/mine` on the persisted eval run: 250 hard-negative
  triplets, all already on disk from the synthetic pass (append-as-union added
  0; 998 rows).
- Reranker LoRA run `epstein-files-1__20260823_023509` (MLX, host): completed,
  dev MRR best 0.975 / final 0.98, promoted to `models/learning-reranker-active`
  — and that host training contributed to the second machine crash. Operator
  rule since: reranking uses cloud models (`reranker_cloud_provider=litellm`,
  alias `openai.gpt-4.1-nano`); the learning reranker is not loaded on this
  host. Flyte-orchestrated Learning Agent training was NOT run for the same
  reason.
- Chrome drive: Synthetic Lab (grounded_qa provider, quality gate + grounding
  counts), Eval Analysis (Promptfoo panel), Learning Reranker Studio (live run
  HUD). One pre-existing defect surfaced: the Neural Visualizer's WebGL
  OrbitControls connect to a null DOM element on mount
  (`NeuralVisualizerWebGL2.tsx`, drei 10.7 / three 0.182), logging a console
  exception and leaving the canvas blank — tracked for Phase B.

## Why

`epstein-files-1` is indexed on the promoted lane with no eval dataset and no
triplets. The two paths that were supposed to produce them are not real:

- The Synthetic Lab has exactly one provider, `synthetic_data_kit`, whose
  package was never declared in `pyproject.toml`, never locked, and is not
  importable. Every eval-oriented recipe fails at import. The lane also carries
  a seed-hydration fallback ("hydrate rows from the existing dataset instead of
  LLM generation") and fallback bookkeeping (`SyntheticRunDegradation`),
  which the branch canon forbids.
- Reranker triplets are mined only from thumbs-up/click feedback on the query
  log (none exist), or synthesized by `_build_triplets` with "the first file in
  the same directory" as the negative. Neither is a retrieval trace.

## Replacement (no fallbacks, one path)

1. **Provider `grounded_qa`** (`server/synthetic/providers/grounded_qa_provider.py`)
   replaces `sdkit_provider.py`. For each selected source chunk (Postgres,
   round-robin across files, seeded) it asks the generator alias through the
   LiteLLM gateway for N question/answer rows with a verbatim
   `evidence_quote`. A row is kept only if the quote is a whitespace-normalized
   substring of the source excerpt (deterministic grounding check) and the
   question is self-contained (no "this email"/"the excerpt"). The configured
   `system_prompts.synthetic_judge` rates each survivor; rows below
   `curate_threshold` are dropped. Prompts: new
   `system_prompts.synthetic_generator` (editable via the Prompts API like the
   judge). Generator/judge errors fail the run (`fail_on_error` and the
   degradation flags are deleted; there is nothing to degrade to). Gateway
   concurrency is `synthetic.generator.concurrency`, forced to 1 for the local
   vLLM alias (single stream).
2. **Triplets from the retrieval trace.** The quality gate already runs every
   generated question through the real `TriBridFusion.search`; that eval run
   is the trace. `mine_triplets_from_eval_results` turns each
   `EvalResult` into (question, expected path, hard negative) rows where the
   negatives are the highest-ranked retrieved paths that are not expected, up
   to `training.learning_reranker_negative_ratio`. The synthetic
   `triplets_jsonl` artifact is built from that run (same-directory negatives
   deleted). `POST /api/reranker/mine` mines the same way from the corpus'
   latest persisted eval run (or `eval_run_id`) in addition to feedback
   events, and reports both counts.
3. **Seed hydration deleted.** A run that generates nothing fails its quality
   gate; it does not borrow rows from the published dataset.
4. **UI parity.** Synthetic Lab lists the real provider and shows grounding /
   judge rejection counts; the degraded-run panel is gone. Reranker Training
   Center shows the per-source mining counts.
5. **Cloud reranker through the gateway** (added after the second crash):
   `reranking.reranker_cloud_provider=litellm` (default) scores the top-N
   candidates listwise through the alias in `reranker_cloud_model`
   (`server/retrieval/gateway_reranker.py`, prompt
   `system_prompts.gateway_rerank`), sharing the blend/metadata path with the
   Cohere provider; an unresolvable gateway is a skipped rerank
   (`gateway_unavailable`). The field pattern `^(litellm|cohere)$` is the only
   provider contract (the unreachable runtime check in `PUT /api/config` is
   deleted and a unit test pins the pattern to the runtime option set).
   Catalog RERANK rows for provider `litellm` make the aliases selectable.
6. **Judge budget.** `evaluation.judge_max_tokens` (4096) caps the Ragas judge
   and the Promptfoo grader instead of `chat.max_tokens`.

## Adversarial review (codex exec, high) — pass 1 REFUTED (14 P1, 10 P2, 1 P3), all acted on

- Train/dev leakage: rows of one question landed in both halves and every
  mined negative duplicated the positive pair -> `deterministic_split_by_query`
  and grouped `triplets_to_pairs` (one positive per query, distinct negatives,
  ratio applied once). The reranker run's 0.98 dev MRR predates this and is
  not query-held-out; it is not used.
- Hard negatives: a retrieved document containing the expected answer (a
  duplicate email) is no longer a negative (`negatives_rejected_answer_leak`);
  positives are written as the canonical retrieved path so training can
  materialize them; placeholder queries are rejected (`query_guard`).
- `path_matches` was substring-based (`mail.txt` matched `blackmail.txt`) ->
  boundary-aware suffix/exact only, shared by eval scoring, ML-quality and mining.
- Grounding: the expected answer must be anchored in the excerpt, pronoun-only
  questions are rejected, `evidence_quote` is persisted on the row;
  `curate_threshold=0` honored, judge resolved only when curation is on,
  `items_curated_in=0` when skipped.
- Orchestrator: the scoped-config fallback and the Postgres-error swallow are
  gone (unknown corpus -> 404, store outage -> run error); only eval recipes
  run the gate; starts are atomic under a lock; cancellation aborts in-flight
  gateway calls (race against the cancel event, `TaskGroup` batches) and the
  gate's retrieval loop; progress/artifact writes run off the loop; the local
  alias semaphore is process-wide.
- Mining endpoint: `corpus_id` required (no global back-compat path),
  `eval_run_id` validated at the eval storage owner (traversal -> 422), the
  whole operation serialized under a lock with status reset in `finally`, the
  latest run chosen from validated payloads that name the corpus, counts
  report written rows per source plus skipped/rejected counts, and the JSONL
  is a validated `TripletRow` boundary (corrupt lines fail loudly).
- Reranker: `{id, score}` bijection with opaque per-request ids replaces the
  positional array; uniform scores are neutral (single candidate keeps its
  fusion score); ties break on fusion score; legacy `local`/`hf`/`off`/
  `cohere` mode aliases and the `transformers`/`mlx` backend aliases are
  deleted from the schema, the score request and the runtime (stale stored
  values fail validation); the unreachable runtime provider check in
  `PUT /api/config` is deleted and a test pins the schema pattern to the
  runtime option set.
- `evaluation.*` substrate fields (`ragas_*`, `promptfoo_grader_model`,
  `judge_max_tokens`) now round-trip through the flat config.
- Tests: placeholder queries removed from the reranker suite, the
  "real provider when available" test that accepted failure is deleted, the
  no-chunks test creates a real corpus in the Postgres lane, blend/tie/neutral
  and id-bijection unit tests added, a no-interception Playwright spec covers
  the Synthetic Lab grounding panel and the reranker config surface
  (`web/tests/e2e/gateway/eval_data_lane.spec.ts`).
- Copy: the Synthetic Lab no longer points at a deleted in-process model.

Residuals (documented, not fixed): semantic duplicates that paraphrase the
answer are still mined as negatives (only literal answer containment is
checked); answer support is a lexical anchor check plus the optional judge,
not an entailment gate; `start_run`'s initial state writes are synchronous
(small, under the start lock); the pytest suite cannot exercise a real gateway
call (no credential in the test environment) — live runs are the proof;
`_load_run`'s reconciliation writes and the non-reader-atomic artifact
rename window are tracked in `training-run-state-authority-2026-08-23.md`;
uncased-script predicate-only questions whose source repeats the predicate
(他购买了什么东西, מה הוא כתב שם, ماذا كتب هو هناك — "what did he buy/write")
pass the deterministic self-containment guard because a regex cannot tell a
two-hanzi or Semitic verb from a name, nor a transliterated name made only
of grammar characters (彼得) from a pronoun, nor a CJK thing (飞机) from a
person (张伟) as a pronoun's antecedent; in English, finite verbs outside
the `-ed`/`-ing` forms and the reporting-verb list can pose as antecedent
nouns for it/their — the judge prompt carries the explicit self-containment
rule in every
language and is the authority for that family (the deterministic guard
covers pronoun/particle/okurigana/predicate morphology and discourse
references).

Re-proof after the fixes: live rerank with the id-bound format applied on 20
candidates with 0 errors; 50-entry eval run `epstein-files-1__20260823_102320`
top-1 0.68 / MRR 0.783 / recall@5 0.94 / nDCG@10 0.827; a 24-source
grounded_qa run (luna) kept 12/12 generated rows with 0 ungrounded and 0
malformed, judge avg 10.0, gate top-1 0.75, 58 triplets.

## Adversarial review — pass 2 REFUTED (5 P1, 7 P2, 2 P3), all acted on

Pass 2 verified the pass-1 fixes and found what they left open:

- Held-out eval: fewer than ten questions produced an empty dev set and an
  unconditional promotion -> at least one question is held out whenever two
  exist, and a run without a dev split is never auto-promoted.
- Invented negatives: `triplets_to_pairs` filled the ratio from other queries'
  negatives -> only the query's own mined negatives are used (ratio is a cap).
- Answer-leak guard: short answers (`EJM`) were unchecked, unreadable
  candidates were accepted, answers came from the mutable current dataset ->
  whole-token phrase containment for any answer of 2+ characters, unreadable
  candidates rejected (`negatives_rejected_unverifiable`), and `EvalResult`
  now carries `expected_answer` so a run is mined with its own answers (the
  synthetic run mines with the pre-publication generated answers).
- `TripletRow` paths are canonical POSIX corpus-relative strings (`./a.txt`
  == `a.txt`, backslashes folded, drive-qualified rejected) and the row
  validator applies the real-query guard.
- Cancellation: `_cancellable` now cancels and awaits the gateway task on any
  outer cancellation (TaskGroup sibling failure, run task cancel), and the
  orchestrator re-checks the cancel event after the gate, after mining, per
  artifact write and before completion (unit tests for both directions).
- Curation: the configured `curate_threshold` is authoritative (the prompt's
  `keep` flag is advisory); the generated answer stays on the row through
  judging and mining and is blanked only in the published artifact.
- Anchoring uses whole tokens (`Ann` is not anchored by `planning`);
  capitalized pronouns/question words are not anchors.
- Real-query guard: two-word minimum, banned tokens reject only short queries
  or all-placeholder queries; enforced in `TripletRow`.
- Mine API: missing corpus -> 404, store outage -> typed 503, corrupt triplets
  -> 409 (file untouched), unexpected -> 500; status reset in `finally`.
- Latest eval run is chosen by `completed_at` from validated payloads; a
  corrupt candidate file raises instead of silently shifting the selection.
- Gateway scores reject `NaN`/`Infinity`; descriptions and the UI mode
  default match the schema.
- Tests: the Playwright spec fails (not skips) without a real run and asserts
  the exact persisted summary values; the quality-gate unit test is named and
  asserted as the error path; the no-chunks integration test no longer gates
  on gateway availability; the last placeholder query is gone.

Re-proof on the pass-2 code: live rerank applied on 20 candidates with 0
errors; a 24-source grounded_qa run kept 12/12 rows (0 ungrounded, 0
malformed, judge avg 9.96, gate top-1 0.67) and mined 53 triplets while
rejecting 33 candidate negatives that contained the expected answer.

## Adversarial review — pass 3 REFUTED (2 P1, 4 P2, 1 P3), all acted on

- The typed-503 helper was called with the wrong signature (a `TypeError`
  instead of the 503) and raw Postgres failures fell to a 500 -> fixed and
  pinned by the existing outage contract test, which now also drives
  `POST /api/reranker/mine` and `POST /api/synthetic/run/start` against an
  unreachable Postgres (16 stateful routes, all typed 503).
- The mutable-dataset answer fallback was a dual path -> deleted. Mining reads
  the answer only from the trace (`EvalResult.expected_answer`); the synthetic
  run gates the unpublished rows so their results carry the generated answers;
  results without an answer are mined without the leak check and counted
  (`entries_without_answer_provenance`, on the wire and in the UI).
- ASCII-only guards -> shared Unicode tokenizer
  (`server/evaluation/text_tokens.py`): Cyrillic/CJK queries pass the real-query
  guard, CJK answers anchor/leak-check by normalized containment.
- Training loads and materializes triplets off the event loop.
- The UI never rendered its notifications (both studios called the hook but
  never displayed the list), so no mining or publish outcome was visible;
  both now render them, `RerankService.mineTriplets` decodes the status,
  typed detail and operator hint, and a real-app Playwright test drives a
  corrupt triplets file through the Training Studio to the 409 guidance.
- The training endpoint suite's `monkeypatch`ed config loader is gone: five
  tests register real corpora and run in the Postgres lane.
- `negatives_rejected_unverifiable` is on the wire.

Verification after pass 3: full pytest 910 passed / 76 skipped; strict lane
24 passed; Playwright 3 passed; static and frontend gates green.

## Adversarial review — pass 4 REFUTED (1 P1, 4 P2, 1 P3), all acted on

- P1: the SSE eval route (the one Eval Analysis uses through
  `TerminalService`) built its own `EvalResult` rows and dropped
  `expected_answer`, so UI-run evals lost the provenance the leak guard needs
  -> POST and SSE now share one scoring path (`_score_entry` in
  `server/api/eval.py`) and persist the answer. Regression
  `tests/integration/test_eval_trace_mining.py` indexes the acceptance corpus
  for real (Postgres + Qdrant + Neo4j, deterministic embeddings), streams the
  SSE eval, asserts the persisted run carries both answers, mines from it and
  checks every negative is a retrieved non-expected file that does not contain
  the answer (an unindexed corpus fails closed on the required graph leg, which
  is why the earlier in-memory attempt could not be honest).
- P2: the refused no-dev auto-promotion crashed the finished run
  (`None` formatted with `:.6f`) -> decision + message extracted into the pure
  `decide_auto_promotion` (baseline renders `n/a (no held-out dev split)`),
  pinned in `tests/unit/test_reranker_split.py`. A job-level run would need
  real MLX training on this host, which the operator has ruled out.
- P2: `Infinity`/`NaN` judge scores clamped to 10 -> `parse_constant` rejects
  JSON constants and the score must be finite (tested for all three).
- P2: synthetic question admission was ASCII/whitespace-bound while the query
  guard was Unicode-aware -> `is_self_contained_question` counts tokens/CJK
  characters through the shared tokenizer with a script-independent anchor
  test; invariant test: accepted real Unicode questions pass the synthetic guard.
- P2: triplet writes were non-atomic -> `write_triplet_rows` writes the full
  validated union to a same-directory temp file, fsyncs and `os.replace`s.
- P3: the outage contract still sent the placeholder query `"status"` ->
  real domain questions on every route.

Verification after passes 4-19 and the self-reviews: see the closeout block at the end of this file.

## Adversarial review — pass 5 REFUTED (1 P1, 3 P2, 3 P3), all acted on

- P1: a failed baseline evaluation of the *active* artifact looked like "no
  active artifact" (`baseline_primary=None`) and an improvement-gated run
  promoted over a live model unmeasured -> `decide_auto_promotion` takes an
  explicit `baseline_state` (`absent | incompatible | measured | failed`);
  `failed` refuses automatic promotion unless the operator disabled the gate,
  the state is in the `promotion_skipped` diagnostic, matrix in
  `tests/unit/test_reranker_split.py`.
- P2: mining was an unlocked read-modify-replace, so two API processes could
  drop each other's rows -> `triplets_lock` (`flock` on a sibling lock file)
  held across load/dedupe/write in `mine_triplets`; proven with three real
  processes racing in `tests/unit/test_triplet_rows.py`.
- P2: the "script-independent" anchor was still `[A-Z]` and length used
  `str.split()` -> Unicode word regex with `str.isupper()` (Cyrillic, Greek,
  accented Latin), uncased scripts (CJK, Arabic, Hebrew) anchored by letter
  count, Arabic/Greek question marks; invariant tests over nine scripts.
- P3: `mkstemp` tightened a shared artifact to 0600 and the rename was not
  fsynced -> temp file created with the process umask, existing mode copied,
  parent directory fsynced after `os.replace`.
- P3: a 400-digit judge score overflowed `float()` before the finiteness check
  and failed the whole task group -> converted under `try`, `GroundedQAParseError`.
- P3: the real-index regression did not tie negatives to the question's own
  `retrieved_paths` and ignored teardown results -> every negative must be in
  that question's persisted retrieval, the mined set must equal the eligible
  retrieved prefix (ratio cap 3), deletions asserted, eval status restored.
- P3: `"hello"` in the chat outage probe -> the Aurora calibration question.

## Self-review (author's refutation pass, same standard), all acted on

- `publish_triplets` overwrote the live triplets file with a blocking,
  unlocked, non-atomic, unvalidated `write_text` on the event loop (the run
  artifact never crossed the `TripletRow` boundary; a corrupt or empty artifact
  would replace good data) -> rows are validated off the loop, an empty
  artifact is refused (400), a corrupt one is a 409, and the write goes through
  `triplets_lock` + `write_triplet_rows`; `tests/api/test_synthetic_endpoints.py`
  drives all three against a real scoped corpus.
- "Reset & mine" loaded the corrupt file it was about to discard and 409'd, so
  the operator's recovery path was blocked by the fault it exists for ->
  replace mode only reads the file when `preserve_existing_on_empty` is set;
  the 409 guidance now names `training.tribrid_reranker_mine_reset`.
- A possessive apostrophe opened a "quoted phrase" anchor (`friend's note
  about its plane's` anchored a pronoun-only question) -> a quote must not be
  preceded by a word character.
- The Learning Agent trainer (`server/api/agent.py`) had the same promotion
  hole as the pass-5 P1 (failed baseline or missing final loss -> promoted) and
  promoted with no held-out split -> both trainers now share
  `server/training/promotion.py::decide_auto_promotion` (direction-aware:
  MRR maximize, eval loss minimize), matrix-tested.
- The Playwright corrupt-triplets spec now removes the `.lock` sibling it
  causes; `docs/references/eval-substrates.md` documents the lock/publish
  boundary.
- The Russian self-reference pattern matched the bare word "выше" ("above",
  but also "higher than"), rejecting real comparison questions -> restricted
  to "в тексте выше" / "указано выше" forms and a trailing "выше?".
- The Synthetic Lab showed axios' "Request failed with status code 409" and
  dropped the server `detail` for every failure (start, load, publish, patch)
  -> `describeSyntheticFailure` in `SyntheticService` decodes string, list
  and typed `{code, message, operator_hint}` details; Playwright drives a
  byte-corrupt `triplets_jsonl` publish to the visible
  `TRIPLETS_ARTIFACT_CORRUPT` 409 and checks the live file is untouched.
- `list_runs` silently skipped any run.json that failed validation, so every
  historical run of the replaced provider vanished from the lab -> the runs
  listing reports them as typed `unreadable: [{run_id, reason}]`
  (`SyntheticUnreadableRun`, generated), the lab renders the list, and the
  listing runs off the event loop. API + Playwright coverage.

## Adversarial review — pass 6 REFUTED (1 P1, 3 P2, 1 P3), all acted on

- P1: a NaN/inf final metric promoted when the baseline was absent, and a NaN
  baseline counted as "measured" -> `decide_auto_promotion` (now
  `server/training/promotion.py`, shared with the Learning Agent trainer)
  refuses a non-finite final value in every state and with the gate off (a
  broken artifact is never auto-promoted; a *missing* measurement with the gate
  off still is), reclassifies a non-finite baseline as `failed`; NaN/±inf
  matrix over all states and both gate settings.
- P2: invalid UTF-8 in the triplets file raised a raw `UnicodeDecodeError`
  outside the per-line handler (500 on mine, 400 on publish) -> wrapped as
  `TripletRowsCorruptError`; loader, mining and publish (409) cases.
- P2: my reordered anchor regex applied the capitalization check to e-mail
  matches, so lowercase addresses were no longer anchors -> named groups;
  only `word` matches are checked with `isupper()`. Found alongside it: the
  number anchor used `\b`, which never fires between a CJK letter and a digit
  (`在2017年`), so dates inside CJK runs never anchored.
- P2: uncased-script length stood in for anchoring (any 8-letter Arabic
  question passed; `東京はどこ？` failed; `根据这封邮件…` passed) -> removed.
  Uncased questions now anchor only on a content span shared with the source
  excerpt they were generated from (CJK bigram not in an explicit grammar list,
  or a word of ≥4 letters not in an explicit function-word list); the provider
  passes the excerpt; self-references are matched against an explicit
  multilingual list (zh/ja/ko/ar/he/ru/es/fr/de/pt/it). Matrix of accepted
  (with source) / rejected (pronoun-only, source-referential, no source) cases.
- P3: the copied mode was applied after the data fsync -> `fchmod` before the
  fsync, then replace + directory fsync.
- Also removed on this pass: the generator row fallback `expected_answer or
  answer` (the prompt contract names one key; the call site now uses the
  validated item instead of re-reading the raw row).

## Adversarial review — pass 7 REFUTED (6 P2, 2 P3), all acted on

- P2: NaN/inf metrics reached `primary_series`, best/final values, metric
  events and the persisted summary of both trainers (Pydantic constraints are
  bypassed by attribute assignment; FastAPI later refused to serialize the
  run) -> `server/training/metric_values.py` (`finite_or_none`,
  `finite_metrics`, `stability_stddev`): non-finite metrics are dropped from
  events/MLflow/summary with a diagnostic, `_primary_value` returns None (never
  0.0) when absent or non-finite, the agent keeps "broken" (NaN last eval_loss)
  distinct from "missing" for the promotion decision.
- P2: `corpus_text_loader` decoded with `errors="ignore"`, so binary or
  non-UTF-8 documents became "verified" answer-free negatives -> strict UTF-8
  decode and NUL rejection; such candidates count as unverifiable.
- P2: pronoun+verb CJK bigrams (她问, 他想, 他们) passed the blacklist ->
  replaced by a character-level rule: a shared bigram is content only if at
  least one character is not grammar/deixis/kana/hangul-particle.
- P2: "the attached/following/provided email" were not self-references ->
  extended the English deictic-source list (attached, provided, supplied,
  following, preceding, given, enclosed, accompanying, …; "according to the
  attachment", "in/from the excerpt").
- P2: a quoted pronoun (`'it'`) anchored -> quoted phrases must carry content
  words and, when the source is known, occur in it.
- P2: `TriBridConfig.from_flat_dict({})` rebuilt the replaced Cohere defaults
  and honored `RERANKER_ACTIVE/BACKEND/PROVIDER`, `COHERE_RERANK_MODEL` ->
  canonical keys only, absent keys take the `RerankingConfig` defaults; the
  two legacy glossary rows are gone; parity + round-trip test.
- P3: sentence-initial names ("Aurora recorded …?") and three-letter uncased
  names (علي, دبي) were rejected -> a sentence-initial capitalized word anchors
  when the source writes it capitalized mid-sentence (verbs do not); uncased
  word minimum is three letters with an extended function-word list.
- P3: a 400-digit gateway score raised `OverflowError` past the parser
  boundary -> converted under `try`, `GatewayRerankParseError`.

## Adversarial review — pass 8 REFUTED (1 P1, 5 P2, 2 P3), all acted on

- P1: the MLX agent trainer emitted `eval_loss` only when finite, so a NaN
  loss never reached the control plane as "broken" and a run with the
  improvement gate off promoted a diverged adapter -> the trainer emits the raw
  value; `finite_metrics` classifies it and `final_primary_broken` refuses.
- P2: a reranker run with no dev split fabricated `{mrr:0, ndcg:0, map:0}` as
  a real measurement -> no metrics event, no series value, `final_eval_skipped`
  diagnostic, `primary_metric_final=None`.
- P2: progress/telemetry events used plain `float()` and the event/summary
  models accepted any float -> `FiniteFloat` (`allow_inf_nan=False`) on every
  event scalar/metric and summary field, `validate_assignment` on both
  summaries (fails closed), `finite_or_none` at every call site.
- P2: `stability_stddev` overflowed to inf on finite 1e308 inputs ->
  `statistics.pstdev` + finiteness check.
- P2: "What does the email say about Barry Cohen?" passed -> bare discourse
  references (`the <document> says/mentions/…`, "in the email?") are
  self-references; a *named* document ("the email from Barry Cohen") is not.
- P2: uncased-script classifier accepted 彼は何を… / 그는 무엇을… / ומה הוא אמר
  and rejected all-hiragana さくら -> hiragana runs are segmented with a grammar
  lexicon (DP, fewest uncovered characters; runs after a kanji are okurigana)
  and uncovered chunks shared with the source are content; Korean is handled
  per word (particle stripping, function stems); Hebrew/Arabic clitics
  (ו/ה/ב/ל/מ/ש/כ, و/ف/ب/ل/ك/س, ال) are stripped before the function-word check
  and when matching the source. Matrices for ja/ko/he/ar, positive and negative.
- P3: dropped non-primary metrics had no diagnostic -> `metrics_not_finite`
  names every dropped metric.
- P3: run directories without `run.json` stayed hidden -> reported as
  unreadable ("run.json is missing").

## Adversarial review — pass 9 REFUTED (4 P2, 1 P3), all acted on

- P2: the run-diff fallbacks kept the naive stddev (overflow on two finite
  1e308 events) and diff deltas/response fields were plain floats -> both
  fallbacks use `stability_stddev`, deltas pass through `finite_or_none`, the
  diff responses use `FiniteFloat`.
- P2: predicate-only questions in uncased scripts whose source repeats the
  predicate (彼は何を食べましたか, 그는 무엇을 썼나요, מה הוא כתב שם, 他购买了什么) ->
  structural hardening: a CJK span needs two content characters (a lone
  kanji before okurigana is a predicate stem), Korean predicate morphology
  (나요/습니까/었다/…) never anchors. The remaining family — a two-hanzi or
  Semitic predicate shared with the source (他购买了什么东西, מה הוא כתב שם) —
  cannot be separated from a name by a regex; the judge prompt now states
  the self-containment rule explicitly in every language and is the
  authority there (documented residual, see pass 1 Residuals).
- P2: "in/from the email about X" passed because the bare-reference rule
  required `?`/`,`/end right after the noun -> a definite document reference
  is a self-reference unless the document is identified right after it
  (`the email from Barry Cohen`, `the memo dated 2017-10-03`, `the letter to
  Cohen`).
- P2: hiragana tiling split さかな as さ+かな and Korean stripping collapsed
  회의는 to 회 -> DP segmentation where a single-character particle may only
  stand next to grammar/boundaries (never inside a noun), one longest
  particle stripped per Korean word and never below two syllables.
- P3: `finite_or_none(v) or None` / `int(v or 0) or None` erased step 0,
  epoch 0.0, percent 0.0 -> `step_or_none` + plain `finite_or_none`; the
  progress/telemetry adapters are module-level builders
  (`build_*_progress_event`, `build_*_telemetry_event`) with a zero-preservation
  matrix.
- Also: the committed `tribrid_config.json` had inherited the live
  experiment's `reranker_mode=cloud` / `top_n=20` through the API's config
  persistence -> restored to `none` / 50 (paying for gateway reranking is the
  operator's decision; provider/model defaults stay litellm / gpt-4.1-nano).

## Adversarial review — pass 10 REFUTED (1 P1, 6 P2, 1 P3), all acted on

- P1: finite but impossible metrics (`eval_loss=-1`, `mrr=2.0`) promoted and
  then failed summary validation *after* the copy -> `METRIC_DOMAINS` in
  `metric_values.py` (MRR/nDCG/MAP in [0,1]; losses, lr, grad_norm ≥ 0):
  out-of-domain values are dropped like NaN (so the final value is "no
  measurement" and promotion refuses), and both trainers populate and
  validate the summary BEFORE any artifact copy.
- P2: event loaders silently skipped records that no longer validate ->
  `_load_events` returns an `UnreadableEvents(count, first_reason)`; the
  metrics responses carry `unreadable_events`/`unreadable_reason` and the
  diff responses `baseline_/current_unreadable_events` (generated types).
- P2: negative time-to-best could be fabricated from a timestamp before
  `started_at` -> `non_negative_or_none` at both fallbacks and the summary;
  `ge=0` on the absolute diff fields (deltas stay signed).
- P2: the Hebrew/Arabic predicate-only probes (מה הוא כתב שם, ماذا كتب هو
  هناك) still pass — this is the same POS-less family as the two-hanzi
  residual (a regex cannot identify an arbitrary Semitic verb); the residual
  is now stated for *all* uncased scripts and the pass-9 wording corrected:
  clitic stripping fixed the "ומה" false positive, not predicates.
- P2: the identified-document exception accepted "from him" / "from
  yesterday" (the identifier class was case-insensitive like the rest of the
  pattern) -> `(?-i:[A-Z0-9"“'‘])`: the clause must start with a capital,
  digit or quote; "the email from him say" is a bare reference.
- P2: 昨天/今天/先週/어제 counted as content -> explicit deixis span lists for
  zh/ja/ko (plus hiragana きのう… and Korean 어제… in the grammar lists).
- P2: the two-content-character rule rejected 犬は / 猫は -> a lone kanji
  directly followed by a case particle is a noun candidate (okurigana is not)
  and anchors when the source contains it.
- P3: `step_or_none(1.5) == 1` -> only integral values are steps.

## Adversarial review — pass 11 REFUTED (1 P1, 5 P2), all acted on

- P1: the active artifact was swapped before the fallible lineage/run-record
  writes, so an `ENOSPC` in the lineage store left a new artifact serving
  while the run was not durably completed -> `PromotionSwap`
  (`server/training/promotion.py`): copy + swap with the previous tree
  retained, post-swap work (cache clear, lineage, run record) inside a
  `try`, `rollback` restores the previous artifact on any failure, `commit`
  discards it; used by both training jobs and both manual promote endpoints
  (the old `_atomic_copy_dir` is gone). Filesystem-failure test on the swap
  itself (a job-level test needs MLX training on this host, ruled out).
- P2: domains were enforced in the builders only -> the persisted boundary
  enforces them: `le=1` on the reranker summary scores, a `metrics`
  validator on both event models (`_METRIC_DOMAINS`, single table shared
  with `metric_values.py`), `ge=0` on loss/lr/grad_norm/param_norm/
  update_norm/step_time_ms telemetry fields.
- P2: `unreadable_events` only counted the requested tail, and the SSE
  streams replayed/tailed raw text with `errors="ignore"` -> the loaders
  validate the whole file (physical line numbers) before limiting; SSE
  history replays validated events and announces corruption as an `error`
  event; tailed lines are validated or reported, never lossy-decoded.
- P2: a date/number anchored a pronoun-only question ("What did he do in
  October 2017?", 他在2017年…, 그는 2017년에…) and 自分/자신 were not pronouns
  -> numbers never anchor a question with a pronominal subject (cross-script
  pronoun pattern), calendar words (October, Monday, Oktober…) are not
  anchors, digits are excluded from the uncased-word rule, 自身/자신/자기 are
  grammar. (ماذا كتب هو في 2017 now fails the date rule and lands in the
  documented Semitic-verb residual.)
- P2: "What does the email about Barry Cohen say?" -> about/concerning/
  regarding/on qualify an unidentified document; the bare rule covers them.
- P2: `根据(这|本|上)` matched the prefix of 本田 (Honda) and "in the excerpt
  titled …" was rejected unconditionally -> complete deictic phrases
  (根据这封/这份/本文/上文/…), and the identified-document exception
  (titled/entitled/named/from/by/dated + identifier) on every excerpt/
  document alternative.

## Adversarial review — pass 12 REFUTED (3 P1, 7 P2, 2 P3), all acted on

- P1 ×3 (the pass-11 swap): overlapping promotions could undo each other,
  a failed `begin`/`rollback` could strand the active path, and both jobs
  committed before the remaining completion writes -> `PromotionSwap` holds
  an exclusive `flock` on `.<active>.promote.lock` from `begin` to
  `commit`/`rollback` (proven with three racing processes), `begin` is
  exception-safe (a failed copy or rename leaves the active tree untouched),
  cleanup errors are raised (`PromotionRollbackError`, chained to the original
  failure) and an unremovable retained tree is reported; every outcome-changing
  step (cache clear, lineage, run record) runs inside the transaction and
  everything after `commit` is best-effort observability that logs a warning
  instead of flipping a completed run to failed. Same contract on both manual
  promote endpoints (a diagnostic failure can no longer turn a committed
  promotion into a 500).
- P2: artifact rollback did not undo the `promoted`/`current` lineage aliases
  -> `snapshot_aliases` before the lineage write, `restore_aliases` on
  rollback (re-point or remove).
- P2: copy/delete ran on the event loop -> every swap phase goes through
  `asyncio.to_thread` (the flock is bound to the descriptor, not the thread).
- P2: one invalid UTF-8 byte discarded the whole event history and the
  loaders read on the loop -> lines are decoded and validated individually,
  every corrupt line is counted before the tail limit, and the loaders run
  off-loop at the metrics, diff and SSE call sites.
- P2: `publish_triplets` released its lock and replaced the live file before
  the lineage write -> one locked transaction: previous rows retained in
  memory, written back (or the file removed) when lineage fails; proven in
  the API lane by turning the alias file into a directory.
- P2: `their emissions` made the subject pronominal -> subject pronouns only
  (and the French `on` collision with English removed).
- P2: 上野 rejected -> a bigram of two ideographs with at least one
  non-grammar character is content (彼得-style names made only of grammar
  characters remain in the documented residual).
- P2: 本报告/本報告 -> complete demonstrative+document phrases (`本田` stays a
  name via `(?!田)`).
- P3: French/Spanish/Italian/Portuguese/Russian calendar words and
  capitalized question words after `¿`/`«`/`(` (sentence-initial detection
  now skips opening punctuation).
- P3: lowercase titles after `titled/entitled/named/called` identify the
  source whatever their case, and the title itself anchors when the source
  contains it.

## Adversarial review — pass 13 REFUTED (4 P1, 6 P2, 1 P3), all acted on

- P1 ×3 (promotion, again): cancellation could abandon the worker mid-swap
  with the lock held, alias compensation and artifact rollback shared one
  `try`, and second-order failures (restore rename failing in `begin`,
  retained tree vanished before `rollback`) could lose the active artifact
  -> the four inlined sequences are gone; `run_promotion_transaction`
  (begin -> alias snapshot -> work -> commit, with independent alias
  compensation and artifact rollback aggregated into `PromotionRollbackError`)
  runs as ONE synchronous unit in a worker thread through
  `await_uncancellable`, which waits for the transaction to settle before
  re-raising a cancellation; `begin` always releases the lock; `rollback`
  refuses to delete the candidate when the retained tree is gone (reported,
  not a silent success). Both jobs' outer handlers never flip a run that is
  already durably `completed`; every post-commit step (counters, legacy
  status, diagnostics, MLflow, complete event) is best-effort.
- P1: a corrupt previous triplets file was not put back when lineage failed
  -> the previous file is retained byte-for-byte and restored atomically.
- P2: alias compensation was a blind overwrite -> compare-and-swap: an alias
  is only moved back when it still points at the failed transaction's bundle
  (or, when that id is unknown, no longer matches the snapshot); an unrelated
  concurrent move is left alone. Compensation writes the alias file directly
  (no bundle re-read mid-failure).
- P2: reranker counters/legacy status outside the best-effort block ->
  inside.
- P3: the agent manual promote ignored the leftover retained tree -> logged.
- P2: `it` anywhere made the subject pronominal -> a pronoun counts as the
  subject only within the question's first four tokens.
- P2: `根据(这|本…)` was still a prefix; `titled this` was exempt -> complete
  demonstrative+document phrases after 根据/根據; the title exception is
  granted only for a meaningful, source-backed title (`titled`/`entitled`
  only — `named`/`called` are verbs).
- P2: Portuguese question words and inflected Russian months/weekdays.
- P2: 明日香 rejected -> a deictic span extended by a content ideograph into a
  source-backed compound is a name.

## Adversarial review — pass 14 REFUTED (3 P1, 4 P2, 1 P3), all acted on

- P1: `rollback` removed the candidate before proving the previous tree
  could be renamed back -> the candidate is parked aside, the previous tree
  restored, and only then deleted; a failed restore puts the candidate back
  and reports both trees.
- P1: the in-process MLX cache was invalidated after commit (and the async
  clear could be cancelled) -> `invalidate_mlx_qwen3_cache_sync` runs INSIDE
  the transaction (and again after a rollback); a generation counter keeps a
  load that started before the swap from re-caching the old weights.
- P1: `run.json` was written with `Path.write_text` (truncate-then-write) ->
  `server/training/atomic_json.py::write_json_atomic` (temp + fsync +
  `os.replace` + directory fsync) in both trainers.
- P2: `await_uncancellable` surfaced a later worker failure instead of the
  cancellation -> it waits for settlement and re-raises the cancellation
  chained to the worker's failure.
- P2: alias compensation with an unknown bundle id was a blind overwrite ->
  a per-repository, per-thread-reentrant `flock` (`repo_lineage_lock`) is
  taken by every alias/bundle writer (`create_or_update_bundle`, `set_alias`,
  `restore_aliases`) and held by the promotion transaction across snapshot ->
  write -> compensation, so no concurrent alias writer can interleave.
- P2: the four-token pronoun window missed "Which of the 2017 regulations
  did he enforce?" -> an English pronoun right after the clause auxiliary is
  the subject wherever it sits; one after a reporting verb is an object.
- P2: a title on another noun exempted "the excerpt" -> the title must
  directly follow the very document noun that matched, and the source must
  be non-empty and contain it.
- P3: Portuguese `quanto/quantos/quê` (+ es/fr/de/it/ru "how many") added.

## Adversarial review — pass 15 REFUTED (2 P1, 5 P2, 1 P3), all acted on

- P1: the lineage lock was constructed/acquired after `begin` but outside
  the compensation block (a lineage-root failure stranded the candidate) ->
  the lock object (and its root) is resolved before anything changes and
  its acquisition is inside the compensated region (`acquired` flag).
- P1: manual promotion invalidated the relative config path while the cache
  key held the absolute one -> `canonical_adapter_path` (resolved) on both
  the cache key and every invalidation.
- P2: the generation check covered wrapper construction, not the weight
  read -> the actual `_load`/`_reload` capture the generation before reading
  and re-read (up to three times) when an invalidation overlapped.
- P2: the new fsyncing `_save_run` ran on the event loop at the start/
  cancel/error paths -> every `_save_run` in async code goes through
  `asyncio.to_thread`; the worker-thread closures stay sync. (Residual: the
  reconciliation writes reached indirectly through the sync `_load_run`
  helpers still run where they are called — small, rare, pre-existing.)
- P2: unresolved possessives (`his balance`, 他的名字) and, more generally,
  an unresolved subject pronoun with an unrelated entity anchor ("What did
  he say about Barry Cohen?") were accepted -> an unresolved subject pronoun
  or possessive rejects the row outright; a pronoun is resolved by a named
  person before it (he/she) or any content noun before it (it/they);
  reporting-verb objects and clefts (`was it that …`, `Was it Barry Cohen
  who …`) are exempt.
- P2: publish rollback re-allocated the old file under the same full disk ->
  the previous file is parked by rename and put back by rename.
- P3: appositive titles ("the excerpt, titled 'X', say?") accepted.

## Adversarial review — pass 16 REFUTED (7 P2), all acted on

- `canonical_adapter_path` resolved relative config paths against the CWD
  -> against the repository root (`resolve_project_path`) on both the cache
  key and every invalidation.
- The hot reload (`_maybe_reload_adapter_locked`) mutated the live model and
  only noticed an overlapping promotion afterwards -> a real re-read loop
  (fingerprint + weights, up to three attempts) that fails before scoring
  when promotions keep overlapping.
- `_save_run` still ran on the loop through `_apply_flyte_state` and both
  cancel helpers -> those helpers are async: cancel-event signalling stays
  on the loop, persistence/events/finalization go through `asyncio.to_thread`.
- "Was it in October 2017 that Barry Cohen …" and "Epstein: why did he …"
  were rejected -> prepositional cleft focus recognized; a sentence-initial
  capitalized word followed by `:`/`,` is an antecedent.
- "Which witness statement said he called …" passed through the
  reporting-verb exemption -> the exemption is gone; a nominative pronoun
  after a reporting verb is an embedded subject that needs an antecedent.
- "after his arrest" resolved by `companies` -> possessives are type-aware
  (his/her and the non-English person forms need a named person; its/their
  any content noun) and every possessive is checked.
- Publish: post-commit cleanup of the parked predecessor was inside the
  failure path and every failure was a 400 -> cleanup is best-effort
  (warning with the retained path); the transaction raises
  `PublishRolledBackError` (previous file put back) / `PublishRollbackError`
  (could not put it back), mapped to a typed 503 for a lineage-store failure
  and 500 otherwise, with the body stating whether the previous file was
  restored; 400 stays for refusals before any change, 409 for corrupt
  artifacts / gate failures.

## Adversarial review — pass 17 REFUTED (6 P2), all acted on

- Flyte reconciliation captured `running` before its off-loop awaits and
  could overwrite a run the job completed meanwhile -> a per-run
  `asyncio.Lock` serializes reconciliation with the job's terminal
  transition, the stored record is re-read after every off-loop step, and
  `_finalize_run_without_job` is compare-and-set (a terminal stored run is
  never overwritten).
- Exhausted hot-reload retries left uncommitted weights in the live model ->
  the model is discarded (full load on the next request).
- Clefts with any bounded focus (`because of …`, `due to …`, `between … and
  …`, a noun phrase) are recognized.
- "Which witness said he …" / "Which pilot changed his route" were rejected
  -> the head noun before the pronoun binds it when it is an explicit animate
  role (or `who`); "witness statement" (inanimate head) still does not.
- "What happened to their aircraft" passed (a verb form as antecedent) and
  French/Spanish/German/Russian grammatical-gender possessives were treated
  as human-only -> verb forms and reporting verbs are never antecedents;
  only English/CJK/Korean person possessives need a named person.
- Parking the predecessor dropped its mode -> the mode is captured before
  the rename and passed into the writer (`write_triplet_rows(..., mode=)`).

## Adversarial review — pass 18 REFUTED (2 P1, 5 P2, 1 P3 + 1 heuristic), all acted on

- P1 ×2: the pass-17 lock was not the single transition authority (a Flyte
  abort could lose to completion/promotion; execute handoff, cancel, orphan
  and failure paths wrote outside it) -> `_transition_run` (per-run lock,
  re-reads the STORED record, compare-and-set on `allowed_from`, mutates the
  stored object, atomic save) is the only way a status changes: job
  completion (CAS + cancellation re-checked INSIDE the lock before any
  promotion; a run ended meanwhile raises and rolls the promotion back),
  cancel/failure handlers, Flyte finalize, execute handoff (status + task
  registration in one critical section), orphan cancel. A real interleaving
  test blocks reconciliation on the held lock while the record completes.
  Deployment contract stated: training jobs are in-process, single worker.
- P2: the parked publish had two unrecoverable crash windows -> a durable
  marker (`.<name>.publish.json`: parked name + committed flag) with
  `begin/commit/abort_parked_replacement` and `recover_parked_replacement`,
  run under the triplets lock by publish, mining and training reads; both
  windows and the committed-but-unremoved case are tested.
- P2: `Was it Barry Cohen?` passed as a cleft -> a cleft needs its clause.
- P2: head-pronoun resolution used a substring search (`Shepherd` contains
  `he`) -> match offsets in the original string.
- P2: `king` hit the `-ing` verb heuristic -> explicit roles are checked
  first.
- P2: CJK took any ideograph as a person; Hangul names never bound ->
  name-like spans (two content ideographs / a hangul stem); the person-vs-
  thing distinction (张伟 vs 飞机) is not decidable without a lexicon and is
  part of the documented uncased-script residual.
- P3: per-run locks leaked -> `WeakValueDictionary`.
- Heuristic residual (documented, not fixed): finite verbs outside the
  `-ed`/`-ing` forms and the reporting-verb list (`became`, `occurs`) can act
  as antecedent nouns for it/their.

## Adversarial review — pass 19 REFUTED (3 P1, 4 P2, 1 P3 heuristic): 6 acted on, 2 moved to a follow-up slice

Acted on:
- P1: an active-job cancellation set the event outside the run lock and
  could land during the promotion copy -> `_request_train_run_cancel` (both
  trainers) takes the run's state lock first: it either lands before the
  in-lock check and wins, or observes the terminal stored record.
- P1: a cancellation during Flyte execution creation was acknowledged and
  then overwritten by the launch coroutine's stale queued object -> the
  execution id is recorded through `_transition_run` (CAS from `queued`);
  when the run ended meanwhile the just-created execution is terminated;
  orphan cancellation accepts `queued` as well as `running`.
- P1: the reranker had the equivalent cancel-vs-promotion race -> per-run
  state lock, `_complete_run` compare-and-set on the stored record with the
  cancellation re-checked inside the lock, cancellation under the same lock.
- P2: the manual Learning Agent promotion saved a record loaded before the
  copy -> the promotion transaction runs under the run lock and
  `_finish_promotion` mutates a freshly loaded record.
- P2: publish recovery deleted valid data in three states and its ordering
  was not durable -> explicit phases (`prepared` / `parked` / `written` /
  `committed`), fail-closed on an unreadable marker (`PublishMarkerError`),
  a target is never removed unless the marker proves it is an uncommitted
  candidate and the named predecessor is present, directory fsync after
  every transition; every state tested.
- P3 (heuristic): the cleft exemption applied to any `it` when a cleft
  occurred later -> scoped to the expletive occurrence.

Moved to `training-run-state-authority-2026-08-23.md` (pre-existing trainer
architecture, a redesign rather than a patch): `_load_run`'s reconciliation
writes outside the authority (P2), and a reader-atomic, crash-recoverable
artifact cutover via versioned directories and an atomic pointer switch with
startup recovery (P2). Until then: readers may observe a missing active path
during the two renames of a promotion, and a crash between them strands the
`.bak_*`/`.tmp_*` trees beside an empty active path.

## Proof required (real queries only)

- Synthetic run on `epstein-files-1` with a paid generator/judge alias ->
  published eval dataset (`data/eval_datasets/epstein-files-1.json`) and
  triplets, quality gate passed.
- `POST /api/eval/run` with Ragas enabled and `POST /api/eval/promptfoo/run`
  executed for real on that dataset.
- `POST /api/reranker/mine` + `POST /api/reranker/train/start` on the mined
  triplets (MLX LoRA, host); Learning Agent run through Flyte on the dataset.
- Chrome drive of Synthetic Lab, Eval Analysis and both Training Centers.
- Adversarial `codex exec` review before done.

## Verification

```bash
uv run pytest -q tests/unit/test_triplet_miner.py tests/unit/test_grounded_qa_provider.py \
  tests/unit/test_synthetic_quality_gate.py tests/api/test_synthetic_endpoints.py \
  tests/api/test_reranker_train_endpoints.py
RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh   # mine-from-eval-run lane
# plus the standard closeout gate in AGENTS.md
```

## Closeout verification (2026-08-23, after pass 4)

- `check_docs_ownership`, `check_banned`, `validate_types`,
  `generate_litellm_config --check`: green (404 aliases in lockstep).
- `uv run pytest -q`: 914 passed / 77 skipped (the skips are the
  `requires_postgres` suites the plain lane cannot run honestly).
- Strict lane (`RAGWELD_STRICT_INTEGRATION=1 ./scripts/test_integration.sh`)
  over the Postgres-backed suites this slice touched plus the new
  `tests/integration/test_eval_trace_mining.py` and the promoted-lane index
  test: 26 passed.
- Playwright gateway spec `eval_data_lane` against the live app (API restarted
  on the final code): 3 passed.
- `npm --prefix web run lint` and `build`: green.
- Not run on this host by operator rule: MLX LoRA training jobs (the no-dev
  promotion path is covered at the decision level only).
