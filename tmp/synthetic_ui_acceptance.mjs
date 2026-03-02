import fs from 'node:fs/promises';
import path from 'node:path';
import { chromium, request } from '@playwright/test';

const UI_BASE = process.env.UI_BASE || 'http://127.0.0.1:5173/web';
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8012/api';
const CORPUS_ID = process.env.CORPUS_ID || 'epstein-files-1';

const now = new Date();
const ts = `${now.getUTCFullYear()}${String(now.getUTCMonth() + 1).padStart(2, '0')}${String(now.getUTCDate()).padStart(2, '0')}_${String(now.getUTCHours()).padStart(2, '0')}${String(now.getUTCMinutes()).padStart(2, '0')}${String(now.getUTCSeconds()).padStart(2, '0')}`;
const outDir = path.resolve('output', `synthetic_ui_acceptance_${CORPUS_ID}_${ts}`);

function parseNumberAfter(label, text) {
  const rx = new RegExp(`${label}=([0-9]+(?:\\.[0-9]+)?)`);
  const m = text.match(rx);
  return m ? Number(m[1]) : null;
}

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeJson(p, obj) {
  await fs.writeFile(p, `${JSON.stringify(obj, null, 2)}\n`, 'utf-8');
}

async function waitForRunTerminal(api, runId, timeoutMs = 40 * 60 * 1000) {
  const started = Date.now();
  while (true) {
    const resp = await api.get(`${API_BASE}/synthetic/run/${encodeURIComponent(runId)}`);
    if (!resp.ok()) {
      throw new Error(`Failed to fetch synthetic run ${runId}: HTTP ${resp.status()}`);
    }
    const run = await resp.json();
    if (['completed', 'failed', 'cancelled'].includes(String(run.status || ''))) {
      return run;
    }
    if (Date.now() - started > timeoutMs) {
      throw new Error(`Timed out waiting for synthetic run ${runId} terminal status`);
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
}

async function listSyntheticRuns(api) {
  const resp = await api.get(`${API_BASE}/synthetic/runs?corpus_id=${encodeURIComponent(CORPUS_ID)}&limit=20`);
  if (!resp.ok()) throw new Error(`list synthetic runs failed: HTTP ${resp.status()}`);
  return await resp.json();
}

async function listEvalRuns(api) {
  const resp = await api.get(`${API_BASE}/eval/runs?corpus_id=${encodeURIComponent(CORPUS_ID)}`);
  if (!resp.ok()) throw new Error(`list eval runs failed: HTTP ${resp.status()}`);
  return await resp.json();
}

async function chooseModel(page, labelText) {
  const container = page.locator(`div.setting-row:has(label:has-text("${labelText}"))`).first();
  await container.waitFor({ state: 'visible', timeout: 20000 });
  const select = container.locator('select').first();
  await select.waitFor({ state: 'visible', timeout: 20000 });
  const options = await select.locator('option').evaluateAll((nodes) => nodes.map((n) => ({ value: String((n).value || ''), text: String(n.textContent || '').trim() })));
  const preferred = ['claude-3-haiku', 'claude-3.5-haiku', 'openai/gpt-4o-mini', 'openai/gpt-4.1-mini', 'openai/gpt-4o'];
  let chosen = preferred.find((p) => options.some((o) => o.value === p));
  if (!chosen) {
    const firstValid = options.find((o) => o.value && o.value !== '__custom__');
    chosen = firstValid?.value;
  }
  if (!chosen) {
    throw new Error(`No selectable model found for ${labelText}`);
  }
  await select.selectOption(chosen);
  return { chosen, optionsCount: options.length };
}

async function extractEvalSummaryCards(page) {
  // Read the first summary cards from EvalDrillDown.
  const cards = await page.locator('.eval-drill-down > div').first().locator('div').allInnerTexts();
  // Fallback parse from whole page text if structure drifts.
  const text = await page.locator('body').innerText();
  const top1 = /Top-1 Accuracy\s+([0-9]+(?:\.[0-9]+)?%)/m.exec(text)?.[1] || null;
  const topk = /Top-K Accuracy\s+([0-9]+(?:\.[0-9]+)?%)/m.exec(text)?.[1] || null;
  const mrr = /MRR\s+([0-9]+(?:\.[0-9]+)?)/m.exec(text)?.[1] || null;
  return { top1, topk, mrr, cardsPreview: cards.slice(0, 12) };
}

async function main() {
  await ensureDir(outDir);
  const summary = {
    started_at: new Date().toISOString(),
    ui_base: UI_BASE,
    api_base: API_BASE,
    corpus_id: CORPUS_ID,
    checkpoints: [],
    quick_actions: [],
    artifacts: {},
    synthetic: {},
    eval_compare: {},
    system_prompts: {},
    api_checks: {},
    screenshots: [],
    status: 'running',
  };

  const api = await request.newContext();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1680, height: 1100 } });
  const page = await context.newPage();

  const snap = async (name) => {
    const file = path.join(outDir, `${String(summary.screenshots.length + 1).padStart(2, '0')}_${name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    summary.screenshots.push(file);
    return file;
  };

  try {
    // Ensure deterministic state for explicit model selection checks.
    await page.goto(`${UI_BASE}/rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.evaluate((corpus) => {
      localStorage.setItem('tribrid_active_corpus', corpus);
      localStorage.removeItem('synthetic.generator_model');
      localStorage.removeItem('synthetic.judge_model');
    }, CORPUS_ID);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.getByText('Synthetic Lab').first().waitFor({ timeout: 20000 });

    const startRunBtn = page.getByRole('button', { name: 'Start Run' }).first();
    const startFullBtn = page.getByRole('button', { name: 'Start Full Stack' }).first();
    const disabledBefore = {
      start_run: await startRunBtn.isDisabled(),
      start_full_stack: await startFullBtn.isDisabled(),
    };
    summary.checkpoints.push({ name: 'start_buttons_disabled_before_model_selection', ...disabledBefore });
    await snap('synthetic_start_disabled_before_models');

    const generator = await chooseModel(page, 'Generator Model');
    const judge = await chooseModel(page, 'Judge Model');
    await page.waitForTimeout(800);
    const disabledAfter = {
      start_run: await startRunBtn.isDisabled(),
      start_full_stack: await startFullBtn.isDisabled(),
    };
    summary.synthetic.generator_model = generator.chosen;
    summary.synthetic.judge_model = judge.chosen;
    summary.checkpoints.push({ name: 'start_buttons_state_after_model_selection', ...disabledAfter });
    await snap('synthetic_after_model_selection');

    const runsBefore = await listSyntheticRuns(api);
    const startRespPromise = page.waitForResponse((r) => r.url().includes('/api/synthetic/run/start') && r.request().method() === 'POST', { timeout: 30000 });
    await startRunBtn.click();
    const startResp = await startRespPromise;
    const startStatus = startResp.status();
    let startBody = {};
    try {
      startBody = await startResp.json();
    } catch {
      startBody = {};
    }
    let runId = String(startBody.run_id || '').trim();
    if (!runId && startStatus === 409) {
      const detail = String(startBody.detail || '');
      const m = detail.match(/run_id=([A-Za-z0-9._-]+)/);
      if (m) runId = String(m[1] || '').trim();
    }
    if (!runId) {
      throw new Error(`Synthetic start response missing run_id: HTTP ${startStatus} body=${JSON.stringify(startBody)}`);
    }
    summary.synthetic.run_id = runId;
    summary.synthetic.start_http_status = startStatus;
    summary.synthetic.runs_before_count = Array.isArray(runsBefore.runs) ? runsBefore.runs.length : null;

    // Wait terminal via API, then refresh UI for stable reading.
    const run = await waitForRunTerminal(api, runId);
    summary.synthetic.status = run.status;
    summary.synthetic.error = run.error ?? null;
    summary.synthetic.completed_at = run.completed_at ?? null;

    await page.goto(`${UI_BASE}/rag?subtab=synthetic&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.getByText('Synthetic Lab').first().waitFor({ timeout: 20000 });
    const runRow = page.locator('tr').filter({ hasText: runId }).first();
    await runRow.waitFor({ timeout: 20000 });
    await runRow.click();
    await page.waitForTimeout(1000);

    const gatePanel = page.locator('.studio-callout').filter({ hasText: 'Quality Gate' }).first();
    await gatePanel.waitFor({ timeout: 20000 });
    const gateText = await gatePanel.innerText();
    const top1 = parseNumberAfter('top1', gateText);
    const topk = parseNumberAfter('topk', gateText);
    const mrr = parseNumberAfter('mrr', gateText);
    const threshold = parseNumberAfter('threshold', gateText);

    summary.synthetic.quality = {
      threshold,
      top1,
      topk,
      mrr,
      sample: run.summary?.quality_sample_size ?? null,
      gate_passed: run.summary?.quality_gate_passed ?? null,
      failure_reason: run.summary?.quality_failure_reason ?? null,
    };

    const qualityArtifact = (run.artifacts || []).find((a) => a.kind === 'quality_eval_json');
    summary.artifacts.quality_eval_json_path = qualityArtifact?.path || null;

    // Publish button state from UI.
    const evalRow = page.locator('div').filter({ hasText: 'Eval Dataset' }).filter({ has: page.locator('button') }).first();
    const tripletsRow = page.locator('div').filter({ hasText: 'Triplets' }).filter({ has: page.locator('button') }).first();
    const evalBtn = evalRow.getByRole('button').first();
    const tripletsBtn = tripletsRow.getByRole('button').first();
    const publishUi = {
      eval_dataset_button_text: (await evalBtn.textContent())?.trim() || null,
      eval_dataset_disabled: await evalBtn.isDisabled(),
      eval_dataset_title: await evalBtn.getAttribute('title'),
      triplets_button_text: (await tripletsBtn.textContent())?.trim() || null,
      triplets_disabled: await tripletsBtn.isDisabled(),
      triplets_title: await tripletsBtn.getAttribute('title'),
    };
    summary.synthetic.publish_ui = publishUi;
    await snap('synthetic_quality_gate_and_publish_state');

    // API-level publish checks for the run result.
    const evalPublishResp = await api.post(`${API_BASE}/synthetic/run/${encodeURIComponent(runId)}/publish/eval_dataset`);
    const tripletsPublishResp = await api.post(`${API_BASE}/synthetic/run/${encodeURIComponent(runId)}/publish/triplets`);
    let evalPublishBody;
    let tripletsPublishBody;
    try { evalPublishBody = await evalPublishResp.json(); } catch { evalPublishBody = await evalPublishResp.text(); }
    try { tripletsPublishBody = await tripletsPublishResp.json(); } catch { tripletsPublishBody = await tripletsPublishResp.text(); }

    summary.synthetic.publish_api = {
      eval_dataset_status: evalPublishResp.status(),
      eval_dataset_body: evalPublishBody,
      triplets_status: tripletsPublishResp.status(),
      triplets_body: tripletsPublishBody,
    };

    // Quick-action route checks (must not auto-run).
    const quickCases = [
      { fromSubtab: 'retrieval', button: 'Retrieval Eval Set', expectedContext: 'retrieval', expectedRecipe: 'eval_dataset' },
      { fromSubtab: 'learning-agent', button: 'Agent Eval Set', expectedContext: 'learning-agent', expectedRecipe: 'eval_dataset' },
      { fromSubtab: 'learning-ranker', button: 'Synthetic Triplets', expectedContext: 'learning-ranker', expectedRecipe: 'triplets' },
    ];

    for (const qc of quickCases) {
      const before = await listSyntheticRuns(api);
      const beforeTop = (before.runs || [])[0]?.run_id || null;
      const beforeCount = Array.isArray(before.runs) ? before.runs.length : null;

      await page.goto(`${UI_BASE}/rag?subtab=${encodeURIComponent(qc.fromSubtab)}&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
      const btn = page.getByRole('button', { name: qc.button }).first();
      await btn.waitFor({ timeout: 20000 });
      await btn.click();
      await page.waitForURL((u) => u.pathname.endsWith('/rag') && u.searchParams.get('subtab') === 'synthetic', { timeout: 20000 });
      await page.waitForTimeout(1200);

      const currentUrl = new URL(page.url());
      const after = await listSyntheticRuns(api);
      const afterTop = (after.runs || [])[0]?.run_id || null;
      const afterCount = Array.isArray(after.runs) ? after.runs.length : null;

      const qa = {
        from_subtab: qc.fromSubtab,
        button: qc.button,
        landed_url: page.url(),
        query: {
          subtab: currentUrl.searchParams.get('subtab'),
          synthetic_context: currentUrl.searchParams.get('synthetic_context'),
          synthetic_recipe: currentUrl.searchParams.get('synthetic_recipe'),
          synthetic_autorun: currentUrl.searchParams.get('synthetic_autorun'),
        },
        no_auto_run: beforeTop === afterTop && beforeCount === afterCount,
        before_top_run_id: beforeTop,
        after_top_run_id: afterTop,
      };
      summary.quick_actions.push(qa);
      await snap(`quick_action_${qc.fromSubtab}`);
    }

    // System Prompts -> Synthetic Judge visible/editable path.
    await page.goto(`${UI_BASE}/eval?subtab=prompts&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    // Some states load analysis first; force click tab if present.
    const promptsTab = page.getByRole('button', { name: 'System Prompts' }).first();
    if (await promptsTab.isVisible().catch(() => false)) {
      await promptsTab.click();
    }
    const syntheticJudge = page.getByText('Synthetic Judge').first();
    await syntheticJudge.waitFor({ timeout: 20000 });
    const editButtons = await page.getByRole('button', { name: /^Edit$/ }).count();
    summary.system_prompts = {
      synthetic_judge_visible: await syntheticJudge.isVisible(),
      edit_buttons_count: editButtons,
    };
    await snap('system_prompts_synthetic_judge');

    // Eval compare evidence: run one new eval at sample=50, then compare against previous.
    const evalBefore = await listEvalRuns(api);
    const evalBeforeTop = (evalBefore.runs || [])[0]?.run_id || null;

    await page.goto(`${UI_BASE}/eval?subtab=analysis&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    const sampleInput = page.locator('#eval-run-settings-sample-size');
    await sampleInput.waitFor({ timeout: 20000 });
    await sampleInput.fill('50');
    const runEvalBtn = page.getByRole('button', { name: 'Run Eval' }).first();
    await runEvalBtn.waitFor({ timeout: 20000 });

    const evalStartRespPromise = page.waitForResponse((r) => r.url().includes('/api/eval/run') && r.request().method() === 'POST', { timeout: 30000 });
    await runEvalBtn.click();
    const evalStartResp = await evalStartRespPromise;
    let evalStartBody;
    try { evalStartBody = await evalStartResp.json(); } catch { evalStartBody = {}; }
    const evalNewRunId = String(evalStartBody.run_id || '').trim();

    // Wait until run list updates and selected run reflects new run id.
    const startedWait = Date.now();
    let evalAfter;
    while (true) {
      evalAfter = await listEvalRuns(api);
      const topId = (evalAfter.runs || [])[0]?.run_id || null;
      if (evalNewRunId && (evalAfter.runs || []).some((r) => r.run_id === evalNewRunId)) break;
      if (!evalNewRunId && evalBeforeTop && topId && topId !== evalBeforeTop) break;
      if (Date.now() - startedWait > 25 * 60 * 1000) {
        throw new Error('Timed out waiting for eval run to complete and appear in list');
      }
      await new Promise((r) => setTimeout(r, 3000));
    }

    // Reload analysis page to ensure selectors show latest runs.
    await page.goto(`${UI_BASE}/eval?subtab=analysis&corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
    await page.getByText('Eval Analysis').first().waitFor({ timeout: 20000 });

    // Use current selected as primary, select first non-empty compare value.
    const compareSelect = page.locator('label:has-text("Compare With (BEFORE)") + select').first();
    await compareSelect.waitFor({ timeout: 20000 });
    const compareOptions = await compareSelect.locator('option').evaluateAll((nodes) => nodes.map((n) => ({ value: String((n).value || ''), text: String(n.textContent || '').trim() })));
    const compareCandidate = compareOptions.find((o) => o.value && !o.text.includes('No comparison'));
    if (compareCandidate) {
      await compareSelect.selectOption(compareCandidate.value);
    }
    await page.waitForTimeout(1500);

    const primarySelect = page.locator('label:has-text("Primary Run (AFTER)") + select').first();
    const primaryRunId = await primarySelect.inputValue();
    const compareRunId = compareCandidate?.value || '';

    const evalCards = await extractEvalSummaryCards(page);
    summary.eval_compare = {
      sample_size: 50,
      eval_run_id_new: evalNewRunId || null,
      primary_run_id: primaryRunId || null,
      compare_run_id: compareRunId || null,
      metrics: {
        top1_percent_text: evalCards.top1,
        topk_percent_text: evalCards.topk,
        mrr_text: evalCards.mrr,
      },
      cards_preview: evalCards.cardsPreview,
    };
    await snap('eval_analysis_compare');

    // Required API validation checks for 422 missing fields.
    const missingGenResp = await api.post(`${API_BASE}/synthetic/run/start`, {
      data: { corpus_id: CORPUS_ID, provider: 'internal_ragweld', recipe: 'eval_dataset', judge_model: summary.synthetic.judge_model },
    });
    const missingJudgeResp = await api.post(`${API_BASE}/synthetic/run/start`, {
      data: { corpus_id: CORPUS_ID, provider: 'internal_ragweld', recipe: 'eval_dataset', generator_model: summary.synthetic.generator_model },
    });
    summary.api_checks.start_validation = {
      missing_generator_model_status: missingGenResp.status(),
      missing_judge_model_status: missingJudgeResp.status(),
    };

    summary.status = 'passed';
    summary.completed_at = new Date().toISOString();
  } catch (err) {
    summary.status = 'failed';
    summary.error = err instanceof Error ? err.message : String(err);
    summary.completed_at = new Date().toISOString();
    try {
      await page.screenshot({ path: path.join(outDir, 'failure.png'), fullPage: true });
    } catch {
      // ignore
    }
    throw err;
  } finally {
    await writeJson(path.join(outDir, 'summary.json'), summary);
    await context.close();
    await browser.close();
    await api.dispose();
    // eslint-disable-next-line no-console
    console.log(`UI acceptance summary: ${path.join(outDir, 'summary.json')}`);
  }
}

main();
