import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const BASE_UI = 'http://127.0.0.1:5173/web';
const BASE_API = 'http://127.0.0.1:8012/api';
const CORPUS = 'epstein-files-1';
const OUT_DIR = path.resolve('tmp/ui-evidence-20260228');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function ensureDir(p) {
  await fs.mkdir(p, { recursive: true });
}

async function api(pathname, init = {}) {
  const res = await fetch(`${BASE_API}${pathname}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
    ...init,
  });
  const text = await res.text();
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  return { status: res.status, ok: res.ok, body };
}

async function poll(fn, { timeoutMs = 300000, intervalMs = 2000, label = 'poll' } = {}) {
  const start = Date.now();
  let lastError = null;
  while (Date.now() - start < timeoutMs) {
    try {
      const value = await fn();
      if (value) return value;
    } catch (err) {
      lastError = err;
    }
    await sleep(intervalMs);
  }
  if (lastError) {
    throw new Error(`Timeout waiting for ${label} after ${timeoutMs}ms (last error: ${lastError.message || String(lastError)})`);
  }
  throw new Error(`Timeout waiting for ${label} after ${timeoutMs}ms`);
}

async function firstModelValue(selectLocator) {
  return await selectLocator.evaluate((el) => {
    const select = /** @type {HTMLSelectElement} */ (el);
    const opts = Array.from(select.options).map((o) => String(o.value || '').trim());
    const found = opts.find((v) => v && v !== '__custom__');
    return found || '';
  });
}

async function main() {
  await ensureDir(OUT_DIR);
  const checkpoints = [];
  const summary = {
    timestamp: new Date().toISOString(),
    corpus: CORPUS,
    ui_base: BASE_UI,
    api_base: BASE_API,
    synthetic: {},
    quick_actions: {},
    prompts: {},
    eval_compare: {},
    checkpoints,
  };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1680, height: 1100 } });
  const page = await context.newPage();

  try {
    // Reset synthetic model local state to prove disabled start state first.
    await page.goto(`${BASE_UI}/`, { waitUntil: 'domcontentloaded' });
    await page.evaluate((corpus) => {
      localStorage.removeItem('synthetic.generator_model');
      localStorage.removeItem('synthetic.judge_model');
      localStorage.setItem('tribrid_active_corpus', corpus);
    }, CORPUS);

    // Ensure no active synthetic run blocks starting a new run.
    const runListResp = await api(`/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS)}&limit=50`);
    const existingRuns = Array.isArray(runListResp.body?.runs) ? runListResp.body.runs : [];
    for (const run of existingRuns) {
      if (run?.status === 'running' || run?.status === 'queued') {
        await api(`/synthetic/run/${encodeURIComponent(run.run_id)}/cancel`, { method: 'POST' });
      }
    }

    // Synthetic Lab start
    await page.goto(`${BASE_UI}/rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-testid="synthetic-lab-subtab"]', { timeout: 60000 });

    const startRunButton = page.getByRole('button', { name: 'Start Run' });
    const startFullButton = page.getByRole('button', { name: 'Start Full Stack' });

    const startDisabledBefore = await startRunButton.isDisabled();
    const startFullDisabledBefore = await startFullButton.isDisabled();

    const shot01 = path.join(OUT_DIR, '01_synthetic_initial.png');
    await page.screenshot({ path: shot01, fullPage: true });
    checkpoints.push({ checkpoint: 'synthetic_initial_disabled', screenshot: shot01, startDisabledBefore, startFullDisabledBefore });

    const generatorSelect = page.locator('div.setting-row:has(label:has-text("Generator Model")) select').first();
    const judgeSelect = page.locator('div.setting-row:has(label:has-text("Judge Model")) select').first();
    await generatorSelect.waitFor({ state: 'visible', timeout: 60000 });
    await judgeSelect.waitFor({ state: 'visible', timeout: 60000 });

    const generatorModel = await firstModelValue(generatorSelect);
    const judgeModel = await firstModelValue(judgeSelect);
    if (!generatorModel || !judgeModel) {
      throw new Error(`Model picker did not expose valid options (generator='${generatorModel}', judge='${judgeModel}')`);
    }

    await generatorSelect.selectOption(generatorModel);
    await judgeSelect.selectOption(judgeModel);

    // Verify start unblocked after explicit model selection.
    await poll(async () => {
      const disabled = await startRunButton.isDisabled();
      return disabled ? null : true;
    }, { timeoutMs: 20000, intervalMs: 500, label: 'start button enabled after model selection' });

    const startDisabledAfter = await startRunButton.isDisabled();
    const startFullDisabledAfter = await startFullButton.isDisabled();

    const shot02 = path.join(OUT_DIR, '02_models_selected.png');
    await page.screenshot({ path: shot02, fullPage: true });
    checkpoints.push({
      checkpoint: 'models_selected_start_enabled',
      screenshot: shot02,
      generatorModel,
      judgeModel,
      startDisabledAfter,
      startFullDisabledAfter,
    });

    // Track existing run ids before launch.
    const beforeRunsResp = await api(`/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS)}&limit=50`);
    const beforeRuns = Array.isArray(beforeRunsResp.body?.runs) ? beforeRunsResp.body.runs : [];
    const beforeRunIds = new Set(beforeRuns.map((r) => String(r.run_id || '')));

    await startRunButton.click();

    const createdRunMeta = await poll(async () => {
      const resp = await api(`/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS)}&limit=50`);
      const runs = Array.isArray(resp.body?.runs) ? resp.body.runs : [];
      return runs.find((r) => !beforeRunIds.has(String(r.run_id || ''))) || null;
    }, { timeoutMs: 120000, intervalMs: 2000, label: 'new synthetic run id' });

    const runId = String(createdRunMeta.run_id);

    // Wait for terminal run status.
    const finalRun = await poll(async () => {
      const resp = await api(`/synthetic/run/${encodeURIComponent(runId)}`);
      const run = resp.body;
      if (!run || !run.status) return null;
      if (['completed', 'failed', 'cancelled'].includes(run.status)) return run;
      return null;
    }, { timeoutMs: 45 * 60 * 1000, intervalMs: 5000, label: 'synthetic run completion' });

    // Refresh UI to ensure latest run details visible.
    await page.goto(`${BASE_UI}/rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-testid="synthetic-lab-subtab"]', { timeout: 60000 });
    await page.locator('tr', { hasText: runId }).first().click({ timeout: 15000 });
    await page.waitForTimeout(1000);

    const shot03 = path.join(OUT_DIR, '03_run_completed.png');
    await page.screenshot({ path: shot03, fullPage: true });
    checkpoints.push({ checkpoint: 'synthetic_run_completed', screenshot: shot03, runId, status: finalRun.status });

    const qualityArtifact = (Array.isArray(finalRun.artifacts) ? finalRun.artifacts : []).find((a) => a.kind === 'quality_eval_json');
    let qualityEvalJson = null;
    if (qualityArtifact?.path) {
      try {
        const raw = await fs.readFile(String(qualityArtifact.path), 'utf-8');
        qualityEvalJson = JSON.parse(raw);
      } catch {
        qualityEvalJson = null;
      }
    }

    // UI publish button states
    const evalPublishButton = page.locator('xpath=//div[./span[normalize-space()="Eval Dataset"]]//button[contains(@class,"small-button")]').first();
    const tripletsPublishButton = page.locator('xpath=//div[./span[normalize-space()="Triplets"]]//button[contains(@class,"small-button")]').first();

    const evalPublishVisible = await evalPublishButton.isVisible().catch(() => false);
    const tripletsPublishVisible = await tripletsPublishButton.isVisible().catch(() => false);

    const evalPublishDisabled = evalPublishVisible ? await evalPublishButton.isDisabled() : null;
    const tripletsPublishDisabled = tripletsPublishVisible ? await tripletsPublishButton.isDisabled() : null;
    const evalPublishLabel = evalPublishVisible ? (await evalPublishButton.textContent())?.trim() : null;
    const tripletsPublishLabel = tripletsPublishVisible ? (await tripletsPublishButton.textContent())?.trim() : null;

    const shot04 = path.join(OUT_DIR, '04_publish_state.png');
    await page.screenshot({ path: shot04, fullPage: true });
    checkpoints.push({
      checkpoint: 'publish_buttons_state',
      screenshot: shot04,
      evalPublishVisible,
      tripletsPublishVisible,
      evalPublishDisabled,
      tripletsPublishDisabled,
      evalPublishLabel,
      tripletsPublishLabel,
    });

    // API publish behavior proof.
    const publishEvalResp = await api(`/synthetic/run/${encodeURIComponent(runId)}/publish/eval_dataset`, { method: 'POST' });
    const publishTripletsResp = await api(`/synthetic/run/${encodeURIComponent(runId)}/publish/triplets`, { method: 'POST' });

    // Quick actions routing checks
    const latestRunBeforeQuickResp = await api(`/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS)}&limit=1`);
    const latestRunBeforeQuick = latestRunBeforeQuickResp.body?.runs?.[0]?.run_id || null;

    await page.goto(`${BASE_UI}/rag?subtab=retrieval&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Retrieval Eval Set' }).click();
    await page.waitForTimeout(600);
    const urlRetrievalQuick = page.url();
    const shot05 = path.join(OUT_DIR, '05_quick_action_retrieval.png');
    await page.screenshot({ path: shot05, fullPage: true });

    await page.goto(`${BASE_UI}/rag?subtab=learning-agent&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Open Synthetic Lab' }).first().click();
    await page.waitForTimeout(600);
    const urlAgentQuick = page.url();
    const shot06 = path.join(OUT_DIR, '06_quick_action_learning_agent.png');
    await page.screenshot({ path: shot06, fullPage: true });

    await page.goto(`${BASE_UI}/rag?subtab=learning-ranker&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('button', { name: 'Open Synthetic Lab' }).first().click();
    await page.waitForTimeout(600);
    const urlRankerQuick = page.url();
    const shot07 = path.join(OUT_DIR, '07_quick_action_learning_ranker.png');
    await page.screenshot({ path: shot07, fullPage: true });

    const latestRunAfterQuickResp = await api(`/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS)}&limit=1`);
    const latestRunAfterQuick = latestRunAfterQuickResp.body?.runs?.[0]?.run_id || null;

    // System prompts synthetic judge card.
    await page.goto(`${BASE_UI}/eval?subtab=prompts&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.getByText('Synthetic Judge').first().waitFor({ timeout: 60000 });
    const syntheticJudgeCard = page.locator('div', { hasText: 'Synthetic Judge' }).first();
    const editButton = syntheticJudgeCard.getByRole('button', { name: /Edit/i }).first();
    const editableVisible = await editButton.isVisible().catch(() => false);
    if (editableVisible) {
      await editButton.click();
      await page.waitForTimeout(500);
    }
    const shot08 = path.join(OUT_DIR, '08_system_prompts_synthetic_judge.png');
    await page.screenshot({ path: shot08, fullPage: true });

    // Eval comparison evidence: run one eval via UI then compare with previous run.
    await page.goto(`${BASE_UI}/eval?subtab=analysis&corpus=${encodeURIComponent(CORPUS)}`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);

    const evalRunsBeforeResp = await api(`/eval/runs?corpus_id=${encodeURIComponent(CORPUS)}`);
    const evalRunsBefore = Array.isArray(evalRunsBeforeResp.body?.runs) ? evalRunsBeforeResp.body.runs : [];
    const evalBeforeIds = new Set(evalRunsBefore.map((r) => String(r.run_id || '')));

    const runEvalButton = page.locator('button[title="Run a new evaluation and see live logs"]').first();
    await runEvalButton.click();

    const newEvalMeta = await poll(async () => {
      const resp = await api(`/eval/runs?corpus_id=${encodeURIComponent(CORPUS)}`);
      const runs = Array.isArray(resp.body?.runs) ? resp.body.runs : [];
      return runs.find((r) => !evalBeforeIds.has(String(r.run_id || ''))) || null;
    }, { timeoutMs: 30 * 60 * 1000, intervalMs: 5000, label: 'new eval run id' });

    const primaryEvalRunId = String(newEvalMeta.run_id);
    const evalRunsAfterResp = await api(`/eval/runs?corpus_id=${encodeURIComponent(CORPUS)}`);
    const evalRunsAfter = Array.isArray(evalRunsAfterResp.body?.runs) ? evalRunsAfterResp.body.runs : [];
    const compareEvalRunId = String((evalRunsAfter.find((r) => String(r.run_id) !== primaryEvalRunId)?.run_id) || '');

    // Use selectors order: first is primary, second is compare.
    const analysisSelects = page.locator('select').filter({ has: page.locator('option') });
    await analysisSelects.nth(0).selectOption(primaryEvalRunId);
    if (compareEvalRunId) {
      await analysisSelects.nth(1).selectOption(compareEvalRunId);
    }

    await page.waitForTimeout(1200);
    const shot09 = path.join(OUT_DIR, '09_eval_compare.png');
    await page.screenshot({ path: shot09, fullPage: true });

    const primaryEvalRunResp = await api(`/eval/runs/${encodeURIComponent(primaryEvalRunId)}`);
    const compareEvalRunResp = compareEvalRunId
      ? await api(`/eval/runs/${encodeURIComponent(compareEvalRunId)}`)
      : { status: null, ok: false, body: null };

    summary.synthetic = {
      run_id: runId,
      status: finalRun.status,
      error: finalRun.error || null,
      summary: {
        quality_top1_accuracy: finalRun.summary?.quality_top1_accuracy ?? null,
        quality_topk_accuracy: finalRun.summary?.quality_topk_accuracy ?? null,
        quality_mrr: finalRun.summary?.quality_mrr ?? null,
        quality_sample_size: finalRun.summary?.quality_sample_size ?? null,
        quality_gate_threshold: finalRun.summary?.quality_gate_threshold ?? null,
        quality_gate_passed: finalRun.summary?.quality_gate_passed ?? null,
        quality_failure_reason: finalRun.summary?.quality_failure_reason ?? null,
      },
      quality_eval_json_artifact_path: qualityArtifact?.path || null,
      quality_eval_json: qualityEvalJson,
      publish_api: {
        eval_dataset: { status: publishEvalResp.status, ok: publishEvalResp.ok, body: publishEvalResp.body },
        triplets: { status: publishTripletsResp.status, ok: publishTripletsResp.ok, body: publishTripletsResp.body },
      },
      publish_ui: {
        eval_button_label: evalPublishLabel,
        eval_button_disabled: evalPublishDisabled,
        triplets_button_label: tripletsPublishLabel,
        triplets_button_disabled: tripletsPublishDisabled,
      },
    };

    summary.quick_actions = {
      retrieval: {
        url_after_click: urlRetrievalQuick,
        expected_context: 'synthetic_context=retrieval',
        expected_recipe: 'synthetic_recipe=eval_dataset',
      },
      learning_agent: {
        url_after_click: urlAgentQuick,
        expected_context: 'synthetic_context=learning-agent',
      },
      learning_ranker: {
        url_after_click: urlRankerQuick,
        expected_context: 'synthetic_context=learning-ranker',
      },
      latest_run_before: latestRunBeforeQuick,
      latest_run_after: latestRunAfterQuick,
      no_autorun_new_run_created: latestRunBeforeQuick === latestRunAfterQuick,
    };

    summary.prompts = {
      synthetic_judge_visible: true,
      synthetic_judge_edit_button_visible: editableVisible,
      screenshot: shot08,
    };

    summary.eval_compare = {
      primary_eval_run_id: primaryEvalRunId,
      compare_eval_run_id: compareEvalRunId || null,
      primary_metrics: primaryEvalRunResp.body
        ? {
            top1_accuracy: primaryEvalRunResp.body.top1_accuracy,
            topk_accuracy: primaryEvalRunResp.body.topk_accuracy,
            mrr: primaryEvalRunResp.body.metrics?.mrr,
            total: primaryEvalRunResp.body.total,
          }
        : null,
      compare_metrics: compareEvalRunResp.body
        ? {
            top1_accuracy: compareEvalRunResp.body.top1_accuracy,
            topk_accuracy: compareEvalRunResp.body.topk_accuracy,
            mrr: compareEvalRunResp.body.metrics?.mrr,
            total: compareEvalRunResp.body.total,
          }
        : null,
      screenshot: shot09,
    };

    checkpoints.push({ checkpoint: 'quick_actions_routing', screenshots: [shot05, shot06, shot07] });
    checkpoints.push({ checkpoint: 'system_prompts_synthetic_judge', screenshot: shot08 });
    checkpoints.push({ checkpoint: 'eval_compare', screenshot: shot09, primaryEvalRunId, compareEvalRunId });

    const summaryPath = path.join(OUT_DIR, 'ui_acceptance_summary.json');
    await fs.writeFile(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf-8');

    console.log(JSON.stringify({ ok: true, summaryPath, summary }, null, 2));
  } finally {
    await context.close();
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
