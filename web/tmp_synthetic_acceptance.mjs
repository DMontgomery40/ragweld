import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, request as playwrightRequest } from 'playwright';

const corpusId = process.env.CORPUS_ID || 'epstein-files-1';
const uiBase = (process.env.UI_BASE || 'http://127.0.0.1:5174/web').replace(/\/$/, '');
const apiBase = (process.env.API_BASE || 'http://127.0.0.1:8000/api').replace(/\/$/, '');

const stamp = new Date().toISOString().replace(/[:.]/g, '').replace('T', '_').slice(0, 15);
const outDir = path.resolve('tmp', `synthetic_acceptance_${stamp}`);
await fs.mkdir(outDir, { recursive: true });

const summary = {
  started_at: new Date().toISOString(),
  corpus_id: corpusId,
  ui_base: uiBase,
  api_base: apiBase,
  synthetic: {},
  quick_actions: {},
  system_prompts: {},
  eval: {},
  screenshots: [],
  checkpoints: [],
  errors: [],
};

let shotCounter = 0;
let page;

function checkpoint(name, details = {}) {
  summary.checkpoints.push({
    name,
    at: new Date().toISOString(),
    ...details,
  });
}

async function screenshot(name) {
  shotCounter += 1;
  const file = path.join(outDir, `${String(shotCounter).padStart(2, '0')}_${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  summary.screenshots.push(file);
  return file;
}

function unwrapJsonOrText(status, body) {
  if (typeof body === 'object' && body !== null) return body;
  return { status, body: String(body) };
}

async function apiCall(api, method, pathName, body) {
  const resp = await api.fetch(`${apiBase}${pathName}`, {
    method,
    data: body,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
  });
  const status = resp.status();
  let parsed;
  try {
    parsed = await resp.json();
  } catch {
    parsed = await resp.text();
  }
  return { status, body: parsed };
}

async function listSyntheticRuns(api) {
  const { status, body } = await apiCall(api, 'GET', `/synthetic/runs?corpus_id=${encodeURIComponent(corpusId)}&limit=200`);
  if (status !== 200) throw new Error(`listSyntheticRuns failed: ${status}`);
  return Array.isArray(body?.runs) ? body.runs : [];
}

async function getSyntheticRun(api, runId) {
  const { status, body } = await apiCall(api, 'GET', `/synthetic/run/${encodeURIComponent(runId)}`);
  if (status !== 200) throw new Error(`getSyntheticRun failed: ${runId} status=${status}`);
  return body;
}

async function listEvalRuns(api) {
  const { status, body } = await apiCall(api, 'GET', `/eval/runs?corpus_id=${encodeURIComponent(corpusId)}&limit=200`);
  if (status !== 200) throw new Error(`listEvalRuns failed: ${status}`);
  return Array.isArray(body?.runs) ? body.runs : [];
}

async function getEvalRun(api, runId) {
  const { status, body } = await apiCall(api, 'GET', `/eval/run/${encodeURIComponent(runId)}`);
  if (status !== 200) throw new Error(`getEvalRun failed: ${runId} status=${status}`);
  return body;
}

async function waitForNewSyntheticRun(api, beforeIds, timeoutMs = 120000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const runs = await listSyntheticRuns(api);
    const newer = runs.find((r) => !beforeIds.has(r.run_id));
    if (newer) return newer.run_id;
    await page.waitForTimeout(2000);
  }
  throw new Error('Timed out waiting for new synthetic run id');
}

async function waitForSyntheticCompletion(api, runId, timeoutMs = 20 * 60 * 1000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const run = await getSyntheticRun(api, runId);
    if (['completed', 'failed', 'cancelled'].includes(String(run.status))) return run;
    await page.waitForTimeout(5000);
  }
  throw new Error(`Timed out waiting for synthetic completion: ${runId}`);
}

async function waitForNewEvalRun(api, beforeIds, timeoutMs = 20 * 60 * 1000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const runs = await listEvalRuns(api);
    const newer = runs.find((r) => !beforeIds.has(r.run_id));
    if (newer) return newer.run_id;
    await page.waitForTimeout(3000);
  }
  throw new Error('Timed out waiting for new eval run id');
}

async function selectModel(labelText) {
  const row = page
    .locator('div.setting-row')
    .filter({ has: page.locator('label', { hasText: labelText }) })
    .first();
  await row.waitFor({ state: 'visible', timeout: 60000 });
  const select = row.locator('select').first();
  await select.waitFor({ state: 'visible', timeout: 60000 });
  const options = await select.locator('option').evaluateAll((opts) =>
    opts.map((o) => ({ value: o.getAttribute('value') || '', text: (o.textContent || '').trim() }))
  );
  const preferred = options.find((o) => o.value.includes('gpt-4o-mini'));
  const fallback = options.find((o) => o.value && o.value !== '__custom__');
  const picked = preferred || fallback;
  if (!picked) {
    throw new Error(`No selectable option found for ${labelText}`);
  }
  await select.selectOption(picked.value);
  return picked;
}

async function gatherArtifactPublishUiState() {
  return await page.evaluate(() => {
    const out = { eval_dataset: null, triplets: null };
    const panel = document.querySelector('[data-testid="synthetic-lab-subtab"]');
    if (!panel) return out;

    const labels = ['Eval Dataset', 'Triplets'];
    for (const label of labels) {
      const span = Array.from(panel.querySelectorAll('span')).find((s) => (s.textContent || '').trim() === label);
      if (!span) continue;
      const row = span.closest('div');
      if (!row) continue;
      const button = row.querySelector('button');
      const key = label === 'Eval Dataset' ? 'eval_dataset' : 'triplets';
      out[key] = {
        label,
        button_text: button?.textContent?.trim() || null,
        disabled: button ? button.disabled : null,
        row_text: row.textContent?.trim() || null,
      };
    }
    return out;
  });
}

async function verifyQuickAction(api, cfg) {
  const beforeCount = (await listSyntheticRuns(api)).length;
  await page.goto(`${uiBase}${cfg.path}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2000);
  await page.getByRole('button', { name: cfg.buttonName }).first().click();
  await page.waitForTimeout(1500);
  const url = new URL(page.url());
  const afterCount = (await listSyntheticRuns(api)).length;
  const result = {
    url: page.url(),
    subtab: url.searchParams.get('subtab'),
    synthetic_context: url.searchParams.get('synthetic_context'),
    synthetic_recipe: url.searchParams.get('synthetic_recipe'),
    synthetic_autorun: url.searchParams.get('synthetic_autorun'),
    run_count_before: beforeCount,
    run_count_after: afterCount,
    auto_run_triggered: afterCount > beforeCount,
  };
  checkpoint(`quick_action_${cfg.name}`, result);
  await screenshot(`quick_action_${cfg.name}`);
  return result;
}

const api = await playwrightRequest.newContext({ timeout: 60000 });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });

await context.addInitScript(
  ({ corpus }) => {
    localStorage.setItem('tribrid_active_corpus', corpus);
    localStorage.setItem('tribrid_active_repo', corpus);
    localStorage.removeItem('synthetic.generator_model');
    localStorage.removeItem('synthetic.judge_model');
  },
  { corpus: corpusId }
);

page = await context.newPage();

try {
  checkpoint('open_synthetic_lab_start');
  await page.goto(`${uiBase}/rag?subtab=synthetic&corpus=${encodeURIComponent(corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('[data-testid="synthetic-lab-subtab"]', { timeout: 60000 });
  await page.waitForTimeout(1500);

  const startRunBtn = page.getByRole('button', { name: 'Start Run' });
  const startFullBtn = page.getByRole('button', { name: 'Start Full Stack' });
  const disabledBefore = {
    start_run_disabled: await startRunBtn.isDisabled(),
    start_full_stack_disabled: await startFullBtn.isDisabled(),
  };
  summary.synthetic.start_buttons_before_models = disabledBefore;
  checkpoint('start_buttons_before_models', disabledBefore);
  await screenshot('synthetic_before_model_selection');

  const generatorModel = await selectModel('Generator Model');
  const judgeModel = await selectModel('Judge Model');
  await page.waitForTimeout(1000);

  const enabledAfter = {
    start_run_disabled: await startRunBtn.isDisabled(),
    start_full_stack_disabled: await startFullBtn.isDisabled(),
  };
  summary.synthetic.model_selection = {
    generator_model: generatorModel,
    judge_model: judgeModel,
    buttons_after_selection: enabledAfter,
  };
  checkpoint('models_selected', summary.synthetic.model_selection);
  await screenshot('synthetic_after_model_selection');

  const beforeRuns = await listSyntheticRuns(api);
  const beforeIds = new Set(beforeRuns.map((r) => r.run_id));
  summary.synthetic.run_count_before_start = beforeRuns.length;

  await startRunBtn.click();
  checkpoint('synthetic_start_clicked');

  const runId = await waitForNewSyntheticRun(api, beforeIds, 180000);
  summary.synthetic.run_id = runId;
  checkpoint('synthetic_run_detected', { run_id: runId });

  const completedRun = await waitForSyntheticCompletion(api, runId);
  const artifacts = Array.isArray(completedRun?.artifacts) ? completedRun.artifacts : [];
  const summaryData = completedRun?.summary || {};

  summary.synthetic.final = {
    run_id: runId,
    status: completedRun.status,
    error: completedRun.error || null,
    quality_gate_passed: summaryData.quality_gate_passed,
    quality_failure_reason: summaryData.quality_failure_reason || null,
    quality_gate_threshold: summaryData.quality_gate_threshold,
    quality_top1_accuracy: summaryData.quality_top1_accuracy,
    quality_topk_accuracy: summaryData.quality_topk_accuracy,
    quality_mrr: summaryData.quality_mrr,
    quality_sample_size: summaryData.quality_sample_size,
    has_quality_eval_artifact: artifacts.some((a) => a.kind === 'quality_eval_json'),
    artifact_kinds: artifacts.map((a) => a.kind),
  };
  checkpoint('synthetic_run_completed', summary.synthetic.final);

  await page.goto(`${uiBase}/rag?subtab=synthetic&corpus=${encodeURIComponent(corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('[data-testid="synthetic-lab-subtab"]', { timeout: 60000 });
  const row = page.locator('table tbody tr').filter({ hasText: runId }).first();
  if (await row.count()) {
    await row.click();
    await page.waitForTimeout(1200);
  }
  const qualityPanelText = await page
    .locator('[data-testid="synthetic-lab-subtab"] .studio-callout')
    .filter({ hasText: 'Quality Gate' })
    .first()
    .innerText();
  summary.synthetic.quality_panel_text = qualityPanelText;
  summary.synthetic.publish_ui_state = await gatherArtifactPublishUiState();
  checkpoint('synthetic_ui_quality_publish_state', {
    quality_panel_text: qualityPanelText,
    publish_ui_state: summary.synthetic.publish_ui_state,
  });
  await screenshot('synthetic_completed_quality_publish');

  const pubEval = await apiCall(api, 'POST', `/synthetic/run/${encodeURIComponent(runId)}/publish/eval_dataset`);
  const pubTriplets = await apiCall(api, 'POST', `/synthetic/run/${encodeURIComponent(runId)}/publish/triplets`);
  summary.synthetic.publish_api = {
    eval_dataset: { status: pubEval.status, body: unwrapJsonOrText(pubEval.status, pubEval.body) },
    triplets: { status: pubTriplets.status, body: unwrapJsonOrText(pubTriplets.status, pubTriplets.body) },
  };
  checkpoint('synthetic_publish_api_checked', summary.synthetic.publish_api);

  summary.quick_actions.retrieval = await verifyQuickAction(api, {
    name: 'retrieval',
    path: `/rag?subtab=retrieval&corpus=${encodeURIComponent(corpusId)}`,
    buttonName: 'Retrieval Eval Set',
  });

  summary.quick_actions.learning_agent = await verifyQuickAction(api, {
    name: 'learning_agent',
    path: `/rag?subtab=learning-agent&corpus=${encodeURIComponent(corpusId)}`,
    buttonName: 'Open Synthetic Lab',
  });

  summary.quick_actions.learning_ranker = await verifyQuickAction(api, {
    name: 'learning_ranker',
    path: `/rag?subtab=learning-ranker&corpus=${encodeURIComponent(corpusId)}`,
    buttonName: 'Open Synthetic Lab',
  });

  await page.goto(`${uiBase}/eval?subtab=prompts&corpus=${encodeURIComponent(corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('#prompt-card-synthetic_judge', { timeout: 60000 });
  const syntheticJudgeCard = page.locator('#prompt-card-synthetic_judge');
  const judgeExists = (await syntheticJudgeCard.count()) > 0;
  await syntheticJudgeCard.getByRole('button', { name: 'Edit' }).click();
  await page.waitForTimeout(500);
  const textareaVisible = (await syntheticJudgeCard.locator('textarea').count()) > 0;
  await syntheticJudgeCard.getByRole('button', { name: 'Cancel' }).click();
  await page.waitForTimeout(300);
  summary.system_prompts = {
    synthetic_judge_card_exists: judgeExists,
    synthetic_judge_editable: textareaVisible,
  };
  checkpoint('system_prompts_synthetic_judge', summary.system_prompts);
  await screenshot('system_prompts_synthetic_judge');

  await page.goto(`${uiBase}/eval?subtab=analysis&corpus=${encodeURIComponent(corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForTimeout(2500);

  const sampleInput = page.locator('#eval-run-settings-sample-size');
  if (await sampleInput.count()) {
    await sampleInput.fill('50');
    checkpoint('eval_sample_size_set', { sample_size: 50 });
  }

  const runEvalButton = page.locator('button[title="Run a new evaluation and see live logs"]');

  const evalBefore = await listEvalRuns(api);
  const evalBeforeIds = new Set(evalBefore.map((r) => r.run_id));
  await runEvalButton.click();
  const evalRunId1 = await waitForNewEvalRun(api, evalBeforeIds, 20 * 60 * 1000);
  const evalRun1 = await getEvalRun(api, evalRunId1);
  checkpoint('eval_run_1_completed', { run_id: evalRunId1, top1: evalRun1.top1_accuracy, topk: evalRun1.topk_accuracy, mrr: evalRun1.metrics?.mrr, total: evalRun1.total });

  const evalAfterFirst = await listEvalRuns(api);
  const evalAfterFirstIds = new Set(evalAfterFirst.map((r) => r.run_id));
  await page.waitForTimeout(1500);
  await runEvalButton.click();
  const evalRunId2 = await waitForNewEvalRun(api, evalAfterFirstIds, 20 * 60 * 1000);
  const evalRun2 = await getEvalRun(api, evalRunId2);
  checkpoint('eval_run_2_completed', { run_id: evalRunId2, top1: evalRun2.top1_accuracy, topk: evalRun2.topk_accuracy, mrr: evalRun2.metrics?.mrr, total: evalRun2.total });

  const selectorValues = await page.evaluate(() => {
    const out = { primary_run_id: null, compare_run_id: null };
    const labels = Array.from(document.querySelectorAll('label'));
    for (const label of labels) {
      const txt = (label.textContent || '').trim();
      if (txt.includes('Primary Run')) {
        const sel = label.parentElement?.querySelector('select');
        if (sel) out.primary_run_id = sel.value;
      }
      if (txt.includes('Compare With')) {
        const sel = label.parentElement?.querySelector('select');
        if (sel) out.compare_run_id = sel.value || null;
      }
    }
    return out;
  });

  summary.eval = {
    run_id_1: evalRunId1,
    run_id_2: evalRunId2,
    run_1_metrics: {
      top1: evalRun1.top1_accuracy,
      topk: evalRun1.topk_accuracy,
      mrr: evalRun1.metrics?.mrr,
      total: evalRun1.total,
    },
    run_2_metrics: {
      top1: evalRun2.top1_accuracy,
      topk: evalRun2.topk_accuracy,
      mrr: evalRun2.metrics?.mrr,
      total: evalRun2.total,
    },
    selector_values: selectorValues,
    delta: {
      top1: Number((evalRun2.top1_accuracy - evalRun1.top1_accuracy).toFixed(6)),
      topk: Number((evalRun2.topk_accuracy - evalRun1.topk_accuracy).toFixed(6)),
      mrr: Number(((evalRun2.metrics?.mrr || 0) - (evalRun1.metrics?.mrr || 0)).toFixed(6)),
    },
  };
  checkpoint('eval_comparison_ready', summary.eval);
  await screenshot('eval_comparison');

  summary.completed_at = new Date().toISOString();
  summary.acceptance_status = 'completed';
} catch (error) {
  const msg = error instanceof Error ? `${error.message}\n${error.stack || ''}` : String(error);
  summary.errors.push(msg);
  summary.completed_at = new Date().toISOString();
  summary.acceptance_status = 'failed';
  checkpoint('error', { message: msg });
  try {
    await screenshot('failure_state');
  } catch {
    // ignore
  }
} finally {
  await api.dispose();
  await context.close();
  await browser.close();

  const summaryPath = path.join(outDir, 'summary.json');
  await fs.writeFile(summaryPath, JSON.stringify(summary, null, 2), 'utf-8');
  console.log(JSON.stringify({ outDir, summaryPath, acceptance_status: summary.acceptance_status }, null, 2));
}
