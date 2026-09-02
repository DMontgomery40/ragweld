import type { ChatModelInfo, ReadinessStatus, RuntimeCapabilitiesResponse } from '@/types/generated';

// Pure selection rules for the Benchmark tab. No runtime imports: this module is also
// exercised by the node:test unit suite (web/tests/unit) outside the browser bundle.

/** Canonical checkbox value for a model row (the request's model_override). */
export function toModelValue(model: ChatModelInfo): string {
  return String(model.override || model.id || '').trim();
}

export type LocalLaneState = {
  /** Gateway alias of the local serving row (from runtime capabilities). */
  alias: string;
  /** Serving backend label the host names for that lane (from runtime capabilities). */
  backendLabel: string;
  /** chat.vllm.enabled in the effective config. */
  enabled: boolean;
  /** enabled AND the readiness probe for that backend answered ok. */
  reachable: boolean;
};

/**
 * The local serving lane as this host really has it: switched on in the effective
 * config (runtime capabilities) and answering its readiness probe. A lane that is off,
 * or on but not serving, is never a benchmark default.
 */
export function localLaneState(capabilities: RuntimeCapabilitiesResponse, readiness: ReadinessStatus | null): LocalLaneState {
  const lane = capabilities.generation?.local_serving;
  const alias = String(lane?.alias || '').trim();
  const backend = String(lane?.backend || '').trim();
  const enabled = lane?.enabled === true;
  const probe = backend && readiness ? readiness.dependencies?.[backend] : undefined;
  return {
    alias,
    backendLabel: String(lane?.backend_label || '').trim(),
    enabled,
    reachable: enabled && probe?.ok === true,
  };
}

/**
 * The first `count` distinct rows of `orderedModels` (the page's display order), skipping
 * the local alias unless its lane is reachable. Returns fewer than `count` values when the
 * list is too short; the run gate still requires at least two.
 */
export function defaultBenchmarkSelection(orderedModels: ChatModelInfo[], lane: LocalLaneState, count = 2): string[] {
  const values: string[] = [];
  for (const model of orderedModels) {
    const value = toModelValue(model);
    if (!value || values.includes(value)) continue;
    if (lane.alias && String(model.id || '').trim() === lane.alias && !lane.reachable) continue;
    values.push(value);
    if (values.length >= count) break;
  }
  return values;
}

/** Short operator-facing state for the local row's detail line. */
export function describeLocalLane(lane: LocalLaneState): string {
  const backend = lane.backendLabel || 'local serving';
  if (lane.reachable) return `${backend} lane on`;
  if (lane.enabled) return `${backend} lane enabled but not serving`;
  return `${backend} lane disabled on this host`;
}
