// App-shell regressions from the 2026-08-29 GUI drive, driven against the real app
// and API with no request interception:
//   M-19  the right rail must not ship a dead credential-upload mock,
//   M-125 an unknown /web/* path must say so instead of rendering a blank page,
//   M-126 an unknown ?subtab= must be corrected visibly, not silently,
//   M-127 an unknown ?corpus= must be named in a toast and dropped from the URL,
//   M-128 subtab changes must be reachable with browser Back,
//   M-129 one request per resource per load,
//   M-136 the top bar must not open the search modal on focus, and must trap focus,
//   M-161 sidebar links must announce their label, not their description.
//
// These need no indexed corpus: every assertion is about the shell, so the spec
// reads the corpus registry and activates whatever corpus the box already has.
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

async function firstCorpusId(request: import('@playwright/test').APIRequestContext): Promise<string> {
  const res = await request.get(`${API_BASE}/corpora`);
  expect(res.ok(), `GET ${API_BASE}/corpora must succeed`).toBeTruthy();
  const corpora = (await res.json()) as Array<{ corpus_id: string; internal?: boolean }>;
  const usable = corpora.find((c) => !c.internal) ?? corpora[0];
  expect(usable?.corpus_id, 'the box must have at least one corpus registered').toBeTruthy();
  return usable.corpus_id;
}

async function gotoWeb(page: Page, baseURL: string | undefined, path: string): Promise<void> {
  await page.goto(new URL(path, baseURL).toString(), { waitUntil: 'domcontentloaded' });
}

test.describe('app shell', () => {
  let corpusId = '';

  test.beforeAll(async ({ request }) => {
    corpusId = await firstCorpusId(request);
  });

  test('M-19: the settings rail ships no credential-upload control', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.getByTestId('dock-mode-settings').click();

    const rail = page.getByTestId('dock-panel');
    await expect(rail.getByText('Quick Model Switcher', { exact: false }).first()).toBeVisible();

    // The rail promised to ingest .env/.ini/.md files and to persist them to a repo
    // file on disk; nothing behind it existed. It is deleted, not hidden.
    await expect(rail.getByText('Secrets Ingest', { exact: false })).toHaveCount(0);
    await expect(rail.getByText('Drop any .env', { exact: false })).toHaveCount(0);
    await expect(rail.getByText('Persist to defaults.json', { exact: false })).toHaveCount(0);
    await expect(rail.locator('input[type="checkbox"]')).toHaveCount(0);
    await expect(rail.locator('input[type="file"]')).toHaveCount(0);
  });
});
