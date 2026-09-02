// Unit rules for "which runs did THIS conversation produce" (S37/P2-A). The Routing Trace panel
// falls back to the corpus's most recent run and labels it as not-this-conversation's; that
// judgement is derived from the STORED thread, so it survives a reload and follows a session
// switch instead of belonging to whatever a tab happened to witness.
//
// The fixtures are written through the app's own writer (`persistChatSessions`), so these read
// the bytes the browser really stores, not a hand-shaped JSON guess.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  CHAT_SESSIONS_STORAGE_KEY,
  createAssistantThreadMessage,
  createChatSession,
  createUserThreadMessage,
  persistChatSessions,
  readActiveConversationRunIds,
} from '../../src/components/Chat/chatSessions.ts';

/** The Storage contract, in memory: same interface `localStorage` gives the app. */
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

function answeredSession(
  conversationId: string,
  question: string,
  runIds: { runId?: string; eventId?: string }[],
) {
  const messages = runIds.flatMap((run, index) => [
    createUserThreadMessage({ id: `user-${conversationId}-${index}`, text: question }),
    createAssistantThreadMessage({
      id: `assistant-${conversationId}-${index}`,
      text: 'Calibration is scheduled from the station log.',
      custom: run,
    }),
  ]);
  return createChatSession({ conversationId, title: conversationId, messages });
}

test('the run ids come from the ACTIVE conversation, not from the first stored one', () => {
  const storage = new MemoryStorage();
  const answered = answeredSession('conv-answered', 'How often is the salinity sensor calibrated?', [
    { runId: 'run-older' },
    { runId: 'run-latest' },
  ]);
  const other = answeredSession('conv-other', 'Which standard calibrates the salinity array?', [
    { runId: 'run-other' },
  ]);

  persistChatSessions(storage, [answered, other], 'conv-answered');
  assert.deepEqual(
    [...readActiveConversationRunIds(storage)].sort(),
    ['run-latest', 'run-older'],
    'every run the active conversation produced counts, not only its last one: "View trace" on an older answer opens a run it still produced',
  );

  // Selecting the other saved conversation is a write of the same store, so the next read
  // follows it -- the previous conversation's run is now somebody else's.
  persistChatSessions(storage, [answered, other], 'conv-other');
  assert.deepEqual([...readActiveConversationRunIds(storage)], ['run-other']);
});

test('a conversation that produced no run owns nothing', () => {
  const storage = new MemoryStorage();
  const fresh = createChatSession({ conversationId: 'conv-fresh', title: 'New chat', messages: [] });
  persistChatSessions(storage, [fresh], 'conv-fresh');
  assert.equal(readActiveConversationRunIds(storage).size, 0);
});

test('the feedback-side `eventId` names the same run as `runId`', () => {
  const storage = new MemoryStorage();
  const session = answeredSession('conv-event', 'What calibrates the salinity array?', [
    { eventId: 'run-from-event-id' },
  ]);
  persistChatSessions(storage, [session], 'conv-event');
  assert.deepEqual([...readActiveConversationRunIds(storage)], ['run-from-event-id']);
});

test('an active id that names no stored session falls back to the thread the loader activates', () => {
  const storage = new MemoryStorage();
  const first = answeredSession('conv-first', 'How often is the salinity sensor calibrated?', [
    { runId: 'run-first' },
  ]);
  persistChatSessions(storage, [first], 'conv-first');
  const stored = JSON.parse(String(storage.getItem(CHAT_SESSIONS_STORAGE_KEY)));
  stored.active_conversation_id = 'conv-that-was-deleted';
  storage.setItem(CHAT_SESSIONS_STORAGE_KEY, JSON.stringify(stored));

  assert.deepEqual(
    [...readActiveConversationRunIds(storage)],
    ['run-first'],
    'loadChatSessionsFromStorage activates sessions[0] in this case, so the label must read the same thread',
  );
});

test('an unreadable store labels nothing rather than throwing into the panel', () => {
  const storage = new MemoryStorage();
  storage.setItem(CHAT_SESSIONS_STORAGE_KEY, '{not json');
  assert.equal(readActiveConversationRunIds(storage).size, 0);

  const empty = new MemoryStorage();
  assert.equal(readActiveConversationRunIds(empty).size, 0);
});
