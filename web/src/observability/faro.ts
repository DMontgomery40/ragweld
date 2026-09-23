import { getWebInstrumentations, initializeFaro, type Faro } from '@grafana/faro-web-sdk';

let faro: Faro | null = null;
let decided = false;
const decisionListeners = new Set<(active: boolean) => void>();

function decide(active: boolean): void {
  if (decided) return;
  decided = true;
  for (const listener of decisionListeners) listener(active);
}

/**
 * Initialize frontend RUM (errors, web vitals, session events) once, from the
 * first loaded runtime config. No-op when `tracing.faro_base_url` is empty —
 * the collector (Alloy faro.receiver) is not deployed in that case.
 *
 * Faro cannot be re-initialized, so the first loaded config wins; the
 * collector endpoint is global wiring, not a per-corpus tunable.
 *
 * `undefined`/`null` means the config has not loaded yet; an empty string is a
 * loaded config that turns RUM off. Either real answer is announced once to
 * `onFaroDecision` listeners (the journey queue in `rum.ts` drains or drops).
 */
export function initFaroFromConfig(collectorUrl: string | null | undefined): Faro | null {
  if (faro) return faro;
  if (collectorUrl === undefined || collectorUrl === null) return null;
  const url = String(collectorUrl).trim();
  if (!url) {
    decide(false);
    return null;
  }
  try {
    faro = initializeFaro({
      url,
      app: { name: 'ragweld-web', namespace: 'ragweld' },
      instrumentations: [...getWebInstrumentations({ captureConsole: false })],
    });
  } catch (error) {
    console.warn('[faro] RUM initialization failed:', error);
  }
  decide(Boolean(faro));
  return faro;
}

/** Current Faro instance (null when RUM is not configured). */
export function activeFaro(): Faro | null {
  return faro;
}

/** Called once, when a loaded config has either started RUM or turned it off. */
export function onFaroDecision(listener: (active: boolean) => void): () => void {
  if (decided) {
    listener(Boolean(faro));
    return () => {};
  }
  decisionListeners.add(listener);
  return () => decisionListeners.delete(listener);
}
