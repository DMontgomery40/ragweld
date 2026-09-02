import { expect, test } from '@playwright/test';

import {
  API_BASE,
  activateCorpusInBrowser,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

// Wave 2b, lane `dashboard` (T18): dead controls, debug output and information design.
// Each test drives the real deployment — no route mocking, no stubbed data.

// M-105 / M-140 / A-38: the top-bar HEALTH pill was a dead control — a button whose click
// only re-fired a health probe and ticked a bare, date-less timestamp. It now opens a
// component-status popover backed by the /api/ready dependency breakdown and offers a jump to
// System Status.
test.describe('Top-bar health pill', () => {
  test('opens the /api/ready dependency breakdown and routes to System Status', async ({ page, baseURL, request }) => {
    // Precondition, so the DOM assertions are not vacuous: /api/ready answers with a real
    // per-dependency map (200 ready, or 503 not-ready — same shape either way).
    const ready = await request.get(`${API_BASE}/ready`);
    expect([200, 503]).toContain(ready.status());
    const readyBody = (await ready.json()) as { dependencies: Record<string, { ok: boolean }> };
    const depKeys = Object.keys(readyBody.dependencies);
    expect(depKeys.length, 'readiness must report at least one dependency').toBeGreaterThan(0);

    await page.goto(new URL('dashboard', baseURL).toString());
    await page.waitForURL(/\/dashboard(?:\?|$)/);

    const pill = page.locator('#btn-health');
    await expect(pill).toBeVisible();

    // The status text carries a status word and a staleness, not a bare time-of-day (M-140).
    const statusText = (await page.locator('#health-status').innerText()).trim();
    expect(statusText, `health status was "${statusText}"`).toMatch(/^(OK|Not OK|—)\b/);

    // Clicking is no longer a no-op: a real popover appears.
    await expect(page.getByTestId('health-popover')).toHaveCount(0);
    await pill.click();
    const popover = page.getByTestId('health-popover');
    await expect(popover).toBeVisible();

    // Every dependency the API reported has a row in the popover.
    for (const key of depKeys) {
      await expect(page.getByTestId(`health-dep-${key}`)).toBeVisible();
    }

    // And it offers the jump to the full System Status surface.
    const openStatus = page.getByTestId('health-open-system-status');
    await expect(openStatus).toBeVisible();
    await openStatus.click();
    await page.waitForURL(/\/dashboard\?subtab=system(?:&|$)/);
    await expect(page.locator('#tab-dashboard-system')).toBeVisible();
    // The popover closed on navigation.
    await expect(page.getByTestId('health-popover')).toHaveCount(0);
  });

  test('Escape closes the popover', async ({ page, baseURL }) => {
    await page.goto(new URL('dashboard', baseURL).toString());
    await page.locator('#btn-health').click();
    await expect(page.getByTestId('health-popover')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('health-popover')).toHaveCount(0);
  });

  // S7: every page other than the Dashboard read "— · not checked yet". The Dashboard's System
  // Status subtab probes health on its own, while the app-wide poll that feeds the chip was gated
  // on the tab being visible from its very first tick, so a page opened in a background tab (or
  // driven by an automation tab, which Chrome reports as hidden) never got a first reading. The
  // first probe now runs on mount regardless; only the recurring poll follows visibility.
  test('a page opened in a background tab still gets one health reading', async ({ page, baseURL }) => {
    await page.addInitScript(() => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => 'hidden' });
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    });
    await page.goto(new URL('rag', baseURL).toString());
    await page.waitForURL(/\/rag(?:\?|$)/);
    await expect(page.locator('#tab-rag, #tab-retrieval, main').first()).toBeVisible();

    const status = page.locator('#health-status');
    await expect(status).toBeVisible();
    await expect(status, 'the chip on a hidden RAG tab never got its first reading').toHaveText(/^(OK|Not OK) · /, {
      timeout: 15_000,
    });
    await expect(status).not.toContainText('not checked yet');
  });

  test('the health reading is app-wide: it survives navigating between pages', async ({ page, baseURL }) => {
    await page.goto(new URL('dashboard', baseURL).toString());
    await page.waitForURL(/\/dashboard(?:\?|$)/);
    const status = page.locator('#health-status');
    await expect(status).toHaveText(/^(OK|Not OK) · /, { timeout: 15_000 });

    // Client-side navigation through the sidebar: the store, not the page, owns the reading.
    for (const label of ['RAG', 'Chat', 'Grafana']) {
      const link = page.getByTestId('tab-bar').getByRole('link', { name: label, exact: true });
      await expect(link).toBeVisible();
      await link.click();
      await expect(status, `chip after navigating to ${label}`).toHaveText(/^(OK|Not OK) · /);
      await expect(status).not.toContainText('not checked yet');
    }
  });
});

// M-153 / A-47: with the dock empty, the header rendered Dock Current / Choose AND the empty
// body rendered its own Dock Current / Choose / Dock Chat, so two identical control sets sat on
// screen at once. There is now one set, in the header.
test('Empty dock shows a single set of controls, not two', async ({ page, baseURL }) => {
  await page.goto(new URL('dashboard', baseURL).toString());
  await page.waitForURL(/\/dashboard(?:\?|$)/);

  // Ensure the empty dock body is what is on screen.
  await page.getByTestId('dock-mode-dock').click();
  await expect(page.getByTestId('dock-empty')).toBeVisible();

  // Exactly one of each control, and none of the old empty-body duplicates.
  await expect(page.getByTestId('dock-current')).toHaveCount(1);
  await expect(page.getByTestId('dock-choose')).toHaveCount(1);
  await expect(page.getByTestId('dock-chat')).toHaveCount(1);
  await expect(page.getByTestId('dock-current-empty')).toHaveCount(0);
  await expect(page.getByTestId('dock-choose-empty')).toHaveCount(0);

  // M-106: the Source segmented position is not dead — clicking it switches the panel to
  // document mode, which shows its own empty state rather than leaving Dock on screen.
  await page.getByTestId('dock-mode-document').click();
  await expect(page.getByTestId('dock-document-empty')).toBeVisible();
  await expect(page.getByTestId('dock-empty')).toHaveCount(0);
});

test.describe('Dashboard information design', () => {
  test.describe.configure({ mode: 'serial' });

  let corpus: ExhaustiveCorpus | null = null;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request, { index: true });
  });

  test.afterAll(async ({ request }) => {
    if (corpus) await corpus.dispose(request);
    corpus = null;
  });

  // M-139: the "Recent Query Traces" table promised a Duration for every row under a subtitle
  // claiming "with timing", but the query log records no per-request timing, so the column was
  // "—" for all 10 rows. The column and the claim are gone; the honest columns remain.
  test('Recent Query Traces shows only the columns it can populate, no Duration', async ({ page, baseURL, request }) => {
    const provisioned = corpus;
    expect(provisioned).not.toBeNull();
    const corpusId = provisioned!.corpusId;

    // Seed one real search so the table has a row to render (the header only exists with rows).
    const search = await request.post(`${API_BASE}/search`, {
      data: {
        query: 'mission summary',
        corpus_id: corpusId,
        top_k: 5,
        include_vector: true,
        include_sparse: true,
        include_graph: false,
        cache_mode: 'bypass',
      },
    });
    expect(search.ok(), `search seed failed: ${search.status()} ${(await search.text()).slice(0, 200)}`).toBe(true);

    // Confirm the trace is visible at the API level before asserting on the DOM (non-vacuous).
    await expect
      .poll(
        async () => {
          const res = await request.get(`${API_BASE}/reranker/logs?limit=400&corpus_id=${encodeURIComponent(corpusId)}`);
          if (!res.ok()) return 0;
          const logs = ((await res.json()) as { logs?: Array<Record<string, unknown>> }).logs ?? [];
          return logs.filter((r) => ['chat', 'search', 'query'].includes(String(r.kind || r.type || '').toLowerCase())).length;
        },
        { timeout: 20_000, intervals: [500, 1000, 2000] },
      )
      .toBeGreaterThan(0);

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard?subtab=monitoring', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=monitoring(?:&|$)/);

    const tracesSection = page.locator('.settings-section', { hasText: 'Recent Query Traces' });
    await expect(tracesSection).toBeVisible();
    // The "with timing" promise the table could not keep is gone.
    await expect(tracesSection).not.toContainText('with timing');

    const headers = tracesSection.locator('thead th');
    await expect(headers).toHaveCount(3);
    // The third column is the corpus (7485b0f6 renamed the legacy "Repo" label; the product is corpus-first).
    await expect(headers).toHaveText(['Timestamp', 'Query', 'Corpus']);
    await expect(tracesSection.locator('thead')).not.toContainText('Duration');

    // The rows carry a date, not a bare time-of-day, so a list that spans days cannot read as
    // if it ran backwards (M-140). toLocaleString() always includes a date separator.
    const firstCell = (await tracesSection.locator('tbody tr').first().locator('td').first().innerText()).trim();
    expect(firstCell, `timestamp cell was "${firstCell}"`).toMatch(/\d{1,4}[/-]\d{1,2}[/-]\d{1,4}|\d{4}/);
  });

  // M-141: a count tile ("QDRANT POINTS 1,315 points") was given a "% of total" against a byte
  // total — a category error that always read 0.0% — while KEYWORDS had no such line, so the
  // tiles disagreed on their own format. Byte tiles keep the percentage; count tiles have none.
  test('Storage breakdown gives no byte percentage to count tiles', async ({ page, baseURL, request }) => {
    const provisioned = corpus;
    expect(provisioned).not.toBeNull();
    const corpusId = provisioned!.corpusId;

    const stats = await request.get(`${API_BASE}/index/stats?corpus_id=${encodeURIComponent(corpusId)}`);
    expect(stats.ok()).toBe(true);
    const statsBody = (await stats.json()) as {
      total_storage: number;
      storage_breakdown: { qdrant_points?: number };
    };
    expect(statsBody.storage_breakdown.qdrant_points ?? 0).toBeGreaterThan(0);

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard?subtab=storage', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=storage(?:&|$)/);

    const grid = page.locator('#tab-dashboard-storage');
    await expect(grid).toBeVisible();

    // The QDRANT POINTS tile still shows its count, but no "% of total" line.
    const pointsTile = grid.getByTestId('storage-tile-qdrant-points');
    await expect(pointsTile).toContainText('points');
    await expect(pointsTile).toHaveAttribute('data-count', 'true');
    await expect(pointsTile).not.toContainText('% of total');

    // KEYWORDS is a count too — also no percentage.
    const keywordsTile = grid.getByTestId('storage-tile-keywords');
    await expect(keywordsTile).toHaveAttribute('data-count', 'true');
    await expect(keywordsTile).not.toContainText('% of total');

    // A byte tile, by contrast, keeps its share line.
    await expect(grid.getByTestId('storage-tile-chunks')).toContainText('% of total');

    // Byte tiles that carry a percentage sum to ~100 (the shares partition the byte total).
    const pcts = await grid.locator('text=/% of total/').allInnerTexts();
    expect(pcts.length, 'at least one byte tile shows a share').toBeGreaterThan(0);
    const sum = pcts.reduce((acc, t) => acc + parseFloat(t), 0);
    expect(sum, `byte-tile shares summed to ${sum}`).toBeGreaterThan(99);
    expect(sum).toBeLessThan(101);
  });

  // S5: the NEO4J STORE tile read "0 B (0.0% of total)" for a corpus whose graph held 8,129
  // nodes. Neo4j 5 Community exposes no store-size source (no dbms.queryJmx, no
  // apoc.monitor.store, no size on SHOW DATABASES) and the data volume is not host-readable, so
  // both dashboard panels now say "n/a" with the reason, give the tile no share of the byte
  // total, and leave it out of the total instead of adding a measured-looking zero.
  test('Neo4j store is reported as unmeasured, not 0 B, on both dashboard panels', async ({ page, baseURL, request }) => {
    const provisioned = corpus;
    expect(provisioned).not.toBeNull();
    const corpusId = provisioned!.corpusId;

    const stats = await request.get(`${API_BASE}/index/stats?corpus_id=${encodeURIComponent(corpusId)}`);
    expect(stats.ok()).toBe(true);
    const statsBody = (await stats.json()) as {
      total_storage: number;
      storage_breakdown: {
        neo4j_store_bytes: number | null;
        neo4j_store_note: string | null;
        postgres_total_bytes: number;
        qdrant_dense_vector_bytes: number;
        total_storage_bytes: number;
      };
    };
    const breakdown = statsBody.storage_breakdown;
    // Deployment truth on this stack: the store cannot be measured, and the API says why.
    expect(breakdown.neo4j_store_bytes, JSON.stringify(breakdown)).toBeNull();
    expect(String(breakdown.neo4j_store_note)).toContain('store-size');
    expect(breakdown.total_storage_bytes).toBe(breakdown.postgres_total_bytes + breakdown.qdrant_dense_vector_bytes);
    expect(statsBody.total_storage).toBe(breakdown.total_storage_bytes);

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard?subtab=storage', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=storage(?:&|$)/);

    const tile = page.locator('#tab-dashboard-storage').getByTestId('storage-tile-neo4j-store');
    await expect(tile).toBeVisible();
    await expect(tile).toHaveAttribute('data-measured', 'false');
    await expect(tile).toContainText('n/a');
    await expect(tile).not.toContainText('0 B');
    await expect(tile).not.toContainText('% of total');
    await expect(tile).toContainText(String(breakdown.neo4j_store_note));

    await page.goto(new URL('dashboard?subtab=system', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=system(?:&|$)/);
    const panel = page.locator('[data-tooltip="DASHBOARD_INDEX_PANEL"]');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    const card = panel.getByTestId('storage-card-neo4j-store');
    await expect(card).toContainText('n/a');
    await expect(card).not.toContainText('0 B');
    await expect(card).toHaveAttribute('title', String(breakdown.neo4j_store_note));
  });

  // M-138: this card labelled the same base-1024 byte figure "MB" while the Storage subtab
  // labelled it "MiB". Both now use binary units, so the two subtabs agree on the same number.
  test('System Status storage uses binary units, matching the Storage subtab', async ({ page, baseURL }) => {
    const provisioned = corpus;
    expect(provisioned).not.toBeNull();
    const corpusId = provisioned!.corpusId;

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard?subtab=system', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=system(?:&|$)/);

    const panel = page.locator('[data-tooltip="DASHBOARD_INDEX_PANEL"]');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    // A real byte value renders (the seeded corpus has chunk bytes), and it is binary-labelled.
    await expect(panel).toContainText(/\d\s?(B|KiB|MiB|GiB)\b/);
    // Never the decimal label on a binary division that M-138 flagged.
    await expect(panel).not.toContainText(/\d\s?(KB|MB|GB)\b/);
  });

  // M-142: the Storage Calculator opened at a hardcoded 5 GiB / 1.3M chunks with no relation to
  // the ~3.5 MiB corpus shown right above it. It now frames itself as a hypothetical planner,
  // seeds from the active corpus, and labels the right panel's independent inputs.
  test('Storage Calculator is a labelled planner seeded from the active corpus', async ({ page, baseURL }) => {
    const provisioned = corpus;
    expect(provisioned).not.toBeNull();
    const corpusId = provisioned!.corpusId;

    await activateCorpusInBrowser(page, corpusId);
    await page.goto(new URL('dashboard?subtab=storage', baseURL).toString());
    await page.waitForURL(/\/dashboard\?subtab=storage(?:&|$)/);

    await expect(page.getByText('Hypothetical capacity planner', { exact: false })).toBeVisible();

    const prefill = page.getByTestId('storage-calc-prefill');
    await expect(prefill).toBeVisible();
    // With an indexed corpus active, the planner says what it was seeded from.
    await expect(prefill).toContainText('Seeded from', { timeout: 30_000 });

    // The right panel's independent inputs are labelled as such.
    await expect(page.getByTestId('storage-calc2-independent-note')).toContainText('independent scenario inputs');
  });
});
