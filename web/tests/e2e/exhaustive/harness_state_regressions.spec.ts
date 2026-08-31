import { expect, test } from '@playwright/test';
import { activateCorpusInBrowser, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';
import { applyRefreshDoubleCheck, gotoSurface } from './harness';
import type { ControlDescriptor } from './types';

let corpus: ExhaustiveCorpus | null = null;
let unindexedCorpus: ExhaustiveCorpus | null = null;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: true });
  unindexedCorpus = await provisionExhaustiveCorpus(request, { index: false });
});

test.afterAll(async ({ request }) => {
  if (corpus) await corpus.dispose(request);
  if (unindexedCorpus) await unindexedCorpus.dispose(request);
});

test('surface re-anchoring leaves the transient Chat source dropdown closed', async ({ page }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);
  await gotoSurface(page, { route: '/chat', subtab: 'ui', label: 'Chat / UI' });

  const dropdown = page.getByTestId('source-dropdown');
  await expect(dropdown).toBeVisible();
  await expect(dropdown).not.toHaveAttribute('open', '');
});

test('an indexed corpus disables every advanced field that changes the dense contract', async ({ page }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);
  await page.goto(
    `rag?subtab=indexing&component=embedding&corpus=${encodeURIComponent(corpus!.corpusId)}`,
    { waitUntil: 'domcontentloaded' }
  );

  const contractFields = [
    'embedding-input-truncation',
    'embedding-text-prefix',
    'embedding-text-suffix',
    'embedding-contextual-chunk-embeddings',
    'embedding-late-chunking-max-doc-tokens',
    'embedding-max-tokens',
  ];
  for (const testId of contractFields) {
    const field = page.getByTestId(testId);
    await expect(field).toBeVisible({ timeout: 60_000 });
    await expect(field, `${testId} must not stage a contract change against an existing index`).toBeDisabled();
  }
});

test('Apply confirms and persists an index-affecting field before an index exists', async ({ page }) => {
  expect(unindexedCorpus).not.toBeNull();
  await activateCorpusInBrowser(page, unindexedCorpus!.corpusId);
  await page.goto(
    `rag?subtab=indexing&component=embedding&corpus=${encodeURIComponent(unindexedCorpus!.corpusId)}`,
    { waitUntil: 'domcontentloaded' }
  );

  const selector = '[data-testid="embedding-text-suffix"]';
  const field = page.locator(selector).first();
  await expect(field).toBeVisible({ timeout: 60_000 });
  const expected = `exhaustive-confirm-${Date.now()}`;
  await field.fill(expected);

  const control: ControlDescriptor = {
    fingerprint: 'input|text|||Text suffix',
    selector,
    tag: 'input',
    type: 'text',
    role: '',
    id: '',
    name: '',
    label: 'Text suffix',
    value: '',
    checked: null,
    disabled: false,
    visible: true,
    optionValues: [],
  };
  const cycle = await applyRefreshDoubleCheck(page, control, expected);
  expect(cycle).toEqual({
    config_changed: true,
    apply_saved: true,
    persisted_after_refresh: true,
    ui_matches: true,
  });
});
