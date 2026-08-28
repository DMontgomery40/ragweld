# Config reference: `tracing`

<div class="grid chunk_summaries" markdown>

-   :material-tune:{ .lg .middle } **Enterprise tuning surface**

    ---

    Defaults + constraints are rendered directly from Pydantic.

-   :material-key-outline:{ .lg .middle } **Env keys when available**

    ---

    Many fields have an env-style alias (from `TriBridConfig.to_flat_dict()`).

-   :material-tooltip-text:{ .lg .middle } **Tooltip-level guidance**

    ---

    If a matching glossary entry exists, you’ll see deeper tuning notes.

</div>

[Config reference](index.md){ .md-button .md-button--primary }
[Config API & workflow](../../configuration.md){ .md-button }
[Glossary](../../glossary.md){ .md-button }

**Total parameters**: 26

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `tracing.alert_include_resolved` | `ALERT_INCLUDE_RESOLVED` | `bool` | `true` | — | Include resolved alerts |
| `tracing.alert_notify_severities` | `ALERT_NOTIFY_SEVERITIES` | `str` | `"critical,warning"` | — | Alert severities to notify |
| `tracing.alert_webhook_timeout` | `ALERT_WEBHOOK_TIMEOUT` | `int` | `5` | ≥ 1, ≤ 30 | Alert webhook timeout (seconds) |
| `tracing.alertmanager_base_url` | `ALERTMANAGER_BASE_URL` | `str` | `""` | — | Alertmanager base URL used for wake-up path status checks |
| `tracing.alloy_base_url` | `ALLOY_BASE_URL` | `str` | `""` | — | Grafana Alloy base URL used for collector status checks |
| `tracing.cost_tracking_enabled` | `COST_TRACKING_ENABLED` | `bool` | `true` | — | Enable online request cost attribution in traces |
| `tracing.faro_base_url` | `FARO_BASE_URL` | `str` | `""` | — | Grafana Faro or collector base URL used for frontend telemetry status checks |
| `tracing.langfuse_base_url` | `LANGFUSE_BASE_URL` | `str` | `""` | — | Langfuse base URL |
| `tracing.langfuse_enabled` | `LANGFUSE_ENABLED` | `bool` | `false` | — | Enable Langfuse generation observations |
| `tracing.langfuse_project` | `LANGFUSE_PROJECT` | `str` | `"ragweld"` | — | Langfuse project label for traces and generations |
| `tracing.log_level` | `LOG_LEVEL` | `str` | `"INFO"` | pattern=^(DEBUG\|INFO\|WARNING\|ERROR)$ | Logging level |
| `tracing.metrics_enabled` | `METRICS_ENABLED` | `bool` | `true` | — | Enable metrics collection |
| `tracing.mimir_base_url` | `MIMIR_BASE_URL` | `str` | `""` | — | Grafana Mimir base URL used for metrics backend status checks |
| `tracing.opencost_base_url` | `OPENCOST_BASE_URL` | `str` | `""` | — | OpenCost base URL used for cost and capacity status checks |
| `tracing.otel_export_enabled` | `OTEL_EXPORT_ENABLED` | `bool` | `true` | — | Enable OTLP export for traces |
| `tracing.otel_service_name` | `OTEL_SERVICE_NAME` | `str` | `"ragweld-api"` | — | Service name used for emitted OTel spans |
| `tracing.otlp_endpoint` | `OTLP_ENDPOINT` | `str` | `""` | — | OTLP HTTP endpoint for trace export |
| `tracing.otlp_headers` | `OTLP_HEADERS` | `str` | `""` | — | Comma-separated OTLP headers (k=v) for the exporter |
| `tracing.prometheus_base_url` | `PROMETHEUS_BASE_URL` | `str` | `""` | — | Prometheus base URL used for the alert-rule feed and operator deep links (Prometheus scrapes and remote-writes to Mimir) |
| `tracing.pyroscope_base_url` | `PYROSCOPE_BASE_URL` | `str` | `""` | — | Grafana Pyroscope base URL used for profiling status checks |
| `tracing.tempo_base_url` | `TEMPO_BASE_URL` | `str` | `""` | — | Tempo or Grafana explore base URL used for trace deep links |
| `tracing.trace_retention` | `TRACE_RETENTION` | `int` | `50` | ≥ 10, ≤ 500 | Number of traces to retain |
| `tracing.trace_sampling_rate` | `TRACE_SAMPLING_RATE` | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Trace sampling rate (0.0-1.0) |
| `tracing.tracing_enabled` | `TRACING_ENABLED` | `bool` | `true` | — | Enable distributed tracing |
| `tracing.tracing_mode` | `TRACING_MODE` | `str` | `"local"` | pattern=^(local\|otel\|otel_langfuse\|off)$ | Observability mode |
| `tracing.tribrid_log_path` | `TRIBRID_LOG_PATH` | `str` | `"data/logs/queries.jsonl"` | — | Query log file path |

### Details (glossary)

??? info "`tracing.alert_include_resolved` (`ALERT_INCLUDE_RESOLVED`) — Alert Include Resolved"
    **Category**: `general`

    `ALERT_INCLUDE_RESOLVED` controls whether the alert pipeline emits a second notification when an incident transitions from firing to resolved. In this stack, keeping it enabled (default) gives on-call responders explicit closure signals, which helps reconcile incident timelines and downstream ticket automation. Disabling it reduces message volume but removes recovery-state visibility, so unresolved-looking alerts can persist in chat channels or incident tools even after the condition clears. Enable it when you rely on auditability and MTTR measurement, and only disable it if notification fatigue is materially harming response quality.

    **Links**:
    - [Root Cause Analysis Method Based on Large Language Models with Residual Connection Structures (arXiv)](https://arxiv.org/abs/2602.08804)
    - [Prometheus Alertmanager webhook_config (send_resolved)](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
    - [PagerDuty Events API v2 Overview](https://developer.pagerduty.com/docs/events-api-v2/overview/)
    - [OpenTelemetry Log Data Model: Severity Fields](https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber)

??? info "`tracing.alert_notify_severities` (`ALERT_NOTIFY_SEVERITIES`) — Alert Notify Severities"
    **Category**: `general`

    `ALERT_NOTIFY_SEVERITIES` is the final severity allowlist applied before outbound notification fan-out, using a comma-separated vocabulary such as `critical,warning`. The configured values must match the exact severity labels emitted upstream, otherwise valid alerts can be silently filtered out at dispatch time. With the default `critical,warning`, the system typically captures high-urgency incidents while limiting low-signal noise; adding `info` expands coverage but increases paging and webhook traffic. Treat this setting as an operations policy control: tune it against real incident outcomes, not just raw alert counts.

    **Links**:
    - [Root Cause Analysis Method Based on Large Language Models with Residual Connection Structures (arXiv)](https://arxiv.org/abs/2602.08804)
    - [Prometheus Alertmanager webhook_config (send_resolved)](https://prometheus.io/docs/alerting/latest/configuration/#webhook_config)
    - [PagerDuty Events API v2 Overview](https://developer.pagerduty.com/docs/events-api-v2/overview/)
    - [OpenTelemetry Log Data Model: Severity Fields](https://opentelemetry.io/docs/specs/otel/logs/data-model/#field-severitynumber)

??? info "`tracing.alert_webhook_timeout` (`ALERT_WEBHOOK_TIMEOUT`) — Alert Webhook Timeout"
    **Category**: `general`

    ALERT_WEBHOOK_TIMEOUT defines how long the system waits for an outbound alert webhook before treating delivery as failed. In RAG operations this prevents indexing, tracing, or incident pipelines from stalling when third-party endpoints degrade. Set it from real latency percentiles: high enough for normal network jitter, low enough to preserve queue health and fast failure detection during outages. This value works best with idempotent payloads, retry backoff, and dead-letter handling so timeouts become controlled recovery signals instead of duplicate alert storms.

    **Badges**:
    - Reliability

    **Links**:
    - [LA-IMR: Latency-Aware Tail-Latency Control (arXiv)](https://arxiv.org/abs/2505.07417)
    - [GitHub Webhook Best Practices](https://docs.github.com/en/webhooks/using-webhooks/best-practices-for-using-webhooks)
    - [Stripe Webhooks](https://docs.stripe.com/webhooks)
    - [MDN AbortSignal.timeout](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static)

??? info "`tracing.alertmanager_base_url` (`ALERTMANAGER_BASE_URL`) — Alertmanager Base URL"
    **Category**: `infrastructure`

    ALERTMANAGER_BASE_URL points ragweld at the Prometheus Alertmanager that receives alert rules fired by Prometheus (infra/prometheus-rules.yml). The always-firing RagweldWatchdog alert proves the delivery pipe end to end; its absence from Alertmanager means rule evaluation or routing is broken. Readiness is probed at /-/ready.

    **Badges**:
    - alerting

    **Links**:
    - [Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)

??? info "`tracing.alloy_base_url` (`ALLOY_BASE_URL`) — Alloy Base URL"
    **Category**: `infrastructure`

    ALLOY_BASE_URL identifies the Grafana Alloy collector instance used in the local or deployed observability path. Ragweld uses it for readiness checks and operator hints, so point it at the collector operators should verify first when OTLP export is enabled.

    **Badges**:
    - Collector status

    **Links**:
    - [Grafana Alloy](https://grafana.com/docs/alloy/latest/)

??? info "`tracing.cost_tracking_enabled` (`COST_TRACKING_ENABLED`) — Cost Tracking Enabled"
    **Category**: `general`

    COST_TRACKING_ENABLED turns on best-effort online request cost attribution in the workbench trace path. When enabled, ragweld prefers provider or gateway cost truth and falls back to catalog-derived estimates when only token counts are available. Keep it on when operators need to compare quality, latency, and spend together during debugging or tuning.

    **Badges**:
    - Cost visibility

    **Links**:
    - [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)

??? info "`tracing.faro_base_url` (`FARO_BASE_URL`) — Faro Base URL"
    **Category**: `infrastructure`

    FARO_BASE_URL is the frontend RUM collector endpoint (the Alloy faro.receiver /collect URL). When set, the workbench initializes the Faro Web SDK on boot and ships browser errors, web vitals, and session events; Alloy labels them service_name=ragweld-web and forwards logs to Loki. The status probe treats an HTTP 405/415 to GET as listener-present because the intake is POST-only.

    **Badges**:
    - RUM

    **Links**:
    - [Grafana Faro](https://grafana.com/oss/faro/)

??? info "`tracing.langfuse_base_url` (`LANGFUSE_BASE_URL`) — Langfuse Base URL"
    **Category**: `infrastructure`

    LANGFUSE_BASE_URL points ragweld at the Langfuse deployment used for generation-level observability. Set it to your self-hosted or managed Langfuse instance so the workbench can deep-link from a request trace into prompt and generation drilldown. If this URL is wrong or missing, Langfuse mode should be treated as not ready.

    **Badges**:
    - LLM tracing

    **Links**:
    - [Langfuse Self-Hosting](https://langfuse.com/docs/deployment/self-host)

??? info "`tracing.langfuse_enabled` (`LANGFUSE_ENABLED`) — Langfuse Enabled"
    **Category**: `general`

    LANGFUSE_ENABLED controls whether ragweld enriches generation spans with Langfuse-native prompt, usage, and cost metadata. Enable it when operators need prompt/generation drilldown in addition to raw OpenTelemetry traces. Keep it off if you want pure OTel export without external LLM-native observation.

    **Badges**:
    - LLM observability

    **Links**:
    - [Langfuse Documentation](https://langfuse.com/docs)
    - [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)

??? info "`tracing.langfuse_project` (`LANGFUSE_PROJECT`) — Langfuse Project"
    **Category**: `general`

    LANGFUSE_PROJECT labels the generation traces emitted into Langfuse. Use a stable environment-aware name so operators can compare prompt, cost, and failure patterns without fragmenting trace history across arbitrary project names.

    **Badges**:
    - Namespace hygiene

    **Links**:
    - [Langfuse Documentation](https://langfuse.com/docs)

??? info "`tracing.log_level` (`LOG_LEVEL`) — Log Level"
    **Category**: `general`

    Controls runtime verbosity for diagnostics, operational visibility, and incident response. `DEBUG` is best for short-lived debugging sessions where per-step details matter; `INFO` is the stable default for normal operation; `WARNING` and `ERROR` reduce noise when you only need actionable signals. Excessive debug logging can materially impact latency and storage cost, and can also increase risk of sensitive payload exposure if message templates are not scrubbed. Production-safe practice is to run at INFO/WARNING and temporarily raise verbosity during scoped investigations.

    **Links**:
    - [LLM-SrcLog: Source-Aware Log Analysis with LLMs (arXiv 2025)](https://arxiv.org/abs/2512.04474)
    - [Python Logging Levels Reference](https://docs.python.org/3/library/logging.html#logging-levels)
    - [OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)
    - [RFC 5424 Syslog Severity and Structured Logging](https://www.rfc-editor.org/rfc/rfc5424)

??? info "`tracing.metrics_enabled` (`METRICS_ENABLED`) — Metrics Enabled"
    **Category**: `evaluation`

    Master toggle for emitting runtime metrics from the application. When enabled, the process publishes counters, gauges, and histograms used for dashboards, alerting, and SLO tracking; when disabled, you lose quantitative visibility into throughput, error rates, latency distributions, and retrieval quality trends. Enable this in any shared or production-like environment, then gate high-cardinality labels to control cost. The goal is not just observability but fast diagnosis: metrics should let you correlate parameter changes (retrieval thresholds, rewrites, model routing) with concrete performance and reliability shifts.

    **Links**:
    - [Agentic Observability: Automated Alert Triage (arXiv 2026)](https://arxiv.org/abs/2602.02585)
    - [Prometheus Instrumentation Best Practices](https://prometheus.io/docs/practices/instrumentation/)
    - [OpenTelemetry Metrics API Spec](https://opentelemetry.io/docs/specs/otel/metrics/api/)
    - [Grafana Alerting Documentation](https://grafana.com/docs/grafana/latest/alerting/)

??? info "`tracing.mimir_base_url` (`MIMIR_BASE_URL`) — Mimir Base URL"
    **Category**: `infrastructure`

    MIMIR_BASE_URL points ragweld at the Grafana Mimir deployment that keeps long-range metrics. Prometheus forwards every sample it ingests to Mimir over remote write, so Mimir answers PromQL for retention windows Prometheus itself no longer holds. Readiness is probed at /ready; when the URL is empty the component reports disabled, never healthy.

    **Badges**:
    - metrics

    **Links**:
    - [Grafana Mimir](https://grafana.com/oss/mimir/)

??? info "`tracing.otel_export_enabled` (`OTEL_EXPORT_ENABLED`) — OTel Export Enabled"
    **Category**: `general`

    OTEL_EXPORT_ENABLED turns canonical OpenTelemetry export on or off for live request traces. When enabled alongside a valid OTLP endpoint, ragweld emits correlated spans that can be inspected outside the local workbench buffer. Keep this enabled for shared environments where operators need cross-service trace continuity, and disable it only when you intentionally want local-only observability.

    **Badges**:
    - Observability

    **Links**:
    - [OpenTelemetry Exporters](https://opentelemetry.io/docs/concepts/signals/traces/#exporters)
    - [OTLP Exporter Configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)

??? info "`tracing.otel_service_name` (`OTEL_SERVICE_NAME`) — OTel Service Name"
    **Category**: `general`

    OTEL_SERVICE_NAME sets the service identity attached to emitted spans. Stable service naming makes Tempo searches, Grafana dashboards, and cross-service correlation reliable across environments. Treat this as part of your observability contract, not as an arbitrary label.

    **Badges**:
    - Trace identity

    **Links**:
    - [OpenTelemetry Resources](https://opentelemetry.io/docs/concepts/resources/)

??? info "`tracing.otlp_endpoint` (`OTLP_ENDPOINT`) — OTLP Endpoint"
    **Category**: `infrastructure`

    OTLP_ENDPOINT is the HTTP destination used for canonical trace export from the ragweld API. Point it at Grafana Alloy or another collector that can forward traces into Tempo and the rest of your observability fabric. If this value is blank while OTel export mode is enabled, traces stay local and operators lose end-to-end external drilldown.

    **Badges**:
    - Trace routing

    **Links**:
    - [OTLP Specification](https://opentelemetry.io/docs/specs/otlp/)
    - [Grafana Alloy](https://grafana.com/docs/alloy/latest/)

??? info "`tracing.otlp_headers` (`OTLP_HEADERS`) — OTLP Headers"
    **Category**: `general`

    OTLP_HEADERS carries any required authentication or tenant-routing headers for the OTLP exporter. Use it when the collector path sits behind auth or multi-tenant gateways, and keep the values consistent with the endpoint you configured. Header mismatches are a common cause of silent export failures.

    **Badges**:
    - Transport auth

    **Links**:
    - [OTLP Exporter Configuration](https://opentelemetry.io/docs/languages/sdk-configuration/otlp-exporter/)

??? info "`tracing.prometheus_base_url` (`PROMETHEUS_BASE_URL`) — Prometheus Base URL"
    **Category**: `infrastructure`

    PROMETHEUS_BASE_URL points ragweld at the Prometheus server that scrapes the API, gateway, local model and exporters and forwards every sample to Mimir over remote write. Prometheus also evaluates infra/prometheus-rules.yml, so this URL is where the Monitoring surface reads the live alert rules (state, severity, expression, for-duration) and where the Open Prometheus link lands. When the URL is empty the alert-rule feed reports unconfigured instead of showing an empty rule list.

    **Links**:
    - [Prometheus alerting rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)

??? info "`tracing.pyroscope_base_url` (`PYROSCOPE_BASE_URL`) — Pyroscope Base URL"
    **Category**: `infrastructure`

    PYROSCOPE_BASE_URL points ragweld at the Grafana Pyroscope server used for continuous profiling. When set, the host API attaches the Pyroscope agent at startup and pushes ragweld-api CPU profiles; the component status reports both server readiness (/ready) and the truthful host-agent state. Empty means profiling is off and the component reports disabled.

    **Badges**:
    - profiling

    **Links**:
    - [Grafana Pyroscope](https://grafana.com/oss/pyroscope/)

??? info "`tracing.tempo_base_url` (`TEMPO_BASE_URL`) — Tempo Base URL"
    **Category**: `infrastructure`

    TEMPO_BASE_URL is the trace lookup base used for deep-linking canonical request traces into Tempo or Grafana Explore. Set it to a URL operators can actually open from the workbench so trace ids become actionable drilldown links instead of inert metadata.

    **Badges**:
    - Trace drilldown

    **Links**:
    - [Grafana Tempo Documentation](https://grafana.com/docs/tempo/latest/)

??? info "`tracing.trace_retention` (`TRACE_RETENTION`) — Trace Retention"
    **Category**: `general`

    TRACE_RETENTION defines how long trace records are kept before pruning. Retention is a tradeoff between forensic depth and operational cost: longer windows improve post-incident analysis and regression investigations, while shorter windows limit storage growth and reduce compliance surface area. Set this value based on your incident review cadence and model rollout cycle, then validate that pruning does not remove traces needed for reproducibility. In production, align retention with data-governance policy and downstream index lifecycle settings so trace deletion is predictable and auditable.

    **Links**:
    - [GraphTracer: Tracing Dynamic Dataflow in Agentic AI Systems (arXiv 2025)](https://arxiv.org/abs/2510.10581)
    - [Elasticsearch Index Lifecycle Management (ILM)](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
    - [OpenSearch Index State Management (ISM)](https://docs.opensearch.org/latest/im-plugin/ism/index/)

??? info "`tracing.trace_sampling_rate` (`TRACE_SAMPLING_RATE`) — Trace Sampling Rate"
    **Category**: `general`

    TRACE_SAMPLING_RATE sets the fraction of requests that emit full traces. Higher sampling improves visibility into rare routing failures and latency spikes, but increases telemetry volume, cost, and operator noise. Lower sampling is cheaper but can miss edge cases unless paired with rule-based overrides for errors, timeouts, or high-value tenants. A robust strategy is adaptive sampling: keep a low baseline for normal traffic and automatically raise sampling around deployments, incidents, or anomalous metrics.

    **Badges**:
    - Cost control
    - Observability

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [OpenTelemetry Trace SDK (samplers and processors)](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)

??? info "`tracing.tracing_enabled` (`TRACING_ENABLED`) — Tracing Enabled"
    **Category**: `general`

    TRACING_ENABLED is the master switch for request-level trace capture in the retrieval and generation pipeline. When enabled, each request can emit structured events that explain routing decisions, retrieval candidates, rerank outcomes, and timing breakdowns. This setting is foundational for debugging because it turns opaque failures into inspectable execution paths. In production, keep it enabled with controlled sampling so you retain diagnostic coverage without overwhelming observability storage.

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)

??? info "`tracing.tracing_mode` (`TRACING_MODE`) — Tracing Mode"
    **Category**: `general`

    TRACING_MODE selects how request traces are handled in ragweld: local workbench buffering, canonical OpenTelemetry export, OpenTelemetry plus Langfuse generation observability, or fully off. This mode determines which headers and deep links appear in the UI, where spans are emitted, and whether operators can correlate a live request across FastAPI, retrieval, provider routing, and external observability backends. Keep mode changes explicit and test them with live requests so trace continuity, cost attribution, and drilldown links stay trustworthy across environments.

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [Grafana Tempo Documentation](https://grafana.com/docs/tempo/latest/)

??? info "`tracing.tribrid_log_path` (`TRIBRID_LOG_PATH`) — Reranker Log Path"
    **Category**: `general`

    TRIBRID_LOG_PATH specifies where local runtime logs and trace artifacts are written on disk. A stable, writable path is required for reproducibility workflows such as replaying failure cases, auditing retrieval decisions, and comparing behavior across model/version changes. In multi-process deployments, this path should be paired with rotation and retention policy to prevent unbounded growth and partial-write corruption. Treat log-path configuration as part of operational hardening: explicit permissions, predictable lifecycle, and compatibility with your observability export strategy.

    **Links**:
    - [GraphTracer: Tracing Dynamic Dataflow in Agentic AI Systems (arXiv 2025)](https://arxiv.org/abs/2510.10581)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [Elasticsearch Index Lifecycle Management (ILM)](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
    - [LangSmith Data Purging and Compliance](https://docs.langchain.com/langsmith/data-purging-compliance)
