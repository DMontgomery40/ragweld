# tribrid-rag Contracts Specification

Every class, function, interface, and component prop defined here. 
Code generation MUST match these contracts exactly - no additions, no modifications.

---

## PART 1: PYDANTIC MODELS (server/models/)

### server/models/config.py

```python
class EmbeddingConfig(BaseModel):
    provider: Literal["openai", "voyage", "local"]
    model: str
    dimensions: int
    batch_size: int = 100

class VectorSearchConfig(BaseModel):
    enabled: bool = True
    top_k: int = 50
    similarity_threshold: float = 0.0

class SparseSearchConfig(BaseModel):
    enabled: bool = True
    top_k: int = 50
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

class GraphSearchConfig(BaseModel):
    enabled: bool = True
    max_hops: int = 2
    top_k: int = 20
    include_communities: bool = True

class FusionConfig(BaseModel):
    method: Literal["rrf", "weighted"]
    vector_weight: float = 0.4
    sparse_weight: float = 0.3
    graph_weight: float = 0.3
    rrf_k: int = 60

class RerankerConfig(BaseModel):
    mode: Literal["none", "local", "trained", "api"]
    local_model: str | None = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    trained_model_path: str | None = "models/cross-encoder-tribrid"
    api_provider: Literal["cohere", "voyage", "jina"] | None = None
    api_model: str | None = None
    top_n: int = 20
    batch_size: int = 16
    max_length: int = 512

class ChunkerConfig(BaseModel):
    strategy: Literal["ast", "semantic", "fixed"]
    chunk_size: int = 1500
    chunk_overlap: int = 200
    min_chunk_size: int = 100

class ObservabilityConfig(BaseModel):
    metrics_enabled: bool = True
    tracing_enabled: bool = True
    grafana_url: str | None = None

class TriBridConfig(BaseModel):
    """Root config - SINGLE SOURCE OF TRUTH"""
    embedding: EmbeddingConfig
    vector_search: VectorSearchConfig
    sparse_search: SparseSearchConfig
    graph_search: GraphSearchConfig
    fusion: FusionConfig
    reranker: RerankerConfig
    chunker: ChunkerConfig
    observability: ObservabilityConfig
```

### server/models/retrieval.py

```python
class ChunkMatch(BaseModel):
    chunk_id: str
    content: str
    file_path: str
    start_line: int
    end_line: int
    language: str | None
    score: float
    source: Literal["vector", "sparse", "graph"]
    metadata: dict[str, Any] = {}

class SearchRequest(BaseModel):
    query: str
    repo_id: str
    top_k: int = 20
    include_vector: bool = True
    include_sparse: bool = True
    include_graph: bool = True

class SearchResponse(BaseModel):
    query: str
    matches: list[ChunkMatch]
    fusion_method: str
    reranker_mode: str
    latency_ms: float
    debug: dict[str, Any] | None = None

class AnswerRequest(BaseModel):
    query: str
    repo_id: str
    top_k: int = 10
    stream: bool = False
    system_prompt: str | None = None

class AnswerResponse(BaseModel):
    query: str
    answer: str
    sources: list[ChunkMatch]
    model: str
    tokens_used: int
    latency_ms: float
```

### server/models/index.py

```python
class Chunk(BaseModel):
    chunk_id: str
    content: str
    file_path: str
    start_line: int
    end_line: int
    language: str | None
    token_count: int
    embedding: list[float] | None = None
    summary: str | None = None

class IndexRequest(BaseModel):
    repo_id: str
    repo_path: str
    force_reindex: bool = False

class IndexStatus(BaseModel):
    repo_id: str
    status: Literal["idle", "indexing", "complete", "error"]
    progress: float  # 0.0 to 1.0
    current_file: str | None
    error: str | None
    started_at: datetime | None
    completed_at: datetime | None

class IndexStats(BaseModel):
    repo_id: str
    total_files: int
    total_chunks: int
    total_tokens: int
    embedding_model: str
    embedding_dimensions: int
    last_indexed: datetime | None
    file_breakdown: dict[str, int]  # extension -> count
```

### server/models/graph.py

```python
class Entity(BaseModel):
    entity_id: str
    name: str
    entity_type: Literal["function", "class", "module", "variable", "concept"]
    file_path: str | None
    description: str | None
    properties: dict[str, Any] = {}

class Relationship(BaseModel):
    source_id: str
    target_id: str
    relation_type: Literal["calls", "imports", "inherits", "contains", "references", "related_to"]
    weight: float = 1.0
    properties: dict[str, Any] = {}

class Community(BaseModel):
    community_id: str
    name: str
    summary: str
    member_ids: list[str]
    level: int  # hierarchy level

class GraphStats(BaseModel):
    repo_id: str
    total_entities: int
    total_relationships: int
    total_communities: int
    entity_breakdown: dict[str, int]  # type -> count
    relationship_breakdown: dict[str, int]  # type -> count
```

### server/models/eval.py

```python
class DatasetEntry(BaseModel):
    entry_id: str
    question: str
    expected_chunks: list[str]  # chunk_ids that should be retrieved
    expected_answer: str | None
    tags: list[str] = []
    created_at: datetime

class EvalRequest(BaseModel):
    repo_id: str
    dataset_id: str | None = None  # None = use default
    sample_size: int | None = None  # None = all entries

class EvalMetrics(BaseModel):
    mrr: float  # Mean Reciprocal Rank
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    precision_at_5: float
    ndcg_at_10: float
    latency_p50_ms: float
    latency_p95_ms: float

class EvalResult(BaseModel):
    entry_id: str
    question: str
    retrieved_chunks: list[str]
    expected_chunks: list[str]
    reciprocal_rank: float
    recall: float
    latency_ms: float

class EvalRun(BaseModel):
    run_id: str
    repo_id: str
    dataset_id: str
    config_snapshot: TriBridConfig
    metrics: EvalMetrics
    results: list[EvalResult]
    started_at: datetime
    completed_at: datetime
```

### server/models/chat.py

```python
class Message(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class ChatRequest(BaseModel):
    message: str
    repo_id: str
    conversation_id: str | None = None
    stream: bool = False

class ChatResponse(BaseModel):
    conversation_id: str
    message: Message
    sources: list[ChunkMatch]
    tokens_used: int
```

### server/models/repo.py

```python
class Repository(BaseModel):
    repo_id: str
    name: str
    path: str
    description: str | None
    created_at: datetime
    last_indexed: datetime | None
    
class RepoStats(BaseModel):
    repo_id: str
    file_count: int
    total_size_bytes: int
    language_breakdown: dict[str, int]
    index_stats: IndexStats | None
    graph_stats: GraphStats | None
```

### server/models/cost.py

```python
class CostEstimate(BaseModel):
    operation: Literal["index", "search", "answer"]
    embedding_tokens: int
    embedding_cost: float
    llm_tokens: int
    llm_cost: float
    total_cost: float

class CostRecord(BaseModel):
    record_id: str
    operation: str
    repo_id: str
    tokens: int
    cost: float
    timestamp: datetime

class CostSummary(BaseModel):
    period: Literal["day", "week", "month"]
    total_cost: float
    by_operation: dict[str, float]
    by_repo: dict[str, float]
```

---

## PART 2: API ENDPOINTS (server/api/)

### server/api/search.py

```python
@router.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest) -> SearchResponse: ...

@router.post("/answer", response_model=AnswerResponse)
async def answer(request: AnswerRequest) -> AnswerResponse: ...

@router.post("/answer/stream")
async def answer_stream(request: AnswerRequest) -> StreamingResponse: ...
```

### server/api/index.py

```python
@router.post("/index", response_model=IndexStatus)
async def start_index(request: IndexRequest) -> IndexStatus: ...

@router.get("/index/{repo_id}/status", response_model=IndexStatus)
async def get_index_status(repo_id: str) -> IndexStatus: ...

@router.get("/index/{repo_id}/stats", response_model=IndexStats)
async def get_index_stats(repo_id: str) -> IndexStats: ...

@router.delete("/index/{repo_id}")
async def delete_index(repo_id: str) -> dict: ...
```

### server/api/graph.py

```python
@router.get("/graph/{repo_id}/entities", response_model=list[Entity])
async def list_entities(repo_id: str, entity_type: str | None = None, limit: int = 100) -> list[Entity]: ...

@router.get("/graph/{repo_id}/entity/{entity_id}", response_model=Entity)
async def get_entity(repo_id: str, entity_id: str) -> Entity: ...

@router.get("/graph/{repo_id}/entity/{entity_id}/relationships", response_model=list[Relationship])
async def get_entity_relationships(repo_id: str, entity_id: str) -> list[Relationship]: ...

@router.get("/graph/{repo_id}/communities", response_model=list[Community])
async def list_communities(repo_id: str, level: int | None = None) -> list[Community]: ...

@router.get("/graph/{repo_id}/stats", response_model=GraphStats)
async def get_graph_stats(repo_id: str) -> GraphStats: ...

@router.post("/graph/{repo_id}/query")
async def graph_query(repo_id: str, cypher: str) -> list[dict]: ...
```

### server/api/config.py

```python
@router.get("/config", response_model=TriBridConfig)
async def get_config() -> TriBridConfig: ...

@router.put("/config", response_model=TriBridConfig)
async def update_config(config: TriBridConfig) -> TriBridConfig: ...

@router.patch("/config/{section}", response_model=TriBridConfig)
async def update_config_section(section: str, updates: dict) -> TriBridConfig: ...

@router.post("/config/reset", response_model=TriBridConfig)
async def reset_config() -> TriBridConfig: ...
```

### server/api/eval.py

```python
@router.post("/eval/run", response_model=EvalRun)
async def run_evaluation(request: EvalRequest) -> EvalRun: ...

@router.get("/eval/runs", response_model=list[EvalRun])
async def list_eval_runs(repo_id: str | None = None, limit: int = 20) -> list[EvalRun]: ...

@router.get("/eval/run/{run_id}", response_model=EvalRun)
async def get_eval_run(run_id: str) -> EvalRun: ...

@router.delete("/eval/run/{run_id}")
async def delete_eval_run(run_id: str) -> dict: ...
```

### server/api/dataset.py

```python
@router.get("/dataset", response_model=list[DatasetEntry])
async def list_dataset(repo_id: str) -> list[DatasetEntry]: ...

@router.post("/dataset", response_model=DatasetEntry)
async def add_dataset_entry(entry: DatasetEntry) -> DatasetEntry: ...

@router.put("/dataset/{entry_id}", response_model=DatasetEntry)
async def update_dataset_entry(entry_id: str, entry: DatasetEntry) -> DatasetEntry: ...

@router.delete("/dataset/{entry_id}")
async def delete_dataset_entry(entry_id: str) -> dict: ...

@router.post("/dataset/import")
async def import_dataset(file: UploadFile) -> list[DatasetEntry]: ...

@router.get("/dataset/export")
async def export_dataset(repo_id: str) -> FileResponse: ...
```

### server/api/repos.py

```python
@router.get("/repos", response_model=list[Repository])
async def list_repos() -> list[Repository]: ...

@router.post("/repos", response_model=Repository)
async def add_repo(repo: Repository) -> Repository: ...

@router.get("/repos/{repo_id}", response_model=Repository)
async def get_repo(repo_id: str) -> Repository: ...

@router.get("/repos/{repo_id}/stats", response_model=RepoStats)
async def get_repo_stats(repo_id: str) -> RepoStats: ...

@router.delete("/repos/{repo_id}")
async def delete_repo(repo_id: str) -> dict: ...
```

### server/api/reranker.py

```python
@router.get("/reranker/status")
async def get_reranker_status() -> dict: ...

@router.get("/reranker/triplets/{repo_id}", response_model=list[dict])
async def get_triplets(repo_id: str, limit: int = 100) -> list[dict]: ...

@router.post("/reranker/triplets/{repo_id}")
async def add_triplet(repo_id: str, query: str, positive: str, negative: str) -> dict: ...

@router.post("/reranker/train")
async def train_reranker(repo_id: str | None = None) -> dict: ...

@router.post("/reranker/promote")
async def promote_model(model_path: str) -> dict: ...
```

### server/api/chat.py

```python
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse: ...

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse: ...

@router.get("/chat/history/{conversation_id}", response_model=list[Message])
async def get_chat_history(conversation_id: str) -> list[Message]: ...

@router.delete("/chat/history/{conversation_id}")
async def clear_chat_history(conversation_id: str) -> dict: ...
```

### server/api/cost.py

```python
@router.post("/cost/estimate", response_model=CostEstimate)
async def estimate_cost(operation: str, token_count: int) -> CostEstimate: ...

@router.get("/cost/history", response_model=list[CostRecord])
async def get_cost_history(period: str = "week") -> list[CostRecord]: ...

@router.get("/cost/summary", response_model=CostSummary)
async def get_cost_summary(period: str = "month") -> CostSummary: ...
```

### server/api/docker.py

```python
@router.get("/docker/status")
async def get_docker_status() -> dict[str, dict]: ...

@router.post("/docker/{container}/restart")
async def restart_container(container: str) -> dict: ...

@router.get("/docker/{container}/logs")
async def get_container_logs(container: str, lines: int = 100) -> list[str]: ...
```

### server/api/health.py

```python
@router.get("/health")
async def health_check() -> dict: ...

@router.get("/ready")
async def readiness_check() -> dict: ...

@router.get("/metrics")
async def prometheus_metrics() -> Response: ...
```

---

## PART 3: DATABASE CLIENTS (server/db/)

### server/db/postgres.py

```python
class PostgresClient:
    def __init__(self, connection_string: str): ...
    
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    
    # Vector operations
    async def upsert_embeddings(self, repo_id: str, chunks: list[Chunk]) -> int: ...
    async def vector_search(self, repo_id: str, embedding: list[float], top_k: int) -> list[ChunkMatch]: ...
    async def delete_embeddings(self, repo_id: str) -> int: ...
    
    # FTS operations
    async def upsert_fts(self, repo_id: str, chunks: list[Chunk]) -> int: ...
    async def sparse_search(self, repo_id: str, query: str, top_k: int) -> list[ChunkMatch]: ...
    async def delete_fts(self, repo_id: str) -> int: ...
    
    # Metadata
    async def get_chunk(self, chunk_id: str) -> Chunk | None: ...
    async def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]: ...
    async def get_index_stats(self, repo_id: str) -> IndexStats: ...
```

### server/db/neo4j.py

```python
class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str): ...
    
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    
    # Entity operations
    async def upsert_entity(self, repo_id: str, entity: Entity) -> None: ...
    async def upsert_entities(self, repo_id: str, entities: list[Entity]) -> int: ...
    async def get_entity(self, entity_id: str) -> Entity | None: ...
    async def list_entities(self, repo_id: str, entity_type: str | None, limit: int) -> list[Entity]: ...
    async def delete_entities(self, repo_id: str) -> int: ...
    
    # Relationship operations
    async def upsert_relationship(self, repo_id: str, rel: Relationship) -> None: ...
    async def upsert_relationships(self, repo_id: str, rels: list[Relationship]) -> int: ...
    async def get_relationships(self, entity_id: str) -> list[Relationship]: ...
    
    # Community operations
    async def detect_communities(self, repo_id: str) -> list[Community]: ...
    async def get_communities(self, repo_id: str, level: int | None) -> list[Community]: ...
    
    # Search
    async def graph_search(self, repo_id: str, query: str, max_hops: int, top_k: int) -> list[ChunkMatch]: ...
    async def execute_cypher(self, query: str, params: dict | None) -> list[dict]: ...
    
    # Stats
    async def get_graph_stats(self, repo_id: str) -> GraphStats: ...
```

---

## PART 4: RETRIEVAL PIPELINE (server/retrieval/)

### server/retrieval/vector.py

```python
class VectorRetriever:
    def __init__(self, postgres: PostgresClient, embedder: Embedder): ...
    
    async def search(self, repo_id: str, query: str, config: VectorSearchConfig) -> list[ChunkMatch]: ...
```

### server/retrieval/sparse.py

```python
class SparseRetriever:
    def __init__(self, postgres: PostgresClient): ...
    
    async def search(self, repo_id: str, query: str, config: SparseSearchConfig) -> list[ChunkMatch]: ...
```

### server/retrieval/graph.py

```python
class GraphRetriever:
    def __init__(self, neo4j: Neo4jClient, embedder: Embedder): ...
    
    async def search(self, repo_id: str, query: str, config: GraphSearchConfig) -> list[ChunkMatch]: ...
    async def expand_context(self, chunk_ids: list[str], max_hops: int) -> list[ChunkMatch]: ...
```

### server/retrieval/fusion.py

```python
class TriBridFusion:
    def __init__(self, vector: VectorRetriever, sparse: SparseRetriever, graph: GraphRetriever): ...
    
    async def search(self, repo_id: str, query: str, config: FusionConfig) -> list[ChunkMatch]: ...
    
    def rrf_fusion(self, results: list[list[ChunkMatch]], k: int) -> list[ChunkMatch]: ...
    def weighted_fusion(self, results: list[list[ChunkMatch]], weights: list[float]) -> list[ChunkMatch]: ...
```

### server/retrieval/rerank.py

```python
class Reranker:
    def __init__(self, config: RerankerConfig): ...
    
    async def rerank(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]: ...
    
    async def _rerank_local(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]: ...
    async def _rerank_trained(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]: ...
    async def _rerank_api(self, query: str, chunks: list[ChunkMatch]) -> list[ChunkMatch]: ...
    
    def load_model(self) -> None: ...
    def reload_model(self) -> None: ...
```

### server/retrieval/learning.py

```python
class LearningReranker:
    def __init__(self, base_model: str, output_dir: str): ...
    
    async def mine_triplets(self, repo_id: str, eval_results: list[EvalResult]) -> list[dict]: ...
    async def train(self, triplets: list[dict], epochs: int = 3) -> dict: ...
    async def evaluate(self, test_triplets: list[dict]) -> dict: ...
    def save_model(self, path: str) -> None: ...
    def load_model(self, path: str) -> None: ...
```

---

## PART 5: INDEXING PIPELINE (server/indexing/)

### server/indexing/chunker.py

```python
class Chunker:
    def __init__(self, config: ChunkerConfig): ...
    
    def chunk_file(self, file_path: str, content: str) -> list[Chunk]: ...
    def chunk_ast(self, file_path: str, content: str, language: str) -> list[Chunk]: ...
    def chunk_semantic(self, file_path: str, content: str) -> list[Chunk]: ...
    def chunk_fixed(self, file_path: str, content: str) -> list[Chunk]: ...
```

### server/indexing/embedder.py

```python
class Embedder:
    def __init__(self, config: EmbeddingConfig): ...
    
    async def embed(self, text: str) -> list[float]: ...
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]: ...
```

### server/indexing/graph_builder.py

```python
class GraphBuilder:
    def __init__(self, neo4j: Neo4jClient): ...
    
    async def extract_entities(self, chunks: list[Chunk]) -> list[Entity]: ...
    async def extract_relationships(self, chunks: list[Chunk], entities: list[Entity]) -> list[Relationship]: ...
    async def build_graph(self, repo_id: str, chunks: list[Chunk]) -> GraphStats: ...
    
    def _extract_code_entities(self, chunk: Chunk) -> list[Entity]: ...
    def _extract_semantic_entities(self, chunk: Chunk) -> list[Entity]: ...
    def _infer_relationships(self, entities: list[Entity]) -> list[Relationship]: ...
```

### server/indexing/summarizer.py

```python
class ChunkSummarizer:
    def __init__(self, llm_model: str): ...
    
    async def summarize(self, chunk: Chunk) -> str: ...
    async def summarize_batch(self, chunks: list[Chunk]) -> list[str]: ...
```

### server/indexing/loader.py

```python
class FileLoader:
    def __init__(self, ignore_patterns: list[str] | None = None): ...
    
    def load_repo(self, repo_path: str) -> Iterator[tuple[str, str]]: ...  # (path, content)
    def should_include(self, file_path: str) -> bool: ...
    def detect_language(self, file_path: str) -> str | None: ...
```

---

## PART 6: ZUSTAND STORES (web/src/stores/)

### useConfigStore.ts

```typescript
interface ConfigState {
  config: TriBridConfig | null;
  loading: boolean;
  error: string | null;
  dirty: boolean;  // unsaved changes
}

interface ConfigActions {
  fetchConfig: () => Promise<void>;
  updateConfig: (config: Partial<TriBridConfig>) => Promise<void>;
  updateSection: <K extends keyof TriBridConfig>(section: K, updates: Partial<TriBridConfig[K]>) => Promise<void>;
  resetConfig: () => Promise<void>;
  setDirty: (dirty: boolean) => void;
}

type ConfigStore = ConfigState & ConfigActions;
```

### useHealthStore.ts

```typescript
interface HealthState {
  healthy: boolean;
  services: Record<string, ServiceStatus>;
  docker: Record<string, ContainerStatus>;
  lastCheck: Date | null;
  checking: boolean;
}

interface ServiceStatus {
  name: string;
  healthy: boolean;
  latency_ms: number;
  error: string | null;
}

interface ContainerStatus {
  name: string;
  status: 'running' | 'stopped' | 'error';
  uptime: string | null;
  memory_mb: number | null;
}

interface HealthActions {
  checkHealth: () => Promise<void>;
  checkDocker: () => Promise<void>;
  restartContainer: (name: string) => Promise<void>;
}

type HealthStore = HealthState & HealthActions;
```

### useRepoStore.ts

```typescript
interface RepoState {
  repos: Repository[];
  activeRepoId: string | null;
  loading: boolean;
  error: string | null;
}

interface RepoActions {
  fetchRepos: () => Promise<void>;
  addRepo: (repo: Omit<Repository, 'repo_id' | 'created_at'>) => Promise<void>;
  deleteRepo: (repoId: string) => Promise<void>;
  setActiveRepo: (repoId: string) => void;
  getActiveRepo: () => Repository | null;
}

type RepoStore = RepoState & RepoActions;
```

### useUIStore.ts

```typescript
interface UIState {
  activeTab: string;
  activeSubtabs: Record<string, string>;  // tab -> subtab
  sidebarOpen: boolean;
  theme: 'light' | 'dark' | 'system';
  
  // Eval preservation
  evalInProgress: boolean;
  evalRunId: string | null;
}

interface UIActions {
  setActiveTab: (tab: string) => void;
  setActiveSubtab: (tab: string, subtab: string) => void;
  toggleSidebar: () => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
  setEvalInProgress: (inProgress: boolean, runId?: string) => void;
}

type UIStore = UIState & UIActions;
```

### useTooltipStore.ts

```typescript
interface TooltipEntry {
  id: string;
  term: string;
  definition: string;
  category: string;
  links: Array<{ label: string; url: string }>;
}

interface TooltipState {
  tooltips: Record<string, TooltipEntry>;
  glossary: TooltipEntry[];
  searchQuery: string;
  filteredGlossary: TooltipEntry[];
}

interface TooltipActions {
  registerTooltip: (entry: TooltipEntry) => void;
  setSearchQuery: (query: string) => void;
  getTooltip: (id: string) => TooltipEntry | null;
}

type TooltipStore = TooltipState & TooltipActions;
```

### useGraphStore.ts

```typescript
interface GraphState {
  entities: Entity[];
  relationships: Relationship[];
  communities: Community[];
  selectedEntityId: string | null;
  stats: GraphStats | null;
  loading: boolean;
  error: string | null;
}

interface GraphActions {
  fetchEntities: (repoId: string, type?: string) => Promise<void>;
  fetchRelationships: (entityId: string) => Promise<void>;
  fetchCommunities: (repoId: string, level?: number) => Promise<void>;
  fetchStats: (repoId: string) => Promise<void>;
  selectEntity: (entityId: string | null) => void;
  executeQuery: (cypher: string) => Promise<any[]>;
}

type GraphStore = GraphState & GraphActions;
```

---

## PART 7: REACT HOOKS (web/src/hooks/)

### useAPI.ts

```typescript
function useAPI(): {
  get: <T>(url: string) => Promise<T>;
  post: <T>(url: string, data?: any) => Promise<T>;
  put: <T>(url: string, data: any) => Promise<T>;
  patch: <T>(url: string, data: any) => Promise<T>;
  delete: (url: string) => Promise<void>;
  stream: (url: string, data: any, onChunk: (chunk: string) => void) => Promise<void>;
};
```

### useConfig.ts

```typescript
function useConfig(): {
  config: TriBridConfig | null;
  loading: boolean;
  error: string | null;
  dirty: boolean;
  updateConfig: (updates: Partial<TriBridConfig>) => Promise<void>;
  updateEmbedding: (updates: Partial<EmbeddingConfig>) => Promise<void>;
  updateFusion: (updates: Partial<FusionConfig>) => Promise<void>;
  updateReranker: (updates: Partial<RerankerConfig>) => Promise<void>;
  saveConfig: () => Promise<void>;
  resetConfig: () => Promise<void>;
};
```

### useIndexing.ts

```typescript
function useIndexing(): {
  status: IndexStatus | null;
  stats: IndexStats | null;
  startIndex: (repoId: string, force?: boolean) => Promise<void>;
  cancelIndex: () => Promise<void>;
  refreshStatus: () => Promise<void>;
  refreshStats: (repoId: string) => Promise<void>;
};
```

### useEvalHistory.ts

```typescript
function useEvalHistory(): {
  runs: EvalRun[];
  selectedRun: EvalRun | null;
  loading: boolean;
  fetchRuns: (repoId?: string) => Promise<void>;
  selectRun: (runId: string) => Promise<void>;
  deleteRun: (runId: string) => Promise<void>;
  compareRuns: (runIds: string[]) => EvalComparison;
};
```

### useFusion.ts

```typescript
function useFusion(): {
  weights: { vector: number; sparse: number; graph: number };
  method: 'rrf' | 'weighted';
  setWeights: (weights: { vector: number; sparse: number; graph: number }) => void;
  setMethod: (method: 'rrf' | 'weighted') => void;
  normalizeWeights: () => void;  // ensure sum = 1.0
};
```

### useGraph.ts

```typescript
function useGraph(): {
  entities: Entity[];
  relationships: Relationship[];
  communities: Community[];
  selectedEntity: Entity | null;
  stats: GraphStats | null;
  loading: boolean;
  fetchEntities: (type?: string) => Promise<void>;
  selectEntity: (entityId: string) => Promise<void>;
  fetchCommunities: (level?: number) => Promise<void>;
  executeQuery: (cypher: string) => Promise<any[]>;
};
```

### useReranker.ts

```typescript
function useReranker(): {
  status: RerankerStatus;
  tripletCount: number;
  trainModel: () => Promise<void>;
  promoteModel: (path: string) => Promise<void>;
  refreshStatus: () => Promise<void>;
};
```

### useTooltips.ts

```typescript
function useTooltips(): {
  getTooltip: (id: string) => TooltipEntry | null;
  registerTooltip: (entry: TooltipEntry) => void;
  searchGlossary: (query: string) => TooltipEntry[];
};
```

### useDashboard.ts

```typescript
function useDashboard(): {
  systemStatus: SystemStatus;
  indexingStatus: IndexStatus | null;
  costSummary: CostSummary | null;
  recentActivity: ActivityItem[];
  refresh: () => Promise<void>;
};
```

### useGlobalSearch.ts

```typescript
function useGlobalSearch(): {
  query: string;
  results: SearchResult | null;
  loading: boolean;
  setQuery: (query: string) => void;
  search: () => Promise<void>;
  clear: () => void;
};
```

### useTheme.ts

```typescript
function useTheme(): {
  theme: 'light' | 'dark' | 'system';
  resolvedTheme: 'light' | 'dark';
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
};
```

### useAppInit.ts

```typescript
function useAppInit(): {
  initialized: boolean;
  error: string | null;
};
```

### useEmbeddingStatus.ts

```typescript
function useEmbeddingStatus(): {
  mismatch: boolean;
  currentModel: string | null;
  indexedModel: string | null;
  dismiss: () => void;
};
```

---

## PART 8: REACT COMPONENT PROPS

### Tab Components

```typescript
// All tab components take no props - they use stores/hooks
interface TabProps {}

// StartTab, RAGTab, ChatTab, EvaluationTab, EvalAnalysisTab, 
// GrafanaTab, GraphTab, InfrastructureTab, AdminTab
```

### UI Primitives

```typescript
interface ButtonProps {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}

interface TooltipIconProps {
  tooltipId: string;
  size?: 'sm' | 'md';
}

interface ProgressBarProps {
  progress: number;  // 0-100
  label?: string;
  variant?: 'default' | 'success' | 'warning' | 'error';
}

interface StatusIndicatorProps {
  status: 'healthy' | 'warning' | 'error' | 'unknown';
  label?: string;
}

interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
}

interface CollapsibleSectionProps {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

interface ErrorBoundaryProps {
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

interface RepoSelectorProps {
  value: string | null;
  onChange: (repoId: string) => void;
}
```

### Feature Components

```typescript
interface ChatInterfaceProps {
  repoId: string;
  conversationId?: string;
}

interface EvaluationRunnerProps {
  repoId: string;
  onComplete?: (run: EvalRun) => void;
}

interface EvalDrillDownProps {
  run: EvalRun;
}

interface GraphExplorerProps {
  repoId: string;
  initialEntityId?: string;
}

interface FusionWeightsPanelProps {
  onChange?: (weights: FusionConfig) => void;
}

interface GrafanaDashboardProps {
  dashboardId?: string;
}

interface IndexStatsPanel {
  repoId: string;
}

interface DatasetManagerProps {
  repoId: string;
}
```

---

## PART 9: CSS CLASS CONVENTIONS

All components use Tailwind + these custom classes from the CSS files:

```css
/* From tokens.css */
--color-primary: ...
--color-secondary: ...
--color-success: ...
--color-warning: ...
--color-error: ...
--radius-sm: ...
--radius-md: ...
--radius-lg: ...

/* Custom component classes */
.tribrid-card { }
.tribrid-panel { }
.tribrid-button { }
.tribrid-input { }
.tribrid-select { }
.tribrid-slider { }
.tribrid-tooltip { }
.tribrid-tab { }
.tribrid-tab-active { }
```

---

## VALIDATION RULES

1. **Every Pydantic model field** must have a corresponding TypeScript interface field
2. **Every API endpoint** must return a Pydantic model (or list of models)
3. **Every Zustand store field** must trace to a Pydantic model or UI-only type
4. **Every hook return type** must trace to a store field or API response
5. **Every component prop** must trace to a hook return or store selector
6. **No adapter/transformer/mapper code** - if shapes don't match, fix the Pydantic model

---

## FILE CREATION ORDER

1. `server/models/*.py` - All Pydantic models first
2. `web/src/types/generated.ts` - Run pydantic2ts
3. `server/db/*.py` - Database clients
4. `server/retrieval/*.py` - Retrieval pipeline
5. `server/indexing/*.py` - Indexing pipeline  
6. `server/api/*.py` - API routers
7. `server/main.py` - FastAPI app
8. `web/src/stores/*.ts` - Zustand stores
9. `web/src/hooks/*.ts` - React hooks
10. `web/src/api/*.ts` - API client
11. `web/src/components/ui/*.tsx` - Primitives
12. `web/src/components/**/*.tsx` - Feature components
13. `web/src/components/tabs/*.tsx` - Tab components
14. `web/src/App.tsx` - Root component
