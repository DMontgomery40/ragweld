// RAG > Retrieval consolidated-controls regressions from the 2026-08-29 GUI drive,
// driven against the real app + API with no request interception:
//   M-07  the drifted duplicate "Retrieval Balance" knobs (vector weight 0.7 vs 0.4,
//         topk 75 vs 50, RRF k 60 vs 6, langgraph final k) are deleted; the
//         authoritative fusion.* / per-leg controls remain, one per concept,
//   M-31  inert dependent controls say why they are inert,
//   M-32  the non-chat generation alias is rendered once (Generation > Answer Routing),
//   M-147 that alias picker is provider-grouped (optgroups), not a flat native list.
//
// These are read-only: every assertion inspects rendered config controls, so the
// spec activates whatever corpus the box already has and never mutates it.
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

async function firstCorpusId(request: import('@playwright/test').APIRequestContext): Promise<string> {
  const res = await request.get(`${API_BASE}/corpora`);
  expect(res.ok(), `GET ${API_BASE}/corpora must succeed`).toBeTruthy();
  const corpora = (await res.json()) as Array<{ corpus_id: string; internal?: boolean }>;
  const usable =
    corpora.find((c) => c.corpus_id === 'ragweld_code') ??
    corpora.find((c) => !c.internal && !/^ragweld-(exhaustive|registry)-|^pytest_/.test(c.corpus_id)) ??
    corpora.find((c) => !c.internal) ??
    corpora[0];
  expect(usable?.corpus_id, 'the box must have at least one corpus registered').toBeTruthy();
  return usable.corpus_id;
}

async function openRetrieval(page: Page, corpusId: string): Promise<void> {
  await activateCorpusInBrowser(page, corpusId);
  await page.goto('rag?subtab=retrieval', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('retrieval-subtab')).toBeVisible();
}

test.describe('RAG > Retrieval consolidated controls (wave 2b)', () => {
  let corpusId = '';

  test.beforeAll(async ({ request }) => {
    corpusId = await firstCorpusId(request);
  });

  test('M-07: the drifted duplicate "Retrieval Balance" knobs are gone', async ({ page }) => {
    await openRetrieval(page, corpusId);
    await page.getByTestId('retrieval-card-ops_tracing').click();

    // The dead compatibility set (its values had drifted from the fusion.* / per-leg
    // knobs the pipeline actually reads) is deleted, not hidden.
    await expect(page.getByTestId('retrieval-section-ops-retrieval-balance')).toHaveCount(0);
    for (const label of [
      'RRF K Div',
      'TopK Dense',
      'TopK Sparse',
      'Retrieval Vector Weight',
      'Retrieval BM25 Weight',
      'LangGraph Final K',
    ]) {
      await expect(page.getByText(label, { exact: false })).toHaveCount(0);
    }

    // The sibling sections in the same view still render.
    await expect(page.getByTestId('retrieval-section-ops-semantic-cache')).toBeVisible();
  });

  test('M-07: the authoritative fusion knobs remain, one per concept', async ({ page }) => {
    await openRetrieval(page, corpusId);
    await page.getByTestId('retrieval-card-fusion_scoring').click();

    // Scope to the Fusion Strategy section, and match the control <label> elements
    // specifically (not free text): the inert-reason note is a <div> that mentions
    // "Graph weights", and page-wide text counts would also catch the Layer Weighting
    // controls. Each concept that WAS duplicated (its retrieval.* copy is deleted) now
    // has exactly one label here.
    const strategy = page.getByTestId('retrieval-section-fusion-strategy');
    await expect(strategy).toBeVisible();
    await expect(strategy.locator('label').filter({ hasText: 'RRF K' })).toHaveCount(1);
    await expect(strategy.locator('label').filter({ hasText: 'Vector Weight' })).toHaveCount(1);
    await expect(strategy.locator('label').filter({ hasText: 'Sparse Weight' })).toHaveCount(1);
    await expect(strategy.locator('label').filter({ hasText: 'Graph Weight' })).toHaveCount(1);
  });

  test('M-31: an inert dependent explains why it is inert', async ({ page }) => {
    await openRetrieval(page, corpusId);
    await page.getByTestId('retrieval-card-fusion_scoring').click();

    // One fusion cluster is always inert given the single selected method; the note
    // names which and why (shown regardless of rrf/weighted).
    const note = page.getByTestId('fusion-inert-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('not used by');
  });

  test('M-32: the generation alias is rendered once, in Answer Routing', async ({ page }) => {
    await openRetrieval(page, corpusId);

    // The Universal Controls duplicate is gone.
    await expect(page.getByTestId('retrieval-generation-alias')).toHaveCount(0);

    // Its single home is Generation > Answer Routing.
    await page.getByTestId('retrieval-card-generation').click();
    await expect(page.getByTestId('retrieval-generation-answer-alias')).toHaveCount(1);
  });

  test('M-147: the generation alias picker is provider-grouped, not a flat list', async ({ page }) => {
    await openRetrieval(page, corpusId);
    await page.getByTestId('retrieval-card-generation').click();

    const alias = page.getByTestId('retrieval-generation-answer-alias');
    await expect(alias.locator('select')).toBeVisible();
    // The Chat model picker groups by provider; a flat native <select> would have none.
    await expect(alias.locator('optgroup').first()).toBeAttached();
  });

  test('M-33: the settings rail links to model assignments, not a second copy', async ({ page }) => {
    await activateCorpusInBrowser(page, corpusId);
    await page.goto('dashboard?subtab=system', { waitUntil: 'domcontentloaded' });
    await page.getByTestId('dock-mode-settings').click();

    const rail = page.getByTestId('dock-panel');
    // The duplicate Quick Model Switcher (and its second "Apply Changes") is deleted.
    await expect(rail.getByText('Quick Model Switcher', { exact: false })).toHaveCount(0);
    // It is replaced by a link out to the single assignment surface.
    await expect(rail.getByTestId('sidepanel-open-model-assignments')).toBeVisible();
  });
});
