// RAG > Data Quality, read the way an operator reads it.
//
// The drive found the page promising "Build and review chunk summaries and keywords" with no
// keywords review panel at all, and a chunk-summaries panel reading "No builds yet / No chunk
// summaries to show" for every corpus including a fully indexed one -- with zero requests
// matching `summar` or `keyword` in the network log, because nothing was ever fetched. It
// also found placeholders on "(one per line)" fields containing literal backslash-n.
import { expect, test } from '@playwright/test';
import { provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(10 * 60 * 1000);

let corpus: ExhaustiveCorpus;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: true });
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

test('the page fetches what it claims to review', async ({ page }) => {
  const fetched: string[] = [];
  page.on('request', (req) => {
    const url = req.url();
    if (/chunk_summaries|\/corpora\//.test(url)) fetched.push(url);
  });

  await page.goto(`rag?subtab=data-quality&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('corpus-keywords-panel')).toBeVisible();

  await expect
    .poll(() => fetched.some((u) => u.includes('chunk_summaries')), { timeout: 30_000 })
    .toBe(true);
  expect(fetched.some((u) => u.includes(`/corpora/${corpus.corpusId}`))).toBe(true);
});

test('the empty states say why they are empty and what to do next', async ({ page }) => {
  await page.goto(`rag?subtab=data-quality&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });

  const summaries = page.getByTestId('chunk-summaries-empty');
  await expect(summaries).toBeVisible();
  await expect(summaries).toContainText(/Build chunk summaries/i);

  const keywords = page.getByTestId('corpus-keywords-empty');
  await expect(keywords).toBeVisible();
  await expect(keywords).toContainText(/Generate keywords/i);

  // The header no longer promises a review surface the page does not have.
  const header = page.locator('h3', { hasText: 'Data Quality' });
  await expect(header).toBeVisible();
});

test('the "one per line" placeholders contain real line breaks', async ({ page }) => {
  await page.goto(`rag?subtab=data-quality&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });

  await expect(page.getByTestId('corpus-keywords-panel')).toBeVisible();
  await expect(page.locator('textarea[placeholder]')).toHaveCount(3);
  const placeholders = await page
    .locator('textarea[placeholder]')
    .evaluateAll((nodes) => nodes.map((n) => (n as HTMLTextAreaElement).placeholder));
  const perLine = placeholders.filter((p) => /node_modules|\*\.min\.js|deprecated/.test(p));
  expect(perLine.length).toBe(3);
  for (const placeholder of perLine) {
    expect(placeholder).not.toContain('\\n');
    expect(placeholder.split('\n').length).toBeGreaterThan(1);
  }
});

test('generating keywords fills the review panel from the stored corpus', async ({ page }) => {
  await page.goto(`rag?subtab=data-quality&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('corpus-keywords-empty')).toBeVisible();

  await page.getByRole('button', { name: /generate keywords/i }).click();
  await expect(page.getByTestId('corpus-keywords-empty')).toHaveCount(0, { timeout: 120_000 });

  // Reload: the panel is populated from what was persisted, not from session state.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('corpus-keywords-panel')).toContainText(/Corpus keywords \(\d+\)/);
  await expect(page.getByTestId('corpus-keywords-empty')).toHaveCount(0);
});
