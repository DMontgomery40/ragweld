import { expect, test } from '@playwright/test';

import {
  API_BASE,
  activateCorpusInBrowser,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test('Dashboard default subtab does not trigger storage startup requests', async ({ page, baseURL }) => {
  const observedApiPaths = new Set<string>();

  page.on('request', (request) => {
    const url = request.url();
    if (!url.includes('/api/')) return;
    try {
      observedApiPaths.add(new URL(url).pathname);
    } catch {
      // Ignore malformed URLs in diagnostics.
    }
  });

  await page.goto(new URL('dashboard', baseURL).toString());
  await page.waitForURL(/\/dashboard(?:\?|$)/);
  await page.waitForTimeout(1500);

  const storageRequests = [...observedApiPaths].filter((path) => path.includes('/api/index/stats'));
  expect(storageRequests).toEqual([]);
});

test('Dashboard monitoring deep-link does not trigger system status startup requests', async ({ page, baseURL }) => {
  const observedApiPaths = new Set<string>();

  page.on('request', (request) => {
    const url = request.url();
    if (!url.includes('/api/')) return;
    try {
      observedApiPaths.add(new URL(url).pathname);
    } catch {
      // Ignore malformed URLs in diagnostics.
    }
  });

  await page.goto(new URL('dashboard?subtab=monitoring', baseURL).toString());
  await page.waitForURL(/\/dashboard\?subtab=monitoring(?:&|$)/);
  await page.waitForTimeout(1500);

  const systemStatusRequests = [...observedApiPaths].filter((path) =>
    ['/api/mcp/status', '/api/docker/status'].includes(path),
  );
  expect(systemStatusRequests).toEqual([]);
});

// The dashboard's "Recent Index Runs" panel replaced a dead "Top Folders (Last 5 Days)" table
// whose only setter was setTopFolders([]). Its own describe block with its own fixture: the two
// request-observation tests above run in under a second and must not inherit an indexing wait.
test.describe('Recent index runs panel', () => {
  test.describe.configure({ mode: 'serial' });

  let corpus: ExhaustiveCorpus | null = null;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request, { index: true });
  });

  test.afterAll(async ({ request }) => {
    if (corpus) await corpus.dispose(request);
    corpus = null;
  });

  test('lists the freshly indexed corpus with its real chunk count', async ({ page, baseURL }) => {
    const provisioned = corpus;
    expect(provisioned, 'the corpus fixture must have provisioned').not.toBeNull();
    const corpusId = provisioned!.corpusId;

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard', baseURL).toString());
    await page.waitForURL(/\/dashboard(?:\?|$)/);

    const panel = page.getByTestId('dash-recent-runs');
    await expect(panel).toBeVisible();

    const row = page.getByTestId(`dash-recent-run-${corpusId}`);
    await expect(row).toBeVisible({ timeout: 30_000 });
    await expect(row).toContainText('complete');

    // Chunks come from the run record the indexer persisted, not from a placeholder: the panel
    // this replaced could only ever say "No recent indexing metrics available."
    const chunkText = (await row.locator('td').nth(3).innerText()).trim();
    const chunks = Number(chunkText.replace(/[^0-9]/g, ''));
    expect(Number.isFinite(chunks)).toBe(true);
    expect(chunks).toBeGreaterThan(0);

    // The acceptance fixture has no PDFs, so this run described no figures: the column stays
    // empty rather than printing a zero for every corpus indexed before figures existed.
    await expect(row.locator('td').nth(4)).toHaveText('—');
  });

  // The chat Recall corpus is registered by the runtime and indexes through its own path, so
  // it has no persisted index run: the panel listed it as "never indexed" forever.
  test('omits the runtime-managed Recall corpus', async ({ page, request, baseURL }) => {
    const provisioned = corpus;
    expect(provisioned, 'the corpus fixture must have provisioned').not.toBeNull();
    const corpusId = provisioned!.corpusId;

    // The API has to actually be serving the internal marker, or the assertion below is
    // vacuous: a corpus that is simply absent would also not be rendered.
    const listed = await request.get(`${API_BASE}/corpora`);
    expect(listed.ok()).toBe(true);
    const corpora = (await listed.json()) as Array<{ corpus_id: string; internal?: boolean }>;
    const recall = corpora.find((c) => c.corpus_id === 'recall_default');
    expect(recall, 'the Recall corpus must exist for this assertion to mean anything').toBeTruthy();
    expect(recall!.internal).toBe(true);
    expect(corpora.find((c) => c.corpus_id === corpusId)?.internal).toBe(false);

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard', baseURL).toString());
    await page.waitForURL(/\/dashboard(?:\?|$)/);

    await expect(page.getByTestId('dash-recent-runs')).toBeVisible();
    // The operator's own corpus is still listed, so the filter did not empty the panel.
    await expect(page.getByTestId(`dash-recent-run-${corpusId}`)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('dash-recent-run-recall_default')).toHaveCount(0);
  });
});

// M-15: the Recent Alerts panel rendered the bare string "Failed to load" because
// GET /api/webhooks/alertmanager/status has never existed on the server. These tests
// drive the real panel against the real Alertmanager the API is configured with.
test.describe('Dashboard monitoring alerts panel', () => {
  test('renders what Alertmanager holds, never "Failed to load"', async ({ page, baseURL, request }) => {
    const direct = await request.get(`${API_BASE}/observability/alerts`);
    expect(direct.status(), await direct.text()).toBe(200);
    const payload = await direct.json();

    const statuses: number[] = [];
    page.on('response', (response) => {
      if (new URL(response.url()).pathname.endsWith('/observability/alerts')) {
        statuses.push(response.status());
      }
    });

    await page.goto(new URL('dashboard?subtab=monitoring', baseURL).toString());
    const panel = page.getByTestId('dash-alerts-panel');
    await expect(panel).toBeVisible();

    expect(statuses).not.toContain(404);
    await expect(panel).not.toContainText('Failed to load');
    await expect(page.getByTestId('dash-alerts-error')).toHaveCount(0);

    // Non-vacuous: the panel shows exactly the alerts Alertmanager is holding.
    const rows = page.getByTestId('dash-alert-row');
    await expect(rows).toHaveCount(payload.alerts.length);
    if (payload.alerts.length > 0) {
      await expect(panel).toContainText(String(payload.alerts[0].name));
      await expect(panel).toContainText(`${payload.firing_count} firing of ${payload.total_count}`);
    } else {
      await expect(page.getByTestId('dash-alerts-empty')).toBeVisible();
    }
  });

  test('offers a route to the real monitoring surface', async ({ page, baseURL }) => {
    await page.goto(new URL('dashboard?subtab=monitoring', baseURL).toString());
    const link = page.getByTestId('dash-alerts-monitoring-link');
    await expect(link).toBeVisible();

    await link.click();
    await page.waitForURL(/\/infrastructure\?subtab=monitoring(?:&|$)/);
    await expect(page.getByTestId('alert-rules-panel')).toBeVisible();
  });
});
