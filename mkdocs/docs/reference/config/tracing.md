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

??? info "`tracing.alert_webhook_timeout` (`ALERT_WEBHOOK_TIMEOUT`) — Alert Webhook Timeout"
    **Category**: `general`

    Maximum seconds to wait for alert webhook response (Slack, Discord, etc.). Prevents slow webhooks from blocking the main process. Typical: 5-10 seconds.

    **Links**:
    - [Webhook Timeouts](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Timeout)
    - [Slack Webhooks](https://api.slack.com/messaging/webhooks)

??? info "`tracing.langchain_endpoint` (`LANGCHAIN_ENDPOINT`) — LangChain Endpoint"
    **Category**: `general`

    LangSmith API endpoint URL (external provider). Stored in config field tracing.langchain_endpoint. Reserved for future integration.

    **Links**:
    - [LangSmith API](https://docs.smith.langchain.com/)

??? info "`tracing.langchain_project` (`LANGCHAIN_PROJECT`) — LangChain Project"
    **Category**: `general`

    Project name for organizing traces in LangSmith (external provider). Stored in config field tracing.langchain_project. Reserved for future integration.

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

    Enable Prometheus metrics collection and /metrics endpoint. When on, exposes query latency, cache hits, error rates, etc. Essential for production monitoring. Minimal overhead.

    **Links**:
    - [Prometheus Metrics](https://prometheus.io/docs/concepts/metric_types/)
    - [Monitoring Best Practices](https://prometheus.io/docs/practices/naming/)

??? info "`tracing.prometheus_port` (`PROMETHEUS_PORT`) — Prometheus Port"
    **Category**: `infrastructure`

    TCP port for the /metrics endpoint scraped by Prometheus or Grafana. Default: 9090. Range: 1024-65535. Change it if 9090 conflicts with another service.

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

    Number of traces to retain in the in-memory ring buffer (10-500). Higher values preserve more history for debugging; lower values use less memory.

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

    Tracing backend mode. Options: langsmith, local, off (alias "none" normalizes to off). Default: langsmith. Use local or off when external trace export is not desired.

    **Links**:
    - [LangSmith](https://docs.smith.langchain.com/)

??? info "`tracing.tribrid_log_path` (`TRIBRID_LOG_PATH`) — Reranker Log Path"
    **Category**: `general`

    Path to the query and reranker log file used for diagnostics and training telemetry. Default: data/logs/queries.jsonl. Ensure the server process can write to this location.

    **Links**:
    - [Python logging](https://docs.python.org/3/library/logging.html)
