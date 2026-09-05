// Real Graph API + disposable PG/Neo4j, with server-side scheduling of complete
// original responses. No browser request interception or replacement payloads.
import { createHash } from 'node:crypto';
import { strict as assert } from 'node:assert';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { activateCorpusInBrowser } from './corpus_fixture';

type RepoStoreModule = typeof import('../../../src/stores/useRepoStore');
type ConfigStoreModule = typeof import('../../../src/stores/useConfigStore');
type ConfigApiModule = typeof import('../../../src/api/config');

declare global {
  interface Window {
    __graphOrderingModules?: Record<string, {
      loaded: boolean;
      module: unknown;
      error: string | null;
      promise: Promise<void> | null;
    }>;
    __graphOrderingScopeResult?: {
      result: Array<number | null> | null;
      error: string | null;
      promise: Promise<void> | null;
    };
  }
}

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

async function failAfterCapture(request: APIRequestContext, path: string): Promise<string> {
  const response = await request.post(`${CONTROL}/__graph_fixture__/fail-after-capture`, {
    data: { path, query: null },
  });
  expect(response.ok()).toBe(true);
  return (await response.json()).token;
}

async function fixtureResponseState(request: APIRequestContext, token: string) {
  return (await (await request.get(`${CONTROL}/__graph_fixture__/state/${token}`)).json()) as {
    captured: boolean;
    delivered: boolean;
    faulted: boolean;
    status: number;
    sha256: string;
    path: string;
    query: string | null;
  };
}

async function captured(request: APIRequestContext, token: string): Promise<void> {
  await expect.poll(async () => (await fixtureResponseState(request, token)).captured).toBe(true);
}

async function release(request: APIRequestContext, page: Page, token: string): Promise<void> {
  const state = await fixtureResponseState(request, token);
  const delivered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === state.path
      && url.searchParams.get(state.path === '/api/config' ? 'corpus_id' : 'q') === state.query;
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
      await expect(page.getByTestId('apply-error')).toHaveCount(0);
      await expect.poll(() => page.evaluate(() => ({
        corpus: new URL(location.href).searchParams.get('corpus'),
        repo: new URL(location.href).searchParams.get('repo'),
        storedCorpus: localStorage.getItem('tribrid_active_corpus'),
        storedRepo: localStorage.getItem('tribrid_active_repo'),
      }))).toEqual({ corpus: null, repo: null, storedCorpus: null, storedRepo: null });
      if (stale) {
        await release(request, page, stale);
        await expectNoCorpusGraph(page);
        await expect(page.getByTestId('apply-error')).toHaveCount(0);
      }
      await page.screenshot({ path: testInfo.outputPath(`last-corpus-${transition}.png`) });
    } finally {
      expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
    }
  });
}

async function loadedModuleUrl(page: Page, sourcePath: string): Promise<string> {
  const expectedUrl = new URL(sourcePath, `${process.env.PLAYWRIGHT_WEB_BASE_URL!.replace(/\/$/, '')}/`).toString();
  const moduleUrl = await page.evaluate((expected) => {
    const target = new URL(expected);
    // A running Vite server can stamp app imports with ?t= after source sync.
    // Importing the bare URL creates another Zustand store, not the app's store.
    const matches = [...new Set(performance.getEntriesByType('resource').map((entry) => entry.name)
      .filter((name) => {
        const actual = new URL(name);
        return actual.origin === target.origin && actual.pathname === target.pathname;
      }))];
    if (matches.length !== 1) throw new Error(`Expected exactly one loaded app module for ${target.pathname}; found ${matches.length}`);
    return matches[0];
  }, expectedUrl);
  // Chromium can collect the promise returned by async CDP evaluation of a dynamic import,
  // producing a misleading "execution context destroyed" error without any navigation. Keep
  // module loading owned by the page, and observe it through synchronous CDP evaluations. This
  // is the exact module already used by the rendered app, including its Vite timestamp.
  await page.evaluate((url) => {
    window.__graphOrderingModules ??= {};
    if (window.__graphOrderingModules[url]) return;
    const entry: NonNullable<Window['__graphOrderingModules']>[string] = {
      loaded: false, module: null, error: null, promise: null,
    };
    window.__graphOrderingModules[url] = entry;
    entry.promise = import(/* @vite-ignore */ url).then((module) => {
      entry.module = module;
      entry.loaded = true;
    }).catch((error: unknown) => {
      entry.error = error instanceof Error ? error.message : String(error);
    });
  }, moduleUrl);
  await expect.poll(() => page.evaluate((url) => {
    const entry = window.__graphOrderingModules![url];
    return { loaded: entry.loaded, error: entry.error };
  }, moduleUrl)).toEqual({ loaded: true, error: null });
  return moduleUrl;
}

async function currentRepoState(page: Page, moduleUrl: string) {
  return page.evaluate((url) => {
    const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
    const state = useRepoStore.getState();
    return {
      repos: state.repos.map((repo: { corpus_id: string }) => repo.corpus_id).sort(),
      activeRepo: state.activeRepo,
      loading: state.loading,
      error: state.error,
      initialized: state.initialized,
    };
  }, moduleUrl);
}

async function forceRepoLoad(page: Page, moduleUrl: string): Promise<void> {
  await page.evaluate((url) => {
    const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
    void useRepoStore.getState().loadRepos({ force: true });
  }, moduleUrl);
}

async function startTrackedRepoLoad(
  page: Page,
  moduleUrl: string,
  label: string,
  force: boolean,
): Promise<void> {
  await page.evaluate(({ url, key, forceLoad }) => {
    const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
    const target = window as typeof window & {
      __graphOrderingLoads?: Record<string, { settled: boolean; error: string | null; corpus?: string }>;
    };
    target.__graphOrderingLoads ??= {};
    target.__graphOrderingLoads[key] = { settled: false, error: null };
    void useRepoStore.getState().loadRepos({ force: forceLoad }).then(() => {
      target.__graphOrderingLoads![key].settled = true;
    }).catch((error: unknown) => {
      target.__graphOrderingLoads![key] = {
        settled: true,
        error: error instanceof Error ? error.message : String(error),
      };
    });
  }, { url: moduleUrl, key: label, forceLoad: force });
}

async function startTrackedAddRepo(
  page: Page,
  moduleUrl: string,
  corpus: string,
  path: string,
): Promise<void> {
  await page.evaluate(({ url, corpusId, corpusPath }) => {
    const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
    const target = window as typeof window & {
      __graphOrderingLoads?: Record<string, { settled: boolean; error: string | null; corpus?: string }>;
    };
    target.__graphOrderingLoads ??= {};
    target.__graphOrderingLoads.add = { settled: false, error: null };
    void useRepoStore.getState().addRepo({
      corpus_id: corpusId,
      name: corpusId,
      path: corpusPath,
    }).then((created: { corpus_id: string }) => {
      target.__graphOrderingLoads!.add = { settled: true, error: null, corpus: created.corpus_id };
    }).catch((error: unknown) => {
      target.__graphOrderingLoads!.add = {
        settled: true,
        error: error instanceof Error ? error.message : String(error),
      };
    });
  }, { url: moduleUrl, corpusId: corpus, corpusPath: path });
}

async function trackedRepoLoads(page: Page) {
  return page.evaluate(() => {
    const target = window as typeof window & {
      __graphOrderingLoads?: Record<string, { settled: boolean; error: string | null; corpus?: string }>;
    };
    return target.__graphOrderingLoads ?? {};
  });
}

async function expectOwnedRegistry(request: APIRequestContext, corpusIds: string[]): Promise<void> {
  const response = await request.get(`${CONTROL}/api/corpora`);
  expect(response.ok()).toBe(true);
  const rows = await response.json() as Array<{ corpus_id: string }>;
  expect(rows.map((row) => row.corpus_id).sort()).toEqual([...corpusIds].sort());
}

test('a held pre-delete registry response cannot resurrect the deleted last corpus', async ({ page, request, baseURL }, testInfo) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus, other] = (await seeded.json()).corpora as string[];
  try {
    expect((await request.delete(`${CONTROL}/api/corpora/${other}`)).ok()).toBe(true);
    await expectOwnedRegistry(request, [corpus]);
    await activateCorpusInBrowser(page, corpus);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
    await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
    const moduleUrl = await loadedModuleUrl(page, 'src/stores/useRepoStore.ts');
    const stale = await hold(request, '/api/corpora');
    await forceRepoLoad(page, moduleUrl);
    await captured(request, stale);

    await page.getByTestId('topbar-corpus').click();
    await page.getByTestId(`corpus-delete-${corpus}`).click();
    await page.getByTestId('confirm-dialog-accept').click();
    await expect(page.getByTestId('corpus-registry-empty')).toBeVisible();
    await page.getByTestId('corpus-registry-close').click();
    await expectNoCorpusGraph(page);
    const emptyState = { repos: [], activeRepo: '', loading: false, error: null, initialized: true };
    await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual(emptyState);

    await release(request, page, stale);
    await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual(emptyState);
    await expectNoCorpusGraph(page);
    await expect(page.getByTestId('apply-error')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => ({
      corpus: new URL(location.href).searchParams.get('corpus'),
      repo: new URL(location.href).searchParams.get('repo'),
      storedCorpus: localStorage.getItem('tribrid_active_corpus'),
      storedRepo: localStorage.getItem('tribrid_active_repo'),
    }))).toEqual({ corpus: null, repo: null, storedCorpus: null, storedRepo: null });
    await page.screenshot({ path: testInfo.outputPath('registry-delete-latest-intent.png') });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('an older registry completion cannot clear newer loading or error state', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const corpora = (await seeded.json()).corpora as string[];
  try {
    await expectOwnedRegistry(request, corpora);
    await activateCorpusInBrowser(page, corpora[0]);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpora[0]}`, baseURL).toString());
    await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
    const moduleUrl = await loadedModuleUrl(page, 'src/stores/useRepoStore.ts');
    const older = await hold(request, '/api/corpora');
    const newer = await hold(request, '/api/corpora');
    await forceRepoLoad(page, moduleUrl);
    await captured(request, older);
    await forceRepoLoad(page, moduleUrl);
    await captured(request, newer);
    await page.evaluate((url) => {
      const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
      void useRepoStore.getState().setActiveRepo('__missing_registry_intent__');
    }, moduleUrl);
    const pendingState = await currentRepoState(page, moduleUrl);
    expect(pendingState.loading).toBe(true);
    expect(pendingState.error).toBe('Repository "__missing_registry_intent__" not found');

    await release(request, page, older);
    await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual(pendingState);
    await release(request, page, newer);
    await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual({
      repos: [...corpora].sort(), activeRepo: corpora[0], loading: false, error: null, initialized: true,
    });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('a pending recovery retry retains URL-selected config scope after the first registry load fails', async ({
  page, request, baseURL,
}) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus] = (await seeded.json()).corpora as string[];
  try {
    const globalResponse = await request.get(`${CONTROL}/api/config`);
    expect(globalResponse.ok()).toBe(true);
    const globalFinalK = (await globalResponse.json()).retrieval.final_k as number;
    const scopedFinalK = globalFinalK === 7 ? 11 : 7;
    expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpus}`, {
      data: { final_k: scopedFinalK },
    })).ok()).toBe(true);

    const baseline = await request.get(`${CONTROL}/api/corpora`);
    expect(baseline.ok()).toBe(true);
    const baselineSha = createHash('sha256').update(await baseline.body()).digest('hex');
    const failed = await failAfterCapture(request, '/api/corpora');
    const observedFailure = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === '/api/corpora' && !response.ok();
    });
    await activateCorpusInBrowser(page, corpus);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
    const browserFailure = await observedFailure;
    expect(browserFailure.status()).toBeGreaterThanOrEqual(500);
    await captured(request, failed);
    const failedState = await fixtureResponseState(request, failed);
    expect(failedState).toMatchObject({ status: baseline.status(), sha256: baselineSha, faulted: true, delivered: false });

    const repoModuleUrl = await loadedModuleUrl(page, 'src/stores/useRepoStore.ts');
    await expect.poll(() => currentRepoState(page, repoModuleUrl)).toEqual({
      repos: [], activeRepo: '', loading: false, error: 'Failed to load corpora',
      initialized: true,
    });
    await expect.poll(() => currentConfigState(page)).toEqual({
      finalK: scopedFinalK, error: null, loading: false,
    });

    const recovery = await hold(request, '/api/corpora');
    await page.evaluate((url) => {
      const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
      void useRepoStore.getState().loadRepos();
    }, repoModuleUrl);
    await captured(request, recovery);
    await expect.poll(() => currentRepoState(page, repoModuleUrl)).toEqual({
      repos: [], activeRepo: '', loading: true, error: null, initialized: true,
    });
    await expect.poll(() => currentConfigState(page)).toEqual({
      finalK: scopedFinalK, error: null, loading: false,
    });
    expect(new URL(page.url()).searchParams.get('corpus')).toBe(corpus);

    await release(request, page, recovery);
    await expect.poll(() => currentRepoState(page, repoModuleUrl)).toMatchObject({
      activeRepo: corpus, loading: false, error: null, initialized: true,
    });
    await expect.poll(() => currentConfigState(page)).toEqual({
      finalK: scopedFinalK, error: null, loading: false,
    });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('mutation and shared callers follow a continued chain of forced registry refreshes', async ({
  page, request, baseURL,
}) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const corpora = (await seeded.json()).corpora as string[];
  try {
    await expectOwnedRegistry(request, corpora);
    await activateCorpusInBrowser(page, corpora[0]);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpora[0]}`, baseURL).toString());
    await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
    const moduleUrl = await loadedModuleUrl(page, 'src/stores/useRepoStore.ts');
    const reservedResponse = await request.post(`${CONTROL}/__graph_fixture__/reserve-corpus`);
    expect(reservedResponse.ok()).toBe(true);
    const reserved = await reservedResponse.json() as { corpus: string; path: string };

    const mutationRefresh = await hold(request, '/api/corpora');
    const forcedRefresh = await hold(request, '/api/corpora');
    const winningRefresh = await hold(request, '/api/corpora');
    await startTrackedAddRepo(page, moduleUrl, reserved.corpus, reserved.path);
    await captured(request, mutationRefresh);
    await startTrackedRepoLoad(page, moduleUrl, 'forced', true);
    await captured(request, forcedRefresh);
    await startTrackedRepoLoad(page, moduleUrl, 'shared', false);

    await release(request, page, mutationRefresh);
    await expect.poll(() => trackedRepoLoads(page)).toEqual({
      add: { settled: false, error: null },
      forced: { settled: false, error: null },
      shared: { settled: false, error: null },
    });

    // Keep at most two identical browser requests parked at once. The browser/proxy may queue a
    // third connection until an older one returns, which would test socket limits rather than the
    // store's transitive A -> B -> C completion chain.
    await startTrackedRepoLoad(page, moduleUrl, 'winning', true);
    await captured(request, winningRefresh);
    await release(request, page, forcedRefresh);
    await expect.poll(() => trackedRepoLoads(page)).toEqual({
      add: { settled: false, error: null },
      forced: { settled: false, error: null },
      shared: { settled: false, error: null },
      winning: { settled: false, error: null },
    });

    await release(request, page, winningRefresh);
    await expect.poll(() => trackedRepoLoads(page)).toEqual({
      add: { settled: true, error: null, corpus: reserved.corpus },
      forced: { settled: true, error: null },
      shared: { settled: true, error: null },
      winning: { settled: true, error: null },
    });
    await expectOwnedRegistry(request, [...corpora, reserved.corpus]);
    await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual({
      repos: [...corpora, reserved.corpus].sort(), activeRepo: reserved.corpus,
      loading: false, error: null, initialized: true,
    });
    await expect.poll(() => page.evaluate(() => ({
      corpus: new URL(location.href).searchParams.get('corpus'),
      storedCorpus: localStorage.getItem('tribrid_active_corpus'),
    }))).toEqual({ corpus: reserved.corpus, storedCorpus: reserved.corpus });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

async function currentConfigState(page: Page) {
  const moduleUrl = await loadedModuleUrl(page, 'src/stores/useConfigStore.ts');
  return page.evaluate((url) => {
    // Read the actual rendered app's store; every load still uses its real API.
    const { useConfigStore } = window.__graphOrderingModules![url].module as ConfigStoreModule;
    const state = useConfigStore.getState();
    return { finalK: state.config?.retrieval.final_k ?? null, error: state.error, loading: state.loading };
  }, moduleUrl);
}

for (const mutation of ['add', 'update', 'delete', 'cleanup'] as const) {
  for (const failureOrder of ['before-older', 'after-older'] as const) {
    test(`${mutation} reports completed mutation and failed winning registry refresh ${failureOrder}`, async ({
      page, request, baseURL,
    }) => {
      const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
      const corpora = (await seeded.json()).corpora as string[];
      const pageErrors: string[] = [];
      page.on('pageerror', (error) => pageErrors.push(error.message));
      try {
        await expectOwnedRegistry(request, corpora);
        await activateCorpusInBrowser(page, corpora[0]);
        await page.goto(new URL(`rag?subtab=graph&corpus=${corpora[0]}`, baseURL).toString());
        await expect(page.getByTestId('graph-entities').locator('> button')).toHaveCount(3);
        const moduleUrl = await loadedModuleUrl(page, 'src/stores/useRepoStore.ts');
        const reservedResponse = await request.post(`${CONTROL}/__graph_fixture__/reserve-corpus`);
        expect(reservedResponse.ok()).toBe(true);
        const reserved = await reservedResponse.json() as { corpus: string; path: string };
        const older = await hold(request, '/api/corpora');
        const failingResponse = await request.post(`${CONTROL}/__graph_fixture__/fail-after-release`, {
          data: { path: '/api/corpora', query: null },
        });
        expect(failingResponse.ok()).toBe(true);
        const failing = (await failingResponse.json()).token as string;

        await page.evaluate(({ url, operation, corpus, created }) => {
          const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
          const target = window as typeof window & {
            __registryFailure?: {
              mutation: { settled: boolean; error: string | null };
              loads: Record<string, { settled: boolean; rejected: boolean; ok?: boolean; error?: string }>;
              changed: number;
            };
          };
          target.__registryFailure = { mutation: { settled: false, error: null }, loads: {}, changed: 0 };
          window.addEventListener('tribrid-corpus-changed', () => { target.__registryFailure!.changed += 1; });
          const state = useRepoStore.getState();
          const work = operation === 'add'
            ? state.addRepo({ corpus_id: created.corpus, name: created.corpus, path: created.path })
            : operation === 'update' ? state.updateCorpus(corpus, { name: 'Registry failure regression' })
              : operation === 'delete' ? state.deleteCorpus(corpus) : state.deleteUnindexedCorpora();
          void work.then(() => {
            target.__registryFailure!.mutation = { settled: true, error: null };
          }).catch((error: unknown) => {
            target.__registryFailure!.mutation = {
              settled: true, error: error instanceof Error ? error.message : String(error),
            };
          });
        }, { url: moduleUrl, operation: mutation, corpus: corpora[0], created: reserved });
        await captured(request, older);

        await page.evaluate((url) => {
          const { useRepoStore } = window.__graphOrderingModules![url].module as RepoStoreModule;
          const target = window as typeof window & {
            __registryFailure: {
              loads: Record<string, { settled: boolean; rejected: boolean; ok?: boolean; error?: string }>;
            };
          };
          for (const [label, force] of [['forced', true], ['shared', false]] as const) {
            target.__registryFailure.loads[label] = { settled: false, rejected: false };
            void useRepoStore.getState().loadRepos({ force }).then((result: { ok: boolean; error?: string }) => {
              target.__registryFailure.loads[label] = { settled: true, rejected: false, ...result };
            }).catch((error: unknown) => {
              target.__registryFailure.loads[label] = {
                settled: true, rejected: true, error: error instanceof Error ? error.message : String(error),
              };
            });
          }
          // Ordinary initialization and refresh listeners intentionally ignore the returned promise.
          // A real winning server failure must not produce an unhandled rejection in those callers.
          void useRepoStore.getState().loadRepos();
        }, moduleUrl);
        await captured(request, failing);
        const baseline = await request.get(`${CONTROL}/api/corpora`);
        expect(baseline.ok()).toBe(true);
        const original = await fixtureResponseState(request, failing);
        expect(original).toMatchObject({
          status: baseline.status(),
          sha256: createHash('sha256').update(await baseline.body()).digest('hex'),
          captured: true, faulted: false, delivered: false,
        });

        const failureState = () => page.evaluate(() => (window as typeof window & {
          __registryFailure: {
            mutation: { settled: boolean; error: string | null };
            loads: Record<string, { settled: boolean; rejected: boolean; ok?: boolean; error?: string }>;
            changed: number;
          };
        }).__registryFailure);
        if (failureOrder === 'after-older') {
          await release(request, page, older);
          await expect.poll(failureState).toEqual({
            mutation: { settled: false, error: null },
            loads: {
              forced: { settled: false, rejected: false },
              shared: { settled: false, rejected: false },
            },
            changed: 0,
          });
        }
        const browserFailure = page.waitForResponse((response) => {
          return new URL(response.url()).pathname === '/api/corpora' && response.status() >= 500;
        });
        expect((await request.post(`${CONTROL}/__graph_fixture__/release/${failing}`)).ok()).toBe(true);
        expect((await browserFailure).status()).toBeGreaterThanOrEqual(500);
        await expect.poll(async () => (await fixtureResponseState(request, failing)).faulted).toBe(true);
        await expect.poll(async () => {
          const { loads } = await failureState();
          return loads.forced.settled && loads.shared.settled;
        }).toBe(true);
        if (failureOrder === 'before-older') {
          expect((await failureState()).mutation.settled).toBe(false);
          await release(request, page, older);
        }
        await expect.poll(async () => (await failureState()).mutation).toEqual({
          settled: true,
          error: expect.stringMatching(/(?:was created|was updated|was deleted|Deleted 2\/2 corpora).*corpus list could not be refreshed/),
        });
        await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual({
          repos: [...corpora].sort(), activeRepo: corpora[0],
          loading: false, error: 'Failed to load corpora', initialized: true,
        });
        expect((await failureState()).changed).toBe(0);
        expect(new URL(page.url()).searchParams.get('corpus')).toBe(corpora[0]);
        expect(await page.evaluate(() => localStorage.getItem('tribrid_active_corpus'))).toBe(corpora[0]);
        // Verify the result contract only after the operator-visible failure and scope behavior.
        expect((await failureState()).loads).toEqual({
          forced: { settled: true, rejected: false, ok: false, error: 'Failed to load corpora' },
          shared: { settled: true, rejected: false, ok: false, error: 'Failed to load corpora' },
        });
        const expectedCorpora = mutation === 'add' ? [...corpora, reserved.corpus]
          : mutation === 'delete' ? [corpora[1]] : mutation === 'cleanup' ? [] : corpora;
        await expectOwnedRegistry(request, expectedCorpora);
        if (mutation === 'update') {
          const rows = await baseline.json() as Array<{ corpus_id: string; name: string }>;
          expect(rows.find((row) => row.corpus_id === corpora[0])?.name).toBe('Registry failure regression');
        }

        // A later real successful load reconciles the completed mutation and clears the error.
        await forceRepoLoad(page, moduleUrl);
        await expect.poll(() => currentRepoState(page, moduleUrl)).toEqual({
          repos: [...expectedCorpora].sort(),
          activeRepo: mutation === 'delete' ? corpora[1] : mutation === 'cleanup' ? '' : corpora[0],
          loading: false, error: null, initialized: true,
        });
        expect(pageErrors).toEqual([]);
      } finally {
        expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
      }
    });
  }
}

for (const outcome of ['success', 'failure'] as const) {
  test(`late config ${outcome} cannot replace the newer corpus config`, async ({ page, request, baseURL }) => {
    const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
    const [corpusA, corpusB] = (await seeded.json()).corpora as string[];
    try {
      for (const [corpus, finalK] of [[corpusA, 7], [corpusB, 11]] as const) {
        expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpus}`, {
          data: { final_k: finalK },
        })).ok()).toBe(true);
      }
      await activateCorpusInBrowser(page, corpusB);
      await page.goto(new URL(`rag?subtab=graph&corpus=${corpusB}`, baseURL).toString());
      await expect.poll(() => currentConfigState(page)).toEqual({ finalK: 11, error: null, loading: false });
      if (outcome === 'failure') {
        // Keep the browser's registry snapshot; the actual config API now returns 404.
        expect((await request.delete(`${CONTROL}/api/corpora/${corpusA}`)).ok()).toBe(true);
      }
      const ticket = await hold(request, '/api/config', corpusA);
      await page.getByTestId('graph-corpus-select').selectOption(corpusA);
      await captured(request, ticket);
      await page.getByTestId('graph-corpus-select').selectOption(corpusB);
      await expect.poll(() => currentConfigState(page)).toEqual({ finalK: 11, error: null, loading: false });
      await release(request, page, ticket);
      await expect.poll(() => currentConfigState(page)).toEqual({ finalK: 11, error: null, loading: false });
      await expect(page.getByTestId('apply-error')).toHaveCount(0);

      if (outcome === 'failure') {
        // The same real 404 must remain visible when this is still the selected corpus.
        await page.getByTestId('graph-corpus-select').selectOption(corpusA);
        await expect(page.getByTestId('apply-error')).toContainText(`Corpus not found: ${corpusA}`);
      }
    } finally {
      expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
    }
  });
}

test('config API scope distinguishes explicit global from omitted active scope', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus] = (await seeded.json()).corpora as string[];
  try {
    const globalResponse = await request.get(`${CONTROL}/api/config`);
    expect(globalResponse.ok()).toBe(true);
    const globalFinalK = (await globalResponse.json()).retrieval.final_k as number;
    const scopedFinalK = globalFinalK === 7 ? 11 : 7;
    expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpus}`, {
      data: { final_k: scopedFinalK },
    })).ok()).toBe(true);
    await activateCorpusInBrowser(page, corpus);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpus}`, baseURL).toString());
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: scopedFinalK, error: null, loading: false });
    const moduleUrl = await loadedModuleUrl(page, 'src/api/config.ts');
    await page.evaluate(({ url, corpusId }) => {
      const { configApi } = window.__graphOrderingModules![url].module as ConfigApiModule;
      const state: NonNullable<Window['__graphOrderingScopeResult']> = { result: null, error: null, promise: null };
      window.__graphOrderingScopeResult = state;
      state.promise = (async () => {
        const omitted = await configApi.load();
        const pinned = await configApi.load(corpusId);
        const global = await configApi.load(null);
        let emptyStatus: number | null = null;
        try {
          await configApi.load('');
        } catch (error) {
          emptyStatus = (error as { response?: { status?: number } }).response?.status ?? null;
        }
        state.result = [omitted.retrieval.final_k, pinned.retrieval.final_k, global.retrieval.final_k, emptyStatus];
      })().catch((error: unknown) => {
        state.error = error instanceof Error ? error.message : String(error);
      });
    }, { url: moduleUrl, corpusId: corpus });
    await expect.poll(() => page.evaluate(() => {
      const { result, error } = window.__graphOrderingScopeResult!;
      return { result, error };
    })).toEqual({ result: [scopedFinalK, scopedFinalK, globalFinalK, 422], error: null });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('returning to a corpus starts a new config load instead of sharing its older epoch', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpusA, corpusB] = (await seeded.json()).corpora as string[];
  try {
    expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpusA}`, {
      data: { final_k: 7 },
    })).ok()).toBe(true);
    await activateCorpusInBrowser(page, corpusB);
    await page.goto(new URL(`rag?subtab=graph&corpus=${corpusB}`, baseURL).toString());
    await expect.poll(async () => (await currentConfigState(page)).loading).toBe(false);
    const old = await hold(request, '/api/config', corpusA);
    await page.getByTestId('graph-corpus-select').selectOption(corpusA);
    await captured(request, old);
    await page.getByTestId('graph-corpus-select').selectOption(corpusB);
    expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpusA}`, {
      data: { final_k: 13 },
    })).ok()).toBe(true);
    await page.getByTestId('graph-corpus-select').selectOption(corpusA);
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: 13, error: null, loading: false });
    await release(request, page, old);
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: 13, error: null, loading: false });
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});

test('deleting the last corpus keeps global config after its held config response arrives', async ({ page, request, baseURL }) => {
  const seeded = await request.post(`${CONTROL}/__graph_fixture__/seed`);
  const [corpus, other] = (await seeded.json()).corpora as string[];
  try {
    const globalResponse = await request.get(`${CONTROL}/api/config`);
    expect(globalResponse.ok()).toBe(true);
    const globalFinalK = (await globalResponse.json()).retrieval.final_k as number;
    expect((await request.patch(`${CONTROL}/api/config/retrieval?corpus_id=${corpus}`, {
      data: { final_k: globalFinalK === 7 ? 11 : 7 },
    })).ok()).toBe(true);
    await activateCorpusInBrowser(page, other);
    await page.goto(new URL(`rag?subtab=graph&corpus=${other}`, baseURL).toString());
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: globalFinalK, error: null, loading: false });
    expect((await request.delete(`${CONTROL}/api/corpora/${other}`)).ok()).toBe(true);
    const old = await hold(request, '/api/config', corpus);
    await page.getByTestId('graph-corpus-select').selectOption(corpus);
    await captured(request, old);
    await page.getByTestId('topbar-corpus').click();
    await page.getByTestId(`corpus-delete-${corpus}`).click();
    await page.getByTestId('confirm-dialog-accept').click();
    await expect(page.getByTestId('corpus-registry-empty')).toBeVisible();
    await page.getByTestId('corpus-registry-close').click();
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: globalFinalK, error: null, loading: false });
    await release(request, page, old);
    await expectNoCorpusGraph(page);
    await expect.poll(() => currentConfigState(page)).toEqual({ finalK: globalFinalK, error: null, loading: false });
    await expect(page.getByTestId('apply-error')).toHaveCount(0);
  } finally {
    expect((await request.post(`${CONTROL}/__graph_fixture__/cleanup`)).ok()).toBe(true);
  }
});
