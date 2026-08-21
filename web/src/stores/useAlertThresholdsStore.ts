import { create } from 'zustand';
import { apiClient, api } from '@/api/client';

export type AlertThresholdKey =
  | 'cost_burn_spike_usd_per_hour'
  | 'token_burn_spike_per_minute'
  | 'token_burn_sustained_per_minute'
  | 'monthly_budget_usd'
  | 'budget_warning_usd'
  | 'budget_critical_usd'
  | 'error_rate_threshold_percent'
  | 'request_latency_p99_seconds'
  | 'timeout_errors_per_5min'
  | 'rate_limit_errors_per_5min'
  | 'endpoint_call_frequency_per_minute'
  | 'endpoint_frequency_sustained_minutes'
  | 'cohere_rerank_calls_per_minute'
  | 'retrieval_mrr_threshold'
  | 'canary_pass_rate_threshold';

type FieldType = 'int' | 'float';

const FIELD_META: Record<AlertThresholdKey, FieldType> = {
  cost_burn_spike_usd_per_hour: 'float',
  token_burn_spike_per_minute: 'int',
  token_burn_sustained_per_minute: 'int',
  monthly_budget_usd: 'float',
  budget_warning_usd: 'float',
  budget_critical_usd: 'float',
  error_rate_threshold_percent: 'float',
  request_latency_p99_seconds: 'float',
  timeout_errors_per_5min: 'int',
  rate_limit_errors_per_5min: 'int',
  endpoint_call_frequency_per_minute: 'int',
  endpoint_frequency_sustained_minutes: 'int',
  cohere_rerank_calls_per_minute: 'int',
  retrieval_mrr_threshold: 'float',
  canary_pass_rate_threshold: 'float',
};

type ThresholdMap = Partial<Record<AlertThresholdKey, string>>;

interface AlertThresholdsState {
  data: ThresholdMap;
  dirty: ThresholdMap;
  loading: boolean;
  loaded: boolean;
  error: string | null;
  load: () => Promise<void>;
  updateField: (key: AlertThresholdKey, value: string) => void;
  save: (keys?: AlertThresholdKey[]) => Promise<{ status: string; updated: number; failed: number }>;
  reset: () => void;
}

function normalizeResponse(payload: Record<string, number | string | null | undefined>): ThresholdMap {
  const entries: ThresholdMap = {};
  Object.keys(FIELD_META).forEach((key) => {
    const typedKey = key as AlertThresholdKey;
    const value = payload[typedKey];
    if (value === null || value === undefined) {
      entries[typedKey] = '';
    } else {
      entries[typedKey] = String(value);
    }
  });
  return entries;
}

function parseValue(key: AlertThresholdKey, rawValue: string): number {
  if (rawValue === '' || rawValue === null || rawValue === undefined) {
    throw new Error(`Value for ${key} is required`);
  }
  const type = FIELD_META[key] || 'float';
  const parsed = type === 'int' ? parseInt(rawValue, 10) : parseFloat(rawValue);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid value for ${key}`);
  }
  return parsed;
}

export const useAlertThresholdsStore = create<AlertThresholdsState>((set, get) => ({
  data: {},
  dirty: {},
  loading: false,
  loaded: false,
  error: null,
  async load() {
    if (get().loading) {
      return;
    }
    set({ loading: true, error: null });
    try {
      const { data } = await apiClient.get<Record<string, number | string>>(api('/monitoring/alert-thresholds'));
      set({
        data: normalizeResponse(data),
        dirty: {},
        loading: false,
        loaded: true,
        error: null,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to load alert thresholds';
      set({ loading: false, error: message });
      throw error;
    }
  },
  updateField(key, value) {
    set((state) => ({
      data: { ...state.data, [key]: value },
      dirty: { ...state.dirty, [key]: value },
    }));
  },
  async save(keys) {
    const { data, dirty } = get();
    const keyList = (keys && keys.length ? keys : (Object.keys(dirty) as AlertThresholdKey[])).filter(Boolean);

    if (!keyList.length) {
      return { status: 'ok', updated: 0, failed: 0 };
    }

    const payload: Record<string, number> = {};
    keyList.forEach((key) => {
      const value = data[key];
      if (value === undefined) {
        return;
      }
      payload[key] = parseValue(key, value);
    });

    const response = await apiClient.post<{ status: string; updated: number; failed: number }>(
      api('/monitoring/alert-thresholds'),
      payload
    );

    set((state) => {
      const nextDirty = { ...state.dirty };
      keyList.forEach((key) => {
        delete nextDirty[key];
      });
      return { dirty: nextDirty };
    });

    return response.data;
  },
  reset() {
    set({ data: {}, dirty: {}, loaded: false, loading: false, error: null });
  },
}));

export function useAlertThresholdField(key: AlertThresholdKey): [string, (value: string) => void] {
  const value = useAlertThresholdsStore((state) => state.data[key] ?? '');
  const updateField = useAlertThresholdsStore((state) => state.updateField);
  const setValue = (next: string) => updateField(key, next);
  return [value, setValue];
}

