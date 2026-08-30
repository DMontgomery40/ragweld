// The Indexing tab's configuration cards, read the way an operator reads them.
//
// The drive found copy pointing at subsystems and locations that do not exist: a
// "Postgres FTS tokenizer" removed at the Qdrant cutover, a Figures header promising an
// estimate "below" that lives three panels away inside a modal, the same file-size limit
// exposed twice in units a million apart with no cross-reference, and a destructive
// FORCE REINDEX labelled with two dim words.
import { expect, test, type Page } from '@playwright/test';
import { provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(5 * 60 * 1000);

let corpus: ExhaustiveCorpus;

async function openTab(page: Page): Promise<void> {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('index-now-button')).toBeVisible();
}

async function openCard(page: Page, card: 'chunking' | 'bm25' | 'figures'): Promise<void> {
  await page.getByTestId(`indexing-component-card-${card}`).click();
}

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request);
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

test('no card promises Postgres FTS, which the Qdrant cutover removed', async ({ page }) => {
  await openTab(page);

  const body = (await page.locator('body').innerText()).toLowerCase();
  expect(body).not.toContain('postgres fts');
  expect(body).toContain('sparse stemming');

  // The delete tooltip claimed to delete "FTS" too.
  const deleteButton = page.getByRole('button', { name: /delete index/i });
  await expect(deleteButton).toHaveAttribute('title', /vectors/i);
  expect(await deleteButton.getAttribute('title')).not.toMatch(/\bFTS\b/);
});

test('both file-size ceilings name their own scope and the limit that actually bites', async ({
  page,
}) => {
  await openTab(page);
  await openCard(page, 'chunking');
  const chunkingNote = page.getByTestId('chunking-file-size-note');
  await expect(chunkingNote).toBeVisible();
  await expect(chunkingNote).toContainText(/smaller of the two ceilings wins/i);
  await expect(page.getByText('Chunking file-size ceiling (bytes)')).toBeVisible();
  const chunkingText = await chunkingNote.innerText();

  await openCard(page, 'bm25');
  const tokenizationNote = page.getByTestId('tokenization-file-size-note');
  await expect(tokenizationNote).toBeVisible();
  await expect(tokenizationNote).toContainText(/smaller of the two ceilings wins/i);
  await expect(page.getByText('Indexing file-size ceiling (MB)')).toBeVisible();

  // Same computed sentence in both places: one effective limit, stated once, shown twice.
  expect(await tokenizationNote.innerText()).toBe(chunkingText);
});

test('Force reindex says that it destroys the current index', async ({ page }) => {
  await openTab(page);
  const toggle = page.getByTestId('force-reindex-toggle');
  await expect(toggle).toBeVisible();
  await expect(toggle).toContainText(/destructive/i);
  await expect(toggle).toContainText(/clears the current index before rebuilding/i);
});

test('the Figures header points at where the estimate really is', async ({ page }) => {
  await openTab(page);
  await openCard(page, 'figures');
  const card = page.getByTestId('figures-card');
  await expect(card).toBeVisible();

  const text = await card.innerText();
  expect(text).not.toMatch(/estimate below/i);
  expect(text).toMatch(/Index Now prices them/i);
});
