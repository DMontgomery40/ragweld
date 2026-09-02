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

export type BenchmarkDefaultOptions = {
  /**
   * The gateway alias this corpus answers with (`chat.litellm.default_model` while the
   * LiteLLM lane is on), matched against a row's model id or catalog model exactly as the
   * chat picker matches it. Empty when the deployment names none.
   */
  answeringAlias?: string;
  /** How many rows to preselect (the run gate still requires at least two). */
  count?: number;
};

/** The row this corpus answers with, or `undefined` when the catalog does not serve that alias. */
export function answeringModel(orderedModels: ChatModelInfo[], answeringAlias: string): ChatModelInfo | undefined {
  const alias = String(answeringAlias || '').trim();
  if (!alias) return undefined;
  return orderedModels.find(
    (model) => String(model.id || '').trim() === alias || String(model.catalog_model || '').trim() === alias
  );
}

/**
 * The rows a first benchmark starts with: the alias this corpus answers with, then the
 * page's display order.
 *
 * Display order alone preselected the two rows that happen to sort first in the catalog
 * (two AionLabs models on this deployment), so the first run compared two aliases the
 * operator had never chosen (S41). Anchoring on the answering alias makes the comparison
 * "what this corpus answers with, against the next candidate". The local serving row is
 * skipped unless its lane is reachable, whether it is the anchor or a filler (S11).
 * Returns fewer than `count` values when the list is too short.
 */
export function defaultBenchmarkSelection(
  orderedModels: ChatModelInfo[],
  lane: LocalLaneState,
  options: BenchmarkDefaultOptions = {}
): string[] {
  const count = Number.isFinite(options.count) ? Number(options.count) : 2;
  const values: string[] = [];
  const servesLane = (model: ChatModelInfo): boolean =>
    !lane.alias || String(model.id || '').trim() !== lane.alias || lane.reachable;

  const anchor = answeringModel(orderedModels, String(options.answeringAlias || ''));
  if (anchor && servesLane(anchor)) {
    const value = toModelValue(anchor);
    if (value) values.push(value);
  }
  for (const model of orderedModels) {
    if (values.length >= count) break;
    const value = toModelValue(model);
    if (!value || values.includes(value)) continue;
    if (!servesLane(model)) continue;
    values.push(value);
  }
  return values.slice(0, Math.max(0, count));
}

/** Short operator-facing state for the local row's detail line. */
export function describeLocalLane(lane: LocalLaneState): string {
  const backend = lane.backendLabel || 'local serving';
  if (lane.reachable) return `${backend} lane on`;
  if (lane.enabled) return `${backend} lane enabled but not serving`;
  return `${backend} lane disabled on this host`;
}
