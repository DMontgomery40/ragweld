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
| `ui.chat_default_model` | `CHAT_DEFAULT_MODEL` | `str` | `"ragweld-local"` | — | Default model for chat if not specified in request |
| `ui.chat_history_max` | `CHAT_HISTORY_MAX` | `int` | `50` | ≥ 10, ≤ 500 | Max chat history messages |
| `ui.chat_show_citations` | `CHAT_SHOW_CITATIONS` | `bool` | `true` | — | Show citations list on chat answers |
| `ui.chat_show_confidence` | `CHAT_SHOW_CONFIDENCE` | `bool` | `false` | — | Show confidence badge on chat answers |
| `ui.chat_show_debug_footer` | `CHAT_SHOW_DEBUG_FOOTER` | `bool` | `true` | — | Show dev/debug footer under chat answers |
| `ui.chat_show_trace` | `CHAT_SHOW_TRACE` | `bool` | `true` | — | Show routing trace panel by default |
| `ui.chat_stream_include_thinking` | `CHAT_STREAM_INCLUDE_THINKING` | `bool` | `true` | — | Include reasoning/thinking in streamed responses when supported by model |
| `ui.chat_stream_timeout` | `CHAT_STREAM_TIMEOUT` | `int` | `600` | ≥ 30, ≤ 600 | Streaming response timeout in seconds (sized for single-stream CPU serving of the local model) |
| `ui.chat_streaming_enabled` | `CHAT_STREAMING_ENABLED` | `bool` | `true` | — | Enable streaming responses |
| `ui.chat_thinking_budget_tokens` | `CHAT_THINKING_BUDGET_TOKENS` | `int` | `10000` | ≥ 1000, ≤ 100000 | Max thinking tokens for Anthropic extended thinking |
| `ui.editor_bind` | `EDITOR_BIND` | `str` | `"local"` | — | Editor bind mode |
| `ui.editor_embed_enabled` | `EDITOR_EMBED_ENABLED` | `bool` | `true` | — | Enable editor embedding |
| `ui.editor_enabled` | `EDITOR_ENABLED` | `bool` | `true` | — | Enable embedded editor |
| `ui.editor_image` | `EDITOR_IMAGE` | `str` | `"codercom/code-server:latest"` | — | Editor Docker image |
| `ui.editor_port` | `EDITOR_PORT` | `int` | `4440` | ≥ 1024, ≤ 65535 | Embedded editor port |
| `ui.grafana_auth_mode` | `GRAFANA_AUTH_MODE` | `str` | `"anonymous"` | — | Grafana authentication mode |
| `ui.grafana_base_url` | `GRAFANA_BASE_URL` | `str` | `"http://127.0.0.1:3301"` | — | Grafana base URL |
| `ui.grafana_dashboard_slug` | `GRAFANA_DASHBOARD_SLUG` | `str` | `"on-call-overview"` | — | Grafana dashboard slug |
| `ui.grafana_dashboard_uid` | `GRAFANA_DASHBOARD_UID` | `str` | `"ragweld-oncall-overview"` | — | Default Grafana dashboard UID |
| `ui.grafana_embed_enabled` | `GRAFANA_EMBED_ENABLED` | `bool` | `true` | — | Enable Grafana embedding |
| `ui.grafana_kiosk` | `GRAFANA_KIOSK` | `str` | `"tv"` | — | Grafana kiosk mode |
| `ui.grafana_org_id` | `GRAFANA_ORG_ID` | `int` | `1` | — | Grafana organization ID |
| `ui.grafana_refresh` | `GRAFANA_REFRESH` | `str` | `"10s"` | — | Grafana refresh interval |
| `ui.learning_reranker_default_preset` | `LEARNING_RERANKER_DEFAULT_PRESET` | `Literal["balanced", "focus_viz", "focus_logs", "focus_inspector"]` | `"balanced"` | allowed="balanced", "focus_viz", "focus_logs", "focus_inspector" | Default pane layout preset applied when opening Learning Reranker Studio |
| `ui.learning_reranker_dockview_layout_json` | `LEARNING_RERANKER_DOCKVIEW_LAYOUT_JSON` | `str` | `""` | — | Serialized Dockview layout JSON for Learning Reranker Studio pane persistence |
| `ui.learning_reranker_layout_engine` | `LEARNING_RERANKER_LAYOUT_ENGINE` | `Literal["dockview", "panels"]` | `"dockview"` | allowed="dockview", "panels" | Learning Reranker Studio layout engine selection |
| `ui.learning_reranker_logs_renderer` | `LEARNING_RERANKER_LOGS_RENDERER` | `Literal["json", "xterm"]` | `"xterm"` | allowed="json", "xterm" | Preferred logs renderer for Learning Reranker Studio |
| `ui.learning_reranker_show_setup_row` | `LEARNING_RERANKER_SHOW_SETUP_ROW` | `bool` | `false` | — | Show setup summary row above studio dock layout instead of collapsing it |
| `ui.learning_reranker_studio_bottom_panel_pct` | `LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT` | `int` | `28` | ≥ 18, ≤ 45 | Default bottom dock height percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_immersive` | `LEARNING_RERANKER_STUDIO_IMMERSIVE` | `bool` | `true` | — | Use immersive full-height studio mode for Learning Reranker |
| `ui.learning_reranker_studio_left_panel_pct` | `LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT` | `int` | `20` | ≥ 15, ≤ 35 | Default left dock width percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_right_panel_pct` | `LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT` | `int` | `30` | ≥ 20, ≤ 45 | Default right dock width percentage for Learning Reranker Studio |
| `ui.learning_reranker_studio_v2_enabled` | `LEARNING_RERANKER_STUDIO_V2_ENABLED` | `bool` | `true` | — | Enable Learning Reranker Studio V2 layout and controls |
| `ui.learning_reranker_visualizer_color_mode` | `LEARNING_RERANKER_VISUALIZER_COLOR_MODE` | `Literal["absolute", "delta"]` | `"absolute"` | allowed="absolute", "delta" | Neural Visualizer trajectory coloring mode (absolute loss vs delta loss) |
| `ui.learning_reranker_visualizer_max_points` | `LEARNING_RERANKER_VISUALIZER_MAX_POINTS` | `int` | `10000` | ≥ 1000, ≤ 50000 | Maximum telemetry points retained for Neural Visualizer |
| `ui.learning_reranker_visualizer_motion_intensity` | `LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY` | `float` | `1.0` | ≥ 0.0, ≤ 2.0 | Global motion intensity multiplier for Neural Visualizer effects |
| `ui.learning_reranker_visualizer_quality` | `LEARNING_RERANKER_VISUALIZER_QUALITY` | `Literal["balanced", "cinematic", "ultra"]` | `"cinematic"` | allowed="balanced", "cinematic", "ultra" | Neural Visualizer quality tier |
| `ui.learning_reranker_visualizer_reduce_motion` | `LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION` | `bool` | `false` | — | Reduce Neural Visualizer motion for accessibility/performance |
| `ui.learning_reranker_visualizer_renderer` | `LEARNING_RERANKER_VISUALIZER_RENDERER` | `Literal["auto", "webgpu", "webgl2", "canvas2d"]` | `"auto"` | allowed="auto", "webgpu", "webgl2", "canvas2d" | Preferred renderer for Neural Visualizer |
| `ui.learning_reranker_visualizer_show_vector_field` | `LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD` | `bool` | `true` | — | Render animated vector field accents in Neural Visualizer |
| `ui.learning_reranker_visualizer_tail_seconds` | `LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS` | `float` | `8.0` | ≥ 1.0, ≤ 30.0 | Temporal tail length in seconds for visualizer trajectory effects |
| `ui.learning_reranker_visualizer_target_fps` | `LEARNING_RERANKER_VISUALIZER_TARGET_FPS` | `int` | `60` | ≥ 30, ≤ 144 | Target FPS for Neural Visualizer animation loop |
| `ui.open_browser` | `OPEN_BROWSER` | `bool` | `true` | — | Auto-open browser on start |
| `ui.runtime_mode` | `RUNTIME_MODE` | `Literal["development", "production"]` | `"development"` | allowed="development", "production" | Runtime environment mode (development uses localhost, production uses deployed URLs) |
| `ui.theme_mode` | `THEME_MODE` | `str` | `"dark"` | pattern=^(light\|dark\|auto)$ | UI theme mode |

### Details (glossary)

??? info "`ui.chat_default_model` (`CHAT_DEFAULT_MODEL`) — Default Chat Model"
    **Category**: `generation`

    CHAT_DEFAULT_MODEL sets the model used when a chat request does not specify an override. This becomes your system-wide policy baseline for latency, cost, context length, and reasoning quality, so changing it affects nearly every conversation. In multi-provider setups, pair the default with explicit routing and fallback rules so quota or outage events do not silently shift quality. Revisit this setting after major model releases and benchmark updates, but decide with workload-specific evals instead of generic leaderboard performance.

    **Badges**:
    - Model Policy

    **Links**:
    - [HierRouter: Coordinated LLM Routing (arXiv)](https://arxiv.org/abs/2511.09873)
    - [Anthropic Claude Models Overview](https://docs.anthropic.com/en/docs/about-claude/models/overview)
    - [Google Gemini Models](https://ai.google.dev/gemini-api/docs/models)
    - [Ollama Documentation](https://docs.ollama.com/)

??? info "`ui.chat_show_citations` (`CHAT_SHOW_CITATIONS`) — Inline File References"
    **Category**: `general`

    Controls whether answers include explicit source attributions, such as file paths, snippets, or line references. In RAG, citations are critical for trust and debugging because they let users verify that claims are grounded in retrieved evidence rather than model guesswork. Enabling citations typically improves operator confidence and shortens investigation time when answers are wrong. The trade-off is extra response verbosity and minor UI complexity, but for technical and high-stakes workflows citations should usually remain on.

    **Badges**:
    - Trust

    **Links**:
    - [Concise RAG Citations (2025)](https://arxiv.org/abs/2509.20859)
    - [Anthropic Citations](https://docs.anthropic.com/en/docs/build-with-claude/citations)
    - [LlamaIndex Citation Query Engine](https://docs.llamaindex.ai/en/stable/examples/query_engine/citation_query_engine/)
    - [LangChain QA Citations](https://python.langchain.com/docs/how_to/qa_citations/)

??? info "`ui.chat_stream_include_thinking` (`CHAT_STREAM_INCLUDE_THINKING`) — Include Thinking in Stream"
    **Category**: `general`

    When supported by the selected model, this streams intermediate reasoning content before the final answer. It can improve operator visibility during debugging and evaluation, especially when you need to understand why retrieved evidence was prioritized or ignored. The trade-offs are longer streams, higher token usage, and potential exposure of internal reasoning that may not be appropriate for all audiences. For production end-user chat, many teams keep this off by default and enable it for internal analysis, testing, or expert modes.

    **Badges**:
    - Advanced reasoning

    **Links**:
    - [DeepSeek-R1 (2025)](https://arxiv.org/abs/2501.12948)
    - [Anthropic Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
    - [Anthropic Streaming](https://docs.anthropic.com/en/docs/build-with-claude/streaming)
    - [OpenAI Responses Cookbook](https://cookbook.openai.com/examples/responses_api/responses_example)

??? info "`ui.chat_stream_timeout` (`CHAT_STREAM_TIMEOUT`) — Stream Timeout (seconds)"
    **Category**: `general`

    Defines how long the system waits for a streaming response before aborting. This is a reliability safeguard against stalled model calls, network interruptions, or overloaded inference backends. Set it too low and valid long-form answers will be cut off; set it too high and failed requests tie up resources and degrade user experience. A practical approach is to align timeout values with observed p95 or p99 completion times for your largest retrieval contexts, then add retry logic and clear UI messaging for partial or timed-out outputs.

    **Badges**:
    - Reliability

    **Links**:
    - [CascadeInfer (2025)](https://arxiv.org/abs/2512.19179)
    - [MDN AbortSignal.timeout](https://developer.mozilla.org/en-US/docs/Web/API/AbortSignal/timeout_static)
    - [MDN Using Fetch](https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch)
    - [vLLM OpenAI-Compatible Server](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)

??? info "`ui.chat_streaming_enabled` (`CHAT_STREAMING_ENABLED`) — Chat Streaming"
    **Category**: `general`

    Enables token-by-token delivery instead of waiting for a complete response. Streaming reduces perceived latency and gives users immediate feedback, which is especially useful when retrieval and reasoning steps produce longer answers. It also changes system design requirements: your frontend and gateway must support incremental events, cancellation, and partial-output rendering. If your deployment path does not reliably support SSE-style transport, disabling streaming can simplify operations at the expense of slower perceived responsiveness.

    **Badges**:
    - Real-time UX

    **Links**:
    - [CascadeInfer (2025)](https://arxiv.org/abs/2512.19179)
    - [Anthropic Streaming](https://docs.anthropic.com/en/docs/build-with-claude/streaming)
    - [MDN Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
    - [W3C EventSource Spec](https://www.w3.org/TR/eventsource/)

??? info "`ui.chat_thinking_budget_tokens` (`CHAT_THINKING_BUDGET_TOKENS`) — Thinking Budget Tokens"
    **Category**: `general`

    Sets the token budget allocated to reasoning or hidden deliberation for models that support extended thinking modes. Larger budgets can improve performance on multi-step reasoning, but they also increase latency and spend, and may be unnecessary for straightforward retrieval-backed answers. This parameter should be tuned per task class: keep budgets small for routine lookups and raise them only for complex synthesis, planning, or ambiguity resolution. Monitor both answer quality and total time-to-final-token when adjusting this value.

    **Badges**:
    - Inference budget

    **Links**:
    - [DeepSeek-R1 (2025)](https://arxiv.org/abs/2501.12948)
    - [Anthropic Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
    - [Anthropic Context Windows](https://docs.anthropic.com/en/docs/build-with-claude/context-windows)
    - [vLLM Spec Decode](https://docs.vllm.ai/en/latest/features/spec_decode.html)

??? info "`ui.editor_bind` (`EDITOR_BIND`) — Editor Bind Address"
    **Category**: `ui`

    Chooses the interface address used by the editor service. Binding to 127.0.0.1 limits access to the local host and is safest for development, while 0.0.0.0 exposes the service to the network and requires strong authentication, TLS, and firewall boundaries. In RAG environments, exposed editors can provide indirect access to prompts, config, or indexed data paths. Treat non-local binding as a security-sensitive deployment decision.

    **Badges**:
    - Network exposure

    **Links**:
    - [Uvicorn host and port settings](https://www.uvicorn.org/settings/)
    - [code-server guide](https://coder.com/docs/code-server/latest/guide)
    - [MDN CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)
    - [JavaSith security framework (2025)](https://arxiv.org/abs/2505.21263)

??? info "`ui.editor_embed_enabled` (`EDITOR_EMBED_ENABLED`) — Editor Embed Mode"
    **Category**: `embedding`

    Controls whether the editor opens inside the app via iframe or in a separate tab/window. Embedded mode improves workflow continuity when reviewing retrieved snippets, but it introduces framing and origin policy constraints that must be configured correctly. Misconfiguration can break sessions, block assets, or create clickjacking and token-handling risk. Enable embed mode only when your CORS and frame policies are explicit and tested.

    **Badges**:
    - Embed security

    **Links**:
    - [MDN iframe element](https://developer.mozilla.org/en-US/docs/Web/HTML/Element/iframe)
    - [MDN CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS)
    - [VS Code for the Web](https://code.visualstudio.com/docs/editor/vscode-web)
    - [JavaSith security framework (2025)](https://arxiv.org/abs/2505.21263)

??? info "`ui.editor_enabled` (`EDITOR_ENABLED`) — Editor Enabled"
    **Category**: `ui`

    Master switch for enabling in-product editor integration. When enabled, teams can rapidly adjust prompts, chunking settings, or templates while validating retrieval behavior, which improves iteration speed. The tradeoff is a larger runtime attack surface and a stronger need for authz, audit, and environment isolation. Disable this in hardened environments where runtime mutation is not allowed.

    **Badges**:
    - UI capability gate

    **Links**:
    - [code-server guide](https://coder.com/docs/code-server/latest/guide)
    - [VS Code for the Web](https://code.visualstudio.com/docs/editor/vscode-web)
    - [Uvicorn settings](https://www.uvicorn.org/settings/)
    - [JavaSith security framework (2025)](https://arxiv.org/abs/2505.21263)

??? info "`ui.editor_port` (`EDITOR_PORT`) — Editor Port"
    **Category**: `infrastructure`

    Specifies the TCP port used by the editor service and must be coordinated with API, metrics, and model endpoints. Port conflicts often appear as intermittent startup or health-check failures in multi-service RAG dev environments. If remote access is needed, expose this port through a controlled proxy instead of direct public binding. Keep port mapping documented so local, CI, and staging stacks stay reproducible.

    **Badges**:
    - Port hygiene

    **Links**:
    - [Uvicorn host and port settings](https://www.uvicorn.org/settings/)
    - [Docker port publishing](https://docs.docker.com/get-started/docker-concepts/running-containers/publishing-ports/)
    - [code-server guide](https://coder.com/docs/code-server/latest/guide)
    - [JavaSith security framework (2025)](https://arxiv.org/abs/2505.21263)

??? info "`ui.grafana_auth_mode` (`GRAFANA_AUTH_MODE`) — Grafana Auth Mode"
    **Category**: `general`

    Auth mode determines how your app authenticates to Grafana and therefore defines the monitoring trust boundary. Token or service-account auth is preferred for automated integrations because it supports least privilege and clearer auditing. Basic auth can work for small internal setups but is harder to rotate safely and tends to leak into scripts. No-auth mode should be limited to intentionally public dashboards only. Align auth mode with environment tier and explicitly restrict access to administrative API surfaces.

    **Badges**:
    - Access control

    **Links**:
    - [AgentSight: Observability for AI Agents (arXiv 2025)](https://arxiv.org/abs/2508.02736)
    - [Grafana Security Configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/)
    - [Grafana HTTP API Authentication](https://grafana.com/docs/grafana/latest/developer-resources/api-reference/http-api/authentication/)
    - [Grafana Service Accounts](https://grafana.com/docs/grafana/latest/administration/service-accounts/)

??? info "`ui.grafana_base_url` (`GRAFANA_BASE_URL`) — Grafana Base URL"
    **Category**: `infrastructure`

    This is the canonical Grafana endpoint your app uses for links, API calls, and embedded dashboards. It must match deployment topology, including scheme, host, and any subpath behind reverse proxies. Misalignment between app base URL and Grafana root URL often causes broken embeds, redirect loops, or partial auth failures. Validate this value at startup and in health checks, especially across dev, staging, and production environments. Keep it environment-specific and versioned with infrastructure config so monitor links remain stable.

    **Badges**:
    - Endpoint config

    **Links**:
    - [AgentSight: Observability for AI Agents (arXiv 2025)](https://arxiv.org/abs/2508.02736)
    - [Grafana Setup Guide](https://grafana.com/docs/grafana/latest/setup-grafana/#start-the-grafana-server)
    - [Grafana root_url Configuration](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/#root_url)
    - [Grafana Configuration Reference](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/)

??? info "`ui.grafana_dashboard_uid` (`GRAFANA_DASHBOARD_UID`) — Grafana Dashboard UID"
    **Category**: `ui`

    GRAFANA_DASHBOARD_UID tells the app which Grafana dashboard to open as the default observability view. Use the dashboard UID, not the title slug, because UIDs stay stable across title edits and are the identifier used by Grafana APIs. In a RAG system, point this at a dashboard that tracks retrieval latency, top-k quality proxies, token usage, embedding throughput, and error rates so operators can diagnose regressions quickly. If this value is wrong or points to a dashboard the service account cannot read, users will land on an empty or error page even when Grafana is healthy. For multi-environment deployments, keep a distinct UID per environment and manage it as configuration, not hardcoded UI logic.

    **Badges**:
    - Observability

    **Links**:
    - [Grafana Dashboards Documentation](https://grafana.com/docs/grafana/latest/dashboards/)
    - [View Dashboard JSON Model (UID Field)](https://grafana.com/docs/grafana/latest/dashboards/build-dashboards/view-dashboard-json-model/)
    - [Grafana Dashboard HTTP API](https://grafana.com/docs/grafana/latest/http_api/dashboard/)
    - [DICE (2025): Comparative Evaluation for RAG](https://arxiv.org/abs/2512.22629)

??? info "`ui.learning_reranker_default_preset` (`LEARNING_RERANKER_DEFAULT_PRESET`) — Learning Reranker Default Preset"
    **Category**: `reranking`

    Default studio preset loaded when the learning-reranker workspace opens, controlling which panes and diagnostics are immediately visible. Although it does not change model weights, it changes operator behavior by determining whether users start from metric dashboards, logs, or inspectors, which affects how quickly failures are diagnosed. Good defaults reduce setup friction and increase consistency across experiments, especially when multiple engineers tune reranker training. Choose a preset that exposes the minimum signals needed for safe decision-making in your typical workflow.

    **Badges**:
    - Workflow default

    **Links**:
    - [ERank: Efficient Learning-to-Rank for RAG (arXiv)](https://arxiv.org/abs/2509.00520)
    - [Dockview](https://dockview.dev/)
    - [xterm.js Documentation](https://xtermjs.org/docs/)
    - [MDN JSON Reference](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON)

??? info "`ui.learning_reranker_layout_engine` (`LEARNING_RERANKER_LAYOUT_ENGINE`) — Learning Reranker Layout Engine"
    **Category**: `reranking`

    UI layout system used by the reranker studio, which governs pane docking behavior, state persistence, and interaction performance for high-density training dashboards. While this is not a retrieval algorithm parameter, it impacts operational efficiency because poor layout ergonomics slow inspection of ranking metrics, error cases, and training logs. Prefer the engine that gives stable panel persistence and low interaction overhead on your target hardware and browser stack. Keep layout configuration versioned so team workflows remain consistent across releases.

    **Badges**:
    - Studio ergonomics

    **Links**:
    - [ERank: Efficient Learning-to-Rank for RAG (arXiv)](https://arxiv.org/abs/2509.00520)
    - [Dockview](https://dockview.dev/)
    - [Vite Guide](https://vitejs.dev/guide/)
    - [xterm.js Documentation](https://xtermjs.org/docs/)

??? info "`ui.learning_reranker_logs_renderer` (`LEARNING_RERANKER_LOGS_RENDERER`) — Learning Reranker Logs Renderer"
    **Category**: `reranking`

    Controls whether studio logs are rendered as terminal-like streaming output or structured JSON views. Terminal rendering is better for real-time operational monitoring during active training, while JSON rendering is better for filtering, programmatic analysis, and postmortem debugging of failed runs. The best choice depends on whether your primary task is live supervision or forensic inspection of reranker behavior. Standardizing this setting across teams improves reproducibility of debugging workflows and incident handoffs.

    **Badges**:
    - Debug visibility

    **Links**:
    - [ERank: Efficient Learning-to-Rank for RAG (arXiv)](https://arxiv.org/abs/2509.00520)
    - [xterm.js Documentation](https://xtermjs.org/docs/)
    - [MDN JSON Reference](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/JSON)
    - [LangSmith Observability Quickstart](https://docs.langchain.com/langsmith/observability-quickstart)

??? info "`ui.learning_reranker_show_setup_row` (`LEARNING_RERANKER_SHOW_SETUP_ROW`) — Learning Reranker Show Setup Row"
    **Category**: `reranking`

    `LEARNING_RERANKER_SHOW_SETUP_ROW` controls whether the setup summary row is visible above the training studio dock layout (enabled = shown, disabled = collapsed; default disabled). This row provides quick context about run configuration and can reduce navigation overhead when comparing experiments, especially in dense training sessions. Hiding it increases available workspace for logs, visualizer output, and inspection panels, which can be better on smaller displays. Enable it when onboarding or debugging configuration drift, and disable it when users already know the setup and need maximal panel real estate.

    **Links**:
    - [Automating UI Optimization through Multi-Agentic Reasoning (arXiv)](https://arxiv.org/abs/2602.13126)
    - [Dockview Core Overview](https://dockview.dev/docs/core/overview/)
    - [MDN CSS Grid Layout Guide](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout)
    - [WCAG 2.2 Understanding Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

??? info "`ui.learning_reranker_studio_bottom_panel_pct` (`LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT`) — Learning Reranker Studio Bottom Panel %"
    **Category**: `reranking`

    `LEARNING_RERANKER_STUDIO_BOTTOM_PANEL_PCT` sets the default height of the studio bottom dock as a percentage of total workspace (default `28`, allowed range `18`-`45`). This value directly affects how much vertical space is reserved for outputs like logs, diagnostics, and timeline-style visual traces versus the primary training controls. Lower percentages prioritize top-level controls and inspectors, while higher percentages favor continuous monitoring and detailed log reading. Keep the value within the configured bounds to avoid layout crowding and ensure predictable behavior across desktop and smaller laptop resolutions.

    **Links**:
    - [Automating UI Optimization through Multi-Agentic Reasoning (arXiv)](https://arxiv.org/abs/2602.13126)
    - [Dockview Core Overview](https://dockview.dev/docs/core/overview/)
    - [MDN CSS Grid Layout Guide](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout)
    - [WCAG 2.2 Understanding Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

??? info "`ui.learning_reranker_studio_left_panel_pct` (`LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT`) — Learning Reranker Studio Left Panel %"
    **Category**: `reranking`

    `LEARNING_RERANKER_STUDIO_LEFT_PANEL_PCT` sets the default width of the left dock in the learning-reranker studio (default `20`, allowed range `15`-`35`). In practice, this controls how much horizontal space is allocated to setup/navigation controls before content-heavy panes such as logs, charts, or inspectors take over. Smaller values increase room for analysis panels and visualizer outputs, while larger values improve readability of configuration forms and parameter groups. Tune this with real workflows and screen sizes so key controls remain visible without forcing excessive panel toggling.

    **Links**:
    - [Automating UI Optimization through Multi-Agentic Reasoning (arXiv)](https://arxiv.org/abs/2602.13126)
    - [Dockview Core Overview](https://dockview.dev/docs/core/overview/)
    - [MDN CSS Grid Layout Guide](https://developer.mozilla.org/en-US/docs/Web/CSS/CSS_grid_layout)
    - [WCAG 2.2 Understanding Reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

??? info "`ui.learning_reranker_studio_right_panel_pct` (`LEARNING_RERANKER_STUDIO_RIGHT_PANEL_PCT`) — Learning Reranker Studio Right Panel %"
    **Category**: `reranking`

    Controls how much horizontal space the right-side inspector gets in Learning Reranker Studio. This panel usually contains high-context diagnostics (metric chips, run metadata, and explanation details), so shrinking it too aggressively can hide critical state and force extra toggling. Increasing it improves readability for dense diagnostics, but steals width from query/result panes and can reduce comparison speed. Treat this as a task-fit control: wider for debugging and failure analysis, narrower for rapid iterative edits. Keep it coordinated with left/bottom panel widths so the core training and ranking context remains visible at the same time.

    **Links**:
    - [AI-Assisted Adaptive Rendering for High-Frequency Security Telemetry in Web Interfaces (arXiv, 2026)](https://arxiv.org/abs/2602.01671)
    - [MDN: grid-template-columns](https://developer.mozilla.org/en-US/docs/Web/CSS/grid-template-columns)
    - [MDN: flex](https://developer.mozilla.org/en-US/docs/Web/CSS/flex)
    - [react-resizable-panels](https://github.com/bvaughn/react-resizable-panels)

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

    Maximum number of telemetry samples retained in visualizer history. Larger buffers preserve long-run context and make regression trend analysis easier, but cost more memory and increase render work for each frame. Smaller buffers keep UI responsiveness high and reduce browser/GPU pressure, but can hide earlier failure modes and make long-cycle debugging harder. Choose this alongside telemetry interval: frequent logging plus very large point caps can overload rendering, so prefer either light decimation or moderate caps for sustained real-time sessions.

    **Links**:
    - [AI-Assisted Adaptive Rendering for High-Frequency Security Telemetry in Web Interfaces (arXiv, 2026)](https://arxiv.org/abs/2602.01671)
    - [Chart.js Data Decimation](https://www.chartjs.org/docs/latest/configuration/decimation.html)
    - [MDN: Performance API](https://developer.mozilla.org/en-US/docs/Web/API/Performance_API)
    - [MDN: requestAnimationFrame](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame)

??? info "`ui.learning_reranker_visualizer_motion_intensity` (`LEARNING_RERANKER_VISUALIZER_MOTION_INTENSITY`) — Learning Reranker Visualizer Motion Intensity"
    **Category**: `reranking`

    Global multiplier for animation energy in the visualizer (camera drift, particle movement, transitions). Raising intensity can make state changes easier to notice in brief glances, but also increases motion load and may amplify distraction or simulator sickness for some users. Lower values reduce GPU demand and improve readability during metric-heavy debugging. Treat this as an ergonomics control, not just aesthetics: adjust based on session type (live monitoring vs deep analysis), user preference, and machine capability.

    **Links**:
    - [User-Autonomy Framework for Improving Accessibility in Dynamic Interfaces (arXiv, 2025)](https://arxiv.org/abs/2506.10324)
    - [MDN: prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
    - [web.dev: prefers-reduced-motion](https://web.dev/prefers-reduced-motion/)
    - [AI-Assisted Adaptive Rendering for High-Frequency Security Telemetry in Web Interfaces (arXiv, 2026)](https://arxiv.org/abs/2602.01671)

??? info "`ui.learning_reranker_visualizer_quality` (`LEARNING_RERANKER_VISUALIZER_QUALITY`) — Learning Reranker Visualizer Quality"
    **Category**: `reranking`

    Quality preset for the Neural Visualizer rendering pipeline (for example balanced, cinematic, ultra). Higher tiers usually increase shader complexity, sampling, and post-processing fidelity, which can improve visual clarity but consume more GPU time and reduce frame stability under load. Lower tiers trade visual polish for deterministic interaction and lower power use. Tune this based on objective: use high quality for demos or screenshots, and balanced/lower settings during prolonged optimization sessions where low-latency interaction matters more than effects.

    **Links**:
    - [WebSplatter: 3D Gaussian Splatting from an Image Pair for Scalable Rendering (arXiv, 2026)](https://arxiv.org/abs/2602.03207)
    - [MDN: WebGPU API](https://developer.mozilla.org/en-US/docs/Web/API/WebGPU_API)
    - [MDN: WebGL2RenderingContext](https://developer.mozilla.org/en-US/docs/Web/API/WebGL2RenderingContext)
    - [MDN: Canvas API](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API)

??? info "`ui.learning_reranker_visualizer_reduce_motion` (`LEARNING_RERANKER_VISUALIZER_REDUCE_MOTION`) — Learning Reranker Visualizer Reduce Motion"
    **Category**: `reranking`

    Accessibility-first switch that lowers or disables non-essential motion effects in the visualizer. With this enabled, transitions become calmer and less visually aggressive, which helps users sensitive to animation and can also reduce compute overhead on weaker devices. This should be treated as a functional comfort setting, not a cosmetic option. In most interfaces, the best behavior is to respect OS-level `prefers-reduced-motion` by default and let users override explicitly when they want richer motion.

    **Links**:
    - [Automated Accessibility Remediation for Web Interfaces via LLMs (arXiv, 2026)](https://arxiv.org/abs/2602.17887)
    - [User-Autonomy Framework for Improving Accessibility in Dynamic Interfaces (arXiv, 2025)](https://arxiv.org/abs/2506.10324)
    - [MDN: prefers-reduced-motion](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-reduced-motion)
    - [web.dev: prefers-reduced-motion](https://web.dev/prefers-reduced-motion/)

??? info "`ui.learning_reranker_visualizer_renderer` (`LEARNING_RERANKER_VISUALIZER_RENDERER`) — Learning Reranker Visualizer Renderer"
    **Category**: `reranking`

    Selects the rendering backend used by the visualizer (`auto`, `webgpu`, `webgl2`, or `canvas2d`). `auto` should be the default because runtime capability detection can choose the strongest stable backend on each machine. `webgpu` typically offers the best throughput and future-proof compute features on supported browsers. `webgl2` is a mature fallback with broad compatibility. `canvas2d` provides maximum reach but lowest rendering sophistication. Use explicit backend overrides mainly for debugging platform-specific rendering bugs or enforcing predictable behavior in controlled environments.

    **Links**:
    - [WebSplatter: 3D Gaussian Splatting from an Image Pair for Scalable Rendering (arXiv, 2026)](https://arxiv.org/abs/2602.03207)
    - [MDN: WebGPU API](https://developer.mozilla.org/en-US/docs/Web/API/WebGPU_API)
    - [MDN: WebGL2RenderingContext](https://developer.mozilla.org/en-US/docs/Web/API/WebGL2RenderingContext)
    - [MDN: Canvas API](https://developer.mozilla.org/en-US/docs/Web/API/Canvas_API)

??? info "`ui.learning_reranker_visualizer_show_vector_field` (`LEARNING_RERANKER_VISUALIZER_SHOW_VECTOR_FIELD`) — Learning Reranker Visualizer Show Vector Field"
    **Category**: `reranking`

    Toggles the vector-field overlay used to visualize local direction and intensity of motion in the reranker trajectory view. With this enabled, you can quickly see whether updates are converging smoothly, rotating around a basin, or oscillating in conflicting directions, which is useful when tuning learning rate and regularization. Disable it when you need maximum rendering throughput or a cleaner presentation for non-technical review. Treat this as a diagnostic rendering layer: it does not change model training, only how training dynamics are interpreted.

    **Links**:
    - [Time-Variant Vector Field Visualization on Sparse Trajectories (arXiv 2025)](https://arxiv.org/abs/2501.05084)
    - [Three.js ArrowHelper for Directional Vector Rendering](https://threejs.org/docs/#api/en/helpers/ArrowHelper)
    - [Matplotlib Quiver API for Vector-Field Plotting](https://matplotlib.org/stable/api/_as_gen/matplotlib.pyplot.quiver.html)
    - [PyVista Streamlines Example for Field-Flow Interpretation](https://docs.pyvista.org/examples/01-filter/streamlines.html)

??? info "`ui.learning_reranker_visualizer_tail_seconds` (`LEARNING_RERANKER_VISUALIZER_TAIL_SECONDS`) — Learning Reranker Visualizer: Tail Seconds"
    **Category**: `reranking`

    Defines how much recent history is retained in live trajectory playback, expressed as seconds of visual tail. A shorter tail emphasizes immediate motion and makes rapid shifts easier to see, while a longer tail preserves context and makes drift patterns easier to diagnose over time. If this is too small, users may misinterpret stable long-term movement as abrupt noise; if too large, the display can become visually dense and harder to parse at speed. Tune this together with target FPS so temporal context and animation smoothness stay balanced on your hardware.

    **Badges**:
    - Live playback only
    - Visualization policy

    **Links**:
    - [Animated-LLM: Temporal Coherence and Motion Readability (arXiv 2026)](https://arxiv.org/abs/2601.04213)
    - [Matplotlib Blitting: High-Performance Animation Tradeoffs](https://matplotlib.org/stable/users/explain/animations/blitting.html)
    - [MDN requestAnimationFrame Timing Model](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame)
    - [TensorBoard Scalars for Long-Run Signal Monitoring](https://www.tensorflow.org/tensorboard/scalars_and_keras)

??? info "`ui.learning_reranker_visualizer_target_fps` (`LEARNING_RERANKER_VISUALIZER_TARGET_FPS`) — Learning Reranker Visualizer Target FPS"
    **Category**: `reranking`

    Sets the visualizer's target frame rate for animation updates. Higher FPS improves motion smoothness and makes subtle directional changes easier to perceive, but increases GPU/CPU pressure and can reduce responsiveness on constrained machines. Lower FPS is often preferable for remote sessions, multi-monitor setups, or long diagnostics where thermal and fan limits matter. This parameter only affects rendering cadence, not training quality or optimization math, so tune it for operator comfort and stable observability.

    **Links**:
    - [Animated-LLM: Real-Time Render Cadence in LLM Visual Systems (arXiv 2026)](https://arxiv.org/abs/2601.04213)
    - [MDN requestAnimationFrame Best Practices](https://developer.mozilla.org/en-US/docs/Web/API/Window/requestAnimationFrame)
    - [Three.js setAnimationLoop for Frame Scheduling](https://threejs.org/docs/#api/en/renderers/WebGLRenderer.setAnimationLoop)
    - [Chrome DevTools Performance Panel](https://developer.chrome.com/docs/devtools/performance/)

??? info "`ui.open_browser` (`OPEN_BROWSER`) — Auto-Open Browser"
    **Category**: `general`

    Controls whether Crucible automatically launches a browser tab when the local server starts. It improves developer ergonomics in interactive desktop workflows, but should normally be disabled for CI, SSH sessions, containers, and remote hosts where GUI launch attempts are noisy or impossible. Keep this off in production-like startup scripts to avoid side effects and process-blocking behavior. In short: enable for local convenience, disable for automation and infrastructure.

    **Links**:
    - [WebSailor-V2: Browser Agent Scaling (arXiv 2026)](https://arxiv.org/abs/2601.07262)
    - [Vite server.open Option](https://vite.dev/config/server-options.html#server-open)
    - [Playwright BrowserType API](https://playwright.dev/docs/api/class-browsertype)
    - [open (Node package) Repository](https://github.com/sindresorhus/open)

??? info "`ui.theme_mode` (`THEME_MODE`) — GUI Theme"
    **Category**: `ui`

    Controls the interface color system used by the app (`light`, `dark`, or `auto`). In `auto`, the UI should track OS/browser preference (`prefers-color-scheme`) and apply color tokens before first paint to avoid flash-of-incorrect-theme. This setting is not just aesthetic: it affects readability, contrast compliance, and operator fatigue during long debugging sessions. In production, pair theme switching with contrast checks so status badges, charts, and alert colors remain distinguishable in both modes.

    **Links**:
    - [Predicting Human Color Preferences Through LLMs (arXiv 2025)](https://arxiv.org/abs/2512.00516)
    - [MDN: prefers-color-scheme](https://developer.mozilla.org/en-US/docs/Web/CSS/@media/prefers-color-scheme)
    - [MDN: color-scheme](https://developer.mozilla.org/en-US/docs/Web/CSS/color-scheme)
    - [WCAG 2.2: Contrast (Minimum)](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)
