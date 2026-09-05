// Real Graph API + disposable PG/Neo4j, with server-side scheduling of complete
// original responses. No browser request interception or replacement payloads.
import { createHash } from 'node:crypto';
import { strict as assert } from 'node:assert';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { activateCorpusInBrowser } from './corpus_fixture';

const CONTROL = process.env.GRAPH_ORDERING_FIXTURE_URL;
if (CONTROL && !/^http:\/\/127\.0\.0\.1:58131$/.test(CONTROL)) {
  throw new Error('Run with the explicit loopback Graph ordering fixture on 58131');
}
if (CONTROL) {
  assert(process.platform === 'linux' && process.cwd().startsWith('/var/tmp/'), 'Use a private LXC overlay');
  for (const [key, expected] of [
    ['EXHAUSTIVE_API_BASE_URL', 'http://127.0.0.1:58131/api'],
    ['PLAYWRIGHT_WEB_BASE_URL', 'http://127.0.0.1:55131/web'],
  ]) {
    assert.equal(process.env[key]?.replace(/\/$/, ''), expected, `${key} must explicitly select the private fixture`);
  }
}
if (!CONTROL && /^(1|true|yes|on)$/i.test(process.env.RAGWELD_STRICT_INTEGRATION || '')) {
  throw new Error('Strict Graph ordering acceptance requires GRAPH_ORDERING_FIXTURE_URL');
}
test.skip(!CONTROL, 'Requires the dedicated real Graph ordering API/store fixture');

test.describe.configure({ mode: 'serial' });
test.beforeAll(async ({ request }) => {
  await expect.poll(async () => {
    try {
      const response = await request.get(`${CONTROL}/__graph_fixture__/ready`);
      return response.ok() ? (await response.json()).fixture : null;
    } catch {
      return null;
    }
  }, { timeout: 30_000 }).toBe('real-graph-ordering');
  // Check both the direct API and the browser's actual proxy before any seed.
  for (const endpoint of [process.env.EXHAUSTIVE_API_BASE_URL!, 'http://127.0.0.1:55131/api']) {
    const response = await request.get(`${endpoint}/config`);
    expect(response.ok()).toBe(true);
    const config = await response.json();
    const pg = new URL(config.indexing.postgres_url.replace('[REDACTED]', 'redacted'));
    expect([pg.hostname, pg.port, pg.pathname]).toEqual(['127.0.0.1', '55439', '/astra_graph_ordering']);
    expect(config.graph_storage.neo4j_uri).toBe('bolt://127.0.0.1:57689');
    expect(config.qdrant.url).toBe('http://127.0.0.1:56339');
  }
});

async function hold(request: APIRequestContext, path: string, query: string | null = null): Promise<string> {
  const response = await request.post(`${CONTROL}/__graph_fixture__/hold`, { data: { path, query } });
  expect(response.ok()).toBe(true);
  return (await response.json()).token;
}

async function captured(request: APIRequestContext, token: string): Promise<void> {
  await expect.poll(async () => (await (await request.get(`${CONTROL}/__graph_fixture__/state/${token}`)).json()).captured).toBe(true);
}

async function release(request: APIRequestContext, page: Page, token: string): Promise<void> {
  const state = await (await request.get(`${CONTROL}/__graph_fixture__/state/${token}`)).json();
  const delivered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === state.path && url.searchParams.get('q') === state.query;
  });
  const response = await request.post(`${CONTROL}/__graph_fixture__/release/${token}`);
  expect(response.ok()).toBe(true);
  const original = await delivered;
  expect(original.status()).toBe(state.status);
  expect(createHash('sha256').update(await original.body()).digest('hex')).toBe(state.sha256);
  await expect.poll(async () => (await (await request.get(`${CONTROL}/__graph_fixture__/state/${token}`)).json()).delivered).toBe(true);
  // Observe the rendered state after the response's React update has painted.
  await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function search(page: Page, query: string): Promise<void> {
  await page.getByTestId('graph-entity-search').fill(query);
  await page.getByTestId('graph-search-btn').click();
}

async function expectHarvard(page: Page): Promise<void> {
  await expect(page.getByTestId('graph-entity-search')).toHaveValue('Harvard');
  await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(1);
  await expect(page.getByTestId('graph-entities')).toContainText('Harvard Test Observatory');
  await expect(page.getByTestId('graph-entity-details')).toHaveCount(0);
  await expect(page.getByTestId('graph-community-details')).toHaveCount(0);
  await expect(page.getByTestId('graph-error')).toHaveCount(0);
}

for (const older of ['reset', 'node', 'community', 'search', 'corpus'] as const) {
  test(`newer graph intent survives a late ${older} response`, async ({ page, request, baseURL }, testInfo) => {
    const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
    expect(seeded.ok()).toBe(true);
    const [corpusA, corpusB] = (await seeded.json()).corpora as string[];
    const consoleErrors: string[] = [];
    page.on('pageerror', (error) => consoleErrors.push(error.message));
    try {
      await activateCorpusInBrowser(page, corpusA);
      await page.goto(new URL(`rag?subtab=graph&corpus=${corpusA}`, baseURL).toString());
      await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
      await expect(page.getByTestId('graph-communities').locator('> button')).toHaveCount(2);
      expect(await page.title()).toMatch(/ragweld|tribrid/i);
      await expect(page.locator('vite-error-overlay')).toHaveCount(0);
      if (older === 'reset') {
        await page.getByTestId('graph-community-0').click();
        await expect(page.getByTestId('graph-entity-count')).toContainText('in this community');
        await page.getByTestId('graph-entity-harvard').click();
        await expect(page.getByTestId('graph-entity-count')).toContainText('in this neighborhood');
      }
      const route = older === 'node' ? 'entity/neighbors'
        : older === 'community' ? 'community/0/subgraph' : 'subgraph';
      const tickets = [await hold(request, `/api/graph/${corpusA}/${route}`, older === 'search' ? 'Mira' : null)];
      if (older === 'corpus') {
        tickets.push(await hold(request, `/api/graph/${corpusA}/stats`));
        tickets.push(await hold(request, `/api/graph/${corpusA}/communities`));
      }
      if (older === 'node') await page.getByTestId('graph-entity-mira').click();
      else if (older === 'community') await page.getByTestId('graph-community-0').click();
      else if (older === 'search') await search(page, 'Mira');
      else await page.getByTestId('graph-clear-btn').click();
      for (const token of tickets) await captured(request, token);
      if (older === 'corpus') {
        await page.getByTestId('graph-corpus-select').selectOption(corpusB);
        await expect(page.getByTestId('graph-entities')).toContainText('Orion research institute');
      } else {
        await search(page, 'Harvard');
        await expectHarvard(page);
      }
      for (const token of tickets) await release(request, page, token);
      if (older === 'corpus') {
        await expect(page.getByTestId('graph-corpus-select')).toHaveValue(corpusB);
        await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(1);
        await expect(page.getByTestId('graph-entities')).toContainText('Orion research institute');
        await expect(page.getByTestId('graph-communities').locator('> button')).toHaveCount(1);
        await expect(page.getByTestId('graph-communities')).toContainText('Orion research institute');
      } else await expectHarvard(page);
      expect(consoleErrors).toEqual([]);
      await page.screenshot({ path: testInfo.outputPath(`${older}-latest-view.png`) });
    } finally {
      const cleaned = await request.post(`${CONTROL}/__graph_fixture__/cleanup`);
      expect(cleaned.ok()).toBe(true);
    }
  });
}

test('an older completion cannot clear the newer search loading state', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus] = (await seeded.json()).corpora as string[];
  try {
    await activateCorpusInBrowser(page, corpus);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
    await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
    const reset = await hold(request, `/api/graph/${corpus}/subgraph`);
    await page.getByTestId('graph-clear-btn').click();
    await captured(request, reset);
    const newer = await hold(request, `/api/graph/${corpus}/subgraph`, 'Harvard');
    await search(page, 'Harvard');
    await captured(request, newer);
    await release(request, page, reset);
    await expect(page.getByTestId('graph-loading')).toHaveText('Loading…');
    await release(request, page, newer);
    await expectHarvard(page);
    await expect(page.getByTestId('graph-loading')).toHaveText('');
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('an older real entity 404 cannot replace the newer successful search', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus] = (await seeded.json()).corpora as string[];
  try {
    await activateCorpusInBrowser(page, corpus);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
    await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
    const removed = await request.post(`${CONTROL}/__graph_fixture__/remove-entity`, { data: { corpus, entity: 'mira' } });
    expect(removed.ok()).toBe(true);
    const stale = await hold(request, `/api/graph/${corpus}/entity/neighbors`);
    await page.getByTestId('graph-entity-mira').click();
    await captured(request, stale);
    const state = await (await request.get(`${CONTROL}/__graph_fixture__/state/${stale}`)).json();
    expect(state.status).toBe(404);
    await search(page, 'Harvard');
    await expectHarvard(page);
    await release(request, page, stale);
    await expectHarvard(page);
    await expect(page.getByText('Could not expand this entity', { exact: false })).toHaveCount(0);
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

async function expectNoCorpusGraph(page: Page): Promise<void> {
  await expect(page.getByTestId('graph-corpus-select')).toHaveValue('');
  await expect(page.getByTestId('graph-corpus-select')).toContainText('No corpora');
  await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(0);
  await expect(page.getByTestId('graph-communities').locator('> button')).toHaveCount(0);
  await expect(page.getByTestId('graph-stats')).toHaveCount(0);
  await expect(page.getByTestId('graph-stats-empty')).toBeVisible();
  await expect(page.getByTestId('graph-entity-details')).toHaveCount(0);
  await expect(page.getByTestId('graph-community-details')).toHaveCount(0);
  await expect(page.getByTestId('graph-error')).toHaveCount(0);
  await expect(page.getByTestId('graph-loading')).toHaveText('');
  for (const kind of ['entities', 'relationships', 'json']) {
    await expect(page.getByTestId(`graph-export-${kind}`)).toBeDisabled();
  }
  await page.getByTestId('graph-view-visualization').click();
  await expect(page.getByTestId('graph-export-png')).toBeDisabled();
  await page.getByTestId('graph-view-table').click();
}

for (const transition of ['delete', 'refresh'] as const) {
  test(`last corpus ${transition} clears graph data, selection and errors`, async ({ page, request, baseURL }, testInfo) => {
    const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
    expect(seeded.ok()).toBe(true);
    const [corpus, other] = (await seeded.json()).corpora as string[];
    try {
      // Remove the other owned corpus through the real API before this page loads.
      expect((await request.delete(`${CONTROL}/api/corpora/${other}`)).ok()).toBe(true);
      await activateCorpusInBrowser(page, corpus);
      await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
      await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
      await page.getByTestId('graph-view-table').click();
      await page.getByTestId('graph-community-0').click();
      await expect(page.getByTestId('graph-community-details')).toBeVisible();

      let stale: string | null = null;
      if (transition === 'delete') {
        await page.getByTestId('graph-entity-harvard').click();
        await expect(page.getByTestId('graph-entity-details')).toBeVisible();
        stale = await hold(request, `/api/graph/${corpus}/subgraph`, 'Harvard');
        await search(page, 'Harvard');
        await captured(request, stale);
        await page.getByTestId('topbar-corpus').click();
        await page.getByTestId(`corpus-delete-${corpus}`).click();
        await page.getByTestId('confirm-dialog-accept').click();
      } else {
        // External deletion leaves the displayed selection intact until registry
        // refresh. A real rejected search establishes an error to clear too.
        expect((await request.delete(`${CONTROL}/api/corpora/${corpus}`)).ok()).toBe(true);
        await search(page, 'Harvard');
        await expect(page.getByTestId('graph-error')).toContainText('Corpus not found');
        await page.getByTestId('topbar-corpus').click();
        await page.getByTestId('corpus-registry-refresh').click();
      }
      await expect(page.getByTestId('corpus-registry-empty')).toBeVisible();
      await page.getByTestId('corpus-registry-close').click();
      await expectNoCorpusGraph(page);
      if (stale) {
        await release(request, page, stale);
        await expectNoCorpusGraph(page);
      }
      await page.screenshot({ path: testInfo.outputPath(`last-corpus-${transition}.png`) });
    } finally {
      expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
    }
  });
}
