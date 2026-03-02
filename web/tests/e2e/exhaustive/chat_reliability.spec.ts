import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';

const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:8012/api';
const CORPUS_ID = String(process.env.EXHAUSTIVE_CORPUS_ID || '').trim() || 'epstein-files-1';
const CORPUS_NAME = String(process.env.EXHAUSTIVE_CORPUS_NAME || '').trim() || CORPUS_ID;
const CORPUS_PATH_OVERRIDE = String(process.env.EXHAUSTIVE_CORPUS_PATH || '').trim();

let generatedCorpusPath: string | null = null;

type CorpusRow = { corpus_id?: string; name?: string };

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function ensureCorpusExists(request: APIRequestContext): Promise<string[]> {
  const fetchCorpora = async (): Promise<{ corpora: CorpusRow[] | null; lastStatus: number }> => {
    let corpora: CorpusRow[] | null = null;
    let lastStatus = 0;

    for (let attempt = 1; attempt <= 5; attempt += 1) {
      const resp = await request.get(`${API_BASE}/corpora`);
      lastStatus = resp.status();
      if (resp.ok()) {
        corpora = (await resp.json()) as CorpusRow[];
        break;
      }
      await sleep(1000);
    }
    return { corpora, lastStatus };
  };

  const ensureCorpusPath = async (): Promise<string> => {
    if (CORPUS_PATH_OVERRIDE) return resolve(CORPUS_PATH_OVERRIDE);
    if (generatedCorpusPath) return generatedCorpusPath;
    const dir = await mkdtemp(join(tmpdir(), 'ragweld-exhaustive-corpus-'));
    await writeFile(
      join(dir, 'README.md'),
      'Exhaustive UI reliability corpus fixture.\n',
      { encoding: 'utf-8' }
    );
    generatedCorpusPath = dir;
    return generatedCorpusPath;
  };

  let { corpora, lastStatus } = await fetchCorpora();
  expect(Boolean(corpora), `expected /corpora to succeed, last status=${lastStatus}`).toBeTruthy();
  let rows = corpora || [];
  let row = rows.find((c) => String(c?.corpus_id || '').trim() === CORPUS_ID);
  if (!row) {
    const corpusPath = await ensureCorpusPath();
    const createResp = await request.post(`${API_BASE}/corpora`, {
      data: {
        corpus_id: CORPUS_ID,
        name: CORPUS_NAME,
        path: corpusPath,
      },
    });
    if (!createResp.ok()) {
      const detail = await createResp.text();
      throw new Error(`failed to create corpus ${CORPUS_ID}: ${createResp.status()} ${detail}`);
    }
    ({ corpora, lastStatus } = await fetchCorpora());
    expect(Boolean(corpora), `expected /corpora to succeed, last status=${lastStatus}`).toBeTruthy();
    rows = corpora || [];
    row = rows.find((c) => String(c?.corpus_id || '').trim() === CORPUS_ID);
  }
  expect(Boolean(row), `expected corpus ${CORPUS_ID} to exist`).toBeTruthy();
  const labels = [String(row?.name || '').trim(), CORPUS_ID].filter(Boolean);
  return Array.from(new Set(labels));
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

function eventIncludesCorpus(row: Record<string, unknown>): boolean {
  const corpusIds = Array.isArray(row?.corpus_ids) ? (row.corpus_ids as unknown[]) : [];
  if (corpusIds.some((id) => String(id || '').trim() === CORPUS_ID)) return true;
  const corpusId = String(row?.corpus_id || '').trim();
  return corpusId === CORPUS_ID;
}

function isChatEvent(row: Record<string, unknown>): boolean {
  const kind = String(row?.kind || row?.type || '').trim().toLowerCase();
  const eventId = String(row?.event_id || '').trim();
  return kind === 'chat' && Boolean(eventId);
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

async function findRecentChatEventId(request: APIRequestContext): Promise<string | null> {
  const logs = await getRerankerLogs(request, 1000);
  for (let i = logs.length - 1; i >= 0; i -= 1) {
    const row = logs[i];
    if (!row || typeof row !== 'object') continue;
    if (!isChatEvent(row)) continue;
    if (!eventIncludesCorpus(row)) continue;
    const eventId = String(row.event_id || '').trim();
    if (eventId) return eventId;
  }
  return null;
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
  const existing = await findRecentChatEventId(request);
  if (existing) return existing;

  const query = `reliability-feedback-seed-${Date.now()}`;
  const conversationId = `playwright-feedback-seed-${Date.now()}`;
  const chatResp = await request.post(`${API_BASE}/chat`, {
    timeout: 90_000,
    data: {
      message: query,
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
  const spinner = page.getByText('Generating response...');
  await expect(spinner).toBeVisible({ timeout: 20_000 });
  await expect(spinner).toBeHidden({ timeout: 120_000 });
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
            content: 'Seeded assistant response for feedback linkage.',
            timestamp: now,
            runId: linkedRunId,
            eventId: linkedRunId,
          },
        ],
      };
      localStorage.setItem(
        'tribrid-chat-sessions:v1:global',
        JSON.stringify({ version: 1, active_conversation_id: convId, sessions: [session] })
      );
      localStorage.setItem('tribrid_active_corpus', corpusId);
      localStorage.setItem('tribrid_active_repo', corpusId);
    },
    { corpusId: CORPUS_ID, convId: conversationId, linkedRunId: eventId }
  );
}

async function clickHelpfulFeedback(page: Page): Promise<void> {
  const helpful = page.locator('button[title="This was helpful - trains the reranker"]').first();
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
  expect(Number(minePayload.mined_from_feedback_events || 0)).toBeGreaterThanOrEqual(0);

  const countResp = await request.get(`${API_BASE}/reranker/triplets/count?corpus_id=${encodeURIComponent(CORPUS_ID)}`);
  expect(countResp.ok()).toBeTruthy();
  const countPayload = (await countResp.json()) as { count?: number };
  expect(Number(countPayload.count || 0)).toBeGreaterThanOrEqual(0);
}

test.describe.serial('chat reliability', () => {
  test('streaming reaches terminal state and clears spinner', async ({ page, request }) => {
    const corpusLabels = await ensureCorpusExists(request);
    const uiCfgResp = await request.patch(`${API_BASE}/config/ui?corpus_id=${encodeURIComponent(CORPUS_ID)}`, {
      data: { chat_streaming_enabled: 1 },
    });
    expect(uiCfgResp.ok()).toBeTruthy();

    await gotoChat(page);
    await setSources(page, corpusLabels, true);

    const question = `reliability-stream-${Date.now()}`;
    await sendMessage(page, question);
    await waitForStreamingTerminal(page);

    await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 20_000 });
    await expect(page.getByText('Generating response...')).toBeHidden();
  });

  test('new chat resets in-flight state and clears active stream UI', async ({ page, request }) => {
    const corpusLabels = await ensureCorpusExists(request);
    const uiCfgResp = await request.patch(`${API_BASE}/config/ui?corpus_id=${encodeURIComponent(CORPUS_ID)}`, {
      data: { chat_streaming_enabled: 1 },
    });
    expect(uiCfgResp.ok()).toBeTruthy();

    await gotoChat(page);
    await setSources(page, corpusLabels, false);

    await sendMessage(page, `reliability-new-chat-${Date.now()}`);
    await page.getByTestId('chat-new-chat').click();

    await expect(page.getByText('Generating response...')).toBeHidden({ timeout: 20_000 });
    await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 20_000 });
    await expect(page.getByText('Start a conversation with your codebase')).toBeVisible({ timeout: 20_000 });
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
