// LineageMeta alias controls, end to end and corpus-scoped.
//
// Codex review of #85 (LineageMeta.tsx): alias state must belong to the corpus
// the buttons write to — a lookup for a previous scope may never land on the
// current one, a failed lookup shows no assignments, and a scope change drops
// the old state before looking up anew. The operator-visible contract proven
// here, with no request interception: on the Benchmark tab a real run over the
// isolated corpus exposes the LINEAGE panel; "Set canary" writes the alias, the
// badge and toast reflect it, the API agrees, and a second corpus sees none of it.
import { expect, test } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser, provisionExhaustiveCorpus } from './corpus_fixture';
import { ACCEPTANCE_CORPUS_PROBES } from './suite_config';

const BENCHMARK_MODELS = ['openai.gpt-4.1-nano', 'openai.gpt-5.6-luna'];

type AliasRow = { alias: string; bundle_id: string };

async function listAliases(request: { get: (url: string) => Promise<{ ok(): boolean; status(): number; json(): Promise<unknown> }> }, corpusId: string): Promise<AliasRow[]> {
  const response = await request.get(`${API_BASE}/lineage/aliases?corpus_id=${encodeURIComponent(corpusId)}`);
  expect(response.ok(), `GET /api/lineage/aliases for ${corpusId} -> ${response.status()}`).toBeTruthy();
  const payload = (await response.json()) as { aliases?: AliasRow[] };
  return payload.aliases || [];
}

test('lineage alias controls write, persist and stay scoped to the active corpus', async ({ page, request }) => {
  test.setTimeout(8 * 60 * 1000);
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));
  const failedRequests: string[] = [];
  page.on('response', (response) => {
    if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.request().method()} ${response.url()}`);
  });

  // Indexed (deterministic embeddings, seconds): the shell polls index stats for
  // the active corpus and an unindexed corpus answers 404, which would fail the
  // strict no-failed-request assertion below.
  const corpus = await provisionExhaustiveCorpus(request, { index: true });
  const other = await provisionExhaustiveCorpus(request, { index: true });
  try {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto(`benchmark?corpus=${encodeURIComponent(corpus.corpusId)}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('benchmark-tab')).toBeVisible({ timeout: 60_000 });

    for (const alias of BENCHMARK_MODELS) {
      // Each model row is a <label> whose title carries the gateway alias.
      const row = page.locator('label', { has: page.locator(`[title*="alias ${alias} "], [title$="alias ${alias}"]`) }).first();
      await expect(row, `benchmark model row for ${alias}`).toBeVisible({ timeout: 60_000 });
      await row.locator('input[type="checkbox"]').check();
    }
    await page.locator('textarea').first().fill(ACCEPTANCE_CORPUS_PROBES[0].question);
    const run = page.getByTestId('benchmark-run');
    await expect(run).toBeEnabled();
    await run.click();

    // The run attaches to the corpus bundle; LineageMeta renders with no alias yet.
    const setCanary = page.getByTestId('lineage-set-canary');
    await expect(setCanary).toBeVisible({ timeout: 4 * 60 * 1000 });
    await expect(setCanary).toHaveAttribute('aria-pressed', 'false');
    await expect(setCanary).toBeEnabled();
    // A corpus always carries the auto-maintained `current` alias; `canary` is the operator's.
    const canaryOf = (rows: AliasRow[]) => rows.filter((row) => row.alias === 'canary');
    expect(canaryOf(await listAliases(request, corpus.corpusId))).toEqual([]);

    await setCanary.click();
    await expect(page.locator('.toast.toast-success')).toContainText('"canary" now points at', { timeout: 30_000 });
    await expect(setCanary).toHaveAttribute('aria-pressed', 'true', { timeout: 30_000 });
    await expect(setCanary).toBeDisabled();
    await expect(setCanary).toHaveText(/canary/);

    // Persisted, and pointing at the bundle the run attached to.
    const resultsResp = await request.get(`${API_BASE}/benchmark/results?corpus_id=${encodeURIComponent(corpus.corpusId)}`);
    expect(resultsResp.ok()).toBeTruthy();
    const results = (await resultsResp.json()) as { runs?: Array<{ bundle_id?: string | null }> };
    const runBundle = String(results.runs?.[0]?.bundle_id || '');
    expect(runBundle, 'latest benchmark run carries a bundle id').not.toEqual('');
    const canary = canaryOf(await listAliases(request, corpus.corpusId));
    expect(canary).toHaveLength(1);
    expect(canary[0].bundle_id).toEqual(runBundle);

    // M-112: the middle-truncated bundle id in the LINEAGE panel stays operable
    // -- its copy control carries the FULL id (also the hover value), and one
    // click copies the whole id to the clipboard, not the truncated display.
    await page.context().grantPermissions(['clipboard-write']);
    const copyBundle = page.getByTestId('lineage-copy-current-bundle');
    await expect(copyBundle).toBeVisible();
    // The copy control targets the WHOLE id (also the hover value), not the
    // truncated display, and the truncated text really is shorter than the full.
    expect(await copyBundle.getAttribute('aria-label')).toContain(runBundle);
    const shownId = (await copyBundle.locator('xpath=preceding-sibling::span[1]').innerText()).trim();
    expect(runBundle.startsWith(shownId.split('...')[0])).toBeTruthy();
    expect(shownId.length).toBeLessThan(runBundle.length);
    // Copying succeeds (the success toast only appears when writeText resolves).
    await copyBundle.click();
    await expect(
      page.locator('.toast.toast-success').filter({ hasText: 'copied to the clipboard' }),
    ).toBeVisible({ timeout: 30_000 });

    // Scope: the alias belongs to this corpus only.
    expect(canaryOf(await listAliases(request, other.corpusId))).toEqual([]);

    // Reload with the other corpus active: the page must not show this corpus's
    // alias state (the benchmark panel is empty again; no alias badge exists).
    await activateCorpusInBrowser(page, other.corpusId);
    await page.goto(`benchmark?corpus=${encodeURIComponent(other.corpusId)}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('benchmark-tab')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('lineage-set-canary')).toHaveCount(0);

    expect(failedRequests, `failed requests: ${failedRequests.join(' | ')}`).toEqual([]);
    expect(consoleErrors, `console errors: ${consoleErrors.join(' | ')}`).toEqual([]);
  } finally {
    await other.dispose();
    await corpus.dispose();
  }
});
