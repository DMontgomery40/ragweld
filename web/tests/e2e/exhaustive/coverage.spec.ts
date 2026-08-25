// Exhaustive UI mutation loop over an ISOLATED corpus.
//
// Modernized 2026-08-25 (Phase B defect 6 residual): the loop used to mutate
// every control against whatever corpus the live registry had active, probed
// with generic meta-questions, and never failed — failures only went to the
// sink. Now it provisions its own indexed corpus over the acceptance fixture
// (with its own query log and triplets file), grades real domain questions
// against evidence groups, checks every click against the API responses it
// caused, keeps to a wall-clock budget, proves the global (unscoped) config was
// not touched, deletes its corpus, and fails the test when any action failed.
//
// Modes: `preflight` inventories controls only; `smoke` is budget-bounded and
// reports unreached surfaces as skipped (a loop proof, not a coverage claim);
// `full` must complete every surface within the budget or fails. There is no
// cross-run resume: each run gets a fresh corpus, so a previous run's "ok"
// fingerprints describe a corpus state that no longer exists.
import { test } from '@playwright/test';
import {
  applyRefreshDoubleCheck,
  assertRuntimePreflight,
  collectVisibleControls,
  diffTopLevelSections,
  ensureAppReady,
  executeControlAction,
  fetchGlobalConfigSnapshot,
  gotoSurface,
  isActionBlacklisted,
  isNeverTouchControl,
  isRetrievalImpactControl,
  runMetricsBudgetCheck,
  runChatProbe,
  runEvalAndMcpSmoke,
  runRequiredProviderCoverage,
  scanPropagationMirrors,
  trackFailedApiResponses,
  WallClockBudget,
} from './harness';
import { activateCorpusInBrowser, EXHAUSTIVE_CHAT_MODEL, provisionExhaustiveCorpus } from './corpus_fixture';
import { OutcomeSink } from './outcome_sink';
import {
  ACCEPTANCE_CORPUS_PROBES,
  EXHAUSTIVE_BUDGET_MS,
  RETRIEVAL_PROBES_PER_MUTATION,
  UI_SURFACES,
} from './suite_config';
import type { ControlDescriptor, OutcomeRecord, UISurface } from './types';

type Mode = 'preflight' | 'smoke' | 'full';
const MODE: Mode = (['preflight', 'smoke', 'full'] as const).find((m) => m === process.env.EXHAUSTIVE_MODE) ?? 'full';
// Corpus provisioning + indexing + provider gate + cleanup sit outside the loop budget.
const SETUP_MARGIN_MS = 15 * 60 * 1000;

function surfaceKey(surface: UISurface): string {
  return `${surface.route}|${surface.subtab || ''}`;
}

function controlKey(surface: UISurface, control: ControlDescriptor): string {
  return `${surfaceKey(surface)}|${control.fingerprint}`;
}

test('exhaustive ui mutation + persistence + probe loop', async ({ page, request }) => {
  test.setTimeout(Number(process.env.EXHAUSTIVE_SUITE_TIMEOUT_MS ?? EXHAUSTIVE_BUDGET_MS + SETUP_MARGIN_MS));

  const sink = new OutcomeSink();
  await sink.init({ truncate: true });
  const failures: OutcomeRecord[] = [];
  const record = async (row: OutcomeRecord): Promise<void> => {
    if (row.status === 'failed') failures.push(row);
    await sink.add(row);
  };

  let probeIdx = 0;
  let retrievalMutationCount = 0;
  const seen = new Set<string>();
  const nextProbe = () => {
    const probe = ACCEPTANCE_CORPUS_PROBES[probeIdx % ACCEPTANCE_CORPUS_PROBES.length];
    probeIdx += 1;
    return probe;
  };

  // The loop mutates config; everything it writes must land on this corpus only.
  const corpus = await provisionExhaustiveCorpus(request, { index: MODE !== 'preflight' });
  await activateCorpusInBrowser(page, corpus.corpusId);
  const globalBefore = await fetchGlobalConfigSnapshot(page);
  const budget = new WallClockBudget(EXHAUSTIVE_BUDGET_MS);
  let surfacesCompleted = 0;
  let budgetExhausted = false;

  try {
    // Relative path: the app is served under /web/, so an absolute
    // '/dashboard' resolves to the origin root (404) against the baseURL.
    await page.goto('dashboard', { waitUntil: 'domcontentloaded' });
    await ensureAppReady(page);
    const preflight = await assertRuntimePreflight(page);
    await record({
      ts: new Date().toISOString(),
      surface: 'global',
      surface_key: 'global|preflight',
      action: 'preflight',
      control_fingerprint: 'runtime',
      control_selector: 'runtime',
      status: preflight.has_local_model && preflight.has_cloud_model ? 'ok' : 'failed',
      duration_ms: 0,
      detail: `mode=${MODE} corpus=${corpus.corpusId} probe_model=${EXHAUSTIVE_CHAT_MODEL} model_count=${preflight.model_count} has_local=${preflight.has_local_model} has_cloud=${preflight.has_cloud_model}`,
      error: preflight.has_local_model && preflight.has_cloud_model ? undefined : 'missing required local/cloud model coverage',
    });
    if (!preflight.has_local_model || !preflight.has_cloud_model) {
      throw new Error('Preflight failed: need at least one local model and one cloud model.');
    }

    if (MODE !== 'preflight') {
      const providerCoverage = await runRequiredProviderCoverage(page, () => nextProbe(), corpus.corpusId);
      for (const row of providerCoverage) {
        await record({
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
    }

    for (const surface of UI_SURFACES) {
      if (budget.exhausted()) {
        budgetExhausted = true;
        await record({
          ts: new Date().toISOString(),
          surface: surface.label,
          surface_key: surfaceKey(surface),
          action: 'skip:budget',
          control_fingerprint: 'surface',
          control_selector: 'surface',
          status: MODE === 'full' ? 'failed' : 'skipped',
          duration_ms: 0,
          detail: `wall-clock budget of ${EXHAUSTIVE_BUDGET_MS} ms exhausted before this surface`,
          error: MODE === 'full' ? 'full mode requires every surface to complete within the budget' : undefined,
        });
        continue;
      }

      await gotoSurface(page, surface);
      if (MODE === 'preflight') {
        const count = (await collectVisibleControls(page)).length;
        await record({
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
        surfacesCompleted += 1;
        continue;
      }

      // Crawl up to 4 passes per surface to catch controls revealed by prior clicks.
      let surfaceTruncated = false;
      for (let pass = 0; pass < 4 && !surfaceTruncated; pass += 1) {
        const controls = await collectVisibleControls(page);
        const pending = controls.filter((c) => !seen.has(controlKey(surface, c)));
        if (!pending.length) break;

        for (const control of pending) {
          if (budget.exhausted()) {
            surfaceTruncated = true;
            break;
          }
          const key = controlKey(surface, control);
          seen.add(key);
          const startedAt = Date.now();

          if (isNeverTouchControl(control)) {
            await record({
              ts: new Date().toISOString(),
              surface: surface.label,
              surface_key: surfaceKey(surface),
              action: 'skip:sensitive',
              control_fingerprint: control.fingerprint,
              control_selector: control.selector,
              status: 'skipped',
              duration_ms: Date.now() - startedAt,
              detail: 'Sensitive or connection field (keys/secrets/webhooks/hosts/ports/paths) is excluded by policy.',
            });
            continue;
          }

          if (isActionBlacklisted(control, surface)) {
            await record({
              ts: new Date().toISOString(),
              surface: surface.label,
              surface_key: surfaceKey(surface),
              action: 'skip:blocked-action',
              control_fingerprint: control.fingerprint,
              control_selector: control.selector,
              status: 'skipped',
              duration_ms: Date.now() - startedAt,
              detail:
                'Training/model/process lifecycle, paid run, or any click on a host-action surface is blocked in default mode (EXHAUSTIVE_DESTRUCTIVE=1 lifts).',
            });
            continue;
          }

          const tracker = trackFailedApiResponses(page);
          try {
            const actions = await executeControlAction(page, control);
            if (!actions.length) {
              tracker.stop();
              await record({
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
                detail = `config_changed=${cycle.config_changed} apply_saved=${cycle.apply_saved} persisted_after_refresh=${cycle.persisted_after_refresh} ui_matches=${cycle.ui_matches}`;
                if (!cycle.config_changed && !cycle.apply_saved) {
                  // UI-local session state: Apply never became dirty and the
                  // corpus config is untouched, so the persistence contract does
                  // not apply. Recorded visibly, not as a pass.
                  await record({
                    ts: new Date().toISOString(),
                    surface: surface.label,
                    surface_key: surfaceKey(surface),
                    action: `skip:ui-local:${a.action}`,
                    control_fingerprint: control.fingerprint,
                    control_selector: control.selector,
                    status: 'skipped',
                    duration_ms: Date.now() - actionStartedAt,
                    detail: `${detail}; control mutates UI-local state only`,
                  });
                  await gotoSurface(page, surface);
                  continue;
                }
                if (!cycle.persisted_after_refresh || !cycle.ui_matches || !cycle.config_changed) {
                  // Apply saved (or the config moved) but the change did not
                  // survive, or Apply saved nothing: a persistence defect.
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
                    const probe = nextProbe();
                    question = probe.question;
                    const result = await runChatProbe(page, probe, { modelAlias: EXHAUSTIVE_CHAT_MODEL, corpusId: corpus.corpusId });
                    feedback = result.feedback;
                    probeSignals.push(`q${i + 1}:${result.feedback}:${result.detail}`);
                    await record({
                      ts: new Date().toISOString(),
                      surface: surface.label,
                      surface_key: surfaceKey(surface),
                      action: `retrieval_probe_${i + 1}`,
                      control_fingerprint: control.fingerprint,
                      control_selector: control.selector,
                      // An ungrounded answer after a retrieval mutation is the
                      // finding this loop exists for.
                      status: result.grounded ? 'ok' : 'failed',
                      duration_ms: 0,
                      detail: result.detail,
                      error: result.grounded ? undefined : `answer not grounded in corpus evidence after ${a.action}`,
                      retrieval_probe_question: question,
                      retrieval_probe_feedback: result.feedback,
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
                // A click is only "ok" when the UI did not surface an error and
                // no API call it caused failed (nonexistent endpoints answer 404).
                await page.waitForTimeout(750);
                const errorToast = page.locator('.toast.toast-error');
                const toastText = (await errorToast.count()) > 0 ? (await errorToast.first().innerText()).trim() : '';
                const failedCalls = [...tracker.failures];
                if (failedCalls.length || toastText) {
                  throw new Error(
                    `click produced ${failedCalls.length} failed API call(s)${toastText ? ` and an error toast "${toastText.slice(0, 120)}"` : ''}: ${failedCalls.slice(0, 3).join(' | ')}`
                  );
                }
                detail = 'click action executed; no failed API responses, no error toast';
              }

              await record({
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
            await record({
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
          } finally {
            tracker.stop();
          }
        }
      }
      if (surfaceTruncated) {
        budgetExhausted = true;
        await record({
          ts: new Date().toISOString(),
          surface: surface.label,
          surface_key: surfaceKey(surface),
          action: 'skip:budget',
          control_fingerprint: 'surface',
          control_selector: 'surface',
          status: MODE === 'full' ? 'failed' : 'skipped',
          duration_ms: 0,
          detail: `wall-clock budget of ${EXHAUSTIVE_BUDGET_MS} ms exhausted mid-surface`,
          error: MODE === 'full' ? 'full mode requires every surface to complete within the budget' : undefined,
        });
      } else {
        surfacesCompleted += 1;
      }
    }
  } finally {
    // Isolation proof: a corpus-scoped session must leave the unscoped config
    // alone. Drift is reported, never "restored": overwriting the live config
    // with a stale pre-run snapshot could erase a concurrent operator edit.
    let driftedSections: string[] = [];
    try {
      const globalAfter = await fetchGlobalConfigSnapshot(page);
      driftedSections = diffTopLevelSections(globalBefore, globalAfter);
      if (driftedSections.length) {
        await record({
          ts: new Date().toISOString(),
          surface: 'global',
          surface_key: 'global|config_isolation',
          action: 'global_config_drift',
          control_fingerprint: 'config',
          control_selector: 'GET /api/config',
          status: 'failed',
          duration_ms: 0,
          error: `unscoped config sections changed during a corpus-scoped run: ${driftedSections.join(', ')} (NOT restored; inspect and revert deliberately)`,
        });
      }
    } finally {
      try {
        await corpus.dispose();
      } finally {
        await sink.finalize({
          mode: MODE,
          corpus_id: corpus.corpusId,
          probe_model: EXHAUSTIVE_CHAT_MODEL,
          budget_ms: EXHAUSTIVE_BUDGET_MS,
          elapsed_ms: budget.elapsedMs(),
          budget_exhausted: budgetExhausted,
          surfaces_completed: surfacesCompleted,
          surfaces_total: UI_SURFACES.length,
          global_config_drift: driftedSections,
        });
      }
    }
  }

  if (failures.length) {
    const preview = failures
      .slice(0, 5)
      .map((row) => `${row.surface} :: ${row.action} :: ${row.control_selector} :: ${row.error || row.detail || ''}`)
      .join('\n');
    throw new Error(`${failures.length} exhaustive action(s) failed (see outcomes.ndjson):\n${preview}`);
  }
});
