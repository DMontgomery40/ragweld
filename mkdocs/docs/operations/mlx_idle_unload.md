# MLX reranker idle-unload (Apple Silicon)

<div class="grid chunk_summaries" markdown>

-   :material-chip:{ .lg .middle } **Apple Silicon (MLX)**

    ---

    On-device LoRA reranking with MLX keeps data local and latency tight.

-   :material-timer-sand:{ .lg .middle } **Idle-unload scheduler**

    ---

    Cancels the previous timer and replaces it, so only one unload is pending at a time.

-   :material-tune:{ .lg .middle } **Operator knobs**

    ---

    If `unload_after_sec > 0`, ragweld unloads the model/adapter after that many idle seconds. Set to `0` to disable.

</div>

[Operations home](../operations.md){ .md-button .md-button--primary }
[MLX chat model lifecycle](mlx.md){ .md-button }
[Reranking config](../reference/config/reranking.md){ .md-button }
[API](../api.md){ .md-button }

!!! note "What this page covers"
    This page documents the idle-unload behavior of the MLX-based Qwen3 LoRA reranker, how it affects memory and latency on Apple Silicon, and how to tune it safely. It complements, not replaces, the broader lifecycle notes in MLX chat model lifecycle.

## Why idle-unload exists

Running the reranker on Apple Silicon is fast and private, but the loaded weights and adapters consume unified memory. On laptops, that can push swap/thermals when the system is otherwise idle. Idle-unload releases those weights after a configurable quiet period, trading a future cold-start for lower background memory use.

## What changed in 2026‑03 (single pending timer)

!!! tip "Behavioral improvement"
    Repeated calls to “schedule an idle unload” now cancel any already-scheduled timer and replace it with exactly one new task. This prevents timer pile-ups if the reranker is touched multiple times in quick succession (for example, bursty traffic or UI toggles).

- Only one pending unload task exists at a time.
- If new work arrives before the timer fires, the unload is skipped via a generation guard.
- The internal state is tracked in `server/retrieval/mlx_qwen3.py` with a dedicated task handle.

??? info "Deep dive — concurrency guard and generation check"
    The scheduler:

    - Cancels the previous pending task (if any and not already done).
    - Spawns a single sleeper task for `unload_after_sec`.
    - When it wakes, it grabs a lock and uses a generation counter to decide if it’s still safe to unload.

    ```python
    # Path: server/retrieval/mlx_qwen3.py
    # Sketch of the improved scheduling logic with a single pending task
    prev = self._idle_unload_task                 # (1)!
    if prev is not None and not prev.done():
        prev.cancel()                             # (2)!

    async def _task() -> None:
        await asyncio.sleep(sec)                  # (3)!
        async with self._lock:                    # (4)!
            if unload_generation < self._unload_generation:
                return                            # (5)!
            # Proceed to unload model/adapter/weights...
            self._model = None
            self._adapter = None
            ...

    self._idle_unload_task = asyncio.create_task(_task())  # (6)!
    ```

    1. Keep the current task handle.
    2. Cancel any still-pending timer.
    3. Sleep for the configured idle window.
    4. Serialize teardown with a lock.
    5. Abort unload if newer work has incremented the generation counter.
    6. Track the new pending timer.

## How it works (at a glance)

```mermaid
flowchart LR
  A["Reranker used"] --> B["Schedule unload in sec"]
  B --> C["Cancel previous task"]
  C --> D["Create new task"]
  D --> E["Sleep 'sec'"]
  E --> F["Lock + generation check"]
  F -->|\"stale\"| G["Abort unload"]
  F -->|\"still idle\"| H["Unload model + adapter"]
```

## Tuning guidance

Definition list

- unload_after_sec
  : How long the reranker must be idle before ragweld unloads the model and adapter.
  : Why it matters: Lower values free memory sooner but introduce more cold starts.
  : Safe default: If you're not sure, start around 120–300 seconds for interactive use.
  : Disable: Set to 0 to keep the reranker warm at all times (higher memory, lowest latency).

Tradeoffs and failure modes

- Cold-start latency
  - Unloading adds a one-time reload penalty next time the reranker is used.
  - If you see user-facing stalls, raise `unload_after_sec`.
- Memory pressure
  - If your machine swaps or gets hot when idle, lower `unload_after_sec`.
- Bursty workloads
  - The single-timer behavior prevents extra timers from stacking up on bursty traces.

!!! warning "Setting it too low"
    Extremely small values (for example, under 10 seconds) often create a cycle of unload/reload between user keystrokes. This can feel slow without actually saving much memory. Prefer a minute or more unless you have a batchy workload.

## Verifying the behavior

- Unit test coverage
  - The repository includes a test that asserts only one pending timer exists even if the scheduler is called multiple times back-to-back:
  - File: `tests/unit/test_mlx_qwen3_lifecycle.py`
  - GitHub: https://github.com/DMontgomery40/ragweld/blob/main/tests/unit/test_mlx_qwen3_lifecycle.py

- Local sanity check (developer workflow)
  - Exercise the reranker (search pipeline or eval run), then let the system go idle.
  - Watch memory usage in Activity Monitor; after your configured `unload_after_sec`, the MLX process footprint should drop when the unload fires.
  - Trigger a new retrieval; expect a brief cold-start as the adapter reloads.

## API first, MCP second

The idle-unload mechanism is internal to the reranker lifecycle and is transparent to both:

- API clients calling retrieval/reranking routes under `/api/*` (no contract changes).
- MCP tools layered on top — they inherit the behavior automatically via the same backend.

## Troubleshooting

- “Memory doesn’t drop after idle”
  - Check that `unload_after_sec` is non-zero and that the system actually became idle for longer than that period.
  - Confirm there isn’t a background job keeping the reranker busy (for example, a benchmark loop).
  - If you are using external tracing or verbose logging, ensure those do not re-touch the model periodically.

- “Cold starts are too frequent”
  - Raise `unload_after_sec` or set it to `0` to disable.
  - Consider using a semantic cache to reduce reranker load in interactive sessions.

- “I see many asyncio tasks in flight”
  - With this change, there should be at most one idle-unload task pending. If you observe otherwise, verify your environment isn’t replacing the event loop between calls, and ensure tests like the one linked above pass locally.

## Related docs

- MLX chat model lifecycle (broader MLX bring-up and lifecycle): MLX chat model lifecycle
- Reranking configuration reference (knobs and defaults): Reranking config
