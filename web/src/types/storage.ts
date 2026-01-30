// Storage calculator types (aligned with Pydantic-backed config data and Zustand state)
export interface CalculatorInputs {
  repoSize: number;
  repoUnit: number;
  chunkSize: number;
  chunkUnit: number;
  embeddingDim: number;
  precision: 1 | 2 | 4;
  qdrantOverhead: number;
  hydrationPercent: number;
  redisMiB: number;
  replicationFactor: number;
}

export interface StorageResults {
  chunks: number;
  rawEmbeddings: number;
  qdrantSize: number;
  bm25Index: number;
  cardsSummary: number;
  hydration: number;
  reranker: number;
  redis: number;
  singleInstance: number;
  replicated: number;
}

export interface PrecisionResults {
  float32: number;
  float16: number;
  int8: number;
  pq8: number;
}

export interface Calculator2Inputs {
  repoSize: number;
  repoUnit: number;
  targetSize: number;
  targetUnit: number;
  chunkSize: number;
  chunkUnit: number;
  embeddingDim: number;
  bm25Percent: number;
  cardsPercent: number;
}

export interface OptimizationPlan {
  name: string;
  description: string[];
  total: number;
  replicated: number;
  fits: boolean;
}

export interface Calculator2Results {
  chunks: number;
  baseStorage: number;
  precisions: PrecisionResults;
  aggressivePlan: OptimizationPlan;
  conservativePlan: OptimizationPlan;
  statusMessage: string;
  statusType: 'success' | 'warning' | 'error';
}
