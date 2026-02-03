/**
 * CostService
 * Replacement for legacy `web/src/modules/cost_logic.js` (no window globals).
 *
 * Notes:
 * - Pricing data comes from `models.json` (served by the web app) to avoid hand-written API models.
 * - Also supports delegating to backend cost endpoints when available.
 */
import { apiClient, api } from '@/api/client';
import type { AxiosResponse } from 'axios';
 
export type CostModelType = 'chat' | 'embed' | 'rerank';
 
export type ModelPriceSpec = {
  provider?: string;
  model?: string;
  unit?: string;
 
  // chat
  input_per_1k?: number | null;
  output_per_1k?: number | null;
 
  // embedding
  embed_per_1k?: number | null;
 
  // rerank
  rerank_per_1k?: number | null;
  per_request?: number | null;
  price_per_request?: number | null; // legacy alias (some catalogs)
};
 
export type ModelsCatalog = {
  models: ModelPriceSpec[];
  version?: string | null;
  currency?: string;
  last_updated?: string;
};
 
export type CostBreakdownItem = {
  costUSD: number;
  detail: Record<string, unknown>;
};
 
export type CostEstimateLocal = {
  totalUSD: number;
  breakdown: Partial<Record<CostModelType, CostBreakdownItem>>;
  modelsVersion: string | null;
};
 
export type CostEstimateRequest = {
  chat?: { provider: string; model: string; input_tokens?: number; output_tokens?: number };
  embed?: { provider: string; model: string; embed_tokens?: number };
  rerank?: { provider: string; model: string; requests?: number };
};
 
export type CostEstimatePipelineRequest = {
  gen_provider: string;
  gen_model: string;
  tokens_in: number;
  tokens_out: number;
  embed_provider: string;
  embed_model: string;
  embeds: number;
  rerank_provider: string;
  rerank_model: string;
  reranks: number;
  requests_per_day: number;
  // local-only knobs (optional)
  kwh_rate?: number;
  watts?: number;
  hours_per_day?: number;
};
 
// API responses are not currently modeled in generated.ts; keep minimal typing.
export type CostEstimatePipelineResponse = {
  daily?: number;
  monthly?: number;
  breakdown?: Record<string, unknown>;
  [k: string]: unknown;
};
 
const PRICE_TTL_MS = 60_000;
let catalogCache: { data: ModelsCatalog | null; loadedAtMs: number } = { data: null, loadedAtMs: 0 };
let catalogInFlight: Promise<ModelsCatalog> | null = null;
 
function normKey(s: unknown) {
  return String(s ?? '').trim().toLowerCase();
}
 
function getModelType(model: ModelPriceSpec): CostModelType | null {
  const hasEmbed = model.embed_per_1k != null && typeof model.embed_per_1k === 'number';
  const hasRerank =
    (model.rerank_per_1k != null && typeof model.rerank_per_1k === 'number') ||
    (model.per_request != null && typeof model.per_request === 'number') ||
    (model.price_per_request != null && typeof model.price_per_request === 'number');
  const hasChat =
    (model.input_per_1k != null && typeof model.input_per_1k === 'number') ||
    (model.output_per_1k != null && typeof model.output_per_1k === 'number');
 
  if (hasEmbed) return 'embed';
  if (hasRerank) return 'rerank';
  if (hasChat) return 'chat';
  return null;
}
 
function getModelSpec(models: ModelsCatalog, providerName: string, modelName: string): (ModelPriceSpec & { type: CostModelType | null }) | null {
  const list = Array.isArray(models?.models) ? models.models : [];
  const prov = normKey(providerName);
  const mdl = normKey(modelName);
 
  for (const m of list) {
    if (normKey(m.provider) === prov && normKey(m.model) === mdl) return { ...m, type: getModelType(m) };
  }
 
  if (mdl) {
    for (const m of list) {
      if (normKey(m.model) === mdl) return { ...m, type: getModelType(m) };
    }
  }
 
  for (const m of list) {
    if (normKey(m.provider) === prov) return { ...m, type: getModelType(m) };
  }
 
  return null;
}
 
function computeUnitCost(models: ModelsCatalog, opt: { type: CostModelType } & Record<string, unknown>): CostBreakdownItem {
  const provider = normKey(opt.provider);
  const model = String(opt.model ?? '');
  const spec = getModelSpec(models, provider, model);
  if (!spec) return { costUSD: 0, detail: { error: `Unknown model: ${provider}/${model}` } };
 
  const type = spec.type;
  if (type === 'chat') {
    const inTok = Number(opt.input_tokens ?? 0);
    const outTok = Number(opt.output_tokens ?? 0);
    const inRate = Number(spec.input_per_1k ?? 0);
    const outRate = Number(spec.output_per_1k ?? 0);
    const inCost = (inTok / 1000) * inRate;
    const outCost = (outTok / 1000) * outRate;
    return {
      costUSD: inCost + outCost,
      detail: { type, provider, model, inTok, outTok, inRate, outRate, inCost, outCost },
    };
  }
 
  if (type === 'embed') {
    const eTok = Number(opt.embed_tokens ?? 0);
    const eRate = Number(spec.embed_per_1k ?? 0);
    const eCost = (eTok / 1000) * eRate;
    return { costUSD: eCost, detail: { type, provider, model, embed_tokens: eTok, embed_per_1k: eRate, embed_cost: eCost } };
  }
 
  if (type === 'rerank') {
    const calls = Math.max(0, Number(opt.requests ?? 0));
    const perReq = Number(spec.per_request ?? spec.price_per_request ?? 0);
    const rCost = calls * perReq;
    return { costUSD: rCost, detail: { type, provider, model, requests: calls, per_request: perReq, rerank_cost: rCost } };
  }
 
  return { costUSD: 0, detail: { error: `Unsupported type for ${provider}/${model}` } };
}
 
async function loadModelsCatalog(): Promise<ModelsCatalog> {
  const now = Date.now();
  if (catalogCache.data && now - catalogCache.loadedAtMs < PRICE_TTL_MS) return catalogCache.data;
  if (catalogInFlight) return catalogInFlight;
 
  const baseUrl = import.meta.env.BASE_URL || '/';
  const modelsUrl = `${baseUrl}models.json`.replace(/\/+/g, '/');
 
  catalogInFlight = fetch(modelsUrl, { cache: 'no-store' })
    .then(async (res) => {
      if (!res.ok) throw new Error(`Failed to load models.json: ${res.status}`);
      return (await res.json()) as ModelsCatalog;
    })
    .then((data) => {
      catalogCache = { data, loadedAtMs: now };
      return data;
    })
    .finally(() => {
      catalogInFlight = null;
    });
 
  return catalogInFlight;
}
 
export class CostService {
  async getCatalog(): Promise<ModelsCatalog> {
    return await loadModelsCatalog();
  }
 
  async estimateLocal(req: CostEstimateRequest): Promise<CostEstimateLocal> {
    const models = await loadModelsCatalog();
    let total = 0;
    const breakdown: CostEstimateLocal['breakdown'] = {};
 
    if (req.chat) {
      const r = computeUnitCost(models, { type: 'chat', ...req.chat });
      breakdown.chat = r;
      total += r.costUSD;
    }
    if (req.embed) {
      const r = computeUnitCost(models, { type: 'embed', ...req.embed });
      breakdown.embed = r;
      total += r.costUSD;
    }
    if (req.rerank) {
      const r = computeUnitCost(models, { type: 'rerank', ...req.rerank });
      breakdown.rerank = r;
      total += r.costUSD;
    }
 
    return {
      totalUSD: Number(total.toFixed(6)),
      breakdown,
      modelsVersion: models?.version ? String(models.version) : null,
    };
  }
 
  async listProviders(): Promise<string[]> {
    const modelsData = await loadModelsCatalog();
    const models = Array.isArray(modelsData?.models) ? modelsData.models : [];
    const providers = new Set<string>();
    for (const m of models) {
      const raw = String(m.provider ?? '').trim();
      if (!raw) continue;
      const p = normKey(raw);
      if (p === 'ollama' || p === 'huggingface' || p === 'local') providers.add('Local');
      else providers.add(raw);
    }
    return Array.from(providers).sort((a, b) => a.localeCompare(b));
  }
 
  async listModels(providerName: string, modelType: CostModelType | null = null): Promise<string[]> {
    const modelsData = await loadModelsCatalog();
    const models = Array.isArray(modelsData?.models) ? modelsData.models : [];
    const prov = normKey(providerName);
 
    const filtered = models.filter((m) => {
      const mProv = normKey(m.provider);
      if (prov === 'local') {
        if (mProv !== 'local' && mProv !== 'ollama' && mProv !== 'huggingface') return false;
      } else {
        if (mProv !== prov) return false;
      }
      if (modelType) return getModelType(m) === modelType;
      return true;
    });
 
    return filtered
      .map((m) => String(m.model ?? '').trim())
      .filter(Boolean)
      .sort((a, b) => a.localeCompare(b));
  }
 
  async estimateViaApi(payload: CostEstimatePipelineRequest): Promise<CostEstimatePipelineResponse> {
    // Prefer pipeline endpoint; fall back to base estimate endpoint.
    try {
      const r: AxiosResponse<CostEstimatePipelineResponse> = await apiClient.post(api('/cost/estimate_pipeline'), payload);
      return r.data;
    } catch {
      const r: AxiosResponse<CostEstimatePipelineResponse> = await apiClient.post(api('/cost/estimate'), payload);
      return r.data;
    }
  }
}

