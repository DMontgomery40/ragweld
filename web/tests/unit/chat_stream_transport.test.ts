// The chat waiting experience at its transport boundary: the stream's `status` and `thinking`
// events reach their callbacks and never the answer text, SSE keepalive comments are ignored,
// and an error answered by a proxy's HTML page (Cloudflare's 524 when the origin sent nothing
// for ~100 s) becomes a short classified message instead of the page's markup, which used to
// land verbatim in the message bubble, the error line and the toast. Served by a real local
// HTTP server; the transport under test is the app's own `sendRagweldChat`.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import test from 'node:test';

import {
  ChatRequestFailedError,
  describeNonJsonErrorBody,
  sendRagweldChat,
  type ChatStreamStatus,
} from '../../src/components/Chat/chatTransport.ts';
import {
  CHAT_SESSIONS_STORAGE_KEY,
  createAssistantThreadMessage,
  createChatSession,
  createUserThreadMessage,
  persistChatSessions,
} from '../../src/components/Chat/chatSessions.ts';
import { CHAT_WAITING_TIPS, shuffleTips, tipDurationMs } from '../../src/components/Chat/chatWaitingTips.ts';

const QUESTION = 'Which plane management company did Barry Cohen consider switching to?';

// Cloudflare's 524 page, abridged: what the browser used to render as the answer.
const CLOUDFLARE_524_PAGE = `<!DOCTYPE html>
<!--[if lt IE 7]> <html class="no-js ie6 oldie" lang="en-US"> <![endif]-->
<html class="no-js" lang="en-US"><head><title>ragweld.dtmont.com | 524: A timeout occurred</title>
<meta charset="UTF-8" /></head><body><div id="cf-wrapper"><h1>A timeout occurred</h1>
<span class="cf-error-code">524</span></div></body></html>`;

const STREAM_BODY = [
  'data: {"type": "status", "stage": "generating", "sources_count": 3}',
  ': keepalive',
  'data: {"type": "thinking", "content": "The user asks which company "}',
  ': keepalive',
  'data: {"type": "thinking", "content": "managed the plane."}',
  'data: {"type": "text", "content": "Jet Aviation "}',
  'data: {"type": "text", "content": "managed the plane."}',
  'data: {"type": "done", "run_id": "run-1", "conversation_id": "conv-1", "sources": [], "started_at_ms": 1, "ended_at_ms": 2}',
].join('\n\n') + '\n\n';

type Scenario = { status: number; contentType: string; body: string };

const SCENARIOS: Record<string, Scenario> = {
  'proxy-524': { status: 524, contentType: 'text/html; charset=UTF-8', body: CLOUDFLARE_524_PAGE },
  'proxy-502': { status: 502, contentType: 'text/html', body: '<html><head><title>502 Bad Gateway</title></head><body>Bad Gateway</body></html>' },
  'proxy-unknown': { status: 530, contentType: 'text/html', body: '<!doctype html><html><body>Origin DNS error</body></html>' },
  'plain-text': { status: 500, contentType: 'text/plain', body: 'Internal Server Error' },
  'typed-409': {
    status: 409,
    contentType: 'application/json',
    body: JSON.stringify({
      detail: {
        code: 'retrieval_contract_mismatch',
        message: 'The corpus was indexed with a different embedding contract.',
      },
    }),
  },
  stream: { status: 200, contentType: 'text/event-stream', body: STREAM_BODY },
};

async function withServer(run: (base: string) => Promise<void>): Promise<void> {
  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    req.resume();
    req.on('end', () => {
      const scenario = SCENARIOS[String(req.url || '').split('/')[1] || ''];
      if (!scenario) {
        res.writeHead(404).end();
        return;
      }
      res.writeHead(scenario.status, { 'Content-Type': scenario.contentType });
      res.end(scenario.body);
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address() as AddressInfo;
  try {
    await run(`http://127.0.0.1:${port}`);
  } finally {
    await new Promise<void>((resolve) => server.close(() => resolve()));
  }
}

function send(base: string, scenario: string, callbacks: Partial<Parameters<typeof sendRagweldChat>[0]> = {}) {
  return sendRagweldChat({
    api: (path) => `${base}/${scenario}/api/${path}`,
    conversationId: 'conv-1',
    includeGraph: false,
    includeSparse: true,
    includeVector: true,
    message: createUserThreadMessage({ text: QUESTION }),
    modelOverride: '',
    recallIntensityOverride: null,
    requestSources: { corpus_ids: [] },
    signal: new AbortController().signal,
    streamPreferred: true,
    topK: null,
    webEnabled: false,
    ...callbacks,
  });
}

async function failure(promise: Promise<unknown>): Promise<ChatRequestFailedError> {
  try {
    await promise;
  } catch (error) {
    assert.ok(error instanceof ChatRequestFailedError, `expected ChatRequestFailedError, got ${String(error)}`);
    return error;
  }
  throw new Error('the request was expected to fail');
}

test('a proxy 524 page becomes a short classified message, never the page markup', async () => {
  await withServer(async (base) => {
    const error = await failure(send(base, 'proxy-524'));
    assert.equal(error.status, 524);
    assert.equal(error.message, 'The request timed out at the proxy (524)');
    assert.equal(error.detail, null);
  });
});

test('every proxy error page is named by status; plain text and typed JSON keep their own words', async () => {
  await withServer(async (base) => {
    assert.equal((await failure(send(base, 'proxy-502'))).message, 'The proxy could not get a response from the server (502)');
    assert.equal((await failure(send(base, 'proxy-unknown'))).message, 'The proxy returned an error page (HTTP 530)');
    assert.equal((await failure(send(base, 'plain-text'))).message, 'Internal Server Error');
    const typed = await failure(send(base, 'typed-409'));
    assert.equal(typed.message, 'The corpus was indexed with a different embedding contract.');
    assert.equal(typed.detail?.code, 'retrieval_contract_mismatch');
  });
  // An HTML body is recognised by its markup even when the proxy mislabels the content type.
  assert.equal(describeNonJsonErrorBody(524, 'application/octet-stream', CLOUDFLARE_524_PAGE), 'The request timed out at the proxy (524)');
  for (const scenario of Object.values(SCENARIOS)) {
    assert.ok(!describeNonJsonErrorBody(scenario.status, scenario.contentType, scenario.body).includes('<'));
  }
});

test('status and thinking reach their callbacks in order, keepalives are ignored, and thinking is never answer text', async () => {
  await withServer(async (base) => {
    const seen: string[] = [];
    const statuses: ChatStreamStatus[] = [];
    let thinking = '';
    const result = await send(base, 'stream', {
      onStatus: (status) => {
        statuses.push(status);
        seen.push('status');
      },
      onThinkingDelta: (delta) => {
        thinking += delta;
        seen.push('thinking');
      },
      onTextDelta: () => seen.push('text'),
    });
    assert.deepEqual(statuses, [{ stage: 'generating', sourcesCount: 3 }]);
    assert.deepEqual(seen, ['status', 'thinking', 'thinking', 'text', 'text']);
    assert.equal(thinking, 'The user asks which company managed the plane.');
    assert.equal(result.text, 'Jet Aviation managed the plane.');
    assert.equal(result.runId, 'run-1');
  });
});

test('stored chat history keeps the answer and drops the reasoning and the waiting stage', () => {
  const storage = {
    data: new Map<string, string>(),
    getItem(key: string) {
      return this.data.get(key) ?? null;
    },
    setItem(key: string, value: string) {
      this.data.set(key, value);
    },
  } as unknown as Storage & { data: Map<string, string> };
  const session = createChatSession({
    conversationId: 'conv-thinking',
    messages: [
      createUserThreadMessage({ id: 'user-1', text: QUESTION }),
      createAssistantThreadMessage({
        id: 'assistant-1',
        text: 'Jet Aviation managed the plane.',
        custom: { runId: 'run-1', thinking: 'The user asks which company managed the plane.', waitStage: 'generating', waitSourcesCount: 3 },
      }),
    ],
  });
  persistChatSessions(storage, [session], 'conv-thinking');
  const stored = String(storage.getItem(CHAT_SESSIONS_STORAGE_KEY));
  assert.ok(stored.includes('Jet Aviation managed the plane.'));
  assert.ok(stored.includes('run-1'));
  assert.ok(!stored.includes('which company'), 'reasoning reached stored history');
  assert.ok(!stored.includes('waitStage') && !stored.includes('waitSourcesCount'));
});

test('waiting tips rotate through every tip once per pass and stay readable', () => {
  let seed = 7;
  const random = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const order = shuffleTips(CHAT_WAITING_TIPS, random);
  assert.equal(order.length, CHAT_WAITING_TIPS.length);
  assert.deepEqual(new Set(order), new Set(CHAT_WAITING_TIPS));
  for (const { tip } of CHAT_WAITING_TIPS) {
    const ms = tipDurationMs(tip);
    assert.ok(ms >= 4_000 && ms <= 9_000, `${ms}ms for "${tip}"`);
  }
  // Tips must describe the product as it is: these name features that no longer exist.
  const retired = /VS Code|fast mode|fail(s)? over|failover|pgvector|Ollama|Docker|webhook|\bCLI\b|Tri-Brid|repo selector|MLX/i;
  for (const { tip } of CHAT_WAITING_TIPS) assert.ok(!retired.test(tip), `retired feature in tip: ${tip}`);
});
