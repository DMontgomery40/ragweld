/** Saved accounting fixtures through the real API and UI; no model calls or interception. */
import fs from 'node:fs';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import type { BenchmarkRun, Corpus, TraceCostSummary, TriBridConfig } from '../../../src/types/generated';

const API_BASE = process.env.GATEWAY_API_BASE_URL ?? 'http://127.0.0.1:58043/api';

test('saved benchmarks distinguish reported charges, estimates, and unknown totals', async ({ page }) => {
  const corpora = await page.request.get(`${API_BASE}/corpora`);
  expect(corpora.ok()).toBeTruthy();
  const corpusId = process.env.GATEWAY_E2E_CORPUS_ID || 'nasa-apollo-11';
  expect((await corpora.json()).some((corpus: Corpus) => corpus.corpus_id === corpusId)).toBeTruthy();
  expect(corpusId, 'an existing corpus is required; this test never writes corpus/config state').toBeTruthy();
  const response = await page.request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpusId)}`);
  expect(response.ok()).toBeTruthy();
  const config = await response.json() as TriBridConfig;
  const resultsDir = path.resolve(process.cwd(), config.chat.benchmark.results_path);
  expect(resultsDir.startsWith(`${process.cwd()}${path.sep}`), 'fixtures must stay inside an isolated checkout').toBeTruthy();
  expect(process.cwd().startsWith('/var/tmp/'), 'run this spec in an isolated remote overlay').toBeTruthy();
  fs.mkdirSync(resultsDir, { recursive: true });

  const reported: TraceCostSummary = { cost_source: 'provider', authoritative: true, estimated_cost_usd: 0.0000001234, input_tokens: 100, output_tokens: 20, total_tokens: 120 };
  const estimate: TraceCostSummary = { ...reported, cost_source: 'catalog', authoritative: false, estimated_cost_usd: 0.0025 };
  const unknown: TraceCostSummary = { cost_source: 'unavailable', authoritative: false, estimated_cost_usd: null, detail: 'Run total unavailable because one call has no accounting.' };
  const runs: BenchmarkRun[] = [
    { run_id: `cost-reported-${Date.now()}`, prompt: 'How often is the salinity sensor calibrated? Reported-cost fixture.', cost_summary: reported, results: [
      { model: 'openai.gpt-5.6-luna', response: 'Every 30 days.', cost_summary: reported },
      { model: 'ragweld-local', response: 'Every 30 days.', cost_summary: { ...reported, estimated_cost_usd: 0 } },
    ] },
    { run_id: `cost-estimated-${Date.now()}`, prompt: 'How often is the salinity sensor calibrated? Estimated-cost fixture.', cost_summary: { ...estimate, estimated_cost_usd: 0.0025001234 }, results: [
      { model: 'openai.gpt-5.6-luna', response: 'Every 30 days.', cost_summary: reported },
      { model: 'openai.gpt-5.4-mini', response: 'Every 30 days.', cost_summary: estimate },
    ] },
    { run_id: `cost-unknown-${Date.now()}`, prompt: 'How often is the salinity sensor calibrated? Partial-accounting fixture.', cost_summary: unknown, results: [
      { model: 'openai.gpt-5.6-luna', response: '', error: 'No assistant content; reasoning consumed the output budget.', cost_summary: reported },
      { model: 'openai.gpt-5.4-mini', response: '', error: 'Gateway request failed before accounting was returned.', cost_summary: null },
    ] },
  ].map((run) => ({
    ...run,
    cost_summary: run.cost_summary.cost_source === 'unavailable' ? run.cost_summary : {
      ...run.cost_summary, input_tokens: 200, output_tokens: 40, total_tokens: 240,
    },
    corpus_id: corpusId,
    started_at_ms: Date.now(),
    models: run.results!.map((row) => row.model),
  }));

  const errors: string[] = [];
  const consoleDiagnostics: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') consoleDiagnostics.push(`${message.location().url}: ${message.text()}`);
  });
  page.on('response', (response) => {
    if (response.url().includes('/api/benchmark/') && !response.ok()) {
      errors.push(`Benchmark request failed: ${response.status()} ${response.url()}`);
    }
  });
  const files = runs.map((run) => path.join(resultsDir, `${run.run_id}.json`));
  try {
    runs.forEach((run, index) => fs.writeFileSync(files[index], JSON.stringify(run)));
    const stored = await page.request.get(`${API_BASE}/benchmark/results?corpus_id=${encodeURIComponent(corpusId)}`);
    expect(stored.ok()).toBeTruthy();
    expect((await stored.json()).runs.filter((run: BenchmarkRun) => files.some((file) => file.endsWith(`${run.run_id}.json`)))).toHaveLength(3);

    for (const [index, run] of runs.entries()) {
      await page.goto(`benchmark?corpus=${encodeURIComponent(corpusId)}`);
      await expect(page).toHaveURL(/\/benchmark\?corpus=/);
      await expect(page.getByTestId('benchmark-tab')).toBeVisible();
      await page.getByTestId('benchmark-past-runs').getByRole('button', { name: run.prompt }).click();
      const total = page.getByTestId('benchmark-run-cost');
      const costs = page.getByTestId('benchmark-model-cost');
      await expect(costs).toHaveCount(2);
      await expect(costs.nth(0)).toContainText('Gateway reported: $0.0000001234');
      await expect(costs.nth(0)).toContainText('100 input · 20 output tokens');
      if (index === 0) {
        await expect(total).toContainText('Gateway reported: $0.0000001234');
        await expect(costs.nth(1)).toContainText('Gateway reported: $0');
      } else if (index === 1) {
        await expect(total).toContainText('Estimated cost: $0.00250012');
        await expect(costs.nth(1)).toContainText('Estimated cost: $0.0025');
      } else {
        await expect(total).toContainText('Cost unknown');
        await expect(total).not.toContainText('$0');
        await expect(costs.nth(1)).toContainText('Cost unknown');
        await expect(costs.nth(1)).not.toContainText('$0');
        await expect(page.getByRole('table', { name: 'Benchmark results' })).toContainText('reasoning consumed');
        await total.scrollIntoViewIfNeeded();
        await page.screenshot({ path: '/tmp/astra-benchmark-cost.png', fullPage: false });
      }
      await expect(page.locator('vite-error-overlay')).toHaveCount(0);
    }
    // Preserve environment diagnostics (for example a production Faro collector
    // rejecting the overlay origin) without masking benchmark or JS failures.
    if (consoleDiagnostics.length) {
      await test.info().attach('console-diagnostics', { body: consoleDiagnostics.join('\n'), contentType: 'text/plain' });
    }
    expect(errors).toEqual([]);
  } finally {
    files.forEach((file) => fs.rmSync(file, { force: true }));
  }
});
