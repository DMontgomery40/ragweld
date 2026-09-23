import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import {
  API_BASE,
  EXHAUSTIVE_CHAT_MODEL,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';
import {
  installStreamProbe,
  startStreamFixture,
  startStreamProbe,
  stopStreamProbe,
  type StreamFixture,
  type StreamProbeMetrics,
} from './chat_stream_probe';
import { ACCEPTANCE_CORPUS_PROBES } from './suite_config';

// The corpus is provisioned per run over the acceptance fixture — with its own
// query log and triplets file — and deleted afterwards (it used to be a fixed
// `ragweld-exhaustive` id that leaked into the live registry and mined feedback
// into the operator's shared triplets file). There is deliberately no
// "use an existing corpus" override: this spec mutates config, feedback and
// triplets, and must never do that to an operator corpus.
let CORPUS_ID = '';
let provisioned: ExhaustiveCorpus | null = null;

test.beforeAll(async ({ request }) => {
  provisioned = await provisionExhaustiveCorpus(request, { index: true });
  CORPUS_ID = provisioned.corpusId;
});

test.afterAll(async ({ request }) => {
  if (provisioned) await provisioned.dispose(request);
});

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureCorpusExists(request: APIRequestContext): Promise<string[]> {
  const resp = await request.get(`${API_BASE}/corpora`);
  expect(resp.ok(), `expected /corpora to succeed, status=${resp.status()}`).toBeTruthy();
  const rows = (await resp.json()) as Array<{ corpus_id?: string; name?: string }>;
  const row = rows.find((c) => String(c?.corpus_id || '').trim() === CORPUS_ID);
  expect(Boolean(row), `expected corpus ${CORPUS_ID} to exist`).toBeTruthy();
  return Array.from(new Set([String(row?.name || '').trim(), CORPUS_ID].filter(Boolean)));
}

function corpusQuestion(index: number): string {
  return ACCEPTANCE_CORPUS_PROBES[index % ACCEPTANCE_CORPUS_PROBES.length].question;
}

async function getRerankerLogs(request: APIRequestContext, limit: number = 1000): Promise<Array<Record<string, unknown>>> {
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    const logsResp = await request.get(`${API_BASE}/reranker/logs?corpus_id=${encodeURIComponent(CORPUS_ID)}&limit=${limit}`);
    if (logsResp.ok()) {
      const payload = (await logsResp.json()) as { logs?: Array<Record<string, unknown>> };
      return Array.isArray(payload.logs) ? payload.logs : [];
    }
    await sleep(1000);
  }
  return [];
}

function isThumbsupFeedbackForEvent(row: Record<string, unknown>, eventId: string): boolean {
  const kind = String(row?.kind || row?.type || '').trim().toLowerCase();
  const signal = String(row?.signal || '').trim().toLowerCase();
  const id = String(row?.event_id || '').trim();
  return kind === 'feedback' && signal === 'thumbsup' && id === eventId;
}

function hasLinkedChatEvent(row: Record<string, unknown>, eventId: string): boolean {
  const kind = String(row?.kind || row?.type || '').trim().toLowerCase();
  const id = String(row?.event_id || '').trim();
  return kind === 'chat' && id === eventId;
}

async function countThumbsupForEvent(request: APIRequestContext, eventId: string): Promise<number> {
  const logs = await getRerankerLogs(request, 1000);
  return logs.filter((row) => isThumbsupFeedbackForEvent(row, eventId)).length;
}

async function waitForNewFeedbackLink(
  request: APIRequestContext,
  eventId: string,
  beforeCount: number,
  timeoutMs: number = 30_000
): Promise<{ feedbackFound: boolean; chatLinked: boolean }> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const logs = await getRerankerLogs(request, 1000);
    const feedbackCount = logs.filter((row) => isThumbsupFeedbackForEvent(row, eventId)).length;
    if (feedbackCount > beforeCount) {
      const chatLinked = logs.some((row) => hasLinkedChatEvent(row, eventId));
      return { feedbackFound: true, chatLinked };
    }
    await sleep(1000);
  }

  const finalLogs = await getRerankerLogs(request, 1000);
  return {
    feedbackFound: finalLogs.some((row) => isThumbsupFeedbackForEvent(row, eventId)),
    chatLinked: finalLogs.some((row) => hasLinkedChatEvent(row, eventId)),
  };
}

async function getOrCreateLinkedRunId(request: APIRequestContext): Promise<string> {
  // Always create the event this test will own. Reusing the most recent event
  // couples this assertion to earlier feedback clicks and can make a legitimate
  // one-feedback-per-event policy look like persistence loss.
  const conversationId = `playwright-feedback-seed-${Date.now()}`;
  const chatResp = await request.post(`${API_BASE}/chat`, {
    timeout: 180_000,
    data: {
      message: corpusQuestion(2),
      model_override: `litellm:${EXHAUSTIVE_CHAT_MODEL}`,
      sources: { corpus_ids: [CORPUS_ID, 'recall_default'] },
      conversation_id: conversationId,
      stream: false,
    },
  });
  expect(chatResp.ok()).toBeTruthy();
  const chatPayload = (await chatResp.json()) as { run_id?: string };
  const runId = String(chatPayload.run_id || '').trim();
  expect(runId).toBeTruthy();
  return runId;
}

async function gotoChat(page: Page): Promise<void> {
  await page.goto(`chat?corpus=${encodeURIComponent(CORPUS_ID)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
  await page.evaluate((cid) => {
    localStorage.setItem('tribrid_active_corpus', cid);
    localStorage.setItem('tribrid_active_repo', cid);
  }, CORPUS_ID);
}

async function sendMessage(page: Page, text: string): Promise<void> {
  const input = page.locator('#chat-input');
  await expect(input).toBeVisible();
  await input.fill(text);
  await page.locator('#chat-send').click();
}

async function setSources(page: Page, corpusLabels: string[], recallEnabled: boolean): Promise<void> {
  const dropdown = page.getByTestId('source-dropdown');
  const summary = dropdown.locator('summary');
  await summary.click();

  let corpusBox: Locator | null = null;
  const deadline = Date.now() + 20_000;
  while (!corpusBox && Date.now() < deadline) {
    for (const label of corpusLabels) {
      const row = dropdown.locator('label').filter({ hasText: label }).first();
      if ((await row.count()) === 0) continue;
      corpusBox = row.locator('input[type="checkbox"]').first();
      break;
    }
    if (!corpusBox) {
      await page.waitForTimeout(500);
    }
  }
  expect(Boolean(corpusBox)).toBeTruthy();
  if (corpusBox && !(await corpusBox.isChecked())) {
    await corpusBox.check();
  }

  const recall = page.getByTestId('source-recall');
  if (recallEnabled) {
    await recall.check();
  } else {
    await recall.uncheck();
  }

  await summary.click();
}

async function waitForStreamingTerminal(page: Page): Promise<void> {
  const streamingBadge = page.getByText('Streaming').last();
  await expect(streamingBadge).toBeVisible({ timeout: 20_000 });
  await expect(streamingBadge).toBeHidden({ timeout: 120_000 });
}

async function seedFeedbackSession(page: Page, eventId: string): Promise<void> {
  const conversationId = `playwright-feedback-${Date.now()}`;
  await page.addInitScript(
    ({ corpusId, convId, linkedRunId }) => {
      const now = Date.now();
      const session = {
        conversation_id: convId,
        created_at: now,
        updated_at: now,
        title: 'Feedback seed',
        model_override: '',
        sources: { corpus_ids: [corpusId, 'recall_default'] },
        messages: [
          {
            id: `assistant-${now}`,
            role: 'assistant',
            createdAt: new Date(now).toISOString(),
            content: [{ type: 'text', text: 'Seeded assistant response for feedback linkage.' }],
            status: { type: 'complete', reason: 'stop' },
            metadata: {
              unstable_state: null,
              unstable_annotations: [],
              unstable_data: [],
              steps: [],
              custom: {
                runId: linkedRunId,
                eventId: linkedRunId,
              },
            },
          },
        ],
      };
      localStorage.setItem(
        'ragweld-chat-threads:v2',
        JSON.stringify({ version: 2, active_conversation_id: convId, sessions: [session] })
      );
      localStorage.setItem('tribrid_active_corpus', corpusId);
      localStorage.setItem('tribrid_active_repo', corpusId);
    },
    { corpusId: CORPUS_ID, convId: conversationId, linkedRunId: eventId }
  );
}

async function clickHelpfulFeedback(page: Page): Promise<void> {
  const helpful = page.getByRole('button', { name: 'Helpful' }).first();
  await expect(helpful).toBeVisible({ timeout: 30_000 });
  await helpful.click();
}

async function mineAndAssertReranker(request: APIRequestContext): Promise<void> {
  const mineResp = await request.post(`${API_BASE}/reranker/mine?corpus_id=${encodeURIComponent(CORPUS_ID)}`);
  expect(mineResp.ok()).toBeTruthy();
  const minePayload = (await mineResp.json()) as {
    ok?: boolean;
    triplets_mined?: number;
    mined_from_feedback_events?: number;
  };
  expect(Boolean(minePayload.ok)).toBeTruthy();
  // The thumbs-up above was on a real, retrieval-backed answer for this corpus:
  // mining must turn it into at least one triplet, or "mineable" means nothing.
  expect(Number(minePayload.triplets_mined || 0), JSON.stringify(minePayload)).toBeGreaterThanOrEqual(1);

  const countResp = await request.get(`${API_BASE}/reranker/triplets/count?corpus_id=${encodeURIComponent(CORPUS_ID)}`);
  expect(countResp.ok()).toBeTruthy();
  const countPayload = (await countResp.json()) as { count?: number };
  expect(Number(countPayload.count || 0)).toBeGreaterThanOrEqual(1);
}

test.describe.serial('chat reliability', () => {
  test('streaming reaches terminal state and clears spinner', async ({ page, request }) => {
    const corpusLabels = await ensureCorpusExists(request);
    const uiCfgResp = await request.patch(`${API_BASE}/config/ui?corpus_id=${encodeURIComponent(CORPUS_ID)}`, {
      data: { chat_streaming_enabled: true },
    });
    expect(uiCfgResp.ok()).toBeTruthy();

    await gotoChat(page);
    await setSources(page, corpusLabels, true);

    await sendMessage(page, corpusQuestion(0));
    await waitForStreamingTerminal(page);

    await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 20_000 });
    await expect(page.getByText('Streaming')).toBeHidden();

    // These controls sit at the bottom of a real assistant response. A short
    // window used to collapse the message viewport until the status bar occupied
    // their click coordinates. Exercise the actual buttons without force-clicks.
    await clickHelpfulFeedback(page);
    const citation = page.getByTestId('chat-citation-open').first();
    await expect(citation).toBeVisible({ timeout: 30_000 });
    await citation.click();
  });

  test('new chat resets in-flight state and clears active stream UI', async ({ page, request }) => {
    const corpusLabels = await ensureCorpusExists(request);
    const uiCfgResp = await request.patch(`${API_BASE}/config/ui?corpus_id=${encodeURIComponent(CORPUS_ID)}`, {
      data: { chat_streaming_enabled: true },
    });
    expect(uiCfgResp.ok()).toBeTruthy();

    await gotoChat(page);
    await setSources(page, corpusLabels, false);

    await sendMessage(page, corpusQuestion(1));
    await page.getByTestId('chat-new-chat').click();

    await expect(page.getByText('Streaming')).toBeHidden({ timeout: 20_000 });
    await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 20_000 });
    await expect(page.getByTestId('chat-welcome-prompt-0')).toBeVisible({ timeout: 20_000 });
  });

  test('welcome prompt sends through a pinned runnable model', async ({ page, request }) => {
    const corpusLabels = await ensureCorpusExists(request);
    await gotoChat(page);
    await setSources(page, corpusLabels, false);
    await page.getByTestId('model-picker').selectOption(`litellm:${EXHAUSTIVE_CHAT_MODEL}`);

    await page.getByTestId('chat-welcome-prompt-0').click();
    await waitForStreamingTerminal(page);

    const latest = page.locator('[data-role="assistant"]').last();
    await expect(latest).toBeVisible();
    await expect(latest.getByTestId('chat-structured-error-card')).toHaveCount(0);
  });

  test('feedback is persisted and mineable via matching event_id', async ({ page, request }) => {
    await ensureCorpusExists(request);
    const runId = await getOrCreateLinkedRunId(request);
    expect(runId).toBeTruthy();
    const feedbackCountBefore = await countThumbsupForEvent(request, runId);

    await seedFeedbackSession(page, runId);
    await gotoChat(page);
    await clickHelpfulFeedback(page);

    const linked = await waitForNewFeedbackLink(request, runId, feedbackCountBefore);
    expect(linked.feedbackFound).toBeTruthy();
    expect(linked.chatLinked).toBeTruthy();

    await mineAndAssertReranker(request);
  });
});

test.describe('a failed generation is published like an answer', () => {
  test('the error card says why, and the Routing Trace panel follows the failed run', async ({ page, request }) => {
    // `ragweld-local` is a real, free, deterministic generation failure through the gateway on a
    // box with no vLLM behind it (a connection error). The drive found two defects on it: the
    // card hid the gateway's reason behind a one-size hint about keys and aliases (S9), and the
    // Routing Trace panel kept showing the previous successful run because the transport threw
    // on the stream's `error` event before reading the `done` event that carries the run id (S10).
    const corpusLabels = await ensureCorpusExists(request);
    const uiCfgResp = await request.patch(`${API_BASE}/config/ui?corpus_id=${encodeURIComponent(CORPUS_ID)}`, {
      data: { chat_streaming_enabled: true, chat_show_trace: true },
    });
    expect(uiCfgResp.ok()).toBeTruthy();

    await gotoChat(page);
    await setSources(page, corpusLabels, false);
    await page.getByTestId('model-picker').selectOption('litellm:ragweld-local');

    const tracePanel = page.locator('#chat-trace');
    await expect(tracePanel).toBeVisible();
    if (!(await tracePanel.evaluate((el) => (el as HTMLDetailsElement).open))) {
      await tracePanel.locator('summary').click();
    }
    const traceOutput = page.locator('#chat-trace-output');
    const previousRunId = ((await traceOutput.innerText()).match(/run_id: (\S+)/) || [])[1] || '';

    await sendMessage(page, corpusQuestion(3));

    const latest = page.locator('[data-role="assistant"]').last();
    const card = latest.getByTestId('chat-structured-error-card');
    await expect(card).toBeVisible({ timeout: 120_000 });
    await expect(card).toContainText('generation_unavailable');
    // The hint is chosen from the gateway's reason, not the same sentence for every failure.
    await expect(card.getByTestId('chat-structured-error-action')).toContainText('serving lane is not running');
    await card.locator('summary', { hasText: 'Details' }).click();
    await expect(card).toContainText('failure class');
    await expect(card).toContainText('upstream_unreachable');
    await expect(card).toContainText('reason');
    await expect(card).toContainText('Connection error');
    await expect(card).not.toContainText('http://');
    await expect(card).not.toContainText('https://');

    const runIdCell = card.locator('dt', { hasText: /^run id$/ }).locator('xpath=following-sibling::dd[1]');
    await expect(runIdCell).toBeVisible();
    const failedRunId = (await runIdCell.innerText()).trim();
    expect(failedRunId, 'a failed send must carry the run the server recorded').toMatch(/^[0-9a-f-]{36}$/);
    expect(failedRunId).not.toBe(previousRunId);

    // The panel follows the failed run, not the previous successful one.
    await expect(traceOutput).toContainText(`run_id: ${failedRunId}`, { timeout: 30_000 });
    if (previousRunId) await expect(traceOutput).not.toContainText(`run_id: ${previousRunId}`);
    await expect(traceOutput).toContainText('chat.request');
  });
});

// ---------------------------------------------------------------------------------------------
// Streaming against a scripted gateway (chat_stream_fixture.py): render cost per token, scroll
// landing, an answer that outlives the Chat tab, and feedback only where it can mean something.
//
// No paid model is called. The spec's own pytest_-prefixed corpus (set EXHAUSTIVE_CORPUS_PREFIX)
// points `chat.litellm.base_url` at the fixture, which streams a pinned ~4,000-token answer (two
// fenced code blocks, a table, lists) at a pinned rate; token = one fixture delta. The API under
// test must resolve the gateway from corpus config, i.e. run without LITELLM_BASE_URL in its
// environment; every test proves its request reached the fixture, so a stack wired to the real
// gateway fails loudly instead of passing on someone else's answer.
//
// Ratchet: commits per 1,000 streamed tokens, measured on the Vite dev build (StrictMode) at
// deviceScaleFactor 1 on LXC100 (4,064 tokens at 200 tokens/s). The frame-coalesced renderer
// measured 180-246 across runs: at most one commit per frame, so the count tracks the frame rate
// the box sustains (35-48 fps there). The ceiling is the frame bound (60 fps over the ~21 s
// stream is ~310, plus the handful of start/stage/end commits); a renderer that commits per
// delta and keeps up would be ~1,000. The old renderer measured only 166 because it could not keep up:
// 17.8 s of its 20.8 s stream went to React commits (145 long tasks, 19 fps), so the browser
// batched deltas for it. That regression is caught by the same test's finished-fence check and
// by the attribution test below (583 commits re-rendering every other message before, 2 after).
const STREAM_COMMITS_PER_1K_TOKENS_CEILING = 330;
const STREAM_QUESTION = ACCEPTANCE_CORPUS_PROBES[0].question;
const PRIOR_TURNS = ACCEPTANCE_CORPUS_PROBES.slice(1, 4).map((probe, index) => ({
  question: probe.question,
  answer: [
    `### Earlier answer ${index + 1}`,
    '',
    'The observatory runbook covers this in its maintenance section; the relevant figures are:',
    '',
    '| Item | Value |',
    '|---|---|',
    `| Check cycle | ${30 * (index + 1)} days |`,
    `| Reference | lab standard ${index + 1} |`,
    '',
    '```bash',
    `kestrelctl report --section maintenance --item ${index + 1}`,
    '```',
    '',
    'Each figure is quoted from the cited runbook page.',
  ].join('\n'),
}));

type ThreadSeed = { conversationId: string; title: string; prior: typeof PRIOR_TURNS };

/** Seed conversations (the first is active) scoped to `corpusId` alone, once per page. */
async function seedStreamThreads(page: Page, corpusId: string, threads: ThreadSeed[]): Promise<void> {
  const seedId = `stream-seed-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  await page.addInitScript(
    ({ cid, threads, seedId }) => {
      const appliedKey = `ragweld-exhaustive-seed-applied:${seedId}`;
      if (sessionStorage.getItem(appliedKey)) return;
      sessionStorage.setItem(appliedKey, '1');
      const base = Date.now() - 60_000;
      const sessions = threads.map((thread, threadIndex) => {
        const messages: unknown[] = [];
        thread.prior.forEach((turn, index) => {
          const at = base + threadIndex * 10_000 + index * 1000;
          messages.push({
            id: `user-${thread.conversationId}-${index}`,
            role: 'user',
            createdAt: new Date(at).toISOString(),
            content: [{ type: 'text', text: turn.question }],
            attachments: [],
            metadata: { custom: {} },
          });
          messages.push({
            id: `assistant-${thread.conversationId}-${index}`,
            role: 'assistant',
            createdAt: new Date(at + 500).toISOString(),
            content: [{ type: 'text', text: turn.answer }],
            status: { type: 'complete', reason: 'stop' },
            metadata: {
              unstable_state: null,
              unstable_annotations: [],
              unstable_data: [],
              steps: [],
              custom: { runId: `seed-${thread.conversationId}-${index}` },
            },
          });
        });
        return {
          conversation_id: thread.conversationId,
          created_at: base + threadIndex,
          updated_at: base + threadIndex * 10_000 + 9_000,
          title: thread.title,
          model_override: '',
          sources: { corpus_ids: [cid] },
          messages,
        };
      });
      localStorage.setItem(
        'ragweld-chat-threads:v2',
        JSON.stringify({ version: 2, active_conversation_id: threads[0].conversationId, sessions }),
      );
      localStorage.setItem('tribrid_active_corpus', cid);
      localStorage.setItem('tribrid_active_repo', cid);
    },
    { cid: corpusId, threads, seedId },
  );
}

async function gotoStreamChat(page: Page, corpusId: string): Promise<void> {
  await page.goto(`chat?corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('.main-content #chat-input', { timeout: 90_000 });
  await expect(page.locator('.main-content #chat-input')).toBeEnabled({ timeout: 30_000 });
}

function lastAssistant(page: Page): Locator {
  return page.locator('.main-content [data-role="assistant"]').last();
}

async function sendStreamQuestion(page: Page, question: string): Promise<void> {
  const input = page.locator('.main-content #chat-input');
  await input.fill(question);
  await page.locator('.main-content #chat-send').click();
}

async function waitForAnswerEnd(page: Page, sentinel: string, timeout = 180_000): Promise<void> {
  const answer = lastAssistant(page);
  await expect(answer).toContainText(sentinel, { timeout });
  await expect(answer.getByTestId('chat-streaming-elapsed')).toHaveCount(0, { timeout: 30_000 });
}

/** Geometry of the main pane's message list and its newest assistant message. */
async function scrollState(page: Page): Promise<{
  scrollTop: number;
  scrollHeight: number;
  clientHeight: number;
  atBottom: boolean;
  lastAssistantTop: number;
  viewportTop: number;
  viewportCenter: { x: number; y: number };
}> {
  return page.evaluate(() => {
    const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
    const answer = answers[answers.length - 1] as HTMLElement;
    let viewport = answer.parentElement;
    while (viewport && !/(auto|scroll)/.test(getComputedStyle(viewport).overflowY)) viewport = viewport.parentElement;
    const el = viewport as HTMLElement;
    return {
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      atBottom: el.scrollHeight - el.scrollTop - el.clientHeight < 4,
      lastAssistantTop: Math.round(answer.getBoundingClientRect().top),
      viewportTop: Math.round(el.getBoundingClientRect().top),
      viewportCenter: {
        x: Math.round(el.getBoundingClientRect().left + el.clientWidth / 2),
        y: Math.round(el.getBoundingClientRect().top + el.clientHeight / 2),
      },
    };
  });
}

async function storedAssistantTexts(page: Page, conversationId: string): Promise<string[]> {
  return page.evaluate((cid) => {
    const state = JSON.parse(localStorage.getItem('ragweld-chat-threads:v2') || 'null') as {
      sessions: { conversation_id: string; messages: { role: string; content: { type: string; text?: string }[] }[] }[];
    } | null;
    const session = state?.sessions.find((s) => s.conversation_id === cid);
    return (session?.messages || [])
      .filter((m) => m.role === 'assistant')
      .map((m) => m.content.filter((p) => p.type === 'text').map((p) => p.text || '').join(''));
  }, conversationId);
}

test.describe('chat streaming (scripted gateway)', () => {
  test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

  let streamCorpus: ExhaustiveCorpus | null = null;
  let fixture: StreamFixture | null = null;

  // Every send must reach the scripted gateway. An API with LITELLM_BASE_URL in its environment
  // ignores the corpus's chat.litellm.base_url and would stream a paid model instead: fail fast.
  async function sendViaFixture(page: Page, question: string): Promise<void> {
    const before = (await fixture!.state()).received;
    await sendStreamQuestion(page, question);
    await expect
      .poll(async () => (await fixture!.state()).received, {
        timeout: 20_000,
        message: 'the send never reached the scripted gateway: run the API under test without LITELLM_BASE_URL',
      })
      .toBeGreaterThan(before);
  }

  test.beforeAll(async ({ request }) => {
    test.setTimeout(600_000);
    fixture = await startStreamFixture([EXHAUSTIVE_CHAT_MODEL]);
    streamCorpus = await provisionExhaustiveCorpus(request, { index: true });
    await patchCorpusConfigSection(request, streamCorpus.corpusId, 'chat', {
      litellm: { base_url: fixture.baseUrl, default_model: EXHAUSTIVE_CHAT_MODEL },
    });
    await patchCorpusConfigSection(request, streamCorpus.corpusId, 'ui', {
      chat_streaming_enabled: true,
      chat_show_debug_footer: true,
      chat_show_citations: true,
    });
    const models = await request.get(`${API_BASE}/chat/models?corpus_id=${encodeURIComponent(streamCorpus.corpusId)}`);
    expect(models.ok(), await models.text()).toBeTruthy();
    expect(await models.text()).toContain(EXHAUSTIVE_CHAT_MODEL);
  });

  test.afterAll(async ({ request }) => {
    if (streamCorpus) await streamCorpus.dispose(request);
    if (fixture) await fixture.stop();
  });

  type LongStreamReading = {
    metrics: StreamProbeMetrics;
    tokens: number;
    answerText: string;
    stored: string[];
    streamRequests: number;
    fence: { connected: boolean; same: boolean; mutations: number };
  };

  /** Stream the long answer once with the probe on. Returns readings; the caller asserts after logging. */
  async function streamLongAnswer(page: Page, attribute: boolean): Promise<LongStreamReading> {
    const corpusId = streamCorpus!.corpusId;
    await fixture!.control('scenario', { scenario: 'long' });
    const answer = await fixture!.answer();
    const conversationId = `pytest-stream-perf-${Date.now()}`;
    await installStreamProbe(page, { attribute });
    await seedStreamThreads(page, corpusId, [{ conversationId, title: 'Stream perf', prior: PRIOR_TURNS }]);
    await gotoStreamChat(page, corpusId);
    const before = await fixture!.state();

    const streamingIndex = PRIOR_TURNS.length * 2 + 1;
    await startStreamProbe(page, streamingIndex);
    await sendViaFixture(page, STREAM_QUESTION);

    // Once the second fence has started, the first is finished: hold on to its DOM and watch it.
    await expect(lastAssistant(page)).toContainText('type CalibrationWindow', { timeout: 120_000 });
    const captured = await page.evaluate(() => {
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      const code = answers[answers.length - 1].querySelector('code.language-python');
      if (!code) return false;
      const holder = window as unknown as { __firstFence: Element; __firstFenceMutations: number };
      holder.__firstFence = code;
      holder.__firstFenceMutations = 0;
      new MutationObserver((records) => {
        holder.__firstFenceMutations += records.length;
      }).observe(code.parentElement as Element, { subtree: true, childList: true, characterData: true, attributes: true });
      return true;
    });
    expect(captured, 'the finished python block was not rendered as highlighted code').toBe(true);

    await waitForAnswerEnd(page, 'End of calibration report.');
    const metrics = await stopStreamProbe(page);

    const fence = await page.evaluate(() => {
      const holder = window as unknown as { __firstFence: Element; __firstFenceMutations: number };
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      return {
        connected: holder.__firstFence.isConnected,
        same: answers[answers.length - 1].querySelector('code.language-python') === holder.__firstFence,
        mutations: holder.__firstFenceMutations,
      };
    });
    const after = await fixture!.state();
    return {
      metrics,
      tokens: answer.tokens,
      answerText: answer.text,
      stored: await storedAssistantTexts(page, conversationId),
      streamRequests: after.stream_requests - before.stream_requests,
      fence,
    };
  }

  function expectLongStreamLanded(reading: LongStreamReading): void {
    expect(reading.streamRequests, 'the answer must come from the scripted gateway, once').toBe(1);
    const landed = reading.stored.filter((text) => text.includes('End of calibration report.'));
    expect(landed, 'the answer is persisted once').toHaveLength(1);
    expect(landed[0].trim()).toBe(reading.answerText.trim());
    expect(reading.fence, 'a finished code block must not be re-rendered while the answer streams on').toEqual({
      connected: true,
      same: true,
      mutations: 0,
    });
  }

  test('a long answer streams with commits bounded per token (timing pass, ratchet)', async ({ page }) => {
    test.setTimeout(300_000);
    const result = await streamLongAnswer(page, false);
    const { metrics, tokens } = result;
    const commitsPer1k = Math.round((metrics.commits / tokens) * 1000 * 10) / 10;
    const reading = { pass: 'timing', tokens, commitsPer1k, fence: result.fence, ...metrics };
    console.log(`CHAT_STREAM_METRICS ${JSON.stringify(reading)}`);
    test.info().annotations.push({ type: 'chat-stream-metrics', description: JSON.stringify(reading) });
    expectLongStreamLanded(result);
    expect(commitsPer1k, JSON.stringify(reading)).toBeLessThanOrEqual(STREAM_COMMITS_PER_1K_TOKENS_CEILING);
  });

  test('while an answer streams, the other messages in the thread do not re-render', async ({ page }) => {
    test.setTimeout(300_000);
    const result = await streamLongAnswer(page, true);
    const { metrics, tokens } = result;
    const reading = { pass: 'attribution', tokens, fence: result.fence, ...metrics };
    console.log(`CHAT_STREAM_METRICS ${JSON.stringify(reading)}`);
    test.info().annotations.push({ type: 'chat-stream-attribution', description: JSON.stringify(reading) });
    expectLongStreamLanded(result);
    // The streaming message renders per frame; the others only on the send and the landing
    // commits (the new user turn mounting, the thread reloading its persisted answer).
    expect(metrics.streamingMessageRenders, JSON.stringify(reading)).toBeGreaterThan(20);
    expect(metrics.otherMessageRenders, JSON.stringify(reading)).toBeLessThanOrEqual(6);
  });

  test('the stream is followed from the bottom, and a reader who scrolls up keeps their place', async ({
    page,
  }) => {
    test.setTimeout(300_000);
    const corpusId = streamCorpus!.corpusId;
    await fixture!.control('scenario', { scenario: 'long', tokens_per_second: 300 });
    await seedStreamThreads(page, corpusId, [
      { conversationId: `pytest-stream-scroll-${Date.now()}`, title: 'Stream scroll', prior: PRIOR_TURNS },
    ]);
    await gotoStreamChat(page, corpusId);
    const before = await fixture!.state();

    await sendViaFixture(page, STREAM_QUESTION);
    // The new question and the incoming answer are on screen right after the send.
    const question = page.locator('.main-content [data-role="user"]').last();
    await expect(question).toContainText(STREAM_QUESTION);
    await expect(question).toBeInViewport();
    await expect(lastAssistant(page)).toBeInViewport();

    // At the bottom, the stream is followed.
    await expect(lastAssistant(page)).toContainText('The drift estimate below', { timeout: 60_000 });
    await expect.poll(async () => (await scrollState(page)).scrollHeight > (await scrollState(page)).clientHeight * 2, {
      timeout: 60_000,
    }).toBe(true);
    await expect.poll(async () => (await scrollState(page)).atBottom, { timeout: 5_000 }).toBe(true);

    // Scrolled up, it is not: the reader keeps their place while the answer grows below.
    const { viewportCenter } = await scrollState(page);
    await page.mouse.move(viewportCenter.x, viewportCenter.y);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(400);
    const heldAt = (await scrollState(page)).scrollTop;
    await page.waitForTimeout(1500);
    const held = await scrollState(page);
    expect(Math.abs(held.scrollTop - heldAt), JSON.stringify(held)).toBeLessThanOrEqual(2);
    expect(held.atBottom).toBe(false);

    // Back at the bottom, following resumes.
    await page.evaluate(() => {
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      let viewport = answers[answers.length - 1].parentElement;
      while (viewport && !/(auto|scroll)/.test(getComputedStyle(viewport).overflowY)) viewport = viewport.parentElement;
      const el = viewport as HTMLElement;
      el.scrollTop = el.scrollHeight;
    });
    await page.waitForTimeout(800);
    expect((await scrollState(page)).atBottom, 'following did not resume at the bottom').toBe(true);

    await waitForAnswerEnd(page, 'End of calibration report.');
    const after = await fixture!.state();
    expect(after.stream_requests - before.stream_requests).toBe(1);
    await fixture!.control('scenario', { scenario: 'long' });
  });

  test('a finished answer lands where the reader is, and Jump to latest opens it at its start', async ({ page }) => {
    test.setTimeout(300_000);
    const corpusId = streamCorpus!.corpusId;
    // A paced answer that still overflows the pane: the reader can follow it, and when it ends its
    // sources, feedback and debug footer arrive below them.
    await fixture!.control('scenario', { scenario: 'medium' });
    await seedStreamThreads(page, corpusId, [
      { conversationId: `pytest-stream-landing-${Date.now()}`, title: 'Stream landing', prior: PRIOR_TURNS },
    ]);
    await gotoStreamChat(page, corpusId);
    const before = await fixture!.state();
    await sendViaFixture(page, STREAM_QUESTION);
    await expect(lastAssistant(page)).toContainText('Short calibration summary', { timeout: 60_000 });

    // The reader stays at the bottom while it streams; record where they are until it ends.
    await page.evaluate(() => {
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      let viewport = answers[answers.length - 1].parentElement;
      while (viewport && !/(auto|scroll)/.test(getComputedStyle(viewport).overflowY)) viewport = viewport.parentElement;
      const el = viewport as HTMLElement;
      el.scrollTop = el.scrollHeight;
      const holder = window as unknown as { __lastStreamingScrollTop: number };
      holder.__lastStreamingScrollTop = el.scrollTop;
      const sample = () => {
        const running = document.querySelector('.main-content [data-testid="chat-streaming-elapsed"]');
        if (!running) return;
        holder.__lastStreamingScrollTop = el.scrollTop;
        requestAnimationFrame(sample);
      };
      requestAnimationFrame(sample);
    });

    await waitForAnswerEnd(page, 'End of calibration summary.');
    await expect(lastAssistant(page).getByTestId('chat-sources')).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(800);
    const landed = await page.evaluate(() => {
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      let viewport = answers[answers.length - 1].parentElement;
      while (viewport && !/(auto|scroll)/.test(getComputedStyle(viewport).overflowY)) viewport = viewport.parentElement;
      const el = viewport as HTMLElement;
      return {
        final: el.scrollTop,
        lastStreaming: (window as unknown as { __lastStreamingScrollTop: number }).__lastStreamingScrollTop,
        max: el.scrollHeight - el.clientHeight,
      };
    });
    // The finished answer's sources, feedback and debug footer arrive below the reader; the
    // view stays where the reader was instead of jumping to the bottom of the footer.
    expect(landed.final, JSON.stringify(landed)).toBeLessThanOrEqual(landed.lastStreaming + 2);
    expect(landed.max, JSON.stringify(landed)).toBeGreaterThan(landed.lastStreaming + 40);

    // Jump to latest opens the newest answer at its start, not at the bottom of the thread.
    await page.evaluate(() => {
      const answers = [...document.querySelectorAll('.main-content [data-role="assistant"]')];
      let viewport = answers[answers.length - 1].parentElement;
      while (viewport && !/(auto|scroll)/.test(getComputedStyle(viewport).overflowY)) viewport = viewport.parentElement;
      (viewport as HTMLElement).scrollTop = 0;
    });
    await page.locator('.main-content').getByRole('button', { name: 'Jump to latest' }).click();
    await expect.poll(async () => {
      const state = await scrollState(page);
      const offset = state.lastAssistantTop - state.viewportTop;
      return offset >= -2 && offset <= 48;
    }, { timeout: 5_000 }).toBe(true);
    const jumped = await scrollState(page);
    expect(jumped.lastAssistantTop - jumped.viewportTop, JSON.stringify(jumped)).toBeLessThanOrEqual(48);

    const after = await fixture!.state();
    expect(after.stream_requests - before.stream_requests).toBe(1);
    await fixture!.control('scenario', { scenario: 'long' });
  });

  test('an answer keeps streaming while the operator is on another tab, and lands once', async ({ page }) => {
    test.setTimeout(240_000);
    const corpusId = streamCorpus!.corpusId;
    await fixture!.control('scenario', { scenario: 'medium' });
    const answer = await fixture!.answer();
    const conversationId = `pytest-stream-away-${Date.now()}`;
    await seedStreamThreads(page, corpusId, [{ conversationId, title: 'Stream away', prior: [] }]);
    await gotoStreamChat(page, corpusId);
    const before = await fixture!.state();

    await sendViaFixture(page, STREAM_QUESTION);
    await expect(lastAssistant(page)).toContainText('Short calibration summary', { timeout: 60_000 });

    const nav = page.getByTestId('tab-bar');
    await nav.getByRole('link', { name: 'Dashboard', exact: true }).click();
    await expect(page).toHaveURL(/\/dashboard/);
    await page.waitForTimeout(2500);
    await expect(page.locator('.toast-error'), 'leaving the Chat tab must not fail the answer').toHaveCount(0);
    await nav.getByRole('link', { name: 'Chat', exact: true }).click();
    await page.waitForSelector('.main-content #chat-input', { timeout: 60_000 });

    // Back on the tab: the same answer, still streaming or already finished, never interrupted.
    await expect(lastAssistant(page)).toContainText('Short calibration summary');
    await expect(lastAssistant(page).getByTestId('chat-assistant-error')).toHaveCount(0);
    await waitForAnswerEnd(page, 'End of calibration summary.');
    await expect(lastAssistant(page).getByTestId('chat-assistant-error')).toHaveCount(0);
    await expect(page.locator('.toast-error')).toHaveCount(0);

    const stored = await storedAssistantTexts(page, conversationId);
    expect(stored.map((text) => text.trim()), 'the answer is persisted exactly once').toEqual([answer.text.trim()]);
    const after = await fixture!.state();
    expect(after.stream_requests - before.stream_requests, 'coming back must not start a second stream').toBe(1);
  });

  test('Helpful / Not helpful appear only on a finished answer, never on a failed or stopped one', async ({ page }) => {
    test.setTimeout(240_000);
    const corpusId = streamCorpus!.corpusId;
    await seedStreamThreads(page, corpusId, [
      { conversationId: `pytest-stream-feedback-${Date.now()}`, title: 'Stream feedback', prior: [] },
    ]);
    await gotoStreamChat(page, corpusId);

    // A finished answer can be rated.
    await fixture!.control('scenario', { scenario: 'short' });
    await sendViaFixture(page, ACCEPTANCE_CORPUS_PROBES[1].question);
    await waitForAnswerEnd(page, 'PS-105 is due first.');
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsup')).toBeVisible();

    // A streaming answer cannot yet, and a stopped one never can.
    await fixture!.control('scenario', { scenario: 'medium' });
    await sendViaFixture(page, ACCEPTANCE_CORPUS_PROBES[2].question);
    await expect(lastAssistant(page)).toContainText('Short calibration summary', { timeout: 60_000 });
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsup')).toHaveCount(0);
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsdown')).toHaveCount(0);
    await page.locator('.main-content').getByRole('button', { name: 'Stop generation' }).click();
    await expect(lastAssistant(page).getByTestId('chat-assistant-error')).toBeVisible({ timeout: 30_000 });
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsup')).toHaveCount(0);
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsdown')).toHaveCount(0);

    // A failed generation never can.
    await fixture!.control('scenario', { scenario: 'fail' });
    const before = await fixture!.state();
    await sendViaFixture(page, ACCEPTANCE_CORPUS_PROBES[3].question);
    const failed = lastAssistant(page);
    await expect(
      failed.locator('[data-testid="chat-structured-error-card"], [data-testid="chat-assistant-error"]'),
    ).toBeVisible({ timeout: 120_000 });
    expect((await fixture!.state()).received).toBeGreaterThan(before.received);
    await expect(failed.getByTestId('chat-feedback-thumbsup')).toHaveCount(0);
    await expect(failed.getByTestId('chat-feedback-thumbsdown')).toHaveCount(0);
    await fixture!.control('scenario', { scenario: 'long' });
  });

  test('Helpful carries the chunks the answer cited, and opening a citation sends a click on that chunk', async ({ page }) => {
    test.setTimeout(240_000);
    const corpusId = streamCorpus!.corpusId;
    const conversationId = `pytest-stream-signals-${Date.now()}`;
    await seedStreamThreads(page, corpusId, [{ conversationId, title: 'Stream signals', prior: [] }]);
    await gotoStreamChat(page, corpusId);
    const feedback: { body: Record<string, unknown>; status: number }[] = [];
    page.on('response', async (response) => {
      const request = response.request();
      if (request.method() !== 'POST' || !new URL(request.url()).pathname.endsWith('/api/feedback')) return;
      feedback.push({ body: request.postDataJSON() as Record<string, unknown>, status: response.status() });
    });

    await fixture!.control('scenario', { scenario: 'short' });
    await sendViaFixture(page, ACCEPTANCE_CORPUS_PROBES[4].question);
    await waitForAnswerEnd(page, 'PS-105 is due first.');
    const answer = await page.evaluate((cid) => {
      const state = JSON.parse(localStorage.getItem('ragweld-chat-threads:v2') || 'null') as {
        sessions: { conversation_id: string; messages: { role: string; metadata?: { custom?: { runId?: string; sources?: { chunk_id: string }[] } } }[] }[];
      };
      const session = state.sessions.find((s) => s.conversation_id === cid)!;
      const last = session.messages.filter((m) => m.role === 'assistant').pop()!;
      return { runId: last.metadata?.custom?.runId ?? '', chunkIds: (last.metadata?.custom?.sources ?? []).map((s) => s.chunk_id) };
    }, conversationId);
    expect(answer.runId, 'the answer carries its run').not.toBe('');
    expect(answer.chunkIds.length, 'retrieval over the acceptance corpus cited nothing').toBeGreaterThan(0);

    // Opening a citation is a silent click signal on that chunk, for this answer's run.
    const citation = lastAssistant(page).locator('[data-testid="chat-citation-open"], [data-testid="chat-citation-open-pdf"]').first();
    await citation.click();
    await expect.poll(() => feedback.length, { timeout: 15_000 }).toBe(1);
    expect(feedback[0].status, JSON.stringify(feedback[0])).toBeLessThan(300);
    expect(feedback[0].body).toMatchObject({
      signal: 'click',
      doc_id: answer.chunkIds[0],
      event_id: answer.runId,
      surface: 'chat',
      chunk_ids: [...new Set(answer.chunkIds)],
    });
    // The click is not a rating: Helpful / Not helpful are still offered.
    await expect(lastAssistant(page).getByTestId('chat-feedback-thumbsup')).toBeVisible();

    await lastAssistant(page).getByTestId('chat-feedback-thumbsup').click();
    await expect.poll(() => feedback.length, { timeout: 15_000 }).toBe(2);
    expect(feedback[1].status, JSON.stringify(feedback[1])).toBeLessThan(300);
    expect(feedback[1].body).toMatchObject({
      signal: 'thumbsup',
      event_id: answer.runId,
      surface: 'chat',
      chunk_ids: [...new Set(answer.chunkIds)],
    });
    await expect(lastAssistant(page)).toContainText('Feedback saved');
    await fixture!.control('scenario', { scenario: 'long' });
  });

  test('the composer stays mounted when the operator switches conversations', async ({ page }) => {
    const corpusId = streamCorpus!.corpusId;
    const first = `pytest-stream-switch-a-${Date.now()}`;
    const second = `pytest-stream-switch-b-${Date.now()}`;
    await seedStreamThreads(page, corpusId, [
      { conversationId: first, title: 'Switch A', prior: PRIOR_TURNS.slice(0, 1) },
      { conversationId: second, title: 'Switch B', prior: PRIOR_TURNS.slice(1, 2) },
    ]);
    await gotoStreamChat(page, corpusId);
    await page.evaluate(() => {
      (window as unknown as { __composer: Element | null }).__composer = document.querySelector('.main-content #chat-input');
    });
    await page.locator('.main-content').getByTestId('chat-history-toggle').click();
    await page.locator(`.main-content button[title="conversation_id: ${second}"]`).click();
    await expect(page.locator('.main-content [data-role="user"]').first()).toContainText(PRIOR_TURNS[1].question);
    const same = await page.evaluate(
      () => (window as unknown as { __composer: Element | null }).__composer === document.querySelector('.main-content #chat-input'),
    );
    expect(same, 'switching conversations remounted the composer').toBe(true);
  });
});
