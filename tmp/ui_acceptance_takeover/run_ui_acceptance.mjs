import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';

const CORPUS_ID = 'epstein-files-1';
const UI_BASE = process.env.UI_BASE || 'http://127.0.0.1:5173/web';
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8012/api';
const OUT_DIR = process.env.OUT_DIR || '/Users/davidmontgomery/ragweld/tmp/ui_acceptance_takeover/latest';
const SUMMARY_PATH = path.join(OUT_DIR, 'summary.json');
const USER_DATA_DIR = path.join(OUT_DIR, 'playwright_user_data');

const summary = {
  generated_at: new Date().toISOString(),
  corpus_id: CORPUS_ID,
  ui_base: UI_BASE,
  api_base: API_BASE,
  checkpoints: {},
  synthetic: {},
  publish: {
    eval_dataset: {},
    triplets: {},
  },
  quick_actions: [],
  system_prompts: {},
  eval_compare: {},
  screenshots: [],
  run_id: null,
  run_ids: [],
  eval_run_id: null,
  eval_run_ids: [],
  top1: null,
  topk: null,
  mrr: null,
  sample: null,
  api_status_evidence: {
    synthetic_start: [],
    synthetic_publish: [],
    eval: [],
  },
  instability_notes: [],
  blocker: null,
  furthest_checkpoint: null,
  errors: [],
};

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function ensureOutDir() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.mkdir(USER_DATA_DIR, { recursive: true });
}

async function fetchJson(url, opts = undefined) {
  const res = await fetch(url, opts);
  const text = await res.text();
  let json = null;
  try {
    json = JSON.parse(text);
  } catch {
    json = null;
  }
  return {
    ok: res.ok,
    status: res.status,
    url,
    json,
    text,
  };
}

async function listSyntheticRuns(limit = 50) {
  const u = `${API_BASE}/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS_ID)}&limit=${limit}`;
  const resp = await fetchJson(u);
  return Array.isArray(resp.json?.runs) ? resp.json.runs : [];
}

async function getSyntheticRun(runId) {
  const u = `${API_BASE}/synthetic/run/${encodeURIComponent(runId)}`;
  const resp = await fetchJson(u);
  return resp.json;
}

async function listEvalRuns() {
  const u = `${API_BASE}/eval/runs?corpus_id=${encodeURIComponent(CORPUS_ID)}`;
  const resp = await fetchJson(u, { headers: { 'Cache-Control': 'no-store' } });
  const runs = Array.isArray(resp.json?.runs) ? resp.json.runs : [];
  runs.sort((a, b) => String(b.run_id || '').localeCompare(String(a.run_id || '')));
  return runs;
}

async function getEvalResults(runId) {
  const u = `${API_BASE}/eval/results/${encodeURIComponent(runId)}`;
  const resp = await fetchJson(u);
  return resp.json;
}

async function waitUntil(fn, {
  timeoutMs = 30000,
  intervalMs = 500,
  description = 'condition',
} = {}) {
  const start = Date.now();
  let lastErr;
  while (Date.now() - start < timeoutMs) {
    try {
      const result = await fn();
      if (result) return result;
    } catch (err) {
      lastErr = err;
    }
    await delay(intervalMs);
  }
  const suffix = lastErr ? ` (last error: ${String(lastErr)})` : '';
  throw new Error(`Timed out waiting for ${description}${suffix}`);
}

async function waitForNoActiveSynthetic(timeoutMs = 20 * 60 * 1000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const runs = await listSyntheticRuns(50);
    const active = runs.find((r) => ['queued', 'running'].includes(String(r.status || '').toLowerCase()));
    if (!active) return;
    summary.instability_notes.push(
      `Waiting for pre-existing synthetic run to finish: ${active.run_id} status=${active.status}`
    );
    await delay(5000);
  }
  throw new Error('Timed out waiting for pre-existing synthetic run to finish');
}

function safeUrlParams(urlString) {
  try {
    const u = new URL(urlString);
    return u.searchParams;
  } catch {
    return new URLSearchParams('');
  }
}

async function main() {
  await ensureOutDir();

  await waitForNoActiveSynthetic();

  const context = await chromium.launchPersistentContext(USER_DATA_DIR, {
    headless: true,
    viewport: { width: 1720, height: 1100 },
  });

  let page = context.pages()[0];
  if (!page) page = await context.newPage();
  page.setDefaultTimeout(30000);

  const screenshot = async (name) => {
    const filePath = path.join(OUT_DIR, `${name}.png`);
    await page.screenshot({ path: filePath, fullPage: true });
    summary.screenshots.push(filePath);
    return filePath;
  };

  page.on('response', async (resp) => {
    const req = resp.request();
    const url = resp.url();
    if (!url.includes('/api/')) return;

    const baseEntry = {
      ts: new Date().toISOString(),
      url,
      method: req.method(),
      status: resp.status(),
    };

    if (url.includes('/synthetic/run/start') && req.method() === 'POST') {
      let requestPayload = null;
      let responsePayload = null;
      try {
        requestPayload = req.postDataJSON();
      } catch {
        requestPayload = null;
      }
      try {
        responsePayload = await resp.json();
      } catch {
        responsePayload = null;
      }
      summary.api_status_evidence.synthetic_start.push({
        ...baseEntry,
        request: requestPayload,
        response: responsePayload,
      });
      return;
    }

    if (url.includes('/synthetic/run/') && url.includes('/publish/')) {
      let responsePayload = null;
      try {
        responsePayload = await resp.json();
      } catch {
        responsePayload = null;
      }
      summary.api_status_evidence.synthetic_publish.push({
        ...baseEntry,
        response: responsePayload,
      });
      return;
    }

    if (url.includes('/eval/')) {
      summary.api_status_evidence.eval.push(baseEntry);
    }
  });

  try {
    // 1) Load UI and open Synthetic Lab for epstein-files-1
    await page.goto(`${UI_BASE}/rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded');
    await page.evaluate(() => {
      localStorage.removeItem('synthetic.generator_model');
      localStorage.removeItem('synthetic.judge_model');
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded');
    await page.getByText('Synthetic Lab').first().waitFor({ state: 'visible' });
    summary.checkpoints.synthetic_lab_loaded = true;
    summary.checkpoints.synthetic_lab_url = page.url();
    summary.checkpoints.synthetic_lab_loaded_shot = await screenshot('01_synthetic_lab_loaded');
    summary.furthest_checkpoint = '1_ui_loaded';

    // 2/3) Confirm start buttons disabled before model selection
    const startRunBtn = page.getByRole('button', { name: 'Start Run' }).first();
    const startFullBtn = page.getByRole('button', { name: 'Start Full Stack' }).first();

    const startRunDisabledBefore = await startRunBtn.isDisabled();
    const startFullDisabledBefore = await startFullBtn.isDisabled();
    summary.checkpoints.start_disabled_before_model_selection = {
      start_run_disabled: startRunDisabledBefore,
      start_full_stack_disabled: startFullDisabledBefore,
    };
    summary.checkpoints.start_disabled_shot = await screenshot('02_start_buttons_disabled_before_models');
    summary.furthest_checkpoint = '3_pre_model_disabled_verified';

    // 4) Select explicit generator and judge models
    const genSelect = page.locator('.setting-row', { hasText: 'Generator Model' }).locator('select').first();
    const judgeSelect = page.locator('.setting-row', { hasText: 'Judge Model' }).locator('select').first();

    const selectFirstValid = async (selectLocator) => {
      const options = selectLocator.locator('option');
      const count = await options.count();
      for (let i = 0; i < count; i += 1) {
        const value = (await options.nth(i).getAttribute('value')) || '';
        if (value && value !== '__custom__') {
          await selectLocator.selectOption(value);
          return value;
        }
      }
      throw new Error('No valid model options found in model picker');
    };

    const generatorModel = await selectFirstValid(genSelect);
    const judgeModel = await selectFirstValid(judgeSelect);

    const setNumeric = async (label, value) => {
      const input = page.locator(`.input-group:has(label:has-text("${label}")) input`).first();
      await input.fill(String(value));
      return Number(await input.inputValue());
    };

    const maxSourceChunks = await setNumeric('Max source chunks', 50);
    const maxPairs = await setNumeric('Max pairs', 50);
    const pairsPerSource = await setNumeric('Pairs per source', 1);

    await waitUntil(async () => !(await startRunBtn.isDisabled()), {
      timeoutMs: 15000,
      description: 'Start Run to enable after model selection',
    });

    summary.checkpoints.models_selected = {
      generator_model: generatorModel,
      judge_model: judgeModel,
      start_run_enabled: !(await startRunBtn.isDisabled()),
      start_full_stack_enabled: !(await startFullBtn.isDisabled()),
    };
    summary.synthetic.request_budget = {
      budget_label: 'medium',
      max_source_chunks: maxSourceChunks,
      max_pairs: maxPairs,
      pairs_per_source: pairsPerSource,
    };
    summary.checkpoints.models_selected_shot = await screenshot('03_models_selected_medium_budget_set');
    summary.furthest_checkpoint = '4_models_selected';

    // 5) Start medium-budget run and wait completion
    const syntheticRunsBefore = await listSyntheticRuns(50);
    const syntheticBeforeSet = new Set(syntheticRunsBefore.map((r) => String(r.run_id || '')));
    const syntheticStartCountBefore = summary.api_status_evidence.synthetic_start.length;

    await startRunBtn.click();

    let startedRunId = null;
    try {
      await waitUntil(
        async () => summary.api_status_evidence.synthetic_start.length > syntheticStartCountBefore,
        { timeoutMs: 30000, description: 'synthetic run/start API call' }
      );
      const latestStart = summary.api_status_evidence.synthetic_start.at(-1) || null;
      startedRunId = String(latestStart?.response?.run_id || '').trim() || null;
      if (latestStart?.request) {
        summary.synthetic.start_request_payload = latestStart.request;
      }
    } catch (err) {
      summary.instability_notes.push(`Did not observe /synthetic/run/start network response immediately: ${String(err)}`);
    }

    if (!startedRunId) {
      const discovered = await waitUntil(async () => {
        const runs = await listSyntheticRuns(50);
        const fresh = runs.find((r) => !syntheticBeforeSet.has(String(r.run_id || '')));
        return fresh ? String(fresh.run_id || '') : null;
      }, {
        timeoutMs: 120000,
        intervalMs: 2000,
        description: 'new synthetic run id after Start Run click',
      });
      startedRunId = discovered;
      summary.instability_notes.push('Derived synthetic run id from run list because start response did not include run_id.');
    }

    summary.run_id = startedRunId;
    summary.run_ids = [startedRunId].filter(Boolean);
    summary.synthetic.run_id = startedRunId;

    const syntheticRun = await waitUntil(async () => {
      const run = await getSyntheticRun(startedRunId);
      const st = String(run?.status || '').toLowerCase();
      if (st === 'completed' || st === 'failed' || st === 'cancelled') return run;
      return null;
    }, {
      timeoutMs: 25 * 60 * 1000,
      intervalMs: 4000,
      description: `synthetic run ${startedRunId} completion`,
    });

    const runRow = page.locator('tr', { hasText: startedRunId }).first();
    if (await runRow.count()) {
      await runRow.click();
      await delay(500);
    }

    summary.synthetic.status = syntheticRun?.status || null;
    summary.synthetic.recipe = syntheticRun?.recipe || null;
    summary.synthetic.provider = syntheticRun?.provider || null;
    summary.synthetic.completed_at = syntheticRun?.completed_at || null;
    summary.synthetic.quality = {
      gate_passed: syntheticRun?.summary?.quality_gate_passed ?? null,
      gate_threshold: syntheticRun?.summary?.quality_gate_threshold ?? null,
      top1: syntheticRun?.summary?.quality_top1_accuracy ?? null,
      topk: syntheticRun?.summary?.quality_topk_accuracy ?? null,
      mrr: syntheticRun?.summary?.quality_mrr ?? null,
      sample: syntheticRun?.summary?.quality_sample_size ?? null,
      failure_reason: syntheticRun?.summary?.quality_failure_reason ?? null,
    };
    summary.top1 = syntheticRun?.summary?.quality_top1_accuracy ?? null;
    summary.topk = syntheticRun?.summary?.quality_topk_accuracy ?? null;
    summary.mrr = syntheticRun?.summary?.quality_mrr ?? null;
    summary.sample = syntheticRun?.summary?.quality_sample_size ?? null;

    summary.checkpoints.synthetic_run_completed_shot = await screenshot('04_synthetic_run_completed_quality_gate');
    summary.furthest_checkpoint = '6_quality_gate_and_artifacts';

    // 6/7) Publish attempts for eval_dataset and triplets
    const artifactsSection = page.locator('section', { hasText: 'Artifacts + Publish' }).first();

    const handlePublishAttempt = async ({ artifactLabel, endpointFragment, outKey, shotName }) => {
      const labelEl = artifactsSection.locator(`span:has-text("${artifactLabel}")`).first();
      await labelEl.scrollIntoViewIfNeeded();
      const row = labelEl.locator('xpath=ancestor::div[1]');
      const button = row.getByRole('button').first();

      const buttonText = (await button.textContent())?.trim() || '';
      const disabled = await button.isDisabled();
      const publishCountBefore = summary.api_status_evidence.synthetic_publish.length;

      let attempted = false;
      if (!disabled && /publish/i.test(buttonText)) {
        attempted = true;
        await button.click();
        await delay(1500);
      }

      const matched = summary.api_status_evidence.synthetic_publish
        .slice(publishCountBefore)
        .filter((e) => String(e.url || '').includes(endpointFragment));
      const latest = matched.at(-1) || null;

      summary.publish[outKey] = {
        artifact_label: artifactLabel,
        button_text: buttonText,
        button_disabled: disabled,
        attempted,
        state: disabled ? 'blocked' : 'enabled',
        api_status: latest?.status ?? null,
        api_url: latest?.url ?? null,
        api_response: latest?.response ?? null,
      };

      summary.checkpoints[`${outKey}_publish_shot`] = await screenshot(shotName);
    };

    await handlePublishAttempt({
      artifactLabel: 'Eval Dataset',
      endpointFragment: '/publish/eval_dataset',
      outKey: 'eval_dataset',
      shotName: '05_publish_eval_dataset_attempt',
    });

    await handlePublishAttempt({
      artifactLabel: 'Triplets',
      endpointFragment: '/publish/triplets',
      outKey: 'triplets',
      shotName: '06_publish_triplets_attempt',
    });

    summary.furthest_checkpoint = '7_publish_verified';

    // 8) Quick actions routing checks
    const verifyQuickAction = async ({
      fromSubtab,
      context,
      buttonName,
      expectedRecipe,
      shotName,
    }) => {
      await page.goto(`${UI_BASE}/rag?subtab=${encodeURIComponent(fromSubtab)}&corpus=${encodeURIComponent(CORPUS_ID)}`, {
        waitUntil: 'domcontentloaded',
      });
      await page.waitForLoadState('domcontentloaded');

      const actionBtn = page.getByRole('button', { name: buttonName }).first();
      await actionBtn.waitFor({ state: 'visible' });

      const startBefore = summary.api_status_evidence.synthetic_start.length;
      await actionBtn.click();
      await page.waitForURL((u) => u.toString().includes('subtab=synthetic'), { timeout: 15000 });
      await delay(1000);

      const currentUrl = page.url();
      const params = safeUrlParams(currentUrl);
      const startAfter = summary.api_status_evidence.synthetic_start.length;
      const autoRunTriggered = startAfter > startBefore;

      const actualRecipe = params.get('synthetic_recipe');
      const record = {
        context,
        from_subtab: fromSubtab,
        action_button: buttonName,
        url: currentUrl,
        query_context: params.get('synthetic_context'),
        query_recipe: actualRecipe,
        query_autorun: params.get('synthetic_autorun'),
        context_ok: params.get('synthetic_context') === context,
        recipe_ok: expectedRecipe ? actualRecipe === expectedRecipe : !actualRecipe,
        autorun_ok: params.get('synthetic_autorun') === '0',
        synthetic_start_count_before: startBefore,
        synthetic_start_count_after: startAfter,
        auto_run_triggered: autoRunTriggered,
        screenshot: await screenshot(shotName),
      };
      summary.quick_actions.push(record);
    };

    await verifyQuickAction({
      fromSubtab: 'retrieval',
      context: 'retrieval',
      buttonName: 'Retrieval Eval Set',
      expectedRecipe: 'eval_dataset',
      shotName: '07_quick_action_retrieval_to_synthetic',
    });

    await verifyQuickAction({
      fromSubtab: 'learning-agent',
      context: 'learning-agent',
      buttonName: 'Agent Eval Set',
      expectedRecipe: 'eval_dataset',
      shotName: '08_quick_action_learning_agent_to_synthetic',
    });

    await verifyQuickAction({
      fromSubtab: 'learning-ranker',
      context: 'learning-ranker',
      buttonName: 'Synthetic Triplets',
      expectedRecipe: 'triplets',
      shotName: '09_quick_action_learning_ranker_to_synthetic',
    });

    summary.furthest_checkpoint = '8_quick_actions_verified';

    // 9) System Prompts subtab: Synthetic Judge prompt exists and editable
    await page.goto(`${UI_BASE}/eval?subtab=prompts&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded');
    await page.getByText('System Prompts').first().waitFor({ state: 'visible' });

    const syntheticJudgeCard = page.locator('[id^="prompt-card-"]', { hasText: 'Synthetic Judge' }).first();
    const promptExists = (await syntheticJudgeCard.count()) > 0;
    let editable = false;
    let editButtonVisible = false;
    if (promptExists) {
      const editBtn = syntheticJudgeCard.getByRole('button', { name: 'Edit' }).first();
      editButtonVisible = (await editBtn.count()) > 0;
      editable = editButtonVisible ? await editBtn.isEnabled() : false;
      await syntheticJudgeCard.scrollIntoViewIfNeeded();
    }

    summary.system_prompts = {
      synthetic_judge_prompt_exists: promptExists,
      synthetic_judge_edit_button_visible: editButtonVisible,
      synthetic_judge_editable: editable,
      screenshot: await screenshot('10_system_prompts_synthetic_judge'),
    };
    summary.furthest_checkpoint = '9_system_prompts_verified';

    // 10) Run/compare evals and capture evidence
    await page.goto(`${UI_BASE}/eval?subtab=analysis&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded');

    const runSettingsToggle = page.getByRole('button', { name: /Run Settings/i }).first();
    const sampleSizeSelect = page.locator('#eval-run-settings-sample-size').first();
    if (await runSettingsToggle.count()) {
      const expanded = await runSettingsToggle.getAttribute('aria-expanded');
      if (expanded !== 'true') {
        await runSettingsToggle.click();
      }
    }
    await sampleSizeSelect.waitFor({ state: 'visible' });
    await sampleSizeSelect.selectOption('50');

    const evalRunsBefore = await listEvalRuns();
    const evalBeforeSet = new Set(evalRunsBefore.map((r) => String(r.run_id || '')));

    const runEvalBtn = page.getByRole('button', { name: /Run Eval/i }).first();
    await runEvalBtn.waitFor({ state: 'visible' });
    await runEvalBtn.click();

    let newEvalRunId = null;
    try {
      newEvalRunId = await waitUntil(async () => {
        const runs = await listEvalRuns();
        const fresh = runs.find((r) => !evalBeforeSet.has(String(r.run_id || '')));
        return fresh ? String(fresh.run_id || '') : null;
      }, {
        timeoutMs: 30 * 60 * 1000,
        intervalMs: 5000,
        description: 'new eval run after Run Eval',
      });
    } catch (err) {
      summary.instability_notes.push(`Could not confirm newly created eval run id via API: ${String(err)}`);
    }

    await waitUntil(async () => {
      try {
        return !(await runEvalBtn.isDisabled());
      } catch {
        return false;
      }
    }, {
      timeoutMs: 10 * 60 * 1000,
      intervalMs: 2000,
      description: 'Run Eval button to re-enable',
    }).catch((err) => {
      summary.instability_notes.push(`Run Eval button did not visibly re-enable in expected window: ${String(err)}`);
    });

    const primarySelect = page
      .locator('label:has-text("Primary Run (AFTER)")')
      .locator('xpath=following::select[1]')
      .first();

    const compareSelect = page
      .locator('label:has-text("Compare With (BEFORE)")')
      .locator('xpath=following::select[1]')
      .first();

    await primarySelect.waitFor({ state: 'visible' });
    await compareSelect.waitFor({ state: 'visible' });

    const primaryRunId = (await primarySelect.inputValue()).trim();
    const compareRunIdRaw = (await compareSelect.inputValue()).trim();
    const compareRunId = compareRunIdRaw || null;

    const primaryRunLabel = ((await primarySelect.locator('option:checked').textContent()) || '').trim();
    const compareRunLabel = compareRunId
      ? ((await compareSelect.locator('option:checked').textContent()) || '').trim()
      : null;

    const primaryRunResults = primaryRunId ? await getEvalResults(primaryRunId) : null;
    const compareRunResults = compareRunId ? await getEvalResults(compareRunId) : null;

    summary.eval_run_id = newEvalRunId || primaryRunId || null;
    summary.eval_run_ids = [newEvalRunId, primaryRunId, compareRunId].filter(Boolean);

    summary.eval_compare = {
      new_eval_run_id: newEvalRunId,
      primary_run_id: primaryRunId || null,
      compare_run_id: compareRunId,
      primary_run_label: primaryRunLabel || null,
      compare_run_label: compareRunLabel,
      primary_metrics: primaryRunResults
        ? {
            top1: primaryRunResults.top1_accuracy ?? null,
            topk: primaryRunResults.topk_accuracy ?? null,
            mrr: primaryRunResults.metrics?.mrr ?? null,
            sample: primaryRunResults.total ?? null,
          }
        : null,
      compare_metrics: compareRunResults
        ? {
            top1: compareRunResults.top1_accuracy ?? null,
            topk: compareRunResults.topk_accuracy ?? null,
            mrr: compareRunResults.metrics?.mrr ?? null,
            sample: compareRunResults.total ?? null,
          }
        : null,
      screenshot: await screenshot('11_eval_run_compare_evidence'),
    };

    summary.furthest_checkpoint = '10_eval_compare_verified';

    // Required flat top-level publish status fields
    summary.publish_eval_dataset_status = summary.publish.eval_dataset.state || null;
    summary.publish_triplets_status = summary.publish.triplets.state || null;

    if (!summary.run_ids.includes(summary.run_id) && summary.run_id) {
      summary.run_ids.unshift(summary.run_id);
    }

    // Required quick-action URL evidence map
    summary.quick_action_url_evidence = Object.fromEntries(
      summary.quick_actions.map((q) => [q.context, q.url])
    );

    summary.completed = true;
  } catch (err) {
    summary.completed = false;
    summary.errors.push(String(err));
    if (!summary.blocker) {
      summary.blocker = String(err);
    }
  } finally {
    await context.close();
    await fs.writeFile(SUMMARY_PATH, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  }
}

main().catch(async (err) => {
  summary.completed = false;
  summary.errors.push(String(err));
  summary.blocker = summary.blocker || String(err);
  await fs.writeFile(SUMMARY_PATH, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');
  process.exitCode = 1;
});
