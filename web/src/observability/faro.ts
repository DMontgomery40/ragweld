import { getWebInstrumentations, initializeFaro, type Faro } from '@grafana/faro-web-sdk';

let faro: Faro | null = null;

/**
 * Initialize frontend RUM (errors, web vitals, session events) once, from the
 * first loaded runtime config. No-op when `tracing.faro_base_url` is empty —
 * the collector (Alloy faro.receiver) is not deployed in that case.
 *
 * Faro cannot be re-initialized, so the first loaded config wins; the
 * collector endpoint is global wiring, not a per-corpus tunable.
 */
export function initFaroFromConfig(collectorUrl: string | null | undefined): Faro | null {
  const url = String(collectorUrl ?? '').trim();
  if (!url || faro) return faro;
  try {
    faro = initializeFaro({
      url,
      app: { name: 'ragweld-web', namespace: 'ragweld' },
      instrumentations: [...getWebInstrumentations({ captureConsole: false })],
    });
  } catch (error) {
    console.warn('[faro] RUM initialization failed:', error);
  }
  return faro;
}

/** Current Faro instance (null when RUM is not configured). */
export function activeFaro(): Faro | null {
  return faro;
}
