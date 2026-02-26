# Config reference: `ui`

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

**Total parameters**: 45

??? info "Group index"
    - `(root)`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `ui.chat_default_model` | `CHAT_DEFAULT_MODEL` | `str` | `"gpt-4o-mini"` | — | Default model for chat if not specified in request |
| `ui.chat_history_max` | `CHAT_HISTORY_MAX` | `int` | `50` | ≥ 10, ≤ 500 | Max chat history messages |
| `ui.chat_show_citations` | `CHAT_SHOW_CITATIONS` | `int` | `1` | ≥ 0, ≤ 1 | Show citations list on chat answers |
| `ui.chat_show_confidence` | `CHAT_SHOW_CONFIDENCE` | `int` | `0` | ≥ 0, ≤ 1 | Show confidence badge on chat answers |
| `ui.chat_show_debug_footer` | `CHAT_SHOW_DEBUG_FOOTER` | `int` | `1` | ≥ 0, ≤ 1 | Show dev/debug footer under chat answers |
| `ui.chat_show_trace` | `CHAT_SHOW_TRACE` | `int` | `1` | ≥ 0, ≤ 1 | Show routing trace panel by default |
| `ui.chat_stream_include_thinking` | `CHAT_STREAM_INCLUDE_THINKING` | `int` | `1` | ≥ 0, ≤ 1 | Include reasoning/thinking in streamed responses when supported by model |
| `ui.chat_stream_timeout` | `CHAT_STREAM_TIMEOUT` | `int` | `120` | ≥ 30, ≤ 600 | Streaming response timeout in seconds |
| `ui.chat_streaming_enabled` | `CHAT_STREAMING_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable streaming responses |
| `ui.chat_thinking_budget_tokens` | `CHAT_THINKING_BUDGET_TOKENS` | `int` | `10000` | ≥ 1000, ≤ 100000 | Max thinking tokens for Anthropic extended thinking |
| `ui.editor_bind` | `EDITOR_BIND` | `str` | `"local"` | — | Editor bind mode |
| `ui.editor_embed_enabled` | `EDITOR_EMBED_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable editor embedding |
| `ui.editor_enabled` | `EDITOR_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable embedded editor |
| `ui.editor_image` | `EDITOR_IMAGE` | `str` | `"codercom/code-server:latest"` | — | Editor Docker image |
| `ui.editor_port` | `EDITOR_PORT` | `int` | `4440` | ≥ 1024, ≤ 65535 | Embedded editor port |
| `ui.grafana_auth_mode` | `GRAFANA_AUTH_MODE` | `str` | `"anonymous"` | — | Grafana authentication mode |
| `ui.grafana_base_url` | `GRAFANA_BASE_URL` | `str` | `"http://127.0.0.1:3001"` | — | Grafana base URL |
| `ui.grafana_dashboard_slug` | `GRAFANA_DASHBOARD_SLUG` | `str` | `"tribrid-overview"` | — | Grafana dashboard slug |
| `ui.grafana_dashboard_uid` | `GRAFANA_DASHBOARD_UID` | `str` | `"tribrid-overview"` | — | Default Grafana dashboard UID |
| `ui.grafana_embed_enabled` | `GRAFANA_EMBED_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable Grafana embedding |
| `ui.grafana_kiosk` | `GRAFANA_KIOSK` | `str` | `"tv"` | — | Grafana kiosk mode |
| `ui.grafana_org_id` | `GRAFANA_ORG_ID` | `int` | `1` | — | Grafana organization ID |
| `ui.grafana_refresh` | `GRAFANA_REFRESH` | `str` | `"10s"` | — | Grafana refresh interval |
| `ui.learning_reranker_default_preset` | `LEARNING_RERANKER_DEFAULT_PRESET` | `Literal["balanced", "focus_viz", "focus_logs", "focus_inspector"]` | `"balanced"` | allowed="balanced", "focus_viz", "focus_logs", "focus_inspector" | Default pane layout preset applied when opening Learning Reranker Studio |
| `ui.learning_reranker_dockview_layout_json` | `LEARNING_RERANKER_DOCKVIEW_LAYOUT_JSON` | `str` | `""` | — | Serialized Dockview layout JSON for Learning Reranker Studio pane persistence |
| `ui.learning_reranker_layout_engine` | `LEARNING_RERANKER_LAYOUT_ENGINE` | `Literal["dockview", "panels"]` | `"dockview"` | allowed="dockview", "panels" | Learning Reranker Studio layout engine selection |
| `ui.learning_reranker_logs_renderer` | `LEARNING_RERANKER_LOGS_RENDERER` | `Literal["json", "xterm"]` | `"xterm"` | allowed="json", "xterm" | Preferred logs renderer for Learning Reranker Studio |
| `ui.learning_reranker_show_setup_row` | `LEARNING_RERANKER_SHOW_SETUP_ROW` | `int` | `0` | ≥ 0, ≤ 1 | Show setup summary row above studio dock layout (1=show, 0=collapsed) |
| `ui.learning_reranker_studio_bottom_panel_pct` | `LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT` | `int` | `28` | ≥ 18, ≤ 45 | Default bottom dock height percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_immersive` | `LEARNING_RERANKER_STUDIO_IMMERSIVE` | `int` | `1` | ≥ 0, ≤ 1 | Use immersive full-height studio mode for Learning Reranker |
| `ui.learning_reranker_studio_left_panel_pct` | `LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT` | `int` | `20` | ≥ 15, ≤ 35 | Default left dock width percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_right_panel_pct` | `LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT` | `int` | `30` | ≥ 20, ≤ 45 | Default right dock width percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_v2_enabled` | `LEARNING_RERANKER_STUDIO_V2_ENABLED` | `int` | `1` | ≥ 0, ≤ 1 | Enable Learning Reranker Studio V2 layout and controls |
| `ui.learning_reranker_visualizer_color_mode` | `LEARNING_RERANKER_VISUALIZER_COLOR_MODE` | `Literal["absolute", "delta"]` | `"absolute"` | allowed="absolute", "delta" | Neural Visualizer trajectory coloring mode (absolute loss vs delta loss) |
| `ui.learning_reranker_visualizer_max_points` | `LEARNING_RERANKER_VISUALIZER_MAX_POINTS` | `int` | `10000` | ≥ 1000, ≤ 50000 | Maximum telemetry points retained for Neural Visualizer |
| `ui.learning_reranker_visualizer_motion_intensity` | `LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY` | `float` | `1.0` | ≥ 0.0, ≤ 2.0 | Global motion intensity multiplier for Neural Visualizer effects |
| `ui.learning_reranker_visualizer_quality` | `LEARNING_RERANKER_VISUALIZER_QUALITY` | `Literal["balanced", "cinematic", "ultra"]` | `"cinematic"` | allowed="balanced", "cinematic", "ultra" | Neural Visualizer quality tier |
| `ui.learning_reranker_visualizer_reduce_motion` | `LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION` | `int` | `0` | ≥ 0, ≤ 1 | Reduce Neural Visualizer motion for accessibility/performance |
| `ui.learning_reranker_visualizer_renderer` | `LEARNING_RERANKER_VISUALIZER_RENDERER` | `Literal["auto", "webgpu", "webgl2", "canvas2d"]` | `"auto"` | allowed="auto", "webgpu", "webgl2", "canvas2d" | Preferred renderer for Neural Visualizer |
| `ui.learning_reranker_visualizer_show_vector_field` | `LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD` | `int` | `1` | ≥ 0, ≤ 1 | Render animated vector field accents in Neural Visualizer |
| `ui.learning_reranker_visualizer_tail_seconds` | `LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS` | `float` | `8.0` | ≥ 1.0, ≤ 30.0 | Temporal tail length in seconds for visualizer trajectory effects |
| `ui.learning_reranker_visualizer_target_fps` | `LEARNING_RERANKER_VISUALIZER_TARGET_FPS` | `int` | `60` | ≥ 30, ≤ 144 | Target FPS for Neural Visualizer animation loop |
| `ui.open_browser` | `OPEN_BROWSER` | `int` | `1` | ≥ 0, ≤ 1 | Auto-open browser on start |
| `ui.runtime_mode` | `RUNTIME_MODE` | `Literal["development", "production"]` | `"development"` | allowed="development", "production" | Runtime environment mode (development uses localhost, production uses deployed URLs) |
| `ui.theme_mode` | `THEME_MODE` | `str` | `"dark"` | pattern=^(light\|dark\|auto)$ | UI theme mode |

### Details (glossary)

??? info "`ui.chat_default_model` (`CHAT_DEFAULT_MODEL`) — Default Chat Model"
    **Category**: `generation`

    Default LLM model used for chat when not overridden per-request. Common options: gpt-4o-mini (fast/cheap), gpt-4o (balanced), claude-3-5-sonnet (high quality), or local Ollama models. Per-request model overrides take precedence.

    **Links**:
    - [OpenAI Models](https://platform.openai.com/docs/models)
    - [Anthropic Models](https://docs.anthropic.com/en/docs/about-claude/models)

??? info "`ui.chat_show_citations` (`CHAT_SHOW_CITATIONS`) — Inline File References"
    **Category**: `general`

    Display source file paths and line numbers inline with the answer. Citations become clickable links to code locations.

??? info "`ui.chat_stream_include_thinking` (`CHAT_STREAM_INCLUDE_THINKING`) — Include Thinking in Stream"
    **Category**: `general`

    When enabled and using a thinking/reasoning model (like Anthropic Claude with extended thinking or OpenAI o-series), the model's reasoning process will be streamed to the UI before the final answer. This provides transparency into how the model arrived at its conclusion but increases response length. Disable if you only want final answers without reasoning traces.

    **Badges**:
    - Advanced

    **Links**:
    - [Anthropic Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
    - [OpenAI Reasoning Models](https://platform.openai.com/docs/guides/reasoning)

??? info "`ui.chat_stream_timeout` (`CHAT_STREAM_TIMEOUT`) — Stream Timeout (seconds)"
    **Category**: `general`

    Maximum time in seconds to wait for a streaming chat response to complete. If the stream doesn't finish within this time, the connection will be closed. Increase for complex queries that require longer generation times. Default: 120 seconds (2 minutes). Range: 30-600 seconds.

    **Badges**:
    - Affects reliability

    **Links**:
    - [HTTP Timeouts](https://developer.mozilla.org/en-US/docs/Web/API/fetch#options)

??? info "`ui.chat_streaming_enabled` (`CHAT_STREAMING_ENABLED`) — Chat Streaming"
    **Category**: `general`

    Enable streaming responses for chat interfaces. When on, tokens appear incrementally (like typing). Better UX but requires SSE support. Disable for simple request-response APIs.

    **Links**:
    - [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
    - [Streaming API](https://platform.openai.com/docs/api-reference/streaming)

??? info "`ui.chat_thinking_budget_tokens` (`CHAT_THINKING_BUDGET_TOKENS`) — Thinking Budget Tokens"
    **Category**: `general`

    Maximum number of tokens allocated for the model's internal reasoning/thinking process when using thinking-enabled models like Anthropic Claude with extended thinking. Higher budgets allow deeper reasoning but increase latency and cost. Only applies when using models that support extended thinking. Default: 10,000 tokens. Range: 1,000-100,000.

    **Badges**:
    - Cost

    **Links**:
    - [Anthropic Thinking Budget](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#budget-tokens)

??? info "`ui.editor_bind` (`EDITOR_BIND`) — Editor Bind Address"
    **Category**: `ui`

    Network interface for editor service to bind to. Use 127.0.0.1 for localhost-only access (secure), 0.0.0.0 for network access (enable remote editing).

    **Links**:
    - [Network Binding](https://en.wikipedia.org/wiki/Network_socket)

??? info "`ui.editor_embed_enabled` (`EDITOR_EMBED_ENABLED`) — Editor Embed Mode"
    **Category**: `embedding`

    Enable embedded editor iframe in GUI (1=yes, 0=no). When enabled, editor opens inline. When disabled, opens in new tab/window. Embedding requires CORS configuration.

    **Links**:
    - [iframe Embedding](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/iframe)

??? info "`ui.editor_enabled` (`EDITOR_ENABLED`) — Editor Enabled"
    **Category**: `ui`

    Enable embedded code editor integration in GUI (1=yes, 0=no). Allows viewing and editing code snippets from retrieval results directly in browser.

    **Links**:
    - [Code Editor Integration](https://en.wikipedia.org/wiki/Source-code_editor)

??? info "`ui.editor_port` (`EDITOR_PORT`) — Editor Port"
    **Category**: `infrastructure`

    TCP port for code editor service. Default: varies by editor. Must not conflict with other services (PORT, MCP_HTTP_PORT, PROMETHEUS_PORT).

    **Links**:
    - [Port Configuration](https://en.wikipedia.org/wiki/Port_(computer_networking))

??? info "`ui.grafana_auth_mode` (`GRAFANA_AUTH_MODE`) — Grafana Auth Mode"
    **Category**: `general`

    Authentication method for Grafana. Options: "token" (API token), "basic" (username/password), "none" (public dashboards).

    **Links**:
    - [Grafana Auth](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/)

??? info "`ui.grafana_base_url` (`GRAFANA_BASE_URL`) — Grafana Base URL"
    **Category**: `infrastructure`

    Base URL for Grafana dashboard server (e.g., http://localhost:3000). Used for embedded dashboard iframes in GUI and direct links to monitoring dashboards.

    **Links**:
    - [Grafana Setup](https://grafana.com/docs/grafana/latest/setup-grafana/)

??? info "`ui.grafana_dashboard_uid` (`GRAFANA_DASHBOARD_UID`) — Grafana Dashboard UID"
    **Category**: `ui`

    Unique identifier for default Grafana dashboard to display in GUI. Find UID in dashboard settings or URL (e.g., /d/abc123/dashboard-name -> UID is abc123).

    **Links**:
    - [Dashboard UIDs](https://grafana.com/docs/grafana/latest/dashboards/)

??? info "`ui.learning_reranker_default_preset` (`LEARNING_RERANKER_DEFAULT_PRESET`) — Learning Reranker Default Preset"
    **Category**: `reranking`

    Default pane preset applied when Learning Reranker Studio opens. Options: balanced, focus_viz, focus_logs, focus_inspector. Default: balanced.

??? info "`ui.learning_reranker_layout_engine` (`LEARNING_RERANKER_LAYOUT_ENGINE`) — Learning Reranker Layout Engine"
    **Category**: `reranking`

    Layout system used by Learning Reranker Studio. Options: dockview or panels. Default: dockview. Use panels only if you need the simpler fallback layout behavior.

??? info "`ui.learning_reranker_logs_renderer` (`LEARNING_RERANKER_LOGS_RENDERER`) — Learning Reranker Logs Renderer"
    **Category**: `reranking`

    Preferred log output renderer in Learning Reranker Studio. Options: json or xterm. Default: xterm.

??? info "`ui.learning_reranker_show_setup_row` (`LEARNING_RERANKER_SHOW_SETUP_ROW`) — Learning Reranker Show Setup Row"
    **Category**: `reranking`

    Show or hide the setup summary row above the studio layout (1=show, 0=collapsed). Default: 0. Range: 0-1.

??? info "`ui.learning_reranker_studio_bottom_panel_pct` (`LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT`) — Learning Reranker Studio Bottom Panel %"
    **Category**: `reranking`

    Default bottom dock height percentage for Learning Reranker Studio. Default: 28. Range: 18-45.

??? info "`ui.learning_reranker_studio_left_panel_pct` (`LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT`) — Learning Reranker Studio Left Panel %"
    **Category**: `reranking`

    Default left dock width percentage for Learning Reranker Studio. Default: 20. Range: 15-35.

??? info "`ui.learning_reranker_studio_right_panel_pct` (`LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT`) — Learning Reranker Studio Right Panel %"
    **Category**: `reranking`

    Default right dock width percentage for Learning Reranker Studio. Default: 30. Range: 20-45.

??? info "`ui.learning_reranker_visualizer_color_mode` (`LEARNING_RERANKER_VISUALIZER_COLOR_MODE`) — Learning Reranker Visualizer: Color Mode"
    **Category**: `reranking`

    <span class="tt-strong">What this control changes</span><br>Color mode changes only <span class="tt-strong">hue/intensity encoding</span> for the trajectory points. It does <span class="tt-strong">not</span> change x/y projection and it does <span class="tt-strong">not</span> change terrain height. In the code path, geometry is computed first and color is assigned later in <span class="mono">projectPoints(..., intensityMode)</span>.<br><br><span class="tt-strong">Mode = absolute (where am I doing well?)</span><br>Each point is colored from normalized train loss at that step. Lower loss maps toward the better/cooler side of the palette, higher loss toward the worse/warmer side. This is the easiest way to answer "which regions of this run were strong vs weak?" In this implementation, color is mostly loss with a smaller gradient-norm blend so structure remains visible when loss is locally flat.<br><br><span class="tt-strong">Mode = delta (am I improving right now?)</span><br>Each point is colored from first difference versus the previous point: <span class="mono">prev_loss - current_loss</span>. Positive delta means local improvement; negative delta means local regression. This surfaces "learning" vs "thrashing" even when absolute loss is jagged because of mini-batch stochasticity.<br><br><span class="tt-strong">Interpretation rule</span><br>Use <span class="mono">absolute</span> when comparing quality across run regions. Use <span class="mono">delta</span> when diagnosing local optimizer behavior, schedule transitions, or instability.<br><br><span class="tt-strong">Code path</span><br><span class="mono">web/src/components/RerankerTraining/NeuralVisualizerCore.tsx -> projectPoints(... intensityMode ...)</span>

    **Badges**:
    - Visualizer semantics
    - Telemetry-driven

    **Links**:
    - [Matplotlib: Choosing Colormaps](https://matplotlib.org/stable/users/explain/colors/colormaps.html)
    - [Kenneth Moreland: Diverging Color Maps for Scientific Visualization](https://www.kennethmoreland.com/color-maps/)
    - [ColorBrewer 2.0](https://colorbrewer2.org/)
    - [Deep Learning Book - Optimization for Training Deep Models](https://www.deeplearningbook.org/contents/optimization.html)
    - [SGDR: Stochastic Gradient Descent with Warm Restarts](https://arxiv.org/abs/1608.03983)

??? info "`ui.learning_reranker_visualizer_max_points` (`LEARNING_RERANKER_VISUALIZER_MAX_POINTS`) — Learning Reranker Visualizer Max Points"
    **Category**: `reranking`

    Maximum telemetry points retained for Neural Visualizer history. Default: 10000. Range: 1000-50000. Higher values preserve more history at higher memory cost.

??? info "`ui.learning_reranker_visualizer_motion_intensity` (`LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY`) — Learning Reranker Visualizer Motion Intensity"
    **Category**: `reranking`

    Global motion multiplier for Neural Visualizer effects. Default: 1.0. Range: 0.0-2.0. Lower values produce calmer motion.

??? info "`ui.learning_reranker_visualizer_quality` (`LEARNING_RERANKER_VISUALIZER_QUALITY`) — Learning Reranker Visualizer Quality"
    **Category**: `reranking`

    Neural Visualizer quality tier. Options: balanced, cinematic, ultra. Default: cinematic. Higher tiers look better but use more GPU/CPU.

??? info "`ui.learning_reranker_visualizer_reduce_motion` (`LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION`) — Learning Reranker Visualizer Reduce Motion"
    **Category**: `reranking`

    Accessibility/performance switch to reduce visualizer motion (1=reduce, 0=full motion). Default: 0. Range: 0-1.

??? info "`ui.learning_reranker_visualizer_renderer` (`LEARNING_RERANKER_VISUALIZER_RENDERER`) — Learning Reranker Visualizer Renderer"
    **Category**: `reranking`

    Preferred renderer backend for the Neural Visualizer. Options: auto, webgpu, webgl2, canvas2d. Default: auto.

??? info "`ui.learning_reranker_visualizer_show_vector_field` (`LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD`) — Learning Reranker Visualizer Show Vector Field"
    **Category**: `reranking`

    Render animated vector-field accents in Neural Visualizer (1=on, 0=off). Default: 1. Range: 0-1.

??? info "`ui.learning_reranker_visualizer_tail_seconds` (`LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS`) — Learning Reranker Visualizer: Tail Seconds"
    **Category**: `reranking`

    <span class="tt-strong">What this setting does</span><br>Controls the temporal tail length used while Live mode is on. The visualizer shows the most recent portion of the trajectory to keep motion legible and avoid overdraw in long runs.<br><br><span class="tt-strong">Implementation detail</span><br>Tail seconds are converted to a displayed point count using an internal sampling heuristic (approximately <span class="mono">tail_seconds * 14</span>, then clamped to a safety range). This is a rendering policy, not a training metric policy.<br><br><span class="tt-strong">Troubleshooting "snake tail" behavior</span><br>If the run start appears to vanish, increase this value, disable Live, or scrub manually. In scrubbing mode, full history up to the selected index is shown.<br><br><span class="tt-strong">Tuning guidance</span><br>Lower values emphasize short-term dynamics and make rapid motion cleaner. Higher values preserve more context but can look visually dense on noisy runs.

    **Badges**:
    - Live playback only
    - Visualization policy

    **Links**:
    - [Matplotlib Animation Blitting (performance/readability tradeoffs)](https://matplotlib.org/stable/users/explain/animations/blitting.html)
    - [TensorBoard Scalars (handling long, noisy trajectories)](https://www.tensorflow.org/tensorboard/scalars_and_keras)

??? info "`ui.learning_reranker_visualizer_target_fps` (`LEARNING_RERANKER_VISUALIZER_TARGET_FPS`) — Learning Reranker Visualizer Target FPS"
    **Category**: `reranking`

    Target frame rate for Neural Visualizer animation. Default: 60. Range: 30-144. Lower values reduce GPU load.

??? info "`ui.open_browser` (`OPEN_BROWSER`) — Auto-Open Browser"
    **Category**: `general`

    Automatically open browser to GUI when server starts (1=yes, 0=no). Convenient for local development, disable for server deployments or headless environments.

    **Links**:
    - [Browser Automation](https://en.wikipedia.org/wiki/Browser_automation)

??? info "`ui.theme_mode` (`THEME_MODE`) — GUI Theme"
    **Category**: `ui`

    Color theme for web GUI. Options: "light" (light mode), "dark" (dark mode), "auto" (follows system preference). Changes appearance immediately when toggled.

    **Links**:
    - [Dark Mode Benefits](https://en.wikipedia.org/wiki/Light-on-dark_color_scheme)
