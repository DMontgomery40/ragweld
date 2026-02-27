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

    Controls whether resolved events are included in outbound alert notifications. Set to on (1) to receive recovery/resolution notices alongside active alerts, or off (0) to only notify on active issues.

??? info "`tracing.alert_notify_severities` (`ALERT_NOTIFY_SEVERITIES`) — Alert Notify Severities"
    **Category**: `general`

    Comma-separated severity levels that are allowed to trigger outbound alert notifications (for example: critical,warning). This acts as the final routing filter after alert generation, so misconfigured values can silently suppress notifications you expected to see.

    Use this to align operational noise with team on-call policy: start narrow (critical only), then expand once signal quality is stable. Keep values synchronized with the severity vocabulary emitted by your tracing/alert pipeline.

    - Typical progression: critical -> critical,warning -> critical,warning,info
    - Affects: webhook fan-out volume, pager noise, incident MTTA

??? info "`tracing.alert_webhook_timeout` (`ALERT_WEBHOOK_TIMEOUT`) — Alert Webhook Timeout"
    **Category**: `general`

    Maximum time in seconds to wait for alert webhook delivery before the request is treated as failed. This timeout protects retrieval/tracing workflows from hanging on slow third-party incident tooling.

    Set this high enough for normal network jitter, but low enough to avoid backlog growth during outages. If notifications are frequently timing out, fix endpoint reliability before increasing this value aggressively.

    - Lower timeout: faster failure detection, more dropped notifications under transient latency
    - Higher timeout: better delivery chance, slower failure feedback

    **Links**:
    - [Webhook Timeouts](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Timeout)
    - [Slack Webhooks](https://api.slack.com/messaging/webhooks)

??? info "`tracing.langchain_endpoint` (`LANGCHAIN_ENDPOINT`) — LangChain Endpoint"
    **Category**: `general`

    Base endpoint used for LangSmith/LangChain trace ingestion. This controls where trace payloads are sent when tracing integration is enabled.

    Override this for self-hosted gateways, enterprise proxies, or region-specific endpoints. Keep endpoint, project name, and API key aligned or traces will fail silently or fragment across projects.

    - Default commonly points to api.smith.langchain.com
    - Verify network egress and TLS policy in production

    **Links**:
    - [LangSmith API](https://docs.smith.langchain.com/)

??? info "`tracing.langchain_project` (`LANGCHAIN_PROJECT`) — LangChain Project"
    **Category**: `general`

    Logical project/container name used when publishing traces to LangSmith. It determines where runs appear in dashboards and how teams segment environments (dev/staging/prod) or product areas.

    Use a stable naming convention so trend analysis remains coherent over time. Avoid ad-hoc names that split observability history across many near-duplicate projects.

    - Example convention: ragweld-dev, ragweld-staging, ragweld-prod
    - Affects: trace discoverability, dashboard hygiene

    **Links**:
    - [LangSmith Projects](https://docs.smith.langchain.com/tracing/faq#how-do-i-use-projects)

??? info "`tracing.langchain_tracing_v2` (`LANGCHAIN_TRACING_V2`) — LangChain Tracing"
    **Category**: `general`

    Reserved for future LangSmith integration (v2 tracing protocol). TriBridRAG currently captures local, in-memory request traces for UI preview and does not export traces to LangSmith yet.

    **Badges**:
    - Requires API key

    **Links**:
    - [LangSmith Setup](https://docs.smith.langchain.com/)
    - [Tracing Guide](https://docs.smith.langchain.com/tracing)
    - [How to Enable](https://docs.smith.langchain.com/tracing/faq#how-do-i-turn-on-tracing)

??? info "`tracing.langtrace_api_host` (`LANGTRACE_API_HOST`) — LangTrace API Host"
    **Category**: `infrastructure`

    LangTrace API endpoint host (optional). Stored in config field tracing.langtrace_api_host (and surfaced as LANGTRACE_API_HOST in env exports). Reserved for future external trace export.

    **Links**:
    - [Langtrace Docs](https://docs.langtrace.ai/)

??? info "`tracing.langtrace_project_id` (`LANGTRACE_PROJECT_ID`) — LangTrace Project ID"
    **Category**: `general`

    Project identifier for LangTrace (optional). Stored in config field tracing.langtrace_project_id (and surfaced as LANGTRACE_PROJECT_ID in env exports). Reserved for future external trace export.

    **Links**:
    - [Langtrace Projects](https://docs.langtrace.ai/)

??? info "`tracing.log_level` (`LOG_LEVEL`) — Log Level"
    **Category**: `general`

    Logging verbosity level. Options: DEBUG (verbose, dev), INFO (normal, recommended), WARNING (errors + warnings only), ERROR (errors only). Higher levels reduce noise but may hide useful diagnostics.

    **Links**:
    - [Python Logging Levels](https://docs.python.org/3/library/logging.html#logging-levels)
    - [Logging Best Practices](https://docs.python.org/3/howto/logging.html)

??? info "`tracing.metrics_enabled` (`METRICS_ENABLED`) — Metrics Enabled"
    **Category**: `evaluation`

    Master toggle for exporting internal metrics (for example Prometheus-compatible counters/gauges/histograms). When disabled, trace logs may still exist but metric endpoints/series emission are reduced or silent.

    Enable in environments where dashboards/alerts depend on metric streams. Disable only for constrained local runs where telemetry overhead must be minimized.

    - Affects: observability dashboards, alert pipelines, SLO reporting
    - Pair with: PROMETHEUS_PORT, TRACE_SAMPLING_RATE

    **Links**:
    - [Prometheus Metrics](https://prometheus.io/docs/concepts/metric_types/)
    - [Monitoring Best Practices](https://prometheus.io/docs/practices/naming/)

??? info "`tracing.prometheus_port` (`PROMETHEUS_PORT`) — Prometheus Port"
    **Category**: `infrastructure`

    Network port used to expose Prometheus-compatible metrics endpoint. Monitoring systems scrape this port to collect retrieval/tracing health and performance metrics.

    Ensure this port is reachable from your monitoring plane and does not conflict with other services on the host. In containerized setups, verify both container and host mapping are correct.

    - Typical default: 9090
    - Affects: metrics ingestion and dashboard freshness

    **Links**:
    - [Prometheus Basics](https://prometheus.io/docs/introduction/overview/)
    - [Metrics Endpoint](https://prometheus.io/docs/instrumenting/exposition_formats/)

??? info "`tracing.trace_auto_ls` (`TRACE_AUTO_LS`) — Auto-open LangSmith"
    **Category**: `general`

    UI convenience flag intended to auto-open LangSmith after a request (1=yes, 0=no). TriBridRAG does not currently implement LangSmith deep-linking; this setting is reserved for future integration.

    **Links**:
    - [LangSmith Setup](https://docs.smith.langchain.com/)

??? info "`tracing.trace_retention` (`TRACE_RETENTION`) — Trace Retention"
    **Category**: `general`

    Retention cap for stored trace records/events in local history. Older traces beyond this limit are pruned to keep storage and UI performance manageable.

    Set based on debugging horizon and storage budget. Higher retention helps long-tail incident analysis but increases disk usage and list/query overhead.

    - Lower retention: lean local storage
    - Higher retention: richer historical diagnostics

    **Links**:
    - [Data Retention](https://en.wikipedia.org/wiki/Data_retention)

??? info "`tracing.trace_sampling_rate` (`TRACE_SAMPLING_RATE`) — Trace Sampling Rate"
    **Category**: `general`

    Percentage of requests to trace with LangSmith/observability (0.0-1.0). 1.0 = trace everything (100%), 0.1 = trace 10% of requests, 0.0 = no tracing. Lower sampling reduces LangSmith costs and overhead while still providing visibility into system behavior. Use 1.0 during development/debugging, 0.05-0.2 in production for cost-effective monitoring. Sampling is random - every request has this probability of being traced.

    Recommended: 1.0 for development, 0.1-0.2 for production monitoring, 0.05 for high-traffic systems.

    **Badges**:
    - Cost control
    - Observability

    **Links**:
    - [LangSmith Tracing](https://docs.smith.langchain.com/tracing)
    - [Sampling Strategies](https://docs.smith.langchain.com/tracing/faq#how-do-i-sample-traces)
    - [Trace Costs](https://www.langchain.com/pricing)

??? info "`tracing.tracing_enabled` (`TRACING_ENABLED`) — Tracing Enabled"
    **Category**: `general`

    Enable TriBridRAG request tracing. This records an in-memory per-request event trace (used by the UI “Routing Trace” preview) for debugging routing/retrieval decisions and latency. This does not export traces to external providers.

    **Links**:
    - [Distributed Tracing (concepts)](https://opentelemetry.io/docs/concepts/observability-primer/#distributed-traces)

??? info "`tracing.tracing_mode` (`TRACING_MODE`) — Tracing Mode"
    **Category**: `general`

    Selects the tracing backend mode used by the retrieval pipeline (for example off, local, or langsmith export). Mode determines where trace data is emitted and how debugging/observability workflows operate.

    Use local mode for quick iteration and deterministic local introspection; use external modes for team-level dashboards and long-term telemetry. Keep credentials/endpoints aligned with selected mode.

    - off: minimal overhead, no trace diagnostics
    - local: local debugging visibility
    - langsmith: remote observability and sharing

    **Links**:
    - [LangSmith](https://docs.smith.langchain.com/)

??? info "`tracing.tribrid_log_path` (`TRIBRID_LOG_PATH`) — Reranker Log Path"
    **Category**: `general`

    Filesystem path for local query/trace log persistence. This file is used for audit trails, debugging replay, and compatibility tooling that reads historical run data.

    Choose a stable writable location with predictable rotation/backup behavior. In production, pair with retention management to avoid unbounded log growth.

    - Affects: local trace replay and diagnostics
    - Verify path permissions in containerized environments

    **Links**:
    - [Python logging](https://docs.python.org/3/library/logging.html)
