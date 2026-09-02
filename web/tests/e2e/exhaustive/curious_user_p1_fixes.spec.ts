// Regressions for the 2026-08-25 curious-user drive P1 findings, driven against
// the real app and API (no request interception): M1 onboarding on real APIs
// (and M5, a non-forced rebuild of an indexed corpus, through its UI), M2 global
// settings search, M3 dock scroll bound, M4 light-theme deck legibility, M6 new
// chat threads follow the active corpus, M8 benchmark grounding disclosure,
// M10/M11 live alert rules + config-driven links, M12 MCP tools + search probe,
// and G1/G2/G3 relationship-based communities, whole-corpus edges and the
// fullscreen visualizer sizing.
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  API_BASE,
  EXHAUSTIVE_CHAT_MODEL,
  acceptanceCorpusPath,
  activateCorpusInBrowser,
  indexCorpus,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

const REAL_QUESTION = 'How often is the salinity sensor calibrated?';
const BENCHMARK_MODELS = [
  process.env.BENCHMARK_E2E_MODEL_A ?? 'openai.gpt-5.6-luna',
  process.env.BENCHMARK_E2E_MODEL_B ?? 'openai.gpt-5.4-mini',
];

function trackRequests(page: Page, predicate: (url: string) => boolean): () => string[] {
  const hits: string[] = [];
  page.on('request', (req) => {
    if (predicate(req.url())) hits.push(`${req.method()} ${req.url()}`);
  });
  return () => hits;
}

async function gotoWeb(page: Page, baseURL: string | undefined, path: string): Promise<void> {
  await page.goto(new URL(path, baseURL).toString(), { waitUntil: 'domcontentloaded' });
}

test.describe.serial('curious-user drive P1 fixes on an isolated corpus', () => {
  let corpus: ExhaustiveCorpus;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request, { index: true });
  });

  test.afterAll(async ({ request }) => {
    if (corpus) await corpus.dispose(request);
  });

  test('M2: global settings search indexes the config registry, never calls /api/search, and deep-links a field', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    const searchCalls = trackRequests(page, (url) => /\/api\/search(\?|$)/.test(url));
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.locator('#global-search').click();
    const input = page.getByRole('dialog', { name: 'Global search' }).locator('input').first();
    await expect(input).toBeVisible();
    await input.fill('fusion vector weight');
    const rows = page.getByTestId('global-search-result');
    await expect(rows.first()).toBeVisible({ timeout: 30_000 });
    const count = await rows.count();
    for (let i = 0; i < count; i += 1) {
      expect((await rows.nth(i).innerText()).trim().length, `row ${i} must not be blank`).toBeGreaterThan(3);
    }
    const target = rows.filter({ has: page.locator('[data-path="fusion.vector_weight"]') }).first();
    const configRow = page.locator('[data-testid="global-search-result"][data-path="fusion.vector_weight"]').first();
    await expect(configRow).toBeVisible();
    await configRow.click();
    await expect(page).toHaveURL(/\/admin\?subtab=advanced&q=fusion\.vector_weight/);
    await expect(page.locator('[data-testid="config-field-fusion.vector_weight"][data-highlighted="true"]')).toBeVisible({ timeout: 30_000 });
    expect(searchCalls(), 'the settings palette must not run RAG retrieval').toEqual([]);
    void target;
  });

  test('M3: a docked page scrolls inside the dock, not the window', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    // The Grafana Overview (operator deck) is the tall native page from the finding.
    await gotoWeb(page, baseURL, 'grafana?subtab=overview');
    await expect(page.locator('.obs-deck-title').first()).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('dock-current').click();
    await expect(page.getByTestId('dock-native')).toBeVisible({ timeout: 30_000 });
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await expect(page.getByTestId('dock-native')).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(1500);
    const metrics = await page.evaluate(() => {
      const side = document.getElementById('sidepanel') as HTMLElement;
      // The tallest scrollable region inside the dock: the docked page's content
      // must live in an inner scroll container, not stretch the layout grid.
      let innerScrollable = 0;
      side.querySelectorAll<HTMLElement>('*').forEach((el) => {
        if (el.scrollHeight > el.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(el).overflowY)) {
          innerScrollable = Math.max(innerScrollable, el.scrollHeight - el.clientHeight);
        }
      });
      return {
        documentScrollHeight: document.documentElement.scrollHeight,
        innerHeight: window.innerHeight,
        sidepanelHeight: side.getBoundingClientRect().height,
        innerScrollable,
      };
    });
    expect(metrics.documentScrollHeight, 'window must not scroll').toBeLessThanOrEqual(metrics.innerHeight + 2);
    expect(metrics.sidepanelHeight, 'the right panel is bounded to the viewport').toBeLessThanOrEqual(metrics.innerHeight);
    expect(metrics.innerScrollable, 'the docked page scrolls inside the dock').toBeGreaterThan(0);
  });

  test('M4: the operator deck keeps light text on its dark gradient under the Light theme', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.addInitScript(() => {
      document.documentElement.setAttribute('data-theme', 'light');
    });
    await gotoWeb(page, baseURL, 'infrastructure?subtab=monitoring');
    const title = page.locator('.obs-deck-title').first();
    await expect(title).toBeVisible({ timeout: 30_000 });
    const colors = await page.evaluate(() => {
      const lum = (rgb: string) => {
        const m = rgb.match(/\d+(\.\d+)?/g) || [];
        const [r, g, b] = m.slice(0, 3).map((v) => Number(v) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      const style = (sel: string) => getComputedStyle(document.querySelector(sel) as Element);
      return {
        theme: document.documentElement.getAttribute('data-theme'),
        titleLum: lum(style('.obs-deck-title').color),
        subtitleLum: lum(style('.obs-deck-subtitle').color),
        kickerLum: lum(style('.obs-deck-kicker').color),
        bodyFgLum: lum(getComputedStyle(document.body).color),
      };
    });
    expect(colors.theme).toBe('light');
    expect(colors.bodyFgLum, 'the page itself is in light mode (dark body text)').toBeLessThan(0.2);
    // Light text (>= 0.6 luminance) on the deck's ~0.02 luminance gradient is >= 10:1.
    expect(colors.titleLum).toBeGreaterThan(0.6);
    expect(colors.subtitleLum).toBeGreaterThan(0.45);
    expect(colors.kickerLum).toBeGreaterThan(0.35);
  });

  test('M6: a fresh chat thread is scoped to the active corpus', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await gotoWeb(page, baseURL, 'chat?subtab=ui');
    const dropdown = page.getByTestId('source-dropdown');
    await expect(dropdown).toBeVisible({ timeout: 60_000 });
    await dropdown.locator('summary').click();
    const corpusBox = page.getByTestId(`source-corpus-${corpus.corpusId}`);
    await expect(corpusBox).toBeVisible();
    await expect(corpusBox).toBeChecked({ timeout: 30_000 });
    await expect(page.getByTestId('source-recall')).toBeChecked();
  });

  test('M10/M11: Monitoring lists the live Prometheus alert rules and links resolve from config', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    const deadCalls = trackRequests(page, (url) => url.includes('/api/monitoring/alert-thresholds'));
    await gotoWeb(page, baseURL, 'infrastructure?subtab=monitoring');
    await expect(page.getByTestId('alert-rules-table')).toBeVisible({ timeout: 60_000 });
    const watchdog = page.getByTestId('alert-rule-RagweldWatchdog');
    await expect(watchdog).toBeVisible();
    await expect(watchdog).toHaveAttribute('data-state', 'firing');
    await expect(page.getByTestId('alert-rules-summary')).toContainText('firing');
    const config = await (await page.request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpus.corpusId)}`)).json();
    const grafana = String(config.ui.grafana_base_url).replace(/\/$/, '');
    const prometheus = String(config.tracing.prometheus_base_url).replace(/\/$/, '');
    expect(grafana).toMatch(/^https?:\/\//);
    expect(prometheus).toMatch(/^https?:\/\//);
    await expect(page.getByTestId('open-grafana')).toHaveAttribute('href', grafana);
    await expect(page.getByTestId('open-prometheus')).toHaveAttribute('href', prometheus);
    // The table and the link resolve from the same authoritative (corpus-scoped) value.
    await expect(page.getByTestId('alert-rules-summary')).toContainText(prometheus);
    expect(grafana).not.toMatch(/:3000$/);
    expect(prometheus).not.toMatch(/:9090$/);
    expect(deadCalls()).toEqual([]);
  });

  test('M12: the MCP subtab lists registered tools and probes real retrieval', async ({ page, baseURL, request }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    // P2-B: the number that matters is the one the MOUNTED tools apply, which the status
    // boundary reports. `config.mcp.default_top_k` is only what a restart would mount.
    const mcpStatus = (await (await request.get(`${API_BASE}/mcp/status`)).json()) as {
      default_top_k?: number | null;
      default_mode?: string | null;
      config_default_top_k?: number | null;
      defaults_restart_pending?: boolean;
    };
    const mountedTopK = Number(mcpStatus.default_top_k ?? 0);
    expect(mountedTopK, 'the status must report the top_k the mounted MCP tools use').toBeGreaterThan(0);
    const deadCalls = trackRequests(page, (url) => /\/api\/mcp\/(http\/|test|rag_search)/.test(url));
    await gotoWeb(page, baseURL, 'infrastructure?subtab=mcp');
    await expect(page.getByTestId('mcp-tool-search')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('mcp-tool-answer')).toBeVisible();
    await expect(page.getByTestId('mcp-tool-list_corpora')).toBeVisible();
    await expect(page.getByTestId('mcp-http-url')).toContainText('/mcp/');
    await expect(page.getByTestId('mcp-error')).toHaveCount(0);
    // S40: the card described a top_k the probe does not use.
    const probeCard = page.getByTestId('mcp-probe');
    await expect(probeCard).toContainText(`top_k=${mountedTopK}`);
    await page.getByTestId('mcp-probe-question').fill(REAL_QUESTION);
    await page.getByTestId('mcp-probe-run').click();
    const results = page.getByTestId('mcp-probe-results');
    await expect(results).toBeVisible({ timeout: 60_000 });
    await expect(results).toContainText('sensor-calibration.md');
    // S34: the URL the probe reports is the in-process ASGI address, not the address an
    // MCP client dials, and the line has to say so.
    await expect(results).toContainText('in-process transport');
    await expect(results).toContainText('/mcp/');
    await expect(results).toContainText('tool search');
    await expect(results).toContainText(`top_k ${mountedTopK}`);
    await expect(results).toContainText('mode tribrid');
    expect(deadCalls()).toEqual([]);

    // P2-B: change the persisted default. The mounted tools keep the value they captured at
    // process start, so the card must keep describing THAT and say a restart is pending --
    // it used to print the new number over a tool that had never seen it.
    const configBefore = (await (await request.get(`${API_BASE}/config`)).json()) as { mcp?: { default_top_k?: number } };
    const configuredTopK = Number(configBefore.mcp?.default_top_k ?? 0);
    expect(configuredTopK).toBeGreaterThan(0);
    const changedTopK = mountedTopK + 7;
    const patched = await request.patch(`${API_BASE}/config/mcp`, { data: { default_top_k: changedTopK } });
    expect(patched.ok(), await patched.text()).toBe(true);
    // The card reads config through the store, which is scoped to the ACTIVE corpus, so the
    // operator's edit lands there too -- and a per-corpus `mcp.default_top_k` reaches the
    // mounted tool even less than the global one does.
    await patchCorpusConfigSection(request, corpus.corpusId, 'mcp', { default_top_k: changedTopK });
    try {
      await gotoWeb(page, baseURL, 'infrastructure?subtab=mcp');
      await expect(page.getByTestId('mcp-tool-search')).toBeVisible({ timeout: 60_000 });
      await expect(page.getByTestId('mcp-probe')).toContainText(`top_k=${mountedTopK}`);
      const pending = page.getByTestId('mcp-defaults-restart-pending');
      await expect(pending).toBeVisible({ timeout: 30_000 });
      await expect(pending).toContainText(`top_k=${changedTopK}`);
    } finally {
      const restored = await request.patch(`${API_BASE}/config/mcp`, { data: { default_top_k: configuredTopK } });
      expect(restored.ok(), await restored.text()).toBe(true);
      await patchCorpusConfigSection(request, corpus.corpusId, 'mcp', { default_top_k: configuredTopK });
    }
  });

  test('M8: the benchmark discloses that every model was grounded on the corpus', async ({ page, baseURL, request }) => {
    await patchCorpusConfigSection(request, corpus.corpusId, 'chat', { benchmark: { enabled: true, save_results: false } });
    await activateCorpusInBrowser(page, corpus.corpusId);
    await gotoWeb(page, baseURL, 'benchmark');
    await expect(page.getByTestId('benchmark-tab')).toBeVisible({ timeout: 60_000 });
    const checked = page.locator('input[type="checkbox"][aria-label^="Select "]:checked');
    await expect.poll(async () => checked.count(), { timeout: 60_000 }).toBeGreaterThan(0);
    while ((await checked.count()) > 0) await checked.first().uncheck();
    for (const alias of BENCHMARK_MODELS) {
      const row = page.locator('label').filter({ has: page.locator(`[title*="${alias}"]`) }).first();
      await expect(row, `${alias} must be in the catalog`).toBeVisible();
      await row.locator('input[type="checkbox"]').check();
    }
    await page.locator('textarea[aria-label="Benchmark prompt"]').fill(REAL_QUESTION);
    await page.getByTestId('benchmark-run').click();
    const grounding = page.getByTestId('benchmark-grounding');
    await expect(grounding).toBeVisible({ timeout: 180_000 });
    await expect(grounding).toHaveAttribute('data-grounded', 'true');
    await expect(grounding).toContainText('Grounded');
    await expect(grounding).toContainText('sensor-calibration');
    const contextCells = page.getByTestId('benchmark-context-chunks');
    await expect(contextCells).toHaveCount(BENCHMARK_MODELS.length);
    for (let i = 0; i < BENCHMARK_MODELS.length; i += 1) {
      await expect(contextCells.nth(i)).toContainText(/^[1-9]\d* chunks?$/);
    }
  });
});

test.describe.serial('G1/G2/G3 on a semantic graph corpus provisioned by the suite', () => {
  // The acceptance corpus indexed under the derived semantic policy (four
  // paid extraction calls through the cheap alias); no dependency on any
  // pre-existing corpus, so the graph assertions can never skip.
  let graphCorpus: ExhaustiveCorpus;
  let graphCorpusId = '';
  /** Node labels of the reviewed schema the run indexed against (the legend must show these). */
  let approvedNodeLabels: string[] = [];

  test.beforeAll(async ({ request }) => {
    test.setTimeout(10 * 60 * 1000);
    graphCorpus = await provisionExhaustiveCorpus(request, { index: false });
    graphCorpusId = graphCorpus.corpusId;
    await patchCorpusConfigSection(request, graphCorpusId, 'graph_indexing', {
      enabled: true,
      build_code_graph: false,
      semantic_kg_llm_model: EXHAUSTIVE_CHAT_MODEL,
    });
    // Semantic indexing runs only against a reviewed schema (Task 8): derive the proposal
    // the way the operator does on the Indexing page and approve its exact hash.
    const proposalRes = await request.post(`${API_BASE}/index/${encodeURIComponent(graphCorpusId)}/graph-schema/proposal`, {
      data: { force_refresh: false },
    });
    expect(proposalRes.ok(), await proposalRes.text()).toBeTruthy();
    const proposal = (await proposalRes.json()) as {
      schema_hash: string;
      schema?: { node_types?: Array<{ label: string }> };
      schema_payload?: { node_types?: Array<{ label: string }> };
    };
    expect(proposal.schema_hash).toMatch(/^[0-9a-f]{64}$/);
    approvedNodeLabels = ((proposal.schema ?? proposal.schema_payload)?.node_types ?? []).map((n) => n.label);
    expect(approvedNodeLabels.length, 'the reviewed schema names at least one node type').toBeGreaterThan(0);
    await indexCorpus(request, graphCorpusId, graphCorpus.corpusPath, { approvedGraphSchemaHash: proposal.schema_hash });
    const stats = await (await request.get(`${API_BASE}/graph/${encodeURIComponent(graphCorpusId)}/stats`)).json();
    expect(stats.total_entities, 'semantic extraction must produce entities').toBeGreaterThan(0);
    expect(stats.total_relationships, 'semantic extraction must produce relationships').toBeGreaterThan(0);
  });

  test.afterAll(async ({ request }) => {
    if (graphCorpus) await graphCorpus.dispose(request);
  });

  test('communities are relationship-based, the full view has edges, fullscreen fills the modal', async ({ page, baseURL }) => {
    const GRAPH_CORPUS_ID = graphCorpusId;
    await activateCorpusInBrowser(page, GRAPH_CORPUS_ID);
    await gotoWeb(page, baseURL, `rag?subtab=graph&corpus=${encodeURIComponent(GRAPH_CORPUS_ID)}`);
    await expect(page.getByTestId('graph-subtab')).toBeVisible({ timeout: 60_000 });
    const communities = page.locator('[data-testid^="graph-community-"]');
    await expect(communities.first()).toBeVisible({ timeout: 60_000 });
    const ids = await communities.evaluateAll((els) => els.map((el) => el.getAttribute('data-testid') || ''));
    expect(ids.length).toBeGreaterThan(1);
    for (const id of ids) {
      // Communities are GDS Leiden partitions since Task 7 (integer communityId), not the
      // label-propagation hashes the 2026-08-25 fix wave named `c-<12 hex>`.
      expect(id).toMatch(/^graph-community-\d+$/);
      expect(id).not.toContain('__staging__');
      expect(id).not.toContain('(root)');
    }
    await expect(page.getByTestId('graph-communities-empty')).toHaveCount(0);

    // Whole-corpus view: the visualizer is fed relationships, not only entities.
    const stats = await (await page.request.get(`${API_BASE}/graph/${encodeURIComponent(GRAPH_CORPUS_ID)}/subgraph?limit=200`)).json();
    expect(stats.relationships.length).toBeGreaterThan(0);
    await page.getByTestId('graph-view-visualization').click();
    await expect(page.getByTestId('graph-viz-canvas').locator('canvas')).toBeVisible({ timeout: 60_000 });

    const expand = page.getByTestId('graph-expand-btn');
    await expect(expand).toBeEnabled({ timeout: 30_000 });
    await expand.click();
    const modal = page.getByTestId('graph-fullscreen-modal');
    await expect(modal).toBeVisible();
    await page.waitForTimeout(700);
    const sizes = await page.evaluate(() => {
      const host = document.querySelector('[data-testid="graph-fullscreen-canvas"]') as HTMLElement;
      const canvas = host.querySelector('canvas') as HTMLCanvasElement;
      const rect = host.getBoundingClientRect();
      const modalRect = (document.querySelector('[data-testid="graph-fullscreen-modal"]') as HTMLElement).getBoundingClientRect();
      const header = (document.querySelector('[data-testid="graph-fullscreen-modal"]') as HTMLElement).firstElementChild as HTMLElement;
      return {
        hostW: rect.width,
        hostH: rect.height,
        canvasW: canvas?.getBoundingClientRect().width ?? 0,
        canvasH: canvas?.getBoundingClientRect().height ?? 0,
        modalW: modalRect.width,
        headerText: header?.textContent || '',
      };
    });
    expect(sizes.modalW).toBeGreaterThan(800);
    expect(sizes.canvasW, 'fullscreen canvas fills the modal width').toBeGreaterThan(sizes.modalW - 4);
    expect(sizes.canvasH, 'fullscreen canvas fills the modal height').toBeGreaterThan(sizes.hostH - 4);
    expect(sizes.headerText).toMatch(/\d+ nodes • [1-9]\d* edges/);
    // Entity types are the reviewed schema's labels since Task 8 (D1), not a closed
    // vocabulary; the legend lists them and never the code policy's kinds.
    const legend = page.getByTestId('graph-fullscreen-legend');
    const legendText = (await legend.innerText()).trim();
    expect(legendText.length).toBeGreaterThan(0);
    expect(
      approvedNodeLabels.some((label) => legendText.includes(label)),
      `legend "${legendText}" names none of the reviewed labels ${approvedNodeLabels.join(', ')}`,
    ).toBe(true);
    await expect(legend).not.toContainText('function');

    // G3: scroll-zoom changes the zoom transform AND repaints; clicking a node selects it.
    const canvasHash = async () =>
      page.evaluate(() => {
        const canvas = document.querySelector('[data-testid="graph-fullscreen-canvas"] canvas') as HTMLCanvasElement;
        const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
        let h = 0;
        for (let i = 0; i < data.length; i += 512) h = (h * 31 + data[i]) >>> 0;
        return h;
      });
    const zoomK = async () =>
      page.evaluate(() => {
        const canvas = document.querySelector('[data-testid="graph-fullscreen-canvas"] canvas') as HTMLCanvasElement & { __zoom?: { k: number } };
        return canvas.__zoom?.k ?? null;
      });
    await page.waitForTimeout(2500); // let the simulation settle so a frame diff means zoom, not layout
    const canvasBox = await page.getByTestId('graph-fullscreen-canvas').locator('canvas').boundingBox();
    expect(canvasBox).toBeTruthy();
    const center = { x: canvasBox!.x + canvasBox!.width / 2, y: canvasBox!.y + canvasBox!.height / 2 };
    const [k0, h0] = [await zoomK(), await canvasHash()];
    await page.mouse.move(center.x, center.y);
    await page.mouse.wheel(0, -600);
    await page.waitForTimeout(600);
    const [k1, h1] = [await zoomK(), await canvasHash()];
    expect(k0).not.toBeNull();
    expect(k1! > k0!, `wheel must zoom in (k ${k0} -> ${k1})`).toBeTruthy();
    expect(h1, 'the canvas must repaint after zoom').not.toBe(h0);

    // Find a painted node and click it. Node colours belong to the reviewed schema's
    // labels (D1), so the targets are read from the legend's own swatches rather than a
    // fixed palette.
    const nodePoint = await page.evaluate(() => {
      const canvas = document.querySelector('[data-testid="graph-fullscreen-canvas"] canvas') as HTMLCanvasElement;
      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;
      const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      const swatches = Array.from(
        document.querySelectorAll('[data-testid="graph-fullscreen-legend"] span span'),
      ) as HTMLElement[];
      const targets: number[][] = [];
      for (const swatch of swatches) {
        const match = getComputedStyle(swatch).backgroundColor.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (match) targets.push([Number(match[1]), Number(match[2]), Number(match[3])]);
      }
      if (targets.length === 0) return null;
      for (let y = Math.floor(canvas.height * 0.12); y < canvas.height * 0.88; y += 2) {
        for (let x = Math.floor(canvas.width * 0.05); x < canvas.width * 0.95; x += 2) {
          const i = (y * canvas.width + x) * 4;
          for (const [r, g, b] of targets) {
            if (Math.abs(data[i] - r) < 12 && Math.abs(data[i + 1] - g) < 12 && Math.abs(data[i + 2] - b) < 12) {
              return { x: rect.left + x / scaleX, y: rect.top + y / scaleY };
            }
          }
        }
      }
      return null;
    });
    expect(nodePoint, 'a node must be painted on the fullscreen canvas').toBeTruthy();
    await page.mouse.click(nodePoint!.x + 3, nodePoint!.y + 3);
    await expect(modal).toContainText(/\d+ connections/, { timeout: 15_000 });

    await page.getByTestId('graph-fullscreen-close').click();
    await expect(modal).toHaveCount(0);
  });
});

test.describe.serial('M1/M5: onboarding runs on the real corpus, index and chat APIs', () => {
  const corpusName = `Aurora onboarding ${Date.now().toString(36)}`;
  let createdCorpusId = '';

  async function disposeCorpus(request: APIRequestContext): Promise<void> {
    if (!createdCorpusId) return;
    await request.delete(`${API_BASE}/corpora/${encodeURIComponent(createdCorpusId)}`);
  }

  test.afterAll(async ({ request }) => {
    await disposeCorpus(request);
  });

  test('create corpus → build → rebuild (non-forced) → grounded first answer → chat', async ({ page, baseURL, request }) => {
    test.setTimeout(15 * 60 * 1000);
    await page.addInitScript(() => localStorage.removeItem('tribrid-onboarding-ui'));
    await gotoWeb(page, baseURL, 'start');
    await expect(page.getByTestId('onboarding-step-1')).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('onboarding-step-1')).toContainText('versioned config, prompts, and executable specs');
    await page.getByTestId('onboarding-next').click();

    await expect(page.getByTestId('onboarding-step-2')).toBeVisible();
    await expect(page.getByTestId('onboarding-next')).toBeDisabled();
    await page.getByTestId('onboarding-corpus-name').fill(corpusName);
    await page.getByTestId('onboarding-corpus-path').fill(acceptanceCorpusPath());
    await page.getByTestId('onboarding-create-corpus').click();

    await expect(page.getByTestId('onboarding-step-3')).toBeVisible({ timeout: 60_000 });
    const corpora = (await (await request.get(`${API_BASE}/corpora`)).json()) as Array<{ corpus_id: string; name: string }>;
    createdCorpusId = corpora.find((c) => c.name === corpusName)?.corpus_id || '';
    expect(createdCorpusId, 'the wizard registered the corpus through the API').toBeTruthy();
    // Test-lane cost isolation only (deterministic embeddings, cheap alias); the
    // wizard's own gate is the estimate + confirmation asserted below.
    await patchCorpusConfigSection(request, createdCorpusId, 'embedding', { embedding_backend: 'deterministic' });
    await patchCorpusConfigSection(request, createdCorpusId, 'generation', { enrich_disabled: true });
    await patchCorpusConfigSection(request, createdCorpusId, 'graph_indexing', { enabled: false });
    await patchCorpusConfigSection(request, createdCorpusId, 'reranking', { reranker_mode: 'none' });
    await patchCorpusConfigSection(request, createdCorpusId, 'chat', { litellm: { default_model: EXHAUSTIVE_CHAT_MODEL } });
    await patchCorpusConfigSection(request, createdCorpusId, 'ui', { chat_default_model: EXHAUSTIVE_CHAT_MODEL });

    // No index POST may happen before the operator sees the estimate and confirms.
    const indexPosts = trackRequests(page, (url) => /\/api\/index(\?|$)/.test(url));
    await page.getByTestId('onboarding-index-start').click();
    const estimateDialog = page.getByTestId('confirm-dialog');
    await expect(estimateDialog).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('confirm-dialog-message')).toContainText('Index estimate');
    await expect(page.getByTestId('confirm-dialog-message')).toContainText(/Files: \d+/);
    await expect(page.getByTestId('confirm-dialog-message')).toContainText(/Estimated cost/);
    expect(indexPosts(), 'no run starts before confirmation').toEqual([]);
    await page.getByTestId('confirm-dialog-cancel').click();
    await expect(estimateDialog).toHaveCount(0);
    expect(indexPosts(), 'cancel starts no run').toEqual([]);
    await page.getByTestId('onboarding-index-start').click();
    await expect(page.getByTestId('confirm-dialog')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('confirm-dialog-accept').click();
    const status = page.getByTestId('onboarding-index-status');
    await expect(status).toContainText(/Indexed \d+ files into \d+ chunks/, { timeout: 5 * 60 * 1000 });
    await expect(page.getByTestId('onboarding-index-error')).toHaveCount(0);
    const firstLog = await page.getByTestId('onboarding-index-log').innerText();
    expect(firstLog.length).toBeGreaterThan(20);

    // M5: a NON-forced rebuild of an already indexed corpus completes (it used to
    // fail with "Staging corpus not found" and leave a permanent error run).
    const rebuild = page.getByTestId('onboarding-index-start');
    await expect(rebuild).toHaveText('Rebuild indexes');
    await rebuild.click();
    await expect(page.getByTestId('confirm-dialog')).toBeVisible({ timeout: 60_000 });
    await page.getByTestId('confirm-dialog-accept').click();
    await expect(status).toContainText(/Starting|Indexing|%|chunk/i, { timeout: 30_000 });
    await expect(status).toContainText(/Indexed \d+ files into \d+ chunks/, { timeout: 5 * 60 * 1000 });
    await expect(page.getByTestId('onboarding-index-error')).toHaveCount(0);
    const latest = await (await request.get(`${API_BASE}/index/${encodeURIComponent(createdCorpusId)}/runs/latest`)).json();
    expect(latest.status).toBe('complete');
    expect(latest.error ?? null).toBeNull();

    await page.getByTestId('onboarding-next').click();
    await expect(page.getByTestId('onboarding-step-4')).toBeVisible();
    await page.getByTestId('onboarding-question').fill(REAL_QUESTION);
    await page.getByTestId('onboarding-ask').click();
    const answer = page.getByTestId('onboarding-answer');
    await expect(answer).toBeVisible({ timeout: 180_000 });
    await expect(page.getByTestId('onboarding-ask-error')).toHaveCount(0);
    await expect(answer).toContainText(/calibrat/i);
    await expect(page.getByTestId('onboarding-citations')).toContainText('sensor-calibration.md');

    await page.getByTestId('onboarding-next').click();
    await expect(page).toHaveURL(new RegExp(`/chat\\?corpus=${createdCorpusId}`));
  });
});

test.describe('S12: the Get Started wizard drops a deleted corpus and follows the active one', () => {
  let corpus: ExhaustiveCorpus;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request, { index: true });
  });

  test.afterAll(async ({ request }) => {
    await corpus?.dispose(request);
  });

  test('a persisted wizard corpus that no longer exists gives way to the URL corpus', async ({ page, baseURL }) => {
    // The 2026-09-02 drive found the wizard on step 4 of a corpus deleted three days earlier:
    // step 3 greyed out with "Pick or create a corpus in the previous step first" and step 4 with
    // "Build the indexes in the previous step first", while the corpus in the URL was indexed.
    await page.addInitScript(() => {
      localStorage.setItem(
        'tribrid-onboarding-ui',
        JSON.stringify({ state: { step: 4, corpusId: 'drive-scratch-runbooks' }, version: 0 })
      );
    });
    await gotoWeb(page, baseURL, `start?corpus=${encodeURIComponent(corpus.corpusId)}`);

    const step4 = page.getByTestId('onboarding-step-4');
    await expect(step4).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId('onboarding-wizard-corpus')).toContainText(corpus.corpusId, { timeout: 60_000 });
    await expect(step4).not.toContainText('Build the indexes in the previous step first');
    await expect(page.getByTestId('onboarding-question')).toBeVisible();

    await page.getByTestId('onboarding-dot-3').click();
    const step3 = page.getByTestId('onboarding-step-3');
    await expect(step3).toBeVisible();
    await expect(step3).not.toContainText('Pick or create a corpus in the previous step first');
    await expect(page.getByTestId('onboarding-wizard-corpus')).toContainText(corpus.corpusId);
    await expect(page.getByTestId('onboarding-index-start')).toHaveText('Rebuild indexes');
    await expect(page.getByTestId('onboarding-index-summary')).toBeVisible();

    await page.getByTestId('onboarding-dot-2').click();
    await expect(page.getByTestId('onboarding-existing-corpus')).toHaveValue(corpus.corpusId);

    const persisted = await page.evaluate(() => {
      const raw = localStorage.getItem('tribrid-onboarding-ui') || '{}';
      return (JSON.parse(raw) as { state?: { corpusId?: string } }).state?.corpusId || '';
    });
    expect(persisted, 'the stale corpus id must be replaced in the persisted wizard state').toBe(corpus.corpusId);
  });
});
