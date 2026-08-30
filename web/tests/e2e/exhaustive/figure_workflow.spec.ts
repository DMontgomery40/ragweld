// Figure description, end to end through the operator's own surfaces.
//
// One temp corpus (the Aurora markdown fixture, for guaranteed text chunks, plus the two
// Apollo figure pages) drives the whole workflow against the live stack with zero route
// mocking: figures are switched on from the Indexing tab, the estimate prices the vision
// calls before anything is spent, a real index describes the figures through the gateway,
// and the resulting figure chunk is retrieved, badged in the citation list and opened in
// the source viewer. The last three tests are the GUI contract the Figures controls ship
// with: bounds clamping, commit-on-blur, Escape, and the nested-PATCH deep merge.
//
// `mode: 'serial'` — the corpus is provisioned once and each test builds on the previous
// one's state. A failure therefore SKIPS the tests after it; a red run must be read as
// "these scenarios were never exercised", not as a pass.
import { copyFileSync, cpSync, mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page, type Request } from '@playwright/test';
import { seedAnswerFromSearch } from './chat_seed';
import {
  API_BASE,
  acceptanceCorpusPath,
  indexCorpus,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(15 * 60 * 1000);

/**
 * Real question against the fixture's second page ("Figure 5-6. - Expanded pitch and roll
 * attitude time histories near landing."). It is answerable only from the figure's
 * description, which is exactly what the vision call produces.
 */
const FIGURE_QUESTION =
  'What does Figure 5-6 show about the lunar module pitch and roll attitude time histories near landing?';

/**
 * top_k for the seeded citation list. Measured on this fixture: at top_k 6 the result-shaping
 * stage answers with figure chunks only (4 of them), which would make the "the badge is
 * conditional" control vacuous; at 12 the same real query returns the whole corpus — 5 figure
 * chunks and 4 markdown text chunks — so one query produces a genuinely mixed list.
 */
const CITATION_TOP_K = 12;

/**
 * Deadline handed to `corpus_fixture.indexCorpus`. Its own default is 5 minutes
 * (`EXHAUSTIVE_INDEX_TIMEOUT_MS`), shorter than a Docling conversion of scanned pages plus the
 * per-figure vision calls takes on a loaded box — a measured 10-minute wait was not enough
 * while a production re-index held the shared converter. Passed explicitly rather than set in
 * the environment so the spec cannot fail for whoever forgets the env var.
 */
const INDEX_DEADLINE_MS = 30 * 60 * 1000;

/** Docling emits lower-case class names, so "Logo, logo" is one rule, not two. */
const SKIP_CLASSES_DEFAULT = ['logo', 'signature', 'icon'];

type FigureSettings = {
  enabled: boolean;
  describe: boolean;
  classify: boolean;
  vision_model: string;
  prompt_profile: string;
  images_scale: number;
  min_area_fraction: number;
  skip_classes: string[];
  max_completion_tokens: number;
  concurrency: number;
  timeout_s: number;
};

let corpus: ExhaustiveCorpus | null = null;
let corpusDir: string | null = null;
/** The operator's global (unscoped) figure settings, captured before anything is patched. */
let globalFiguresBaseline: FigureSettings | null = null;

function apolloFigurePdf(): string {
  return path.resolve(process.cwd(), 'tests', 'fixtures', 'acceptance_corpus_docs', 'apollo11_figure_pages.pdf');
}

async function figureSettings(request: APIRequestContext, corpusId?: string): Promise<FigureSettings> {
  const url = corpusId ? `${API_BASE}/config?corpus_id=${encodeURIComponent(corpusId)}` : `${API_BASE}/config`;
  const response = await request.get(url);
  if (!response.ok()) throw new Error(`GET ${url} -> ${response.status()} ${(await response.text()).slice(0, 200)}`);
  const config = (await response.json()) as { indexing: { figures: FigureSettings } };
  return config.indexing.figures;
}

/**
 * Status plus run id of the corpus's latest run, as one comparable string. `runs/latest` is
 * a 404 until the corpus has been indexed, so the baseline is the whole answer rather than a
 * run id that may not exist yet: any change means a run started.
 */
async function latestRunFingerprint(request: APIRequestContext, corpusId: string): Promise<string> {
  const response = await request.get(`${API_BASE}/index/${encodeURIComponent(corpusId)}/runs/latest`);
  if (!response.ok()) return `status=${response.status()}`;
  const run = (await response.json()) as { run_id?: string };
  return `status=200 run_id=${String(run.run_id || '')}`;
}

/**
 * Wait (bounded) for any run holding the corpus to leave "indexing". A corpus under a live
 * run cannot be deleted — `DELETE /api/corpora` answers 409 `index_run_in_progress` — so a
 * failure part-way through the index test would otherwise leak the corpus into the
 * operator's registry, which is exactly what `corpus_fixture` exists to prevent.
 */
async function settleAnyRun(request: APIRequestContext, corpusId: string): Promise<void> {
  const deadline = Date.now() + 10 * 60 * 1000;
  while (Date.now() < deadline) {
    const response = await request.get(`${API_BASE}/index/${encodeURIComponent(corpusId)}/status`);
    if (!response.ok()) return;
    const status = (await response.json()) as { status?: string };
    if (status.status !== 'indexing') return;
    await new Promise((resolve) => setTimeout(resolve, 5_000));
  }
}

/** Open the Indexing subtab for `corpusId` with the Figures component panel selected. */
async function gotoFiguresPanel(page: Page, corpusId: string): Promise<void> {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await expect(page.getByTestId('target-corpus-select')).toHaveValue(corpusId, { timeout: 90_000 });
  await page.getByTestId('indexing-component-card-figures').click();
  await expect(page.getByTestId('figures-card')).toBeVisible();
}

async function gotoChat(page: Page, corpusId: string): Promise<void> {
  await page.goto(`chat?corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

/** The citation card for a figure chunk: a PDF thumbnail card carrying the figure badge. */
function figureCitationCard(page: Page): Locator {
  return page
    .getByTestId('chat-citation-open-pdf')
    .filter({ has: page.getByTestId('chat-citation-figure-badge') })
    .first();
}

async function waitForIndexingPatch(page: Page, corpusId: string): Promise<void> {
  const response = await page.waitForResponse(
    (res) =>
      res.request().method() === 'PATCH' &&
      res.url().includes('/api/config/indexing') &&
      res.url().includes(encodeURIComponent(corpusId)),
    { timeout: 30_000 },
  );
  expect(response.status(), 'PATCH /api/config/indexing failed').toBe(200);
}

test.beforeAll(async ({ request }) => {
  // The Aurora markdown gives the corpus guaranteed non-figure chunks (the control in the
  // "badge is conditional" test); only the two-page Apollo PDF is copied from the docs
  // fixtures, so Docling converts two pages and the run costs exactly the figure calls on
  // them — the Aurora PDF/HTML would add conversions this workflow does not need.
  const dir = mkdtempSync(path.join(os.tmpdir(), 'ragweld-figures-'));
  corpusDir = dir;
  cpSync(acceptanceCorpusPath(), dir, { recursive: true });
  copyFileSync(apolloFigurePdf(), path.join(dir, 'apollo11_figure_pages.pdf'));
  globalFiguresBaseline = await figureSettings(request);
  corpus = await provisionExhaustiveCorpus(request, { index: false, corpusPath: dir });
});

test.afterAll(async ({ request }) => {
  if (corpus) {
    await settleAnyRun(request, corpus.corpusId);
    await corpus.dispose(request);
  }
  if (corpusDir) rmSync(corpusDir, { recursive: true, force: true });
});

test('Figures are enabled from the Indexing tab, persist per corpus, and leave the global config alone', async ({
  page,
  request,
}) => {
  if (!corpus || !globalFiguresBaseline) throw new Error('corpus not provisioned');
  const persistedVisionModel = (await figureSettings(request, corpus.corpusId)).vision_model;
  await gotoFiguresPanel(page, corpus.corpusId);

  const enabled = page.getByTestId('figures-enabled');
  await expect(enabled).not.toBeChecked();
  // The nested controls are rendered only once figures are on.
  await expect(page.getByTestId('figures-describe')).toHaveCount(0);
  await expect(page.getByTestId('figures-max-completion-tokens')).toHaveCount(0);

  const patched = waitForIndexingPatch(page, corpus.corpusId);
  await enabled.check();

  await expect(page.getByTestId('figures-describe')).toBeChecked();
  await expect(page.getByTestId('figures-classify')).toBeChecked();
  await expect(page.getByTestId('figures-vision-model')).toBeVisible();
  await expect(page.getByTestId('figures-prompt-profile')).toHaveValue('technical_figure');
  await expect(page.getByTestId('figures-images-scale')).toHaveValue('2');
  await expect(page.getByTestId('figures-min-area-fraction')).toHaveValue('0.02');
  await expect(page.getByTestId('figures-max-completion-tokens')).toHaveValue('2500');
  await expect(page.getByTestId('figures-concurrency')).toHaveValue('4');
  await expect(page.getByTestId('figures-timeout-s')).toHaveValue('90');
  await expect(page.getByTestId('figures-skip-classes')).toHaveValue(SKIP_CLASSES_DEFAULT.join(', '));
  // The absent-warning assertion below is only meaningful once the catalog has loaded: the
  // picker renders value="" until then, and the warning is suppressed for an empty catalog.
  // Assert the saved alias is actually selected first, so "no warning" cannot pass vacuously.
  expect(persistedVisionModel, 'no vision alias configured to assert on').not.toEqual('');
  await expect(page.getByTestId('figures-vision-model')).toHaveValue(persistedVisionModel);
  // The configured alias must actually be a vision-capable route in the live catalog, or
  // the run would be refused with 409 figure_vision_alias.
  await expect(page.getByTestId('figures-vision-model-warning')).toHaveCount(0);
  await patched;

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByTestId('indexing-component-card-figures').click();
  await expect(page.getByTestId('figures-enabled')).toBeChecked();
  await expect(page.getByTestId('figures-max-completion-tokens')).toHaveValue('2500');

  const scoped = await figureSettings(request, corpus.corpusId);
  expect(scoped.enabled).toBe(true);
  expect(scoped.max_completion_tokens).toBe(2500);
  expect(scoped.describe).toBe(true);
  // A corpus-scoped PATCH must not leak into the operator's global config.
  expect(await figureSettings(request)).toEqual(globalFiguresBaseline);
  expect(globalFiguresBaseline.enabled).toBe(false);
});

test('the index estimate prices the figure descriptions before any run starts', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const runBefore = await latestRunFingerprint(request, corpus.corpusId);
  await gotoFiguresPanel(page, corpus.corpusId);

  const indexNow = page.getByTestId('index-now-button');
  await expect(indexNow).toBeEnabled({ timeout: 90_000 });
  await indexNow.click();

  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 60_000 });
  const message = page.getByTestId('confirm-dialog-message');
  await expect(message).toContainText('Index estimate');
  await expect(message).toContainText('Cost breakdown:');
  const breakdown = await message.innerText();
  const figures = /Figures ≤ \$[\d,]+\.\d\d \(~(\d+)\)/.exec(breakdown);
  expect(figures, `no figure line in the cost breakdown:\n${breakdown}`).not.toBeNull();
  expect(Number(figures![1]), 'estimated_figures must be at least 1 for a 2-page PDF').toBeGreaterThanOrEqual(1);

  // Cancelling must start no run: the index itself is driven through the API so the spec
  // controls force_reindex and completion.
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).not.toBeVisible();
  await expect(page.getByTestId('index-estimate-summary')).toContainText(/\+ Figures ≤ \$/);
  await page.waitForTimeout(1_500);
  expect(await latestRunFingerprint(request, corpus.corpusId), 'cancelling the estimate started a run').toEqual(
    runBefore,
  );
});

test('a real index describes the figures and the run log reports the count', async ({ page, request }) => {
  if (!corpus || !corpusDir) throw new Error('corpus not provisioned');
  test.setTimeout(INDEX_DEADLINE_MS + 5 * 60 * 1000);
  // Explicit preconditions for the run (not a weakened assertion): the previous tests set
  // `enabled` through the GUI, and this states the rest of the figure lane the run needs.
  await patchCorpusConfigSection(request, corpus.corpusId, 'indexing', {
    figures: {
      enabled: true,
      describe: true,
      classify: true,
      images_scale: 2.0,
      min_area_fraction: 0.02,
      max_completion_tokens: 2500,
      concurrency: 4,
      timeout_s: 90,
    },
  });
  const scoped = await figureSettings(request, corpus.corpusId);
  expect(scoped.enabled && scoped.describe).toBe(true);

  await indexCorpus(request, corpus.corpusId, corpusDir, { timeoutMs: INDEX_DEADLINE_MS });

  await gotoFiguresPanel(page, corpus.corpusId);
  // Scoped to the Indexing subtab: RAGTab mounts every subtab at once, and more than one of
  // them renders a LiveTerminal, so the shared test id is not unique across the page.
  const indexingPanel = page.locator('#tab-rag-indexing');
  await indexingPanel.getByTestId('indexing-show-logs').click();
  const terminal = indexingPanel.getByTestId('live-terminal-output');
  await expect(terminal).toContainText('Figure summary:', { timeout: 60_000 });
  const log = await terminal.innerText();
  const described = /figures_described=(\d+)/.exec(log);
  expect(described, `no figures_described in the replayed run log:\n${log.slice(-2000)}`).not.toBeNull();
  expect(Number(described![1]), `the vision alias described no figure:\n${log.slice(-2000)}`).toBeGreaterThanOrEqual(1);
});

test('a figure citation is badged and its thumbnail boxes the figure region', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const matches = await seedAnswerFromSearch(page, request, corpus.corpusId, FIGURE_QUESTION, {
    topK: CITATION_TOP_K,
    label: 'Figure workflow spec',
  });
  // API-level precondition: separates "retrieval never surfaced a figure chunk" from
  // "the badge did not render".
  const figureMatches = matches.filter((m) => m.metadata?.chunk_kind === 'figure');
  expect(figureMatches.length, `no figure chunk in the top ${CITATION_TOP_K} for the figure question`).toBeGreaterThan(0);
  expect(
    figureMatches.some(
      (m) =>
        m.provenance?.extraction === 'docling' &&
        typeof m.provenance?.page_start === 'number' &&
        (m.provenance?.regions?.length ?? 0) > 0,
    ),
    'the figure chunk carries no Docling page regions',
  ).toBe(true);

  await gotoChat(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const badges = page.getByTestId('chat-citation-figure-badge');
  await expect(badges.first()).toBeVisible({ timeout: 30_000 });
  await expect(badges.first()).toHaveText(/^Figure/);

  const card = figureCitationCard(page);
  await expect(card).toBeVisible();
  await expect(card).toContainText('apollo11_figure_pages.pdf');
  const thumb = card.getByTestId('chat-citation-thumb');
  await expect
    .poll(async () => thumb.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), {
      timeout: 60_000,
    })
    .toBe(true);
  expect(await card.getByTestId('document-region').count(), 'the thumbnail draws no region overlay').toBeGreaterThan(0);
});

test('clicking the figure citation opens the page image with the figure description', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, FIGURE_QUESTION, {
    topK: CITATION_TOP_K,
    label: 'Figure workflow spec',
  });
  await gotoChat(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const card = figureCitationCard(page);
  await expect(card).toBeVisible({ timeout: 30_000 });
  await card.click();

  await expect(page.getByTestId('dock-mode-document')).toBeVisible();
  await expect(page.getByTestId('dock-title')).toContainText('· Figure');
  const viewer = page.getByTestId('document-viewer');
  await expect(viewer).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('document-viewer-title')).toHaveText('apollo11_figure_pages.pdf');
  const image = page.getByTestId('document-page-image');
  await expect
    .poll(async () => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), {
      timeout: 60_000,
    })
    .toBe(true);
  expect(await page.getByTestId('document-page-frame').getByTestId('document-region').count()).toBeGreaterThan(0);

  const badge = page.getByTestId('document-figure-badge');
  await expect(badge).toBeVisible();
  await expect(badge).toHaveText(/^Figure/);
  // The summary reads "Figure description", not "Cited text", for a figure chunk.
  await expect(viewer.locator('summary').filter({ hasText: 'Figure description' })).toBeVisible();
  await expect(page.getByTestId('document-cited-text')).toContainText(/pitch|roll|landing|descent/i);
});

test('the figure badge is conditional: ordinary citations in the same list carry none', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const matches = await seedAnswerFromSearch(page, request, corpus.corpusId, FIGURE_QUESTION, {
    topK: CITATION_TOP_K,
    label: 'Figure workflow spec',
  });
  expect(
    matches.filter((m) => m.metadata?.chunk_kind !== 'figure').length,
    'every seeded match was a figure chunk, so the control is vacuous',
  ).toBeGreaterThan(0);

  await gotoChat(page, corpus.corpusId);
  const sources = page.getByTestId('chat-sources').last();
  await expect(sources).toBeVisible({ timeout: 60_000 });
  await expect(sources.getByTestId('chat-citation-figure-badge').first()).toBeVisible({ timeout: 30_000 });

  const citations = sources.getByTestId(/^chat-citation-open(-pdf)?$/);
  const total = await citations.count();
  const badged = await sources.getByTestId('chat-citation-figure-badge').count();
  expect(total).toBe(matches.length);
  expect(badged).toBeGreaterThan(0);
  expect(badged, 'every citation was badged; the badge is not conditional').toBeLessThan(total);
});

test('numeric figure fields clamp to their bounds, commit on blur, and restore on Escape', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await gotoFiguresPanel(page, corpus.corpusId);

  // (a) above the maximum: images_scale is le=4.
  const scale = page.getByTestId('figures-images-scale');
  let patched = waitForIndexingPatch(page, corpus.corpusId);
  await scale.fill('99');
  await scale.blur();
  await expect(scale).toHaveValue('4');
  await patched;
  expect((await figureSettings(request, corpus.corpusId)).images_scale).toBe(4);

  // (b) skip classes collapse case-insensitively: "Logo, logo" is one rule.
  const skip = page.getByTestId('figures-skip-classes');
  patched = waitForIndexingPatch(page, corpus.corpusId);
  await skip.fill('Logo, logo');
  await skip.blur();
  await patched;
  expect((await figureSettings(request, corpus.corpusId)).skip_classes).toEqual(['logo']);

  // (c) below the minimum: max_completion_tokens is ge=64.
  const tokens = page.getByTestId('figures-max-completion-tokens');
  patched = waitForIndexingPatch(page, corpus.corpusId);
  await tokens.fill('1');
  await tokens.blur();
  await expect(tokens).toHaveValue('64');
  await patched;

  // (d) a value whose first keystroke is below the minimum must survive: typing "128" into
  // a ge=64 field commits 128, not 64 (the regression fixed by committing on blur).
  patched = waitForIndexingPatch(page, corpus.corpusId);
  await tokens.fill('128');
  await tokens.press('Tab');
  await expect(tokens).toHaveValue('128');
  await patched;
  expect((await figureSettings(request, corpus.corpusId)).max_completion_tokens).toBe(128);

  // (e) Escape restores the last committed value and saves nothing. The window opens after
  // (d)'s PATCH has landed, so a stale request cannot be mistaken for a new one.
  const patchesDuringEscape: string[] = [];
  const record = (sent: Request) => {
    if (sent.method() === 'PATCH' && sent.url().includes('/api/config/')) {
      patchesDuringEscape.push(`${sent.url()} ${sent.postData() ?? ''}`);
    }
  };
  page.on('request', record);
  await tokens.fill('256');
  await tokens.press('Escape');
  await expect(tokens).toHaveValue('128');
  await tokens.blur();
  await page.waitForTimeout(1_500);
  page.off('request', record);
  expect(patchesDuringEscape, 'Escape must not persist the abandoned edit').toEqual([]);
  expect((await figureSettings(request, corpus.corpusId)).max_completion_tokens).toBe(128);
});

test('a Retrieval numeric field commits on blur too', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await page.goto(`rag?subtab=retrieval&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await expect(page.getByTestId('retrieval-subtab')).toBeVisible({ timeout: 90_000 });
  await page.getByTestId('retrieval-card-search_paths').click();

  const field = page.getByTestId('max-chunks-per-file');
  await expect(field).toBeVisible();
  const patched = page.waitForResponse(
    (res) =>
      res.request().method() === 'PATCH' &&
      res.url().includes('/api/config/retrieval') &&
      res.url().includes(encodeURIComponent(corpus!.corpusId)),
    { timeout: 30_000 },
  );
  await field.fill('7');
  await field.press('Tab');
  await expect(field).toHaveValue('7');
  expect((await patched).status()).toBe(200);

  const response = await request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpus.corpusId)}`);
  expect(response.ok()).toBe(true);
  const config = (await response.json()) as { retrieval: { max_chunks_per_file: number } };
  expect(config.retrieval.max_chunks_per_file).toBe(7);
});

test('two nested figures edits inside the debounce window are sent as one deep-merged PATCH', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await gotoFiguresPanel(page, corpus.corpusId);
  await expect(page.getByTestId('figures-classify')).toBeChecked();
  await expect(page.getByTestId('figures-prompt-profile')).toHaveValue('technical_figure');

  const carriesBothKeys = (sent: Request): boolean => {
    if (sent.method() !== 'PATCH' || !sent.url().includes('/api/config/indexing')) return false;
    let body: unknown = null;
    try {
      body = sent.postDataJSON();
    } catch {
      return false;
    }
    const figures = (body as { figures?: Record<string, unknown> } | null)?.figures;
    return Boolean(figures && 'classify' in figures && 'prompt_profile' in figures);
  };
  const merged = page.waitForRequest(carriesBothKeys, { timeout: 30_000 });
  // Two nested `indexing.figures.*` edits inside the 300 ms debounce window. A shallow
  // merge of the pending patch would drop the first one entirely.
  await page.getByTestId('figures-classify').uncheck();
  await page.getByTestId('figures-prompt-profile').selectOption('schematic');
  const body = (await merged).postDataJSON() as { figures: Record<string, unknown> };
  expect(body.figures.classify).toBe(false);
  expect(body.figures.prompt_profile).toBe('schematic');

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByTestId('indexing-component-card-figures').click();
  await expect(page.getByTestId('figures-classify')).not.toBeChecked();
  await expect(page.getByTestId('figures-prompt-profile')).toHaveValue('schematic');

  const scoped = await figureSettings(request, corpus.corpusId);
  expect(scoped.classify).toBe(false);
  expect(scoped.prompt_profile).toBe('schematic');
  // The siblings of the two patched keys survived the merge on both sides.
  expect(scoped.enabled).toBe(true);
  expect(scoped.max_completion_tokens).toBe(128);
  expect(scoped.images_scale).toBe(4);
  expect(scoped.skip_classes).toEqual(['logo']);
});

// F4 (2026-08-30 drive): every `indexing.figures.*` hit in the global search routed to the
// Admin Advanced explorer -- a raw registry row -- so the Figures & Vision card the settings
// actually live on was unreachable from search.
test('a global search hit for a figures setting opens the Figures & Vision card', async ({ page }) => {
  if (!corpus) throw new Error('corpus not provisioned');

  // The dashboard renders no `figures` control, so this hit has to come from the config
  // registry: started from the Indexing tab, the on-page DOM index would answer first and
  // the config route would never be exercised.
  await page.goto(`dashboard?corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('.topbar', { timeout: 90_000 });

  await page.locator('#global-search').click();
  // Both terms, so the row is inside the 20-result cap whatever else mentions figures.
  await page.getByPlaceholder('Search all settings... (Ctrl+K)').fill('figures enabled');

  const hit = page.locator(
    '[data-testid="global-search-result"][data-path="indexing.figures.enabled"]',
  );
  await expect(hit).toBeVisible({ timeout: 30_000 });
  await expect(hit).toHaveAttribute('data-kind', 'config');
  await expect(hit).toContainText('Figures & Vision');
  await hit.click();

  await page.waitForURL(/\/rag\?[^#]*subtab=indexing/, { timeout: 30_000 });
  const params = new URL(page.url()).searchParams;
  expect(params.get('component')).toBe('figures');
  // The corpus the operator was working on survives the jump, so the card edits that scope.
  expect(params.get('corpus')).toBe(corpus.corpusId);

  await expect(page.getByTestId('figures-card')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('figures-enabled')).toBeFocused({ timeout: 30_000 });
});
