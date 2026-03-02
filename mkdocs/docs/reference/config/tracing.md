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

**Total parameters**: 17

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `tracing.alert_include_resolved` | `ALERT_INCLUDE_RESOLVED` | `int` | `1` | ≥ 0, ≤ 1 | Include resolved alerts |
| `tracing.alert_notify_severities` | `ALERT_NOTIFY_SEVERITIES` | `str` | `"critical,warning"` | — | Alert severities to notify |
| `tracing.alert_webhook_timeout` | `ALERT_WEBHOOK_TIMEOUT` | `int` | `5` | ≥ 1, ≤ 30 | Alert webhook timeout (seconds) |
| `tracing.langchain_endpoint` | `LANGCHAIN_ENDPOINT` | `str` | `"https://api.smith.langchain.com"` | — | LangChain/LangSmith API endpoint |
| `tracing.langchain_project` | `LANGCHAIN_PROJECT` | `str` | `"tribrid"` | — | LangChain project name |
| `tracing.langchain_tracing_v2` | `LANGCHAIN_TRACING_V2` | `int` | `0` | ≥ 0, ≤ 1 | Enable LangChain v2 tracing |
| `tracing.langtrace_api_host` | `LANGTRACE_API_HOST` | `str` | `""` | — | LangTrace API host |
| `tracing.langtrace_project_id` | `LANGTRACE_PROJECT_ID` | `str` | `""` | — | LangTrace project ID |
| `tracing.log_level` | `LOG_LEVEL` | `str` | `"INFO"` | pattern=^(DEBUG\|INFO\|WARNING\|ERROR)$ | Logging level |
| `tracing.metrics_enabled` | `METRICS_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable metrics collection |
| `tracing.prometheus_port` | `PROMETHEUS_PORT` | `int` | `9090` | ≥ 1024, ≤ 65535 | Prometheus metrics port |
| `tracing.trace_auto_ls` | `TRACE_AUTO_LS` | `int` | `1` | ≥ 0, ≤ 1 | Auto-enable LangSmith tracing |
| `tracing.trace_retention` | `TRACE_RETENTION` | `int` | `50` | ≥ 10, ≤ 500 | Number of traces to retain |
| `tracing.trace_sampling_rate` | `TRACE_SAMPLING_RATE` | `float` | `1.0` | ≥ 0.0, ≤ 1.0 | Trace sampling rate (0.0-1.0) |
| `tracing.tracing_enabled` | `TRACING_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable distributed tracing |
| `tracing.tracing_mode` | `TRACING_MODE` | `str` | `"langsmith"` | pattern=^(langsmith\|local\|none\|off)$ | Tracing backend mode |
| `tracing.tribrid_log_path` | `TRIBRID_LOG_PATH` | `str` | `"data/logs/queries.jsonl"` | — | Query log file path |

### Details (glossary)

??? info "`tracing.alert_include_resolved` (`ALERT_INCLUDE_RESOLVED`) — Alert Include Resolved"
    **Category**: `general`

    `ALERT_INCLUDE_RESOLVED` controls whether the alert pipeline emits a second notification when an incident transitions from firing to resolved. In this stack, keeping it enabled (`1`, default) gives on-call responders explicit closure signals, which helps reconcile incident timelines and downstream ticket automation. Disabling it (`0`) reduces message volume but removes recovery-state visibility, so unresolved-looking alerts can persist in chat channels or incident tools even after the condition clears. Use `1` when you rely on auditability and MTTR measurement, and only disable it if notification fatigue is materially harming response quality.

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

??? info "`tracing.langchain_endpoint` (`LANGCHAIN_ENDPOINT`) — LangChain Endpoint"
    **Category**: `general`

    Specifies the base URL where LangSmith trace payloads are sent. This is critical in enterprise setups that route telemetry through regional gateways, private networks, or controlled egress proxies. Endpoint and key must match the same deployment; otherwise you can see authentication failures, timeouts, or fragmented projects across environments. Validate endpoint reachability with health checks before enabling full tracing volume in production. Keeping endpoint configuration explicit per environment reduces surprise during incident response and migration.

    **Badges**:
    - Telemetry routing

    **Links**:
    - [AgentSight: A Monitoring and Risk Mitigation Framework for LLM-based Agents](https://arxiv.org/abs/2508.02736)
    - [LangSmith Environment Variables](https://docs.langchain.com/langsmith/env-var)
    - [Trace with LangChain](https://docs.langchain.com/langsmith/trace-with-langchain)
    - [OpenTelemetry SDK Environment Variables](https://opentelemetry.io/docs/specs/otel/configuration/sdk-environment-variables/)

??? info "`tracing.langchain_project` (`LANGCHAIN_PROJECT`) — LangChain Project"
    **Category**: `general`

    Defines the project namespace under which traces are grouped in LangSmith dashboards and analytics. For RAG systems, stable project naming is essential for comparing retrieval quality, latency, and failure patterns across environments like dev, staging, and prod. Frequent renaming fragments trend history and makes incident forensics harder because related runs are no longer co-located. Use a predictable naming convention that encodes environment and service boundary without excessive granularity. Good project hygiene turns traces into operational evidence rather than isolated run logs.

    **Badges**:
    - Namespace hygiene

    **Links**:
    - [RAGVUE: RAG Validation and Unified Evaluation](https://arxiv.org/abs/2601.04196)
    - [LangSmith Observability](https://docs.langchain.com/langsmith/observability)
    - [LangSmith Evaluation Concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
    - [LangSmith Documentation](https://docs.langchain.com/langsmith)

??? info "`tracing.langchain_tracing_v2` (`LANGCHAIN_TRACING_V2`) — LangChain Tracing"
    **Category**: `general`

    Enables the modern LangSmith tracing path that captures structured run trees for model calls, tools, retrievers, and chain steps. In RAG pipelines this visibility is essential for understanding where latency and quality degrade, especially when retrieval and generation are orchestrated through multiple components. Turning tracing on without controls can add overhead, so production setups often apply sampling and metadata policies. Before exporting traces externally, ensure prompt and document payload redaction aligns with data governance requirements. Treat this switch as operational instrumentation, not just a debugging toggle.

    **Badges**:
    - Tracing pipeline

    **Links**:
    - [AgentSight: A Monitoring and Risk Mitigation Framework for LLM-based Agents](https://arxiv.org/abs/2508.02736)
    - [Trace with LangChain](https://docs.langchain.com/langsmith/trace-with-langchain)
    - [LangSmith Observability](https://docs.langchain.com/langsmith/observability)
    - [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)

??? info "`tracing.langtrace_api_host` (`LANGTRACE_API_HOST`) — LangTrace API Host"
    **Category**: `infrastructure`

    Base endpoint for Langtrace ingestion and control APIs. This setting determines where traces from retrieval, reranking, and generation are delivered, so it effectively controls data residency, network path, and tenant routing for observability. Use an explicit host per environment and verify protocol, TLS, and region alignment before enabling high-volume tracing, especially when moving between cloud and self-hosted collectors. Host/key/project mismatches are a common cause of silent trace loss, so validate this alongside credentials during rollout.

    **Badges**:
    - Trace routing

    **Links**:
    - [AgentSight: AI Agent Observability (arXiv)](https://arxiv.org/abs/2508.02736)
    - [Langtrace Documentation](https://docs.langtrace.ai/)
    - [Langtrace OTEL Configuration](https://docs.langtrace.ai/supported-integrations/otel-support/otel-configuration)
    - [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)

??? info "`tracing.langtrace_project_id` (`LANGTRACE_PROJECT_ID`) — LangTrace Project ID"
    **Category**: `general`

    Logical project namespace used by Langtrace to partition telemetry from different applications or environments. In practice, it is the boundary that keeps retrieval experiments, reranker tuning runs, and production traffic from mixing in the same dashboard and skewing metrics. Assign stable project IDs per environment and per major product surface so trace analytics remain comparable over time and access controls stay clean. If this is mis-set, traces may appear to vanish when they are actually being written to a different project bucket.

    **Badges**:
    - Project scoping

    **Links**:
    - [AgentSight: AI Agent Observability (arXiv)](https://arxiv.org/abs/2508.02736)
    - [Langtrace Documentation](https://docs.langtrace.ai/)
    - [Langtrace Integrations Overview](https://docs.langtrace.ai/supported-integrations/overview)
    - [OpenTelemetry Traces](https://opentelemetry.io/docs/concepts/signals/traces/)

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

??? info "`tracing.prometheus_port` (`PROMETHEUS_PORT`) — Prometheus Port"
    **Category**: `infrastructure`

    Port used to expose the metrics endpoint that Prometheus scrapes (typically `/metrics`). If this value is wrong, observability breaks quietly: the application can be healthy while dashboards, alerts, and SLO calculations go blind. Configure it together with scrape jobs, network policy, and service discovery labels so monitoring remains consistent across environments. In production, validate this by checking target health in Prometheus and ensuring metric cardinality and scrape intervals match system load.

    **Links**:
    - [PromAssistant: Prompting for Time-Series Monitoring with PromQL (arXiv 2025)](https://arxiv.org/abs/2503.03114)
    - [Prometheus Configuration Reference](https://prometheus.io/docs/prometheus/latest/configuration/configuration/)
    - [Prometheus Exposition Formats](https://prometheus.io/docs/instrumenting/exposition_formats/)
    - [Prometheus Querying Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)

??? info "`tracing.trace_auto_ls` (`TRACE_AUTO_LS`) — Auto-open LangSmith"
    **Category**: `general`

    TRACE_AUTO_LS controls whether the UI should automatically open a LangSmith run view after request completion. It does not change retrieval quality directly, but it changes debugging speed by reducing the friction between an anomalous response and its trace evidence. Keep it enabled in active tuning sessions where fast trace inspection matters, and disable it in high-throughput workflows where constant context switching is distracting. If this flag is enabled while external tracing is disabled, the expected behavior should degrade gracefully to local trace views rather than broken deep-links.

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [LangSmith Observability Quickstart](https://docs.langchain.com/langsmith/observability-quickstart)
    - [LangSmith Environment Variables](https://docs.langchain.com/langsmith/env-var)
    - [LangSmith Trace with OpenTelemetry](https://docs.langchain.com/langsmith/trace-with-opentelemetry)

??? info "`tracing.trace_retention` (`TRACE_RETENTION`) — Trace Retention"
    **Category**: `general`

    TRACE_RETENTION defines how long trace records are kept before pruning. Retention is a tradeoff between forensic depth and operational cost: longer windows improve post-incident analysis and regression investigations, while shorter windows limit storage growth and reduce compliance surface area. Set this value based on your incident review cadence and model rollout cycle, then validate that pruning does not remove traces needed for reproducibility. In production, align retention with data-governance policy and downstream index lifecycle settings so trace deletion is predictable and auditable.

    **Links**:
    - [GraphTracer: Tracing Dynamic Dataflow in Agentic AI Systems (arXiv 2025)](https://arxiv.org/abs/2510.10581)
    - [Elasticsearch Index Lifecycle Management (ILM)](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
    - [OpenSearch Index State Management (ISM)](https://docs.opensearch.org/latest/im-plugin/ism/index/)
    - [LangSmith Data Purging and Compliance](https://docs.langchain.com/langsmith/data-purging-compliance)

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
    - [LangSmith Trace with OpenTelemetry](https://docs.langchain.com/langsmith/trace-with-opentelemetry)

??? info "`tracing.tracing_enabled` (`TRACING_ENABLED`) — Tracing Enabled"
    **Category**: `general`

    TRACING_ENABLED is the master switch for request-level trace capture in the retrieval and generation pipeline. When enabled, each request can emit structured events that explain routing decisions, retrieval candidates, rerank outcomes, and timing breakdowns. This setting is foundational for debugging because it turns opaque failures into inspectable execution paths. In production, keep it enabled with controlled sampling so you retain diagnostic coverage without overwhelming observability storage.

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [OpenTelemetry Trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [LangSmith Observability Concepts](https://docs.langchain.com/langsmith/observability-concepts)

??? info "`tracing.tracing_mode` (`TRACING_MODE`) — Tracing Mode"
    **Category**: `general`

    TRACING_MODE selects the trace backend behavior (for example local-only, external export, or disabled pathways in mixed environments). This mode determines where spans are emitted, which metadata is attached, and how operators inspect runs during incident triage. Choose a mode that matches deployment stage: local views for rapid iteration, full OpenTelemetry export for shared production observability, and controlled fallback modes for constrained environments. Ensure mode changes are tested with synthetic requests so trace continuity does not break across upgrades.

    **Links**:
    - [AgentTrace: Comprehensive Tracing for AI Agents (arXiv 2026)](https://arxiv.org/abs/2602.10133)
    - [LangSmith Trace with OpenTelemetry](https://docs.langchain.com/langsmith/trace-with-opentelemetry)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [LangSmith Observability Concepts](https://docs.langchain.com/langsmith/observability-concepts)

??? info "`tracing.tribrid_log_path` (`TRIBRID_LOG_PATH`) — Reranker Log Path"
    **Category**: `general`

    TRIBRID_LOG_PATH specifies where local runtime logs and trace artifacts are written on disk. A stable, writable path is required for reproducibility workflows such as replaying failure cases, auditing retrieval decisions, and comparing behavior across model/version changes. In multi-process deployments, this path should be paired with rotation and retention policy to prevent unbounded growth and partial-write corruption. Treat log-path configuration as part of operational hardening: explicit permissions, predictable lifecycle, and compatibility with your observability export strategy.

    **Links**:
    - [GraphTracer: Tracing Dynamic Dataflow in Agentic AI Systems (arXiv 2025)](https://arxiv.org/abs/2510.10581)
    - [OpenTelemetry Trace SDK](https://opentelemetry.io/docs/specs/otel/trace/sdk/)
    - [Elasticsearch Index Lifecycle Management (ILM)](https://www.elastic.co/guide/en/elasticsearch/reference/current/index-lifecycle-management.html)
    - [LangSmith Data Purging and Compliance](https://docs.langchain.com/langsmith/data-purging-compliance)
