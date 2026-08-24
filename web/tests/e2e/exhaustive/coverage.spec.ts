import { test } from '@playwright/test';
import {
  applyRefreshDoubleCheck,
  assertRuntimePreflight,
  collectVisibleControls,
  ensureAppReady,
  executeControlAction,
  gotoSurface,
  isNeverTouchControl,
  isRetrievalImpactControl,
  runMetricsBudgetCheck,
  runChatProbe,
  runEvalAndMcpSmoke,
  runRequiredProviderCoverage,
  scanPropagationMirrors,
} from './harness';
import { OutcomeSink } from './outcome_sink';
import {
  REAL_WORLD_CHAT_QUESTIONS,
  RETRIEVAL_PROBES_PER_MUTATION,
  UI_SURFACES,
} from './suite_config';
import type { ControlDescriptor, UISurface } from './types';

const RESUME = process.env.EXHAUSTIVE_RESUME !== '0';
const MODE = process.env.EXHAUSTIVE_MODE ?? 'full';

function surfaceKey(surface: UISurface): string {
  return `${surface.route}|${surface.subtab || ''}`;
}

function controlKey(surface: UISurface, control: ControlDescriptor): string {
  return `${surfaceKey(surface)}|${control.fingerprint}`;
}

test('exhaustive ui mutation + persistence + probe loop', async ({ page }) => {
  const sink = new OutcomeSink();
  await sink.init({ truncate: !RESUME });

  let questionIdx = 0;
  let retrievalMutationCount = 0;
  const seen = new Set<string>(RESUME ? Array.from(await sink.loadResumeKeys()) : []);

  const nextQuestion = (): string => {
    const q = REAL_WORLD_CHAT_QUESTIONS[questionIdx % REAL_WORLD_CHAT_QUESTIONS.length];
    questionIdx += 1;
    return q;
  };

  try {
    // Relative path: the app is served under /web/, so an absolute
    // '/dashboard' resolves to the origin root (404) against the baseURL.
    await page.goto('dashboard', { waitUntil: 'domcontentloaded' });
    await ensureAppReady(page);
    const preflight = await assertRuntimePreflight(page);
    await sink.add({
      ts: new Date().toISOString(),
      surface: 'global',
      surface_key: 'global|preflight',
      action: 'preflight',
      control_fingerprint: 'runtime',
      control_selector: 'runtime',
      status: preflight.has_local_model && preflight.has_cloud_model ? 'ok' : 'failed',
      duration_ms: 0,
      detail: `mode=${MODE} model_count=${preflight.model_count} has_local=${preflight.has_local_model} has_cloud=${preflight.has_cloud_model}`,
      error: preflight.has_local_model && preflight.has_cloud_model ? undefined : 'missing required local/cloud model coverage',
    });
    if (!preflight.has_local_model || !preflight.has_cloud_model) {
      throw new Error('Preflight failed: need at least one local model and one cloud model.');
    }

    const providerCoverage = await runRequiredProviderCoverage(page, (provider) =>
      `Explain the most important operational tradeoffs when using ${provider} models in this RAG workflow.`
    );
    for (const row of providerCoverage) {
      await sink.add({
        ts: new Date().toISOString(),
        surface: 'global',
        surface_key: 'global|provider_coverage',
        action: `provider_coverage:${row.provider}`,
        control_fingerprint: `provider:${row.provider}`,
        control_selector: '[data-testid="model-picker"]',
        status: row.available && row.tested ? 'ok' : 'failed',
        duration_ms: 0,
        detail: row.detail,
        retrieval_probe_feedback: row.feedback,
      });
    }
    // Required-provider probes are a hard gate, not sink telemetry: a probe
    // that could not run must fail the suite instead of passing silently.
    const brokenProviders = providerCoverage.filter((row) => !(row.available && row.tested));
    if (brokenProviders.length > 0) {
      throw new Error(
        `Required provider coverage failed: ${brokenProviders
          .map((row) => `${row.provider} (${row.detail})`)
          .join('; ')}`
      );
    }

    for (const surface of UI_SURFACES) {
      await gotoSurface(page, surface);
      if (MODE === 'preflight') {
        const count = (await collectVisibleControls(page)).length;
        await sink.add({
          ts: new Date().toISOString(),
          surface: surface.label,
          surface_key: surfaceKey(surface),
          action: 'preflight_inventory',
          control_fingerprint: 'inventory',
          control_selector: 'inventory',
          status: 'ok',
          duration_ms: 0,
          detail: `visible_controls=${count}`,
        });
        continue;
      }

      // Crawl up to 4 passes per surface to catch controls revealed by prior clicks.
      for (let pass = 0; pass < 4; pass += 1) {
        const controls = await collectVisibleControls(page);
        const pending = controls.filter((c) => !seen.has(controlKey(surface, c)));
        if (!pending.length) break;

        for (const control of pending) {
          const key = controlKey(surface, control);
          seen.add(key);
          const startedAt = Date.now();

          if (isNeverTouchControl(control)) {
            await sink.add({
              ts: new Date().toISOString(),
              surface: surface.label,
              surface_key: surfaceKey(surface),
              action: 'skip:sensitive',
              control_fingerprint: control.fingerprint,
              control_selector: control.selector,
              status: 'skipped',
              duration_ms: Date.now() - startedAt,
              detail: 'Sensitive field (keys/secrets/webhooks) is excluded by policy.',
            });
            continue;
          }

          try {
            const actions = await executeControlAction(page, control);
            if (!actions.length) {
              await sink.add({
                ts: new Date().toISOString(),
                surface: surface.label,
                surface_key: surfaceKey(surface),
                action: 'skip:non-actionable',
                control_fingerprint: control.fingerprint,
                control_selector: control.selector,
                status: 'skipped',
                duration_ms: Date.now() - startedAt,
                detail: 'No safe deterministic action available in current mode.',
              });
              continue;
            }

            for (const a of actions) {
              const actionStartedAt = Date.now();
              let detail = '';
              let question: string | undefined;
              let feedback: 'thumbsup' | 'thumbsdown' | undefined;

              if (a.expected !== undefined) {
                const cycle = await applyRefreshDoubleCheck(page, control, a.expected);
                detail = `config_changed=${cycle.config_changed} persisted_after_refresh=${cycle.persisted_after_refresh} ui_matches=${cycle.ui_matches}`;
                if (!cycle.persisted_after_refresh || !cycle.ui_matches) {
                  throw new Error(`post-change validation failed (${detail})`);
                }

                const propagation = await scanPropagationMirrors(page, surface, control, a.expected);
                detail += ` propagation_checked=${propagation.checked}`;
                if (propagation.failed.length) {
                  throw new Error(`propagation mismatch: ${propagation.failed[0]}`);
                }

                if (isRetrievalImpactControl(control)) {
                  retrievalMutationCount += 1;
                  const probeSignals: string[] = [];
                  for (let i = 0; i < RETRIEVAL_PROBES_PER_MUTATION; i += 1) {
                    question = nextQuestion();
                    const probe = await runChatProbe(page, question);
                    feedback = probe.feedback;
                    probeSignals.push(`q${i + 1}:${probe.feedback}:${probe.detail}`);
                    await sink.add({
                      ts: new Date().toISOString(),
                      surface: surface.label,
                      surface_key: surfaceKey(surface),
                      action: `retrieval_probe_${i + 1}`,
                      control_fingerprint: control.fingerprint,
                      control_selector: control.selector,
                      status: 'ok',
                      duration_ms: 0,
                      detail: probe.detail,
                      retrieval_probe_question: question,
                      retrieval_probe_feedback: probe.feedback,
                    });
                  }
                  detail += ` probes=${probeSignals.join('|')}`;
                  await runEvalAndMcpSmoke(page);

                  const metrics = await runMetricsBudgetCheck(page, retrievalMutationCount);
                  if (metrics.checked) {
                    detail += ` metrics_budget=${metrics.budget} sample_every=${metrics.sample_every}`;
                    if (metrics.missing.length) {
                      throw new Error(`metrics check failed: ${metrics.missing[0]}`);
                    }
                  }
                }
              } else {
                detail = 'click action executed';
              }

              await sink.add({
                ts: new Date().toISOString(),
                surface: surface.label,
                surface_key: surfaceKey(surface),
                action: a.action,
                control_fingerprint: control.fingerprint,
                control_selector: control.selector,
                status: 'ok',
                duration_ms: Date.now() - actionStartedAt,
                detail,
                retrieval_probe_question: question,
                retrieval_probe_feedback: feedback,
              });

              // Re-anchor to the current surface after each action.
              await gotoSurface(page, surface);
            }
          } catch (error) {
            await sink.add({
              ts: new Date().toISOString(),
              surface: surface.label,
              surface_key: surfaceKey(surface),
              action: 'action_failed',
              control_fingerprint: control.fingerprint,
              control_selector: control.selector,
              status: 'failed',
              duration_ms: Date.now() - startedAt,
              error: error instanceof Error ? error.message : String(error),
            });

            // Re-anchor after failures so the loop can continue.
            await gotoSurface(page, surface);
          }
        }
      }
    }
  } finally {
    await sink.finalize();
  }
});
