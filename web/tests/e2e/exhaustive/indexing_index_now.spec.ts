// Index Now: the consent gate, for every corpus.
//
// The drive found the Indexing tab's primary action dead for two of four corpora — no
// dialog, no estimate line, no error, no toast — and found that when the estimate call
// fails the handler proceeds STRAIGHT to the run, skipping the confirmation the operator
// is supposed to give before any embedding or vision spend.
//
// Both corpora here are provisioned by this spec and disposed afterwards; no production
// corpus is clicked, and no test in this file ever confirms the dialog, so no index run
// is started by the UI.
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  API_BASE,
  acceptanceCorpusPath,
  provisionExhaustiveCorpus,
  uniqueCorpusId,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(5 * 60 * 1000);

let healthy: ExhaustiveCorpus;
/** A registered corpus whose path no longer resolves — recall_default's shape (its
 *  `data/recall` is relative and resolves nowhere), which makes POST /api/index/estimate
 *  answer 422 `repo_path not found`. */
let unresolvable: { corpusId: string; dispose: (ctx?: APIRequestContext) => Promise<void> };

async function openIndexing(page: Page, corpusId: string): Promise<void> {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('index-now-button')).toBeVisible();
  // The corpus registry has to be loaded before the button means anything: the path comes
  // from it, and an unloaded registry is one of the ways this button goes quietly dead.
  await expect
    .poll(async () => page.getByTestId('index-now-button').isEnabled(), { timeout: 30_000 })
    .toBe(true);
}

test.beforeAll(async ({ request }) => {
  healthy = await provisionExhaustiveCorpus(request);
  const corpusId = uniqueCorpusId();
  // Registration insists on a real directory, so make one, register it, then take it away:
  // the estimate then answers 422 exactly as it does for the recall corpus.
  const vanishing = mkdtempSync(path.join(os.tmpdir(), 'ragweld-vanishing-'));
  writeFileSync(path.join(vanishing, 'note.md'), '# placeholder\n', 'utf-8');
  const created = await request.post(`${API_BASE}/corpora`, {
    data: { corpus_id: corpusId, name: corpusId, path: vanishing },
  });
  expect(created.ok(), `POST /api/corpora (${corpusId}) -> ${created.status()}`).toBe(true);
  rmSync(vanishing, { recursive: true, force: true });
  unresolvable = {
    corpusId,
    dispose: async (ctx: APIRequestContext = request) => {
      const response = await ctx.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`);
      expect([200, 204, 404]).toContain(response.status());
    },
  };
});

test.afterAll(async ({ request }) => {
  await unresolvable?.dispose(request);
  await healthy?.dispose(request);
});

test('the estimate dialog opens for a corpus whose estimate answers 200', async ({ page }) => {
  await openIndexing(page, healthy.corpusId);

  const estimate = page.waitForResponse(
    (response) => response.url().includes('/api/index/estimate') && response.request().method() === 'POST'
  );
  await page.getByTestId('index-now-button').click();
  expect((await estimate).status()).toBe(200);

  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId('confirm-dialog-message')).toContainText('Chunks (est)');
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).toHaveCount(0);
});

test('a second Index Now in the same page session still opens the dialog', async ({ page }) => {
  // The dialog helper serializes every confirmation through one module-level promise chain,
  // so a first dialog that never settled would leave every later one hanging silently. This
  // is the drive's symptom (works on the corpora visited first, dead on the ones after).
  await openIndexing(page, healthy.corpusId);

  for (const attempt of [1, 2, 3]) {
    await page.getByTestId('index-now-button').click();
    await expect(
      page.getByTestId('confirm-dialog'),
      `dialog missing on Index Now attempt ${attempt}`
    ).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('confirm-dialog-cancel').click();
    await expect(page.getByTestId('confirm-dialog')).toHaveCount(0);
  }
});

test('a failed estimate blocks the run with an actionable error instead of skipping the gate', async ({
  page,
  request,
}) => {
  await openIndexing(page, unresolvable.corpusId);

  const estimate = page.waitForResponse(
    (response) => response.url().includes('/api/index/estimate') && response.request().method() === 'POST'
  );
  const indexPosts: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/index(\?|$)/.test(req.url())) indexPosts.push(req.url());
  });
  await page.getByTestId('index-now-button').click();
  expect((await estimate).status()).toBe(422);

  // The operator is told why, in the page, and the run does NOT start.
  const banner = page.getByTestId('index-error-banner');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(/estimate/i);
  await expect(banner).toContainText(unresolvable.corpusId);
  await expect(page.getByTestId('confirm-dialog')).toHaveCount(0);

  await page.waitForTimeout(1500);
  expect(indexPosts, 'a failed estimate must never reach POST /api/index').toEqual([]);
  const latest = await request.get(`${API_BASE}/index/${encodeURIComponent(unresolvable.corpusId)}/runs/latest`);
  expect(latest.status(), 'no index run may exist for a corpus whose estimate failed').toBe(404);
});
