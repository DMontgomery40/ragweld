import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { API_BASE, EXHAUSTIVE_CHAT_MODEL, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';
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
    await expect(page.getByText('Chat stays grounded in recall, sources, and session continuity.')).toBeVisible({ timeout: 20_000 });
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
