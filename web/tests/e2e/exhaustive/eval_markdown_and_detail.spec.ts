// Eval Analysis rendering + workflow (wave 2b, lane `eval`).
//
// Proves the wave-2b eval rulings against the real app + API with no request
// interception and no mocks: LLM output renders as GFM through the one shared
// markdown renderer (M-14 / M-72 / M-164), a question row opens a per-question
// detail with retrieved-chunk rank/leg/score, the generated answer, and the
// judge output (M-13), pass/fail/neutral colours are honest (M-68), and the
// changed-params count is de-duplicated (M-67).
//
// Content is deterministic: two eval runs and one Promptfoo run are seeded as
// persisted JSON for a uniquely-named isolated corpus, so nothing runs an eval
// or spends on an LLM, and nothing touches a production corpus. The files live
// under the temp API's own data/eval_runs (the worktree root), never the
// operator's.
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import {
  activateCorpusInBrowser,
  EXHAUSTIVE_CHAT_MODEL,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

// A single fixture exercising every GFM construct the drives found broken:
// a table (with its `---` separator row), bold, inline code, and a nested list.
const GFM_FIXTURE = [
  'The **most important** next experiment tunes `RERANKER_MODEL`.',
  '',
  '| Metric | Before | After |',
  '| --- | --- | --- |',
  '| top-k | 0.62 | 0.78 |',
  '| mrr | 0.55 | 0.71 |',
  '',
  'Next steps:',
  '',
  '- Tune fusion',
  '    - vector weight',
  '    - sparse weight',
  '- Re-index the corpus',
  '',
].join('\n');

function runsDir(): string {
  return path.resolve(process.cwd(), 'data', 'eval_runs');
}

function evalMetrics(): Record<string, number> {
  return {
    mrr: 1.0,
    recall_at_5: 1.0,
    recall_at_10: 1.0,
    recall_at_20: 1.0,
    precision_at_5: 1.0,
    ndcg_at_10: 1.0,
    latency_p50_ms: 120,
    latency_p95_ms: 140,
  };
}

function evalRunJson(corpusId: string, runId: string, useMulti: boolean, fusion: string): Record<string, unknown> {
  return {
    run_id: runId,
    corpus_id: corpusId,
    dataset_id: 'seed-dataset',
    config_snapshot: {},
    // The flat snapshot carries EVAL_MULTI; the runtime fields carry use_multi.
    // Old code counted EVAL_MULTI + use_multi + eval_multi as three changes.
    config: { EVAL_MULTI: useMulti, FUSION_METHOD: fusion },
    total: 1,
    top1_hits: 1,
    topk_hits: 1,
    top1_accuracy: 1.0,
    topk_accuracy: 1.0,
    duration_secs: 0.12,
    use_multi: useMulti,
    final_k: 5,
    metrics: evalMetrics(),
    results: [
      {
        entry_id: 'q1',
        question: 'What procedure calibrates the tide sensor?',
        retrieved_paths: ['sensor-calibration.md'],
        expected_paths: ['sensor-calibration.md'],
        top_paths: ['sensor-calibration.md'],
        top1_path: ['sensor-calibration.md'],
        top1_hit: true,
        topk_hit: true,
        reciprocal_rank: 1.0,
        recall: 1.0,
        latency_ms: 120,
        duration_secs: 0.12,
        docs: [
          { file_path: 'sensor-calibration.md', start_line: 10, score: 0.91, source: 'vector' },
          { file_path: 'tide-tables.md', start_line: 3, score: 0.55, source: 'sparse' },
          { file_path: 'harbor-log.md', start_line: 1, score: 0.4, source: 'graph' },
        ],
        generated_answer: GFM_FIXTURE,
        ragas: { faithfulness: 0.92, answer_relevancy: 0.88 },
      },
    ],
    started_at: '2026-08-30T12:00:00Z',
    completed_at: '2026-08-30T12:00:05Z',
  };
}

function promptfooRunJson(corpusId: string, runId: string): Record<string, unknown> {
  return {
    run_id: runId,
    corpus_id: corpusId,
    provider_alias: 'openai.gpt-5.6-luna',
    grader_alias: 'openai.gpt-5.6-luna',
    promptfoo_version: '0.0.0-seed',
    total: 1,
    passed: 1,
    failed: 0,
    skipped_entries: 0,
    started_at: '2026-08-30T12:01:00Z',
    completed_at: '2026-08-30T12:01:30Z',
    results: [
      {
        entry_id: 'q1',
        question: 'What procedure calibrates the tide sensor?',
        expected_answer: 'A calibration procedure grounded in the corpus.',
        response: GFM_FIXTURE,
        passed: true,
        score: 1.0,
        reason: 'All assertions passed',
        latency_ms: 900,
      },
    ],
  };
}

let corpus: ExhaustiveCorpus;
const seededFiles: string[] = [];

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: false });
  const dir = runsDir();
  const pfDir = path.join(dir, 'promptfoo');
  mkdirSync(pfDir, { recursive: true });

  // run ids sort by localeCompare desc → the ...05 run is "current", ...00 is "compare".
  const currentId = `${corpus.corpusId}__20260830120005`;
  const compareId = `${corpus.corpusId}__20260830120000`;
  const pfId = `${corpus.corpusId}__pf20260830120130`;

  const write = (p: string, data: unknown) => {
    writeFileSync(p, JSON.stringify(data, null, 2), 'utf-8');
    seededFiles.push(p);
  };
  write(path.join(dir, `${currentId}.json`), evalRunJson(corpus.corpusId, currentId, true, 'rrf'));
  write(path.join(dir, `${compareId}.json`), evalRunJson(corpus.corpusId, compareId, false, 'weighted'));
  write(path.join(pfDir, `${pfId}.json`), promptfooRunJson(corpus.corpusId, pfId));
});

test.afterAll(async ({ request }) => {
  for (const f of seededFiles) {
    if (existsSync(f)) rmSync(f, { force: true });
  }
  if (corpus) await corpus.dispose(request);
});

test('eval question detail renders GFM and shows chunk rank/leg, answer, and judge', async ({ page, baseURL }) => {
  await activateCorpusInBrowser(page, corpus.corpusId);
  await page.goto(new URL('eval?subtab=analysis', baseURL ?? '').toString());

  // The drill-down loads the seeded current run and its compare.
  const row = page.getByTestId('eval-question-row-0');
  await expect(row).toBeVisible();
  await row.click();

  // M-13: retrieved chunks with rank + leg + score, the answer, and the judge.
  const chunks = page.getByTestId('eval-question-chunks');
  await expect(chunks).toBeVisible();
  const legs = page.getByTestId('eval-chunk-leg');
  await expect(legs).toHaveCount(3);
  await expect(legs.nth(0)).toHaveText('vector');
  await expect(legs.nth(1)).toHaveText('sparse');
  await expect(legs.nth(2)).toHaveText('graph');

  const answer = page.getByTestId('eval-question-answer');
  await expect(answer).toBeVisible();
  const judge = page.getByTestId('eval-question-judge');
  await expect(judge).toContainText('faithfulness');

  // M-14/M-164 renderer: the answer is real GFM, not raw markdown text.
  const md = answer.getByTestId('assistant-markdown');
  await expect(md.locator('table')).toHaveCount(1);
  await expect(md.locator('th', { hasText: 'Metric' })).toBeVisible();
  await expect(md.locator('strong', { hasText: 'most important' })).toBeVisible();
  await expect(md.locator('code', { hasText: 'RERANKER_MODEL' })).toBeVisible();
  // Nested list: a <ul> inside a <li> inside a <ul>.
  await expect(md.locator('ul li ul li')).not.toHaveCount(0);
  // The raw markdown syntax must NOT survive as visible text.
  const answerText = (await md.innerText()).trim();
  expect(answerText).not.toContain('| --- |');
  expect(answerText).not.toContain('**most important**');
});

test('changed-params count is de-duplicated and pass/fail colours are honest', async ({ page, baseURL }) => {
  await activateCorpusInBrowser(page, corpus.corpusId);
  await page.goto(new URL('eval?subtab=analysis', baseURL ?? '').toString());

  // M-67: EVAL_MULTI + use_multi + eval_multi collapse to one setting, so with
  // FUSION_METHOD the distinct count is 2 (old code counted 4).
  const changes = page.locator('text=/\\d+ params changed/');
  await expect(changes.first()).toContainText('2 params changed');

  // M-68: perf change is 0.0% and there are no regressions, so neither is red.
  const tokens = await page.evaluate(() => {
    const cs = getComputedStyle(document.documentElement);
    const probe = (name: string) => {
      const el = document.createElement('span');
      el.style.color = `var(${name})`;
      document.body.appendChild(el);
      const c = getComputedStyle(el).color;
      el.remove();
      return c;
    };
    return { err: probe('--err'), muted: probe('--fg-muted'), fg: probe('--fg'), _cs: cs.color };
  });

  const perf = page.getByTestId('eval-performance-change');
  await expect(perf).toContainText('0.0%');
  await expect(perf).toHaveCSS('color', tokens.muted);

  const regressions = page.getByTestId('eval-regressions-count');
  await expect(regressions).toHaveText('0');
  await expect(regressions).toHaveCSS('color', tokens.muted);

  // A changed config value is neutral, never the danger colour.
  const value = page.getByTestId('config-diff-value').first();
  const valueColor = await value.evaluate((el) => getComputedStyle(el).color);
  expect(valueColor).not.toBe(tokens.err);
});

test('promptfoo answer renders GFM through the shared renderer', async ({ page, baseURL }) => {
  await activateCorpusInBrowser(page, corpus.corpusId);
  await page.goto(new URL('eval?subtab=analysis', baseURL ?? '').toString());

  const panel = page.getByTestId('promptfoo-regression-panel');
  await expect(panel).toBeVisible();

  // Expand: the "Run results" section, the Passed group, then the card.
  await panel.getByRole('button', { name: /Run results/ }).click();
  await panel.locator('[data-testid="promptfoo-passed-group"] > summary').click();
  await panel.locator('[data-testid="promptfoo-result-card"] > summary').first().click();

  const md = panel.getByTestId('promptfoo-result-answer').getByTestId('assistant-markdown');
  await expect(md.locator('table')).toHaveCount(1);
  await expect(md.locator('strong', { hasText: 'most important' })).toBeVisible();
  await expect(md.locator('code', { hasText: 'RERANKER_MODEL' })).toBeVisible();
  const text = (await md.innerText()).trim();
  expect(text).not.toContain('| --- |');
});

// M-73: the AI analysis panel gains copy + Markdown export (it had only Clear).
// This is the one paid path in the file — one small analysis on the isolated
// corpus through the cheap gateway alias, never the host-served local model.
test('AI analysis exposes copy and Markdown export that produce a download', async ({ page, baseURL, request }) => {
  // The analysis routes on generation.gen_model; point it at the cheap paid alias.
  await patchCorpusConfigSection(request, corpus.corpusId, 'generation', { gen_model: EXHAUSTIVE_CHAT_MODEL });
  await activateCorpusInBrowser(page, corpus.corpusId);
  await page.goto(new URL('eval?subtab=analysis', baseURL ?? '').toString());

  await expect(page.getByTestId('eval-question-row-0')).toBeVisible();
  await page.getByRole('button', { name: 'Generate AI Analysis' }).click();

  // The costed analysis renders as markdown; then copy/export controls appear.
  await expect(page.getByTestId('eval-ai-analysis')).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId('eval-ai-analysis').getByTestId('assistant-markdown')).toBeVisible();
  await expect(page.getByTestId('eval-analysis-copy')).toBeVisible();
  const exportBtn = page.getByTestId('eval-analysis-export');
  await expect(exportBtn).toBeVisible();

  const downloadPromise = page.waitForEvent('download');
  await exportBtn.click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toMatch(/^eval-analysis-.*\.md$/);
});

// M-75: the Add Eval Entry form gains an expected_answer field, so entries
// created through the UI are gradeable by the Promptfoo regression lane instead
// of being skipped by construction.
test('the eval dataset form captures an expected answer that round-trips', async ({ page, baseURL }) => {
  await activateCorpusInBrowser(page, corpus.corpusId);
  await page.goto(new URL('eval?subtab=dataset', baseURL ?? '').toString());

  const answer = `A grounded calibration answer ${Date.now().toString(36)}.`;
  await page.getByPlaceholder('Question (e.g., Where is X implemented?)').fill('How is the tide sensor calibrated?');
  await page.getByPlaceholder('Expected paths (comma-separated)').first().fill('sensor-calibration.md');
  await page.getByTestId('eval-new-expected-answer').fill(answer);
  await page.getByRole('button', { name: 'Add Entry' }).click();

  // The saved entry shows its expected answer — the field persisted through the API.
  const saved = page.getByTestId('eval-entry-expected-answer').filter({ hasText: answer });
  await expect(saved).toBeVisible();
});
