import { activeFaro, onFaroDecision } from './faro';
import {
  LAYOUT_SHIFT_POLICY,
  createRateLimiter,
  createRum,
  layoutShiftEvent,
  type LayoutShiftPhase,
  type RumContext,
  type RumMeasurementName,
  type ShiftSourceRegion,
} from './rumCore';

/**
 * The app's RUM journeys, bound to Grafana Faro (`rumCore.ts` has the policy and the names).
 *
 * Measurements (Faro `pushMeasurement`, `values: { duration_ms }`):
 *   app_load_to_composer_ready  { surface: main|dock, landing_route }
 *   chat_send_to_status         { model, outcome }
 *   chat_send_to_first_text     { model, outcome }
 *   chat_send_to_done           { model, outcome }
 *   conversation_switch         { kind: select|new|delete, surface }
 * Events (Faro `pushEvent`):
 *   layout_shift                { region, surface, phase: load|stream|idle, value, sample_rate }
 */
export const rum = createRum(() => activeFaro()?.api ?? null);

onFaroDecision((active) => (active ? rum.flush() : rum.disable()));

/** Top-level route the page was opened on ('chat', 'dashboard', ...), fixed at first import. */
const LANDING_ROUTE = (() => {
  try {
    const path = window.location.pathname.replace(/^\/web(?=\/|$)/, '');
    return path.split('/').filter(Boolean)[0] || 'root';
  } catch {
    return 'unknown';
  }
})();

/** Shifts count as 'load' until the composer is first usable, or this long after navigation. */
const LOAD_PHASE_MAX_MS = 10_000;
let loadPhaseOver = false;
let streaming = false;

/** The chat stream controller reports whether any answer is streaming. */
export function setRumStreaming(active: boolean): void {
  streaming = active;
}

function currentShiftPhase(): LayoutShiftPhase {
  if (!loadPhaseOver && performance.now() < LOAD_PHASE_MAX_MS) return 'load';
  return streaming ? 'stream' : 'idle';
}

let composerReadyReported = false;

/** The first time a chat composer is on screen and usable in this page load. */
export function reportComposerReady(surface: 'main' | 'dock'): void {
  if (composerReadyReported) return;
  composerReadyReported = true;
  loadPhaseOver = true;
  rum.measure('app_load_to_composer_ready', performance.now(), { surface, landing_route: LANDING_ROUTE });
}

export function reportJourney(name: RumMeasurementName, durationMs: number, context: RumContext): void {
  rum.measure(name, durationMs, context);
}

let switchStart: { at: number; kind: string; owner: string } | null = null;

/**
 * The operator asked for another conversation (picked one, started one, deleted the open one).
 * `owner` is the chat view that acted: the other view mirroring the switch does not end it.
 */
export function startConversationSwitch(kind: 'select' | 'new' | 'delete', owner: string): void {
  switchStart = { at: performance.now(), kind, owner };
}

/** The switched-to conversation is on screen in `owner`'s view. */
export function finishConversationSwitch(owner: string, surface: 'main' | 'dock'): void {
  if (!switchStart || switchStart.owner !== owner) return;
  const { at, kind } = switchStart;
  switchStart = null;
  rum.measure('conversation_switch', performance.now() - at, { kind, surface });
}

type LayoutShiftAttribution = {
  node?: Node | null;
  previousRect: DOMRectReadOnly;
  currentRect: DOMRectReadOnly;
};
type LayoutShiftEntry = PerformanceEntry & {
  value: number;
  hadRecentInput: boolean;
  sources?: LayoutShiftAttribution[];
};

function sourceRegion(source: LayoutShiftAttribution): ShiftSourceRegion {
  const node = source.node ?? null;
  const element = node instanceof Element ? node : node?.parentElement ?? null;
  const area = Math.max(
    source.currentRect.width * source.currentRect.height,
    source.previousRect.width * source.previousRect.height,
  );
  if (!element) return { region: 'unknown', surface: 'main', area };
  const region = element.closest('[data-region]')?.getAttribute('data-region') || 'other';
  const surface = element.closest(DOCK_SURFACE_SELECTOR) ? 'dock' : 'main';
  return { region, surface, area };
}

/** The Dock: its native pane in this document, or this whole document when it is the Dock's frame. */
export const DOCK_SURFACE_SELECTOR = '[data-region="dock"], .app-embed-root[data-docked="true"]';

let layoutShiftObserverInstalled = false;

/** Report sampled, rate-limited layout shifts with the region that moved. Installs once per page. */
export function installLayoutShiftObserver(): void {
  if (layoutShiftObserverInstalled || typeof PerformanceObserver === 'undefined') return;
  layoutShiftObserverInstalled = true;
  const limiter = createRateLimiter(LAYOUT_SHIFT_POLICY.maxPerMinute, 60_000, () => performance.now());
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries() as LayoutShiftEntry[]) {
        const attributes = layoutShiftEvent(
          {
            value: entry.value,
            hadRecentInput: entry.hadRecentInput,
            sources: (entry.sources ?? []).map(sourceRegion),
          },
          currentShiftPhase(),
          { random: Math.random, limiter },
        );
        if (attributes) rum.event('layout_shift', attributes);
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {
    // layout-shift is not supported in this browser
  }
}
