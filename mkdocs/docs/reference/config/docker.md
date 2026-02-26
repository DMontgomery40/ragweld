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

**Total parameters**: 11

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `docker.dev_backend_port` | `DEV_BACKEND_PORT` | `int` | `8012` | ≥ 1024, ≤ 65535 | Port for dev backend (Uvicorn) |
| `docker.dev_frontend_port` | `DEV_FRONTEND_PORT` | `int` | `5173` | ≥ 1024, ≤ 65535 | Port for dev frontend (Vite) |
| `docker.dev_stack_restart_timeout` | `DEV_STACK_RESTART_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Timeout for dev stack restart operations (seconds) |
| `docker.docker_container_action_timeout` | `DOCKER_CONTAINER_ACTION_TIMEOUT` | `int` | `30` | ≥ 5, ≤ 120 | Timeout for Docker container actions (start/stop/restart) |
| `docker.docker_container_list_timeout` | `DOCKER_CONTAINER_LIST_TIMEOUT` | `int` | `10` | ≥ 1, ≤ 60 | Timeout for Docker container list (seconds) |
| `docker.docker_host` | `DOCKER_HOST` | `str` | `""` | — | Docker socket URL (e.g., unix:///var/run/docker.sock). Leave empty for auto-detection. |
| `docker.docker_infra_down_timeout` | `DOCKER_INFRA_DOWN_TIMEOUT` | `int` | `30` | ≥ 10, ≤ 120 | Timeout for Docker infrastructure down command (seconds) |
| `docker.docker_infra_up_timeout` | `DOCKER_INFRA_UP_TIMEOUT` | `int` | `60` | ≥ 30, ≤ 300 | Timeout for Docker infrastructure up command (seconds) |
| `docker.docker_logs_tail` | `DOCKER_LOGS_TAIL` | `int` | `100` | ≥ 10, ≤ 1000 | Default number of log lines to tail from containers |
| `docker.docker_logs_timestamps` | `DOCKER_LOGS_TIMESTAMPS` | `int` | `1` | ≥ 0, ≤ 1 | Include timestamps in Docker logs (1=yes, 0=no) |
| `docker.docker_status_timeout` | `DOCKER_STATUS_TIMEOUT` | `int` | `5` | ≥ 1, ≤ 30 | Timeout for Docker status check (seconds) |

### Details (glossary)

??? info "`docker.docker_container_action_timeout` (`DOCKER_CONTAINER_ACTION_TIMEOUT`) — Container Action Timeout"
    **Category**: `infrastructure`

    Maximum seconds to wait for container start/stop/restart operations. Containers with complex startup sequences or cleanup hooks may need higher values. If container actions timeout, increase this. Range: 5-120 seconds.

    **Badges**:
    - Container operations

    **Links**:
    - [Container Lifecycle](https://docs.docker.com/config/containers/start-containers-automatically/)
    - [Stop Containers](https://docs.docker.com/engine/reference/commandline/stop/)

??? info "`docker.docker_container_list_timeout` (`DOCKER_CONTAINER_LIST_TIMEOUT`) — Container List Timeout"
    **Category**: `infrastructure`

    Maximum seconds to wait when listing all Docker containers. Increase if you have many containers (100+) or slow Docker API response. Range: 1-60 seconds.

    **Badges**:
    - Performance

    **Links**:
    - [Docker ps command](https://docs.docker.com/engine/reference/commandline/ps/)
    - [Container Management](https://docs.docker.com/config/containers/)

??? info "`docker.docker_infra_down_timeout` (`DOCKER_INFRA_DOWN_TIMEOUT`) — Infrastructure Down Timeout"
    **Category**: `infrastructure`

    Maximum seconds to wait when stopping TriBridRAG infrastructure services. Containers with data persistence may need time to flush to disk. If infra down fails, increase this value. Range: 10-120 seconds.

    **Badges**:
    - Infrastructure shutdown

    **Links**:
    - [Docker Compose Down](https://docs.docker.com/compose/reference/down/)
    - [Graceful Shutdown](https://docs.docker.com/engine/reference/commandline/stop/#extended-description)

??? info "`docker.docker_infra_up_timeout` (`DOCKER_INFRA_UP_TIMEOUT`) — Infrastructure Up Timeout"
    **Category**: `infrastructure`

    Maximum seconds to wait when starting TriBridRAG infrastructure services (Postgres, Neo4j, Grafana, Loki, etc.) via docker-compose. First-time startup may pull images and take longer. If infra up fails with timeout, increase this value. Range: 30-300 seconds.

    **Badges**:
    - Infrastructure startup
    - May pull images

    **Links**:
    - [Docker Compose](https://docs.docker.com/compose/)

??? info "`docker.docker_logs_tail` (`DOCKER_LOGS_TAIL`) — Log Lines to Tail"
    **Category**: `infrastructure`

    Number of log lines to display when viewing container logs. Higher values show more history but may slow down log retrieval. Use 50-100 for quick checks, 500-1000 for debugging. Range: 10-1000 lines.

    **Badges**:
    - Log visibility

    **Links**:
    - [Docker Logs](https://docs.docker.com/engine/reference/commandline/logs/)
    - [Log Management](https://docs.docker.com/config/containers/logging/)

??? info "`docker.docker_logs_timestamps` (`DOCKER_LOGS_TIMESTAMPS`) — Include Log Timestamps"
    **Category**: `infrastructure`

    Whether to include timestamps in Docker log output. Timestamps help correlate events across containers but add visual noise. Set to 1 to show timestamps, 0 to hide them.

    **Badges**:
    - Log format

    **Links**:
    - [Docker Logs Timestamps](https://docs.docker.com/engine/reference/commandline/logs/#options)
    - [Log Analysis](https://grafana.com/docs/loki/latest/)

??? info "`docker.docker_status_timeout` (`DOCKER_STATUS_TIMEOUT`) — Docker Status Timeout"
    **Category**: `infrastructure`

    Maximum seconds to wait when checking Docker daemon status. Increase if your Docker host is slow to respond or under heavy load. If health checks timeout frequently, raise this value. Range: 1-30 seconds.

    **Badges**:
    - Performance

    **Links**:
    - [Docker Health Checks](https://docs.docker.com/engine/reference/commandline/inspect/)
    - [Docker Daemon](https://docs.docker.com/config/daemon/)
