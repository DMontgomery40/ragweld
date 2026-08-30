// Graph Explorer regressions for the 2026-08-29 drive T1 findings, driven against the
// real app and the real API with no request interception.
//
// The corpora are read-only production corpora chosen because they carry the two graph
// shapes the findings depend on: `ragweld_code` is a code graph whose entity ids contain
// `/` and `::` (5,179 entities, 11,779 relationships, 0 communities), and `nasa-apollo-11`
// has a chunk graph with an empty entity graph. Nothing here writes: no index run, no
// config patch, no corpus creation or deletion.
//
// M-01  entity ids survive the round trip; a failed expansion keeps the results
// M-59  one legend, derived from the entity types drawn
// M-60  the communities empty state names the real cause
// M-61  the entity count has a denominator and the limit is settable
// M-62  a search carries the relationships between its own results
// M-63  the inline panel has labels, zoom and pan
// M-64  wheel zoom is real, and there is a readout that proves it
// M-65  Table view shows tables, and its empty state does not loop
// M-66  Retrieval's graph-leg card says whether this corpus has an entity graph
// M-149 hub labels are drawn above the nodes; the graph can be exported
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

const CODE_CORPUS = 'ragweld_code';
const NO_ENTITY_CORPUS = 'nasa-apollo-11';
/** A real `ragweld_code` entity whose id carries both a `/` and a `::`. */
const CODE_ENTITY_ID = 'server/retrieval/rerank.py::Reranker';
const SEARCH_TERM = 'reranker';

async function gotoGraph(page: Page, baseURL: string | undefined, corpusId: string): Promise<void> {
  await activateCorpusInBrowser(page, corpusId);
  await page.goto(new URL(`rag?subtab=graph&corpus=${encodeURIComponent(corpusId)}`, baseURL).toString(), {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('graph-subtab')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('graph-stats')).toBeVisible({ timeout: 60_000 });
}

/** The visualizer's own "N nodes - M edges" readout, parsed. */
async function vizCounts(page: Page): Promise<{ nodes: number; edges: number }> {
  const text = await page.getByTestId('graph-viz-panel').innerText();
  const match = text.match(/([\d,]+)\s*nodes\s*•\s*([\d,]+)\s*edges/);
  expect(match, `no node/edge readout in: ${text.slice(0, 200)}`).toBeTruthy();
  return { nodes: Number(match![1].replace(/,/g, '')), edges: Number(match![2].replace(/,/g, '')) };
}

async function zoomLevel(page: Page, testId: string): Promise<number> {
  const text = await page.getByTestId(testId).innerText();
  expect(text, 'the zoom readout must never show NaN').not.toContain('NaN');
  const value = Number(text.replace('%', '').trim());
  expect(Number.isFinite(value), `unreadable zoom level: ${text}`).toBe(true);
  return value;
}

/** Wait for the fit-to-view transform to settle into a readable number. */
async function settledZoom(page: Page, testId: string): Promise<number> {
  await expect
    .poll(async () => (await page.getByTestId(testId).innerText()).trim(), { timeout: 30_000 })
    .toMatch(/^[\d.]+%$/);
  return zoomLevel(page, testId);
}

async function searchEntities(page: Page, term: string): Promise<void> {
  await page.getByTestId('graph-entity-search').fill(term);
  await page.getByTestId('graph-search-btn').click();
  await expect(page.getByTestId('graph-entity-count')).toContainText(term, { timeout: 30_000 });
}

test.describe('Graph Explorer on the ragweld_code code graph', () => {
  test('M-01/M-62/M-61: a code entity expands, the search carries its edges, and the count has a denominator', async ({
    page,
    baseURL,
  }) => {
    const neighborCalls: string[] = [];
    const neighborStatuses: number[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/entity/neighbors')) neighborCalls.push(req.url());
    });
    page.on('response', async (res) => {
      if (res.url().includes('/entity/neighbors')) neighborStatuses.push(res.status());
    });

    await gotoGraph(page, baseURL, CODE_CORPUS);

    // M-61: the resting corpus view names what it is not showing.
    await expect(page.getByTestId('graph-entity-count')).toHaveText(/Showing 200 of 5,\d{3} in this corpus/, {
      timeout: 60_000,
    });
    const resting = await vizCounts(page);
    expect(resting.nodes).toBe(200);
    expect(resting.edges).toBeGreaterThan(0);

    // M-62: a search returns the relationships between its own results. The drive saw
    // "101 nodes - 1 edges"; the induced subgraph is what makes it a graph.
    await searchEntities(page, SEARCH_TERM);
    const searched = await vizCounts(page);
    expect(searched.nodes).toBeGreaterThan(50);
    expect(searched.edges, 'a search must carry the edges among its results').toBeGreaterThan(1);
    await expect(page.getByTestId('graph-no-edges-note')).toHaveCount(0);
    const listedBefore = await page.getByTestId('graph-entities').locator('> button').count();
    expect(listedBefore).toBe(searched.nodes);

    // M-01: the entity whose id carries `/` and `::` expands instead of 404ing, and the
    // operator's view is not wiped.
    const target = page.getByTestId(`graph-entity-${CODE_ENTITY_ID}`);
    await expect(target).toBeVisible();
    await target.click();
    await expect(page.getByTestId('graph-entity-count')).toContainText('in this neighborhood', { timeout: 60_000 });

    expect(neighborCalls.length, 'the click must call the neighbors endpoint').toBeGreaterThan(0);
    expect(neighborCalls[0]).toContain(`entity_id=${encodeURIComponent(CODE_ENTITY_ID)}`);
    expect(neighborCalls[0], 'the id must not be a path segment').not.toContain('/entity/server');
    expect(neighborStatuses).toEqual(neighborStatuses.map(() => 200));

    const expanded = await vizCounts(page);
    expect(expanded.nodes, 'the neighborhood must not be empty').toBeGreaterThan(1);
    expect(expanded.edges).toBeGreaterThan(0);
    await expect(page.getByTestId('graph-error')).toHaveCount(0);

    // M-61: the limit is settable and actually reaches past entity 200.
    await page.getByTestId('graph-clear-btn').click();
    await expect(page.getByTestId('graph-entity-count')).toHaveText(/Showing 200 of/, { timeout: 60_000 });
    await page.getByTestId('graph-entity-limit').selectOption('500');
    await expect(page.getByTestId('graph-entity-count')).toHaveText(/Showing 500 of 5,\d{3} in this corpus/, {
      timeout: 60_000,
    });
  });

  test('M-59: one legend, and it describes the entity types actually drawn', async ({ page, baseURL }) => {
    await gotoGraph(page, baseURL, CODE_CORPUS);
    const legend = page.getByTestId('graph-legend');
    await expect(legend).toBeVisible({ timeout: 60_000 });
    const inline = (await legend.innerText()).split('\n').map((s) => s.trim()).filter(Boolean).sort();
    expect(inline).toEqual(['class', 'function', 'module']);
    // The NER palette the inline legend used to show is gone from a code graph.
    for (const wrong of ['person', 'org', 'location', 'event', 'concept']) {
      await expect(legend).not.toContainText(wrong);
    }

    // The filter checkboxes describe the same types the legend does.
    await page.getByText('Filters', { exact: true }).click();
    for (const type of inline) {
      await expect(page.getByTestId('graph-subtab').getByText(type, { exact: true }).first()).toBeVisible();
    }

    // The modal legend is the same component over the same data: they cannot disagree.
    await page.getByTestId('graph-expand-btn').click();
    await expect(page.getByTestId('graph-fullscreen-modal')).toBeVisible();
    const modal = (await page.getByTestId('graph-fullscreen-legend').innerText())
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .sort();
    expect(modal).toEqual(inline);
    await page.keyboard.press('Escape');
  });

  test('M-60: the communities empty state names the real cause, not an expensive re-index', async ({
    page,
    baseURL,
  }) => {
    await gotoGraph(page, baseURL, CODE_CORPUS);
    const stats = await (await page.request.get(`${API_BASE}/graph/${CODE_CORPUS}/stats`)).json();
    expect(stats.total_entities).toBeGreaterThan(0);
    expect(stats.total_relationships).toBeGreaterThan(0);
    expect(stats.total_communities).toBe(0);

    const empty = page.getByTestId('graph-communities-empty');
    await expect(empty).toBeVisible({ timeout: 60_000 });
    // The old copy claimed the graph had no linked entities and prescribed a Force re-index.
    await expect(empty).not.toContainText('no linked entities');
    await expect(empty).not.toContainText('Force re-index');
    await expect(empty).toContainText('community detection');
    await expect(empty).toContainText(String(stats.total_entities).replace(/\B(?=(\d{3})+(?!\d))/g, ','));
  });

  test('M-63/M-64/M-149: labels, real wheel zoom with a readout, and export', async ({ page, baseURL }) => {
    await gotoGraph(page, baseURL, CODE_CORPUS);
    await expect(page.getByTestId('graph-viz-canvas').locator('canvas')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('graph-viz-hint')).toContainText('zoom');

    // M-64: the wheel really zooms, and the readout says so. The drive could only compare
    // screenshots and saw a pixel-identical render.
    const canvas = page.getByTestId('graph-viz-canvas').locator('canvas');
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    expect(box).toBeTruthy();
    // M-63: the panel must actually be a panel. `1fr` (= minmax(auto, 1fr)) let the
    // entity list's unbreakable ids squeeze this canvas to 2px wide at 1280x720.
    expect(box!.width, 'the inline visualization must have real width').toBeGreaterThan(250);
    expect(box!.height).toBeGreaterThan(300);
    await page.waitForTimeout(2500); // let the simulation settle: a frame diff must mean zoom
    const before = await settledZoom(page, 'graph-zoom-level');
    await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
    await page.mouse.wheel(0, -600);
    await expect
      .poll(() => zoomLevel(page, 'graph-zoom-level'), { timeout: 10_000 })
      .toBeGreaterThan(before);

    // M-63: the inline panel has its own zoom controls, not only the modal.
    const afterWheel = await zoomLevel(page, 'graph-zoom-level');
    await page.getByTestId('graph-zoom-out').click();
    await expect.poll(() => zoomLevel(page, 'graph-zoom-level'), { timeout: 10_000 }).toBeLessThan(afterWheel);
    await page.getByTestId('graph-zoom-fit').click();

    // M-63: hub labels are legible in the INLINE panel at the zoom the operator lands on
    // (it rests near k = 0.01, where a canvas-unit font cap rendered sub-pixel text).
    const inlineInk = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="graph-viz-canvas"] canvas') as HTMLCanvasElement;
      const data = el.getContext('2d')!.getImageData(0, 0, el.width, el.height).data;
      let ink = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i] > 230 && data[i + 1] > 230 && data[i + 2] > 230 && data[i + 3] > 200) ink += 1;
      }
      return ink;
    });
    expect(inlineInk, 'inline hub labels must be painted at the resting zoom').toBeGreaterThan(100);

    // M-149 / C-40: hub labels are painted in the pass after the nodes, so they survive
    // on top. Sample the canvas for the near-white label ink over the dark pill.
    await page.getByTestId('graph-expand-btn').click();
    await expect(page.getByTestId('graph-fullscreen-modal')).toBeVisible();
    await page.waitForTimeout(3000);
    const labelInk = await page.evaluate(() => {
      const el = document.querySelector('[data-testid="graph-fullscreen-canvas"] canvas') as HTMLCanvasElement;
      const data = el.getContext('2d')!.getImageData(0, 0, el.width, el.height).data;
      let ink = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (data[i] > 230 && data[i + 1] > 230 && data[i + 2] > 230 && data[i + 3] > 200) ink += 1;
      }
      return ink;
    });
    expect(labelInk, 'hub label text must be painted on the canvas').toBeGreaterThan(200);

    // M-64 in the modal: wheel zoom and the +/- controls both move the readout.
    const modalBefore = await settledZoom(page, 'graph-fullscreen-zoom-level');
    const modalCanvas = await page.getByTestId('graph-fullscreen-canvas').locator('canvas').boundingBox();
    await page.mouse.move(modalCanvas!.x + modalCanvas!.width / 2, modalCanvas!.y + modalCanvas!.height / 2);
    await page.mouse.wheel(0, -600);
    await expect
      .poll(() => zoomLevel(page, 'graph-fullscreen-zoom-level'), { timeout: 10_000 })
      .toBeGreaterThan(modalBefore);
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('graph-fullscreen-modal')).toHaveCount(0);

    // M-149 / C-42: the render and the data can leave the page.
    const png = page.waitForEvent('download');
    await page.getByTestId('graph-export-png').click();
    expect((await png).suggestedFilename()).toMatch(/^graph-ragweld_code.*\.png$/);

    const csv = page.waitForEvent('download');
    await page.getByTestId('graph-export-entities').click();
    const entitiesCsv = await csv;
    expect(entitiesCsv.suggestedFilename()).toMatch(/-entities\.csv$/);
    const stream = await entitiesCsv.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(Buffer.from(chunk));
    const body = Buffer.concat(chunks).toString('utf8');
    expect(body.split('\n')[0]).toBe('entity_id,name,entity_type,file_path,connections,description');
    expect(body.split('\n').length).toBeGreaterThan(100);
  });

  test('M-65: Table view is a table, and a failed expansion neither wipes the results nor loops', async ({
    page,
    baseURL,
    context,
  }) => {
    await gotoGraph(page, baseURL, CODE_CORPUS);
    await searchEntities(page, SEARCH_TERM);
    // Count the list's own buttons: a `graph-entity-` prefix match would also pick up the
    // count, search box and limit picker, and an id filter on `::` would drop modules.
    const listed = await page.getByTestId('graph-entities').locator('> button').count();
    expect(listed).toBeGreaterThan(0);

    await page.getByTestId('graph-view-table').click();
    // F-04: export lives above the grid, so it survives the view switch that removes the
    // visualization panel. The tables are the surface most obviously wanting CSV.
    await expect(page.getByTestId('graph-export-entities')).toBeVisible();
    await expect(page.getByTestId('graph-export-relationships')).toBeVisible();
    await expect(page.getByTestId('graph-export-png')).toHaveCount(0);
    // N-03: a disabled export must LOOK disabled. `controlButtonStyle` sets an explicit
    // color and background, which override the UA stylesheet's greying.
    const relStyle = await page.getByTestId('graph-export-relationships').evaluate((el) => {
      const cs = getComputedStyle(el);
      return { disabled: (el as HTMLButtonElement).disabled, color: cs.color, cursor: cs.cursor };
    });
    const enabledStyle = await page.getByTestId('graph-export-entities').evaluate((el) => {
      const cs = getComputedStyle(el);
      return { disabled: (el as HTMLButtonElement).disabled, color: cs.color, cursor: cs.cursor };
    });
    expect(enabledStyle.disabled).toBe(false);
    if (relStyle.disabled) {
      expect(relStyle.color, 'a disabled export must not look identical to a live one').not.toBe(
        enabledStyle.color
      );
      expect(relStyle.cursor).toBe('not-allowed');
    }
    const tableCsv = page.waitForEvent('download');
    await page.getByTestId('graph-export-relationships').click();
    expect((await tableCsv).suggestedFilename()).toMatch(/-relationships\.csv$/);

    const entityRows = page.getByTestId('graph-entities-table').locator('tbody tr');
    const relRows = page.getByTestId('graph-relationships-table').locator('tbody tr');
    await expect(entityRows.first()).toBeVisible({ timeout: 30_000 });
    expect(await entityRows.count()).toBe(listed);
    expect(await relRows.count(), 'the relationships table must have rows, not a loop').toBeGreaterThan(0);
    await expect(page.getByTestId('graph-entities-table')).toContainText('Connections');
    await expect(page.getByTestId('graph-relationships-empty')).toHaveCount(0);

    await page.getByTestId(`graph-entity-row-${CODE_ENTITY_ID}`).click();
    await expect(page.getByTestId('graph-entity-details')).toContainText(CODE_ENTITY_ID, { timeout: 30_000 });
    const afterExpand = await entityRows.count();
    expect(afterExpand).toBeGreaterThan(1);

    // A failed expansion: a real transport failure, not an intercepted route. The results
    // must survive it and the reason must be on screen (M-01, and the empty state must not
    // tell the operator to do the thing that just failed - M-65).
    const selectedBefore = await page.getByTestId('graph-entity-details').innerText();
    const relsBefore = await relRows.count();
    // The label must describe what is on screen BEFORE the failure, and still describe it
    // after: these rows are one entity's neighborhood, not the first N of the corpus.
    const labelBefore = await page.getByTestId('graph-entity-count').innerText();
    expect(labelBefore).toContain('in this neighborhood');

    await context.setOffline(true);
    await page.locator('[data-testid^="graph-entity-row-"]').nth(1).click();

    await expect(page.getByTestId('graph-expansion-failed')).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('graph-expansion-failed')).toContainText('unchanged');
    // One error surface, not two stacked red boxes saying the same sentence (F-02).
    await expect(page.getByTestId('graph-error')).toHaveCount(0);
    expect(await entityRows.count(), 'a failed expansion must not clear the results').toBe(afterExpand);
    expect(await relRows.count(), 'a failed expansion must not clear the graph').toBe(relsBefore);
    // F-01: the count label must not relabel a neighborhood as a slice of the corpus.
    const labelAfter = await page.getByTestId('graph-entity-count').innerText();
    expect(labelAfter, 'a failed expansion must not relabel the loaded scope').toBe(labelBefore);
    expect(labelAfter).not.toContain('in this corpus');
    // The selection must not move to an entity whose neighborhood never loaded, or the
    // panel would show the previous entity's relationships under the new entity's name.
    expect(await page.getByTestId('graph-entity-details').innerText()).toBe(selectedBefore);
    // ...and no empty state anywhere may tell the operator to redo what just failed.
    const looping = page.getByText('Select an entity to load its neighborhood');
    expect(await looping.count()).toBe(0);
    await context.setOffline(false);
  });
});

test.describe('Graph Explorer on a corpus with no entity graph', () => {
  test('M-60/M-66: the empty state names the missing entity graph and the API 404 names the id', async ({
    page,
    baseURL,
  }) => {
    const stats = await (await page.request.get(`${API_BASE}/graph/${NO_ENTITY_CORPUS}/stats`)).json();
    expect(stats.total_entities).toBe(0);
    expect(stats.total_chunks).toBeGreaterThan(0);

    await gotoGraph(page, baseURL, NO_ENTITY_CORPUS);
    await expect(page.getByTestId('graph-entity-empty-hint')).toBeVisible({ timeout: 60_000 });
    const empty = page.getByTestId('graph-communities-empty');
    await expect(empty).toContainText('no entity graph');
    await expect(empty).not.toContainText('Force re-index');
    await expect(empty).not.toContainText('community detection has not produced');

    // The entity routes answer a missing id with a 404 that names it, over real HTTP.
    const missing = await page.request.get(`${API_BASE}/graph/${NO_ENTITY_CORPUS}/entity/neighbors`, {
      params: { entity_id: CODE_ENTITY_ID },
    });
    expect(missing.status()).toBe(404);
    expect((await missing.json()).detail).toContain(CODE_ENTITY_ID);
  });
});


test.describe('Retrieval graph-leg readiness', () => {
  // M-66 (C-43): Graph reported 0 entities / 0 relationships / 0 communities for
  // `nasa-apollo-11` while Retrieval for the SAME corpus showed ENABLE GRAPH SEARCH on,
  // GRAPH TOP-K 30, GRAPH WEIGHT 0.3 and EXPAND VIA ENTITIES on, with nothing to suggest
  // the entity half of the leg could not fire. The card now states the corpus's readiness.
  async function openGraphLeg(page: Page, baseURL: string | undefined, corpusId: string) {
    await activateCorpusInBrowser(page, corpusId);
    await page.goto(
      new URL(`rag?subtab=retrieval&corpus=${encodeURIComponent(corpusId)}`, baseURL).toString(),
      { waitUntil: 'domcontentloaded' }
    );
    await page.getByTestId('retrieval-card-search_paths').click();
    await expect(page.getByTestId('retrieval-graph-readiness')).toBeVisible({ timeout: 60_000 });
  }

  test('a corpus with no entity graph says so on the graph-leg card', async ({ page, baseURL }) => {
    const stats = await (await page.request.get(`${API_BASE}/graph/${NO_ENTITY_CORPUS}/stats`)).json();
    expect(stats.total_entities).toBe(0);
    expect(stats.total_chunks).toBeGreaterThan(0);

    await openGraphLeg(page, baseURL, NO_ENTITY_CORPUS);
    const readiness = page.getByTestId('retrieval-graph-readiness');
    await expect(readiness).toContainText('no entity graph');
    await expect(readiness).toContainText('entity expansion cannot contribute');
    await expect(readiness).toContainText(String(stats.total_chunks).replace(/\B(?=(\d{3})+(?!\d))/g, ','));
  });

  test('a corpus with an entity graph reports its real counts', async ({ page, baseURL }) => {
    const stats = await (await page.request.get(`${API_BASE}/graph/${CODE_CORPUS}/stats`)).json();
    expect(stats.total_entities).toBeGreaterThan(0);

    await openGraphLeg(page, baseURL, CODE_CORPUS);
    const readiness = page.getByTestId('retrieval-graph-readiness');
    await expect(readiness).toContainText('Graph ready');
    await expect(readiness).not.toContainText('no entity graph');
    await expect(readiness).toContainText(String(stats.total_entities).replace(/\B(?=(\d{3})+(?!\d))/g, ','));
  });
});
