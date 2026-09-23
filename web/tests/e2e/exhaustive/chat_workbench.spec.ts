// Chat workbench UI defects (wave 2b, lane chat2). Every test here is seeded from
// localStorage and drives only client behaviour — no gateway model is called, so the whole
// file costs nothing to run. The paid Stop proof lives in chat_reliability.spec.ts.
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, patchCorpusConfigSection, provisionExhaustiveCorpus } from './corpus_fixture';
import { dragPanelCorner, overflowingPanels } from './panel_resize';

const SCHEMA_MODEL = String(process.env.GRAPH_E2E_KG_MODEL || '').trim() || 'deepseek.deepseek-v4-flash';

const THREADS_KEY = 'ragweld-chat-threads:v2';

type SeededMessage = {
  id: string;
  role: 'user' | 'assistant';
  createdAt: string;
  content: { type: 'text'; text: string }[];
  status?: { type: string; reason?: string; error?: string };
  metadata?: { custom?: Record<string, unknown> };
};

async function seedThread(
  page: Page,
  opts: { sources: { corpus_ids: string[] }; messages: SeededMessage[]; title?: string },
): Promise<string> {
  const convId = `chat2-seed-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  await page.addInitScript(
    ({ key, convId, sources, messages, title }) => {
      const now = Date.now();
      const session = {
        conversation_id: convId,
        created_at: now,
        updated_at: now,
        title: title || 'Chat2 seed',
        model_override: '',
        sources,
        messages,
      };
      localStorage.setItem(key, JSON.stringify({ version: 2, active_conversation_id: convId, sessions: [session] }));
    },
    { key: THREADS_KEY, convId, sources: opts.sources, messages: opts.messages, title: opts.title },
  );
  return convId;
}

async function gotoChat(page: Page): Promise<void> {
  await page.goto('chat', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

function completedAssistant(text: string, custom: Record<string, unknown> = {}): SeededMessage {
  const now = Date.now();
  return {
    id: `assistant-${now}`,
    role: 'assistant',
    createdAt: new Date(now).toISOString(),
    content: [{ type: 'text', text }],
    status: { type: 'complete', reason: 'stop' },
    metadata: { custom: { runId: `spec-${now}`, ...custom } },
  };
}

test.describe.serial('chat workbench (seeded, no paid sends)', () => {
  test('M-05: Helpful / Not helpful are legible (>=11.5px, >=4.5:1)', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'hi' }] },
        completedAssistant('An answer with feedback controls.'),
      ],
    });
    await gotoChat(page);

    for (const testId of ['chat-feedback-thumbsup', 'chat-feedback-thumbsdown']) {
      const button = page.getByTestId(testId);
      await expect(button).toBeVisible();
      const metrics = await button.evaluate((el) => {
        const lin = (c: number): number => {
          const s = c / 255;
          return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        };
        const lum = (rgb: string): number => {
          const m = (rgb.match(/\d+(\.\d+)?/g) || ['0', '0', '0']).map(Number);
          return 0.2126 * lin(m[0]) + 0.7152 * lin(m[1]) + 0.0722 * lin(m[2]);
        };
        const contrast = (fg: string, bg: string): number => {
          const a = lum(fg);
          const b = lum(bg);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        };
        const bgOf = (node: HTMLElement | null): string => {
          let n: HTMLElement | null = node;
          while (n) {
            const c = getComputedStyle(n).backgroundColor;
            if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c;
            n = n.parentElement;
          }
          return 'rgb(0, 0, 0)';
        };
        const cs = getComputedStyle(el);
        const bg = bgOf(el.parentElement);
        return {
          fontSizePx: parseFloat(cs.fontSize),
          color: cs.color,
          opacity: parseFloat(cs.opacity),
          contrast: contrast(cs.color, bg),
        };
      });
      expect(metrics.fontSizePx, `${testId} font-size`).toBeGreaterThanOrEqual(11.5);
      expect(metrics.color, `${testId} colour must not be black-on-black`).not.toBe('rgb(0, 0, 0)');
      expect(metrics.opacity, `${testId} opacity floor`).toBeGreaterThanOrEqual(0.8);
      expect(metrics.contrast, `${testId} contrast (measured ${metrics.contrast.toFixed(2)}:1)`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test('M-93: an abandoned running stream reconciles to a retryable error on reload', async ({ page }) => {
    const now = Date.now();
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: 'why did it hang?' }] },
        {
          id: 'a1',
          role: 'assistant',
          createdAt: new Date(now + 1).toISOString(),
          content: [],
          status: { type: 'running' },
          metadata: { custom: {} },
        },
      ],
    });
    await gotoChat(page);

    // The orphan no longer renders "Streaming" forever; it is a terminal, retryable error.
    await expect(page.getByTestId('chat-streaming-elapsed')).toHaveCount(0);
    const errorCard = page.getByTestId('chat-assistant-error');
    await expect(errorCard).toBeVisible();
    await expect(errorCard).toContainText(/interrupted/i);
    await expect(page.getByTestId('chat-retry')).toBeVisible();
  });

  test('M-99: Export downloads a file and confirms', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'export me' }] },
        completedAssistant('Answer to export.'),
      ],
    });
    await gotoChat(page);

    const downloadPromise = page.waitForEvent('download', { timeout: 15_000 });
    await page.getByTestId('chat-export').click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^chat-export-\d+\.json$/);
    await expect(page.getByText(/Exported \d+ message/)).toBeVisible();
  });

  test('M-98: an attached image shows its name, size and type', async ({ page }) => {
    await seedThread(page, { sources: { corpus_ids: ['recall_default'] }, messages: [] });
    await gotoChat(page);

    // A minimal valid 1x1 PNG.
    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    await page.getByTestId('chat-image-input').setInputFiles({
      name: 'diagram.png',
      mimeType: 'image/png',
      buffer: Buffer.from(pngBase64, 'base64'),
    });

    const name = page.getByTestId('chat-attachment-name-0');
    await expect(name).toBeVisible();
    await expect(name).toHaveText('diagram.png');
    await expect(page.getByTestId('chat-attachment-0')).toContainText('PNG');
  });

  test('M-94: source scores carry a label and a consistent 3-dp precision', async ({ page }) => {
    const sources = [
      { chunk_id: 'c1', content: 'alpha', file_path: 'src/a.py', start_line: 1, end_line: 5, score: 0.0432, source: 'vector', metadata: { corpus_id: 'demo' } },
      { chunk_id: 'c2', content: 'beta', file_path: 'src/b.py', start_line: 9, end_line: 12, score: 0.7, source: 'sparse', metadata: { corpus_id: 'demo' } },
    ];
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'scores?' }] },
        completedAssistant('Answer with scored sources.', { sources }),
      ],
    });
    await gotoChat(page);

    const block = page.getByTestId('chat-sources');
    await expect(block).toBeVisible();
    // Header count matches the two rendered corpus sources.
    await expect(page.getByTestId('chat-sources-header')).toHaveText('Sources (2)');
    // Every score is labelled and rendered to exactly three decimals.
    const scoreTexts = await block.getByText(/score \d/).allInnerTexts();
    expect(scoreTexts.length).toBeGreaterThanOrEqual(2);
    for (const t of scoreTexts) {
      expect(t, `score "${t}" should be labelled with 3-dp precision`).toMatch(/score \d+\.\d{3}\b/);
    }
  });

  test('M-95: a multimodal answer lists its attached image sources', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'what is in this image?' }] },
        completedAssistant('It shows a diagram.', { attachedImageCount: 2 }),
      ],
    });
    await gotoChat(page);
    const imageSource = page.getByTestId('chat-source-attached-images');
    await expect(imageSource).toBeVisible();
    await expect(imageSource).toContainText(/2 attached images/);
  });

  test('M-97: a long answer does not grow a horizontal scrollbar at 1024px', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 768 });
    const longWord = 'x'.repeat(400);
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'long?' }] },
        completedAssistant(`Here is an unbreakable token ${longWord} and a wide line ${longWord}.`),
      ],
    });
    await gotoChat(page);
    // The chat surface must not overflow horizontally (wide content wraps/scrolls internally).
    const overflow = await page.locator('[data-react-chat="true"]').evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow, 'chat surface should not scroll horizontally').toBeLessThanOrEqual(1);
    const bodyOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(bodyOverflow, 'page should not scroll horizontally').toBeLessThanOrEqual(1);
  });

  test('M-100: chat history shows a corpus badge and a timestamp', async ({ page }) => {
    // Two sessions: the ACTIVE one is recall-only (so the "drop unknown corpora" effect,
    // which only reconciles the active session, never prunes our synthetic corpus id); an
    // INACTIVE session carries the corpus whose badge the History row must show.
    await page.addInitScript(() => {
      const now = Date.now();
      const active = {
        conversation_id: 'chat2-hist-active',
        created_at: now,
        updated_at: now + 10,
        title: 'active recall chat',
        model_override: '',
        sources: { corpus_ids: ['recall_default'] },
        messages: [
          { id: 'ua', role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: 'hi' }] },
        ],
      };
      const withCorpus = {
        conversation_id: 'chat2-hist-corpus',
        created_at: now,
        updated_at: now,
        title: 'oxygen recycling question',
        model_override: '',
        sources: { corpus_ids: ['recall_default', 'apollo-corpus'] },
        messages: [
          { id: 'uc', role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: 'how was oxygen recycled?' }] },
        ],
      };
      localStorage.setItem(
        'ragweld-chat-threads:v2',
        JSON.stringify({ version: 2, active_conversation_id: 'chat2-hist-active', sessions: [active, withCorpus] }),
      );
    });
    await gotoChat(page);
    await page.getByTestId('chat-history-toggle').click();
    // The corpus session's History row shows its corpus badge and Recall, plus a timestamp/msgs.
    const corpora = page.getByTestId('chat-history-corpora').filter({ hasText: 'apollo-corpus' });
    await expect(corpora).toBeVisible();
    await expect(corpora).toContainText('Recall');
    await expect(page.getByText(/msgs: \d/).first()).toBeVisible();
  });

  test('M-96: recall-only selection reads "Recall", never "1 selected"', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'memory only' }] },
        completedAssistant('Recall-only answer.'),
      ],
    });
    await gotoChat(page);

    const trigger = page.getByTestId('source-dropdown-trigger');
    await expect(trigger).toContainText('Recall');
    await expect(trigger).not.toContainText(/\bselected\b/);
    await expect(trigger).not.toContainText(/\bcorpus\b|\bcorpora\b/);
  });

  test('T8-7: the debug footer discloses the graph-leg counters recorded by the API', async ({ page, request }) => {
    // Task 8 step 7: a graph-including search must disclose the traversal accounting the
    // API actually recorded — Qdrant-seeded chunks, relationship expansions, hydrated chunks —
    // and never the retired entity-hit figure. The footer renders the message's own
    // ChatDebugInfo, so the assistant message is seeded with the REAL /api/search response of
    // a corpus that holds a real promoted semantic graph (schema proposed, approved and
    // extracted through the official pipeline against the live gateway).
    test.setTimeout(8 * 60 * 1000);
    const corpus = await provisionExhaustiveCorpus(request, { index: false });
    try {
      await patchCorpusConfigSection(request, corpus.corpusId, 'graph_indexing', {
        enabled: true,
        build_code_graph: false,
        semantic_kg_llm_model: SCHEMA_MODEL,
      });
      const proposalRes = await request.post(`${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/graph-schema/proposal`, {
        data: { force_refresh: false },
      });
      expect(proposalRes.ok(), await proposalRes.text()).toBeTruthy();
      const proposal = (await proposalRes.json()) as { schema_hash: string };
      expect(proposal.schema_hash).toMatch(/^[0-9a-f]{64}$/);

      const started = await request.post(`${API_BASE}/index`, {
        data: {
          corpus_id: corpus.corpusId,
          repo_path: corpus.corpusPath,
          force_reindex: true,
          approved_graph_schema_hash: proposal.schema_hash,
        },
      });
      expect(started.ok(), await started.text()).toBeTruthy();
      const deadline = Date.now() + 6 * 60 * 1000;
      let latest: { status?: string; error?: string | null; graph_promotable?: boolean | null } = {};
      while (Date.now() < deadline) {
        const latestRes = await request.get(`${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/runs/latest`);
        if (latestRes.ok()) {
          latest = (await latestRes.json()) as typeof latest;
          if (latest.status === 'complete' || latest.status === 'error' || latest.status === 'cancelled') break;
        }
        await page.waitForTimeout(3000);
      }
      expect(latest.status, `run ended ${latest.status}: ${latest.error || ''}`).toBe('complete');
      expect(latest.graph_promotable).toBe(true);

      const res = await request.post(`${API_BASE}/search`, {
        data: {
          query: 'tidal calibration campaign',
          corpus_id: corpus.corpusId,
          // The fixture has four chunks and traversal credits only NON-seed chunks, so a
          // four-seed search has nothing left to hydrate; two seeds leave two to reach.
          top_k: 2,
          include_vector: true,
          include_sparse: true,
          include_graph: true,
          cache_mode: 'bypass',
        },
      });
      expect(res.ok(), await res.text()).toBeTruthy();
      const body = (await res.json()) as { matches: unknown[]; debug: Record<string, unknown> };
      // A graph-including search on a promoted graph: the leg ran and every counter is a real number.
      expect(body.debug.fusion_graph_enabled).toBe(true);
      expect(body.debug).not.toHaveProperty('fusion_graph_entity_hits');
      for (const key of ['fusion_graph_qdrant_seed_chunks', 'fusion_graph_relationship_expansion_hits', 'fusion_graph_hydrated_chunks']) {
        expect(typeof body.debug[key], key).toBe('number');
      }
      expect(Number(body.debug.fusion_graph_qdrant_seed_chunks)).toBeGreaterThan(0);
      expect(Number(body.debug.fusion_graph_hydrated_chunks)).toBeGreaterThan(0);
      // The chat wire contract (ChatDebugInfo) carries the same accounting under its own
      // names; the seed carries the recorded search values under those names.
      const debug = {
        llm_used: true,
        graph_enabled: body.debug.fusion_graph_enabled,
        graph_qdrant_seed_chunks: body.debug.fusion_graph_qdrant_seed_chunks,
        graph_relationship_expansion_hits: body.debug.fusion_graph_relationship_expansion_hits,
        graph_hydrated_chunks: body.debug.fusion_graph_hydrated_chunks,
      };

      await seedThread(page, {
        sources: { corpus_ids: [corpus.corpusId] },
        messages: [
          { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'tidal calibration campaign' }] },
          completedAssistant('Grounded answer seeded from retrieval.', { sources: body.matches, debug }),
        ],
      });
      await gotoChat(page);

      const graphLine = page.getByTestId('chat-debug-graph');
      await expect(graphLine).toBeVisible();
      await expect(graphLine).toHaveText(
        'graph: graph_enabled=true ' +
          `graph_qdrant_seed_chunks=${String(debug.graph_qdrant_seed_chunks)} ` +
          `graph_relationship_expansion_hits=${String(debug.graph_relationship_expansion_hits)} ` +
          `graph_hydrated_chunks=${String(debug.graph_hydrated_chunks)}`
      );
      await expect(graphLine).not.toContainText('entity_hits');
    } finally {
      await corpus.dispose(request);
    }
  });
});

// GUI-050 / GUI-052 / GUI-059, revised: the workbench is a panel like every other. It opens at a
// comfortable default height, NOT pinned to fill the pane (the operator read the fill-the-pane
// version as "frozen solid all the way open"), and the operator drags it taller or shorter from
// its corner through the global resizable-panel rule; the height is remembered per viewer.
// Seeded from localStorage (no sends), real app + API, measured at deviceScaleFactor 1.
test.describe('chat workbench is a resizable panel (GUI-050)', () => {
  test.use({ deviceScaleFactor: 1 });

  const LAYOUT_QUESTION = 'What is the calibration interval for the pressure sensor on the acceptance rig?';
  const WORKBENCH = '.main-content [data-resizable="chat-workbench"]';

  type ChatGeom = {
    innerH: number;
    scrollportBottom: number;
    panelTop: number;
    panelBottom: number;
    panelH: number;
    panelClientH: number;
    workbenchH: number;
    messagesH: number;
    traceTop: number | null;
    resize: string;
  };

  async function seedLayoutThread(page: Page): Promise<void> {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: LAYOUT_QUESTION }] },
        completedAssistant('The acceptance rig recalibrates the pressure sensor every 90 days.'),
      ],
    });
  }

  // The message region is found as the scroll container of the seeded question, so the
  // measurement does not trust a test id to point at the right element.
  async function measure(page: Page): Promise<ChatGeom> {
    return page.evaluate(
      ({ selector, question }) => {
        const panel = document.querySelector(selector) as HTMLElement;
        const root = panel.querySelector('[data-react-chat="true"]') as HTMLElement;
        const scrollport = panel.closest('.tab-content') as HTMLElement;
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        let questionNode: Node | null = null;
        while (walker.nextNode()) {
          if ((walker.currentNode.textContent || '').includes(question)) {
            questionNode = walker.currentNode;
            break;
          }
        }
        let messages: HTMLElement | null = questionNode ? questionNode.parentElement : null;
        while (messages && messages !== root && !/(auto|scroll)/.test(getComputedStyle(messages).overflowY)) {
          messages = messages.parentElement;
        }
        const trace = document.querySelector('.main-content #chat-trace') as HTMLElement | null;
        const sp = scrollport.getBoundingClientRect();
        const pr = panel.getBoundingClientRect();
        return {
          innerH: window.innerHeight,
          scrollportBottom: Math.round(sp.top + scrollport.clientHeight),
          panelTop: Math.round(pr.top),
          panelBottom: Math.round(pr.bottom),
          panelH: Math.round(pr.height),
          panelClientH: panel.clientHeight,
          workbenchH: Math.round(root.getBoundingClientRect().height),
          messagesH: messages && messages !== root ? Math.round(messages.getBoundingClientRect().height) : -1,
          traceTop: trace && trace.offsetParent ? Math.round(trace.getBoundingClientRect().top) : null,
          resize: getComputedStyle(panel).resize,
        };
      },
      { selector: WORKBENCH, question: LAYOUT_QUESTION },
    );
  }

  for (const vp of [
    { width: 1440, height: 900 },
    { width: 1920, height: 1200 },
  ]) {
    test(`at ${vp.width}x${vp.height} it opens at a comfortable default, with Routing Trace below it in the pane`, async ({
      page,
    }) => {
      await page.setViewportSize(vp);
      await seedLayoutThread(page);
      await gotoChat(page);
      await page.waitForTimeout(500);

      const g = await measure(page);
      const detail = JSON.stringify(g);
      // clamp(520px, 68vh, 900px): a normal size, not the whole pane.
      const expected = Math.min(900, Math.max(520, Math.round(0.68 * g.innerH)));
      expect(Math.abs(g.panelH - expected), `default workbench height: ${detail}`).toBeLessThanOrEqual(2);
      expect(g.resize, detail).toBe('vertical');
      // The conversation fills the panel it is in.
      expect(g.panelClientH - g.workbenchH, `workbench does not fill its panel: ${detail}`).toBeLessThanOrEqual(1);
      expect(g.workbenchH - g.panelClientH, `workbench overflows its panel: ${detail}`).toBeLessThanOrEqual(1);
      expect(g.messagesH, `message list not found: ${detail}`).toBeGreaterThan(0);
      // The toolbar can wrap and carry a Sources notice; the conversation still gets real room.
      expect(g.messagesH, `message list is a strip: ${detail}`).toBeGreaterThanOrEqual(200);
      // Not pinned to the pane: the panel ends inside it and Routing Trace starts above its bottom.
      expect(g.panelBottom, `workbench runs to the pane bottom: ${detail}`).toBeLessThan(g.scrollportBottom);
      expect(g.traceTop, `Routing Trace is not rendered: ${detail}`).not.toBeNull();
      expect(g.traceTop!, `Routing Trace is pushed out of the pane: ${detail}`).toBeLessThan(g.scrollportBottom);
      expect(await overflowingPanels(page, '.main-content'), 'a resizable chat panel clips its content').toEqual([]);
    });
  }

  test('dragging its corner makes it shorter and taller, the conversation follows, and the height survives a reload', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await seedLayoutThread(page);
    await gotoChat(page);
    await page.waitForTimeout(500);
    const panel = page.locator(WORKBENCH);
    const start = await measure(page);

    // Count the height writes (a pass-through spy; the write itself still happens): a drag
    // rewrites the inline height every frame, and storage must see only where it came to rest.
    await page.evaluate(() => {
      const w = window as unknown as { __panelWrites: string[] };
      w.__panelWrites = [];
      const setItem = Storage.prototype.setItem;
      Storage.prototype.setItem = function (key: string, value: string) {
        if (key.startsWith('ragweld-panel-height:')) w.__panelWrites.push(`${key}=${value}`);
        return setItem.call(this, key, value);
      };
    });
    const shorter = (await dragPanelCorner(page, panel, -180)).to;
    await page.waitForTimeout(600);
    const writes = await page.evaluate(() => (window as unknown as { __panelWrites: string[] }).__panelWrites);
    expect(writes, 'the dragged height must be written once, after the drag').toEqual([
      `ragweld-panel-height:v1:main:chat-workbench=${shorter}`,
    ]);
    const shrunk = await measure(page);
    const shrunkDetail = JSON.stringify({ start, shrunk });
    expect(Math.abs(shorter - (start.panelH - 180)), shrunkDetail).toBeLessThanOrEqual(4);
    expect(Math.abs(shrunk.panelClientH - shrunk.workbenchH), shrunkDetail).toBeLessThanOrEqual(1);
    expect(Math.abs(start.messagesH - shrunk.messagesH - 180), `the message list did not give up the height: ${shrunkDetail}`).toBeLessThanOrEqual(8);
    // The edge moves, not the pane: resizing never scrolls the conversation away.
    expect(Math.abs(shrunk.panelTop - start.panelTop), shrunkDetail).toBeLessThanOrEqual(1);

    const taller = (await dragPanelCorner(page, panel, 120)).to;
    const grown = await measure(page);
    expect(Math.abs(taller - (shorter + 120)), JSON.stringify({ shrunk, grown })).toBeLessThanOrEqual(4);
    expect(grown.messagesH, JSON.stringify({ shrunk, grown })).toBeGreaterThan(shrunk.messagesH + 100);
    expect(Math.abs(grown.panelClientH - grown.workbenchH), JSON.stringify(grown)).toBeLessThanOrEqual(1);

    // It never collapses below a usable conversation (min-height 420px).
    const floor = (await dragPanelCorner(page, panel, -400)).to;
    expect(floor, 'the workbench shrank below its floor').toBeGreaterThanOrEqual(418);
    expect(floor).toBeLessThanOrEqual(424);

    // The size the operator leaves it at is the size it comes back at.
    const kept = (await dragPanelCorner(page, panel, 90)).to;
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#chat-input', { timeout: 90_000 });
    await page.waitForTimeout(500);
    const reloaded = await measure(page);
    expect(Math.abs(reloaded.panelH - kept), JSON.stringify({ kept, reloaded })).toBeLessThanOrEqual(2);
    expect(Math.abs(reloaded.panelClientH - reloaded.workbenchH), JSON.stringify(reloaded)).toBeLessThanOrEqual(1);
  });
});
