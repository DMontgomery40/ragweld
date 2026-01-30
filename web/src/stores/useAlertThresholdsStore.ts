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

/**
 * ---agentspec
 * what: |
 *   Normalizes a payload object into a ThresholdMap by converting all values to strings.
 *   Takes a Record with string keys and values that are numbers, strings, null, or undefined.
 *   Iterates over FIELD_META keys, retrieves corresponding payload values, and converts them to strings (null/undefined become empty strings).
 *   Returns a ThresholdMap object where all values are stringified.
 *   Handles missing keys gracefully by treating them as undefined and converting to empty strings.
 *
 * why: |
 *   Ensures consistent string representation of threshold values across the application, regardless of input type.
 *   Centralizes type coercion logic so downstream consumers always receive normalized string data.
 *   Iterating over FIELD_META keys (rather than payload keys) guarantees only expected fields are processed and prevents injection of unexpected keys.
 *
 * guardrails:
 *   - DO NOT modify the iteration to use Object.keys(payload) instead of Object.keys(FIELD_META) because it would allow arbitrary keys to bypass validation
 *   - ALWAYS cast keys to AlertThresholdKey type to maintain type safety and prevent runtime key mismatches
 *   - NOTE: Empty strings are used as the normalized representation for null/undefined; confirm this is the intended sentinel value for your use case
 *   - ASK USER: Before changing the string conversion logic, clarify whether numeric precision should be preserved (e.g., toFixed for decimals) or if simple String() coercion is sufficient
 * ---/agentspec
 */
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

/**
 * ---agentspec
 * what: |
 *   Parses and validates a raw string value into a typed number (int or float) based on the alert threshold key.
 *   Takes two parameters: key (AlertThresholdKey) and rawValue (string). Returns a number after type conversion.
 *   Throws Error if rawValue is empty/null/undefined, or if parsing fails (NaN result).
 *   Uses FIELD_META lookup to determine target type; defaults to 'float' if key not found.
 *   Handles both integer parsing (base 10) and floating-point parsing with NaN validation.
 *
 * why: |
 *   Centralizes type conversion logic for alert threshold configuration to ensure consistent validation across all threshold keys.
 *   Separates parsing concerns from business logic, making it reusable for multiple threshold fields.
 *   The FIELD_META lookup pattern allows per-key type specification without hardcoding conversion rules.
 *
 * guardrails:
 *   - DO NOT remove the NaN check; parseFloat/parseInt return NaN on invalid input, which would silently pass invalid data
 *   - ALWAYS validate rawValue for empty/null/undefined before parsing to provide clear error messages
 *   - NOTE: Default type 'float' means missing FIELD_META entries will parse as floats; confirm this is intentional for all keys
 *   - ASK USER: Before modifying FIELD_META lookup or adding new AlertThresholdKey types, confirm the type mapping is complete and correct
 * ---/agentspec
 */
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

/**
 * ---agentspec
 * what: |
 *   Custom React hook that provides reactive access to a single alert threshold field from Zustand store.
 *   Takes an AlertThresholdKey parameter (string enum identifying which threshold field to access).
 *   Returns a tuple: [currentValue: string, setValue: (value: string) => void].
 *   The hook subscribes to store changes for the specific key and re-renders only when that field updates.
 *   Handles missing/undefined values by defaulting to empty string.
 *
 * why: |
 *   Abstracts Zustand store subscription logic into a reusable hook following React conventions.
 *   Reduces boilerplate in components that need to read/write individual threshold fields.
 *   Selector pattern ensures components only re-render when their specific field changes, not on unrelated store updates.
 *   Provides a familiar useState-like API for developers familiar with React hooks.
 *
 * guardrails:
 *   - DO NOT call this hook conditionally or in loops; it must be called at the top level of a component
 *   - ALWAYS pass a valid AlertThresholdKey; invalid keys will silently return empty string with no error
 *   - NOTE: The hook does not validate the string value being set; validation must occur in updateField or at form submission
 *   - ASK USER: Before adding debouncing or async validation, confirm whether updates should be immediate or batched
 * ---/agentspec
 */
export function useAlertThresholdField(key: AlertThresholdKey): [string, (value: string) => void] {
  const value = useAlertThresholdsStore((state) => state.data[key] ?? '');
  const updateField = useAlertThresholdsStore((state) => state.updateField);
  /**
   * ---agentspec
   * what: |
   *   Returns a tuple containing the current field value and a setter function for updating that field.
   *   Takes a `key` parameter (string) identifying which field to manage and accesses `value` from closure/context.
   *   Returns a two-element array: [currentValue: string, setterFunction: (next: string) => void].
   *   The setter function calls `updateField(key, next)` to persist changes, delegating update logic to the parent scope.
   *   No edge case handling; assumes `key` is valid and `updateField` is always available in closure.
   *
   * why: |
   *   Provides a React-like hook pattern for field state management, abstracting the update mechanism behind a simple setter interface.
   *   Centralizes the field key and update logic so callers only need to invoke the setter without knowing implementation details.
   *   This pattern reduces boilerplate when managing multiple form fields or similar state containers.
   *
   * guardrails:
   *   - DO NOT modify the return tuple structure without updating all call sites; the [value, setter] convention is relied upon by consumers
   *   - ALWAYS ensure `updateField` is defined in the enclosing scope before calling this function; missing dependency will cause runtime error
   *   - NOTE: No validation of `key` or `next` value; invalid keys will silently fail or update wrong fields if `updateField` lacks guards
   *   - ASK USER: Confirm whether `value` should be validated (e.g., non-empty string) before returning, or if that responsibility belongs to `updateField`
   * ---/agentspec
   */
  const setValue = (next: string) => updateField(key, next);
  return [value, setValue];
}

