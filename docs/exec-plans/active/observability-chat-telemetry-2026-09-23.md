# Observability, alerting and chat telemetry wave (2026-09-23)

## Goal

Make Grafana, tracing and alerts trustworthy for commercial operators. Every panel
either shows real data or states the rare flow that fills it. Chat gets first-class
telemetry: time to first text, end-to-end latency with the real tail, outcomes, cost,
feedback and Recall decisions. Alerts fire on real problems and never on a lane that
is disabled by design.

## Scope

- **Phase 1 (infra only, starts now).** Fix and extend what already-emitted metrics
  can prove: provisioned dashboards, Prometheus rules, histogram buckets for Tempo
  span metrics and LiteLLM TTFT, a Caddy access log, and gating the vLLM scrape and
  alert on the lane being enabled.
- **Phase 2 (after the chat-stream slice lands).** Emit the chat metric contract
  below from the chat path, fix chunk-level feedback capture, then build the chat
  panels and alerts on those names.

## Non-goals

Reranker training (pinned in `docs/exec-plans/tech-debt-tracker.md`, deferred to
Hugging Face cloud GPUs), a Grafana version upgrade, and new datasources beyond what
is provisioned.

## Chat metric contract (Phase 2 emits exactly these names)

Metrics are exposed on the API `/metrics` endpoint (`server/observability/metrics.py`).
Labels are low-cardinality: no conversation, run or corpus ids.

| Metric | Type | Labels | Semantics |
|---|---|---|---|
| `tribrid_chat_requests_total` | counter | `model`, `outcome` | One per chat request. `outcome` ∈ `ok`, `retrieval_error`, `gateway_error`, `timeout`, `cancelled`, `client_disconnect` |
| `tribrid_chat_time_to_first_event_seconds` | histogram | `model` | Request start → first SSE event (headers flushed) |
| `tribrid_chat_time_to_first_text_seconds` | histogram | `model` | Request start → first answer text delta. Reasoning and status don't count |
| `tribrid_chat_duration_seconds` | histogram | `model`, `outcome` | Request start → terminal event or stream end |
| `tribrid_chat_cost_usd_total` | counter | `model`, `cost_source` | Per-chat authoritative cost (`provider`, `catalog`, `unavailable`=0) |
| `tribrid_chat_tokens_total` | counter | `model`, `kind` | `kind` ∈ `input`, `output`, `reasoning` |
| `tribrid_feedback_events_total` | counter | `signal`, `surface` | `signal` ∈ `thumbsup`, `thumbsdown`, `click`, `note`, `star1`..`star5`; `surface` ∈ `chat`, `search` |
| `tribrid_recall_gate_decisions_total` | counter | `intensity`, `reason` | `intensity` ∈ `skip`, `light`, `standard`, `deep`. `reason` is the gate's rule enum |

**Latency buckets (seconds)** for all three chat histograms:
`0.25, 0.5, 1, 2, 4, 8, 15, 30, 45, 60, 90, 120, 180, 300, 600`.
The current Tempo span-metric buckets top out at 16.384 s and the LiteLLM TTFT buckets
at about 8 s, which hides the 60–120 s stalls seen live on 2026-09-23.

## Acceptance criteria

- A live-query check runs every provisioned panel query against live Prometheus/Mimir
  on LXC100. Each query returns series, or is listed with the rare flow that fills it
  (index run, eval run, reranker run).
- No ratio uses a `clamp_min(..., 1)` denominator. No stat masks an outage with
  `or vector(0)`.
- No panel queries a stage label that is never emitted.
- No template variable is decorative.
- The alert set has no rule for a disabled lane.
- Alerts route to an operator-chosen receiver. Until one is chosen, rules may exist,
  but no destination is invented.

## Risks / failure modes

- Restarting LiteLLM resets its in-memory Prometheus counters, so gateway panels dip
  after deploys.
- Grafana 10.0.0 feature limits.
- `infra/litellm-config.yaml` is generated from `data/models.json`: edit the generator
  or template, never the output.
- Per-corpus config lives in Postgres, so changed defaults don't reach existing corpora
  without a migration or explicit write.

## Verification

- The live-query script.
- The touched unit/API suites on an LXC100 overlay.
- A deployed Grafana pass in the operator's Chrome.

## Rollout / rollback

- Batched deploy on LXC100 via bundle and fast-forward.
- Grafana and Prometheus pick up provisioning on container restart; Caddy reloads.
- Rollback: the previous commit plus a restart of the affected containers.
