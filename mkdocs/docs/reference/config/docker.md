# Config reference: `docker`

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

**Total parameters**: 7

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `docker.dev_backend_port` | `DEV_BACKEND_PORT` | `int` | `58012` | ≥ 1024, ≤ 65535 | Port for dev backend (Uvicorn) |
| `docker.dev_frontend_port` | `DEV_FRONTEND_PORT` | `int` | `55173` | ≥ 1024, ≤ 65535 | Port for dev frontend (Vite) |
| `docker.docker_container_action_timeout` | `DOCKER_CONTAINER_ACTION_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Timeout for Docker container actions (start/stop/restart) |
| `docker.docker_container_list_timeout` | `DOCKER_CONTAINER_LIST_TIMEOUT` | `int` | `10` | ≥ 1, ≤ 60 | Timeout for Docker container list (seconds) |
| `docker.docker_logs_tail` | `DOCKER_LOGS_TAIL` | `int` | `100` | ≥ 10, ≤ 1000 | Default number of log lines to tail from containers |
| `docker.docker_logs_timestamps` | `DOCKER_LOGS_TIMESTAMPS` | `bool` | `true` | — | Include timestamps in Docker logs |
| `docker.docker_status_timeout` | `DOCKER_STATUS_TIMEOUT` | `int` | `5` | ≥ 1, ≤ 30 | Timeout for Docker status check (seconds) |

### Details (glossary)

??? info "`docker.docker_container_action_timeout` (`DOCKER_CONTAINER_ACTION_TIMEOUT`) — Container Action Timeout"
    **Category**: `infrastructure`

    Maximum wait time for start, stop, or restart operations before the control layer marks the action as timed out. This setting protects UI/API responsiveness when containers hang during bootstrap, health checks, or shutdown hooks. If set too low, normal slow starts appear as failures; if set too high, real faults surface too late and block automation. Choose a value slightly above observed p95 action latency for your heaviest service profile and revisit after infrastructure changes.

    **Badges**:
    - Timeout control

    **Links**:
    - [Docker startup performance study (arXiv 2026)](https://arxiv.org/abs/2602.15214)
    - [docker container start](https://docs.docker.com/reference/cli/docker/container/start/)
    - [docker container stop](https://docs.docker.com/reference/cli/docker/container/stop/)
    - [docker container wait](https://docs.docker.com/reference/cli/docker/container/wait/)

??? info "`docker.docker_container_list_timeout` (`DOCKER_CONTAINER_LIST_TIMEOUT`) — Container List Timeout"
    **Category**: `infrastructure`

    Upper bound for how long the system waits when requesting container listings from the Docker API. This mainly protects control-plane responsiveness in environments with many containers, remote contexts, or overloaded Docker daemons. Higher values reduce false timeout errors during heavy load, while lower values fail fast and keep UIs responsive when the daemon is unhealthy. Tune it from observed list latency, not guesswork, and monitor for growth as your service count increases.

    **Badges**:
    - API latency

    **Links**:
    - [CrossTrace distributed tracing for microservices (arXiv 2025)](https://arxiv.org/abs/2508.11342)
    - [docker container ls](https://docs.docker.com/reference/cli/docker/container/ls/)
    - [docker ps](https://docs.docker.com/reference/cli/docker/ps/)
    - [Docker contexts](https://docs.docker.com/engine/context/working-with-contexts/)

??? info "`docker.docker_logs_tail` (`DOCKER_LOGS_TAIL`) — Log Lines to Tail"
    **Category**: `infrastructure`

    Sets how many trailing log lines are fetched per container when debugging retrieval workflows. Smaller tails keep UI and CLI feedback fast for routine checks, while larger tails help reconstruct multi-step failures across chunking, embedding, indexing, and query handling. Extremely large tails increase I/O and can bury the newest signal in historical noise. Use a conservative default and temporarily raise the value during incident analysis.

    **Badges**:
    - Log visibility

    **Links**:
    - [docker container logs](https://docs.docker.com/reference/cli/docker/container/logs/)
    - [Docker logging drivers](https://docs.docker.com/engine/logging/configure/)
    - [Grafana Loki docs](https://grafana.com/docs/loki/latest/)
    - [Sharpening Kubernetes Audit Logs with Context Awareness (2025)](https://arxiv.org/abs/2506.16328)

??? info "`docker.docker_logs_timestamps` (`DOCKER_LOGS_TIMESTAMPS`) — Include Log Timestamps"
    **Category**: `infrastructure`

    Adds timestamps to container output so events can be correlated across services in a single RAG request path. This is critical when tracing latency between ingestion, embedding calls, vector writes, and generation. Without timestamps, parallel service events are easy to misorder and root-cause analysis takes longer. Keep timestamps enabled for shared and production-like environments, and normalize timezone handling in downstream log tools.

    **Badges**:
    - Correlation ready

    **Links**:
    - [docker container logs](https://docs.docker.com/reference/cli/docker/container/logs/)
    - [Docker logging drivers](https://docs.docker.com/engine/logging/configure/)
    - [Grafana Loki docs](https://grafana.com/docs/loki/latest/)
    - [Sharpening Kubernetes Audit Logs with Context Awareness (2025)](https://arxiv.org/abs/2506.16328)

??? info "`docker.docker_status_timeout` (`DOCKER_STATUS_TIMEOUT`) — Docker Status Timeout"
    **Category**: `infrastructure`

    Sets the maximum time allowed for each Docker status probe. Low values surface daemon failures quickly but can create false negatives under CPU, disk, or socket contention; high values reduce noise but delay detection of real outages. In retrieval pipelines this directly affects whether preflight checks pass before ingestion and evaluation tasks begin. Choose a value slightly above observed probe latency at peak local load.

    **Badges**:
    - Probe tuning

    **Links**:
    - [docker system info](https://docs.docker.com/reference/cli/docker/system/info/)
    - [Compose healthcheck](https://docs.docker.com/reference/compose-file/services/#healthcheck)
    - [Docker Compose up](https://docs.docker.com/reference/cli/docker/compose/up/)
    - [Decomposing Docker Container Startup Performance (2026)](https://arxiv.org/abs/2602.15214)
