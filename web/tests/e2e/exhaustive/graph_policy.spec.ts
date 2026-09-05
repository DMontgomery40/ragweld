import { expect, test } from '@playwright/test';
import {
  API_BASE,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(5 * 60 * 1000);

let corpus: ExhaustiveCorpus;
const SCHEMA_MODEL = String(process.env.GRAPH_E2E_KG_MODEL || '').trim() || 'deepseek.deepseek-v4-flash';

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request);
  await patchCorpusConfigSection(request, corpus.corpusId, 'graph_indexing', {
    enabled: true,
    build_code_graph: false,
    semantic_kg_llm_model: SCHEMA_MODEL,
  });
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

test('external documents derive semantic policy while Recall stays excluded', async ({ page }) => {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('target-corpus-select')).toHaveValue(corpus.corpusId);
  await page.getByTestId('indexing-component-card-enrichment').click();

  await expect(page.getByTestId('graph-policy-badge')).toHaveText('Semantic entity graph');
  await expect(page.getByTestId('graph-indexing-enabled')).toBeEnabled();
  await expect(page.getByTestId('semantic-graph-settings')).toBeVisible();
  await expect(page.getByTestId('semantic-kg-enabled')).toHaveCount(0);
  await expect(page.getByTestId('semantic-kg-mode')).toHaveCount(0);

  const corpusSelect = page.getByTestId('target-corpus-select');
  await corpusSelect.selectOption('recall_default');
  await expect(corpusSelect).toHaveValue('recall_default');
  await expect(page.getByTestId('graph-policy-badge')).toHaveText('Excluded internal corpus');
  await expect(page.getByTestId('graph-indexing-enabled')).toBeDisabled();
  await expect(page.getByTestId('semantic-graph-settings')).toHaveCount(0);
});

test('operator reviews the proposed schema before approving a semantic run', async ({ page, request }) => {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('target-corpus-select')).toHaveValue(corpus.corpusId);
  await page.getByTestId('indexing-component-card-enrichment').click();

  await page.getByTestId('generate-graph-schema').click();
  const proposal = page.getByTestId('graph-schema-proposal');
  await expect(proposal).toBeVisible({ timeout: 180_000 });
  await expect(proposal).toContainText(SCHEMA_MODEL);
  await expect(page.getByTestId('graph-schema-hash')).toHaveText(/^[0-9a-f]{64}$/);

  await expect(page.getByTestId('graph-schema-review')).toHaveJSProperty('open', false);
  await page.getByTestId('graph-schema-review').locator('summary').first().click();
  await page.getByTestId('graph-schema-technical').locator('summary').first().click();
  for (const section of [
    'graph-schema-node-types',
    'graph-schema-relationship-types',
    'graph-schema-patterns',
    'graph-schema-constraints',
    'graph-schema-sample',
  ]) {
    const details = page.getByTestId(section);
    await details.locator('summary').click();
    await expect(details).toHaveJSProperty('open', true);
  }

  const approve = page.getByTestId('index-now-button');
  await expect(approve).toHaveText(/Approve schema & index/);
  await approve.click();
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 120_000 });
  await expect(page.getByTestId('confirm-dialog-message')).toContainText('Semantic KG');

  const started = page.waitForResponse(
    (response) => /\/api\/index(?:\?|$)/.test(response.url()) && response.request().method() === 'POST'
  );
  await page.getByTestId('confirm-dialog-accept').click();
  expect((await started).status()).toBe(200);
  await expect(page.getByRole('button', { name: 'Stop Indexing' })).toBeVisible({ timeout: 30_000 });

  // Task 8 drive observation D2: the run panel used to keep the PREVIOUS run's id and
  // graph verdict under the new run's "indexing" badge for the whole run. The panel must
  // name the run the API is actually executing, and nothing else, while it is live.
  await page.getByTestId('index-run-details').locator('summary').click();
  let liveRunId = '';
  for (let attempt = 0; attempt < 15 && !liveRunId; attempt += 1) {
    const latest = await request.get(`${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/runs/latest`);
    if (latest.ok()) {
      const body = (await latest.json()) as { run_id?: string; status?: string };
      if (body.status === 'indexing') liveRunId = String(body.run_id || '');
    }
    if (!liveRunId) await page.waitForTimeout(1000);
  }
  expect(liveRunId).toMatch(/^[0-9a-f]{32}$/);
  await expect(page.getByTestId('index-run-id')).toHaveText(`run_id: ${liveRunId}`, { timeout: 30_000 });

  await page.getByRole('button', { name: 'Stop Indexing' }).click();
  await expect(page.getByTestId('index-now-button')).toBeVisible({ timeout: 60_000 });
});
