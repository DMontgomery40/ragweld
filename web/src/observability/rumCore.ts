/**
 * Named user journeys and layout-shift attribution for frontend RUM, independent of the SDK.
 *
 * The app reports a handful of journeys the operator actually waits on (load to a usable
 * composer, send to first text, conversation switch) plus every sampled layout shift with the
 * region of the page that moved. `rum.ts` binds this core to Grafana Faro; with Faro off it is a
 * no-op, and before Faro has initialized a small bounded queue holds what was reported early.
 *
 * Only relative imports and types here, so `node --test` loads it (web/tests/unit/rum_core.test.ts).
 */

/** Durations, pushed as Faro measurements with `values: { duration_ms }`. */
export type RumMeasurementName =
  | 'app_load_to_composer_ready'
  | 'chat_send_to_status'
  | 'chat_send_to_first_text'
  | 'chat_send_to_done'
  | 'conversation_switch';

/** Discrete occurrences, pushed as Faro events with string attributes. */
export type RumEventName = 'layout_shift';

export type RumContext = Record<string, string>;

/** The two Faro API calls this module uses (a structural subset of `faro.api`). */
export type RumSink = {
  pushMeasurement: (
    payload: { type: string; values: Record<string, number> },
    options?: { context?: RumContext; skipDedupe?: boolean },
  ) => void;
  pushEvent: (name: string, attributes?: RumContext, domain?: string, options?: { skipDedupe?: boolean }) => void;
};

type Pending =
  | { kind: 'measurement'; name: RumMeasurementName; durationMs: number; context: RumContext }
  | { kind: 'event'; name: RumEventName; attributes: RumContext };

export type Rum = {
  measure: (name: RumMeasurementName, durationMs: number, context?: RumContext) => void;
  event: (name: RumEventName, attributes?: RumContext) => void;
  /** RUM is configured and ready: drain the queue into the sink. */
  flush: () => void;
  /** RUM is configured off: drop the queue and ignore everything from now on. */
  disable: () => void;
  /** Items waiting for the sink (for tests and diagnostics). */
  queued: () => number;
};

export const RUM_QUEUE_LIMIT = 50;

export function createRum(getSink: () => RumSink | null, options: { queueLimit?: number } = {}): Rum {
  const limit = options.queueLimit ?? RUM_QUEUE_LIMIT;
  let queue: Pending[] = [];
  let disabled = false;

  const send = (sink: RumSink, item: Pending) => {
    try {
      if (item.kind === 'measurement') {
        sink.pushMeasurement(
          { type: item.name, values: { duration_ms: Math.max(0, Math.round(item.durationMs)) } },
          { context: item.context, skipDedupe: true },
        );
      } else {
        sink.pushEvent(item.name, item.attributes, undefined, { skipDedupe: true });
      }
    } catch {
      // RUM must never break the page it measures
    }
  };

  const drain = (sink: RumSink) => {
    const pending = queue;
    queue = [];
    for (const item of pending) send(sink, item);
  };

  const report = (item: Pending) => {
    if (disabled) return;
    const sink = getSink();
    if (sink) {
      if (queue.length) drain(sink);
      send(sink, item);
      return;
    }
    queue.push(item);
    if (queue.length > limit) queue.splice(0, queue.length - limit);
  };

  return {
    measure: (name, durationMs, context = {}) => {
      if (!Number.isFinite(durationMs)) return;
      report({ kind: 'measurement', name, durationMs, context });
    },
    event: (name, attributes = {}) => report({ kind: 'event', name, attributes }),
    flush: () => {
      const sink = getSink();
      if (sink && !disabled) drain(sink);
    },
    disable: () => {
      disabled = true;
      queue = [];
    },
    queued: () => queue.length,
  };
}

/** Allows at most `max` takes per sliding `windowMs`. */
export function createRateLimiter(max: number, windowMs: number, now: () => number): { tryTake: () => boolean } {
  const taken: number[] = [];
  return {
    tryTake() {
      const t = now();
      while (taken.length && t - taken[0] >= windowMs) taken.shift();
      if (taken.length >= max) return false;
      taken.push(t);
      return true;
    },
  };
}

export type LayoutShiftPhase = 'load' | 'stream' | 'idle';

/** One attributed source of a layout shift: the moved node's region and the area it covered. */
export type ShiftSourceRegion = { region: string; surface: 'main' | 'dock'; area: number };

/**
 * The region a shift is charged to: the source that moved the largest area. A shift with no
 * attributable source is charged to 'unknown'; a source outside every named region to 'other'.
 */
export function pickShiftRegion(sources: ShiftSourceRegion[]): { region: string; surface: 'main' | 'dock' } {
  let best: ShiftSourceRegion | null = null;
  for (const source of sources) {
    if (!best || source.area > best.area) best = source;
  }
  return best ? { region: best.region, surface: best.surface } : { region: 'unknown', surface: 'main' };
}

export type LayoutShiftPolicy = {
  /** Shifts smaller than this are not reported (sub-pixel noise). */
  minValue: number;
  /** Fraction of qualifying shifts that are reported; reported as `sample_rate`. */
  sampleRate: number;
  /** Most shifts reported per minute per page. */
  maxPerMinute: number;
};

export const LAYOUT_SHIFT_POLICY: LayoutShiftPolicy = { minValue: 0.001, sampleRate: 0.5, maxPerMinute: 20 };

/**
 * Decide whether one shift is reported and with which attributes. Pure except for the injected
 * random draw and rate limiter, so the sampling and limiting policy is unit-tested.
 */
export function layoutShiftEvent(
  shift: { value: number; hadRecentInput: boolean; sources: ShiftSourceRegion[] },
  phase: LayoutShiftPhase,
  deps: { random: () => number; limiter: { tryTake: () => boolean }; policy?: LayoutShiftPolicy },
): RumContext | null {
  const policy = deps.policy ?? LAYOUT_SHIFT_POLICY;
  if (shift.hadRecentInput) return null;
  if (!(shift.value >= policy.minValue)) return null;
  if (deps.random() >= policy.sampleRate) return null;
  if (!deps.limiter.tryTake()) return null;
  const { region, surface } = pickShiftRegion(shift.sources);
  return {
    region,
    surface,
    phase,
    value: shift.value.toFixed(4),
    sample_rate: String(policy.sampleRate),
  };
}
