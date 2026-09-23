// The chat stream controller owns an answer while it streams, independently of any view: a
// turn with no view mounted still lands in the stored thread exactly once; text reaches views at
// most once per frame, and a tab with no frames at all still settles with the full answer; a
// second turn in the same conversation supersedes the first instead of running beside it; Stop
// lands a cancelled message, deleting the conversation lands nothing; a failed stream lands its
// structured error with the run; the journeys the RUM layer reports carry the outcome.
// The server is a real local HTTP server speaking the /api/chat/stream SSE protocol, and the
// transport is the app's own sendRagweldChat.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import test from 'node:test';

import type { ThreadAssistantMessage } from '@assistant-ui/react';
import {
  CHAT_SESSIONS_STORAGE_KEY,
  createAssistantThreadMessage,
  createChatSession,
  createUserThreadMessage,
  getMessageCustom,
  getMessageText,
  INTERRUPTED_STREAM_MESSAGE,
  loadChatSessionsFromStorage,
  persistChatSessions,
  reconcileInterruptedMessages,
} from '../../src/components/Chat/chatSessions.ts';
import {
  createChatStreamController,
  type ChatJourney,
  type ChatStreamControllerDeps,
  type ChatTurnSettled,
} from '../../src/components/Chat/chatStreamController.ts';
import { sendRagweldChat } from '../../src/components/Chat/chatTransport.ts';
import { browserFrameScheduler, type FrameScheduler } from '../../src/components/Chat/frameCoalescer.ts';

const QUESTION = 'How often is the salinity sensor array on each buoy calibrated, and against which reference standard?';
const DELTAS = Array.from({ length: 40 }, (_, index) => `Calibration step ${index + 1} is logged. `);
const ANSWER = DELTAS.join('');

class MemoryStorage implements Storage {
  private readonly entries = new Map<string, string>();
  get length(): number {
    return this.entries.size;
  }
  clear(): void {
    this.entries.clear();
  }
  getItem(key: string): string | null {
    return this.entries.has(key) ? String(this.entries.get(key)) : null;
  }
  key(index: number): string | null {
    return Array.from(this.entries.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.entries.delete(key);
  }
  setItem(key: string, value: string): void {
    this.entries.set(key, String(value));
  }
  [name: string]: unknown;
}

function sse(event: Record<string, unknown>): string {
  return `data: ${JSON.stringify(event)}\n\n`;
}

/** Streams status, DELTAS (one write each, `gapMs` apart) and done; `/fail` streams an error first. */
async function withServer(gapMs: number, run: (base: string, counts: { requests: number }) => Promise<void>): Promise<void> {
  const counts = { requests: 0 };
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    req.resume();
    req.on('end', () => {
      counts.requests += 1;
      res.writeHead(200, { 'Content-Type': 'text/event-stream' });
      const fail = String(req.url || '').startsWith('/fail/');
      const events: string[] = [sse({ type: 'status', stage: 'generating', sources_count: 3 })];
      if (fail) {
        events.push(
          sse({
            type: 'error',
            message: 'The generation gateway is unavailable.',
            detail: { code: 'generation_unavailable', message: 'The generation gateway is unavailable.', retryable: true },
          }),
        );
      } else {
        for (const delta of DELTAS) events.push(sse({ type: 'text', content: delta }));
      }
      events.push(sse({ type: 'done', run_id: 'run-7', conversation_id: 'conv-1', sources: [], started_at_ms: 1, ended_at_ms: 2 }));
      let index = 0;
      const next = () => {
        if (res.destroyed) return;
        if (index >= events.length) {
          res.end();
          return;
        }
        res.write(events[index]);
        index += 1;
        setTimeout(next, gapMs);
      };
      next();
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  try {
    await run(`http://127.0.0.1:${port}`, counts);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

/** A frame scheduler whose frames never fire unless the test runs them (a hidden tab). */
function manualFrames(): { scheduler: FrameScheduler; pending: () => number; runFrame: () => void } {
  let handle = 1;
  const frames = new Map<number, () => void>();
  return {
    scheduler: {
      requestFrame: (callback) => {
        const id = handle++;
        frames.set(id, callback);
        return id;
      },
      cancelFrame: (id) => {
        frames.delete(id);
      },
      // The hidden-tab timer is parked too: nothing publishes unless the test says so.
      setTimer: () => -1,
      clearTimer: () => {},
    },
    pending: () => frames.size,
    runFrame: () => {
      const callbacks = [...frames.values()];
      frames.clear();
      for (const callback of callbacks) callback();
    },
  };
}

type Harness = {
  storage: MemoryStorage;
  toasts: string[];
  runs: unknown[];
  journeys: ChatJourney[];
  controller: ReturnType<typeof createChatStreamController>;
};

function harness(overrides: Partial<ChatStreamControllerDeps> = {}): Harness {
  const storage = new MemoryStorage();
  const toasts: string[] = [];
  const runs: unknown[] = [];
  const journeys: ChatJourney[] = [];
  const controller = createChatStreamController({
    send: sendRagweldChat,
    storage: () => storage,
    writerId: 'chat-stream-controller',
    scheduler: browserFrameScheduler(),
    now: () => Date.now(),
    monotonic: () => performance.now(),
    setTimer: (callback, ms) => setTimeout(callback, ms),
    clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    toast: (message) => toasts.push(message),
    runComplete: (detail) => runs.push(detail),
    journey: (journey) => journeys.push(journey),
    ...overrides,
  });
  return { storage, toasts, runs, journeys, controller };
}

/** Store conversation `conv-1` with the question and its running placeholder, as a view does on send. */
function seedTurn(storage: Storage, conversationId = 'conv-1') {
  const suffix = Math.random().toString(16).slice(2);
  const userMessage = createUserThreadMessage({ id: `user-${conversationId}-${suffix}`, text: QUESTION });
  const assistant = createAssistantThreadMessage({
    id: `assistant-${conversationId}-${suffix}`,
    status: { type: 'running' },
    custom: { waitStage: 'searching' },
  });
  const existing = storage.getItem(CHAT_SESSIONS_STORAGE_KEY) ? loadChatSessionsFromStorage(storage, 50).sessions : [];
  const others = existing.filter((session) => session.conversation_id !== conversationId);
  const current = existing.find((session) => session.conversation_id === conversationId);
  const session = createChatSession({
    conversationId,
    title: 'Salinity calibration',
    messages: [...(current?.messages ?? []), userMessage, assistant],
    sources: { corpus_ids: ['pytest_acceptance'] },
  });
  persistChatSessions(storage, [session, ...others], conversationId);
  return { userMessage, assistant };
}

function startTurn(h: Harness, base: string, turn: ReturnType<typeof seedTurn>, conversationId = 'conv-1', route = 'ok') {
  h.controller.start({
    conversationId,
    assistant: turn.assistant,
    userMessage: turn.userMessage,
    request: {
      api: (path) => `${base}/${route}/api/${path}`,
      includeGraph: false,
      includeSparse: true,
      includeVector: true,
      modelOverride: 'openai.gpt-5.6-luna',
      recallIntensityOverride: null,
      requestSources: { corpus_ids: ['pytest_acceptance'] },
      topK: null,
      webEnabled: false,
    },
    timeoutMs: 30_000,
    chatHistoryMax: 50,
    maxSessions: 50,
  });
}

function settled(h: Harness, count = 1): Promise<ChatTurnSettled[]> {
  const seen: ChatTurnSettled[] = [];
  return new Promise((resolve) => {
    const stop = h.controller.onSettled((event) => {
      seen.push(event);
      if (seen.length === count) {
        stop();
        resolve(seen);
      }
    });
  });
}

function storedAssistants(storage: Storage, conversationId = 'conv-1'): ThreadAssistantMessage[] {
  const session = loadChatSessionsFromStorage(storage, 50).sessions.find((s) => s.conversation_id === conversationId);
  return (session?.messages ?? []).filter((m) => m.role === 'assistant') as ThreadAssistantMessage[];
}

test('with no view mounted, the answer lands in the stored thread exactly once, with its run', async () => {
  await withServer(2, async (base, counts) => {
    const h = harness();
    const turn = seedTurn(h.storage);
    const done = settled(h);
    startTurn(h, base, turn);
    assert.equal(h.controller.runningAssistantId('conv-1'), turn.assistant.id);
    assert.equal(h.controller.isRunning(turn.assistant.id), true);
    const [event] = await done;
    assert.equal(event.outcome, 'ok');
    assert.equal(counts.requests, 1);
    assert.equal(h.controller.runningAssistantId('conv-1'), null);

    const assistants = storedAssistants(h.storage);
    assert.equal(assistants.length, 1, 'persisted exactly once');
    assert.equal(assistants[0].id, turn.assistant.id);
    assert.equal(getMessageText(assistants[0]), ANSWER);
    assert.equal(assistants[0].status.type, 'complete');
    assert.equal(getMessageCustom(assistants[0]).runId, 'run-7');
    assert.equal(getMessageCustom(assistants[0]).waitStage, undefined, 'view state is never stored');
    assert.deepEqual(h.runs, [{ run_id: 'run-7', started_at_ms: 1, ended_at_ms: 2 }]);
    // A view that mounts after the turn settled but before it reloaded still sees the answer.
    assert.equal(getMessageText(h.controller.liveContent(turn.assistant.id)!.final!), ANSWER);

    assert.deepEqual(
      h.journeys.map((j) => [j.name, j.model, j.outcome]),
      [
        ['chat_send_to_status', 'openai.gpt-5.6-luna', 'ok'],
        ['chat_send_to_first_text', 'openai.gpt-5.6-luna', 'ok'],
        ['chat_send_to_done', 'openai.gpt-5.6-luna', 'ok'],
      ],
    );
    const [status, first, finished] = h.journeys.map((j) => j.durationMs);
    assert.ok(status >= 0 && status <= first && first <= finished, JSON.stringify(h.journeys));
  });
});

test('text reaches views at most once per frame; with no frames at all the turn still settles in full', async () => {
  await withServer(3, async (base) => {
    const frames = manualFrames();
    const h = harness({ scheduler: frames.scheduler });
    const turn = seedTurn(h.storage);
    const done = settled(h);
    startTurn(h, base, turn);
    assert.equal(h.controller.liveContent(turn.assistant.id)?.text, '', 'the turn starts published, empty');
    let publishes = 0;
    h.controller.subscribeContent(turn.assistant.id, () => (publishes += 1));

    // Wait until deltas have arrived and asked for a frame, then let exactly one frame run.
    while (frames.pending() === 0) await new Promise((resolve) => setTimeout(resolve, 2));
    await new Promise((resolve) => setTimeout(resolve, 20));
    frames.runFrame();
    const midway = h.controller.liveContent(turn.assistant.id)!;
    assert.equal(publishes, 1, 'one frame, one publish, however many deltas arrived before it');
    assert.ok(midway.text.length > 0 && midway.text.length < ANSWER.length, `${midway.text.length} chars midway`);
    assert.ok(ANSWER.startsWith(midway.text));
    assert.equal(midway.waitStage, 'generating');

    // No further frames: the remaining deltas never publish, yet the settled answer is complete.
    const [event] = await done;
    assert.equal(event.outcome, 'ok');
    assert.equal(publishes, 2, 'the terminal state is published without waiting for a frame');
    const final = h.controller.liveContent(turn.assistant.id)!;
    assert.equal(final.running, false);
    assert.equal(getMessageText(final.final!), ANSWER);
    assert.equal(getMessageText(storedAssistants(h.storage)[0]), ANSWER);
  });
});

test('a second turn in the same conversation supersedes the first: one stream per conversation', async () => {
  await withServer(5, async (base, counts) => {
    const h = harness();
    const first = seedTurn(h.storage);
    const both = settled(h, 2);
    startTurn(h, base, first);
    await new Promise((resolve) => setTimeout(resolve, 30));
    const second = seedTurn(h.storage);
    startTurn(h, base, second);
    assert.equal(h.controller.runningAssistantId('conv-1'), second.assistant.id);
    const events = await both;
    assert.deepEqual(events.map((e) => [e.assistantId, e.outcome]), [
      [first.assistant.id, 'interrupted'],
      [second.assistant.id, 'ok'],
    ]);
    assert.equal(counts.requests, 2);
    const assistants = storedAssistants(h.storage);
    assert.equal(assistants.length, 2);
    assert.equal(assistants[0].status.type, 'incomplete');
    assert.equal((assistants[0].status as { error?: string }).error, INTERRUPTED_STREAM_MESSAGE);
    assert.equal(getMessageText(assistants[1]), ANSWER);
  });
});

test('Stop lands a cancelled message; deleting the conversation lands nothing', async () => {
  await withServer(5, async (base) => {
    const h = harness();
    const turn = seedTurn(h.storage);
    const done = settled(h);
    startTurn(h, base, turn);
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.equal(h.controller.cancel('conv-1', 'user_cancel'), true);
    const [event] = await done;
    assert.equal(event.outcome, 'cancelled');
    const [assistant] = storedAssistants(h.storage);
    assert.equal(assistant.status.type, 'incomplete');
    assert.equal(getMessageText(assistant), 'Error: Chat request was cancelled.');
    assert.equal(h.controller.cancel('conv-1', 'user_cancel'), false, 'nothing left to stop');

    const h2 = harness();
    const doomed = seedTurn(h2.storage, 'conv-2');
    const gone = settled(h2);
    startTurn(h2, base, doomed, 'conv-2');
    await new Promise((resolve) => setTimeout(resolve, 30));
    const before = h2.storage.getItem(CHAT_SESSIONS_STORAGE_KEY);
    h2.controller.cancel('conv-2', 'deleted');
    const [deleted] = await gone;
    assert.equal(deleted.outcome, 'cancelled');
    assert.equal(h2.storage.getItem(CHAT_SESSIONS_STORAGE_KEY), before, 'a deleted conversation is not written');
    assert.equal(h2.controller.liveContent(doomed.assistant.id), null);
  });
});

test('a failed stream lands its structured error with the run the server recorded', async () => {
  await withServer(1, async (base) => {
    const h = harness();
    const turn = seedTurn(h.storage);
    const done = settled(h);
    startTurn(h, base, turn, 'conv-1', 'fail');
    const [event] = await done;
    assert.equal(event.outcome, 'error');
    const [assistant] = storedAssistants(h.storage);
    assert.equal(assistant.status.type, 'incomplete');
    const custom = getMessageCustom(assistant);
    assert.equal(custom.structuredError?.code, 'generation_unavailable');
    assert.equal(custom.runId, 'run-7');
    assert.deepEqual(h.toasts, ['The generation gateway is unavailable.']);
    assert.deepEqual(h.runs, [{ run_id: 'run-7', started_at_ms: 1, ended_at_ms: 2 }]);
    assert.equal(h.journeys.at(-1)?.outcome, 'error');
  });
});

test('first hydration reconciles an abandoned stream, never one that is still live', () => {
  const live = createAssistantThreadMessage({ id: 'assistant-live', status: { type: 'running' } });
  const abandoned = createAssistantThreadMessage({ id: 'assistant-abandoned', status: { type: 'running' } });
  const { messages, changed } = reconcileInterruptedMessages([live, abandoned], (id) => id === 'assistant-live');
  assert.equal(changed, true);
  assert.equal((messages[0] as ThreadAssistantMessage).status.type, 'running');
  assert.equal((messages[1] as ThreadAssistantMessage).status.type, 'incomplete');
});
