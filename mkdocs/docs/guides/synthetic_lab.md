

# Synthetic Data Lab

<div class="grid chunk_summaries" markdown>

-   :material-flask:{ .lg .middle } **Recipe-driven generation**

    ---

    Turn an indexed corpus into grounded eval datasets, reranker triplets, semantic cards, and keywords — recipe by recipe, not one giant pipeline.

-   :material-scale-balance:{ .lg .middle } **Judge + quality gate**

    ---

    System One judges every row against two typed thresholds, a verbatim evidence check rejects ungrounded ones, and a retrieval quality gate blocks publication before weak data reaches your evals.

-   :material-shield-lock:{ .lg .middle } **Gated promotion**

    ---

    Only a completed, gate-passed run can be promoted to a lineage alias — enforced server-side, including on the raw lineage endpoint, so a failed run can never become "current".

</div>

[Get started](../index.md){ .md-button .md-button--primary }
[Evaluation guide](../eval_guide.md){ .md-button }
[Config reference: synthetic](../reference/config/synthetic.md){ .md-button }
[Config reference: system_one](../reference/config/system_one.md){ .md-button }

!!! tip "Where it lives"
    Open **RAG → Synthetic Lab** with a corpus selected. Every run is scoped to that corpus, and each run ends with artifacts, a run report, and (for full-stack recipes) a lineage bundle you can publish or promote.

!!! note "Generation costs money"
    Generator calls route through the LiteLLM gateway using the alias you pick per run, and every generated row is then judged by System One (`system_one.*`) — its own endpoint, not a gateway alias. A gated recipe that fails its quality gate has already spent the generation cost — the gate decides whether the output may be *used*, not whether it is free. Run small `max_pairs` first.

## What one run does

A run walks the corpus's indexed chunks in bounded batches:

1. **Generate** — the generator prompt (`system_prompts.synthetic_generator`) asks for question / expected answer / verbatim evidence-quote rows grounded in one chunk's excerpt, with self-contained questions (no "this document").
2. **Ground** — a row survives only when its `evidence_quote` appears **verbatim** in the source chunk; anything else is counted as ungrounded and dropped.
3. **Judge** — every row is judged by System One (`system_one.provider` / `system_one.model`), not by a gateway model: two typed judgments — does the evidence quote, not the file name or path, support the expected answer, and would a real reader ask this question about the document's subject — must each clear its threshold (`synthetic.judge.answer_supported_min` and `synthetic.judge.reader_question_min`, both 0.7 by default), and a row below either is dropped.
4. **Gate** — for retrieval-affecting recipes (`eval_dataset`, `triplets`), the gate retrieves the run's own generated questions against the corpus via `POST /api/search` and requires top-1 accuracy >= `synthetic.quality_gate.top1_min` over `synthetic.quality_gate.sample_size` samples.

!!! note "Every run names one model: the generator"
    `POST /api/synthetic/run/start` carries only `generator_model`, and it must be a `litellm:<gateway_alias>` route — a direct provider id such as `openai/gpt-6-luna` is refused with a `422` rather than silently bypassing the gateway. There is no `judge_model` field: the rows are judged by System One (`system_one.provider` / `system_one.model`), which is configured outside the generator alias, and the `synthetic.judge.*` thresholds below decide what survives. See the [system_one config reference](../reference/config/system_one.md) for that endpoint's knobs.

!!! warning "The quality gate is a self-consistency check, not external validation"
    The gate retrieves the run's *own* generated questions against the corpus they came from. A perfect score proves the questions are self-consistent with the index — it is **not** evidence of retrieval quality on real operator questions. Validate published datasets with the [Evaluation guide](../eval_guide.md) workflows.

## Recipes and artifacts

| Recipe | Artifact | Publish action | Quality-gated |
|---|---|---|---|
| Grounded QA | `eval_dataset_json` | Publish eval dataset | yes |
| Triplets | `triplets_jsonl` | Publish triplets (reranker training) | yes |
| Semantic summaries | `semantic_cards_jsonl` | Publish semantic summaries | no |
| Keywords | keywords file | Publish keywords | no |

Every run also writes a human-readable `report_md` summary. That report is not published to a corpus store, so it has no Publish action; each artifact row carries **Copy path**, **Preview** (a bounded, read-only preview of the artifact rows), and **Publish** where applicable.

The recipe picker labels every lane in plain language — **Eval Dataset**, **Semantic Summaries**, **Triplets**, **Keywords**, **Autotune Retrieval**, and **Full Stack** — and the deep-link preset notice uses those labels too (`Recipe preset to "Eval Dataset" … Nothing has run`). Autotune Retrieval and Full Stack sit in the same picker under the same rules as the recipes above: nothing runs until you start it there, and each run writes its artifacts and report to the run record.

## Publish vs promote

Publishing writes an artifact into the corpus's stores (eval datasets, triplets, cards, keywords). **Promotion** moves a lineage alias — `baseline`, `canary`, `current`, or `promoted` — to point at the run's bundle, which is how the rest of the platform records "this output is now the reference".

The gate is enforced server-side on both paths:

| Run state | Promote? | What you see |
|---|---|---|
| `completed`, gate passed (or recipe has no gate), bundle attached | yes | alias buttons enabled |
| failed or still running | no — typed `409 PROMOTION_BLOCKED` | disabled buttons + the reason |
| completed but the gate failed | no — `409` | the gate's failure reason |
| completed but never attached to a bundle | no — `409` | "not attached to a lineage bundle" |

The **raw lineage endpoint** refuses too: `POST /api/lineage/aliases/{alias}` checks whether the posted bundle id belongs to a synthetic run and applies the same gate, so a direct API call cannot bypass the UI's disabled buttons. It fails closed — if a run's record no longer validates, promotion is refused rather than trusted.

```mermaid
flowchart LR
  subgraph s_req["Request (RAG - Synthetic Lab)"]
    REQ["POST /api/synthetic/run/start\\nrecipe + generator model"]
  end
  subgraph s_orch["Orchestrator (server/synthetic/orchestrator.py)"]
    ORCH["Per-source chunk batches"]
    GEN["Generator LLM\\nsynthetic.generator.*\\nvia the LiteLLM gateway :54000"]
    GROUND["Grounding check\\nevidence_quote verbatim\\nin the source chunk"]
    REJ["Ungrounded + malformed rows rejected"]
    JUDGE["System One judging\\nsystem_one.provider / system_one.model\\nsynthetic.judge.* thresholds"]
    GATE["Quality gate\\nsynthetic.quality_gate.*\\nPOST /api/search on the corpus"]
    ART["Artifacts + report\\neval dataset / triplets /\\nsemantic cards / keywords"]
  end
  subgraph s_store["Run store and lineage"]
    RUNS["Run record\\nrun.json + live events"]
    BUNDLE["Lineage bundle"]
    PUBLISH["Publish endpoints\\n/synthetic/run/:id/publish/:kind"]
    PROMOTE["Promotion gate\\ncompleted + gate passed +\\nbundle attached, else 409"]
    ALIAS["POST /api/synthetic/run/:id/promote/:alias\\nand POST /api/lineage/aliases/:alias"]
    SET["Alias updated\\nbaseline / canary / current / promoted"]
  end
  REQ --> ORCH
  ORCH --> GEN
  GEN --> GROUND
  GROUND --> REJ
  GROUND --> JUDGE
  JUDGE --> GATE
  GATE --> ART
  GATE -->|"gate failed"| RUNS
  ART --> RUNS
  ART --> PUBLISH
  RUNS --> BUNDLE
  BUNDLE --> PROMOTE
  PROMOTE --> ALIAS
  ALIAS --> SET
```

## When a run fails

A failed run is a data point, not a dead end:

- The run detail shows the failure reason in a **Run failed** card; **Live events** below it holds the run log.
- **Retry** re-launches with the exact recipe, model, and parameters the run stored — no rebuilding the request by hand.
- Aliases stay locked until a run actually completes and passes its gate.

=== "Retry from the UI"

    Open the failed run in **RAG → Synthetic Lab**, read the reason, fix the cause (an unindexed corpus, an unreachable gateway alias), then press **Retry**.

=== "Retry from the API"

    Start a new run with the same request body you used before (`POST /api/synthetic/run/start`); the run record's `request` block is exactly that body. Cancel a still-running run first if you need to:

    ```bash
    curl -sS -X POST "http://127.0.0.1:58012/api/synthetic/run/<run_id>/cancel" | jq .
    ```

!!! tip "Read the numbers the way the run wrote them"
    The Grounding & Curation panel reports `sources` used, `generated`, `ungrounded`, `malformed`, `judged`, `kept`, the average judgment score, and mined `triplets`. A run with many `ungrounded` rows is telling you the generator is reaching beyond its excerpt — narrow the per-run excerpt scope or lower `pairs_per_source` rather than loosening the curation thresholds.

## Knobs

All knobs are generated in the [synthetic config reference](../reference/config/synthetic.md). The ones that matter first:

| Knob | Default | Why it matters |
|---|---|---|
| `synthetic.generator.max_tokens` | 1200 | Output budget per generator call; too low truncates JSON rows |
| `synthetic.generator.temperature` | 0.0 | Keep at 0 for grounded, reproducible rows |
| `synthetic.generator.concurrency` | 4 | Parallel gateway calls; forced to 1 for the single-stream local serving row |
| `synthetic.judge.temperature` | 0.0 | A judge that samples is a judge that wobbles |
| `synthetic.judge.answer_supported_min` | 0.7 | Minimum probability that the evidence quote — not the file name or path — supports the expected answer |
| `synthetic.judge.reader_question_min` | 0.7 | Minimum probability a real reader would ask this question about the document's subject, not cover or filename trivia |
| `synthetic.quality_gate.sample_size` | 50 | Questions sampled for the gate — raise for a stronger signal |
| `synthetic.quality_gate.top1_min` | 0.4 | Minimum top-1 accuracy to pass; raise cautiously |

Judging itself is configured outside the synthetic section: `system_one.provider` and `system_one.model` pick the System One endpoint that scores the rows — TypeSafe's hosted Jev (`TYPESAFE_API_KEY`), or a self-hosted laya-serve (offline, no credential). See the [system_one config reference](../reference/config/system_one.md).

!!! tip "If you're not sure"
    Start with the `eval_dataset` recipe and small limits, read the run report, and only promote (point an alias at) runs whose gate passed on a healthy sample. Wire the published dataset into an eval run before trusting it in any regression workflow.

