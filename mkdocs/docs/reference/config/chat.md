# Config reference: `chat`

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

**Total parameters**: 70

??? info "Group index"
    - `(root)`
    - `benchmark`
    - `image_gen`
    - `litellm`
    - `multimodal`
    - `recall`
    - `recall_gate`
    - `vllm`
    - `web`

## `(root)`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.default_corpus_ids` | — | `list[str]` | `["recall_default"]` | — | Default checked user-facing corpus IDs for new conversations. |
| `chat.max_tokens` | — | `int` | `512` | ≥ 100, ≤ 16384 | — |
| `chat.send_shortcut` | — | `str` | `"ctrl+enter"` | — | — |
| `chat.show_source_dropdown` | — | `bool` | `true` | — | — |
| `chat.system_prompt_base` | — | `str` | `"You are a helpful assistant."` | — | — |
| `chat.system_prompt_direct` | — | `str` | `"You are a helpful agentic RAG database assistant.\n\nThe user is chatting directly without any retrieval context. No database repositories or conversation history are being queried for this message.\n\nAnswer based on your general knowledge. If the user asks about their specific database and no context is provided, let them know they can enable RAG corpora in the Data Sources panel to query their indexed repositories.\n\nBe direct and helpful."` | — | State 1: No context. Nothing checked or retrieval returned empty. |
| `chat.system_prompt_rag` | — | `str` | `"You are a database assistant powered by TriBridRAG, a hybrid retrieval system that combines vector search, keyword search, and knowledge graphs to find relevant database.\n\nThe user has selected one or more database repositories to query. You will receive relevant database snippets in <rag_context>...</rag_context> tags.\n\nEach snippet includes:\n- File path and line numbers\n\nHow to use this context:\n- Base your answers on the actual database shown, not assumptions\n- Always cite file paths and line numbers when referencing database\n- If the retrieved information doesn't fully answer the question, say what's missing\n- Don't invent information that isn't in the context\n- **Connect related pieces when they appear across multiple snippets** (e.g. if the user asks about a specific database table, and you have information about the table in the context, connect the information to the question)\n\nBe helpful, friendly, and engaging, and base your answers on the actual database information you have."` | — | State 2: RAG only. Code corpora returned results; Recall did not. |
| `chat.system_prompt_rag_and_recall` | — | `str` | `"You are an agentic RAG database assistant powered by TriBridRAG, a hybrid retrieval system. You have access to both:\n1) The user's indexed database repositories\n2) Your conversation history with this user (Recall)\n\ndatabase context appears in <rag_context>...</rag_context> tags.\nConversation history appears in <recall_context>...</recall_context> tags.\n\nHow to use both:\n- Reference past discussions naturally\n- Connect them when relevant (e.g., a past decision and the database information that implements it)\n- If past context contradicts current database information, acknowledge the change\n- Don't say \"according to recall\" — just incorporate shared knowledge naturally\n\nBe helpful, friendly, and engaging, and base your answers on the actual database information you have."` | — | State 4: Both. RAG and Recall both returned results. |
| `chat.system_prompt_rag_suffix` | — | `str` | `" Answer questions using the provided database information."` | — | — |
| `chat.system_prompt_recall` | — | `str` | `"You are an agentic RAG database assistant powered by TriBridRAG. You have access to your conversation history with this user via the Recall system.\n\nRelevant snippets from past conversations appear in <recall_context>...</recall_context> tags.\n\nEach snippet includes:\n- Who said it (user or assistant)\n- Timestamp\n- The message content\n\nHow to use this context:\n- Reference past discussions naturally\n- Don't explicitly say \"according to my recall\" — incorporate it as shared context\n- Past conversations may contain decisions, preferences, or context that inform the current question\n- Prioritize recent conversations over older ones when relevant\n\nBe direct and helpful. You're continuing an ongoing collaboration with this user."` | — | State 3: Recall only. Recall returned results; no RAG corpora active. |
| `chat.system_prompt_recall_suffix` | — | `str` | `" You have access to conversation history. Reference past discussions when relevant."` | — | — |
| `chat.temperature` | — | `float` | `0.3` | ≥ 0.0, ≤ 2.0 | — |
| `chat.temperature_no_retrieval` | — | `float` | `0.7` | ≥ 0.0, ≤ 2.0 | Temperature when nothing is checked (direct chat = more creative) |

## `benchmark`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.benchmark.enabled` | — | `bool` | `true` | — | — |
| `chat.benchmark.include_cost_tracking` | — | `bool` | `true` | — | — |
| `chat.benchmark.include_timing_breakdown` | — | `bool` | `true` | — | — |
| `chat.benchmark.max_concurrent_models` | — | `int` | `4` | ≥ 2, ≤ 8 | — |
| `chat.benchmark.results_path` | — | `str` | `"data/benchmarks/"` | — | — |
| `chat.benchmark.save_results` | — | `bool` | `true` | — | — |

## `image_gen`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.image_gen.comfyui_api_endpoint` | — | `str` | `""` | — | — |
| `chat.image_gen.default_resolution` | — | `str` | `"1024x1024"` | — | — |
| `chat.image_gen.default_steps` | — | `int` | `8` | ≥ 1, ≤ 50 | — |
| `chat.image_gen.enabled` | — | `bool` | `false` | — | — |
| `chat.image_gen.local_command` | — | `str` | `"python -m qwen_image.generate"` | — | CLI command. Receives --prompt, --output, --steps, --width, --height. |
| `chat.image_gen.local_model_path` | — | `str` | `""` | — | — |
| `chat.image_gen.provider` | — | `str` | `"local"` | pattern=^(local\|openai\|comfyui_api\|replicate)$ | — |
| `chat.image_gen.replicate_model` | — | `str` | `""` | — | — |
| `chat.image_gen.use_lightning_lora` | — | `bool` | `true` | — | — |

## `litellm`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.litellm.base_url` | — | `str` | `"http://127.0.0.1:54000/v1"` | — | — |
| `chat.litellm.default_model` | — | `str` | `"ragweld-local"` | — | — |
| `chat.litellm.enabled` | — | `bool` | `true` | — | — |

## `multimodal`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.multimodal.image_detail` | — | `str` | `"auto"` | pattern=^(auto\|low\|high)$ | OpenAI vision detail level. |
| `chat.multimodal.max_image_size_mb` | — | `int` | `20` | ≥ 1, ≤ 50 | — |
| `chat.multimodal.max_images_per_message` | — | `int` | `5` | ≥ 1, ≤ 10 | — |
| `chat.multimodal.supported_formats` | — | `list[str]` | `["png", "jpg", "jpeg", "gif", "webp"]` | — | — |
| `chat.multimodal.vision_enabled` | — | `bool` | `true` | — | — |
| `chat.multimodal.vision_model_override` | — | `str` | `""` | — | Force model for vision. Empty=use chat model if it supports vision. |

## `recall`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.recall.auto_index` | — | `bool` | `true` | — | — |
| `chat.recall.chunk_max_tokens` | — | `int` | `256` | ≥ 64, ≤ 1024 | Chat chunks should be smaller than code chunks. |
| `chat.recall.chunking_strategy` | — | `str` | `"sentence"` | pattern=^(sentence\|paragraph\|turn\|fixed)$ | 'turn'=one chunk per message, 'sentence'=split by sentence. |
| `chat.recall.corpus_root` | — | `str` | `"data/recall"` | — | Directory a recall corpus is created under, one subdirectory per corpus id. Relative values resolve against the project root; RAGWELD_RECALL_ROOT overrides it for disposable lanes. Only consulted when the corpus is created - after that the registry row's path is authoritative, so every process agrees. |
| `chat.recall.default_corpus_id` | — | `str` | `"recall_default"` | — | Auto-created at first launch. Users never touch this. |
| `chat.recall.embedding_model` | — | `str` | `""` | — | Override embedding model. Empty=use global config. |
| `chat.recall.enabled` | — | `bool` | `true` | — | Enable Recall. ON by default. |
| `chat.recall.graph_enabled` | — | `bool` | `false` | — | Enable Recall graph indexing + retrieval (experimental). |
| `chat.recall.index_delay_seconds` | — | `int` | `5` | ≥ 1, ≤ 60 | — |
| `chat.recall.max_history_tokens` | — | `int` | `4096` | ≥ 512, ≤ 32768 | — |

## `recall_gate`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.recall_gate.deep_on_explicit_reference` | — | `bool` | `true` | — | Trigger deep when message explicitly references past conversation. |
| `chat.recall_gate.deep_recency_weight` | — | `float` | `0.5` | ≥ 0.0, ≤ 1.0 | recency_weight for deep (higher when user explicitly asks about the past). |
| `chat.recall_gate.deep_top_k` | — | `int` | `10` | ≥ 3, ≤ 30 | top_k when intensity=deep. |
| `chat.recall_gate.default_intensity` | — | `RecallIntensity` | `"standard"` | — | Fallback when classifier is uncertain. |
| `chat.recall_gate.enabled` | — | `bool` | `true` | — | Enable smart gating. False=always query Recall when checked. |
| `chat.recall_gate.light_for_short_questions` | — | `bool` | `true` | — | Use sparse-only for short questions (< 10 tokens) without explicit recall triggers. |
| `chat.recall_gate.light_top_k` | — | `int` | `3` | ≥ 1, ≤ 10 | top_k when intensity=light. |
| `chat.recall_gate.show_gate_decision` | — | `bool` | `true` | — | Show gate decision (intensity, reason) in status bar. |
| `chat.recall_gate.show_signals` | — | `bool` | `false` | — | Show raw RecallSignals in debug footer (dev mode). |
| `chat.recall_gate.skip_greetings` | — | `bool` | `true` | — | Skip Recall for greetings, farewells, acknowledgments. |
| `chat.recall_gate.skip_max_tokens` | — | `int` | `4` | ≥ 1, ≤ 20 | Messages with ≤ this many tokens are skip candidates (only if they match a skip pattern). |
| `chat.recall_gate.skip_standalone_questions` | — | `bool` | `true` | — | Skip Recall for questions that don't reference past context. 'How does auth work?' doesn't need chat history. |
| `chat.recall_gate.skip_when_rag_active` | — | `bool` | `false` | — | Skip Recall when RAG corpora are checked. Assumes user wants code context, not chat history. Default False — let both contribute. |
| `chat.recall_gate.standard_recency_weight` | — | `float` | `0.3` | ≥ 0.0, ≤ 1.0 | Default recency weight for Recall (recent messages often more relevant). |
| `chat.recall_gate.standard_top_k` | — | `int` | `5` | ≥ 1, ≤ 20 | top_k for standard Recall queries. |

## `vllm`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.vllm.base_url` | — | `str` | `"http://127.0.0.1:58080/v1"` | — | — |
| `chat.vllm.default_model` | — | `str` | `"mlx-community/Qwen3.8-27B-4bit"` | — | — |
| `chat.vllm.enabled` | — | `bool` | `true` | — | — |

## `web`

| JSON key | Env key(s) | Type | Default | Constraints | Summary |
|---------|------------|------|---------|-------------|---------|
| `chat.web.enabled` | — | `bool` | `true` | — | Allow opt-in web search in Chat. |
| `chat.web.engine` | — | `Literal["auto", "native", "exa"]` | `"auto"` | allowed="auto", "native", "exa" | — |
| `chat.web.max_characters` | — | `int` | `12000` | ≥ 1000, ≤ 50000 | — |
| `chat.web.max_results` | — | `int` | `5` | ≥ 1, ≤ 20 | — |
| `chat.web.max_total_results` | — | `int` | `5` | ≥ 1, ≤ 20 | — |
