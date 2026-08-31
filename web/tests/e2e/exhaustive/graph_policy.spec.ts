import { expect, test } from '@playwright/test';
import {
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(5 * 60 * 1000);

let corpus: ExhaustiveCorpus;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request);
  await patchCorpusConfigSection(request, corpus.corpusId, 'graph_indexing', {
    enabled: true,
    build_code_graph: false,
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
