import { create } from 'zustand';

// Model types for cost calculation
type ModelType = 'inference' | 'embedding' | 'rerank';

// Model definition from models.json
interface ModelEntry {
  provider: string;
  family: string;
  model: string;
  components: string[]; // "GEN" | "EMB" | "RERANK"
  unit?: string;
  input_per_1k?: number;
  output_per_1k?: number;
  embed_per_1k?: number;
  rerank_per_1k?: number;
  per_request?: number;
  dimensions?: number;
  context?: number;
  notes?: string;
}

interface ModelsData {
  currency: string;
  last_updated: string;
  sources: string[];
  models: ModelEntry[];
}

// Cache for models.json - shared across all store instances
let modelsCache: ModelsData | null = null;
let modelsFetchPromise: Promise<ModelsData> | null = null;

async function fetchModelsJson(): Promise<ModelsData> {
  if (modelsCache) return modelsCache;
  if (modelsFetchPromise) return modelsFetchPromise;

  // Use Vite's base URL to correctly resolve the models.json path
  const baseUrl = import.meta.env.BASE_URL || '/';
  const modelsUrl = `${baseUrl}models.json`.replace(/\/+/g, '/');

  modelsFetchPromise = fetch(modelsUrl)
    .then(res => {
      if (!res.ok) throw new Error(`Failed to load models.json: ${res.status}`);
      return res.json();
    })
    .then((data: ModelsData) => {
      modelsCache = data;
      return data;
    })
    .catch(err => {
      modelsFetchPromise = null;
      throw err;
    });

  return modelsFetchPromise;
}

// Normalize provider name for grouping (local providers grouped together)
function normalizeProvider(provider: string): string {
  const p = provider.toLowerCase();
  if (p === 'ollama' || p === 'huggingface' || p === 'local') {
    return 'Local';
  }
  return provider;
}

interface CostCalculatorStore {
  // Provider/Model selections
  inferenceProvider: string;
  inferenceModel: string;
  embeddingProvider: string;
  embeddingModel: string;
  rerankProvider: string;
  rerankModel: string;

  // Token inputs
  tokensIn: number;
  tokensOut: number;
  embeds: number;
  reranks: number;
  requestsPerDay: number;

  // Results
  dailyCost: string;
  monthlyCost: string;
  calculating: boolean;
  error: string | null;

  // Model lists (populated from models.json)
  providers: string[];
  chatModels: string[];
  embedModels: string[];
  rerankModels: string[];
  modelsLoading: boolean;

  // Internal: cached models data
  _modelsData: ModelsData | null;

  // Actions
  setProvider: (type: ModelType, value: string) => void;
  setModel: (type: ModelType, value: string) => void;
  setTokensIn: (value: number) => void;
  setTokensOut: (value: number) => void;
  setEmbeds: (value: number) => void;
  setReranks: (value: number) => void;
  setRequestsPerDay: (value: number) => void;
  calculateCost: () => Promise<void>;
  loadProviders: () => Promise<void>;
  loadModelsForProvider: (type: ModelType, provider: string) => Promise<void>;
  syncFromConfig: (config: { env?: Record<string, string> }) => void;
  reset: () => void;
}

const initialState = {
  // Provider/Model selections - defaults from Pydantic config
  inferenceProvider: 'openai',
  inferenceModel: '',
  embeddingProvider: 'openai',
  embeddingModel: '',
  rerankProvider: 'cohere',
  rerankModel: '',

  // Token inputs - reasonable defaults
  tokensIn: 5000,
  tokensOut: 800,
  embeds: 4,
  reranks: 3,
  requestsPerDay: 100,

  // Results
  dailyCost: '--',
  monthlyCost: '--',
  calculating: false,
  error: null as string | null,

  // Model lists
  providers: [] as string[],
  chatModels: [] as string[],
  embedModels: [] as string[],
  rerankModels: [] as string[],
  modelsLoading: false,

  // Internal cache
  _modelsData: null as ModelsData | null,
};

export const useCostCalculatorStore = create<CostCalculatorStore>((set, get) => ({
  ...initialState,

  setProvider: (type: ModelType, value: string) => {
    switch (type) {
      case 'inference':
        set({ inferenceProvider: value });
        // Load models for new provider
        get().loadModelsForProvider('inference', value);
        break;
      case 'embedding':
        set({ embeddingProvider: value });
        get().loadModelsForProvider('embedding', value);
        break;
      case 'rerank':
        set({ rerankProvider: value });
        get().loadModelsForProvider('rerank', value);
        break;
    }
  },

  setModel: (type: ModelType, value: string) => {
    switch (type) {
      case 'inference':
        set({ inferenceModel: value });
        break;
      case 'embedding':
        set({ embeddingModel: value });
        break;
      case 'rerank':
        set({ rerankModel: value });
        break;
    }
  },

  setTokensIn: (value: number) => set({ tokensIn: value }),
  setTokensOut: (value: number) => set({ tokensOut: value }),
  setEmbeds: (value: number) => set({ embeds: value }),
  setReranks: (value: number) => set({ reranks: value }),
  setRequestsPerDay: (value: number) => set({ requestsPerDay: value }),

  calculateCost: async () => {
    const state = get();
    set({ calculating: true, error: null });

    try {
      // Load models data if not cached
      let modelsData = state._modelsData;
      if (!modelsData) {
        modelsData = await fetchModelsJson();
        set({ _modelsData: modelsData });
      }

      const models = modelsData.models;
      let totalCost = 0;

      // Find and calculate chat/inference cost
      const chatModel = models.find(
        m => m.model === state.inferenceModel &&
             normalizeProvider(m.provider) === state.inferenceProvider
      ) || models.find(m => m.model === state.inferenceModel);

      if (chatModel && chatModel.components.includes('GEN')) {
        const inputCost = (state.tokensIn / 1000) * (chatModel.input_per_1k || 0);
        const outputCost = (state.tokensOut / 1000) * (chatModel.output_per_1k || 0);
        totalCost += inputCost + outputCost;
      }

      // Find and calculate embedding cost
      const embedModel = models.find(
        m => m.model === state.embeddingModel &&
             normalizeProvider(m.provider) === state.embeddingProvider
      ) || models.find(m => m.model === state.embeddingModel);

      if (embedModel && embedModel.components.includes('EMB')) {
        // embeds is number of chunks, assume avg 1000 tokens per chunk
        const embedTokens = state.embeds * 1000;
        totalCost += (embedTokens / 1000) * (embedModel.embed_per_1k || 0);
      }

      // Find and calculate rerank cost
      const rerankModel = models.find(
        m => m.model === state.rerankModel &&
             normalizeProvider(m.provider) === state.rerankProvider
      ) || models.find(m => m.model === state.rerankModel);

      if (rerankModel && rerankModel.components.includes('RERANK')) {
        if (rerankModel.per_request) {
          // Per-request pricing (e.g., Cohere)
          totalCost += state.reranks * rerankModel.per_request;
        } else if (rerankModel.rerank_per_1k) {
          // Per-1k tokens pricing (e.g., Voyage)
          // Assume avg 500 tokens per rerank call
          totalCost += (state.reranks * 500 / 1000) * rerankModel.rerank_per_1k;
        }
      }

      // Calculate daily and monthly costs
      const daily = totalCost * state.requestsPerDay;
      const monthly = daily * 30;

      set({
        dailyCost: `$${daily.toFixed(2)}`,
        monthlyCost: `$${monthly.toFixed(2)}`,
        calculating: false,
        error: null,
      });
    } catch (error) {
      console.error('[useCostCalculatorStore] Calculate cost error:', error);
      set({
        dailyCost: 'Error',
        monthlyCost: 'Error',
        calculating: false,
        error: error instanceof Error ? error.message : 'Failed to calculate cost',
      });
    }
  },

  loadProviders: async () => {
    set({ modelsLoading: true });
    try {
      const modelsData = await fetchModelsJson();
      set({ _modelsData: modelsData });

      // Extract unique providers (grouping local/ollama/huggingface as "Local")
      const providersSet = new Set<string>();
      modelsData.models.forEach(m => {
        if (m.provider) {
          providersSet.add(normalizeProvider(m.provider));
        }
      });
      const providers = Array.from(providersSet).sort();
      set({ providers, modelsLoading: false });

      // Load models for current providers
      const state = get();
      if (state.inferenceProvider) {
        get().loadModelsForProvider('inference', state.inferenceProvider);
      }
      if (state.embeddingProvider) {
        get().loadModelsForProvider('embedding', state.embeddingProvider);
      }
      if (state.rerankProvider) {
        get().loadModelsForProvider('rerank', state.rerankProvider);
      }
    } catch (error) {
      console.error('[useCostCalculatorStore] Load providers error:', error);
      set({ modelsLoading: false });
    }
  },

  loadModelsForProvider: async (type: ModelType, provider: string) => {
    try {
      // Ensure models data is loaded
      let modelsData = get()._modelsData;
      if (!modelsData) {
        modelsData = await fetchModelsJson();
        set({ _modelsData: modelsData });
      }

      // Map ModelType to component type
      let componentType: string;
      switch (type) {
        case 'inference':
          componentType = 'GEN';
          break;
        case 'embedding':
          componentType = 'EMB';
          break;
        case 'rerank':
          componentType = 'RERANK';
          break;
      }

      const normalizedProvider = provider.toLowerCase();

      // Filter models by provider and component type
      const filtered = modelsData.models.filter(m => {
        const mProv = m.provider.toLowerCase();

        // Handle "Local" group (includes local, ollama, huggingface)
        if (normalizedProvider === 'local') {
          if (mProv !== 'local' && mProv !== 'ollama' && mProv !== 'huggingface') {
            return false;
          }
        } else {
          if (mProv !== normalizedProvider) {
            return false;
          }
        }

        // Filter by component type
        return m.components.includes(componentType);
      });

      const modelNames = filtered.map(m => m.model).filter(Boolean).sort();

      switch (type) {
        case 'inference':
          set({ chatModels: modelNames });
          // If current model not in list, select first
          if (modelNames.length > 0 && !modelNames.includes(get().inferenceModel)) {
            set({ inferenceModel: modelNames[0] });
          }
          break;
        case 'embedding':
          set({ embedModels: modelNames });
          if (modelNames.length > 0 && !modelNames.includes(get().embeddingModel)) {
            set({ embeddingModel: modelNames[0] });
          }
          break;
        case 'rerank':
          set({ rerankModels: modelNames });
          if (modelNames.length > 0 && !modelNames.includes(get().rerankModel)) {
            set({ rerankModel: modelNames[0] });
          }
          break;
      }
    } catch (error) {
      console.error(`[useCostCalculatorStore] Load ${type} models error:`, error);
    }
  },

  syncFromConfig: (config: { env?: Record<string, string> }) => {
    if (!config?.env) return;

    const updates: Partial<CostCalculatorStore> = {};

    // Sync inference model from GEN_MODEL
    if (config.env.GEN_MODEL) {
      updates.inferenceModel = config.env.GEN_MODEL;
      // Try to infer provider from model name
      const genModel = config.env.GEN_MODEL.toLowerCase();
      if (genModel.includes('gpt')) updates.inferenceProvider = 'openai';
      else if (genModel.includes('claude')) updates.inferenceProvider = 'anthropic';
      else if (genModel.includes('gemini')) updates.inferenceProvider = 'google';
    }

    // Sync embedding model from EMBEDDING_MODEL
    if (config.env.EMBEDDING_MODEL) {
      updates.embeddingModel = config.env.EMBEDDING_MODEL;
    }

    // Sync rerank model from RERANKER_CLOUD_MODEL
    if (config.env.RERANKER_CLOUD_MODEL) {
      updates.rerankModel = config.env.RERANKER_CLOUD_MODEL;
    }
    if (config.env.RERANKER_CLOUD_PROVIDER) {
      updates.rerankProvider = config.env.RERANKER_CLOUD_PROVIDER;
    }

    set(updates);
  },

  reset: () => set(initialState),
}));
