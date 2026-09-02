// A conversation owns its corpus: it remembers what it was answered from, and every write the
// chat surface makes is scoped to that corpus rather than to whatever `?corpus=` happens to say.
//
// M-03/B-04: Chat re-initialised its Sources from the global corpus on every mount, so coming
// back to a conversation reverted the picker while the answer from the other corpus was still
// on screen -- the next message in that thread would silently query a different corpus.
// M-02/B-03: with Sources = recall + corpus X, Top-K 10->12 issued
// `PATCH /api/config/retrieval?corpus_id=Y` and Helpful issued `POST /api/feedback?corpus_id=Y`,
// where Y was the stale global corpus. The feedback log is per-corpus training data, so that
// mislabels the reranker's inputs as well as mutating the wrong corpus's config.
// D20: the other half of M-03. Because a used thread is never rewritten, opening
// `/chat?corpus=X` over a conversation answered from Y silently searched Y and reported nothing
// about X. The surface must say so and offer the two honest moves (add X to this thread's
// Sources, or start a fresh thread about X), and a `thread=new` deep link must land in a fresh
// thread scoped to X without touching the used one.
import { expect, test, type Page } from '@playwright/test';
import { runSeedSearch, seedAnswerFromSearch, seedConversationFromRun } from './chat_seed';
import {
  acceptanceCorpusPath,
  API_BASE,
  EXHAUSTIVE_CHAT_MODEL,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(15 * 60 * 1000);

let corpus: ExhaustiveCorpus | null = null;
/** A second, different corpus, used as the stale global `?corpus=` the drive was bitten by. */
let otherCorpusId = '';

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: true });
  otherCorpusId = `ragweld-scope-other-${Date.now().toString(36)}`;
  const created = await request.post(`${API_BASE}/corpora`, {
    data: { corpus_id: otherCorpusId, name: otherCorpusId, path: acceptanceCorpusPath() },
  });
  expect(created.ok(), await created.text()).toBe(true);
});

test.afterAll(async ({ request }) => {
  if (corpus) await corpus.dispose(request);
  if (otherCorpusId) await request.delete(`${API_BASE}/corpora/${encodeURIComponent(otherCorpusId)}`);
});

/** Open Chat with the GLOBAL corpus set to `globalCorpusId` (the URL wins in useRepoStore). */
async function gotoChatWithGlobalCorpus(page: Page, globalCorpusId: string): Promise<void> {
  await page.goto(`chat?subtab=ui&corpus=${encodeURIComponent(globalCorpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

async function openSources(page: Page): Promise<void> {
  const dropdown = page.getByTestId('source-dropdown');
  await expect(dropdown).toBeVisible({ timeout: 30_000 });
  if (!(await dropdown.evaluate((el: HTMLDetailsElement) => el.open))) {
    await dropdown.locator('summary').click();
  }
  await expect(dropdown).toHaveJSProperty('open', true);
}

test('a conversation keeps the corpus it was answered from when the global corpus is different', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope spec',
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
  await expect(page.getByTestId(`source-corpus-${otherCorpusId}`)).not.toBeChecked();

  // Navigate away and back: B-04's exact move.
  await page.goto('benchmark', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
  await expect(page.getByTestId(`source-corpus-${otherCorpusId}`)).not.toBeChecked();

  // The persisted thread must not have been rewritten behind the operator's back either.
  const stored = await page.evaluate(() => localStorage.getItem('ragweld-chat-threads:v2'));
  expect(stored, 'the thread store must still exist').toBeTruthy();
  const parsed = JSON.parse(String(stored)) as {
    sessions: Array<{ conversation_id: string; sources?: { corpus_ids?: string[] } }>;
    active_conversation_id: string;
  };
  const active = parsed.sessions.find((s) => s.conversation_id === parsed.active_conversation_id);
  expect(active?.sources?.corpus_ids ?? []).toContain(corpus.corpusId);
  expect(active?.sources?.corpus_ids ?? []).not.toContain(otherCorpusId);
});

type StoredThreads = {
  sessions: Array<{ conversation_id: string; sources?: { corpus_ids?: string[] }; messages?: unknown[] }>;
  active_conversation_id: string;
};

async function readThreadStore(page: Page): Promise<StoredThreads> {
  const stored = await page.evaluate(() => localStorage.getItem('ragweld-chat-threads:v2'));
  expect(stored, 'the thread store must exist').toBeTruthy();
  return JSON.parse(String(stored)) as StoredThreads;
}

test('a used conversation shows the active-corpus mismatch notice and Add puts the corpus in Sources', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope mismatch spec',
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  // The thread was answered from `corpus`, the URL says `otherCorpusId`: the operator must be
  // told, in the conversation, instead of finding out from an answer that searched elsewhere.
  const notice = page.getByTestId('chat-active-corpus-mismatch');
  await expect(notice).toBeVisible({ timeout: 30_000 });
  await expect(notice).toContainText(otherCorpusId);

  await page.getByTestId('chat-add-active-corpus').click();
  await expect(notice).toHaveCount(0);
  // Adding a source is not a new thread: the seeded answer is still the conversation.
  await expect(page.getByTestId('chat-sources')).toHaveCount(1);

  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${otherCorpusId}`)).toBeChecked();
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();

  await expect
    .poll(
      async () => {
        const parsed = await readThreadStore(page);
        const active = parsed.sessions.find((s) => s.conversation_id === parsed.active_conversation_id);
        return active?.sources?.corpus_ids ?? [];
      },
      { timeout: 30_000 },
    )
    .toEqual(expect.arrayContaining([corpus.corpusId, otherCorpusId]));
});

test('a full reload keeps the thread and the source added to it: the seed is one-shot', async ({
  page,
  request,
}) => {
  // `seedAnswerFromSearch` installs an init script, and init scripts run on EVERY navigation
  // of the page, a `page.reload()` included. Until the seed marked itself applied, a reload
  // re-wrote the store with a fresh seeded thread, so a spec reloading to check persistence
  // was checking the seed, not the app (S28b). This reloads over a real change to the
  // persisted thread and expects the change, and the thread identity, to survive.
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope reload spec',
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });
  const seededId = (await readThreadStore(page)).active_conversation_id;
  expect(seededId).toBeTruthy();

  await page.getByTestId('chat-add-active-corpus').click();
  await expect(page.getByTestId('chat-active-corpus-mismatch')).toHaveCount(0);
  await expect
    .poll(
      async () => {
        const parsed = await readThreadStore(page);
        return parsed.sessions.find((s) => s.conversation_id === seededId)?.sources?.corpus_ids ?? [];
      },
      { timeout: 30_000 },
    )
    .toEqual(expect.arrayContaining([corpus.corpusId, otherCorpusId]));

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const after = await readThreadStore(page);
  expect(after.active_conversation_id, 'a reload must not mint another seeded thread').toBe(seededId);
  expect(after.sessions.map((s) => s.conversation_id)).toEqual([seededId]);
  const active = after.sessions.find((s) => s.conversation_id === seededId);
  expect(active?.sources?.corpus_ids ?? []).toEqual(expect.arrayContaining([corpus.corpusId, otherCorpusId]));
  // The surface agrees with the store: the added corpus is still a source, so nothing to warn about.
  await expect(page.getByTestId('chat-active-corpus-mismatch')).toHaveCount(0);
  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${otherCorpusId}`)).toBeChecked();
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
});

test('the notice is absent when the active corpus is already a source', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'What is the calibration interval?', {
    topK: 5,
    label: 'Corpus scope no-mismatch spec',
  });

  await gotoChatWithGlobalCorpus(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
  await expect(page.getByTestId('chat-active-corpus-mismatch')).toHaveCount(0);
});

test('thread=new opens a fresh conversation scoped to the URL corpus and leaves the used thread alone', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope deep-link spec',
  });

  await page.goto(`chat?subtab=ui&corpus=${encodeURIComponent(otherCorpusId)}&thread=new`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });

  // The link is consumed: a reload must not mint another thread.
  await expect
    .poll(() => page.evaluate(() => new URL(window.location.href).searchParams.get('thread')), {
      timeout: 30_000,
    })
    .toBeNull();
  expect(await page.evaluate(() => new URL(window.location.href).searchParams.get('corpus'))).toBe(otherCorpusId);

  // A fresh thread about the URL corpus: no answer on screen, nothing to warn about.
  await expect(page.getByTestId('chat-sources')).toHaveCount(0);
  await expect(page.getByTestId('chat-active-corpus-mismatch')).toHaveCount(0);
  await openSources(page);
  await expect(page.getByTestId(`source-corpus-${otherCorpusId}`)).toBeChecked();
  await expect(page.getByTestId(`source-corpus-${corpus.corpusId}`)).not.toBeChecked();

  const parsed = await readThreadStore(page);
  expect(parsed.sessions, 'the seeded thread plus the new one').toHaveLength(2);
  const active = parsed.sessions.find((s) => s.conversation_id === parsed.active_conversation_id);
  expect(active?.messages ?? []).toHaveLength(0);
  expect(active?.sources?.corpus_ids ?? []).toContain(otherCorpusId);
  expect(active?.sources?.corpus_ids ?? []).not.toContain(corpus.corpusId);
  const seeded = parsed.sessions.find((s) => s.conversation_id !== parsed.active_conversation_id);
  expect((seeded?.messages ?? []).length, 'the used thread keeps its answer').toBeGreaterThan(0);
  expect(seeded?.sources?.corpus_ids ?? []).toEqual([corpus.corpusId]);

  // Leaving and re-entering Chat remounts the surface over the consumed URL and keeps the
  // two threads: the deep link fired exactly once. This is an in-app navigation on purpose:
  // it proves the remount path; the full-reload path is proven by the reload test below.
  const sidebar = page.getByRole('navigation');
  await sidebar.getByRole('link', { name: 'Benchmark', exact: true }).click();
  await expect(page.locator('#chat-input')).toHaveCount(0);
  await sidebar.getByRole('link', { name: 'Chat', exact: true }).click();
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
  await expect(page.getByTestId('chat-sources')).toHaveCount(0);
  expect((await readThreadStore(page)).sessions).toHaveLength(2);
});

test('feedback on an answer is scoped to the conversation corpus, not the global one', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'What is the calibration interval?', {
    topK: 5,
    label: 'Corpus scope feedback spec',
  });

  const feedbackUrls: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && req.url().includes('/api/feedback')) feedbackUrls.push(req.url());
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  await page.getByTestId('chat-feedback-thumbsup').last().click();
  await expect.poll(() => feedbackUrls.length, { timeout: 30_000 }).toBeGreaterThan(0);

  const url = new URL(feedbackUrls[0]);
  expect(url.searchParams.get('corpus_id')).toBe(corpus.corpusId);
});

test('changing Top-K tunes this conversation and writes to no corpus at all', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope top-k spec',
  });

  const configWrites: string[] = [];
  page.on('request', (req) => {
    const method = req.method();
    if ((method === 'PATCH' || method === 'PUT' || method === 'POST') && req.url().includes('/api/config')) {
      configWrites.push(`${method} ${req.url()}`);
    }
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  // The baseline shown is the CONVERSATION corpus's configured final_k, not the global one.
  const scopedConfig = await request.get(`${API_BASE}/config`, {
    params: { corpus_id: corpus.corpusId },
  });
  expect(scopedConfig.ok(), await scopedConfig.text()).toBe(true);
  const expectedFinalK = Number(
    ((await scopedConfig.json()) as { retrieval?: { final_k?: number } }).retrieval?.final_k,
  );
  expect(Number.isFinite(expectedFinalK)).toBe(true);

  await page.getByTestId('chat-quick-settings').click();
  const topK = page.getByTestId('chat-top-k');
  await expect(topK).toBeVisible({ timeout: 30_000 });
  await expect.poll(async () => Number(await topK.inputValue()), { timeout: 30_000 }).toBe(expectedFinalK);

  await topK.fill(String(expectedFinalK + 2));
  await topK.blur();
  await page.waitForTimeout(1500); // settle window: under the staged model a chat quick-setting stages, never auto-writes

  expect(configWrites, 'a chat quick setting must not write a corpus config').toEqual([]);
  const after = await request.get(`${API_BASE}/config`, { params: { corpus_id: otherCorpusId } });
  expect(Number(((await after.json()) as { retrieval?: { final_k?: number } }).retrieval?.final_k)).not.toBe(
    expectedFinalK + 2,
  );
});

test('the conversation Top-K reaches the server and bounds a real answer', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  // One real, paid send: the wire contract (ChatRequest.top_k) and its effect on retrieval
  // breadth are the half a request-shape assertion cannot prove on its own.
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 5,
    label: 'Corpus scope live send spec',
  });
  await page.addInitScript((model) => {
    const raw = localStorage.getItem('ragweld-chat-threads:v2');
    if (!raw) return;
    const store = JSON.parse(raw) as { sessions: Array<{ model_override?: string }> };
    for (const session of store.sessions) session.model_override = model;
    localStorage.setItem('ragweld-chat-threads:v2', JSON.stringify(store));
  }, `litellm:${EXHAUSTIVE_CHAT_MODEL}`);

  const sentTopK: Array<number | null> = [];
  page.on('request', (req) => {
    if (req.method() !== 'POST' || !/\/api\/chat(\/stream)?$/.test(new URL(req.url()).pathname)) return;
    const body = req.postData();
    if (!body) return;
    sentTopK.push((JSON.parse(body) as { top_k?: number | null }).top_k ?? null);
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  await page.getByTestId('chat-quick-settings').click();
  const topK = page.getByTestId('chat-top-k');
  await expect(topK).toBeVisible({ timeout: 30_000 });
  await topK.fill('2');
  await page.getByTestId('chat-quick-settings').click();

  await page.locator('#chat-input').fill('What is the calibration interval for the salinity array?');
  await page.locator('#chat-send').click();
  await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 300_000 });

  expect(sentTopK, 'the send must carry the conversation Top-K').toContain(2);

  // A second answer really arrived (the seeded thread had exactly one), it has text, and its
  // citation list is bounded by the override the operator set - which the seeded answer's
  // five citations are not, so this cannot pass by reading the wrong message.
  const sourceBlocks = page.getByTestId('chat-sources');
  await expect.poll(async () => sourceBlocks.count(), { timeout: 120_000 }).toBe(2);
  const seededCitations = await sourceBlocks.first().getByTestId('chat-citation-open').count();
  expect(seededCitations, 'the seeded answer is the unbounded control').toBeGreaterThan(2);
  const answered = await sourceBlocks.last().getByTestId('chat-citation-open').count();
  expect(answered, `new answer cited ${answered} sources`).toBeGreaterThan(0);
  expect(answered).toBeLessThanOrEqual(2);

  // S37/P2-A on the live path: the run this send just produced is the conversation's own, and
  // the panel must not label it as coming from somewhere else. The seeded specs below prove the
  // reload and session-switch halves; this is the ordinary "ask, then look at the trace" one.
  await openTracePanel(page);
  const panel = page.locator('#chat-trace');
  await expect(panel).toContainText(/run_id: \S+/, { timeout: 60_000 });
  await expect(page.getByTestId('chat-trace-foreign-run')).toHaveCount(0);
});

test('the docked chat mirrors the live conversation instead of drifting into its own state', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'What is the calibration interval?', {
    topK: 5,
    label: 'Corpus scope dock spec',
  });
  // Dock the chat route, so the page renders TWO ChatInterface instances over one thread.
  await page.addInitScript(() => {
    localStorage.setItem(
      'tribrid-dock-storage',
      JSON.stringify({
        version: 0,
        state: {
          mode: 'dock',
          docked: { path: '/chat', search: '?subtab=ui', label: 'Chat', icon: '', renderMode: 'native' },
          lastDocked: null,
        },
      }),
    );
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  const pickers = page.getByTestId('source-dropdown');
  await expect.poll(async () => pickers.count(), { timeout: 60_000 }).toBe(2);

  // One picker at a time: since M-161 a pointer press outside a popover dismisses it, so
  // opening the docked copy closes the tab's. Read them in turn instead.
  const openPicker = async (index: number) => {
    const picker = pickers.nth(index);
    if (!(await picker.evaluate((el: HTMLDetailsElement) => el.open))) {
      await picker.locator('summary').click();
    }
    await expect(picker).toHaveJSProperty('open', true);
    return picker;
  };

  // Both instances start on the same conversation: the docked copy is not a third state.
  for (let i = 0; i < 2; i += 1) {
    const picker = await openPicker(i);
    await expect(picker.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
    await expect(picker.getByTestId(`source-corpus-${otherCorpusId}`)).not.toBeChecked();
  }

  // A change made in one instance reaches the other.
  const first = await openPicker(0);
  await first.getByTestId(`source-corpus-${otherCorpusId}`).check();
  const second = await openPicker(1);
  await expect(second.getByTestId(`source-corpus-${otherCorpusId}`)).toBeChecked({ timeout: 30_000 });
  await expect(second.getByTestId(`source-corpus-${corpus.corpusId}`)).toBeChecked();
});

test('mirroring the same conversation does not drop the operator per-conversation Top-K', async ({
  page,
  request,
}) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'What is the calibration interval?', {
    topK: 5,
    label: 'Corpus scope mirror-topk spec',
  });
  await page.addInitScript(() => {
    localStorage.setItem(
      'tribrid-dock-storage',
      JSON.stringify({
        version: 0,
        state: {
          mode: 'dock',
          docked: { path: '/chat', search: '?subtab=ui', label: 'Chat', icon: '', renderMode: 'native' },
          lastDocked: null,
        },
      }),
    );
  });

  await gotoChatWithGlobalCorpus(page, otherCorpusId);
  const pickers = page.getByTestId('source-dropdown');
  await expect.poll(async () => pickers.count(), { timeout: 60_000 }).toBe(2);

  // Set Top-K in the first instance.
  await page.getByTestId('chat-quick-settings').first().click();
  const topK = page.getByTestId('chat-top-k').first();
  await expect(topK).toBeVisible({ timeout: 30_000 });
  await topK.fill('3');
  await expect(topK).toHaveValue('3');

  // Now make the OTHER instance write, which broadcasts a reload of the SAME conversation.
  const otherPicker = pickers.nth(1);
  if (!(await otherPicker.evaluate((el: HTMLDetailsElement) => el.open))) {
    await otherPicker.locator('summary').click();
  }
  await expect(otherPicker).toHaveJSProperty('open', true);
  await otherPicker.getByTestId(`source-corpus-${otherCorpusId}`).check();
  await expect(pickers.first().getByTestId(`source-corpus-${otherCorpusId}`)).toBeChecked({
    timeout: 30_000,
  });

  // Mirroring one conversation into itself is not a session change: the setting survives.
  await expect(topK).toHaveValue('3');
});

test('Escape closes the Sources popover and puts focus back on its trigger', async ({ page }) => {
  // M-161/B-28: a native <details> ignores Escape, so this popover stayed open through
  // Escape and through opening other popovers - the drive ended with three stacked.
  await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });

  const dropdown = page.getByTestId('source-dropdown');
  const trigger = page.getByTestId('source-dropdown-trigger');
  await expect(dropdown).toBeVisible({ timeout: 30_000 });
  await trigger.click();
  await expect(dropdown).toHaveJSProperty('open', true);

  await page.keyboard.press('Escape');
  await expect(dropdown).toHaveJSProperty('open', false);
  // A keyboard operator must land back on the control they opened, not in the void.
  await expect(trigger).toBeFocused();
});

test('opening another chat control dismisses the Sources popover', async ({ page }) => {
  // B-28's actual evidence is the stacking: Sources "survives Escape AND clicking History
  // and New chat - three popovers stacked at once".
  await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });

  const dropdown = page.getByTestId('source-dropdown');
  await expect(dropdown).toBeVisible({ timeout: 30_000 });

  for (const other of ['chat-quick-settings', 'chat-history-toggle']) {
    await page.getByTestId('source-dropdown-trigger').click();
    await expect(dropdown).toHaveJSProperty('open', true);

    await page.getByTestId(other).click();
    await expect(dropdown, `Sources stayed open behind ${other}`).toHaveJSProperty('open', false);
  }
});


/** Open the Routing Trace panel, whatever `ui.chat_show_trace` left it as. */
async function openTracePanel(page: Page): Promise<void> {
  const panel = page.locator('#chat-trace');
  await expect(panel).toBeVisible({ timeout: 60_000 });
  // The panel follows `ui.chat_show_trace`, so it can already be open: clicking would close it.
  if (!(await panel.evaluate((el) => (el as HTMLDetailsElement).open))) {
    await panel.locator('summary').click();
  }
  await expect(panel).toHaveJSProperty('open', true);
}

test('the trace panel says when it is showing a run this conversation did not produce', async ({
  page,
  request,
}) => {
  // S37: with no answer in this conversation yet, the panel falls back to the corpus's most
  // recent run, which can be a Retrieval-tab search or an MCP probe. It rendered that under
  // "Routing Trace" with nothing saying where it came from.
  if (!corpus) throw new Error('corpus not provisioned');
  // A real run on the corpus that no conversation produced -- exactly the Retrieval-tab search
  // in the finding. Nothing is seeded into localStorage, so chat opens on an empty thread.
  const foreign = await runSeedSearch(request, corpus.corpusId, 'What calibrates the salinity array?', 5);
  await gotoChatWithGlobalCorpus(page, corpus.corpusId);
  await openTracePanel(page);
  const panel = page.locator('#chat-trace');
  await expect(panel).toContainText(`run_id: ${foreign.runId}`, { timeout: 60_000 });
  const notice = page.getByTestId('chat-trace-foreign-run');
  await expect(notice).toBeVisible({ timeout: 60_000 });
  await expect(notice).toContainText(corpus.corpusId);
});

test('the conversation that produced the run keeps it across a reload and a session switch', async ({
  page,
  request,
}) => {
  // The other half of S37 (P2-A): "this conversation" was collected from window events this tab
  // happened to witness, so it was empty after a reload -- the panel called the conversation's
  // OWN answer a foreign run -- and switching conversations left the previous conversation's
  // run unlabelled. It is a property of the stored thread, not of the tab.
  if (!corpus) throw new Error('corpus not provisioned');
  const earlier = await runSeedSearch(request, corpus.corpusId, 'What is the calibration interval?', 5);
  await seedConversationFromRun(page, corpus.corpusId, 'What is the calibration interval?', earlier, {
    label: 'Earlier conversation',
  });
  // Seeded second, so this is the active thread AND the corpus's most recent run, which is the
  // run the panel falls back to when it has no explicit selection.
  const latest = await runSeedSearch(request, corpus.corpusId, 'How often is the salinity array calibrated?', 5);
  await seedConversationFromRun(page, corpus.corpusId, 'How often is the salinity array calibrated?', latest, {
    label: 'Latest conversation',
    append: true,
  });
  expect(latest.runId).not.toBe(earlier.runId);

  await gotoChatWithGlobalCorpus(page, corpus.corpusId);
  await openTracePanel(page);
  const panel = page.locator('#chat-trace');
  const notice = page.getByTestId('chat-trace-foreign-run');
  // The panel really is showing this conversation's run: an absent notice over an absent trace
  // would prove nothing.
  await expect(panel).toContainText(`run_id: ${latest.runId}`, { timeout: 60_000 });
  await expect(notice).toHaveCount(0);

  // A reload restores the same saved conversation, and it still owns its run.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
  await openTracePanel(page);
  await expect(panel).toContainText(`run_id: ${latest.runId}`, { timeout: 60_000 });
  await expect(notice).toHaveCount(0);

  // Switching to the other saved conversation leaves the same trace on screen, and that run is
  // now foreign: the label follows the conversation, not the tab.
  await page.getByTestId('chat-history-toggle').click();
  await page.getByRole('button').filter({ hasText: 'Earlier conversation' }).first().click();
  await expect(panel).toContainText(`run_id: ${latest.runId}`);
  await expect(notice).toBeVisible({ timeout: 30_000 });
  await expect(notice).toContainText(corpus.corpusId);
});
