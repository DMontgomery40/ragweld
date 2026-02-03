// GUI Tooltips: human-readable help + accurate links
// Legacy tooltip definitions (migrated away from window globals)
const LegacyTooltips = (function(){
  /**
   * ---agentspec
   * what: |
   *   Renders labeled tooltip HTML with optional badges and links. Inputs: label, body, links array, badges array. Outputs: formatted HTML string.
   *
   * why: |
   *   Centralizes tooltip markup generation to avoid duplication across UI components.
   *
   * guardrails:
   *   - DO NOT sanitize HTML; caller responsible for XSS prevention
   *   - NOTE: Links open in new tab with noopener; badges use optional CSS class
   * ---/agentspec
   */
  function L(label, body, links, badges){
    const linkHtml = (links||[]).map(([txt, href]) => `<a href="${href}" target="_blank" rel="noopener">${txt}</a>`).join(' ');
    const badgeHtml = (badges||[]).map(([txt, cls]) => `<span class="tt-badge ${cls||''}">${txt}</span>`).join(' ');
    const badgesBlock = badgeHtml ? `<div class="tt-badges">${badgeHtml}</div>` : '';
    return `<span class=\"tt-title\">${label}</span>${badgesBlock}<div>${body}</div>` + (links && links.length ? `<div class=\"tt-links\">${linkHtml}</div>` : '');
  }

  /**
   * ---agentspec
   * what: |
   *   Builds tooltip metadata map for infrastructure config keys (QDRANT_URL, REDIS_URL, etc.). Returns object with descriptions, fallback behavior, and reference links.
   *
   * why: |
   *   Centralizes UI hints and dependency docs to avoid duplication and keep config help in sync.
   *
   * guardrails:
   *   - DO NOT assume external services are required; document graceful degradation (BM25 fallback, stateless mode)
   *   - NOTE: Links must stay current; stale URLs break user navigation
   * ---/agentspec
   */
  function buildTooltipMap(){
    return {
      // -------------------------------------------------------------------
      // Dashboard: System Status (live, clickable chips)
      // -------------------------------------------------------------------

      SYS_STATUS_CORPUS: L(
        'Corpora (active selection)',
        'A <span class="tt-strong">corpus</span> is TriBridRAG’s unit of isolation: each corpus has its own indexing storage (Postgres), graph storage (Neo4j), and per-corpus configuration.'
          + '<br><br>'
          + 'This System Status row shows the <span class="tt-strong">active corpus</span> and the <span class="tt-strong">total number of corpora</span> registered in this TriBridRAG instance.'
          + '<br><br>'
          + '<span class="tt-strong">Selection precedence</span> (highest → lowest):'
          + '<br>1) URL query param <span class="mono">?corpus=</span> (or legacy <span class="mono">?repo=</span>)'
          + '<br>2) Browser localStorage <span class="mono">tribrid_active_corpus</span>'
          + '<br>3) First corpus in the registry'
          + '<br><br>'
          + 'Compatibility note: some API fields still use <span class="mono">repo_id</span> as the identifier, but it means <span class="tt-strong">corpus_id</span>.',
        [
          ['Corpus guide', '/docs/guides/corpus.md'],
          ['Glossary', '/docs/glossary.md']
        ],
        [['Core concept', 'info']]
      ),

      SYS_STATUS_CONTAINERS: L(
        'Containers (running/total)',
        'Shows Docker container health for <span class="tt-strong">this TriBridRAG stack</span> as <span class="mono">running/total</span>.'
          + '<br><br>'
          + '<span class="tt-strong">running</span>: containers whose state is <span class="mono">running</span>'
          + '<br>'
          + '<span class="tt-strong">total</span>: all containers in the TriBridRAG docker-compose project (including stopped/exited)'
          + '<br><br>'
          + 'This intentionally excludes unrelated containers on your machine. Internally we identify TriBrid-managed containers via Docker Compose labels (<span class="mono">com.docker.compose.project</span>) and/or the <span class="mono">tribrid-*</span> container name prefix.'
          + '<br><br>'
          + '<span class="tt-strong">Tip:</span> click the chip to open <span class="tt-strong">Infrastructure → Docker</span> for full container management and logs.',
        [
          ['Docker Compose docs', 'https://docs.docker.com/compose/'],
          ['Deployment guide', '/docs/deployment.md']
        ],
        [['Operational', 'info']]
      ),

      SYS_STATUS_MCP_SERVERS: L(
        'MCP transports (stdio/HTTP)',
        'MCP (Model Context Protocol) lets external clients (IDEs, agents, automation) call TriBridRAG tools in a standardized way.'
          + '<br><br>'
          + 'This System Status chip lists which <span class="tt-strong">inbound MCP transports</span> are available right now:'
          + '<br>'
          + '- <span class="mono">py-stdio</span>: Python stdio transport. This is typically <span class="tt-strong">client-spawned</span> (no always-on server). “available” means the required Python MCP runtime is installed and can be launched by an MCP client.'
          + '<br>'
          + '- <span class="mono">py-http</span> / <span class="mono">node-http</span>: future HTTP transports (will show host/port and running state when implemented).'
          + '<br><br>'
          + '<span class="tt-strong">Tip:</span> click the chip to open <span class="tt-strong">Infrastructure → MCP Servers</span> for detailed status and setup guidance.',
        [
          ['MCP specification', 'https://github.com/modelcontextprotocol/specification'],
          ['MCP overview', 'https://modelcontextprotocol.io']
        ],
        [['Integration', 'info']]
      ),

      DEV_STACK_CLEAR_PYTHON_BYTECODE: L(
        'Clear Python bytecode caches',
        'Clears <span class="tt-strong">Python bytecode caches</span> inside this repo and then triggers a backend reload.'
          + '<br><br>'
          + '<span class="tt-strong">What it deletes</span> (repo-owned only):'
          + '<br>- <span class="mono">__pycache__/</span> directories'
          + '<br>- <span class="mono">*.pyc</span> files'
          + '<br><br>'
          + '<span class="tt-strong">Where</span>: <span class="mono">server/</span>, <span class="mono">tests/</span>, <span class="mono">scripts/</span>'
          + '<br><br>'
          + '<span class="tt-strong">What it does NOT delete</span>: your <span class="mono">.venv</span> / uv / pip caches, Docker images/volumes, Postgres/Neo4j data, or model files under <span class="mono">models/</span>.'
          + '<br><br>'
          + '<span class="tt-strong">Expected consequences</span>: backend reload (brief interruption) and a slightly slower first request after reload due to re-import/compile.'
          + '<br><br>'
          + 'Use this when you suspect stale bytecode after refactors or aggressive file watching — not as routine maintenance.',
        [
          ['Python bytecode docs', 'https://docs.python.org/3/library/importlib.html#bytecode-cache']
        ],
        [['Safe', 'ok']]
      ),

      // Infrastructure & routing
      QDRANT_URL: L('Qdrant URL', 'HTTP URL for your Qdrant vector database. Used for dense vector queries during retrieval. If unavailable, retrieval still works via BM25 (sparse).', [
        ['Qdrant Docs: Collections', 'https://qdrant.tech/documentation/concepts/collections/'],
        ['Qdrant (GitHub)', 'https://github.com/qdrant/qdrant']
      ]),
      REDIS_URL: L('Redis URL', 'Connection string for Redis, used for LangGraph checkpoints and optional session memory. The graph runs even if Redis is down (stateless mode).', [
        ['Redis Docs', 'https://redis.io/docs/latest/'],
        ['LangGraph Checkpoints', 'https://langchain-ai.github.io/langgraph/concepts/persistence/'],
        ['Redis Connection URLs', 'https://redis.io/docs/latest/develop/connect/clients/']
      ]),
      REPO: L('Active Repository', 'Logical repository name for routing and indexing. MCP and CLI use this to scope retrieval. Must match a repository name defined in repos.json for multi-repo setups. Example: "tribrid-demo", "myapp", "cli-tool". Used for multi-repo RAG systems where each repo has separate indices, keywords, and path boosts.', [
        ['Namespace Concept', 'https://en.wikipedia.org/wiki/Namespace'],
        ['MCP Protocol Spec', 'https://github.com/modelcontextprotocol/specification'],
        ['LangSmith Context', 'https://www.langchain.com/langsmith']
      ]),
      COLLECTION_NAME: L('Collection Name', 'Optional override for the Qdrant collection name where vectors are stored. Defaults to code_chunks_{REPO}. Set this if you maintain multiple profiles, A/B test embedding models, or run parallel indexing. Must be lowercase alphanumeric + underscore. Examples: code_chunks_v2, vectors_staging, embeddings_prod', [
        ['Qdrant Collections Intro', 'https://qdrant.tech/documentation/concepts/collections/'],
        ['Create Collections', 'https://qdrant.tech/documentation/concepts/collections/#create-collection'],
        ['Database Collections', 'https://en.wikipedia.org/wiki/Database_collection']
      ]),
      COLLECTION_SUFFIX: L(
        'Collection Suffix',
        'Optional string appended to the default collection name (code_chunks_{REPO}) for A/B testing different indexing strategies. For example, suffix "_v2" creates "code_chunks_myrepo_v2". Useful when comparing embedding models, chunking strategies, or reranking approaches without overwriting your production index. Leave empty for default collection.',
        [
          ['Qdrant Collections', 'https://qdrant.tech/documentation/concepts/collections/'],
          ['Collection Management', 'https://qdrant.tech/documentation/concepts/collections/#create-collection'],
          ['Collection Naming', 'https://qdrant.tech/documentation/concepts/collections/#collection-name']
        ],
        [['Experimental', 'warn']]
      ),
      REPOS_FILE: L('Repos File', 'Path to repos.json that defines repo names, paths, keywords, path boosts, and layer bonuses used for multi-repo routing. Each repo entry includes name, path, optional keywords for boosting, path_boosts for directory-specific relevance, and layer_bonuses for hierarchical retrieval.', [
        ['JSON Format Reference', 'https://www.json.org/json-en.html'],
        ['Configuration Management', 'https://github.com/topics/configuration-management'],
        ['Config File Concepts', 'https://en.wikipedia.org/wiki/Configuration_file']
      ]),
      REPO_PATH: L(
        'Repo Path (fallback)',
        'Absolute filesystem path to the active repository when repos.json is not configured. This is the directory that will be indexed for code retrieval. Use repos.json instead for multi-repo setups with routing, keywords, and path boosts. Example: /Users/you/projects/myapp or /home/user/code/myrepo',
        [
          ['Path Patterns', 'https://github.com/github/gitignore'],
          ['Python pathlib Module', 'https://docs.python.org/3/library/pathlib.html'],
          ['File System Paths', 'https://en.wikipedia.org/wiki/Path_(computing)']
        ]
      ),
      OUT_DIR_BASE: L('Out Dir Base', 'Where retrieval looks for indices (chunks.jsonl, bm25_index/). Use ./out.noindex-shared for one index across branches so MCP and local tools stay in sync. Stores dense vectors (Qdrant), sparse BM25 index, and indexed chunks. Symptom of mismatch: rag_search returns 0 results.', [
        ['Directory Concepts', 'https://en.wikipedia.org/wiki/Directory_(computing)'],
        ['MCP Protocol Spec', 'https://github.com/modelcontextprotocol/specification'],
        ['Storage Management', 'https://qdrant.tech/documentation/concepts/storage/']
      ], [['Requires restart (MCP)','info']]),
      RAG_OUT_BASE: L(
        'RAG Out Base',
        'Optional override for OUT_DIR_BASE for retrieval-specific output directory. Advanced users can use this to separate indexing output from retrieval search indices while keeping OUT_DIR_BASE for main indexing. Most users should leave empty—use OUT_DIR_BASE only. Primarily for multi-environment setups needing separate retrieval and indexing directories.',
        [
          ['Configuration Management', 'https://12factor.net/config'],
          ['Storage Concepts', 'https://qdrant.tech/documentation/concepts/storage/'],
          ['BM25 Index Storage', 'https://github.com/BM25S/bm25s']
        ],
        [['Advanced', 'warn']]
      ),
      MCP_HTTP_HOST: L('MCP HTTP Host', 'Bind address for the HTTP MCP server (fast transport). Use 0.0.0.0 to listen on all interfaces, 127.0.0.1 for localhost only, or a specific IP like 192.168.1.100 for LAN access. MCP (Model Context Protocol) enables fast communication between clients and the RAG engine.', [
        ['HTTP Host Header Reference', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Host'],
        ['Localhost Concept', 'https://en.wikipedia.org/wiki/Localhost'],
        ['MCP Specification', 'https://github.com/modelcontextprotocol/specification']
      ]),
      MCP_HTTP_PORT: L('MCP HTTP Port', 'TCP port for HTTP MCP server (default 8013). Must not conflict with other services. Use ports 1024+ without special permissions. MCP enables fast, stateless communication for multi-client scenarios.', [
        ['Port Numbers', 'https://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers'],
        ['HTTP Basics', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Basics_of_HTTP'],
        ['MCP Specification', 'https://github.com/modelcontextprotocol/specification']
      ]),
      MCP_HTTP_PATH: L('MCP HTTP Path', 'URL path for the HTTP MCP endpoint (default /mcp). Example: http://localhost:8013/mcp. Customize for reverse proxies or routing needs. Must match client configuration if changed.', [
        ['URL Structure', 'https://developer.mozilla.org/en-US/docs/Learn/Common_questions/Web_mechanics/What_is_a_URL'],
        ['URI Standard', 'https://en.wikipedia.org/wiki/Uniform_Resource_Identifier'],
        ['MCP Specification', 'https://github.com/modelcontextprotocol/specification']
      ]),
      HOST: L(
        'Server Host',
        'Network interface for the HTTP server to bind to when running serve_rag. Use 0.0.0.0 for all interfaces (accessible from network), 127.0.0.1 for localhost only (secure, dev mode).',
        [
          ['Network Interfaces', 'https://en.wikipedia.org/wiki/Network_interface'],
          ['Localhost vs 0.0.0.0', 'https://stackoverflow.com/questions/20778771/what-is-the-difference-between-0-0-0-0-127-0-0-1-and-localhost']
        ]
      ),
      DATA_DIR: L(
        'Data Directory',
        'Base directory for application data storage (logs, tracking, temp files). Defaults to ./data. Change if you need data stored elsewhere or shared across deployments.',
        [
          ['Directory Structure', 'https://en.wikipedia.org/wiki/Directory_structure']
        ]
      ),
      THEME_MODE: L(
        'GUI Theme',
        'Color theme for web GUI. Options: "light" (light mode), "dark" (dark mode), "auto" (follows system preference). Changes appearance immediately when toggled.',
        [
          ['Dark Mode Benefits', 'https://en.wikipedia.org/wiki/Light-on-dark_color_scheme']
        ]
      ),
      OPEN_BROWSER: L(
        'Auto-Open Browser',
        'Automatically open browser to GUI when server starts (1=yes, 0=no). Convenient for local development, disable for server deployments or headless environments.',
        [
          ['Browser Automation', 'https://en.wikipedia.org/wiki/Browser_automation']
        ]
      ),
      AUTO_COLIMA: L(
        'Auto-Start Colima',
        'Automatically start Colima Docker runtime if not running (macOS only, 1=yes, 0=no). Convenient for local development, ensures Docker containers start without manual intervention.',
        [
          ['Colima', 'https://github.com/abiosoft/colima']
        ]
      ),
      COLIMA_PROFILE: L(
        'Colima Profile',
        'Colima profile name to use when AUTO_COLIMA is enabled. Profiles allow different Docker VM configurations (CPU, memory, disk). Default profile used if empty.',
        [
          ['Colima Profiles', 'https://github.com/abiosoft/colima#profile']
        ]
      ),
      DEV_LOCAL_UVICORN: L(
        'Dev Local Uvicorn',
        'Run Uvicorn ASGI server in direct Python mode instead of Docker for faster development iteration (1=yes, 0=no). Enables hot-reload and easier debugging. Production should use 0 (Docker).',
        [
          ['Uvicorn', 'https://www.uvicorn.org/']
        ]
      ),

      // Code Editor Integration
      EDITOR_ENABLED: L(
        'Editor Enabled',
        'Enable embedded code editor integration in GUI (1=yes, 0=no). Allows viewing and editing code snippets from retrieval results directly in browser.',
        [
          ['Code Editor Integration', 'https://en.wikipedia.org/wiki/Source-code_editor']
        ]
      ),
      EDITOR_PORT: L(
        'Editor Port',
        'TCP port for code editor service. Default: varies by editor. Must not conflict with other services (PORT, MCP_HTTP_PORT, PROMETHEUS_PORT).',
        [
          ['Port Configuration', 'https://en.wikipedia.org/wiki/Port_(computer_networking)']
        ]
      ),
      EDITOR_BIND: L(
        'Editor Bind Address',
        'Network interface for editor service to bind to. Use 127.0.0.1 for localhost-only access (secure), 0.0.0.0 for network access (enable remote editing).',
        [
          ['Network Binding', 'https://en.wikipedia.org/wiki/Network_socket']
        ]
      ),
      EDITOR_EMBED_ENABLED: L(
        'Editor Embed Mode',
        'Enable embedded editor iframe in GUI (1=yes, 0=no). When enabled, editor opens inline. When disabled, opens in new tab/window. Embedding requires CORS configuration.',
        [
          ['iframe Embedding', 'https://developer.mozilla.org/en-US/docs/Web/HTML/Element/iframe']
        ]
      ),

      // Models / Providers
      GEN_MODEL: L('Generation Model', 'Answer model. Local: qwen3-coder:14b via Ollama. Cloud: gpt-4o-mini, etc. Larger models cost more and can be slower; smaller ones are faster/cheaper.', [
        ['OpenAI Models', 'https://platform.openai.com/docs/models'],
        ['Ollama API (GitHub)', 'https://github.com/ollama/ollama/blob/main/docs/api.md']
      ], [['Affects latency','info']]),
      OLLAMA_URL: L('Ollama URL', 'Local inference endpoint for Ollama running on your machine (e.g., http://127.0.0.1:11434/api). Used when GEN_MODEL targets a local model like llama2, mistral, qwen, or neural-chat. Requires Ollama installed and running: ollama serve', [
        ['Ollama REST API', 'https://github.com/ollama/ollama/blob/main/docs/api.md'],
        ['Ollama Docker Setup', 'https://ollama.com/blog/ollama-is-now-available-as-an-official-docker-image'],
        ['Ollama Model Library', 'https://ollama.com/library']
      ]),
      OPENAI_API_KEY: L('OpenAI API Key', 'API key used for OpenAI-based embeddings and/or generation.', [
        ['OpenAI: API Keys', 'https://platform.openai.com/docs/quickstart/step-2-set-up-your-api-key'],
        ['OpenAI Models', 'https://platform.openai.com/docs/models']
      ]),
      EMBEDDING_TYPE: L('Embedding Provider', 'Selects the embedding provider for dense vector search. Also determines the token counter used during code chunking, which affects chunk boundaries and splitting behavior.\n\n• openai — strong quality, paid (cl100k tokenizer)\n• voyage — strong retrieval, paid (voyage tokenizer)\n• mxbai — OSS via SentenceTransformers\n• local — any HuggingFace SentenceTransformer model\n• gemini — Google Gemini embeddings\n\nNote: Changing this setting affects both retrieval quality AND how code is split into chunks during indexing. A reindex is required after changing.', [
        ['OpenAI Embeddings', 'https://platform.openai.com/docs/guides/embeddings'],
        ['Voyage AI Embeddings', 'https://docs.voyageai.com/docs/embeddings'],
        ['Google Gemini Embeddings', 'https://ai.google.dev/gemini-api/docs/embeddings'],
        ['SentenceTransformers Docs', 'https://www.sbert.net/']
      ], [['Requires reindex','reindex'], ['Affects chunking','info']]),
      VOYAGE_API_KEY: L('Voyage API Key', 'API key for Voyage AI embeddings when EMBEDDING_TYPE=voyage.', [
        ['Voyage AI Docs', 'https://docs.voyageai.com/']
      ]),
      VOYAGE_EMBED_DIM: L('Voyage Embed Dim', 'Embedding vector dimension when using Voyage embeddings (provider‑specific). Larger dims can improve recall but increase Qdrant storage. Must match the output dimension of your chosen Voyage model (e.g., voyage-code-2 uses 1536 dims).', [
        ['Voyage Embeddings API', 'https://docs.voyageai.com/docs/embeddings'],
        ['Vector Dimensionality', 'https://www.sbert.net/docs/pretrained_models.html#model-overview'],
        ['Qdrant Storage Config', 'https://qdrant.tech/documentation/concepts/collections/']
      ], [['Requires reindex','reindex']]),

      // Reranking
      RERANK_BACKEND: L('Rerank Backend', 'Reranks fused candidates for better ordering.\n• cohere — best quality, paid (COHERE_API_KEY)\n• local/hf — no cost (ensure model installed)\nDisable only to save cost.', [
        ['Cohere Docs: Rerank', 'https://docs.cohere.com/reference/rerank'],
        ['Cohere Python (GitHub)', 'https://github.com/cohere-ai/cohere-python']
      ]),
      COHERE_API_KEY: L('Cohere API Key', 'API key for Cohere reranking when RERANK_BACKEND=cohere.', [
        ['Cohere Dashboard: API Keys', 'https://dashboard.cohere.com/api-keys']
      ]),
      COHERE_RERANK_MODEL: L('Cohere Rerank Model', 'Cohere rerank model name (e.g., rerank-3.5). Check the provider docs for the latest list and pricing.', [
        ['Cohere Docs: Models', 'https://docs.cohere.com/docs/models']
      ]),

      // Unified Reranker Configuration (4 modes)
      RERANKER_MODE: L(
        'Reranker Mode',
        'Controls which reranking approach is used. Four options:\n\n• none: Disabled—BM25 + vector fusion only, no cross-encoder scoring.\n• local: Any local reranker model you provide (BGE, Jina, etc.).\n• learning: TriBridRAG self-training cross-encoder that improves with your usage patterns.\n• cloud: External API reranking (Cohere, Voyage, Jina).\n\nRecommended: Start with "learning" to leverage TriBridRAG\'s adaptive improvements, or "cloud" for lowest latency if you have API budget.',
        [
          ['Cross-Encoder Overview', 'https://www.sbert.net/examples/applications/cross-encoder/README.html'],
          ['Learning Reranker Docs', '/docs/LEARNING_RERANKER.md']
        ],
        [['Controls reranking behavior', 'info']]
      ),
      RERANKER_CLOUD_PROVIDER: L(
        'Cloud Rerank Provider',
        'When RERANKER_MODE=cloud, specifies which API provider to use for reranking. Options: cohere, voyage, jina. Each provider has different pricing and model options—see models.json for available models. Requires the corresponding API key (COHERE_API_KEY, VOYAGE_API_KEY, etc.).',
        [
          ['Cohere Rerank', 'https://docs.cohere.com/reference/rerank'],
          ['Voyage Rerank', 'https://docs.voyageai.com/docs/reranker'],
          ['Jina Rerank', 'https://jina.ai/reranker/']
        ],
        [['Requires API key', 'warn']]
      ),
      RERANKER_LOCAL_MODEL: L(
        'Local Reranker Model',
        'When RERANKER_MODE=local, specifies the model to load. Can be:\n• A HuggingFace model ID (e.g., BAAI/bge-reranker-v2-m3)\n• A local filesystem path (e.g., /models/my-reranker)\n• Any sentence-transformers compatible model\n\nPopular options: BAAI/bge-reranker-v2-m3 (high quality), jinaai/jina-reranker-v1-base-en, cross-encoder/ms-marco-MiniLM-L-12-v2 (fast).',
        [
          ['BGE Reranker', 'https://huggingface.co/BAAI/bge-reranker-v2-m3'],
          ['Jina Reranker', 'https://huggingface.co/jinaai/jina-reranker-v1-base-en'],
          ['SBERT Cross-Encoders', 'https://www.sbert.net/docs/cross_encoder/pretrained_models.html']
        ],
        [['Free (no API costs)', 'info'], ['Requires download', 'warn']]
      ),

      RERANKER_MODEL: L(
        'Local Reranker (HF)',
        'HuggingFace model name or path for local reranking when RERANK_BACKEND=local or hf. Common options: "cross-encoder/ms-marco-MiniLM-L-6-v2" (fast, good quality), "BAAI/bge-reranker-base" (higher quality, slower), or path to your fine-tuned model like "models/cross-encoder-tribrid". Local reranking is free but slower than Cohere. Ensure model is downloaded before use.',
        [
          ['Cross-Encoder Models', 'https://www.sbert.net/docs/cross_encoder/pretrained_models.html'],
          ['HuggingFace Model Hub', 'https://huggingface.co/models?pipeline_tag=text-classification&sort=downloads'],
          ['Local Reranker README', '/models/cross-encoder-tribrid/README.md'],
          ['Learning Reranker', '/docs/LEARNING_RERANKER.md']
        ],
        [['Free (no API costs)', 'info'], ['Requires download', 'warn']]
      ),

      // Reranker Inference (live search blending)
      TRIBRID_RERANKER_ALPHA: L(
        'Reranker Blend Alpha',
        'Weight of the cross-encoder reranker score during final fusion. Higher alpha prioritizes semantic pairwise scoring; lower alpha relies more on initial hybrid retrieval (BM25 + dense). Typical range 0.6–0.8. Increasing alpha can improve ordering for nuanced queries but may surface false positives if your model is undertrained.',
        [
          ['Cross-Encoder Overview (SBERT)', 'https://www.sbert.net/examples/applications/cross-encoder/README.html'],
          ['Reciprocal Rank Fusion (RRF)', 'https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf'],
          ['Hybrid Retrieval Concepts', 'https://qdrant.tech/articles/hybrid-search/']
        ],
        [['Affects ranking', 'info']]
      ),
      TRIBRID_RERANKER_MAXLEN: L(
        'Reranker Max Sequence Length (Inference)',
        'Maximum token length for each (query, text) pair during live reranking. Larger values increase memory/cost and may not improve quality beyond ~256–384 tokens for code. Use higher values for long comments/docs; lower for tight compute budgets.',
        [
          ['Transformers Tokenization', 'https://huggingface.co/docs/transformers/main/en/tokenizer_summary'],
          ['Sequence Length vs Memory', 'https://huggingface.co/docs/transformers/perf_train_gpu_one']
        ],
        [['Performance sensitive', 'warn']]
      ),
      TRIBRID_RERANKER_BATCH: L(
        'Reranker Batch Size (Inference)',
        'Batch size used when scoring candidates during rerank. Higher values reduce latency but increase memory. If you see OOM or throttling, lower this value.',
        [
          ['Batching Techniques', 'https://huggingface.co/docs/transformers/v4.44.2/en/perf_train_gpu_one#use-mixed-precision'],
          ['Latency vs Throughput', 'https://en.wikipedia.org/wiki/Batch_processing']
        ],
        [['Tune for memory', 'info']]
      ),
      TRIBRID_RERANKER_TOPN: L(
        'Reranker Top-N',
        'Maximum number of candidates to pass through the cross-encoder reranker stage during retrieval. After hybrid fusion (BM25 + dense), the top-N candidates are reranked using pairwise semantic scoring before final selection. Higher values (50-100) improve recall by considering more candidates but increase reranking latency and compute cost quadratically. Lower values (20-30) are faster but may miss relevant results that scored poorly in initial retrieval but would rank highly after reranking.\n\nSweet spot: 40-60 for most use cases. Use 60-80 for complex queries where initial ranking may be noisy (e.g., ambiguous natural language queries like "where do we handle payments?"). Use 20-40 for tight latency budgets or when initial hybrid retrieval is already high-quality. Reranking cost scales with top-N × query length, so monitor inference time when tuning this parameter.\n\nSymptom of too low: Relevant results appear when you increase top-K but not with default settings. Symptom of too high: Reranking takes >500ms and retrieval latency dominates response time. Most production systems use 40-50 as a balanced default.\n\n• Typical range: 20-80 candidates\n• Balanced default: 40-50 for most workloads\n• High recall: 60-80 for exploratory queries\n• Low latency: 20-30 for speed-critical apps\n• Reranking cost: O(top-N × tokens) per query',
        [
          ['Cross-Encoder Reranking', 'https://www.sbert.net/examples/applications/cross-encoder/README.html'],
          ['Reranking in RAG', 'https://arxiv.org/abs/2407.21059'],
          ['SBERT Reranking Docs', 'https://www.sbert.net/docs/cross_encoder/pretrained_models.html'],
          ['Hybrid Search + Rerank', 'https://qdrant.tech/articles/hybrid-search/']
        ],
        [['Advanced RAG tuning', 'info'], ['Affects latency', 'warn']]
      ),

      RERANKER_CLOUD_TOP_N: L(
        'Cloud Reranker Top-N',
        'Maximum number of candidates to send to cloud reranking APIs (Cohere, Voyage, Jina). Cloud rerankers have rate limits and per-request pricing, so this setting is separate from the local reranker top-N. Lower values reduce API costs and stay within rate limits. Higher values improve recall but increase costs per query.\n\n• Typical range: 20-100 candidates\n• Cost-conscious: 20-30 for budget limits\n• Balanced default: 50 for most workloads\n• High recall: 80-100 for exploratory queries\n• Note: Cloud reranking is billed per candidate, so monitor costs',
        [
          ['Cohere Rerank API', 'https://docs.cohere.com/reference/rerank'],
          ['Voyage Rerank', 'https://docs.voyageai.com/docs/reranker']
        ],
        [['Cloud API costs', 'warn'], ['Rate limits apply', 'info']]
      ),

      // Learning Reranker — Training controls (GUI-only; not env vars)
      RERANKER_TRAIN_EPOCHS: L(
        'Training Epochs',
        'Number of full passes over the training triplets for the learning reranker. More epochs can improve quality but risk overfitting when data is small. Start with 1–2 and increase as your mined dataset grows.',
        [
          ['Fine-tuning Cross-Encoders', 'https://www.sbert.net/examples/training/cross-encoder/README.html'],
          ['InputExample format', 'https://www.sbert.net/docs/package_reference/cross_encoder.html#inputexample']
        ],
        [['Quality vs overfit', 'warn']]
      ),
      RERANKER_TRAIN_BATCH: L(
        'Training Batch Size',
        'Batches per gradient step during training. Larger batch sizes stabilize training but require more memory. For Colima or small GPUs/CPUs, use 1–4. If you see the container exit with code -9 (OOM), reduce this value.',
        [
          ['Memory Tips (HF)', 'https://huggingface.co/docs/transformers/perf_train_gpu_one'],
          ['Colima Resources', 'https://github.com/abiosoft/colima']
        ],
        [['Lower = safer on Colima', 'info']]
      ),
      RERANKER_TRAIN_MAXLEN: L(
        'Training Max Sequence Length',
        'Token limit for the cross-encoder during training. Longer sequences increase memory quadratically. If training fails with OOM (-9) under Docker/Colima, set 128–256. Sequences longer than the limit are truncated by the tokenizer and may emit warnings.',
        [
          ['Tokenization & Truncation', 'https://huggingface.co/docs/tokenizers/index'],
          ['Cross-Encoder Training', 'https://www.sbert.net/examples/training/cross-encoder/README.html']
        ],
        [['Memory sensitive', 'warn']]
      ),
      RERANKER_TRAIN_LR: L(
        'Training Learning Rate',
        'Learning rate for the cross-encoder optimizer during fine-tuning. This controls the size of weight updates during gradient descent. Standard range for cross-encoder fine-tuning is 1e-6 to 5e-5. Higher learning rates (3e-5, 5e-5) converge faster but risk overshooting optimal weights and causing training instability or divergence. Lower learning rates (1e-6, 5e-6) are safer and more stable but require more epochs to converge.\n\nSweet spot: 2e-5 for most cross-encoder fine-tuning tasks. This is the default used in many SBERT examples and works well for code reranking. Use 1e-5 for conservative training when you have limited data (<500 triplets) or notice training loss oscillating. Use 3e-5 for faster convergence when you have abundant data (>2000 triplets) and stable validation metrics. Always monitor training loss - if it spikes or increases, your learning rate is too high.\n\nCombine with RERANKER_WARMUP_RATIO for optimal results. Warmup gradually increases the learning rate from 0 to your target LR over the first N% of training, preventing early instability. Most practitioners use 2e-5 with 0.1 warmup as a reliable baseline.\n\n• Standard range: 1e-6 to 5e-5\n• Conservative (small data): 1e-5\n• Balanced default: 2e-5 (recommended)\n• Aggressive (large data): 3e-5 to 5e-5\n• Symptom too high: Loss spikes, NaN values, divergence\n• Symptom too low: Slow convergence, minimal improvement',
        [
          ['Learning Rate Explained', 'https://machinelearningmastery.com/understand-the-dynamics-of-learning-rate-on-deep-learning-neural-networks/'],
          ['Fine-tuning Cross-Encoders', 'https://www.sbert.net/examples/training/cross-encoder/README.html'],
          ['Learning Rate Schedules', 'https://huggingface.co/docs/transformers/main_classes/optimizer_schedules'],
          ['Cross-Encoder Training Guide', 'https://arxiv.org/abs/1908.10084']
        ],
        [['Advanced ML training', 'warn'], ['Requires tuning', 'info']]
      ),
      RERANKER_WARMUP_RATIO: L(
        'Warmup Ratio',
        'Fraction of total training steps to use for linear learning rate warmup. During warmup, the learning rate gradually increases from 0 to your target RERANKER_TRAIN_LR, preventing early training instability from large gradient updates. After warmup completes, the learning rate follows its normal schedule (typically constant or linear decay). Standard range: 0.0 (no warmup) to 0.2 (20% of training).\n\nSweet spot: 0.1 (10% warmup) for most cross-encoder training. This means if you train for 100 steps, the first 10 steps will gradually increase LR from 0 to your target. Warmup is especially important when fine-tuning from pretrained models, as it prevents catastrophic forgetting early in training. Use 0.05-0.08 for short training runs (<500 steps) and 0.1-0.15 for longer runs (>1000 steps).\n\nWarmup is critical when training with high learning rates (3e-5+) or limited data. Without warmup, the first few batches can cause large weight updates that destabilize the pretrained model. With warmup, training starts gentle and accelerates gradually. Most SBERT training recipes default to 0.1, which works well across domains.\n\n• No warmup: 0.0 (not recommended for fine-tuning)\n• Short training: 0.05-0.08 (e.g., 1-2 epochs, <500 steps)\n• Balanced default: 0.1 (recommended for most cases)\n• Long training: 0.15-0.2 (e.g., 5+ epochs, >2000 steps)\n• Effect: Stabilizes early training, prevents catastrophic forgetting\n• Combines with: RERANKER_TRAIN_LR for optimal convergence',
        [
          ['Warmup Schedules', 'https://huggingface.co/docs/transformers/main_classes/optimizer_schedules#transformers.get_linear_schedule_with_warmup'],
          ['Learning Rate Warmup Paper', 'https://arxiv.org/abs/1706.02677'],
          ['Fine-tuning Best Practices', 'https://www.sbert.net/examples/training/cross-encoder/README.html'],
          ['Scheduler Visualization', 'https://huggingface.co/docs/transformers/main_classes/optimizer_schedules']
        ],
        [['Advanced ML training', 'warn'], ['Stabilizes training', 'info']]
      ),
      TRIPLETS_MIN_COUNT: L(
        'Triplets Min Count',
        'Minimum number of training triplets (query, positive_doc, negative_doc) required to proceed with reranker training. Acts as a data quality gate - training with too few examples leads to severe overfitting and poor generalization. The reranker learns to distinguish relevant from irrelevant results, so it needs diverse examples to learn robust patterns. Standard minimum: 50-100 triplets for proof-of-concept, 500+ for production use.\n\nSweet spot: 200-500 triplets as a training threshold. With 200 triplets, you can run 2-3 epochs without severe overfitting. With 500+, you have enough diversity to learn generalizable patterns. Production systems should target 1000+ triplets from real user queries and feedback for best results. The quality of triplets matters more than quantity - 100 high-quality triplets from actual user interactions beat 500 synthetic triplets.\n\nTriplets are mined from your query logs, feedback data, or golden question sets using the triplet mining tools. Each triplet represents a learning signal: "query A is more relevant to document B than document C." The reranker learns these preferences and generalizes to new queries. If training fails with "insufficient data," increase your mining scope or lower this threshold temporarily for experimentation.\n\n• Absolute minimum: 50 triplets (proof-of-concept only)\n• Development minimum: 100-200 triplets\n• Production minimum: 500+ triplets (recommended)\n• Ideal: 1000-2000+ triplets for robust training\n• Quality over quantity: Real user data > synthetic examples\n• Symptom too low: Overfitting, poor generalization, reranker only works on training queries',
        [
          ['Triplet Loss for Ranking', 'https://arxiv.org/abs/1503.03832'],
          ['Hard Negative Mining', 'https://arxiv.org/abs/2104.08663'],
          ['Triplet Mining in RAG (ACL 2025)', 'https://aclanthology.org/2025.acl-industry.72.pdf'],
          ['Learning to Rank', 'https://en.wikipedia.org/wiki/Learning_to_rank']
        ],
        [['Data quality gate', 'warn'], ['Production needs 500+', 'info']]
      ),
      TRIPLETS_MINE_MODE: L(
        'Triplets Mine Mode',
        'Strategy for mining negative examples when constructing training triplets from query logs and feedback. Negative examples are crucial for learning to rank - they teach the model what NOT to retrieve. Three strategies: "random" (random negatives from corpus), "semi-hard" (negatives that scored moderately but below positives), and "hard" (negatives that scored high but are actually irrelevant). Hard negatives are most effective but require careful mining to avoid false negatives.\n\n"random": Randomly sample documents from the corpus that aren\'t in the positive set. Fast and safe but produces easy negatives that don\'t challenge the model. Use for initial training or small datasets (<200 triplets). Converges quickly but may not improve ranking quality much beyond baseline.\n\n"semi-hard" (recommended): Mine negatives that scored in the 40th-70th percentile of retrieval results but weren\'t marked as relevant. These are plausible but wrong answers. Teaches the model nuanced distinctions. Balances training difficulty and false negative risk. Best for production systems with 500+ triplets.\n\n"hard": Use top-ranked results that are actually irrelevant as negatives. Most effective for learning but risky - if your relevance labels are noisy, you may train on false negatives (actually relevant docs mislabeled as negative). Use only with high-confidence human feedback or click data. Produces strongest rerankers when data quality is high.\n\n• random: Safe baseline, fast, easy negatives, less effective\n• semi-hard: Balanced default, good difficulty, low false negative risk (recommended)\n• hard: Maximum difficulty, best results, requires clean labels, high false negative risk\n• Effect on training: Harder negatives = slower convergence but better final quality\n• Combine with: TRIPLETS_MIN_COUNT (need more data for hard negatives)',
        [
          ['Hard Negative Mining', 'https://arxiv.org/abs/2104.08663'],
          ['Negative Sampling Strategies', 'https://arxiv.org/abs/2007.00808'],
          ['Triplet Mining (ACL 2025)', 'https://aclanthology.org/2025.acl-industry.72.pdf'],
          ['Learning to Rank with Negatives', 'https://www.sbert.net/examples/training/cross-encoder/README.html']
        ],
        [['Advanced training control', 'warn'], ['Use semi-hard for production', 'info']]
      ),

      // Retrieval tuning
      BM25_WEIGHT: L(
        'BM25 Weight (Hybrid Fusion)',
        'Weight assigned to BM25 (sparse lexical) scores during hybrid search fusion. BM25 excels at exact keyword matches - variable names, function names, error codes, technical terms. Higher weights (0.5-0.7) prioritize keyword precision, favoring exact matches over semantic similarity. Lower weights (0.2-0.4) defer to dense embeddings, better for conceptual queries. The fusion formula is: final_score = (BM25_WEIGHT × bm25_score) + (VECTOR_WEIGHT × dense_score).\n\nSweet spot: 0.4-0.5 for balanced hybrid retrieval. Use 0.5-0.6 when users search with specific identifiers (e.g., "getUserById function" or "AuthenticationError exception"). Use 0.3-0.4 for natural language queries (e.g., "how does authentication work?"). The two weights should sum to approximately 1.0 for normalized scoring, though this isn\'t strictly enforced.\n\nSymptom of too high: Semantic matches are buried under keyword matches. Symptom of too low: Exact identifier matches rank poorly despite containing query terms. Production systems often A/B test 0.4 vs 0.5 to optimize for their user query patterns. Code search typically needs higher BM25 weight than document search.\n\n• Range: 0.2-0.7 (typical)\n• Keyword-heavy: 0.5-0.6 (function names, error codes)\n• Balanced: 0.4-0.5 (recommended for mixed queries)\n• Semantic-heavy: 0.3-0.4 (conceptual questions)\n• Should sum with VECTOR_WEIGHT to ~1.0\n• Affects: Hybrid fusion ranking, keyword vs semantic balance',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Hybrid Search Overview', 'https://qdrant.tech/articles/hybrid-search/'],
          ['Fusion Strategies in RAG', 'https://arxiv.org/abs/2402.14734'],
          ['Sparse vs Dense Retrieval', 'https://www.pinecone.io/learn/hybrid-search-intro/']
        ],
        [['Advanced RAG tuning', 'info'], ['Pairs with VECTOR_WEIGHT', 'info']]
      ),
      VECTOR_WEIGHT: L(
        'Vector Weight (Hybrid Fusion)',
        'Weight assigned to dense vector (semantic embedding) scores during hybrid search fusion. Dense embeddings capture semantic meaning and conceptual similarity, excelling at natural language queries and synonym matching. Higher weights (0.5-0.7) prioritize semantic relevance over exact keywords. Lower weights (0.2-0.4) defer to BM25 lexical matching. The fusion formula: final_score = (BM25_WEIGHT × bm25_score) + (VECTOR_WEIGHT × dense_score).\n\nSweet spot: 0.5-0.6 for balanced hybrid retrieval. Use 0.6-0.7 when users ask conceptual questions ("how does X work?", "what handles Y?") where synonyms and paraphrasing matter. Use 0.4-0.5 when exact term matching is important alongside semantics. The two weights should sum to approximately 1.0 for normalized scoring.\n\nSymptom of too high: Exact keyword matches (function names, specific terms) rank below semantic near-matches. Symptom of too low: Conceptually relevant results are buried despite being semantically similar. Most production RAG systems balance 0.5 BM25 with 0.5 vector, then fine-tune based on user feedback and eval metrics.\n\n• Range: 0.3-0.7 (typical)\n• Semantic-heavy: 0.6-0.7 (conceptual queries, natural language)\n• Balanced: 0.5-0.6 (recommended for mixed queries)\n• Keyword-heavy: 0.3-0.4 (when precision matters)\n• Should sum with BM25_WEIGHT to ~1.0\n• Affects: Hybrid fusion ranking, semantic vs keyword balance',
        [
          ['Dense Embeddings', 'https://www.sbert.net/docs/pretrained_models.html'],
          ['Hybrid Search Explained', 'https://qdrant.tech/articles/hybrid-search/'],
          ['Semantic Search', 'https://en.wikipedia.org/wiki/Semantic_search'],
          ['Embedding Models', 'https://weaviate.io/blog/how-to-choose-an-embedding-model']
        ],
        [['Advanced RAG tuning', 'info'], ['Pairs with BM25_WEIGHT', 'info']]
      ),
      LAYER_BONUS_GUI: L(
        'Layer Bonus (GUI)',
        'Score boost applied to chunks from GUI/frontend layers when query intent is classified as UI-related. Part of the multi-layer architecture routing system. When users ask "how does the settings page work?" or "where is the login button?", chunks from directories like frontend/, components/, views/ receive this additive bonus during reranking. Higher values (0.08-0.15) strongly bias toward frontend code. Lower values (0.03-0.06) provide subtle guidance.\n\nSweet spot: 0.06-0.10 for production systems with clear frontend/backend separation. Use 0.10-0.15 for strict layer routing when your architecture is well-organized and layer detection is accurate. Use 0.03-0.06 for loose guidance when layer boundaries are fuzzy. This bonus is only applied when intent classification detects UI/frontend intent from the query.\n\nWorks with repos.json layer_bonuses configuration, which maps intent types to directory patterns. Example: "ui" intent boosts frontend/, components/, views/. Combine with LAYER_BONUS_RETRIEVAL for multi-tier architectures (API, service, data layers). Intent detection uses keyword matching and optional LLM classification.\n\n• Range: 0.03-0.15 (typical)\n• Subtle guidance: 0.03-0.06\n• Balanced: 0.06-0.10 (recommended)\n• Strong routing: 0.10-0.15\n• Applied: Only when query intent = UI/frontend\n• Requires: repos.json layer_bonuses configuration',
        [
          ['Layer Routing in RAG', '/docs/MULTI_REPO.md#layer-bonuses'],
          ['Intent Classification', '/docs/RETRIEVAL.md#intent-classification'],
          ['repos.json Config', '/repos.json'],
          ['Architecture-Aware Retrieval', 'https://arxiv.org/abs/2312.10997']
        ],
        [['Advanced RAG tuning', 'info'], ['Multi-layer architectures', 'info']]
      ),
      LAYER_BONUS_RETRIEVAL: L(
        'Layer Bonus (Retrieval)',
        'Score boost applied to chunks from backend/API/service layers when query intent is classified as retrieval or data-related. Complements LAYER_BONUS_GUI for multi-tier architecture routing. When users ask "how do we fetch user data?" or "where is the search API?", chunks from api/, services/, models/, controllers/ receive this bonus during reranking. Helps route queries to the right architectural layer.\n\nSweet spot: 0.06-0.10 for production systems. Use 0.10-0.15 for strong backend routing when API layer is clearly separated. Use 0.03-0.06 for subtle hints when boundaries are less clear. This bonus applies when intent detection identifies backend/API/data queries via keywords like "fetch", "query", "API", "endpoint", "database".\n\nConfigure layer patterns in repos.json layer_bonuses: map "retrieval" intent to api/, routes/, controllers/, services/, etc. The intent classifier examines query terms and (optionally) uses an LLM to categorize intent. Multiple bonuses can apply simultaneously - a query about "user profile API" might trigger both LAYER_BONUS_GUI and LAYER_BONUS_RETRIEVAL.\n\n• Range: 0.03-0.15 (typical)\n• Subtle guidance: 0.03-0.06\n• Balanced: 0.06-0.10 (recommended)\n• Strong routing: 0.10-0.15\n• Applied: When query intent = API/backend/retrieval/data\n• Requires: repos.json layer_bonuses with retrieval intent mapping',
        [
          ['Layer Routing', '/docs/MULTI_REPO.md#layer-bonuses'],
          ['Intent Detection', '/docs/RETRIEVAL.md#intent-classification'],
          ['Multi-Tier Architectures', 'https://en.wikipedia.org/wiki/Multitier_architecture'],
          ['Backend Routing', '/docs/RETRIEVAL.md#layer-routing']
        ],
        [['Advanced RAG tuning', 'info'], ['Multi-layer architectures', 'info']]
      ),
      VENDOR_PENALTY: L(
        'Vendor Penalty',
        'Score penalty (negative bonus) applied to third-party library code (node_modules, vendor/, site-packages/, etc.) during reranking when VENDOR_MODE is set to prefer_first_party. Helps prioritize your application code over external dependencies. Typical range: -0.05 to -0.12. Higher penalties (more negative) push library code down the rankings more aggressively.\n\nSweet spot: -0.08 to -0.10 for production systems. Use -0.10 to -0.12 for strong first-party preference when you want library code only as fallback. Use -0.05 to -0.08 for moderate preference when library examples are sometimes helpful. Set to 0.0 to disable vendor detection entirely (all code ranked equally).\n\nVendor detection matches common patterns: node_modules/, vendor/, .venv/, site-packages/, bower_components/, Pods/, third_party/. The penalty is applied during final reranking after hybrid fusion. Pair with path boosts in repos.json to further prioritize your core application directories. Most users want to understand THEIR code first, then library internals.\n\n• Range: -0.12 to 0.0 (negative = penalty)\n• No penalty: 0.0 (rank libraries equally)\n• Moderate preference: -0.05 to -0.08\n• Balanced: -0.08 to -0.10 (recommended)\n• Strong first-party: -0.10 to -0.12\n• Opposite mode: Set VENDOR_MODE=prefer_vendor to boost libraries instead',
        [
          ['Vendor Detection Logic', '/docs/RETRIEVAL.md#vendor-detection'],
          ['VENDOR_MODE Setting', '/docs/RETRIEVAL.md#vendor-mode'],
          ['Path Patterns', 'https://github.com/github/gitignore'],
          ['First-Party vs Third-Party', 'https://en.wikipedia.org/wiki/First-party_and_third-party_sources']
        ],
        [['Advanced RAG tuning', 'info'], ['Code priority control', 'info']]
      ),
      FRESHNESS_BONUS: L(
        'Freshness Bonus',
        'Score boost applied to recently modified files during reranking, prioritizing newer code over stale code. Based on file modification time (mtime). Files modified in the last N days receive the full bonus, with linear decay over time. Useful for prioritizing recent work, active features, and current implementation patterns. Typical range: 0.0 (disabled) to 0.10 (strong recency bias).\n\nSweet spot: 0.03-0.06 for subtle freshness preference. Use 0.06-0.10 for strong recency bias when your codebase changes rapidly and recent code is more likely relevant. Use 0.0 to disable entirely for stable codebases where age doesn\'t correlate with relevance. The bonus decays linearly from full value (files modified <7 days ago) to zero (files modified >90 days ago).\n\nExample: With 0.05 bonus, a file modified yesterday gets +0.05, a file modified 30 days ago gets +0.025, a file modified 90+ days ago gets 0. Freshness helps when users ask "how do we currently handle X?" - emphasizes recent implementations over legacy code. Trade-off: May deprioritize well-tested stable code in favor of recent changes.\n\n• Range: 0.0-0.10 (typical)\n• Disabled: 0.0 (age-agnostic ranking)\n• Subtle: 0.03-0.05\n• Balanced: 0.05-0.06 (recommended for active repos)\n• Strong recency: 0.08-0.10\n• Decay window: Full bonus at 0-7 days, linear decay to 90 days\n• Trade-off: Recent code vs battle-tested stable code',
        [
          ['Freshness in Ranking', 'https://en.wikipedia.org/wiki/Freshness_(search_engine)'],
          ['Temporal Relevance', 'https://en.wikipedia.org/wiki/Temporal_information_retrieval'],
          ['Score Boosting', '/docs/RETRIEVAL.md#freshness-scoring'],
          ['Recency Bias', 'https://en.wikipedia.org/wiki/Recency_bias']
        ],
        [['Advanced RAG tuning', 'info'], ['Time-based ranking', 'info']]
      ),
      KEYWORDS_BOOST: L(
        'Keywords Boost',
        'Score boost applied to chunks containing high-frequency repository-specific keywords. Keywords are mined during indexing from your codebase - class names, function names, domain terms that appear frequently in your project but rarely in general code. When a query contains these keywords, matching chunks receive this bonus. Helps surface domain-specific code and project-specific patterns.\n\nSweet spot: 0.08-0.12 for balanced keyword boosting. Use 0.12-0.15 for strong domain term preference when your project has unique terminology (e.g., "TriBrid", "TriBridRAG", "hybrid_search"). Use 0.05-0.08 for subtle boosting when overlap with common terms is high. Keywords must appear >= KEYWORDS_MIN_FREQ times in the codebase to be considered domain-specific.\n\nKeywords are stored during indexing in keywords.json (per-repo). Query terms are matched against this keyword set, and chunks containing these terms get the bonus during reranking. This is separate from BM25 (which scores all terms) - keyword boost targets YOUR project\'s vocabulary. Example: "AuthService" is a keyword in your codebase but not in general code, so queries about "AuthService" get extra boost.\n\n• Range: 0.05-0.15 (typical)\n• Subtle: 0.05-0.08\n• Balanced: 0.08-0.12 (recommended)\n• Strong domain preference: 0.12-0.15\n• Requires: keywords.json generated during indexing\n• Controlled by: KEYWORDS_MIN_FREQ (frequency threshold)',
        [
          ['Keyword Extraction', 'https://en.wikipedia.org/wiki/Keyword_extraction'],
          ['Domain-Specific Terms', 'https://en.wikipedia.org/wiki/Terminology'],
          ['TF-IDF for Keywords', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf'],
          ['Keywords Mining', '/docs/INDEXING.md#keywords-extraction']
        ],
        [['Advanced RAG tuning', 'info'], ['Domain-specific boosting', 'info']]
      ),
      KEYWORDS_MIN_FREQ: L(
        'Keywords Min Frequency',
        'Minimum frequency threshold for a term to be considered a repository-specific keyword during indexing. Terms appearing fewer than this many times are ignored. Higher thresholds (10-20) focus on common project terms; lower thresholds (3-5) include more specialized terms. Keywords are used by KEYWORDS_BOOST for query-time score boosting.\n\nSweet spot: 5-8 for balanced keyword extraction. Use 8-12 for large codebases (>100k LOC) to focus on truly common terms and avoid noise. Use 3-5 for small codebases (<20k LOC) to capture enough domain vocabulary. Terms must appear at least this many times AND be relatively rare in general code to qualify as keywords.\n\nKeyword mining runs during indexing: terms are counted, filtered by frequency, and compared against a general code corpus to compute TF-IDF-like scores. High-scoring terms (frequent in YOUR repo, rare in general code) become keywords. These are stored in keywords.json and used at query time for KEYWORDS_BOOST scoring. Re-index after changing this setting.\n\n• Range: 3-20 (typical)\n• Small codebases: 3-5 (capture domain terms)\n• Balanced: 5-8 (recommended for most projects)\n• Large codebases: 8-12 (focus on common terms)\n• Very large: 15-20 (only highly frequent terms)\n• Effect: Higher = fewer, more common keywords; Lower = more, rarer keywords\n• Requires reindex: Changes take effect after rebuilding index',
        [
          ['TF-IDF Scoring', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf'],
          ['Keyword Extraction', 'https://en.wikipedia.org/wiki/Keyword_extraction'],
          ['Document Frequency', 'https://en.wikipedia.org/wiki/Document_frequency'],
          ['Keyword Mining', '/docs/INDEXING.md#keywords-extraction']
        ],
        [['Advanced indexing', 'info'], ['Requires reindex', 'reindex']]
      ),
      MULTI_QUERY_M: L(
        'Multi-Query M (RRF Constant)',
        'Constant "k" parameter in Reciprocal Rank Fusion (RRF) formula used to merge results from multiple query rewrites. RRF formula: score = sum(1 / (k + rank_i)) across all query variants. Higher M values (60-100) compress rank differences, treating top-10 and top-20 results more equally. Lower M values (20-40) emphasize top-ranked results, creating steeper rank penalties.\n\nSweet spot: 50-60 for balanced fusion. This is the standard RRF constant used in most production systems. Use 40-50 for more emphasis on top results (good when rewrites are high quality). Use 60-80 for smoother fusion (good when rewrites produce diverse rankings). The parameter is called "M" in code but represents the "k" constant in academic RRF papers.\n\nRRF fusion happens when MQ_REWRITES > 1: each query variant retrieves results, then RRF merges them by summing reciprocal ranks. Example with M=60: rank-1 result scores 1/61=0.016, rank-10 scores 1/70=0.014. Higher M reduces the gap. This parameter rarely needs tuning - default of 60 works well for most use cases.\n\n• Standard range: 40-80\n• Emphasize top results: 40-50\n• Balanced: 50-60 (recommended, RRF default)\n• Smooth fusion: 60-80\n• Formula: score = sum(1 / (M + rank)) for each query variant\n• Only matters when: MQ_REWRITES > 1 (multi-query enabled)',
        [
          ['Reciprocal Rank Fusion Paper', 'https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf'],
          ['RRF in Practice', 'https://www.elastic.co/guide/en/elasticsearch/reference/current/rrf.html'],
          ['Multi-Query RAG', 'https://arxiv.org/abs/2305.14283'],
          ['Fusion Strategies', 'https://arxiv.org/abs/2402.14734']
        ],
        [['Advanced RAG tuning', 'info'], ['RRF fusion control', 'info']]
      ),
      BM25_TOKENIZER: L(
        'BM25 Tokenizer',
        'Tokenization strategy for BM25 sparse index. Controls how code text is split into searchable terms. Options: "stemmer" (Porter stemming, normalizes word forms like "running" → "run"), "whitespace" (split on spaces only, preserves exact forms), "standard" (lowercase + split on punctuation). For code search, preserving exact forms is usually better than stemming.\n\nSweet spot: "whitespace" or "standard" for code search. Stemming helps with natural language (README files, comments) but can hurt code search by conflating different identifiers. For example, stemming might merge "user" and "users" (good for prose) but also "handler" and "handle" (bad for code). Most code-focused RAG systems avoid stemming.\n\n"whitespace": Splits on whitespace only, preserves case and punctuation. Good for camelCase and snake_case. Example: "getUserData" → ["getUserData"].\n\n"standard": Lowercase + split on punctuation. Better for cross-case matching. Example: "getUserData" → ["getuserdata"] (matches "getuserdata", "getUserData", "GETUSERDATA").\n\n"stemmer": Applies Porter stemmer. Best for natural language, risky for code. Example: "getUserData" → stems individual tokens.\n\n• whitespace: Preserve exact forms, case-sensitive, best for strict code search\n• standard: Lowercase + punctuation split, case-insensitive, balanced (recommended)\n• stemmer: Normalize word forms, best for natural language, risky for code\n• Effect: Changes how BM25 matches query terms to code\n• Requires reindex: Changes take effect after rebuilding BM25 index',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Porter Stemmer', 'https://en.wikipedia.org/wiki/Stemming#Porter_stemmer'],
          ['Tokenization', 'https://en.wikipedia.org/wiki/Lexical_analysis#Tokenization'],
          ['BM25S Tokenizers', 'https://github.com/xhluca/bm25s#tokenization']
        ],
        [['Advanced indexing', 'info'], ['Requires reindex', 'reindex']]
      ),
      BM25_VOCAB_PREVIEW: L(
        'BM25 Vocabulary Preview',
        'Inspect tokenized vocabulary from BM25 sparse index. Shows term frequencies for debugging. Use cases: verify code identifiers preserved, check stemmer behavior, identify noise terms, debug zero-result queries. Vocabulary reflects tokenizer: whitespace (exact, best for code), stemmer (normalized, best for prose), standard (balanced). Large vocabularies (>100K) indicate insufficient stopword filtering.',
        [
          ['BM25S: Eager Sparse Scoring (arXiv 2024)', 'https://arxiv.org/abs/2407.03618'],
          ['BMX: Entropy-weighted BM25 Extension', 'https://arxiv.org/abs/2408.06643'],
          ['Tokenization Foundations (ICLR 2025)', 'https://arxiv.org/abs/2407.11606'],
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Text Tokenization', 'https://en.wikipedia.org/wiki/Lexical_analysis#Tokenization']
        ],
        [['DEBUGGING', 'info'], ['REINDEX TO UPDATE', 'warn']]
      ),
      BM25_TOKENIZER_RESOLVED: L(
        'Resolved Tokenizer',
        'The actual tokenization settings that will be applied during indexing. Shows the combined effect of tokenizer type, stemmer language, and stopwords language. This is the effective configuration after all settings are resolved.',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Tokenization', 'https://en.wikipedia.org/wiki/Lexical_analysis#Tokenization']
        ],
        [['Read-only', 'info']]
      ),
      INDEX_VALIDATION_ERROR: L(
        'Validation Error',
        'Configuration issues that must be fixed before indexing can proceed. Common errors: embedding dimension mismatch with existing index, missing API keys for cloud providers, chunk overlap exceeding chunk size. Fix these issues and try again.',
        [
          ['Indexing Guide', '/docs/INDEXING.md'],
          ['Embedding Configuration', '/docs/EMBEDDINGS.md']
        ],
        [['Blocks indexing', 'warn']]
      ),
      INDEX_VALIDATION_WARNING: L(
        'Validation Warning',
        'Configuration may reduce retrieval quality but indexing can still proceed. Common warnings: skip dense vectors enabled (BM25-only mode), very large chunk sizes (>2000), small chunks with AST strategy. Review and confirm to proceed.',
        [
          ['Retrieval Best Practices', '/docs/RETRIEVAL.md'],
          ['Chunk Size Tuning', '/docs/INDEXING.md#chunk-sizing']
        ],
        [['Quality impact', 'info']]
      ),
      PER_REPO_INDEXING: L(
        'Per-Repository Indexing Configuration',
        'Override global indexing settings per repo. Enables optimization for different codebases. Scenarios: docs repos (larger chunks 1500-2000, stemmer), dense code (smaller chunks 500-800, whitespace), mixed (AST + hybrid), legacy (greedy if AST fails). Checked = inherit tribrid_config.json. Unchecked = repos.json overrides take precedence. Unchanged fields still inherit global. Changes apply on reindex.',
        [
          ['Monorepo Configuration Patterns', 'https://monorepo.tools/'],
          ['Multi-Repo Search Strategies', 'https://www.aviator.co/blog/monorepo-a-hands-on-guide-for-managing-repositories-and-microservices/'],
          ['Configuration Override Patterns', 'https://en.wikipedia.org/wiki/Configuration_file'],
          ['Cascading Configuration', 'https://en.wikipedia.org/wiki/Cascading_Style_Sheets#Specificity']
        ],
        [['ADVANCED', 'warn'], ['PER-REPO', 'info']]
      ),
      MQ_REWRITES: L(
        'Multi‑Query Rewrites',
        'Number of query variations to generate for improved recall. Each rewrite searches independently, then results are fused and reranked. For example, query "auth flow" might expand to "authentication flow", "login process", "user authentication". Higher values (4-6) improve recall for vague questions like "Where is X implemented?" but increase API calls and latency. Start at 2-3 for general use.',
        [
          ['Multi-Query RAG', 'https://arxiv.org/abs/2305.14283'],
          ['Query Expansion', 'https://en.wikipedia.org/wiki/Query_expansion'],
          ['RAG Techniques', 'https://python.langchain.com/docs/how_to/MultiQueryRetriever/']
        ],
        [['Affects latency','info'], ['Higher cost', 'warn']]
      ),
      TOPK_DENSE: L(
        'Top‑K Dense',
        'Number of candidate results to retrieve from Qdrant vector (semantic) search before hybrid fusion. Higher values (100-150) improve recall for semantic matches but increase query latency and memory usage. Lower values (40-60) are faster but may miss relevant results. Must be >= FINAL_K. Recommended: 75 for balanced performance, 100-120 for high recall scenarios.',
        [
          ['Vector Similarity Search', 'https://qdrant.tech/documentation/concepts/search/'],
          ['Semantic Search', 'https://en.wikipedia.org/wiki/Semantic_search'],
          ['Top-K Retrieval', 'https://en.wikipedia.org/wiki/Nearest_neighbor_search#k-nearest_neighbors']
        ],
        [['Affects latency','info'], ['Semantic matches', 'info']]
      ),
      TOPK_SPARSE: L(
        'Top‑K Sparse',
        'Number of candidate results to retrieve from BM25 keyword (lexical) search before hybrid fusion. Higher values (100-150) improve recall for exact keyword matches (variable names, function names, error codes) but increase latency. Lower values (40-60) are faster but may miss exact matches. Must be >= FINAL_K. Recommended: 75 for balanced performance, 100-120 for keyword-heavy queries.',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['BM25S Library (GitHub)', 'https://github.com/xhluca/bm25s'],
          ['Lexical vs Semantic', '/docs/RETRIEVAL.md#hybrid-search']
        ],
        [['Affects latency','info'], ['Keyword matches', 'info']]
      ),
      FINAL_K: L(
        'Final Top‑K',
        'Number of top results to return after hybrid fusion, reranking, and scoring boosts. This is what you get back from search. Higher values (15-30) provide more context but may include noise. Lower values (5-10) are faster and more precise. Default: 10. Recommended: 10 for chat, 20-30 for browsing/exploration.',
        [
          ['Precision vs Recall', 'https://en.wikipedia.org/wiki/Precision_and_recall'],
          ['Top-K Selection', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf#Top-K_retrieval'],
          ['RAG Retrieval', '/docs/RETRIEVAL.md#final-k']
        ],
        [['Core Setting', 'info']]
      ),
      HYDRATION_MODE: L(
        'Hydration Mode',
        'Controls when full code is loaded from chunks.jsonl. "Lazy" (recommended) loads code after retrieval, providing full context with minimal memory overhead. "None" returns only metadata (file path, line numbers) - fastest but no code content. Use "none" for testing retrieval quality or when you only need file locations, not actual code.',
        [
          ['Lazy Loading', 'https://en.wikipedia.org/wiki/Lazy_loading'],
          ['Performance Guide', '/docs/PERFORMANCE_AND_COST.md'],
          ['chunks.jsonl Format', '/docs/INDEXING.md#chunks-format']
        ],
        [['Lazy Recommended', 'info']]
      ),
      HYDRATION_MAX_CHARS: L(
        'Hydration Max Chars',
        'Maximum characters to load per chunk when hydrating results with code content. Prevents huge chunks from bloating responses and consuming excessive memory. 0 = no limit (may cause memory issues with large files). Recommended: 2000 for general use, 1000 for memory-constrained environments, 5000 for detailed code review. Chunks larger than this limit are truncated.',
        [
          ['Text Truncation', 'https://en.wikipedia.org/wiki/Truncation'],
          ['Performance Guide', '/docs/PERFORMANCE_AND_COST.md'],
          ['Chunk Size Tuning', '/docs/INDEXING.md#chunk-size']
        ],
        [['Performance', 'info']]
      ),

      // Vector Search
      VECTOR_SEARCH_ENABLED: L(
        'Vector Search Enabled',
        'Enable or disable vector (dense semantic) search using pgvector. When enabled, queries use embedding similarity to find semantically related chunks. When disabled, only sparse (BM25) and graph search are used. Recommended: enabled for most use cases. Disable only if you want pure keyword-based retrieval or are troubleshooting vector search performance.\n\nSweet spot: enabled for production systems. Vector search excels at finding conceptually related content even when exact keywords don\'t match. Disable temporarily if pgvector is unavailable or causing latency issues.\n\n• Enabled: Full tri-brid retrieval (vector + sparse + graph)\n• Disabled: Dual-mode retrieval (sparse + graph only)\n• Effect: Controls whether semantic similarity search contributes to results\n• Symptom if disabled: Semantic matches may be missed, especially for abstract queries',
        [
          ['pgvector Documentation', 'https://github.com/pgvector/pgvector'],
          ['Vector Search Optimization', 'https://neon.tech/docs/ai/ai-vector-search-optimization'],
          ['Semantic Search', 'https://en.wikipedia.org/wiki/Semantic_search'],
          ['Tri-brid Retrieval', '/docs/retrieval/overview.md']
        ],
        [['Core Setting', 'info']]
      ),
      VECTOR_SEARCH_TOP_K: L(
        'Vector Search Top-K',
        'Number of candidate results to retrieve from pgvector vector search before fusion. Higher values (75-150) improve recall for semantic matches but increase query latency and memory usage. Lower values (30-50) are faster but may miss relevant results. Must be >= FINAL_K. Recommended: 50 for balanced performance, 75-100 for high recall scenarios.\n\nSweet spot: 50-75 for production systems. Use 75-100 when semantic matching is critical (e.g., finding conceptually similar code patterns). Use 30-50 for cost-sensitive scenarios or when initial retrieval quality is already high.\n\n• Range: 10-200 (typical: 30-100)\n• Balanced: 50-75 (recommended)\n• High recall: 75-100 (semantic-heavy queries)\n• Cost-sensitive: 30-50 (faster, lower cost)\n• Effect: Higher = more semantic candidates, better recall, higher latency\n• Symptom too low: Relevant semantic matches missed\n• Symptom too high: Slower queries, memory pressure, diminishing returns',
        [
          ['pgvector Optimization', 'https://neon.tech/blog/optimizing-vector-search-performance-with-pgvector'],
          ['Top-K Retrieval', 'https://en.wikipedia.org/wiki/Nearest_neighbor_search#k-nearest_neighbors'],
          ['Vector Search Performance', 'https://aws.amazon.com/blogs/database/supercharging-vector-search-performance-and-relevance-with-pgvector-0-8-0-on-amazon-aurora-postgresql/'],
          ['Retrieval Tuning', '/docs/retrieval/vector-sparse.md']
        ],
        [['Affects latency', 'info'], ['Semantic matches', 'info']]
      ),
      VECTOR_SIMILARITY_THRESHOLD: L(
        'Vector Similarity Threshold',
        'Minimum cosine similarity score (0.0-1.0) required to include a vector search result. Results below this threshold are filtered out before fusion. 0.0 = no threshold (all results included). Higher values (0.5-0.7) ensure only highly similar results pass, improving precision but reducing recall. Lower values (0.0-0.3) allow more diverse results.\n\nSweet spot: 0.0 for most use cases (let fusion handle filtering). Use 0.5-0.6 when you want to aggressively filter low-quality semantic matches. Use 0.7+ only for precision-critical scenarios where false positives are costly.\n\n• Range: 0.0-1.0 (typical: 0.0-0.6)\n• No filtering: 0.0 (recommended, let fusion decide)\n• Moderate filtering: 0.4-0.5 (reduce noise)\n• Aggressive filtering: 0.6-0.7 (precision-critical)\n• Effect: Higher = fewer results, higher precision, lower recall\n• Symptom too high: Relevant semantic matches filtered out\n• Symptom too low: Noise included, fusion must handle filtering',
        [
          ['Cosine Similarity Threshold', 'https://www.emergentmind.com/topics/cosine-similarity-threshold'],
          ['Vector Similarity Search', 'https://en.wikipedia.org/wiki/Cosine_similarity'],
          ['Score Filtering', 'https://ui.adsabs.harvard.edu/abs/2018arXiv181207695L/abstract'],
          ['Retrieval Filtering', '/docs/retrieval/vector-sparse.md#similarity-thresholds']
        ],
        [['Precision tuning', 'info']]
      ),

      // Sparse Search
      SPARSE_SEARCH_ENABLED: L(
        'Sparse Search Enabled',
        'Enable or disable sparse (BM25 keyword) search. When enabled, queries use lexical matching to find chunks containing exact keywords, variable names, function names, and error codes. When disabled, only vector and graph search are used. Recommended: enabled for most use cases. Disable only if you want pure semantic retrieval or are troubleshooting BM25 performance.\n\nSweet spot: enabled for production systems. Sparse search excels at exact keyword matching and finding specific code symbols. Disable temporarily if BM25 indexing is unavailable or causing latency issues.\n\n• Enabled: Full tri-brid retrieval (vector + sparse + graph)\n• Disabled: Dual-mode retrieval (vector + graph only)\n• Effect: Controls whether lexical keyword search contributes to results\n• Symptom if disabled: Exact keyword matches may be missed, especially for code symbols',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Hybrid Retrieval', 'https://www.elastic.co/search-labs/blog/improving-information-retrieval-elastic-stack-hybrid'],
          ['Sparse vs Dense Retrieval', 'https://www.pinecone.io/learn/hybrid-search-intro/'],
          ['Tri-brid Retrieval', '/docs/retrieval/overview.md']
        ],
        [['Core Setting', 'info']]
      ),
      SPARSE_SEARCH_TOP_K: L(
        'Sparse Search Top-K',
        'Number of candidate results to retrieve from BM25 sparse search before fusion. Higher values (75-150) improve recall for exact keyword matches (variable names, function names, error codes) but increase query latency. Lower values (30-50) are faster but may miss exact matches. Must be >= FINAL_K. Recommended: 50 for balanced performance, 75-100 for keyword-heavy queries.\n\nSweet spot: 50-75 for production systems. Use 75-100 when exact keyword matching is critical (e.g., finding specific function names or error codes). Use 30-50 for cost-sensitive scenarios or when initial retrieval quality is already high.\n\n• Range: 10-200 (typical: 30-100)\n• Balanced: 50-75 (recommended)\n• High recall: 75-100 (keyword-heavy queries)\n• Cost-sensitive: 30-50 (faster, lower cost)\n• Effect: Higher = more keyword candidates, better recall, higher latency\n• Symptom too low: Exact keyword matches missed\n• Symptom too high: Slower queries, diminishing returns',
        [
          ['BM25 Best Practices', 'https://www.elastic.co/blog/practical-bm25-part-3-considerations-for-picking-b-and-k1-in-elasticsearch'],
          ['Top-K Retrieval', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf#Top-K_retrieval'],
          ['BM25 Weighting Scheme', 'https://xapian.org/docs/bm25.html'],
          ['Retrieval Tuning', '/docs/retrieval/vector-sparse.md']
        ],
        [['Affects latency', 'info'], ['Keyword matches', 'info']]
      ),

      // Graph Search
      GRAPH_SEARCH_ENABLED: L(
        'Graph Search Enabled',
        'Enable or disable graph-based search using Neo4j. When enabled, queries traverse the knowledge graph to find related chunks through entity relationships, code structure (AST), and community detection. When disabled, only vector and sparse search are used. Recommended: enabled for codebases with rich structure and relationships.\n\nSweet spot: enabled for production systems with graph indexing. Graph search excels at finding related code through structural relationships (imports, calls, inheritance). Disable if Neo4j is unavailable, graph indexing is incomplete, or you want pure vector/sparse retrieval.\n\n• Enabled: Full tri-brid retrieval (vector + sparse + graph)\n• Disabled: Dual-mode retrieval (vector + sparse only)\n• Effect: Controls whether graph traversal contributes to results\n• Symptom if disabled: Structural relationships and entity connections may be missed',
        [
          ['Neo4j GraphRAG', 'https://neo4j.com/blog/what-is-graphrag/'],
          ['GraphRAG User Guide', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Traversal', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Tri-brid Retrieval', '/docs/retrieval/graph.md']
        ],
        [['Core Setting', 'info']]
      ),
      GRAPH_SEARCH_MODE: L(
        'Graph Search Mode',
        'Graph retrieval strategy: "chunk" uses lexical chunk nodes with Neo4j vector index for semantic chunk search, "entity" uses the legacy code-entity graph. Chunk mode (recommended) combines vector similarity with graph traversal for better relevance. Entity mode uses structural relationships between code entities (functions, classes, modules).\n\nSweet spot: "chunk" for most use cases. Chunk mode provides better integration with vector search and more relevant results. Use "entity" only for legacy compatibility or when entity-based traversal is specifically needed.\n\n• Chunk mode: Modern approach, integrates with vector search, better relevance\n• Entity mode: Legacy approach, entity-based traversal, structural relationships\n• Effect: Determines how graph traversal finds related chunks\n• Symptom wrong mode: Suboptimal results, missing relevant connections',
        [
          ['Neo4j GraphRAG', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Retrieval Modes', 'https://neo4j.com/blog/developer/graphrag-field-guide-rag-patterns'],
          ['Graph Traversal', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Configuration', 'info']]
      ),
      GRAPH_MAX_HOPS: L(
        'Graph Max Hops',
        'Maximum number of graph traversal hops from seed nodes. Each hop expands the search to connected nodes (chunks, entities, relationships). Higher values (3-5) find more distant relationships but increase query latency and may introduce noise. Lower values (1-2) are faster and more focused. Recommended: 2 for balanced performance.\n\nSweet spot: 2 for production systems. Use 1 for fast, focused traversal (immediate neighbors only). Use 3-4 when you need to find distant relationships or explore deep code structures. Use 5 only for exploratory queries where completeness matters more than speed.\n\n• Range: 1-5 (typical: 1-3)\n• Focused: 1 (immediate neighbors only)\n• Balanced: 2 (recommended)\n• Deep exploration: 3-4 (distant relationships)\n• Effect: Higher = more relationships explored, better recall, higher latency\n• Symptom too low: Relevant connections missed\n• Symptom too high: Slower queries, noise introduced',
        [
          ['Neo4j Graph Traversal', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Traversal Depth', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Graph Algorithms', 'https://en.wikipedia.org/wiki/Graph_traversal'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Performance', 'info']]
      ),
      GRAPH_INCLUDE_COMMUNITIES: L(
        'Include Communities',
        'Enable community-based expansion in graph search. When enabled, the system uses community detection algorithms (e.g., Louvain) to identify clusters of related nodes and expands search to include entire communities. This improves recall for related concepts but may introduce noise. Recommended: enabled for entity mode, optional for chunk mode.\n\nSweet spot: enabled for entity mode, disabled for chunk mode. Community expansion works best with entity-based graphs where structural clusters are meaningful. For chunk mode, neighbor expansion is usually sufficient.\n\n• Enabled: Community-based expansion, better recall, may introduce noise\n• Disabled: Direct neighbor expansion only, more focused results\n• Effect: Controls whether community detection influences traversal\n• Symptom if disabled: Related concepts in same community may be missed',
        [
          ['Louvain Algorithm', 'https://neo4j.com/docs/graph-data-science/current/algorithms/louvain'],
          ['Community Detection', 'https://neo4j.com/docs/graph-data-science/current/algorithms/community/'],
          ['Community Detection Algorithms', 'https://en.wikipedia.org/wiki/Community_structure'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Advanced', 'info']]
      ),
      GRAPH_SEARCH_TOP_K: L(
        'Graph Search Top-K',
        'Number of candidate results to retrieve from Neo4j graph search before fusion. Higher values (40-100) improve recall for graph-based relationships but increase query latency. Lower values (15-30) are faster but may miss relevant connections. Must be >= FINAL_K. Recommended: 30 for balanced performance.\n\nSweet spot: 30 for production systems. Use 40-50 when graph relationships are critical (e.g., finding code that calls or imports specific functions). Use 15-20 for cost-sensitive scenarios or when graph indexing is sparse.\n\n• Range: 5-100 (typical: 20-50)\n• Balanced: 30 (recommended)\n• High recall: 40-50 (relationship-heavy queries)\n• Cost-sensitive: 15-20 (faster, lower cost)\n• Effect: Higher = more graph candidates, better recall, higher latency\n• Symptom too low: Relevant graph connections missed\n• Symptom too high: Slower queries, diminishing returns',
        [
          ['Neo4j GraphRAG', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Traversal', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Top-K Retrieval', 'https://en.wikipedia.org/wiki/Nearest_neighbor_search#k-nearest_neighbors'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Affects latency', 'info'], ['Graph relationships', 'info']]
      ),
      GRAPH_CHUNK_NEIGHBOR_WINDOW: L(
        'Chunk Neighbor Window',
        'When graph mode is "chunk", include up to N adjacent chunks (NEXT_CHUNK relationships) around each seed hit. Higher values (2-5) include more context but may introduce noise. Lower values (0-1) are more focused. Recommended: 1 for balanced context.\n\nSweet spot: 1 for production systems. Use 0 for minimal context (seed chunks only). Use 2-3 when you need more surrounding context (e.g., finding complete function implementations). Use 4-5 only for exploratory queries where completeness matters.\n\n• Range: 0-10 (typical: 0-3)\n• Minimal: 0 (seed chunks only)\n• Balanced: 1 (recommended)\n• Extended context: 2-3 (more surrounding chunks)\n• Effect: Higher = more adjacent chunks included, better context, may introduce noise\n• Symptom too low: Insufficient context around seed hits\n• Symptom too high: Too much noise from distant chunks',
        [
          ['Neo4j Graph Traversal', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Chunk Relationships', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Context Window', 'https://en.wikipedia.org/wiki/Context_window'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Chunk Mode', 'info']]
      ),
      GRAPH_CHUNK_SEED_OVERFETCH: L(
        'Chunk Seed Overfetch Multiplier',
        'When graph mode is "chunk" and Neo4j uses a shared database, overfetch seed hits before filtering by corpus_id. This compensates for shared database queries where corpus filtering happens after retrieval. Higher values (10-20) ensure sufficient results after filtering but increase query cost. Lower values (5-10) are more efficient but may return fewer results.\n\nSweet spot: 10 for shared database mode. Use 5-8 for per-corpus databases (no filtering needed). Use 15-20 when corpus filtering is very selective (small corpus in large database).\n\n• Range: 1-50 (typical: 5-20)\n• Per-corpus DB: 5-8 (minimal overfetch)\n• Shared DB: 10 (recommended)\n• Selective filtering: 15-20 (high overfetch)\n• Effect: Higher = more seed candidates, better recall after filtering, higher cost\n• Symptom too low: Insufficient results after corpus filtering\n• Symptom too high: Unnecessary query overhead',
        [
          ['Neo4j Multi-Database', 'https://assets.neo4j.com/Official-Materials/Multi+DB+Considerations.pdf'],
          ['Database Isolation', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Query Optimization', 'https://neo4j.com/docs/cypher-manual/current/query-tuning/'],
          ['Graph Storage', '/docs/database.md']
        ],
        [['Performance', 'info'], ['Shared DB', 'warn']]
      ),
      GRAPH_CHUNK_ENTITY_EXPANSION_ENABLED: L(
        'Chunk Entity Expansion Enabled',
        'When graph mode is "chunk", expand from seed chunks via entity graph (IN_CHUNK links) to find related chunks. This combines chunk-based retrieval with entity relationships for better recall. When enabled, chunks connected to the same entities are included. Recommended: enabled for codebases with rich entity relationships.\n\nSweet spot: enabled for production systems. Entity expansion improves recall by finding chunks that share entities (functions, classes, modules) even if they\'re not directly connected. Disable if entity relationships are sparse or causing noise.\n\n• Enabled: Entity-based expansion, better recall, may introduce noise\n• Disabled: Chunk-only expansion, more focused results\n• Effect: Controls whether entity relationships influence chunk retrieval\n• Symptom if disabled: Related chunks sharing entities may be missed',
        [
          ['Neo4j Graph Traversal', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Entity Relationships', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Graph Expansion', 'https://en.wikipedia.org/wiki/Graph_traversal'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Chunk Mode', 'info']]
      ),
      GRAPH_CHUNK_ENTITY_EXPANSION_WEIGHT: L(
        'Chunk Entity Expansion Weight',
        'Blend weight for entity-expansion scores relative to seed chunk scores when entity expansion is enabled. Higher values (0.7-1.0) favor entity-expanded chunks, lower values (0.3-0.6) favor seed chunks. Recommended: 0.8 for balanced blending.\n\nSweet spot: 0.8 for production systems. Use 0.6-0.7 when seed chunks are more reliable. Use 0.9-1.0 when entity relationships are highly trustworthy. Use 0.3-0.5 when entity expansion is experimental or noisy.\n\n• Range: 0.0-1.0 (typical: 0.5-0.9)\n• Seed-focused: 0.5-0.6 (favor seed chunks)\n• Balanced: 0.7-0.8 (recommended)\n• Entity-focused: 0.9-1.0 (favor entity expansion)\n• Effect: Higher = more weight to entity-expanded chunks\n• Symptom too low: Entity expansion underutilized\n• Symptom too high: Seed chunks undervalued',
        [
          ['Score Blending', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Traversal', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Weighted Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Graph Search', '/docs/retrieval/graph.md']
        ],
        [['Advanced', 'info']]
      ),

      // Fusion
      FUSION_METHOD: L(
        'Fusion Method',
        'Method for combining results from vector, sparse, and graph search: "rrf" (Reciprocal Rank Fusion) or "weighted" (score-based weighted sum). RRF combines ranking positions without score normalization, making it robust to different score scales. Weighted fusion requires normalized scores and allows fine-grained control over modality weights.\n\nSweet spot: "rrf" for most use cases. RRF is simpler, more robust, and doesn\'t require score normalization. Use "weighted" when you need precise control over modality weights or when score distributions are well-calibrated.\n\n• RRF: Position-based fusion, robust to score scales, simpler\n• Weighted: Score-based fusion, requires normalization, more control\n• Effect: Determines how tri-brid results are combined\n• Symptom wrong method: Suboptimal result ranking',
        [
          ['Reciprocal Rank Fusion', 'https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf'],
          ['RRF Paper', 'https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/'],
          ['Data Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Fusion Strategies', '/docs/retrieval/fusion.md']
        ],
        [['Core Setting', 'info']]
      ),
      FUSION_VECTOR_WEIGHT: L(
        'Vector Weight',
        'Weight assigned to vector (pgvector) search results in weighted fusion mode. Higher values (0.5-0.7) favor semantic matches, lower values (0.2-0.4) reduce semantic influence. Weights must sum to ~1.0 with sparse and graph weights. Recommended: 0.4 for balanced tri-brid retrieval.\n\nSweet spot: 0.4 for balanced systems. Use 0.5-0.6 when semantic matching is critical (e.g., finding conceptually similar code). Use 0.2-0.3 when keyword matching is more important than semantics.\n\n• Range: 0.0-1.0 (must sum with sparse + graph ≈ 1.0)\n• Keyword-focused: 0.2-0.3 (lower semantic weight)\n• Balanced: 0.4 (recommended)\n• Semantic-focused: 0.5-0.6 (higher semantic weight)\n• Effect: Higher = more weight to vector search results\n• Symptom too high: Semantic matches dominate, keyword matches buried\n• Symptom too low: Semantic matches undervalued',
        [
          ['Hybrid Search', 'https://www.pinecone.io/learn/hybrid-search-intro/'],
          ['Weighted Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Fusion Strategies', 'https://arxiv.org/abs/2402.14734'],
          ['Fusion Configuration', '/docs/retrieval/fusion.md']
        ],
        [['Weighted Mode', 'info']]
      ),
      FUSION_SPARSE_WEIGHT: L(
        'Sparse Weight',
        'Weight assigned to sparse (BM25) search results in weighted fusion mode. Higher values (0.4-0.6) favor keyword matches, lower values (0.2-0.3) reduce keyword influence. Weights must sum to ~1.0 with vector and graph weights. Recommended: 0.3 for balanced tri-brid retrieval.\n\nSweet spot: 0.3 for balanced systems. Use 0.4-0.5 when exact keyword matching is critical (e.g., finding specific function names or error codes). Use 0.2 when semantic and graph search are more important.\n\n• Range: 0.0-1.0 (must sum with vector + graph ≈ 1.0)\n• Semantic-focused: 0.2 (lower keyword weight)\n• Balanced: 0.3 (recommended)\n• Keyword-focused: 0.4-0.5 (higher keyword weight)\n• Effect: Higher = more weight to sparse search results\n• Symptom too high: Keyword matches dominate, semantic matches buried\n• Symptom too low: Keyword matches undervalued',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Hybrid Search', 'https://www.elastic.co/search-labs/blog/improving-information-retrieval-elastic-stack-hybrid'],
          ['Weighted Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Fusion Configuration', '/docs/retrieval/fusion.md']
        ],
        [['Weighted Mode', 'info']]
      ),
      FUSION_GRAPH_WEIGHT: L(
        'Graph Weight',
        'Weight assigned to graph (Neo4j) search results in weighted fusion mode. Higher values (0.4-0.6) favor structural relationships, lower values (0.2-0.3) reduce graph influence. Weights must sum to ~1.0 with vector and sparse weights. Recommended: 0.3 for balanced tri-brid retrieval.\n\nSweet spot: 0.3 for balanced systems. Use 0.4-0.5 when graph relationships are critical (e.g., finding code that calls or imports specific functions). Use 0.2 when vector and sparse search are more important.\n\n• Range: 0.0-1.0 (must sum with vector + sparse ≈ 1.0)\n• Vector/sparse-focused: 0.2 (lower graph weight)\n• Balanced: 0.3 (recommended)\n• Graph-focused: 0.4-0.5 (higher graph weight)\n• Effect: Higher = more weight to graph search results\n• Symptom too high: Graph matches dominate, other modalities buried\n• Symptom too low: Graph relationships undervalued',
        [
          ['Neo4j GraphRAG', 'https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html'],
          ['Graph Traversal', 'https://neo4j.com/blog/developer/graph-traversal-graphrag-python-package'],
          ['Weighted Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Fusion Configuration', '/docs/retrieval/fusion.md']
        ],
        [['Weighted Mode', 'info']]
      ),
      FUSION_RRF_K: L(
        'RRF k Parameter',
        'Smoothing constant for Reciprocal Rank Fusion. Higher values (80-120) give more weight to top-ranked results, lower values (40-60) distribute weight more evenly across ranks. The original RRF paper used k=60, which is near-optimal for most cases. Recommended: 60 for standard RRF behavior.\n\nSweet spot: 60 for production systems (matches original RRF paper). Use 40-50 when you want more uniform weight distribution (less emphasis on top ranks). Use 80-100 when top-ranked results are highly reliable and should dominate.\n\n• Range: 1-200 (typical: 40-100)\n• Uniform weights: 40-50 (less top-rank emphasis)\n• Standard RRF: 60 (recommended, original paper)\n• Top-rank focused: 80-100 (more emphasis on top results)\n• Effect: Higher = more weight to top-ranked results\n• Symptom too low: Top results undervalued\n• Symptom too high: Lower-ranked results ignored',
        [
          ['RRF Original Paper', 'https://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf'],
          ['RRF Research', 'https://research.google/pubs/reciprocal-rank-fusion-outperforms-condorcet-and-individual-rank-learning-methods/'],
          ['Reciprocal Rank Fusion', 'https://en.wikipedia.org/wiki/Reciprocal_rank_fusion'],
          ['Fusion Configuration', '/docs/retrieval/fusion.md']
        ],
        [['RRF Mode', 'info']]
      ),
      FUSION_NORMALIZE_SCORES: L(
        'Normalize Scores',
        'Normalize scores from vector, sparse, and graph search to [0,1] range before fusion. This ensures scores from different modalities are comparable when using weighted fusion. When disabled, raw scores are used directly (may cause one modality to dominate). Recommended: enabled for weighted fusion, not needed for RRF.\n\nSweet spot: enabled for weighted fusion mode. Normalization prevents one modality from dominating due to different score scales. For RRF mode, normalization is unnecessary since RRF uses ranking positions, not scores.\n\n• Enabled: Scores normalized to [0,1], comparable across modalities\n• Disabled: Raw scores used, may cause modality imbalance\n• Effect: Controls score normalization before weighted fusion\n• Symptom if disabled: One modality may dominate due to score scale differences',
        [
          ['Score Normalization', 'https://link.springer.com/chapter/10.1007/11880592_57'],
          ['Normalization Methods', 'https://codecademy.com/article/min-max-zscore-normalization'],
          ['Data Fusion', 'https://en.wikipedia.org/wiki/Data_fusion'],
          ['Fusion Configuration', '/docs/retrieval/fusion.md']
        ],
        [['Weighted Mode', 'info']]
      ),

      // Neo4j Storage
      neo4j_uri: L(
        'Neo4j Connection URI',
        'Neo4j database connection URI using Bolt protocol. Format: <SCHEME>://<HOST>[:<PORT>]. Schemes: "bolt" (no encryption), "bolt+s" (TLS with CA cert), "bolt+ssc" (TLS with self-signed cert), "neo4j" (routing-aware), "neo4j+s" (routing + TLS). Default: bolt://localhost:7687. Use "neo4j" schemes for cluster routing, "bolt" schemes for direct connections.\n\nSweet spot: bolt://localhost:7687 for local development, neo4j+s://your-cluster:7687 for production clusters. Use "bolt+s" or "neo4j+s" for encrypted connections. Use "bolt+ssc" or "neo4j+ssc" for self-signed certificates.\n\n• Local dev: bolt://localhost:7687\n• Production cluster: neo4j+s://cluster-host:7687\n• Direct connection: bolt://host:7687\n• Encrypted: bolt+s://host:7687 (CA cert) or bolt+ssc://host:7687 (self-signed)\n• Effect: Determines how the system connects to Neo4j\n• Symptom wrong URI: Connection failures, authentication errors',
        [
          ['Neo4j URI Schemes', 'https://neo4j.com/docs/upgrade-migration-guide/current/version-4/migration/drivers/new-uri-schemes/'],
          ['Bolt Protocol', 'https://neo4j.com/docs/bolt/current/'],
          ['Connection Configuration', 'https://neo4j.com/docs/java-manual/current/connect-advanced/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Core Setting', 'info']]
      ),
      neo4j_user: L(
        'Neo4j Username',
        'Neo4j database authentication username. Default: "neo4j". Used for basic authentication along with the password. For Kerberos or bearer token authentication, different configuration is required. The username must match a Neo4j user account with appropriate permissions.\n\nSweet spot: "neo4j" for default installations, custom username for production deployments. Use a dedicated service account with minimal required permissions rather than the admin account. Store credentials securely (environment variables, not in config files).\n\n• Default: neo4j (initial admin user)\n• Production: Custom service account with minimal permissions\n• Security: Use environment variables, not config files\n• Effect: Determines authentication identity\n• Symptom wrong user: Authentication failures',
        [
          ['Neo4j Authentication', 'https://neo4j.com/docs/java-manual/current/connect-advanced/'],
          ['Connection Configuration', 'https://neo4j.com/docs/browser-manual/current/operations/dbms-connection/'],
          ['Security Best Practices', 'https://neo4j.com/product/neo4j-graph-database/security'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Security', 'warn']]
      ),
      neo4j_password: L(
        'Neo4j Password',
        'Neo4j database authentication password. Required for basic authentication along with the username. Default: empty (must be set). For security, use environment variables rather than storing passwords in config files. The password must match the Neo4j user account.\n\nSweet spot: Store in environment variable (e.g., NEO4J_PASSWORD), not in config files. Use strong passwords for production deployments. Rotate passwords regularly. For initial setup, Neo4j requires password change on first login.\n\n• Security: Use environment variables, never store in config files\n• Production: Strong passwords, regular rotation\n• Initial setup: Neo4j requires password change on first login\n• Effect: Determines authentication credentials\n• Symptom wrong password: Authentication failures',
        [
          ['Neo4j Authentication', 'https://neo4j.com/docs/java-manual/current/connect-advanced/'],
          ['Security Best Practices', 'https://neo4j.com/product/neo4j-graph-database/security'],
          ['Connection Configuration', 'https://neo4j.com/docs/browser-manual/current/operations/dbms-connection/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Security', 'err']]
      ),
      neo4j_database: L(
        'Neo4j Database Name',
        'Neo4j database name used when database_mode is "shared". All corpora share this single database with corpus_id filtering. Default: "neo4j". For "per_corpus" mode, this is ignored and databases are named using the prefix + corpus_id pattern. Must be a valid Neo4j database name.\n\nSweet spot: "neo4j" for default installations, custom name for shared multi-corpus setups. Use descriptive names that indicate purpose (e.g., "tribrid_shared"). For per_corpus mode, this setting is ignored.\n\n• Default: neo4j (standard database name)\n• Shared mode: Single database name for all corpora\n• Per-corpus mode: Ignored (uses prefix + corpus_id)\n• Effect: Determines database name in shared mode\n• Symptom wrong name: Database not found errors',
        [
          ['Neo4j Multi-Database', 'https://assets.neo4j.com/Official-Materials/Multi+DB+Considerations.pdf'],
          ['Database Isolation', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Database Management', 'https://neo4j.com/docs/cypher-manual/current/administration/databases/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Shared Mode', 'info']]
      ),
      neo4j_database_mode: L(
        'Neo4j Database Mode',
        'Database isolation strategy: "shared" uses a single Neo4j database for all corpora (Community-compatible, requires corpus_id filtering), "per_corpus" uses separate databases per corpus (Enterprise multi-database, better isolation). Shared mode works with Neo4j Community Edition, per_corpus requires Enterprise Edition.\n\nSweet spot: "shared" for Community Edition or small deployments, "per_corpus" for Enterprise Edition with strict isolation needs. Per_corpus mode provides better performance (no filtering) and isolation but requires Enterprise licensing.\n\n• Shared: Single database, corpus_id filtering, Community-compatible\n• Per-corpus: Separate databases, no filtering needed, Enterprise required\n• Effect: Determines database isolation strategy\n• Symptom wrong mode: Performance issues (shared) or licensing errors (per_corpus without Enterprise)',
        [
          ['Neo4j Multi-Database', 'https://assets.neo4j.com/Official-Materials/Multi+DB+Considerations.pdf'],
          ['Database Isolation', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Enterprise Features', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Enterprise', 'warn']]
      ),
      neo4j_database_prefix: L(
        'Neo4j Database Prefix',
        'Prefix applied to per-corpus database names when database_mode is "per_corpus". Database names are constructed as: {prefix}{corpus_id} (sanitized). Default: "tribrid_". The prefix helps identify TriBridRAG-managed databases and prevents conflicts with other applications. Must be a valid database name prefix.\n\nSweet spot: "tribrid_" for standard deployments, custom prefix for multi-tenant or organizational needs. Use descriptive prefixes that indicate purpose or organization. Database names are sanitized (lowercase, alphanumeric + underscore only).\n\n• Default: tribrid_\n• Per-corpus mode: Applied to corpus_id to form database name\n• Shared mode: Ignored\n• Effect: Determines database naming pattern in per_corpus mode\n• Symptom wrong prefix: Database naming conflicts or confusion',
        [
          ['Neo4j Multi-Database', 'https://assets.neo4j.com/Official-Materials/Multi+DB+Considerations.pdf'],
          ['Database Isolation', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Database Naming', 'https://neo4j.com/docs/cypher-manual/current/administration/databases/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Per-corpus Mode', 'info']]
      ),
      neo4j_auto_create_databases: L(
        'Neo4j Auto-Create Databases',
        'Automatically create per-corpus Neo4j databases when missing (Enterprise multi-database only). When enabled, creating a corpus will create its Neo4j database automatically if it doesn\'t exist. When disabled, databases must be created manually before indexing. Requires Neo4j Enterprise Edition and database_mode="per_corpus".\n\nSweet spot: enabled for Enterprise deployments. Auto-creation simplifies corpus management and ensures databases exist when needed. Disable if you need manual control over database creation or want to pre-create databases with custom settings.\n\n• Enabled: Automatic database creation on corpus creation\n• Disabled: Manual database creation required\n• Requirements: Enterprise Edition, per_corpus mode\n• Effect: Controls automatic database provisioning\n• Symptom if disabled: Database not found errors when indexing new corpus',
        [
          ['Neo4j Multi-Database', 'https://assets.neo4j.com/Official-Materials/Multi+DB+Considerations.pdf'],
          ['Database Isolation', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Enterprise Features', 'https://neo4j.com/docs/operations-manual/current/scalability/concepts/'],
          ['Database Configuration', '/docs/database.md']
        ],
        [['Enterprise', 'warn']]
      ),

      // Data Quality - Chunk Summaries
      CHUNK_SUMMARIES_MAX: L(
        'Max Chunk Summaries',
        'Maximum number of chunk summaries to generate per corpus. Chunk summaries provide structured metadata (purpose, symbols, keywords) for each code chunk, improving retrieval quality. Higher values (200-500) provide more comprehensive coverage but increase indexing time and storage. Lower values (50-100) are faster but may miss important chunks.\n\nSweet spot: 100 for balanced coverage. Use 50-75 for large codebases where indexing speed matters. Use 200-300 when comprehensive coverage is critical. Use 500+ only for small, critical codebases.\n\n• Range: 10-1000 (typical: 50-300)\n• Fast indexing: 50-75 (lower coverage)\n• Balanced: 100 (recommended)\n• Comprehensive: 200-300 (higher coverage)\n• Effect: Higher = more summaries, better coverage, longer indexing\n• Symptom too low: Important chunks missing summaries\n• Symptom too high: Slow indexing, storage overhead',
        [
          ['Chunk Summarization', 'https://vectify.ai/blog/LargeDocumentSummarization'],
          ['Code Analysis', 'https://llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex-6207e5d3fec5'],
          ['Document Summarization', 'https://cookbook.openai.com/examples/summarizing_long_documents'],
          ['Data Quality', '/docs/guides/corpus.md']
        ],
        [['Indexing', 'info']]
      ),
      CHUNK_SUMMARIES_EXCLUDE_DIRS: L(
        'Exclude Directories',
        'List of directory paths to skip when building chunk summaries. Directories matching these paths (exact or prefix) are excluded from summarization. Useful for excluding test files, documentation, generated code, or third-party dependencies. Default includes: docs, tests, node_modules, venv, dist, etc.\n\nSweet spot: Default list for most projects. Add project-specific directories (e.g., "legacy", "deprecated") to improve summary quality. Remove defaults only if you want to include tests or docs in summaries.\n\n• Format: Comma-separated or newline-separated directory paths\n• Default: docs, tests, node_modules, venv, dist, etc.\n• Effect: Filters out directories from summarization\n• Symptom if too permissive: Low-quality summaries from test files or dependencies',
        [
          ['Code Filtering', 'https://en.wikipedia.org/wiki/Code_filtering'],
          ['File Exclusion Patterns', 'https://en.wikipedia.org/wiki/Glob_(programming)'],
          ['Data Quality', '/docs/guides/corpus.md'],
          ['Indexing Configuration', '/docs/indexing.md']
        ],
        [['Filtering', 'info']]
      ),
      CHUNK_SUMMARIES_EXCLUDE_PATTERNS: L(
        'Exclude Patterns',
        'List of glob patterns (e.g., "*.min.js", "*.lock", "**/*.test.ts") to skip when building chunk summaries. Files matching these patterns are excluded from summarization. Useful for excluding generated files, lock files, minified code, or test files. More flexible than directory exclusion.\n\nSweet spot: Add patterns for generated or minified files (e.g., "*.min.js", "*.bundle.js"). Include test file patterns if you don\'t want tests summarized (e.g., "**/*.test.ts", "**/*.spec.js"). Leave empty if you want all files summarized.\n\n• Format: Comma-separated or newline-separated glob patterns\n• Examples: *.min.js, *.lock, **/*.test.ts, dist/**\n• Effect: Filters out files matching patterns from summarization\n• Symptom if too permissive: Low-quality summaries from generated or test files',
        [
          ['Glob Patterns', 'https://en.wikipedia.org/wiki/Glob_(programming)'],
          ['File Filtering', 'https://en.wikipedia.org/wiki/File_system'],
          ['Data Quality', '/docs/guides/corpus.md'],
          ['Indexing Configuration', '/docs/indexing.md']
        ],
        [['Filtering', 'info']]
      ),
      CHUNK_SUMMARIES_EXCLUDE_KEYWORDS: L(
        'Exclude Keywords',
        'List of keywords that, when present in code, cause the chunk to be skipped during summarization. Useful for excluding deprecated code, TODO comments, legacy implementations, or experimental features. Case-insensitive matching.\n\nSweet spot: Add project-specific keywords (e.g., "deprecated", "legacy", "TODO", "FIXME") to improve summary quality. Leave empty if you want all code summarized regardless of keywords.\n\n• Format: Comma-separated or newline-separated keywords\n• Examples: deprecated, legacy, TODO, FIXME, experimental\n• Effect: Filters out chunks containing keywords from summarization\n• Symptom if too permissive: Low-quality summaries from deprecated or incomplete code',
        [
          ['Code Filtering', 'https://en.wikipedia.org/wiki/Code_filtering'],
          ['Keyword Extraction', 'https://en.wikipedia.org/wiki/Keyword_extraction'],
          ['Data Quality', '/docs/guides/corpus.md'],
          ['Indexing Configuration', '/docs/indexing.md']
        ],
        [['Filtering', 'info']]
      ),
      CHUNK_SUMMARIES_ENRICH_DEFAULT: L(
        'Chunk Summaries Enrich Default',
        'Enable chunk summary enrichment by default when building summaries. When enabled, summaries include enriched metadata (detailed purpose, technical details, domain concepts) using LLM analysis. When disabled, summaries use lightweight extraction only. Enrichment improves quality but increases indexing time and cost.\n\nSweet spot: enabled for production systems. Enriched summaries provide better retrieval quality and more detailed metadata. Disable only if indexing speed or cost is a concern, or if lightweight summaries are sufficient.\n\n• Enabled: Full enrichment with LLM analysis (recommended)\n• Disabled: Lightweight extraction only (faster, lower cost)\n• Effect: Controls whether summaries are enriched with detailed metadata\n• Symptom if disabled: Less detailed summaries, potentially lower retrieval quality',
        [
          ['Code Enrichment', 'https://cookbook.openai.com/examples/summarizing_long_documents'],
          ['Chunk Summarization', 'https://vectify.ai/blog/LargeDocumentSummarization'],
          ['Data Quality', '/docs/guides/corpus.md'],
          ['Indexing Configuration', '/docs/indexing.md']
        ],
        [['Enrichment', 'info']]
      ),

      // Data Quality - Keywords
      KEYWORDS_MAX_PER_REPO: L(
        'Keywords Max Per Corpus',
        'Maximum number of discriminative keywords to extract per corpus. Keywords are computed using TF-IDF to identify terms that distinguish this corpus from others. Higher values (100-300) provide more keyword coverage but may include less discriminative terms. Lower values (20-50) focus on the most distinctive keywords.\n\nSweet spot: 50 for balanced keyword extraction. Use 20-30 for focused keyword sets (most discriminative only). Use 100-200 when comprehensive keyword coverage is needed. Use 300+ only for very large or diverse corpora.\n\n• Range: 10-500 (typical: 20-200)\n• Focused: 20-30 (most discriminative)\n• Balanced: 50 (recommended)\n• Comprehensive: 100-200 (broader coverage)\n• Effect: Higher = more keywords, broader coverage, less discriminative\n• Symptom too low: Important keywords missed\n• Symptom too high: Less discriminative keywords included',
        [
          ['TF-IDF Keyword Extraction', 'https://github.com/tonifuc3m/document_selection_tfidf'],
          ['Keyword Extraction', 'https://github.com/airKlizz/CustomizedTFIDF'],
          ['TF-IDF Algorithm', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf'],
          ['Data Quality', '/docs/guides/corpus.md']
        ],
        [['Keyword Extraction', 'info']]
      ),
      KEYWORDS_MIN_FREQ: L(
        'Keywords Min Frequency',
        'Minimum term frequency required for a keyword to be included. Terms must appear at least this many times in the corpus to be considered. Higher values (5-10) ensure keywords are common enough to be meaningful, lower values (1-3) allow rare but distinctive terms. Recommended: 3 for balanced filtering.\n\nSweet spot: 3 for most corpora. Use 1-2 when you want to include rare but distinctive terms (e.g., unique function names). Use 5-7 when you want only common, well-established keywords. Use 10+ only for very large corpora.\n\n• Range: 1-10 (typical: 2-5)\n• Rare terms: 1-2 (include distinctive rare terms)\n• Balanced: 3 (recommended)\n• Common terms: 5-7 (only well-established keywords)\n• Effect: Higher = fewer keywords, more common terms only\n• Symptom too low: Rare, potentially noisy keywords included\n• Symptom too high: Important distinctive keywords filtered out',
        [
          ['TF-IDF Keyword Extraction', 'https://github.com/tonifuc3m/document_selection_tfidf'],
          ['Term Frequency', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf'],
          ['Keyword Extraction', 'https://github.com/MOoTawaty/TF-IDF-keywords-extraction'],
          ['Data Quality', '/docs/guides/corpus.md']
        ],
        [['Keyword Extraction', 'info']]
      ),
      KEYWORDS_BOOST: L(
        'Keywords Boost',
        'Score boost multiplier applied to search results that match corpus keywords. Higher values (1.5-2.0) strongly favor keyword matches, lower values (1.1-1.3) provide mild preference. The boost is multiplied with the base retrieval score. Recommended: 1.3 for balanced keyword preference.\n\nSweet spot: 1.3 for balanced systems. Use 1.1-1.2 for mild keyword preference (keyword matches slightly favored). Use 1.5-2.0 when keywords are highly reliable indicators of relevance. Use 2.5+ only when keywords are definitive relevance signals.\n\n• Range: 1.0-3.0 (typical: 1.1-2.0)\n• Mild boost: 1.1-1.2 (slight preference)\n• Balanced: 1.3 (recommended)\n• Strong boost: 1.5-2.0 (strong preference)\n• Effect: Higher = more weight to keyword matches\n• Symptom too low: Keyword matches undervalued\n• Symptom too high: Keyword matches dominate, other signals ignored',
        [
          ['Score Boosting', 'https://en.wikipedia.org/wiki/Relevance_(information_retrieval)'],
          ['TF-IDF Scoring', 'https://en.wikipedia.org/wiki/Tf%E2%80%93idf'],
          ['Keyword Extraction', 'https://github.com/airKlizz/CustomizedTFIDF'],
          ['Data Quality', '/docs/guides/corpus.md']
        ],
        [['Scoring', 'info']]
      ),
      KEYWORDS_AUTO_GENERATE: L(
        'Keywords Auto-Generate',
        'Automatically generate discriminative keywords during indexing. When enabled, keywords are computed and stored automatically when a corpus is indexed. When disabled, keywords must be generated manually via the API. Recommended: enabled for automatic keyword management.\n\nSweet spot: enabled for production systems. Auto-generation ensures keywords are always up-to-date with the latest corpus content. Disable only if you want manual control over keyword generation timing or want to use pre-computed keywords.\n\n• Enabled: Automatic keyword generation during indexing (recommended)\n• Disabled: Manual keyword generation required\n• Effect: Controls automatic keyword computation\n• Symptom if disabled: Keywords may be stale or missing',
        [
          ['TF-IDF Keyword Extraction', 'https://github.com/tonifuc3m/document_selection_tfidf'],
          ['Keyword Extraction', 'https://github.com/airKlizz/CustomizedTFIDF'],
          ['Automatic Indexing', 'https://en.wikipedia.org/wiki/Index_(search_engine)'],
          ['Data Quality', '/docs/guides/corpus.md']
        ],
        [['Auto-Generation', 'info']]
      ),
      KEYWORDS_REFRESH_HOURS: L(
        'Keywords Refresh Hours',
        'Hours between automatic keyword refresh. When auto-generate is enabled, keywords are recomputed after this interval to reflect corpus changes. Lower values (12-24) keep keywords more current but increase computation cost. Higher values (48-168) reduce cost but keywords may become stale.\n\nSweet spot: 24 hours for most corpora. Use 12 hours for rapidly changing codebases where keyword freshness is critical. Use 48-72 hours for stable codebases where frequent refresh isn\'t needed. Use 168+ (weekly) only for very stable corpora.\n\n• Range: 1-168 (typical: 12-72)\n• Rapid changes: 12 (more frequent refresh)\n• Balanced: 24 (recommended)\n• Stable codebase: 48-72 (less frequent refresh)\n• Effect: Higher = less frequent refresh, lower cost, potentially stale keywords\n• Symptom too low: Unnecessary refresh overhead\n• Symptom too high: Stale keywords, reduced retrieval quality',
        [
          ['TF-IDF Keyword Extraction', 'https://github.com/tonifuc3m/document_selection_tfidf'],
          ['Keyword Refresh', 'https://en.wikipedia.org/wiki/Index_(search_engine)'],
          ['Data Quality', '/docs/guides/corpus.md'],
          ['Indexing Configuration', '/docs/indexing.md']
        ],
        [['Refresh Interval', 'info']]
      ),

      // Confidence
      CONF_TOP1: L(
        'Confidence Top-1',
        'Minimum confidence score (0.0-1.0) required to accept the top-1 result without further processing. If the best result scores above this threshold, it\'s returned immediately. Lower values (0.55-0.60) produce more answers but risk lower quality. Higher values (0.65-0.70) ensure precision but may trigger unnecessary query rewrites. Recommended: 0.60-0.65 for balanced precision/recall.\n\nSweet spot: 0.60-0.65 for production systems. Use 0.65-0.70 when precision is critical and false positives are costly (e.g., production debugging, compliance queries). Use 0.55-0.60 for exploratory search where recall matters more. This threshold gates whether the system accepts the top result or attempts query rewriting for better candidates.\n\nConfidence is computed from hybrid fusion scores, reranking scores, and score boosting. A score of 0.65 means high confidence that the result is relevant. Below the threshold, the system may rewrite the query (if MQ_REWRITES > 1) and try again. Tune this alongside CONF_AVG5 and CONF_ANY for optimal answer rate vs quality.\n\n• Range: 0.55-0.75 (typical)\n• Exploratory: 0.55-0.60 (favor recall)\n• Balanced: 0.60-0.65 (recommended)\n• Precision-critical: 0.65-0.70 (favor precision)\n• Effect: Lower = more answers, higher risk; Higher = fewer answers, higher quality\n• Triggers: Query rewriting when below threshold',
        [
          ['Confidence Thresholds', 'https://en.wikipedia.org/wiki/Confidence_interval'],
          ['Precision-Recall Tradeoff', 'https://developers.google.com/machine-learning/crash-course/classification/precision-and-recall'],
          ['Score Calibration', '/docs/RETRIEVAL.md#confidence-scoring'],
          ['Decision Boundaries', 'https://en.wikipedia.org/wiki/Decision_boundary']
        ],
        [['Advanced RAG tuning', 'info'], ['Affects answer rate', 'warn']]
      ),
      CONF_AVG5: L(
        'Confidence Avg-5',
        'Average confidence score of the top-5 results, used as a gate for query rewriting iterations. If avg(top-5) is below this threshold, the system may rewrite the query and try again. Lower values (0.50-0.53) reduce retries, accepting more borderline results. Higher values (0.56-0.60) force more rewrites for higher quality. Recommended: 0.52-0.58 for balanced behavior.\n\nSweet spot: 0.52-0.55 for production systems. Use 0.55-0.58 when quality is paramount and you have budget for extra LLM calls (query rewriting). Use 0.50-0.52 for cost-sensitive scenarios or when initial retrieval is already high-quality. This threshold examines the top-5 results as a group - even if top-1 is strong, weak supporting results might trigger a rewrite.\n\nAVG5 complements TOP1: TOP1 checks the best result, AVG5 checks overall result quality. A query might pass TOP1 (strong top result) but fail AVG5 (weak supporting results), triggering refinement. Conversely, borderline TOP1 with strong AVG5 might proceed. Tune both thresholds together for optimal precision/recall trade-offs.\n\n• Range: 0.48-0.60 (typical)\n• Cost-sensitive: 0.50-0.52 (fewer retries)\n• Balanced: 0.52-0.55 (recommended)\n• Quality-focused: 0.55-0.58 (more retries)\n• Effect: Higher = more query rewrites, better quality, higher cost\n• Interacts with: CONF_TOP1 (top result threshold), MQ_REWRITES (rewrite budget)',
        [
          ['Iterative Refinement', 'https://en.wikipedia.org/wiki/Iterative_refinement'],
          ['Query Reformulation', 'https://en.wikipedia.org/wiki/Query_reformulation'],
          ['Confidence Scoring', '/docs/RETRIEVAL.md#confidence-thresholds'],
          ['Multi-Query RAG', 'https://arxiv.org/abs/2305.14283']
        ],
        [['Advanced RAG tuning', 'info'], ['Controls retries', 'warn']]
      ),
      CONF_ANY: L(
        'Confidence Any',
        'Fallback threshold - proceed with retrieval if ANY single result exceeds this score, even if top-1 or avg-5 thresholds aren\'t met. This prevents the system from giving up when there\'s at least one decent match. Lower values (0.30-0.40) are more permissive, returning results even with weak confidence. Higher values (0.45-0.50) maintain quality standards. Recommended: 0.35-0.45 as a safety net.',
        [
          ['Fallback Strategies', 'https://en.wikipedia.org/wiki/Fault_tolerance'],
          ['Confidence Bounds', '/docs/RETRIEVAL.md#confidence-fallback'],
          ['Decision Boundaries', 'https://en.wikipedia.org/wiki/Decision_boundary']
        ],
        [['Safety net', 'info']]
      ),

      // Netlify
      NETLIFY_API_KEY: L('Netlify API Key', 'API key for the netlify_deploy MCP tool to trigger automated site deployments and builds. Get your personal access token from Netlify dashboard under User Settings > Applications > Personal Access Tokens. Used to programmatically deploy site updates from your workflow.', [
        ['Netlify: Access Tokens', 'https://docs.netlify.com/api/get-started/#access-tokens'],
        ['MCP README', '/docs/MCP_README.md']
      ]),
      NETLIFY_DOMAINS: L(
        'Netlify Domains',
        'Comma-separated list of Netlify site domains for the netlify_deploy MCP tool (e.g., "mysite.netlify.app,docs.mysite.com"). When deploying, the tool targets these specific sites. Find your site domains in Netlify dashboard under Site Settings > Domain Management. Multiple domains allow you to deploy to staging and production from the same config.',
        [
          ['Netlify Sites', 'https://docs.netlify.com/domains-https/custom-domains/'],
          ['MCP Tools Guide', '/docs/MCP_README.md'],
          ['Netlify Dashboard', 'https://app.netlify.com/']
        ]
      ),

      // Misc
      THREAD_ID: L(
        'Thread ID',
        'Unique identifier for conversation session state in LangGraph checkpoints or CLI chat. Use a stable value (e.g., "session-123", user email, UUID) to preserve chat history and context across runs. Different thread IDs create separate conversation contexts. Useful for multi-user systems or A/B testing different conversation flows. Stored in Redis when available.',
        [
          ['LangGraph Checkpoints', 'https://langchain-ai.github.io/langgraph/concepts/persistence/'],
          ['Thread Management', 'https://langchain-ai.github.io/langgraph/how-tos/persistence/#threads'],
          ['CLI Chat Guide', '/docs/CLI_CHAT.md#sessions']
        ]
      ),
      TRANSFORMERS_TRUST_REMOTE_CODE: L(
        'Transformers: trust_remote_code',
        'SECURITY WARNING: Set to "true" only if you completely trust the model source. Allows HuggingFace Transformers to execute arbitrary Python code from model repositories for custom architectures. Malicious models could run harmful code on your system. Only enable for models from verified sources (official HuggingFace, your organization). Required for some specialized models with custom model classes.',
        [
          ['Security Notes', 'https://huggingface.co/docs/transformers/installation#security-notes'],
          ['Custom Code in Models', 'https://huggingface.co/docs/transformers/custom_models'],
          ['Model Security', 'https://huggingface.co/docs/hub/security']
        ],
        [['Security risk', 'warn'], ['Only for trusted models', 'warn']]
      ),
      LANGCHAIN_TRACING_V2: L(
        'LangChain Tracing',
        'Reserved for future LangSmith integration (v2 tracing protocol). TriBridRAG currently captures local, in-memory request traces for UI preview and does not export traces to LangSmith yet.',
        [
          ['LangSmith Setup', 'https://docs.smith.langchain.com/'],
          ['Tracing Guide', 'https://docs.smith.langchain.com/tracing'],
          ['How to Enable', 'https://docs.smith.langchain.com/tracing/faq#how-do-i-turn-on-tracing']
        ],
        [['Requires API key', 'info']]
      ),

      GEN_MODEL_HTTP: L(
        'HTTP Channel Model',
        'Override GEN_MODEL specifically for HTTP API requests (GUI, external API calls). Useful for serving different models to different channels - e.g., use gpt-4o for production HTTP but qwen-coder locally. If not set, falls back to GEN_MODEL. Example use case: cheaper models for public API, expensive models for internal tools.',
        [
          ['Model Recommendations', '/docs/MODEL_RECOMMENDATIONS.md'],
          ['Model Selection', 'https://platform.openai.com/docs/models'],
          ['Cost & Performance', '/docs/PERFORMANCE_AND_COST.md']
        ],
        [['Channel-specific', 'info']]
      ),
      GEN_MODEL_MCP: L(
        'MCP Channel Model',
        'Override GEN_MODEL for MCP tool invocations only. Use a lighter/cheaper model for MCP tools since tool calls are typically simpler than complex reasoning. Example: gpt-4o-mini for MCP, gpt-4o for main chat. Reduces costs when tools are called frequently (search, file operations, etc.). If not set, uses GEN_MODEL.',
        [
          ['MCP Tools Guide', '/docs/MCP_README.md'],
          ['Model Recommendations', '/docs/MODEL_RECOMMENDATIONS.md'],
          ['Model Pricing', 'https://openai.com/api/pricing/']
        ],
        [['Cost savings', 'info'], ['Channel-specific', 'info']]
      ),
      GEN_MODEL_CLI: L(
        'CLI Channel Model',
        'Override GEN_MODEL for CLI chat sessions only. Allows using different models for terminal vs web interface - e.g., faster models for CLI iteration, higher quality for production GUI. Useful for developer workflows where CLI is for quick testing and HTTP is for end users. If not set, uses GEN_MODEL.',
        [
          ['CLI Chat', '/docs/CLI_CHAT.md'],
          ['Model Recommendations', '/docs/MODEL_RECOMMENDATIONS.md'],
          ['Model Selection Guide', '/docs/MODELS.md']
        ],
        [['Channel-specific', 'info']]
      ),

      // Additional providers
      ANTHROPIC_API_KEY: L(
        'Anthropic API Key',
        'API key for Anthropic models (Claude family: claude-3-5-sonnet, claude-3-opus, claude-instant). Required when using Claude models for generation. Get your key from Anthropic Console under Account Settings > API Keys. Claude models excel at code understanding, long context (200K tokens), and following complex instructions. Costs vary by model tier.',
        [
          ['Get API Key', 'https://console.anthropic.com/settings/keys'],
          ['Claude Models', 'https://docs.anthropic.com/en/docs/about-claude/models'],
          ['API Quickstart', 'https://docs.anthropic.com/en/api/getting-started'],
          ['Pricing', 'https://www.anthropic.com/pricing']
        ]
      ),
      GOOGLE_API_KEY: L(
        'Google API Key',
        'API key for Google Gemini models and embedding endpoints (gemini-1.5-pro, gemini-1.5-flash, text-embedding-004). Required when using Google AI services. Create key at Google AI Studio. Gemini 1.5 Pro offers 2M token context window and multimodal capabilities. Flash variant is faster and cheaper. Great for code analysis with long context.',
        [
          ['Get API Key', 'https://ai.google.dev/gemini-api/docs/api-key'],
          ['Gemini Models', 'https://ai.google.dev/gemini-api/docs/models/gemini'],
          ['API Quickstart', 'https://ai.google.dev/gemini-api/docs/quickstart'],
          ['Pricing', 'https://ai.google.dev/pricing']
        ]
      ),
      OPENAI_BASE_URL: L(
        'OpenAI Base URL',
        'ADVANCED: Override the OpenAI API base URL for OpenAI-compatible endpoints. Use cases: local inference servers (LM Studio, vLLM, text-generation-webui), Azure OpenAI (https://YOUR_RESOURCE.openai.azure.com/), proxy services. Default: https://api.openai.com/v1. Useful for development, air-gapped environments, or cost optimization via self-hosted models.',
        [
          ['OpenAI API Reference', 'https://platform.openai.com/docs/api-reference'],
          ['Azure OpenAI', 'https://learn.microsoft.com/en-us/azure/ai-services/openai/'],
          ['LM Studio Setup', 'https://lmstudio.ai/docs/local-server'],
          ['vLLM Compatibility', 'https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html']
        ],
        [['Advanced', 'warn'], ['For compatible endpoints only', 'info']]
      ),

      // Enrichment / Cards / Indexing
      ENRICH_BACKEND: L(
        'Enrichment Backend',
        'Backend service for generating code summaries and enrichment metadata during indexing. Options: "openai" (GPT models, highest quality), "ollama" (local models, free), "mlx" (Apple Silicon optimized). Enrichment adds per-chunk summaries and keywords used by features like cards and improved reranking. Disable to speed up indexing or reduce costs.',
        [
          ['Code Enrichment', '/docs/ENRICHMENT.md'],
          ['MLX on Apple Silicon', 'https://github.com/ml-explore/mlx'],
          ['Ollama Local Models', 'https://ollama.com/library']
        ],
        [['Optional feature', 'info'], ['Increases index time', 'warn']]
      ),
      ENRICH_MODEL: L(
        'Enrichment Model',
        'Specific model name for code enrichment when ENRICH_BACKEND is set. For OpenAI: "gpt-4o-mini" (recommended, cheap), "gpt-4o" (higher quality, costly). For Ollama: specify via ENRICH_MODEL_OLLAMA instead. Smaller models (gpt-4o-mini, qwen2.5-coder:7b) balance cost and quality for summaries. Enrichment happens during indexing, not at query time.',
        [
          ['OpenAI Models', 'https://platform.openai.com/docs/models'],
          ['Model Selection Guide', '/docs/ENRICHMENT.md#model-selection'],
          ['Cost Comparison', 'https://openai.com/api/pricing/']
        ],
        [['Affects index cost', 'warn']]
      ),
      ENRICH_MODEL_OLLAMA: L(
        'Enrichment Model (Ollama)',
        'Ollama model name for code enrichment when ENRICH_BACKEND=ollama. Recommended: "qwen2.5-coder:7b" (fast, code-focused), "deepseek-coder:6.7b" (excellent code understanding), "codellama:13b" (high quality, slower). Model must be pulled via "ollama pull <model>" before use. Local enrichment is free but slower than cloud APIs.',
        [
          ['Ollama Models', 'https://ollama.com/library'],
          ['Pull Models', 'https://github.com/ollama/ollama#quickstart'],
          ['Code-Focused Models', 'https://ollama.com/search?c=tools'],
          ['Enrichment Setup', '/docs/ENRICHMENT.md#ollama']
        ],
        [['Free (local)', 'info'], ['Requires model download', 'warn']]
      ),
      ENRICH_CODE_CHUNKS: L(
        'Enrich Code Chunks',
        'Enable per-chunk code summarization during indexing. When on, each code chunk gets an AI-generated summary and keywords stored alongside the code. Powers the Cards feature (high-level code summaries) and improves reranking by providing semantic context. Increases indexing time and cost (API calls) but significantly improves retrieval quality for conceptual queries like "where is auth handled?"',
        [
          ['Cards Feature', '/docs/CARDS.md'],
          ['Code Summarization', 'https://en.wikipedia.org/wiki/Automatic_summarization'],
          ['Cards Builder Source', '/indexer/build_cards.py'],
          ['Enrichment Guide', '/docs/ENRICHMENT.md']
        ],
        [['Better retrieval', 'info'], ['Slower indexing', 'warn'], ['Costs API calls', 'warn']]
      ),
      CARDS_MAX: L(
        'Cards Max',
        'Maximum number of summary cards to load and consider during retrieval for score boosting. Cards are high-level summaries of code modules/features. Lower values (10-20) are faster but may miss relevant modules. Higher values (30-50) provide better coverage but increase memory and latency. Set to 0 to disable cards entirely. Recommended: 20-30 for balanced performance.',
        [
          ['Cards Feature Overview', '/docs/CARDS.md'],
          ['Cards Builder Source', '/indexer/build_cards.py'],
          ['Score Boosting', '/docs/RETRIEVAL.md#card-boosting']
        ],
        [['Affects memory', 'warn']]
      ),
      SKIP_DENSE: L(
        'Skip Dense Embeddings',
        'Skip vector embeddings and Qdrant during indexing to create a fast BM25-only (keyword-only) index. Useful for quick testing, CI/CD pipelines, or when Qdrant is unavailable. BM25-only mode is faster and uses less resources but loses semantic search capability - only exact keyword matches work. Not recommended for production use unless you have a purely keyword-based use case.',
        [
          ['BM25 vs Semantic', '/docs/RETRIEVAL.md#bm25-vs-dense'],
          ['Hybrid Search Benefits', 'https://www.pinecone.io/learn/hybrid-search-intro/'],
          ['Fast Indexing Guide', '/docs/INDEXING.md#bm25-only']
        ],
        [['Much faster', 'info'], ['Keyword-only', 'warn'], ['No semantic search', 'warn']]
      ),
      VENDOR_MODE: L(
        'Vendor Mode',
        'Controls scoring preference for your code vs third-party library code during reranking. "prefer_first_party" (recommended) boosts your app code (+0.06) and penalizes node_modules/vendor libs (-0.08) - best for understanding YOUR codebase. "prefer_vendor" does the opposite - useful when debugging library internals or learning from open-source code. Most users want prefer_first_party.',
        [
          ['First-Party vs Third-Party', 'https://en.wikipedia.org/wiki/First-party_and_third-party_sources'],
          ['Score Boosting Logic', '/docs/RETRIEVAL.md#vendor-mode'],
          ['Path Detection', '/docs/RETRIEVAL.md#vendor-detection']
        ],
        [['Code priority', 'info']]
      ),
      EMBEDDING_DIM: L(
        'Embedding Dimension',
        'Vector dimensionality for MXBAI/local embedding models. Common sizes: 384 (fast, lower quality), 768 (balanced, recommended), 1024 (best quality, slower). Larger dimensions capture more semantic nuance but increase Qdrant storage requirements and query latency. Must match your embedding model\'s output size. Changing this requires full reindexing - vectors of different dimensions are incompatible.',
        [
          ['Vector Embeddings', 'https://en.wikipedia.org/wiki/Word_embedding'],
          ['Dimensionality Tradeoffs', 'https://www.sbert.net/docs/pretrained_models.html#model-overview'],
          ['Qdrant Vector Config', 'https://qdrant.tech/documentation/concepts/collections/#create-a-collection'],
          ['Reindexing Guide', '/docs/INDEXING.md#full-reindex']
        ],
        [['Requires reindex','reindex'], ['Affects storage', 'warn']]
      ),
      PORT: L(
        'HTTP Port',
        'TCP port for the HTTP server that serves the GUI and API endpoints when running serve_rag. Default: 8012. Change if port 8012 is already in use by another service (common conflict: development servers). After changing, access GUI at http://127.0.0.1:<NEW_PORT>. Requires server restart to take effect.',
        [
          ['TCP Ports', 'https://en.wikipedia.org/wiki/List_of_TCP_and_UDP_port_numbers'],
          ['Port Conflicts', 'https://en.wikipedia.org/wiki/Port_scanner'],
          ['Server Configuration', '/docs/SERVER.md#port-configuration']
        ],
        [['Requires restart', 'warn']]
      ),
      TRIBRID_EDITION: L(
        'Edition',
        'Product edition identifier for feature gating in multi-tier deployments. Values: "oss" (open source, all community features), "pro" (professional tier with advanced features), "enterprise" (full feature set with support). This flag enables/disables certain UI elements and API endpoints based on licensing. Most users should leave this as "oss".',
        [
          ['Feature Matrix', '/docs/EDITIONS.md'],
          ['Licensing', '/docs/LICENSE.md'],
          ['Enterprise Features', '/docs/ENTERPRISE.md']
        ],
        [['Feature gating', 'info']]
      ),

      // Repo editor (dynamic inputs)
      repo_path: L(
        'Repository Path',
        'Absolute filesystem path to the repository directory to be indexed under this logical repo name. Example: /Users/you/projects/myapp or /home/dev/backend. This directory will be scanned for code files during indexing. Use repos.json to configure multiple repositories with different paths, keywords, and routing rules.',
        [
          ['repos.json Format', '/repos.json'],
          ['Multi-Repo Setup', '/docs/MULTI_REPO.md'],
          ['Indexing Workflow', '/docs/INDEXING.md#repository-setup']
        ]
      ),
      repo_keywords: L(
        'Repository Keywords',
        'Comma-separated keywords for query routing to this repository. When users ask questions containing these keywords, this repo is prioritized. Examples: "auth,authentication,login" or "payment,stripe,billing". Choose terms users naturally use when asking about this repo\'s domain. Helps multi-repo setups route queries to the right codebase.',
        [
          ['Query Routing', '/docs/MULTI_REPO.md#routing'],
          ['Keyword Selection', '/docs/MULTI_REPO.md#keyword-strategy'],
          ['repos.json Examples', '/repos.json']
        ],
        [['Multi-repo only', 'info']]
      ),
      repo_pathboosts: L(
        'Path Boosts',
        'Comma-separated directory path substrings to boost in search rankings for this repo. Examples: "src/,app/,lib/" boosts code in those directories. Use this to prioritize your main application code over tests, docs, or vendor code. Partial matches work - "api/" matches "src/api/", "backend/api/", etc. Boosts are applied during reranking.',
        [
          ['Score Boosting', '/docs/RETRIEVAL.md#path-boosting'],
          ['repos.json Config', '/repos.json'],
          ['Ranking Logic', '/docs/RETRIEVAL.md#ranking-algorithm']
        ],
        [['Affects ranking', 'info']]
      ),
      repo_layerbonuses: L(
        'Layer Bonuses',
        'JSON object mapping intent types to architecture layer bonuses for smart routing. Example: {"ui": {"frontend": 0.1, "components": 0.08}, "api": {"routes": 0.1, "controllers": 0.08}}. When users ask UI questions, code in frontend/ gets a +0.1 boost. Advanced feature for multi-tier architectures. Leave empty if not needed.',
        [
          ['Layer Routing', '/docs/MULTI_REPO.md#layer-bonuses'],
          ['Intent Detection', '/docs/RETRIEVAL.md#intent-classification'],
          ['JSON Format', 'https://www.json.org/json-en.html']
        ],
        [['Advanced', 'warn'], ['Multi-repo only', 'info']]
      ),

      // Evaluation
      GOLDEN_PATH: L(
        'Golden Questions Path',
        'Filesystem path to your golden questions JSON file (default: golden.json). Golden questions are curated query-answer pairs used to evaluate retrieval quality through automated testing. Format: [{"query": "how does auth work?", "expected_file": "src/auth.py"}]. Used by eval loop to measure metrics like Hit@K, MRR, and precision. Create golden questions from real user queries for best results.',
        [
          ['Golden Questions Format', '/docs/EVALUATION.md#golden-format'],
          ['Eval Script Source', '/eval/eval_loop.py'],
          ['Creating Golden Sets', '/docs/EVALUATION.md#creating-golden-questions'],
          ['Evaluation Metrics', 'https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval)']
        ]
      ),
      BASELINE_PATH: L(
        'Baseline Path',
        'Directory where evaluation loop saves baseline results for regression testing and A/B comparison. Each eval run\'s metrics (Hit@K, MRR, latency) are stored here with timestamps. Use this to ensure retrieval quality doesn\'t regress after configuration changes, reindexing, or model upgrades. Compare current run against baseline to detect improvements or degradations.',
        [
          ['Baseline Testing', '/docs/EVALUATION.md#baseline-comparison'],
          ['Eval Script Source', '/eval/eval_loop.py'],
          ['Regression Prevention', 'https://en.wikipedia.org/wiki/Software_regression']
        ]
      ),
      EVAL_MULTI: L(
        'Eval Multi‑Query',
        'Enable multi-query expansion during evaluation runs (1=yes, 0=no). When enabled, each golden question is rewritten multiple times (per MQ_REWRITES setting) to test recall under query variation. Turning this on makes eval results match production behavior if you use multi-query in prod, but increases eval runtime. Use 1 to measure realistic performance, 0 for faster eval iterations.',
        [
          ['Multi-Query RAG', 'https://arxiv.org/abs/2305.14283'],
          ['Evaluation Setup', '/docs/EVALUATION.md#multi-query'],
          ['MQ_REWRITES Setting', '/docs/RETRIEVAL.md#multi-query']
        ],
        [['Affects eval time', 'warn']]
      ),
      EVAL_FINAL_K: L(
        'Eval Final‑K',
        'Number of top results to consider when evaluating Hit@K metrics. If set to 10, eval checks if the expected answer appears in the top 10 results. Lower values (5) test precision, higher values (20) test recall. Should match your production FINAL_K setting for realistic evaluation. Common: 5 (strict), 10 (balanced), 20 (lenient).',
        [
          ['Hit@K Metric', 'https://en.wikipedia.org/wiki/Evaluation_measures_(information_retrieval)#Precision_at_K'],
          ['Evaluation Metrics', '/docs/EVALUATION.md#metrics'],
          ['FINAL_K Setting', '/docs/RETRIEVAL.md#final-k']
        ]
      ),
      EVAL_SAMPLE_SIZE: L(
        'Sample Size (Quick vs Full)',
        'Limit evaluation to a subset of golden questions for faster iteration and testing. Quick (10): ~1 minute, good for sanity checks. Medium (25): ~2-3 minutes, better coverage. Large (50): ~5 minutes, more representative. Full (all): Run complete eval suite for milestone validation and regression detection. Leave empty or select "Full" to evaluate all questions. Sample evals are perfect for rapid iteration; use full evals before production changes or major updates.',
        [
          ['Evaluation Best Practices', '/docs/EVALUATION.md#quick-vs-full'],
          ['Regression Testing', '/docs/EVALUATION.md#baseline-comparison'],
          ['Evaluation Metrics Guide', '/docs/EVALUATION.md#metrics']
        ],
        [['Quick testing', 'info'], ['Sample recommended for CI', 'info']]
      ),

      // Repo‑specific env overrides (legacy) removed (use repos.json / config UI instead)

      // Generation & API
      GEN_MAX_TOKENS: L(
        'Max Tokens',
        'Maximum number of tokens the LLM can generate in a single response. Higher values allow longer answers but increase cost and latency. Typical: 512-1024 for concise answers, 2048-4096 for detailed explanations.',
        [
          ['OpenAI Token Limits', 'https://platform.openai.com/docs/guides/text-generation'],
          ['Token Counting', 'https://platform.openai.com/tokenizer']
        ]
      ),
      GEN_TOP_P: L(
        'Top-P (Nucleus Sampling)',
        'Controls randomness via nucleus sampling (0.0-1.0). Lower values (0.1-0.5) make output more focused and deterministic. Higher values (0.9-1.0) increase creativity and diversity. Recommended: 0.9 for general use.',
        [
          ['Nucleus Sampling', 'https://platform.openai.com/docs/guides/text-generation/parameter-details'],
          ['Top-P Explanation', 'https://en.wikipedia.org/wiki/Top-p_sampling']
        ]
      ),
      GEN_TIMEOUT: L(
        'Generation Timeout',
        'Maximum seconds to wait for LLM response before timing out. Prevents hanging on slow models or network issues. Increase for large models or slow connections. Typical: 30-120 seconds.',
        [
          ['Timeout Best Practices', 'https://platform.openai.com/docs/guides/rate-limits'],
          ['HTTP Timeouts', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Timeout']
        ]
      ),
      GEN_RETRY_MAX: L(
        'Generation Max Retries',
        'Number of retry attempts for failed LLM API calls due to rate limits, network errors, or transient failures. Higher values improve reliability but increase latency on failures. Typical: 2-3 retries.',
        [
          ['Retry Strategies', 'https://platform.openai.com/docs/guides/error-codes'],
          ['Exponential Backoff', 'https://en.wikipedia.org/wiki/Exponential_backoff']
        ]
      ),

      // Embedding
      EMBEDDING_CACHE_ENABLED: L(
        'Embedding Cache',
        'Cache embedding API results to disk to avoid re-computing vectors for identical text. Reduces API costs and speeds up reindexing. Disable only for debugging or when embeddings change frequently.',
        [
          ['Caching Strategies', 'https://en.wikipedia.org/wiki/Cache_(computing)'],
          ['Embedding Best Practices', 'https://platform.openai.com/docs/guides/embeddings/use-cases']
        ]
      ),
      EMBEDDING_TIMEOUT: L(
        'Embedding Timeout',
        'Maximum seconds to wait for embedding API response. Similar to GEN_TIMEOUT but for embedding calls during indexing. Increase for large batches or slow networks. Typical: 30-60 seconds.',
        [
          ['API Timeouts', 'https://platform.openai.com/docs/guides/rate-limits'],
          ['Embedding API', 'https://platform.openai.com/docs/api-reference/embeddings']
        ]
      ),
      EMBEDDING_RETRY_MAX: L(
        'Embedding Max Retries',
        'Retry attempts for failed embedding API calls during indexing. Higher values ensure indexing completes despite transient errors but slow down failure recovery. Typical: 2-3 retries.',
        [
          ['Error Handling', 'https://platform.openai.com/docs/guides/error-codes'],
          ['Retry Patterns', 'https://en.wikipedia.org/wiki/Retry_pattern']
        ]
      ),

      // Indexing
      INDEX_EXCLUDED_EXTS: L(
        'Excluded Extensions',
        'Comma-separated file extensions to skip during indexing (e.g., ".png,.jpg,.pdf,.zip"). Prevents indexing binary files, images, or non-code assets. Reduces index size and improves relevance.',
        [
          ['Gitignore Patterns', 'https://git-scm.com/docs/gitignore'],
          ['File Extensions', 'https://en.wikipedia.org/wiki/Filename_extension']
        ]
      ),
      INDEX_MAX_FILE_SIZE_MB: L(
        'Max File Size (MB)',
        'Skip files larger than this size (in megabytes) during indexing. Prevents huge generated files or vendor bundles from bloating the index. Typical: 1-5 MB for source code, higher for docs.',
        [
          ['File Size Management', 'https://en.wikipedia.org/wiki/File_size'],
          ['Indexing Best Practices', '/docs/INDEXING.md#file-size-limits']
        ]
      ),

      // Metrics & Monitoring
      PROMETHEUS_PORT: L(
        'Prometheus Port',
        'TCP port for Prometheus metrics endpoint. Exposes /metrics for scraping by Prometheus or Grafana. Default: 9090. Change to avoid conflicts with existing monitoring tools.',
        [
          ['Prometheus Basics', 'https://prometheus.io/docs/introduction/overview/'],
          ['Metrics Endpoint', 'https://prometheus.io/docs/instrumenting/exposition_formats/']
        ]
      ),
      METRICS_ENABLED: L(
        'Metrics Enabled',
        'Enable Prometheus metrics collection and /metrics endpoint. When on, exposes query latency, cache hits, error rates, etc. Essential for production monitoring. Minimal overhead.',
        [
          ['Prometheus Metrics', 'https://prometheus.io/docs/concepts/metric_types/'],
          ['Monitoring Best Practices', 'https://prometheus.io/docs/practices/naming/']
        ]
      ),

      // Logging & Observability
      LOG_LEVEL: L(
        'Log Level',
        'Logging verbosity level. Options: DEBUG (verbose, dev), INFO (normal, recommended), WARNING (errors + warnings only), ERROR (errors only). Higher levels reduce noise but may hide useful diagnostics.',
        [
          ['Python Logging Levels', 'https://docs.python.org/3/library/logging.html#logging-levels'],
          ['Logging Best Practices', 'https://docs.python.org/3/howto/logging.html']
        ]
      ),
      TRACING_ENABLED: L(
        'Tracing Enabled',
        'Enable TriBridRAG request tracing. This records an in-memory per-request event trace (used by the UI “Routing Trace” preview) for debugging routing/retrieval decisions and latency. This does not export traces to external providers.',
        [
          ['Distributed Tracing (concepts)', 'https://opentelemetry.io/docs/concepts/observability-primer/#distributed-traces']
        ]
      ),
      TRACING_MODE: L(
        'Tracing Mode',
        'Controls tracing behavior. Options: "off" (disable tracing), "local" (local-only), "langsmith" (local traces + reserved for future LangSmith export). Alias: "none" is normalized to "off".',
        [
          ['LangSmith', 'https://docs.smith.langchain.com/']
        ]
      ),
      TRACE_AUTO_LS: L(
        'Auto-open LangSmith',
        'UI convenience flag intended to auto-open LangSmith after a request (1=yes, 0=no). TriBridRAG does not currently implement LangSmith deep-linking; this setting is reserved for future integration.',
        [
          ['LangSmith Setup', 'https://docs.smith.langchain.com/']
        ]
      ),
      TRACE_RETENTION: L(
        'Trace Retention',
        'Number of traces to retain in the in-memory ring buffer (10-500). Higher values preserve more history for debugging; lower values use less memory.',
        [
          ['Data Retention', 'https://en.wikipedia.org/wiki/Data_retention']
        ]
      ),
      LANGSMITH_API_KEY: L(
        'LangSmith API Key',
        'API key for LangSmith (external provider). TriBridRAG does not currently export traces to LangSmith; the UI only checks whether this key is set in your environment.',
        [
          ['LangSmith API Keys', 'https://docs.smith.langchain.com/'],
          ['Get API Key', 'https://smith.langchain.com/settings']
        ]
      ),
      LANGCHAIN_API_KEY: L(
        'LangChain API Key',
        'Alternate env var name used by LangSmith. Treat as an alias for LANGSMITH_API_KEY (external provider). TriBridRAG does not currently export traces to LangSmith.',
        [
          ['LangSmith Setup', 'https://docs.smith.langchain.com/']
        ]
      ),
      LANGCHAIN_PROJECT: L(
        'LangChain Project',
        'Project name for organizing traces in LangSmith (external provider). Stored in config field tracing.langchain_project. Reserved for future integration.',
        [
          ['LangSmith Projects', 'https://docs.smith.langchain.com/tracing/faq#how-do-i-use-projects']
        ]
      ),
      LANGCHAIN_ENDPOINT: L(
        'LangChain Endpoint',
        'LangSmith API endpoint URL (external provider). Stored in config field tracing.langchain_endpoint. Reserved for future integration.',
        [
          ['LangSmith API', 'https://docs.smith.langchain.com/']
        ]
      ),
      LANGTRACE_API_KEY: L(
        'LangTrace API Key',
        'API key for LangTrace (external provider). TriBridRAG does not currently export traces to LangTrace; the UI only checks whether this key is set in your environment.',
        [
          ['Langtrace Setup', 'https://docs.langtrace.ai/']
        ]
      ),
      LANGTRACE_API_HOST: L(
        'LangTrace API Host',
        'LangTrace API endpoint host (optional). Stored in config field tracing.langtrace_api_host (and surfaced as LANGTRACE_API_HOST in env exports). Reserved for future external trace export.',
        [
          ['Langtrace Docs', 'https://docs.langtrace.ai/']
        ]
      ),
      LANGTRACE_PROJECT_ID: L(
        'LangTrace Project ID',
        'Project identifier for LangTrace (optional). Stored in config field tracing.langtrace_project_id (and surfaced as LANGTRACE_PROJECT_ID in env exports). Reserved for future external trace export.',
        [
          ['Langtrace Projects', 'https://docs.langtrace.ai/']
        ]
      ),

      // Grafana Integration
      GRAFANA_BASE_URL: L(
        'Grafana Base URL',
        'Base URL for Grafana dashboard server (e.g., http://localhost:3000). Used for embedded dashboard iframes in GUI and direct links to monitoring dashboards.',
        [
          ['Grafana Setup', 'https://grafana.com/docs/grafana/latest/setup-grafana/']
        ]
      ),
      GRAFANA_AUTH_TOKEN: L(
        'Grafana Auth Token',
        'API token or service account token for Grafana authentication. Generate in Grafana under Configuration > API Keys or Service Accounts.',
        [
          ['Grafana API Keys', 'https://grafana.com/docs/grafana/latest/administration/api-keys/']
        ]
      ),
      GRAFANA_AUTH_MODE: L(
        'Grafana Auth Mode',
        'Authentication method for Grafana. Options: "token" (API token), "basic" (username/password), "none" (public dashboards).',
        [
          ['Grafana Auth', 'https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/']
        ]
      ),
      GRAFANA_DASHBOARD_UID: L(
        'Grafana Dashboard UID',
        'Unique identifier for default Grafana dashboard to display in GUI. Find UID in dashboard settings or URL (e.g., /d/abc123/dashboard-name -> UID is abc123).',
        [
          ['Dashboard UIDs', 'https://grafana.com/docs/grafana/latest/dashboards/']
        ]
      ),

      // Webhooks & Alerts
      ALERT_WEBHOOK_TIMEOUT: L(
        'Alert Webhook Timeout',
        'Maximum seconds to wait for alert webhook response (Slack, Discord, etc.). Prevents slow webhooks from blocking the main process. Typical: 5-10 seconds.',
        [
          ['Webhook Timeouts', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Timeout'],
          ['Slack Webhooks', 'https://api.slack.com/messaging/webhooks']
        ]
      ),

      // Keywords & Routing
      KEYWORDS_REFRESH_HOURS: L(
        'Keywords Refresh (Hours)',
        'How often (in hours) to regenerate repository keywords from code for improved query routing. Lower values keep keywords fresh but increase indexing overhead. Typical: 24-168 hours (1-7 days).',
        [
          ['Query Routing', '/docs/MULTI_REPO.md#keyword-routing'],
          ['Keyword Extraction', 'https://en.wikipedia.org/wiki/Keyword_extraction']
        ]
      ),

      // RAG Parameters (chunking, embeddings, indexing, enrichment)
      CARD_SEARCH_ENABLED: L(
        'Card Search Enabled',
        'Enable card-based boosting during retrieval to surface relevant code modules and features. When enabled, the system loads summary cards (high-level descriptions of modules/classes/features) and boosts results that match card content. This improves retrieval for conceptual queries like "where is payment processing?" at the cost of slightly increased memory and query latency. Requires ENRICH_CODE_CHUNKS=1 and cards to be built during indexing.\n\nRecommended: 1 (enabled) for production with enrichment, 0 (disabled) for development or when enrichment is off.',
        [
          ['Cards Feature Guide', '/docs/CARDS.md'],
          ['Card Builder Source', '/indexer/build_cards.py'],
          ['Score Boosting Logic', '/docs/RETRIEVAL.md#card-boosting']
        ],
        [['Better conceptual search', 'info'], ['Requires enrichment', 'warn']]
      ),
      EMBEDDING_MODEL: L(
        'Embedding Model (OpenAI)',
        'OpenAI embedding model name when EMBEDDING_TYPE=openai. Current options: "text-embedding-3-small" (512-3072 dims, $0.02/1M tokens, fast), "text-embedding-3-large" (256-3072 dims, $0.13/1M tokens, highest quality), "text-embedding-ada-002" (legacy, 1536 dims, $0.10/1M tokens). Larger models improve semantic search quality but cost more and require more storage. Changing this requires full reindexing as embeddings are incompatible across models.\n\nRecommended: text-embedding-3-small for most use cases, text-embedding-3-large for production systems demanding highest quality.',
        [
          ['OpenAI Embeddings Guide', 'https://platform.openai.com/docs/guides/embeddings'],
          ['Embedding Models', 'https://platform.openai.com/docs/models/embeddings'],
          ['Pricing Calculator', 'https://openai.com/api/pricing/']
        ],
        [['Requires reindex', 'reindex'], ['Costs API calls', 'warn']]
      ),
      VOYAGE_MODEL: L(
        'Voyage Embedding Model',
        'Voyage AI embedding model when EMBEDDING_TYPE=voyage. Options: "voyage-code-2" (1536 dims, optimized for code, recommended), "voyage-3" (1024 dims, general-purpose, fast), "voyage-3-lite" (512 dims, budget option). Voyage models are specialized for code retrieval and often outperform OpenAI on technical queries. Code-specific models understand programming constructs, API patterns, and documentation better than general embeddings.\n\nRecommended: voyage-code-2 for code-heavy repos, voyage-3 for mixed content (code + docs).',
        [
          ['Voyage Embeddings API', 'https://docs.voyageai.com/docs/embeddings'],
          ['voyage-code-2 Details', 'https://docs.voyageai.com/docs/voyage-code-2'],
          ['Model Comparison', 'https://docs.voyageai.com/docs/model-comparison']
        ],
        [['Requires reindex', 'reindex'], ['Code-optimized', 'info']]
      ),
      EMBEDDING_MODEL_LOCAL: L(
        'Local Embedding Model',
        'HuggingFace model name or local path when EMBEDDING_TYPE=local or mxbai. Popular options: "mixedbread-ai/mxbai-embed-large-v1" (1024 dims, excellent quality), "BAAI/bge-small-en-v1.5" (384 dims, fast), "sentence-transformers/all-MiniLM-L6-v2" (384 dims, lightweight). Local embeddings are free but slower than API-based options. Model is downloaded on first use and cached locally. Choose larger models (768-1024 dims) for quality or smaller (384 dims) for speed.\n\nRecommended: mxbai-embed-large-v1 for best free quality, all-MiniLM-L6-v2 for resource-constrained environments.',
        [
          ['Sentence Transformers Models', 'https://www.sbert.net/docs/sentence_transformer/pretrained_models.html'],
          ['HuggingFace Model Hub', 'https://huggingface.co/models?pipeline_tag=feature-extraction&sort=downloads'],
          ['MTEB Leaderboard', 'https://huggingface.co/spaces/mteb/leaderboard']
        ],
        [['Free (no API)', 'info'], ['Requires download', 'warn']]
      ),
      EMBEDDING_BATCH_SIZE: L(
        'Embedding Batch Size',
        'Number of text chunks to embed in a single API call or local batch during indexing. Higher values (50-200) speed up indexing by reducing API round trips but may hit rate limits or memory constraints. Lower values (10-30) are safer but slower. For OpenAI/Voyage APIs, batching significantly reduces total indexing time. For local models, larger batches improve GPU utilization but require more VRAM. If indexing fails with rate limit or OOM errors, reduce this value.\n\nRecommended: 100-150 for API providers, 16-32 for local models (GPU), 4-8 for CPU-only.',
        [
          ['OpenAI Batch Embedding', 'https://platform.openai.com/docs/guides/embeddings/use-cases'],
          ['Rate Limits', 'https://platform.openai.com/docs/guides/rate-limits'],
          ['GPU Memory Management', 'https://huggingface.co/docs/transformers/en/perf_train_gpu_one']
        ],
        [['Performance tuning', 'info'], ['Watch rate limits', 'warn']]
      ),
      EMBEDDING_MAX_TOKENS: L(
        'Embedding Max Tokens',
        'Maximum token length for text chunks sent to embedding models during indexing. Text exceeding this length is truncated by the tokenizer. Most embedding models support 512-8192 tokens. Longer limits preserve more context per chunk but increase embedding cost and processing time. Shorter limits are faster and cheaper but may lose semantic context for large functions/classes. Balance based on your average code chunk size and model capabilities.\n\nRecommended: 512 for most code (functions/methods), 1024 for documentation-heavy repos, 256 for ultra-fast indexing.',
        [
          ['Tokenization Basics', 'https://huggingface.co/docs/transformers/main/en/tokenizer_summary'],
          ['OpenAI Token Limits', 'https://platform.openai.com/docs/guides/embeddings/embedding-models'],
          ['Voyage Limits', 'https://docs.voyageai.com/docs/embeddings#input-text']
        ],
        [['Affects cost', 'warn'], ['Context preservation', 'info']]
      ),
      INDEXING_BATCH_SIZE: L(
        'Indexing Batch Size',
        'Number of chunks to process in parallel during the indexing pipeline (chunking, enrichment, embedding, Qdrant upload). Higher values (100-500) maximize throughput on fast networks and powerful machines but increase memory usage and risk batch failures. Lower values (20-50) are more stable and provide better progress visibility. If indexing crashes with OOM or connection errors, reduce this. For large repos (100k+ files), use higher values for efficiency.\n\nRecommended: 100-200 for normal repos, 50-100 for large repos or slow connections, 500+ for small repos on powerful hardware.',
        [
          ['Batch Processing', 'https://en.wikipedia.org/wiki/Batch_processing'],
          ['Qdrant Upload Performance', 'https://qdrant.tech/documentation/guides/bulk-upload/'],
          ['Indexing Guide', '/docs/INDEXING.md#performance']
        ],
        [['Performance tuning', 'info'], ['Memory sensitive', 'warn']]
      ),
      INDEXING_WORKERS: L(
        'Indexing Workers',
        'Number of parallel worker threads for CPU-intensive indexing tasks (file parsing, chunking, BM25 indexing). Higher values (4-16) utilize multi-core CPUs better and speed up indexing significantly. Lower values (1-2) reduce CPU load but increase indexing time. Set based on available CPU cores - typically use cores-1 or cores-2 to leave headroom for OS/other processes. For Docker/containers, ensure resource limits allow multiple workers.\n\nRecommended: 4-8 for most systems, 1-2 for low-power machines or containers with CPU limits, 12-16 for powerful servers.',
        [
          ['Parallel Processing', 'https://en.wikipedia.org/wiki/Parallel_computing'],
          ['Python ThreadPoolExecutor', 'https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor'],
          ['Docker CPU Limits', 'https://docs.docker.com/engine/containers/resource_constraints/#cpu']
        ],
        [['CPU utilization', 'info'], ['Faster indexing', 'info']]
      ),
      BM25_STEMMER_LANG: L(
        'BM25 Stemmer Language',
        'Language for stemming/normalization in BM25 sparse indexing. Common values: "en" (English - default), "multilingual" (multiple languages), "none" (disable stemming). Stemming reduces words to root forms (e.g., "running" -> "run") to improve keyword matching. English stemming works well for code comments, docs, and variable names. Use "none" for non-English repos or when exact keyword matching is critical (e.g., API names, error codes).\n\nRecommended: "en" for English codebases, "multilingual" for international teams, "none" for strict keyword matching.',
        [
          ['BM25 Algorithm', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Stemming Explained', 'https://en.wikipedia.org/wiki/Stemming'],
          ['BM25S Library', 'https://github.com/xhluca/bm25s#supported-stemmers']
        ],
        [['Affects keyword search', 'info']]
      ),
      VOYAGE_RERANK_MODEL: L(
        'Voyage Rerank Model',
        'Voyage AI reranker model name when RERANK_BACKEND=voyage. Current option: "rerank-2" (latest, best quality). Voyage rerankers are cross-encoders that score (query, document) pairs for precise relevance ranking. Generally more accurate than open-source rerankers but costs per API call. Use when retrieval quality is critical and budget allows. Pricing is per rerank request (typically $0.05-0.10 per 1000 candidates).\n\nRecommended: Use Voyage reranking for production systems with quality requirements; use local rerankers (RERANKER_MODEL) for development/testing.',
        [
          ['Voyage Rerank API', 'https://docs.voyageai.com/docs/reranker'],
          ['rerank-2 Details', 'https://docs.voyageai.com/docs/rerank-2'],
          ['Pricing', 'https://docs.voyageai.com/docs/pricing']
        ],
        [['Costs API calls', 'warn'], ['High quality', 'info']]
      ),
      TRIBRID_RERANKER_RELOAD_ON_CHANGE: L(
        'Reranker Auto-Reload',
        'Automatically reload the local reranker model when RERANKER_MODEL path changes during runtime (1=yes, 0=no). When enabled, the system detects model path changes and hot-reloads the new model without server restart. Useful during development when switching between reranker models or testing fine-tuned versions. In production, disable to avoid unexpected reloads and ensure stability. Model reloading adds 2-5 seconds of latency on first query after change.\n\nRecommended: 1 for development/testing, 0 for production deployments.',
        [
          ['Model Management', '/docs/LEARNING_RERANKER.md#testing-models'],
          ['Hot Reload Patterns', 'https://en.wikipedia.org/wiki/Hot_swapping'],
          ['Reranker Training', '/docs/LEARNING_RERANKER.md']
        ],
        [['Development feature', 'info'], ['Disable in production', 'warn']]
      ),
      ENRICH_DISABLED: L(
        'Disable Enrichment',
        'Completely disable code enrichment (summaries, keywords, cards) during indexing (1=disable, 0=enable). When disabled, indexing is much faster and cheaper (no LLM API calls) but you lose card search, enriched metadata, and semantic boosting. Use this for quick re-indexing during development, CI/CD pipelines, or when working with non-code content. Re-enable for production to get full retrieval quality benefits.\n\nRecommended: 0 (enrichment ON) for production, 1 (enrichment OFF) for fast iteration and testing.',
        [
          ['Enrichment Guide', '/docs/ENRICHMENT.md'],
          ['Cards Feature', '/docs/CARDS.md'],
          ['Fast Indexing Mode', '/docs/INDEXING.md#skip-enrichment']
        ],
        [['Much faster indexing', 'info'], ['Loses card search', 'warn']]
      ),
      KEYWORDS_MAX_PER_REPO: L(
        'Keywords Max Per Repo',
        'Maximum number of repository-specific keywords to extract and store for query routing in multi-repo setups. Higher values (100-200) capture more routing signals but increase memory and may introduce noise. Lower values (20-50) keep routing focused on core concepts. Keywords are extracted from code, docs, and enrichment metadata. Used by the router to determine which repositories are most relevant for a given query.\n\nRecommended: 50-100 for most repos, 150-200 for large multi-domain codebases, 20-30 for focused microservices.',
        [
          ['Query Routing', '/docs/MULTI_REPO.md#routing'],
          ['Keyword Extraction', '/docs/MULTI_REPO.md#automatic-keywords'],
          ['repos.json Config', '/repos.json']
        ],
        [['Multi-repo only', 'info'], ['Auto-generated', 'info']]
      ),
      KEYWORDS_AUTO_GENERATE: L(
        'Auto-Generate Keywords',
        'Automatically extract repository keywords from code and documentation during indexing (1=yes, 0=no). When enabled, the system analyzes class names, function names, docstrings, and comments to build a keyword set for routing. This supplements manually-defined keywords in repos.json. Auto-generation is useful for new repos or when you don\'t know what routing keywords to use. Disable if you prefer full manual control via repos.json.\n\nRecommended: 1 for automatic keyword discovery, 0 for strict manual control.',
        [
          ['Keyword Extraction Logic', '/docs/MULTI_REPO.md#keyword-generation'],
          ['repos.json Keywords', '/repos.json'],
          ['Routing Guide', '/docs/MULTI_REPO.md#routing-algorithm']
        ],
        [['Multi-repo feature', 'info'], ['Complements manual keywords', 'info']]
      ),
      TRACE_SAMPLING_RATE: L(
        'Trace Sampling Rate',
        'Percentage of requests to trace with LangSmith/observability (0.0-1.0). 1.0 = trace everything (100%), 0.1 = trace 10% of requests, 0.0 = no tracing. Lower sampling reduces LangSmith costs and overhead while still providing visibility into system behavior. Use 1.0 during development/debugging, 0.05-0.2 in production for cost-effective monitoring. Sampling is random - every request has this probability of being traced.\n\nRecommended: 1.0 for development, 0.1-0.2 for production monitoring, 0.05 for high-traffic systems.',
        [
          ['LangSmith Tracing', 'https://docs.smith.langchain.com/tracing'],
          ['Sampling Strategies', 'https://docs.smith.langchain.com/tracing/faq#how-do-i-sample-traces'],
          ['Trace Costs', 'https://www.langchain.com/pricing']
        ],
        [['Cost control', 'info'], ['Observability', 'info']]
      ),

      // Chunking
      AST_OVERLAP_LINES: L(
        'AST Overlap Lines',
        'Number of overlapping lines between consecutive AST-based code chunks. Overlap ensures context continuity across chunk boundaries, preventing loss of meaning when functions or classes are split. Higher overlap (5-15 lines) improves retrieval quality by providing more context but increases index size and duplicate content. Lower overlap (0-5 lines) reduces redundancy but risks fragmenting logical units.\n\nSweet spot: 3-5 lines for balanced context preservation. Use 5-10 lines for codebases with large functions or complex nested structures where context matters heavily. Use 0-2 lines for memory-constrained environments or when chunk boundaries align well with natural code structure (e.g., clean function boundaries). AST-aware chunking (cAST method) respects syntax boundaries, so overlap supplements structural chunking.\n\nExample: With 5-line overlap, if chunk 1 ends at line 100, chunk 2 starts at line 96, creating a 5-line bridge. This helps when a query matches content near chunk boundaries - the overlapping region appears in both chunks, improving recall. The cAST paper (EMNLP 2025) shows overlap significantly improves code retrieval accuracy.\n\n• Range: 0-15 lines (typical)\n• Minimal: 0-2 lines (tight memory, clean boundaries)\n• Balanced: 3-5 lines (recommended for most codebases)\n• High context: 5-10 lines (complex nested code)\n• Very high: 10-15 lines (maximum context, high redundancy)\n• Trade-off: More overlap = better recall, larger index',
        [
          ['cAST Chunking Paper (EMNLP 2025)', 'https://arxiv.org/abs/2506.15655'],
          ['AST Chunking Toolkit', 'https://github.com/yilinjz/astchunk'],
          ['Context Window in RAG', 'https://arxiv.org/abs/2312.10997'],
          ['Chunking Strategies', '/docs/INDEXING.md#ast-chunking']
        ],
        [['Advanced chunking', 'info'], ['Requires reindex', 'reindex']]
      ),
      MAX_CHUNK_TOKENS: L(
        'Max Chunk Tokens',
        'Maximum token length for a single code chunk during AST-based chunking. Limits chunk size to fit within embedding model token limits (typically 512-8192 tokens). Larger chunks (1000-2000 tokens) capture more context per chunk, reducing fragmentation of large functions/classes. Smaller chunks (200-512 tokens) create more granular units, improving precision but potentially losing broader context.\n\nSweet spot: 512-768 tokens for balanced chunking. This fits most embedding models (e.g., OpenAI text-embedding-3 supports up to 8191 tokens, but 512-768 is practical). Use 768-1024 for code with large docstrings or complex classes where context matters. Use 256-512 for tight memory budgets or when targeting very specific code snippets. AST chunking respects syntax, so chunks won\'t split mid-function even if size limit is hit (falls back to greedy chunking).\n\nToken count is approximate (based on whitespace heuristics, not exact tokenization). Actual embedding input may vary slightly. If a logical unit (function, class) exceeds MAX_CHUNK_TOKENS, the chunker splits it using GREEDY_FALLBACK_TARGET for sub-chunking while preserving structure where possible.\n\n• Range: 200-2000 tokens (typical)\n• Small: 256-512 tokens (precision, tight memory)\n• Balanced: 512-768 tokens (recommended, fits most models)\n• Large: 768-1024 tokens (more context, larger functions)\n• Very large: 1024-2000 tokens (maximum context, risky for some models)\n• Constraint: Must not exceed embedding model token limit',
        [
          ['Token Limits by Model', 'https://platform.openai.com/docs/guides/embeddings/embedding-models'],
          ['cAST Paper', 'https://arxiv.org/abs/2506.15655'],
          ['Chunking Size Tradeoffs', 'https://weaviate.io/blog/chunking-strategies-for-rag'],
          ['Token Estimation', 'https://github.com/openai/tiktoken']
        ],
        [['Advanced chunking', 'info'], ['Requires reindex', 'reindex']]
      ),
      MAX_INDEXABLE_FILE_SIZE: L(
        'Max Indexable File Size',
        'Maximum file size in bytes that will be indexed. Files larger than this limit are skipped during indexing to prevent memory issues and avoid indexing large binary or generated files. Default is 2MB (2,000,000 bytes). Increase for codebases with legitimately large source files; decrease to speed up indexing and reduce memory usage.\n\nSweet spot: 1-2 MB for most codebases. Use 500KB-1MB for memory-constrained environments or when you want to exclude large auto-generated files. Use 2-5MB for codebases with large source files (e.g., bundled assets, data files that should be searchable). Files exceeding this limit are logged as skipped.\n\nExample: A 5MB SQL dump file would be skipped with MAX_INDEXABLE_FILE_SIZE=2000000. To include it, increase to 6000000 (6MB). Large files that are indexed will be chunked normally, but may take longer to process and consume more embedding API tokens.\n\n• Range: 100KB - 10MB (typical)\n• Tight: 100KB - 500KB (skip most large files, fast indexing)\n• Balanced: 1MB - 2MB (recommended, handles normal source files)\n• Large: 2MB - 5MB (include larger source files)\n• Very large: 5MB - 10MB (include data files, maximum coverage)\n• Trade-off: Higher limit = more coverage, slower indexing, more memory',
        [
          ['Indexing Guide', '/docs/INDEXING.md#file-limits'],
          ['Memory Optimization', '/docs/PERFORMANCE_AND_COST.md#memory'],
          ['File Filtering', '/docs/INDEXING.md#filtering']
        ],
        [['File filtering', 'info'], ['Requires reindex', 'reindex']]
      ),
      MIN_CHUNK_CHARS: L(
        'Min Chunk Chars',
        'Minimum character count for a valid chunk. Chunks smaller than this are discarded or merged with adjacent chunks to avoid indexing trivial code fragments (empty functions, single-line comments, import statements). Higher minimums (100-200 chars) filter out noise and reduce index size but may skip small utility functions. Lower minimums (20-50 chars) index everything but include low-value chunks.\n\nSweet spot: 50-100 characters for balanced filtering. Use 100-200 for aggressive noise reduction when you have many trivial functions or auto-generated code. Use 20-50 to index everything, including tiny utilities (useful for finding specific one-liners or constants). This threshold applies after AST chunking - if a logical unit is too small, it\'s skipped unless PRESERVE_IMPORTS is enabled.\n\nExample: A 2-line import block (30 chars) would be skipped with MIN_CHUNK_CHARS=50 unless PRESERVE_IMPORTS=1. A 5-line utility function (80 chars) would pass the filter. This prevents embedding API calls and index bloat from non-semantic content. Adjust based on your codebase style - functional codebases with many small functions may need lower thresholds.\n\n• Range: 20-300 characters (typical)\n• Very permissive: 20-50 chars (index everything, including tiny snippets)\n• Balanced: 50-100 chars (recommended, filter trivial fragments)\n• Aggressive filtering: 100-200 chars (skip small utilities, focus on substantial code)\n• Very aggressive: 200-300 chars (only meaningful functions/classes)\n• Trade-off: Higher threshold = cleaner index, may miss small but relevant code',
        [
          ['Noise Filtering', '/docs/INDEXING.md#filtering'],
          ['Code Chunking Best Practices', 'https://weaviate.io/blog/chunking-strategies-for-rag'],
          ['Index Optimization', '/docs/PERFORMANCE_AND_COST.md#index-size'],
          ['cAST Filtering', 'https://github.com/yilinjz/astchunk#filtering']
        ],
        [['Index quality control', 'info'], ['Requires reindex', 'reindex']]
      ),
      GREEDY_FALLBACK_TARGET: L(
        'Greedy Fallback Target (Chars)',
        'Target chunk size (in characters) for greedy fallback chunking when AST-based chunking fails or encounters oversized logical units. Greedy chunking splits text at line boundaries to hit this approximate size. Used as a safety mechanism when: (1) file syntax is unparseable, (2) a single function/class exceeds MAX_CHUNK_SIZE, (3) non-code files (markdown, text) are indexed.\n\nSweet spot: 500-800 characters for fallback chunks. This roughly corresponds to 100-150 tokens, providing reasonable context when AST chunking isn\'t possible. Use 800-1200 for larger fallback chunks (more context but less precise boundaries). Use 300-500 for smaller fallback chunks (tighter boundaries, less context). Greedy chunking is less semantic than AST chunking - it splits at line breaks regardless of code structure.\n\nExample: If a 3000-char function exceeds MAX_CHUNK_SIZE and can\'t be split structurally, greedy fallback divides it into ~4 chunks of ~750 chars each (based on GREEDY_FALLBACK_TARGET=800). This preserves some of the function in each chunk. Greedy fallback is rare in well-formed code but essential for robustness.\n\n• Range: 300-1500 characters (typical)\n• Small: 300-500 chars (tight boundaries, less context)\n• Balanced: 500-800 chars (recommended, ~100-150 tokens)\n• Large: 800-1200 chars (more context per fallback chunk)\n• Very large: 1200-1500 chars (maximum context, rare use)\n• When used: Syntax errors, oversized units, non-code files',
        [
          ['Fallback Strategies', '/docs/INDEXING.md#greedy-fallback'],
          ['Chunking Robustness', 'https://github.com/yilinjz/astchunk#fallback-modes'],
          ['AST Parsing Failures', '/docs/INDEXING.md#error-handling'],
          ['Greedy Chunking', 'https://en.wikipedia.org/wiki/Chunking_(psychology)']
        ],
        [['Fallback mechanism', 'info'], ['Requires reindex', 'reindex']]
      ),
      CHUNKING_STRATEGY: L(
        'Chunking Strategy',
        'Primary strategy for splitting code into chunks during indexing. Options: "ast" (AST-aware, syntax-respecting, recommended for code), "greedy" (line-based splitting, simpler), "hybrid" (AST with greedy fallback). AST chunking uses the cAST method (EMNLP 2025) to respect function/class boundaries, preserving semantic units. Greedy chunking splits at line breaks to hit target size, ignoring syntax. Hybrid uses AST primarily with greedy fallback for unparseable files.\n\n"ast" (recommended for code): Parses syntax tree and chunks at natural boundaries (functions, classes, methods). Produces semantically coherent chunks. Best for code retrieval. Requires parseable syntax - fails gracefully on malformed code.\n\n"greedy": Simple line-based splitting at target character count. Fast, always works, but may split mid-function or mid-class, fragmenting semantic units. Use for non-code (markdown, text) or when AST parsing is too slow.\n\n"hybrid": Tries AST first, falls back to greedy on parse errors. Balanced approach - gets AST benefits for well-formed code, handles edge cases gracefully. Recommended for mixed codebases (code + docs + config).\n\n• ast: Syntax-aware, best retrieval quality, code-only, requires parseable syntax (recommended for code)\n• greedy: Fast, always works, ignores syntax, lower quality chunks, good for non-code\n• hybrid: AST + greedy fallback, balanced, handles all files (recommended for mixed repos)\n• Effect: Fundamental impact on chunk quality, retrieval precision, index structure\n• Requires reindex: Changes take effect after full rebuild',
        [
          ['cAST Chunking Paper (EMNLP 2025)', 'https://arxiv.org/abs/2506.15655'],
          ['AST Chunking Toolkit', 'https://github.com/yilinjz/astchunk'],
          ['Chunking Strategies Guide', '/docs/INDEXING.md#chunking-strategies'],
          ['RAG Chunking Best Practices', 'https://weaviate.io/blog/chunking-strategies-for-rag']
        ],
        [['Core indexing choice', 'warn'], ['Requires reindex', 'reindex']]
      ),
      PRESERVE_IMPORTS: L(
        'Preserve Imports',
        'Include import/require statements in chunks even if they fall below MIN_CHUNK_CHARS threshold (1=yes, 0=no). When enabled, import blocks become searchable, helping users find dependency usage and module relationships. When disabled, imports are filtered out as low-value content. Enabling increases index size slightly but improves dependency discovery (e.g., "where do we use requests library?").\n\nSweet spot: 1 (enabled) for codebases where dependency tracking matters. Use 0 (disabled) to reduce index size and focus on implementation code rather than declarations. Import preservation is especially valuable in polyglot repos (Python, JavaScript, Go) where import patterns reveal architecture. Imports are still visible in full file context; this setting only affects whether they\'re indexed as standalone chunks.\n\nExample: With PRESERVE_IMPORTS=1, a 3-line import block becomes a searchable chunk even if it\'s <MIN_CHUNK_CHARS. A query like "where do we import AuthService?" will match this chunk. With PRESERVE_IMPORTS=0, the import block is skipped, and only code using AuthService is indexed.\n\n• 0: Disabled - skip import statements, reduce noise, smaller index, focus on implementation\n• 1: Enabled - index imports, discover dependencies, find module usage, slightly larger index (recommended)\n• Use case: Dependency audits, security reviews, architecture analysis\n• Trade-off: Slightly larger index vs better dependency discovery',
        [
          ['Import Analysis', '/docs/INDEXING.md#imports'],
          ['Dependency Discovery', '/docs/RETRIEVAL.md#import-search'],
          ['Code Structure Analysis', 'https://en.wikipedia.org/wiki/Dependency_analysis'],
          ['Module Systems', 'https://en.wikipedia.org/wiki/Modular_programming']
        ],
        [['Dependency tracking', 'info'], ['Requires reindex', 'reindex']]
      ),

      // Chat & Streaming
      CHAT_STREAMING_ENABLED: L(
        'Chat Streaming',
        'Enable streaming responses for chat interfaces. When on, tokens appear incrementally (like typing). Better UX but requires SSE support. Disable for simple request-response APIs.',
        [
          ['Server-Sent Events', 'https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events'],
          ['Streaming API', 'https://platform.openai.com/docs/api-reference/streaming']
        ]
      ),

      // === RESTORED MISSING TOOLTIPS (from old gui/js/tooltips.js commit 6a6ac9c) ===

      // Advanced RAG Parameters
      ADVANCED_RAG_TUNING: L(
        'Advanced Parameters',
        'Expert controls for fusion weighting, score bonuses, and iteration behavior. These significantly affect retrieval quality and performance. Change only if you understand trade-offs.',
        [
          ['RAG Tuning Guide', '/docs/RETRIEVAL.md#tuning']
        ],
        [['Expert', 'warn']]
      ),

      // Card & Filename Boosts
      CARD_BONUS: L(
        'Card Semantic Bonus',
        'Score bonus when a result matches code "Cards" (semantic summaries from enrichment). Improves intent\u2011based retrieval (e.g., "where is auth handled?"). Requires ENRICH_CODE_CHUNKS.',
        [
          ['Cards Feature', '/docs/CARDS.md'],
          ['Cards Builder', '/files/indexer/build_cards.py']
        ],
        [['Improves intent','info']]
      ),
      FILENAME_BOOST_EXACT: L(
        'Filename Exact Match Multiplier',
        'Score multiplier applied when the filename matches the query exactly (e.g., auth.py). Increase to prioritize file\u2011specific queries.',
        [
          ['Path Scoring', '/docs/RETRIEVAL.md#path-scoring']
        ]
      ),
      FILENAME_BOOST_PARTIAL: L(
        'Path Component Partial Match Multiplier',
        'Score multiplier for matches in any path component (dir name or filename prefix). Useful for queries like "auth" that should find src/auth/... files.',
        [
          ['Path Scoring', '/docs/RETRIEVAL.md#path-scoring']
        ]
      ),

      // Generation & Temperature
      GEN_TEMPERATURE: L(
        'Default Response Creativity',
        'Global default temperature for generation. 0.0 = deterministic; small values (0.04-0.2) add slight variation in prose. Use per-model tuning for creative tasks vs. code answers.',
        [
          ['Sampling Controls', 'https://platform.openai.com/docs/guides/text-generation'],
          ['Nucleus/Top\u2011p', 'https://en.wikipedia.org/wiki/Nucleus_sampling']
        ]
      ),
      FREQUENCY_PENALTY: L(
        'Frequency Penalty',
        'Penalizes tokens that appear frequently in the generated text so far. Higher values reduce repetition and boilerplate; lower values allow more reuse of prior tokens. Typical ranges: 0.0-0.5 for code answers to avoid runaway repetition; 0.5-1.0 for verbose prose or summarization; >1.0 is rarely needed and can destabilize outputs. Applies per-token during sampling. Combine with TOP_P/TEMPERATURE carefully: high frequency penalty + high temperature can over-constrain and reduce coherence.',
        [
          ['OpenAI Sampling', 'https://platform.openai.com/docs/guides/text-generation'],
          ['Frequency Penalty API', 'https://platform.openai.com/docs/api-reference/chat/create#chat-create-frequency_penalty'],
          ['Decoding Strategies', 'https://huggingface.co/blog/how-to-generate']
        ],
        [['Anti-repetition','info'], ['Tune carefully','warn']]
      ),
      PRESENCE_PENALTY: L(
        'Presence Penalty',
        'Penalizes tokens that have already appeared, encouraging the model to introduce new topics/entities. Higher values increase exploration and reduce reuse of the same concepts. Use 0.0-0.4 for factual/code responses; 0.4-0.8 for brainstorming; >0.8 can push the model toward excessive novelty. Presence penalty interacts with TEMPERATURE/TOP_P: higher penalties with high temperature can make answers meander. For RAG, keep modest (<=0.5) to prevent drifting away from cited context.',
        [
          ['Presence Penalty API', 'https://platform.openai.com/docs/api-reference/chat/create#chat-create-presence_penalty'],
          ['Decoding Trade-offs', 'https://huggingface.co/blog/how-to-generate'],
          ['RAG Best Practices', 'https://langchain-ai.github.io/langgraph/'],
        ],
        [['Encourage novelty','info'], ['Risk: drift','warn']]
      ),
      GEN_MODEL_CHAT: L(
        'Chat-Specific Model',
        'Override model for Chat interface only. Leave empty to use GEN_MODEL. Useful for using a different model (e.g., faster/cheaper) specifically for interactive chat.',
        [
          ['OpenAI Models', 'https://platform.openai.com/docs/models'],
          ['Ollama API', 'https://github.com/ollama/ollama/blob/main/docs/api.md']
        ]
      ),

      // Multi-Query & Synonyms
      MAX_QUERY_REWRITES: L(
        'Multi\u2011Query Rewrites',
        'Number of LLM\u2011generated query variations. Each variation runs hybrid retrieval; results are merged and reranked. Higher improves recall but increases latency and API cost. Typical: 2\u20134.',
        [
          ['Multi\u2011Query Retriever', 'https://python.langchain.com/docs/how_to/MultiQueryRetriever/'],
          ['Multi\u2011Query RAG (paper)', 'https://arxiv.org/abs/2305.14283']
        ],
        [['Better recall','info'], ['Higher cost','warn']]
      ),
      LANGGRAPH_MAX_QUERY_REWRITES: L(
        'LangGraph Max Query Rewrites',
        'Number of query rewrites used inside the LangGraph answer pipeline (/answer). Separate from MAX_QUERY_REWRITES used by general multi-query retrieval. Higher values improve recall but increase latency and LLM cost. Typical: 2-4.',
        [
          ['LangGraph', 'https://langchain-ai.github.io/langgraph/'],
          ['Multi\u2011Query RAG (paper)', 'https://arxiv.org/abs/2305.14283']
        ],
        [['LangGraph only','info'], ['Higher cost','warn']]
      ),
      USE_SEMANTIC_SYNONYMS: L(
        'Semantic Synonyms Expansion',
        'Expands queries with curated domain synonyms and abbreviations (e.g., auth \u2192 authentication, oauth, jwt). Complements LLM rewrites. Configure in data/semantic_synonyms.json.',
        [
          ['Synonym Config', '/files/data/semantic_synonyms.json'],
          ['Synonym Guide', '/docs/RETRIEVAL.md#synonyms']
        ]
      ),
      TRIBRID_SYNONYMS_PATH: L(
        'Synonyms File Path',
        'Custom path to the semantic synonyms JSON file. Defaults to data/semantic_synonyms.json if empty. Use this to point to a repository-specific or custom synonym dictionary. The file should contain a JSON object mapping terms to arrays of synonyms (e.g., {"auth": ["authentication", "oauth", "jwt"]}).\n\n\u2022 Default: data/semantic_synonyms.json\n\u2022 Example: /path/to/custom_synonyms.json\n\u2022 Format: {"term": ["synonym1", "synonym2", ...]}\n\u2022 Works with: USE_SEMANTIC_SYNONYMS toggle',
        [
          ['Synonym Config', '/files/data/semantic_synonyms.json'],
          ['Synonym Expander', '/retrieval/synonym_expander.py']
        ],
        [['Optional override', 'info']]
      ),

      // Fusion & Scoring
      RRF_K_DIV: L(
        'Reciprocal Rank Fusion (K)',
        'Fusion parameter for combining BM25 + vector rankings: score += 1/(K+rank). Lower K increases influence of lower ranks; higher K flattens. Typical: 30\u2013100 (60 recommended).',
        [
          ['RRF Paper', 'https://www.cs.cmu.edu/~jgc/publication/The_Influence_of_Random_Sampling_on_the_Performance_of_Ensembles.pdf'],
          ['Hybrid Search', '/docs/RETRIEVAL.md#hybrid-search']
        ]
      ),
      CONF_FALLBACK: L(
        'Fallback Confidence Threshold',
        'When initial retrieval confidence falls below this threshold, triggers a fallback with expanded query rewrites. Lower = more aggressive fallback. Typical: 0.5\u20130.7.',
        [
          ['RAG Retrieval', '/docs/RETRIEVAL.md']
        ]
      ),
      LANGGRAPH_FINAL_K: L(
        'LangGraph Final K',
        'Documents retrieved for LangGraph pipeline in /answer. Separate from retrieval FINAL_K. Higher = more context, higher cost. Typical: 10\u201330.',
        [
          ['LangGraph', 'https://langchain-ai.github.io/langgraph/']
        ]
      ),

      // Exclude & Paths
      EXCLUDE_PATHS: L(
        'Exclude Directories',
        'Comma\u2011separated directories to exclude when building semantic Code Cards or indexing. Examples: node_modules, vendor, dist.',
        [
          ['Indexing Guide', '/docs/INDEXING.md']
        ]
      ),

      // Code Cards
      CODE_CARDS: L(
        'Code Cards',
        'High\u2011level semantic summaries of code chunks, built during enrichment. Cards enable intent\u2011based retrieval and better filtering for conceptual queries.',
        [
          ['Cards Feature', '/docs/CARDS.md'],
          ['Cards Builder', '/files/indexer/build_cards.py']
        ],
        [['Improves intent','info']]
      ),

      // Chat Settings (React Chat)
      CHAT_SETTINGS: L(
        'Chat Configuration',
        'Settings that control model, answer length, rewrite strategy, and retrieval size for the chat interface. These affect latency, cost, and answer quality.',
        [
          ['RAG Retrieval', '/docs/RETRIEVAL.md']
        ],
        [['Affects quality','info'], ['Affects latency','info']]
      ),
      CHAT_MAX_TOKENS: L(
        'Max Response Tokens (Chat)',
        'Upper bound on generated tokens for chat answers. ~4 chars \u2248 1 token. Higher values cost more and may slow responses.',
        [
          ['Tokenization Basics', 'https://huggingface.co/docs/transformers/main_classes/tokenizer']
        ]
      ),
      CHAT_CONFIDENCE_THRESHOLD: L(
        'Answer Confidence Threshold',
        'Minimum retrieval confidence to return an answer without fallback. Lower values return more answers (risking guesses); higher values are conservative.',
        [
          ['Precision vs Recall', 'https://en.wikipedia.org/wiki/Precision_and_recall']
        ]
      ),
      CHAT_TEMPERATURE: L(
        'Response Creativity (Chat)',
        'Controls randomness for chat answers. For code Q&A, prefer 0.0\u20130.3; for ideation, increase to 0.5\u20130.9.',
        [
          ['Sampling Controls', 'https://platform.openai.com/docs/guides/text-generation']
        ]
      ),
      CHAT_SHOW_CITATIONS: L(
        'Inline File References',
        'Display source file paths and line numbers inline with the answer. Citations become clickable links to code locations.',
        [
          ['Retrieval Traceability', '/docs/RETRIEVAL.md#traceability']
        ]
      ),
      CHAT_CONFIDENCE: L(
        'Retrieval Confidence',
        'Show a normalized confidence score (0\u20131) alongside answers to help judge reliability. Scores reflect retrieval confidence, not model certainty.',
        [
          ['Precision vs Recall', 'https://en.wikipedia.org/wiki/Precision_and_recall']
        ]
      ),
      CHAT_AUTO_SCROLL: L(
        'Auto\u2011Scroll to New Messages',
        'Automatically scrolls the conversation to the newest message. Disable when reviewing earlier context while messages stream.',
        [
          ['ARIA Live Regions (UX)', 'https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/ARIA_Live_Regions']
        ]
      ),
      CHAT_SYNTAX_HIGHLIGHT: L(
        'Code Block Highlighting',
        'Apply syntax highlighting to code blocks in responses. Improves readability in multi\u2011language projects. May increase render time on very long messages.',
        [
          ['Prism.js', 'https://prismjs.com/']
        ],
        [['UX','info']]
      ),
      CHAT_SYSTEM_PROMPT: L(
        'Custom System Prompt',
        'Override the default expert system prompt for Chat. Use to adjust tone, safety constraints, or provide domain instructions. Leave empty to use the built\u2011in TriBridRAG expert prompt.',
        [
          ['Prompt Engineering (Guide)', 'https://platform.openai.com/docs/guides/prompt-engineering']
        ]
      ),

      // Chat 2.0 (Pydantic keys used by React TooltipIcon)
      'chat.system_prompt_base': L(
        'System prompt (base)',
        'Legacy base prompt used for backward compatibility. If the selected 4-state system prompt is empty, TriBridRAG falls back to base + Recall/RAG suffix composition.',
        [
          ['Prompt engineering', 'https://platform.openai.com/docs/guides/prompt-engineering']
        ],
        [['Legacy', 'warn']]
      ),
      'chat.system_prompt_direct': L(
        'System prompt: Direct',
        'Sent when no retrieval context is provided (no RAG and no Recall results). This prompt must fully orient the model for direct chat.',
        [],
        [['Chat 2.0', 'info']]
      ),
      'chat.system_prompt_rag': L(
        'System prompt: RAG only',
        'Sent when RAG corpora returned results. Explains how to use <rag_context> and how to cite file paths and line numbers.',
        [],
        [['Chat 2.0', 'info']]
      ),
      'chat.system_prompt_recall': L(
        'System prompt: Recall only',
        'Sent when Recall returned results but no RAG context is present. Explains how to use <recall_context> chat history snippets.',
        [],
        [['Chat 2.0', 'info']]
      ),
      'chat.system_prompt_rag_and_recall': L(
        'System prompt: RAG + Recall',
        'Sent when both RAG and Recall context are present. Explains how to use both <rag_context> and <recall_context> together.',
        [],
        [['Chat 2.0', 'info']]
      ),
      'chat.recall_gate.enabled': L(
        'Recall gate enabled',
        'Enable smart per-message gating for Recall (chat memory). When disabled, Recall is always queried when checked.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.default_intensity': L(
        'Default Recall intensity',
        'Fallback intensity when the classifier is uncertain (skip/light/standard/deep). Only affects Recall; RAG corpora are always queried when checked.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.skip_greetings': L(
        'Skip greetings/acknowledgments',
        "Skip Recall for short conversational messages like 'hi', 'thanks', 'ok'. Avoids wasted embeddings + noisy context.",
        [],
        [['Latency', 'info'], ['Cost', 'info']]
      ),
      'chat.recall_gate.skip_standalone_questions': L(
        'Skip standalone questions',
        "Skip Recall for technical questions that don't depend on past conversation (e.g., 'How does auth work?').",
        [],
        [['Precision', 'info']]
      ),
      'chat.recall_gate.skip_when_rag_active': L(
        'Skip Recall when RAG active',
        'Optional: skip Recall if any non-Recall RAG corpora are checked. Default is off so both can contribute.',
        [],
        [['Advanced', 'info']]
      ),
      'chat.recall_gate.skip_max_tokens': L(
        'Max skip tokens',
        'Messages with \u2264 this many tokens are strong candidates for skipping Recall when they match a skip pattern.',
        [],
        [['Advanced', 'info']]
      ),
      'chat.recall_gate.light_for_short_questions': L(
        'Light for short questions',
        'For short questions that are not explicit Recall triggers, use light Recall (sparse-only, low top_k).',
        [],
        [['Latency', 'info']]
      ),
      'chat.recall_gate.light_top_k': L(
        'Light top_k',
        'Top-k results to include for light Recall queries.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.standard_top_k': L(
        'Standard top_k',
        'Top-k results to include for standard Recall queries.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.standard_recency_weight': L(
        'Standard recency weight',
        'Blend weight for recency vs relevance when scoring Recall results (0=relevance, 1=recency).',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.deep_on_explicit_reference': L(
        'Deep on explicit reference',
        'When the user explicitly references past conversation (\"we discussed\", \"you mentioned\"), use deep Recall.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.deep_top_k': L(
        'Deep top_k',
        'Top-k results to include for deep Recall queries.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.deep_recency_weight': L(
        'Deep recency weight',
        'Recency weight for deep Recall. Higher values bias toward more recent messages when the user asks about the past.',
        [],
        [['Recall', 'info']]
      ),
      'chat.recall_gate.show_gate_decision': L(
        'Show gate decision',
        'Show Recall gate intensity (skip/light/standard/deep) in the chat status bar.',
        [],
        [['Debug', 'info']]
      ),
      'chat.recall_gate.show_signals': L(
        'Show raw signals',
        'Show extracted RecallSignals + overrides in the debug footer (developer mode).',
        [],
        [['Debug', 'info']]
      ),
      chat_recall_intensity: L(
        'Recall intensity override (per message)',
        'Per-message override for Recall (chat memory) intensity. \"auto\" lets the gate decide; other values force behavior for the next message.',
        [],
        [['Chat 2.0', 'info']]
      ),
      CHAT_HISTORY: L(
        'Chat History Storage',
        'Controls how chat history is saved and loaded. History persists in browser localStorage only \u2014 no server storage for privacy.',
        [
          ['localStorage', 'https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage']
        ],
        [['Browser storage','info']]
      ),
      CHAT_HISTORY_ENABLED: L(
        'Save Chat Messages',
        'When enabled, messages are persisted to browser localStorage and restored on reload. Disable for ephemeral sessions or shared devices.',
        [
          ['localStorage', 'https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage']
        ]
      ),
      CHAT_HISTORY_LIMIT: L(
        'History Limit',
        'Maximum number of messages to retain in local history. Older messages are pruned when the limit is reached. Typical range: 50\u20131000.',
        [
          ['Usability: History & Recall', 'https://www.nngroup.com/articles/search-logs/']
        ]
      ),
      CHAT_HISTORY_LOAD_ON_START: L(
        'Load History on Startup',
        'Automatically loads and displays previous conversations when opening the Chat tab. Disable to start with a clean slate every session.',
        [
          ['localStorage', 'https://developer.mozilla.org/en-US/docs/Web/API/Window/localStorage']
        ]
      ),

      // Chunking Parameters
      CHUNK_SIZE: L(
        'Chunk Size',
        'Target size (in characters) for each indexed chunk. For AST chunking this acts as a guardrail when nodes are large. Larger chunks preserve more context but reduce recall; smaller chunks improve recall but may fragment semantics.',
        [
          ['LangChain: Text Splitters', 'https://python.langchain.com/docs/modules/data_connection/document_transformers/text_splitters/'],
          ['Okapi BM25 (context windows)', 'https://en.wikipedia.org/wiki/Okapi_BM25']
        ],
        [['Affects recall/precision','info']]
      ),
      CHUNK_OVERLAP: L(
        'Chunk Overlap',
        'Number of characters overlapped between adjacent chunks. Overlap reduces boundary effects and improves recall at the cost of a larger index and slower indexing.',
        [
          ['LangChain: Text Splitters', 'https://python.langchain.com/docs/modules/data_connection/document_transformers/text_splitters/']
        ]
      ),

      // Indexing Settings
      INDEX_MAX_WORKERS: L(
        'Index Max Workers',
        'Maximum number of parallel workers used during indexing. Increase to speed up indexing on multi\u2011core machines; decrease if you observe system contention. A good starting point is CPU cores \u2212 1.',
        [
          ['concurrent.futures', 'https://docs.python.org/3/library/concurrent.futures.html'],
          ['multiprocessing', 'https://docs.python.org/3/library/multiprocessing.html']
        ],
        [['Performance','info']]
      ),
      INDEXING_PROCESS: L(
        'Indexing Process',
        'Indexing prepares your code for retrieval: it chunks files, builds a BM25 sparse index, optionally generates dense embeddings, and writes vectors to Qdrant. Re\u2011run after significant code changes to keep answers fresh.',
        [
          ['Okapi BM25', 'https://en.wikipedia.org/wiki/Okapi_BM25'],
          ['Qdrant Docs', 'https://qdrant.tech/documentation/']
        ]
      ),
      INDEX_PROFILES: L(
        'Index Profiles',
        'Preset configurations for common workflows: shared (BM25\u2011only, fast), full (BM25 + embeddings, best quality), dev (small subset). Profiles change multiple parameters at once to match your goal.',
        [
          ['Indexing Guide', '/docs/INDEXING.md']
        ],
        [['Convenience','info']]
      ),

      // Ollama Timeouts
      OLLAMA_REQUEST_TIMEOUT: L(
        'Local Request Timeout (seconds)',
        'Maximum total time to wait for a single local (Ollama) generation request to complete. Increase for long answers; decrease to fail fast on slow models or poor connectivity.',
        [
          ['Ollama API: Generate', 'https://github.com/ollama/ollama/blob/main/docs/api.md#generate-a-completion'],
          ['HTTP Timeouts', 'https://developer.mozilla.org/en-US/docs/Web/HTTP/Timeouts']
        ]
      ),
      OLLAMA_STREAM_IDLE_TIMEOUT: L(
        'Local Stream Idle Timeout (seconds)',
        'Maximum idle time allowed between streamed chunks from local (Ollama). If no tokens arrive within this window, the request aborts to prevent hanging streams.',
        [
          ['Streaming Basics', 'https://developer.mozilla.org/en-US/docs/Web/API/ReadableStream'],
          ['Ollama Streaming', 'https://github.com/ollama/ollama/blob/main/docs/api.md#streaming']
        ]
      ),

      // Backend Selection
      VECTOR_BACKEND: L(
        'Vector Backend',
        'Selects the vector search backend used for dense retrieval. Postgres (pgvector) is the default backend in TriBridRAG and stores your embedding vectors for fast similarity search. Use this to switch between implementations when benchmarking or troubleshooting.',
        [
          ['Qdrant Docs', 'https://qdrant.tech/documentation/'],
          ['LangChain Vector Stores', 'https://python.langchain.com/docs/integrations/vectorstores/']
        ],
        [['Core Setting','info']]
      ),
      RERANKER_BACKEND: L(
        'Reranker Backend',
        'Choose the reranking provider to reorder retrieved results by semantic relevance (cross-encoder). Options typically include Cohere Rerank, the built\u2011in TriBridRAG Learning Reranker, or none. Reranking improves answer quality but adds latency.',
        [
          ['Cohere Rerank', 'https://docs.cohere.com/docs/rerank'],
          ['Sentence\u2011Transformers (Cross\u2011Encoders)', 'https://www.sbert.net/examples/training/cross-encoder/README.html']
        ],
        [['Improves quality','info']]
      ),
      RERANK_INPUT_SNIPPET_CHARS: L(
        'Rerank Snippet Length',
        'Maximum characters from each candidate chunk sent to the reranker. Keeps payloads within provider limits and focuses scoring on the most relevant prefix. Typical range: 400-1200 chars. Use 400-600 when providers reject long inputs or latency is critical; 800-1200 when answers depend on longer doc/context blocks. If set too low, quality drops from missing context; too high increases latency and rerank cost per request.',
        [
          ['Voyage reranker token limits', 'https://docs.voyageai.com/docs/reranker'],
          ['Cohere rerank context length', 'https://docs.cohere.com/docs/rerank']
        ],
        [['Affects latency/cost', 'warn'], ['Context guardrail', 'info']]
      ),
      RERANKER_TRAIN_MAX_LENGTH: L(
        'Reranker Train Max Length',
        'Maximum token length for reranker training examples. Longer sequences may improve context but require more memory and training time. Typical range: 256\u20131024.',
        [
          ['Transformers: Tokenization', 'https://huggingface.co/docs/transformers/main_classes/tokenizer']
        ]
      ),

      // TriBridRAG Learning Reranker (RERANKER_MODE is defined earlier at ~line 236)
      TRIBRID_RERANKER_MODEL_PATH: L(
        'Reranker Model Path',
        'Filesystem path to the trained reranker model checkpoint directory (relative paths recommended). The service loads weights from this path on startup or when reloaded.',
        [
          ['Model Checkpoints', 'https://huggingface.co/docs/transformers/main_classes/model#transformers.PreTrainedModel.from_pretrained']
        ]
      ),
      TRIBRID_LOG_PATH: L(
        'Reranker Log Path',
        'Directory where the reranker writes logs and training progress. Useful for monitoring and resuming experiments. Ensure the path is writable by the server process.',
        [
          ['Python logging', 'https://docs.python.org/3/library/logging.html']
        ]
      ),
      TRIBRID_TRIPLETS_PATH: L(
        'Triplets Dataset Path',
        'Path to mined triplets used for training the Learning Reranker. Triplets contain (query, positive, negative) examples. Keep under version control or in a reproducible data store.',
        [
          ['Triplet Loss', 'https://en.wikipedia.org/wiki/Triplet_loss'],
          ['SBERT Training Data', 'https://www.sbert.net/examples/training/cross-encoder/README.html']
        ]
      ),
      TRIBRID_RERANKER_MINE_MODE: L(
        'Triplet Mining Mode',
        'Strategy for mining training triplets: random, semi\u2011hard, or hard negatives. Harder negatives improve discriminative power but may be noisier and slower to mine.',
        [
          ['Hard Negative Mining', 'https://sbert.net/examples/training/quora_duplicate_questions/README.html']
        ],
        [['Advanced','info']]
      ),
      TRIBRID_RERANKER_MINE_RESET: L(
        'Reset Triplets Before Mining',
        'If enabled, deletes existing mined triplets before starting a new mining run. Use with caution to avoid losing curated datasets.',
        [
          ['Data Management', '/docs/LEARNING_RERANKER.md#mining']
        ],
        [['Destructive','warn']]
      ),

      // === MIGRATED FROM useTooltips.ts (React-only tooltips now unified) ===

      // Path Overrides
      REPO_ROOT: L(
        'Repository Root Override',
        'Override the auto-detected project root directory. TriBridRAG normally detects the repository root automatically by walking up from the current working directory to find .git or pyproject.toml. Use this setting when running in Docker, when TriBridRAG is installed outside the repository, or when you need to force a specific root path. Leave empty to use auto-detection. Example: /workspace/myproject',
        [
          ['Path Resolution', 'https://en.wikipedia.org/wiki/Path_(computing)#Absolute_and_relative_paths'],
          ['Docker Volume Mounts', 'https://docs.docker.com/storage/volumes/'],
          ['Project Structure', '/docs/DIRECTORY_STRUCTURE.md']
        ],
        [['Optional', 'info'], ['Docker-friendly', 'info']]
      ),
      FILES_ROOT: L(
        'Files Root Override',
        'Override the root directory for the /files HTTP mount point. This setting controls where the FastAPI static file server looks for files when serving requests to /files/*. By default, TriBridRAG uses the repository root. Set this when you need to serve files from a different location, such as a mounted volume in Docker, a shared NFS mount, or a custom data directory. Example: /mnt/shared/tribrid-files',
        [
          ['Static Files (FastAPI)', 'https://fastapi.tiangolo.com/tutorial/static-files/'],
          ['File Serving', '/docs/FILE_SERVING.md'],
          ['Docker Volumes', 'https://docs.docker.com/storage/volumes/#use-a-volume-with-docker-compose']
        ],
        [['Optional', 'info'], ['Advanced', 'warn']]
      ),
      GUI_DIR: L(
        'UI Public Directory',
        'Directory for shared UI assets (for example: models.json) used by /api/models and the frontend. Defaults to ./web/public. Point this to a writable volume if you keep catalogs in sync at runtime; the React app reads from the same source.',
        [
          ['Static Files (FastAPI)', 'https://fastapi.tiangolo.com/tutorial/static-files/'],
          ['models catalog', '/web/models.json']
        ],
        [['Recommended', 'info']]
      ),
      DOCS_DIR: L(
        'Documentation Directory',
        'Path to the documentation directory containing markdown files, API references, and user guides. This directory is served at /docs/* by the FastAPI static file handler, making documentation accessible through the web interface. Used by the built-in documentation viewer and help system. Default is ./docs. Change this if you have moved your documentation to a custom location or are using a shared docs directory across multiple projects.',
        [
          ['Documentation Index', '/docs/README.md'],
          ['API Reference', '/docs/API_REFERENCE.md'],
          ['Static File Serving', 'https://fastapi.tiangolo.com/tutorial/static-files/']
        ],
        [['Optional', 'info']]
      ),

      // Eval UI Elements
      EVAL_LOGS_TERMINAL: L(
        'Evaluation Logs Terminal',
        'Open the sliding terminal to stream raw evaluation output (question-by-question) and verify the exact settings used for the last run.',
        [
          ['Evaluation Guide', '/docs/EVALUATION.md']
        ],
        [['Live output', 'info']]
      ),
      EVAL_PRIMARY_RUN: L(
        'Primary Run (AFTER)',
        'Select the evaluation run to analyze. This is typically the most recent run you want to inspect. When comparing, this is the "AFTER" run showing your latest configuration changes. The accuracy metrics and question results will be displayed from this run.',
        [
          ['Evaluation Guide', '/docs/EVALUATION.md']
        ],
        [['Required', 'info']]
      ),
      EVAL_COMPARE_RUN: L(
        'Compare With (BEFORE)',
        'Optionally select a previous evaluation run to compare against. This enables the configuration diff view showing exactly what parameters changed between runs, and highlights regressions (questions that got worse) vs improvements. The AI Analysis will use both runs to provide root cause analysis and recommendations.',
        [
          ['Evaluation Guide', '/docs/EVALUATION.md']
        ],
        [['Optional', 'info'], ['Enables AI Analysis', 'success']]
      ),
      EVAL_ANALYSIS_SUBTAB: L(
        'Eval Analysis',
        'View and compare RAG evaluation runs. Analyze retrieval accuracy metrics, see question-by-question results, compare configuration changes between runs, and get AI-powered insights on performance regressions and recommendations.',
        [
          ['Evaluation Guide', '/docs/EVALUATION.md']
        ],
        [['Deep-dive analysis', 'info']]
      ),
      SYSTEM_PROMPTS_SUBTAB: L(
        'System Prompts',
        'Edit LLM system prompts that control RAG pipeline behavior. These prompts are used for query expansion, chat responses, semantic card generation, code enrichment, and eval analysis. Changes are saved to tribrid_config.json (or per-corpus config) and take effect immediately.',
        [
          ['Prompt Engineering', 'https://www.anthropic.com/news/prompt-engineering']
        ],
        [['Live reload', 'success']]
      ),
      RUN_EVAL_ANALYSIS: L(
        'Run RAG Evaluation',
        'Execute the full RAG evaluation suite using your current configuration settings. This runs all golden questions through the retrieval pipeline and measures Top-1 and Top-K accuracy. A live terminal will slide down showing real-time progress, and results will automatically appear in the Eval Analysis view when complete.',
        [
          ['Evaluation Guide', '/docs/EVALUATION.md'],
          ['Golden Questions', '/data/golden.json']
        ],
        [['Uses current config', 'info'], ['~1-5 min runtime', 'warn']]
      ),
      INDEX_LOGS_TERMINAL: L(
        'Indexing Logs Terminal',
        'Open the sliding terminal to stream raw indexer output with the exact repo/skip_dense/enrich settings used for the run.',
        [
          ['Indexing Guide', '/docs/INDEXING.md']
        ],
        [['Live output', 'info']]
      ),
      DASHBOARD_INDEX_PANEL: L(
        'Index Readiness',
        'Live embedding config, indexing cost, and storage requirements pulled directly from /api/index/status. Updates automatically every 30 seconds and mirrors the legacy GUI layout exactly.',
        [],
        [['Auto-refresh', 'info']]
      ),

      // MCP Extended
      MCP_SERVER_URL: L(
        'MCP Server URL',
        'Complete URL for the HTTP MCP server. Combines host, port, and path into a single endpoint that MCP clients connect to.',
        [
          ['Docs: Remote MCP', '/docs/REMOTE_MCP.md'],
          ['Model Context Protocol', 'https://modelcontextprotocol.io']
        ]
      ),
      MCP_API_KEY: L(
        'MCP API Key (Optional)',
        'Authentication key for securing MCP server access. Stored in .env file. Leave empty to disable authentication (not recommended for production).',
        [
          ['MCP Security Guide', '/docs/REMOTE_MCP.md']
        ],
        [['Stored in .env', 'security']]
      ),

      // Monitoring & Alerts
      ERROR_RATE_THRESHOLD: L(
        'Error Rate Threshold (%)',
        'Percentage threshold for triggering error rate alerts. When the error rate across all requests exceeds this percentage over a 5-minute window, Grafana will trigger an alert. Typical values: 5% for production (strict), 10-15% for development. Set lower for critical systems, higher for experimental features.',
        [
          ['Grafana Alerting', 'https://grafana.com/docs/grafana/latest/alerting/'],
          ['SLOs and Error Budgets', 'https://sre.google/sre-book/service-level-objectives/']
        ],
        [['Performance', 'warn']]
      ),
      TIMEOUT_ERRORS_THRESHOLD: L(
        'Timeout Errors (per 5 min)',
        'Maximum number of timeout errors allowed in a 5-minute window before triggering an alert. Timeout errors indicate requests that took too long and were forcibly terminated. Common causes: slow LLM APIs, overloaded database, network issues. Typical values: 10-20 for production, 50+ for development.',
        [
          ['Timeout Best Practices', 'https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/']
        ],
        [['Reliability', 'err']]
      ),
      RATE_LIMIT_ERRORS_THRESHOLD: L(
        'Rate Limit Errors (per 5 min)',
        'Maximum number of rate limit errors (HTTP 429) allowed in a 5-minute window. Rate limits protect against excessive API usage and prevent cost overruns. Common sources: OpenAI API, Cohere, Voyage AI. If this alert fires frequently, consider upgrading API tier or implementing request batching.',
        [
          ['Rate Limiting (OpenAI)', 'https://platform.openai.com/docs/guides/rate-limits'],
          ['Backoff Strategies', 'https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/']
        ],
        [['Cost Control', 'warn']]
      ),
      ENDPOINT_CALL_FREQUENCY: L(
        'Endpoint Call Frequency (calls/min)',
        'Alert when a single API endpoint receives this many calls per minute. Detects infinite loops, polling gone wrong, or DDoS-like patterns. For example, if /api/search is called 100 times/min for 2+ minutes, something is likely wrong. Typical values: 10-30 calls/min for normal usage, 100+ for high-traffic production.',
        [
          ['API Rate Patterns', '/docs/API_MONITORING.md']
        ],
        [['Anomaly Detection', 'warn']]
      ),
      ENDPOINT_SUSTAINED_DURATION: L(
        'Sustained Frequency Duration (minutes)',
        'How long the high call frequency must be sustained before triggering an alert. Prevents false positives from legitimate bursts. For example, if frequency threshold is 20 calls/min and duration is 2 minutes, the endpoint must receive 20+ calls/min for 2 consecutive minutes to alert. Typical values: 2-5 minutes for quick detection, 10+ for noise reduction.',
        [
          ['Alert Design Patterns', 'https://grafana.com/docs/grafana/latest/alerting/fundamentals/']
        ],
        [['Anomaly Detection', 'warn']]
      ),
      COHERE_RERANK_CALLS: L(
        'Cohere Rerank Calls (calls/min)',
        'Alert when Cohere reranking API is called this many times per minute. Reranking is expensive ($1-2 per 1M tokens) and high call rates can quickly increase costs. Normal usage: 5-10 calls/min. If this spikes to 50+, check for loops or unnecessary reranking. Consider caching rerank results or using local reranker instead.',
        [
          ['Cohere Pricing', 'https://cohere.com/pricing'],
          ['Reranking Strategy', '/docs/RERANKING.md']
        ],
        [['Cost Control', 'warn'], ['API Usage', 'info']]
      ),

      // Chat Extended
      CHAT_STREAM_INCLUDE_THINKING: L(
        'Include Thinking in Stream',
        'When enabled and using a thinking/reasoning model (like Anthropic Claude with extended thinking or OpenAI o-series), the model\'s reasoning process will be streamed to the UI before the final answer. This provides transparency into how the model arrived at its conclusion but increases response length. Disable if you only want final answers without reasoning traces.',
        [
          ['Anthropic Extended Thinking', 'https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking'],
          ['OpenAI Reasoning Models', 'https://platform.openai.com/docs/guides/reasoning']
        ],
        [['Advanced', 'info']]
      ),
      CHAT_DEFAULT_MODEL: L(
        'Default Chat Model',
        'Default LLM model used for chat when not overridden per-request. Common options: gpt-4o-mini (fast/cheap), gpt-4o (balanced), claude-3-5-sonnet (high quality), or local Ollama models. Per-request model overrides take precedence.',
        [
          ['OpenAI Models', 'https://platform.openai.com/docs/models'],
          ['Anthropic Models', 'https://docs.anthropic.com/en/docs/about-claude/models']
        ]
      ),
      CHAT_STREAM_TIMEOUT: L(
        'Stream Timeout (seconds)',
        'Maximum time in seconds to wait for a streaming chat response to complete. If the stream doesn\'t finish within this time, the connection will be closed. Increase for complex queries that require longer generation times. Default: 120 seconds (2 minutes). Range: 30-600 seconds.',
        [
          ['HTTP Timeouts', 'https://developer.mozilla.org/en-US/docs/Web/API/fetch#options']
        ],
        [['Affects reliability', 'info']]
      ),
      CHAT_THINKING_BUDGET_TOKENS: L(
        'Thinking Budget Tokens',
        'Maximum number of tokens allocated for the model\'s internal reasoning/thinking process when using thinking-enabled models like Anthropic Claude with extended thinking. Higher budgets allow deeper reasoning but increase latency and cost. Only applies when using models that support extended thinking. Default: 10,000 tokens. Range: 1,000-100,000.',
        [
          ['Anthropic Thinking Budget', 'https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking#budget-tokens']
        ],
        [['Cost', 'warning']]
      ),

      // Reranker Extended
      RERANKER_ACTIVE: L(
        'Active Reranker',
        'Route reranking to local vs cloud.\n\u2022 local/learning \u2014 on-host (includes TriBridRAG learning reranker)\n\u2022 cloud \u2014 uses provider/model from models.json\n\u2022 none/off \u2014 disables rerank. If cloud is selected but provider/model are empty, rerank is effectively disabled.',
        [],
        [['Required', 'info']]
      ),
      RERANKER_PROVIDER: L(
        'Cloud Provider (models.json)',
        'Provider id for cloud reranking, loaded dynamically from models.json via /api/models. Examples: cohere, voyage, openai, or any custom provider you add. No hardcoded lists; extend models.json to expose more providers.',
        [
          ['models.json catalog (API)', '/api/models']
        ],
        [['models.json-driven', 'info']]
      ),
      RERANKER_CLOUD_MODEL: L(
        'Cloud Model',
        'Provider-scoped rerank model id from models.json. Examples: rerank-3.5 (cohere), rerank-2 (voyage), or any custom id you add. Model list comes from models.json; add entries there to surface more options in this picker.',
        [
          ['models.json catalog (API)', '/api/models']
        ],
        [['Provider-scoped', 'info']]
      ),
      RERANKER_TIMEOUT: L(
        'Reranker Timeout',
        'Timeout (seconds) for cloud reranker HTTP calls. Larger timeouts reduce false failures on slow providers; smaller timeouts fail fast when endpoints are slow or unreachable. Applies only to cloud backends.',
        [],
        [['Reliability', 'info']]
      ),

      // Embedding Status
      EMBEDDING_MISMATCH: L(
        'Embedding Type Mismatch',
        'Your current embedding configuration differs from what was used to create your index. This is a CRITICAL issue that will cause search to return completely irrelevant results. Embeddings are mathematical representations of text in high-dimensional vector space - when you use different embedding models, these vectors exist in incompatible spaces and cannot be meaningfully compared. Think of it like trying to search a French dictionary using Spanish words - the dimensions and meaning of the numbers don\'t align. You must either: (1) Re-index your code with the current embedding type, or (2) Change your embedding configuration back to match what the index was built with.',
        [
          ['What are Embeddings?', 'https://platform.openai.com/docs/guides/embeddings'],
          ['Vector Space Explained', 'https://en.wikipedia.org/wiki/Vector_space'],
          ['Semantic Search', 'https://www.pinecone.io/learn/semantic-search/'],
          ['Embedding Model Comparison', 'https://huggingface.co/spaces/mteb/leaderboard']
        ],
        [['Critical', 'err'], ['Requires Action', 'warn']]
      ),
      EMBEDDING_MATCH: L(
        'Embedding Configuration Valid',
        'Your current embedding configuration matches what was used to create the index. Search results will be accurate and relevant. The vectors in your index are compatible with queries generated using your current embedding model.',
        [
          ['Embedding Guide', '/docs/EMBEDDING.md'],
          ['Retrieval Configuration', '/docs/RETRIEVAL.md']
        ],
        [['Valid', 'info']]
      ),

      // Docker Settings
      DOCKER_STATUS_TIMEOUT: L(
        'Docker Status Timeout',
        'Maximum seconds to wait when checking Docker daemon status. Increase if your Docker host is slow to respond or under heavy load. If health checks timeout frequently, raise this value. Range: 1-30 seconds.',
        [
          ['Docker Health Checks', 'https://docs.docker.com/engine/reference/commandline/inspect/'],
          ['Docker Daemon', 'https://docs.docker.com/config/daemon/']
        ],
        [['Performance', 'info']]
      ),
      DOCKER_CONTAINER_LIST_TIMEOUT: L(
        'Container List Timeout',
        'Maximum seconds to wait when listing all Docker containers. Increase if you have many containers (100+) or slow Docker API response. Range: 1-60 seconds.',
        [
          ['Docker ps command', 'https://docs.docker.com/engine/reference/commandline/ps/'],
          ['Container Management', 'https://docs.docker.com/config/containers/']
        ],
        [['Performance', 'info']]
      ),
      DOCKER_CONTAINER_ACTION_TIMEOUT: L(
        'Container Action Timeout',
        'Maximum seconds to wait for container start/stop/restart operations. Containers with complex startup sequences or cleanup hooks may need higher values. If container actions timeout, increase this. Range: 5-120 seconds.',
        [
          ['Container Lifecycle', 'https://docs.docker.com/config/containers/start-containers-automatically/'],
          ['Stop Containers', 'https://docs.docker.com/engine/reference/commandline/stop/']
        ],
        [['Container operations', 'info']]
      ),
      DOCKER_INFRA_UP_TIMEOUT: L(
        'Infrastructure Up Timeout',
        'Maximum seconds to wait when starting TriBridRAG infrastructure services (Postgres, Neo4j, Grafana, Loki, etc.) via docker-compose. First-time startup may pull images and take longer. If infra up fails with timeout, increase this value. Range: 30-300 seconds.',
        [
          ['Docker Compose', 'https://docs.docker.com/compose/'],
          ['TriBridRAG Infrastructure', '/infra/docker-compose.yml']
        ],
        [['Infrastructure startup', 'info'], ['May pull images', 'warn']]
      ),
      DOCKER_INFRA_DOWN_TIMEOUT: L(
        'Infrastructure Down Timeout',
        'Maximum seconds to wait when stopping TriBridRAG infrastructure services. Containers with data persistence may need time to flush to disk. If infra down fails, increase this value. Range: 10-120 seconds.',
        [
          ['Docker Compose Down', 'https://docs.docker.com/compose/reference/down/'],
          ['Graceful Shutdown', 'https://docs.docker.com/engine/reference/commandline/stop/#extended-description']
        ],
        [['Infrastructure shutdown', 'info']]
      ),
      DOCKER_LOGS_TAIL: L(
        'Log Lines to Tail',
        'Number of log lines to display when viewing container logs. Higher values show more history but may slow down log retrieval. Use 50-100 for quick checks, 500-1000 for debugging. Range: 10-1000 lines.',
        [
          ['Docker Logs', 'https://docs.docker.com/engine/reference/commandline/logs/'],
          ['Log Management', 'https://docs.docker.com/config/containers/logging/']
        ],
        [['Log visibility', 'info']]
      ),
      DOCKER_LOGS_TIMESTAMPS: L(
        'Include Log Timestamps',
        'Whether to include timestamps in Docker log output. Timestamps help correlate events across containers but add visual noise. Set to 1 to show timestamps, 0 to hide them.',
        [
          ['Docker Logs Timestamps', 'https://docs.docker.com/engine/reference/commandline/logs/#options'],
          ['Log Analysis', 'https://grafana.com/docs/loki/latest/']
        ],
        [['Log format', 'info']]
      ),
      DOCKER_INFRASTRUCTURE_SERVICES: L(
        'Infrastructure Services',
        'TriBridRAG infrastructure containers that power the RAG engine. Includes Postgres (storage + pgvector), Neo4j (graph), Grafana (monitoring), Loki (log aggregation), Prometheus (metrics), and Alertmanager (notifications). Start all services with "Start All" or manage individually.',
        [
          ['TriBridRAG Architecture', '/docs/ARCHITECTURE.md'],
          ['Infrastructure Setup', '/infra/docker-compose.yml']
        ],
        [['Core services', 'info']]
      ),
      DOCKER_STATUS: L(
        'Docker Status',
        'Real-time status of the Docker daemon connection. Shows whether TriBridRAG can communicate with Docker to manage containers. If status is unhealthy, ensure Docker Desktop is running or the Docker daemon is accessible.',
        [
          ['Docker Daemon', 'https://docs.docker.com/config/daemon/'],
          ['Troubleshooting', 'https://docs.docker.com/config/daemon/troubleshoot/']
        ],
        [['Health check', 'info']]
      ),
      DOCKER_ALL_CONTAINERS: L(
        'All Containers',
        'Complete list of Docker containers on this host, including running, stopped, and paused containers. Use this view to manage container lifecycle (start, stop, restart, pause, remove) and view logs for debugging.',
        [
          ['Container States', 'https://docs.docker.com/engine/reference/commandline/ps/'],
          ['Container Management', 'https://docs.docker.com/config/containers/']
        ],
        [['Container management', 'info']]
      ),
      DOCKER_SETTINGS: L(
        'Docker Settings',
        'Configuration settings for Docker timeouts and log behavior. These settings control how long TriBridRAG waits for Docker operations and how logs are displayed. Adjust these if you experience timeouts or need more/less log output.',
        [
          ['Docker Configuration', 'https://docs.docker.com/config/'],
          ['TriBridRAG Config', '/tribrid_config.json']
        ],
        [['Configurable', 'info']]
      ),
    };
  }

  /**
   * ---agentspec
   * what: |
   *   Attaches hover/focus listeners to icon element. Shows/hides tooltip bubble with debounced hide delay.
   *
   * why: |
   *   Centralizes tooltip lifecycle (show immediate, hide debounced) to prevent flicker on rapid mouse movement.
   *
   * guardrails:
   *   - DO NOT clear timeout on hide(); only on show() to enforce debounce
   *   - NOTE: hideTimeout persists across show/hide cycles; ensure cleanup on unmount
   * ---/agentspec
   */
  function attachTooltipListeners(icon, bubble, wrap) {
    let hideTimeout = null;

    /**
     * ---agentspec
     * what: |
     *   Controls tooltip visibility. show() adds 'tooltip-visible' class; hide() delays removal via setTimeout to allow mouse movement to tooltip.
     *
     * why: |
     *   Timeout prevents flickering when user moves cursor between trigger and tooltip.
     *
     * guardrails:
     *   - DO NOT call hide() without clearTimeout first; prevents stale timeouts
     *   - NOTE: hideTimeout must be module-scoped or closure-captured
     * ---/agentspec
     */
    function show(){
      clearTimeout(hideTimeout);
      bubble.classList.add('tooltip-visible');
    }

    /**
     * ---agentspec
     * what: |
     *   Hides tooltip bubble after 150ms delay. Clears prior timeout to prevent race conditions.
     *
     * why: |
     *   Delay allows user to move mouse from icon to tooltip without flickering.
     *
     * guardrails:
     *   - DO NOT remove delay; causes tooltip to vanish mid-interaction
     *   - NOTE: clearTimeout() prevents stacked hide calls
     * ---/agentspec
     */
    function hide(){
      // Delay hiding to allow moving mouse to tooltip
      clearTimeout(hideTimeout);
      hideTimeout = setTimeout(() => {
        bubble.classList.remove('tooltip-visible');
      }, 150);
    }

    // Show on icon hover/focus
    icon.addEventListener('mouseenter', show);
    icon.addEventListener('mouseleave', hide);
    icon.addEventListener('focus', show);
    icon.addEventListener('blur', hide);

    // Keep tooltip visible when hovering over it
    bubble.addEventListener('mouseenter', show);
    bubble.addEventListener('mouseleave', hide);

    // Toggle on click
    icon.addEventListener('click', (e) => {
      e.stopPropagation();
      clearTimeout(hideTimeout);
      bubble.classList.toggle('tooltip-visible');
    });

    // Hide when clicking outside
    document.addEventListener('click', (evt) => {
      if (!wrap.contains(evt.target)) {
        clearTimeout(hideTimeout);
        bubble.classList.remove('tooltip-visible');
      }
    });
  }

  /**
   * ---agentspec
   * what: |
   *   Attaches click/hover listeners to manually-created tooltip elements in DOM. Queries .tooltip-wrap, finds .help-icon and .tooltip-bubble children, binds show/hide behavior. Skips if already attached (checks dataset.tooltipAttached).
   *
   * why: |
   *   Prevents double-binding and centralizes tooltip initialization for static HTML tooltips outside framework lifecycle.
   *
   * guardrails:
   *   - DO NOT re-attach if dataset.tooltipAttached already set; causes duplicate listeners
   *   - NOTE: Requires .tooltip-wrap > (.help-icon + .tooltip-bubble) structure
   *   - ASK USER: Define show/hide behavior (click vs hover vs both)
   * ---/agentspec
   */
  function attachManualTooltips() {
    // Attach event listeners to any manually-created tooltips in HTML
    const manualTooltips = document.querySelectorAll('.tooltip-wrap');
    manualTooltips.forEach((wrap) => {
      const icon = wrap.querySelector('.help-icon');
      const bubble = wrap.querySelector('.tooltip-bubble');
      if (!icon || !bubble) return;
      // Check if already has listeners (avoid double-attaching)
      if (icon.dataset.tooltipAttached) return;
      icon.dataset.tooltipAttached = 'true';
      attachTooltipListeners(icon, bubble, wrap);
    });
  }

  /**
   * ---agentspec
   * what: |
   *   Builds tooltip map, then attaches tooltips to form fields by name. Iterates DOM fields, matches labels, skips missing name/parent/label.
   *
   * why: |
   *   Centralizes tooltip logic via map lookup; avoids inline hardcoding.
   *
   * guardrails:
   *   - DO NOT attach tooltip if name, parent, or label missing; silently skip
   *   - NOTE: Assumes .input-group wrapper and label sibling exist
   * ---/agentspec
   */
  function attachTooltips(){
    const map = buildTooltipMap();
    const fields = document.querySelectorAll('[name]');
    fields.forEach((field) => {
      const name = field.getAttribute('name');
      const parent = field.closest('.input-group');
      if (!name || !parent) return;
      const label = parent.querySelector('label');
      if (!label) return;
      if (label.querySelector('.help-icon')) return;
      
      // Skip labels that are part of toggle controls - they have special structure
      if (label.classList.contains('toggle')) {
        // For toggle labels, we need to preserve the existing structure
        // and only add tooltips to the label text, not replace everything
        const existingText = label.querySelector('.toggle-label');
        if (existingText && !label.querySelector('.help-icon')) {
          // Build tooltip HTML (same keying as non-toggle path)
          let key = name;
          if (name.startsWith('repo_')) {
            const type = name.split('_')[1];
            key = 'repo_' + type;
          }
          let htmlContent = map[key];
          if (!htmlContent) {
            htmlContent = `<span class=\"tt-title\">${name}</span><div>No detailed tooltip available yet. See our docs for related settings.</div><div class=\"tt-links\"><a href=\"/README.md\" target=\"_blank\" rel=\"noopener\">Main README</a> <a href=\"/docs/README_INDEX.md\" target=\"_blank\" rel=\"noopener\">Docs Index</a></div>`;
          }
          const spanText = document.createElement('span');
          spanText.className = 'label-text';
          spanText.textContent = existingText.textContent;
          existingText.textContent = '';
          existingText.appendChild(spanText);
          const wrap = document.createElement('span');
          wrap.className = 'tooltip-wrap';
          const icon = document.createElement('span');
          icon.className = 'help-icon';
          icon.setAttribute('tabindex', '0');
          icon.setAttribute('aria-label', `Help: ${name}`);
          icon.textContent = '?';
          icon.dataset.tooltipAttached = 'true';
          const bubble = document.createElement('div');
          bubble.className = 'tooltip-bubble';
          bubble.setAttribute('role', 'tooltip');
          bubble.innerHTML = htmlContent;
          wrap.appendChild(icon);
          wrap.appendChild(bubble);
          existingText.appendChild(wrap);
          attachTooltipListeners(icon, bubble, wrap);
        }
        return;
      }
      let key = name;
      if (name.startsWith('repo_')) {
        const type = name.split('_')[1];
        key = 'repo_' + type;
      }
      let html = map[key];
      if (!html) {
        html = `<span class=\"tt-title\">${name}</span><div>No detailed tooltip available yet. See our docs for related settings.</div><div class=\"tt-links\"><a href=\"/README.md\" target=\"_blank\" rel=\"noopener\">Main README</a> <a href=\"/docs/README_INDEX.md\" target=\"_blank\" rel=\"noopener\">Docs Index</a></div>`;
      }
      const spanText = document.createElement('span');
      spanText.className = 'label-text';
      spanText.textContent = label.textContent;
      label.textContent = '';
      label.appendChild(spanText);
      const wrap = document.createElement('span');
      wrap.className = 'tooltip-wrap';
      const icon = document.createElement('span');
      icon.className = 'help-icon';
      icon.setAttribute('tabindex', '0');
      icon.setAttribute('aria-label', `Help: ${name}`);
      icon.textContent = '?';
      icon.dataset.tooltipAttached = 'true';
      const bubble = document.createElement('div');
      bubble.className = 'tooltip-bubble';
      bubble.setAttribute('role', 'tooltip');
      bubble.innerHTML = html;
      wrap.appendChild(icon);
      wrap.appendChild(bubble);
      label.appendChild(wrap);
      attachTooltipListeners(icon, bubble, wrap);
    });

    // Also attach to manual tooltips in HTML
    attachManualTooltips();

    // Also attach tooltips for training controls that are identified by id (no name attributes)
    const trainingFields = [
      { id: 'reranker-epochs', key: 'RERANKER_TRAIN_EPOCHS' },
      { id: 'reranker-batch', key: 'RERANKER_TRAIN_BATCH' },
      { id: 'reranker-maxlen', key: 'RERANKER_TRAIN_MAXLEN' },
    ];
    trainingFields.forEach(({id, key}) => {
      const field = document.getElementById(id);
      if (!field) return;
      const parent = field.closest('.input-group');
      if (!parent) return;
      const label = parent.querySelector('label');
      if (!label || label.querySelector('.help-icon')) return;
      let html = map[key];
      if (!html) {
        html = `<span class=\"tt-title\">${label.textContent || key}</span><div>No detailed tooltip available yet. See our docs for related settings.</div><div class=\"tt-links\"><a href=\"/README.md\" target=\"_blank\" rel=\"noopener\">Main README</a> <a href=\"/docs/README_INDEX.md\" target=\"_blank\" rel=\"noopener\">Docs Index</a></div>`;
      }
      const spanText = document.createElement('span');
      spanText.className = 'label-text';
      spanText.textContent = label.textContent;
      label.textContent = '';
      label.appendChild(spanText);
      const wrap = document.createElement('span');
      wrap.className = 'tooltip-wrap';
      const icon = document.createElement('span');
      icon.className = 'help-icon';
      icon.setAttribute('tabindex', '0');
      icon.setAttribute('aria-label', `Help: ${label.textContent}`);
      icon.textContent = '?';
      icon.dataset.tooltipAttached = 'true';
      const bubble = document.createElement('div');
      bubble.className = 'tooltip-bubble';
      bubble.setAttribute('role', 'tooltip');
      bubble.innerHTML = html;
      wrap.appendChild(icon);
      wrap.appendChild(bubble);
      label.appendChild(wrap);
      attachTooltipListeners(icon, bubble, wrap);
    });
  }

  // NOTE: React components render tooltips; keep DOM attach helpers for reference only.
  // We intentionally do NOT attach anything to window.*.
  return { buildTooltipMap };
})();

export const buildTooltipMap = LegacyTooltips.buildTooltipMap;
export const tooltipMap = LegacyTooltips.buildTooltipMap();
