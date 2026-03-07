# MLX chat model lifecycle (Apple Silicon)

<div class="grid chunk_summaries" markdown>

-   :material-cpu-64-bit:{ .lg .middle } **On-device MLX runtime**

    ---

    The MLX chat backend runs locally on Apple Silicon. Weights and LoRA adapters are loaded on demand and kept hot while in use.

-   :material-battery-clock:{ .lg .middle } **Idle unload window**

    ---

    After a period of inactivity, ragweld can release MLX weights to free memory. A new request reloads them automatically.

-   :material-timer-cancel:{ .lg .middle } **Single pending timer**

    ---

    Re-scheduling the idle unload cancels the prior timer so only one unload task is ever pending. This avoids “timer pileups” and premature unloads.

-   :material-shield-key:{ .lg .middle } **Operator-safe defaults**

    ---

    If you’re not sure, keep the default idle window. Tune it only if you see memory pressure or frequent reloads in logs.

</div>

[Operations overview](../operations.md){ .md-button }
[Configuration](../configuration.md){ .md-button }
[API](../api.md){ .md-button }
[Observability](../observability.md){ .md-button }

!!! note "Pydantic is the law"
    Lifecycle behavior is driven by configuration and model adapters defined in `server/models/tribrid_config_model.py` and the MLX adapter in `server/chat/ragweld_mlx.py`. If a knob isn’t in Pydantic, it isn’t officially supported.

## Why MLX lifecycle management exists

On Apple Silicon, the MLX backend provides a fast, on-device chat model experience. However, large weights consume substantial unified memory. ragweld manages the model’s lifecycle to balance:

- responsiveness (keep weights hot during active use)
- stability (release memory when idle)
- correctness (never unload while generations are running)

## What “idle unload” does

Definition list

:   Idle unload window  
    The number of seconds of inactivity after which ragweld unloads MLX weights. New activity resets the countdown.

:   In-use guard  
    The model will not unload while generations are running. Active use cancels or defers unloading.

:   Single pending timer  
    Only one unload task is allowed to be scheduled at a time. If a new unload schedule is requested, the previously scheduled one is cancelled.

:   Generation safety  
    The unload routine verifies that the conditions that triggered the timer still hold (still idle) before it frees memory.

!!! tip "If you’re not sure, do this"
    - Leave the idle unload window at its default.
    - Revisit only if you observe frequent model reloads during normal usage or memory pressure during idle periods.

## Operator expectations (signals and failure modes)

- Logs: You should see clear log messages when MLX weights are loaded and when they are unloaded due to idleness.
- Memory telemetry: Expect memory to remain elevated while the model is in use, then drop after the idle window elapses. On Apple Silicon, “returning” memory can lag in system monitors due to allocator behavior.
- Cold-starts: After an unload, the next request will re-load weights. This may add a short cold-start delay.

!!! warning "Don’t fight the scheduler with external timers"
    Avoid implementing your own unload timers in sidecars or wrappers. The built-in scheduler already guarantees a single pending timer and guards against unloading during active use.

## Tuning guidance

Use these rules of thumb when adjusting the idle window:

- Interactive chats (human-in-the-loop)
  - Favor a slightly longer idle window to avoid reloading between short pauses.
  - Tradeoff: higher memory residency while a user is present.

- Batch or scheduled usage
  - A shorter idle window can free memory sooner between jobs.
  - Tradeoff: jobs that arrive sporadically may pay more frequent cold-starts.

!!! note "Disabling idle unload (advanced)"
    The MLX adapter’s internal scheduler treats non-positive values as “no idle unload”. This is useful for high-throughput runs where reloading would be a consistent tax. Only disable if you have the memory headroom.

## What just changed (and why it matters)

ragweld now explicitly tracks the pending idle-unload task for the MLX chat model and cancels any previous one when a new schedule is requested. Practically:

- multiple schedule calls result in only one active timer
- the most recent schedule defines the next unload time
- fewer stray asyncio tasks and less chance of unloading earlier than intended

This is validated by a unit test that asserts only a single pending timer exists after multiple re-schedules. The behavior lives in `server/chat/ragweld_mlx.py` and is covered by `tests/unit/test_ragweld_mlx_lifecycle.py`.

!!! success "Operational impact"
    - More predictable memory release timing under bursty usage
    - Fewer background tasks to manage in long-running processes
    - Lower risk of premature unloads during active sessions

## Troubleshooting checklist

- [ ] Weights never seem to unload
  - Ensure the model isn’t constantly in use (look for active generations).
  - Confirm the idle window isn’t disabled (advanced configurations may set it to non-positive).

- [ ] Model reloads too often
  - Increase the idle window.
  - Confirm that request bursts aren’t spaced just beyond the current window.

- [ ] Memory doesn’t drop immediately after unload
  - Apple Silicon’s unified memory and allocator behavior may delay visible release in some tools. Correlate with logs.

??? info "Deep dive: what happens under the hood"
    - During generation, the adapter tracks an “in use” count and last-used timestamp.
    - When generation completes, the adapter schedules an unload after the configured idle window.
    - If another request arrives, the adapter cancels the pending unload task and reschedules it after the new activity completes.
    - When the timer fires, the adapter re-checks whether it’s still safe to unload before actually freeing the weights.

## Related reading

- Operations overview: practical monitoring and health surfaces  
  See [Operations & metrics](../operations.md).

- Observability: tracing, metrics, and dashboards  
  See [Observability](../observability.md).

- API-first integration: where to call from your app  
  See [API](../api.md).

!!! tip "File paths for engineers"
