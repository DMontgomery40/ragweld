import type { ActiveSources, ChatDebugInfo, ImageAttachment } from '@/types/generated';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  images?: ImageAttachment[];
  citations?: string[];
  confidence?: number;
  runId?: string;
  startedAtMs?: number;
  endedAtMs?: number;
  debug?: ChatDebugInfo | null;
  traceData?: any;
  meta?: any;
  eventId?: string;
}

export type ChatSession = {
  conversation_id: string;
  created_at: number;
  updated_at: number;
  title: string;
  messages: Message[];
  model_override: string;
  sources: ActiveSources;
};

export type ChatSessionsState = {
  version: 1;
  active_conversation_id: string;
  sessions: ChatSession[];
};

type CreateChatSessionOptions = {
  conversationId?: string;
  createdAt?: number;
  updatedAt?: number;
  title?: string;
  messages?: Message[];
  modelOverride?: string;
  sources?: ActiveSources;
  chatHistoryMax?: number;
};

type LoadChatSessionsResult = {
  sessions: ChatSession[];
  activeSession: ChatSession;
  removeLegacyHistory: boolean;
};

type UpsertChatSessionOptions = {
  sessions: ChatSession[];
  activeId: string;
  messages: Message[];
  modelOverride?: string;
  sources?: ActiveSources;
  now?: number;
  chatHistoryMax: number;
  maxSessions?: number;
};

export const CHAT_SESSIONS_STORAGE_KEY = 'tribrid-chat-sessions:v1:global';
export const LEGACY_CHAT_HISTORY_STORAGE_KEY = 'tribrid-chat-history';
export const DEFAULT_CHAT_SESSION_LIMIT = 50;

export function defaultChatSources(): ActiveSources {
  return { corpus_ids: ['recall_default'] };
}

export function createConversationId(): string {
  try {
    const c: any = (globalThis as any).crypto;
    if (c && typeof c.randomUUID === 'function') return String(c.randomUUID());
  } catch {
    // ignore
  }
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function clampChatHistory(messages: Message[], chatHistoryMax: number): Message[] {
  if (!Array.isArray(messages)) return [];
  if (messages.length <= chatHistoryMax) return messages;
  return messages.slice(-chatHistoryMax);
}

export function deriveSessionTitle(messages: Message[]): string {
  const first = messages.find((m) => m && m.role === 'user' && String(m.content || '').trim().length > 0);
  const title = String(first?.content || '').trim();
  if (!title) return 'New chat';
  return title.length > 60 ? `${title.slice(0, 57)}...` : title;
}

export function coerceChatSessionsState(raw: unknown): ChatSessionsState | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as any;
  if (obj.version !== 1) return null;
  if (typeof obj.active_conversation_id !== 'string' || !obj.active_conversation_id.trim()) return null;
  if (!Array.isArray(obj.sessions)) return null;
  return obj as ChatSessionsState;
}

export function createChatSession(options: CreateChatSessionOptions = {}): ChatSession {
  const createdAt = Number(options.createdAt ?? Date.now());
  const messages = clampChatHistory(Array.isArray(options.messages) ? options.messages : [], options.chatHistoryMax ?? DEFAULT_CHAT_SESSION_LIMIT);
  return {
    conversation_id: String(options.conversationId || '').trim() || createConversationId(),
    created_at: createdAt,
    updated_at: Number(options.updatedAt ?? createdAt),
    title: String(options.title || '').trim() || deriveSessionTitle(messages),
    messages,
    model_override: String(options.modelOverride || '').trim(),
    sources: options.sources || defaultChatSources(),
  };
}

export function compactChatSessionsForStorage(sessions: ChatSession[]): ChatSession[] {
  return (sessions || []).map((session) => {
    const messages = Array.isArray(session?.messages) ? session.messages : [];
    const compactMessages: Message[] = messages.map((message) => {
      if (!Array.isArray(message?.images) || message.images.length === 0) return message;
      const nextMeta = { ...(message.meta || {}), image_count: message.images.length, images_stripped: true };
      return { ...message, images: [], meta: nextMeta };
    });
    return { ...session, messages: compactMessages };
  });
}

export function persistChatSessions(storage: Storage, sessions: ChatSession[], activeId: string): void {
  const state: ChatSessionsState = {
    version: 1,
    active_conversation_id: activeId,
    sessions: compactChatSessionsForStorage(sessions),
  };
  storage.setItem(CHAT_SESSIONS_STORAGE_KEY, JSON.stringify(state));
}

export function loadChatSessionsFromStorage(storage: Storage, chatHistoryMax: number): LoadChatSessionsResult {
  const raw = storage.getItem(CHAT_SESSIONS_STORAGE_KEY);
  if (raw) {
    const parsed = coerceChatSessionsState(JSON.parse(raw));
    if (parsed) {
      const sessions = Array.isArray(parsed.sessions) ? parsed.sessions : [];
      const activeId = String(parsed.active_conversation_id || '').trim();
      const activeSession = sessions.find((session) => String(session.conversation_id || '').trim() === activeId) || sessions[0];
      if (activeSession) {
        return {
          sessions,
          activeSession,
          removeLegacyHistory: false,
        };
      }
    }
  }

  let legacyMessages: Message[] = [];
  try {
    const saved = storage.getItem(LEGACY_CHAT_HISTORY_STORAGE_KEY);
    if (saved) {
      const parsed = JSON.parse(saved);
      legacyMessages = Array.isArray(parsed) ? (parsed as Message[]) : [];
    }
  } catch {
    legacyMessages = [];
  }

  const session = createChatSession({
    createdAt: Date.now(),
    title: deriveSessionTitle(legacyMessages),
    messages: legacyMessages,
    chatHistoryMax,
  });
  return {
    sessions: [session],
    activeSession: session,
    removeLegacyHistory: true,
  };
}

export function upsertChatSession(options: UpsertChatSessionOptions): ChatSession[] {
  const nextMessages = clampChatHistory(options.messages, options.chatHistoryMax);
  const nextActiveId = String(options.activeId || '').trim() || createConversationId();
  const now = Number(options.now ?? Date.now());
  const maxSessions = Number(options.maxSessions ?? DEFAULT_CHAT_SESSION_LIMIT);
  const nextSources = options.sources || defaultChatSources();
  let nextSessions = Array.isArray(options.sessions) ? options.sessions.slice() : [];
  const index = nextSessions.findIndex((session) => String(session.conversation_id || '').trim() === nextActiveId);

  if (index >= 0) {
    const current = nextSessions[index];
    const nextTitle = current.title && current.title !== 'New chat' ? current.title : deriveSessionTitle(nextMessages);
    nextSessions[index] = {
      ...current,
      updated_at: now,
      title: nextTitle,
      messages: nextMessages,
      model_override: String(options.modelOverride || current.model_override || '').trim(),
      sources: nextSources,
    };
  } else {
    nextSessions = [
      createChatSession({
        conversationId: nextActiveId,
        createdAt: now,
        updatedAt: now,
        messages: nextMessages,
        modelOverride: options.modelOverride,
        sources: nextSources,
        chatHistoryMax: options.chatHistoryMax,
      }),
      ...nextSessions,
    ];
  }

  nextSessions.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
  if (nextSessions.length > maxSessions) nextSessions = nextSessions.slice(0, maxSessions);
  return nextSessions;
}
