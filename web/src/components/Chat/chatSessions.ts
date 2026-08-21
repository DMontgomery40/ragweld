import type {
  ActiveSources,
  ChatDebugInfo,
  ChunkMatch,
  ImageAttachment,
} from '@/types/generated';
import type {
  MessageStatus,
  ThreadAssistantMessage,
  ThreadAssistantMessagePart,
  ThreadMessage,
  ThreadUserMessage,
  ThreadUserMessagePart,
} from '@assistant-ui/react';
import type { ChatStructuredErrorDetail } from '@/components/Chat/chatTransport';

export type RagweldStructuredError = ChatStructuredErrorDetail & { http_status?: number };

export type RagweldMessageCustom = {
  confidence?: number;
  debug?: ChatDebugInfo | null;
  structuredError?: RagweldStructuredError;
  endedAtMs?: number;
  eventId?: string;
  imagesStripped?: boolean;
  imageCount?: number;
  legacyCitations?: string[];
  providerMeta?: Record<string, unknown>;
  providerResponseId?: string | null;
  rootSpanId?: string | null;
  runId?: string;
  sources?: ChunkMatch[];
  startedAtMs?: number;
  traceId?: string | null;
  correlationId?: string | null;
};

export type ChatSession = {
  conversation_id: string;
  created_at: number;
  updated_at: number;
  title: string;
  messages: ThreadMessage[];
  model_override: string;
  sources: ActiveSources;
};

export type ChatSessionsState = {
  version: 2;
  active_conversation_id: string;
  sessions: ChatSession[];
};

type CreateChatSessionOptions = {
  conversationId?: string;
  createdAt?: number;
  updatedAt?: number;
  title?: string;
  messages?: ThreadMessage[];
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
  messages: ThreadMessage[];
  modelOverride?: string;
  sources?: ActiveSources;
  now?: number;
  chatHistoryMax: number;
  maxSessions?: number;
};

type StoredThreadMessage = Omit<ThreadMessage, 'createdAt'> & {
  createdAt: string;
};

type LegacyMessage = {
  confidence?: number;
  content?: string;
  debug?: ChatDebugInfo | null;
  endedAtMs?: number;
  eventId?: string;
  id?: string;
  images?: ImageAttachment[];
  meta?: Record<string, unknown>;
  role?: 'assistant' | 'system' | 'user';
  runId?: string;
  startedAtMs?: number;
  timestamp?: number;
  citations?: string[];
};

type LegacyChatSession = {
  conversation_id?: string;
  created_at?: number;
  updated_at?: number;
  title?: string;
  messages?: LegacyMessage[];
  model_override?: string;
  sources?: ActiveSources;
};

type LegacyChatSessionsState = {
  version?: number;
  active_conversation_id?: string;
  sessions?: LegacyChatSession[];
};

export const CHAT_SESSIONS_STORAGE_KEY = 'ragweld-chat-threads:v2';
export const LEGACY_CHAT_SESSIONS_STORAGE_KEY = 'tribrid-chat-sessions:v1:global';
export const LEGACY_CHAT_HISTORY_STORAGE_KEY = 'tribrid-chat-history';
export const DEFAULT_CHAT_SESSION_LIMIT = 50;

export function defaultChatSources(): ActiveSources {
  return { corpus_ids: ['recall_default'] };
}

export function createConversationId(): string {
  try {
    const c: { randomUUID?: () => string } | undefined = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
    if (c?.randomUUID) return String(c.randomUUID());
  } catch {
    // ignore
  }
  return `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createUserTextPart(text: string): ThreadUserMessagePart {
  return { type: 'text', text };
}

function createAssistantTextPart(text: string): ThreadAssistantMessagePart {
  return { type: 'text', text };
}

function createImageParts(images: ImageAttachment[]): ThreadUserMessagePart[] {
  return (images || []).flatMap((image, index) => {
    if (!image?.base64) return [];
    const mimeType = String(image.mime_type || 'image/png').trim() || 'image/png';
    return [{
      type: 'image',
      image: `data:${mimeType};base64,${image.base64}`,
      filename: `image-${index + 1}`,
    }];
  });
}

export function getMessageText(message: ThreadMessage): string {
  return (message.content || []).reduce((acc, part) => {
    if (part.type === 'text' || part.type === 'reasoning') return `${acc}${part.text}`;
    return acc;
  }, '');
}

export function getMessageImages(message: ThreadMessage): string[] {
  return (message.content || []).reduce<string[]>((acc, part) => {
    if (part.type === 'image') acc.push(part.image);
    return acc;
  }, []);
}

export function getMessageCustom(message: ThreadMessage): RagweldMessageCustom {
  const custom = message?.metadata?.custom;
  if (!custom || typeof custom !== 'object') return {};
  return custom as RagweldMessageCustom;
}

export function setMessageCustom<T extends ThreadMessage>(message: T, custom: RagweldMessageCustom): T {
  return {
    ...message,
    metadata: {
      ...message.metadata,
      custom,
    },
  };
}

export function createUserThreadMessage(options: {
  id?: string;
  text: string;
  images?: ImageAttachment[];
  createdAt?: Date;
  custom?: RagweldMessageCustom;
}): ThreadUserMessage {
  const createdAt = options.createdAt ?? new Date();
  const text = String(options.text || '');
  const images = Array.isArray(options.images) ? options.images : [];
  const content: ThreadUserMessagePart[] = [];
  if (text.trim()) content.push(createUserTextPart(text));
  content.push(...createImageParts(images));
  return {
    id: String(options.id || `user-${createdAt.getTime()}`),
    role: 'user',
    createdAt,
    content,
    attachments: [],
    metadata: {
      custom: options.custom ?? {},
    },
  };
}

export function createAssistantThreadMessage(options: {
  id?: string;
  text?: string;
  createdAt?: Date;
  status?: MessageStatus;
  custom?: RagweldMessageCustom;
  }): ThreadAssistantMessage {
  const createdAt = options.createdAt ?? new Date();
  const text = String(options.text || '');
  const content: ThreadAssistantMessagePart[] = text ? [createAssistantTextPart(text)] : [];
  return {
    id: String(options.id || `assistant-${createdAt.getTime()}`),
    role: 'assistant',
    createdAt,
    content,
    status: options.status ?? { type: 'complete', reason: 'stop' },
    metadata: {
      unstable_state: null,
      unstable_annotations: [],
      unstable_data: [],
      steps: [],
      timing: undefined,
      custom: options.custom ?? {},
    },
  };
}

export function clampChatHistory(messages: ThreadMessage[], chatHistoryMax: number): ThreadMessage[] {
  if (!Array.isArray(messages)) return [];
  if (messages.length <= chatHistoryMax) return messages;
  return messages.slice(-chatHistoryMax);
}

export function deriveSessionTitle(messages: ThreadMessage[]): string {
  const firstUserMessage = messages.find((message) => message?.role === 'user' && getMessageText(message).trim().length > 0);
  const title = getMessageText(firstUserMessage || ({} as ThreadMessage)).trim();
  if (!title) return 'New chat';
  return title.length > 60 ? `${title.slice(0, 57)}...` : title;
}

export function coerceChatSessionsState(raw: unknown): ChatSessionsState | null {
  if (!raw || typeof raw !== 'object') return null;
  const obj = raw as Partial<ChatSessionsState>;
  if (obj.version !== 2) return null;
  if (typeof obj.active_conversation_id !== 'string' || !obj.active_conversation_id.trim()) return null;
  if (!Array.isArray(obj.sessions)) return null;
  return obj as ChatSessionsState;
}

function serializeMessage(message: ThreadMessage): StoredThreadMessage {
  const custom = getMessageCustom(message);
  const content = (message.content || []).filter((part) => part.type !== 'image');
  const nextCustom: RagweldMessageCustom = {
    ...custom,
  };
  const imageCount = getMessageImages(message).length;
  if (imageCount > 0) {
    nextCustom.imagesStripped = true;
    nextCustom.imageCount = imageCount;
  }
  return {
    ...message,
    createdAt: message.createdAt.toISOString(),
    content: content as ThreadMessage['content'],
    metadata: {
      ...message.metadata,
      custom: nextCustom,
    },
  };
}

function deserializeMessage(message: StoredThreadMessage): ThreadMessage {
  return {
    ...message,
    createdAt: new Date(message.createdAt),
  } as ThreadMessage;
}

function migrateLegacyMessage(message: LegacyMessage, index: number): ThreadMessage {
  const createdAt = new Date(Number(message.timestamp || Date.now()));
  const custom: RagweldMessageCustom = {
    confidence: typeof message.confidence === 'number' ? message.confidence : undefined,
    debug: message.debug ?? null,
    endedAtMs: typeof message.endedAtMs === 'number' ? message.endedAtMs : undefined,
    eventId: typeof message.eventId === 'string' ? message.eventId : undefined,
    legacyCitations: Array.isArray(message.citations) ? message.citations : undefined,
    providerMeta: message.meta && typeof message.meta === 'object' ? message.meta : undefined,
    runId: typeof message.runId === 'string' ? message.runId : undefined,
    startedAtMs: typeof message.startedAtMs === 'number' ? message.startedAtMs : undefined,
  };

  if (message.role === 'assistant') {
    return createAssistantThreadMessage({
      id: String(message.id || `assistant-${createdAt.getTime()}-${index}`),
      text: String(message.content || ''),
      createdAt,
      status: String(message.content || '').startsWith('Error:')
        ? { type: 'incomplete', reason: 'error', error: String(message.content || '') }
        : { type: 'complete', reason: 'stop' },
      custom,
    });
  }

  return createUserThreadMessage({
    id: String(message.id || `user-${createdAt.getTime()}-${index}`),
    text: String(message.content || ''),
    images: Array.isArray(message.images) ? message.images : [],
    createdAt,
    custom,
  });
}

function migrateLegacySessionsState(raw: LegacyChatSessionsState | LegacyChatSession[] | LegacyMessage[]): ChatSessionsState | null {
  const normalized: LegacyChatSessionsState =
    Array.isArray(raw)
      ? { version: 1, active_conversation_id: '', sessions: [{ messages: raw as LegacyMessage[] }] }
      : raw;

  const legacySessions = Array.isArray(normalized.sessions) ? normalized.sessions : [];
  if (!legacySessions.length) return null;

  const sessions = legacySessions.map((session, index) => {
    const createdAt = Number(session.created_at ?? Date.now());
    const messages = Array.isArray(session.messages)
      ? session.messages.map((message, messageIndex) => migrateLegacyMessage(message, messageIndex))
      : [];
    return createChatSession({
      conversationId: String(session.conversation_id || '').trim() || `migrated-${index}-${createdAt}`,
      createdAt,
      updatedAt: Number(session.updated_at ?? createdAt),
      title: String(session.title || '').trim() || deriveSessionTitle(messages),
      messages,
      modelOverride: String(session.model_override || '').trim(),
      sources: session.sources || defaultChatSources(),
    });
  });

  const activeConversationId = String(normalized.active_conversation_id || sessions[0]?.conversation_id || '').trim();
  return {
    version: 2,
    active_conversation_id: activeConversationId || sessions[0]!.conversation_id,
    sessions,
  };
}

export function createChatSession(options: CreateChatSessionOptions = {}): ChatSession {
  const createdAt = Number(options.createdAt ?? Date.now());
  const messages = clampChatHistory(
    Array.isArray(options.messages) ? options.messages : [],
    options.chatHistoryMax ?? DEFAULT_CHAT_SESSION_LIMIT,
  );
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
  return (sessions || []).map((session) => ({
    ...session,
    messages: (session.messages || []).map(serializeMessage).map(deserializeMessage),
  }));
}

export function persistChatSessions(storage: Storage, sessions: ChatSession[], activeId: string): void {
  const state: ChatSessionsState = {
    version: 2,
    active_conversation_id: activeId,
    sessions: compactChatSessionsForStorage(sessions),
  };
  const serialized = {
    ...state,
    sessions: state.sessions.map((session) => ({
      ...session,
      messages: session.messages.map(serializeMessage),
    })),
  };
  storage.setItem(CHAT_SESSIONS_STORAGE_KEY, JSON.stringify(serialized));
}

export function loadChatSessionsFromStorage(storage: Storage, chatHistoryMax: number): LoadChatSessionsResult {
  const raw = storage.getItem(CHAT_SESSIONS_STORAGE_KEY);
  if (raw) {
    const parsed = coerceChatSessionsState(JSON.parse(raw));
    if (parsed) {
      const sessions = parsed.sessions.map((session) => ({
        ...session,
        messages: (session.messages as unknown as StoredThreadMessage[]).map(deserializeMessage),
      }));
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

  let migrated: ChatSessionsState | null = null;
  try {
    const legacySessionsRaw = storage.getItem(LEGACY_CHAT_SESSIONS_STORAGE_KEY);
    if (legacySessionsRaw) {
      migrated = migrateLegacySessionsState(JSON.parse(legacySessionsRaw));
    }
  } catch {
    migrated = null;
  }

  if (!migrated) {
    try {
      const legacyHistoryRaw = storage.getItem(LEGACY_CHAT_HISTORY_STORAGE_KEY);
      if (legacyHistoryRaw) {
        migrated = migrateLegacySessionsState(JSON.parse(legacyHistoryRaw));
      }
    } catch {
      migrated = null;
    }
  }

  if (migrated && migrated.sessions.length > 0) {
    const sessions = migrated.sessions.map((session) => createChatSession({
      ...session,
      messages: clampChatHistory(session.messages, chatHistoryMax),
      chatHistoryMax,
    }));
    const activeId = String(migrated.active_conversation_id || sessions[0]?.conversation_id || '').trim();
    const activeSession = sessions.find((session) => String(session.conversation_id || '').trim() === activeId) || sessions[0];
    return {
      sessions,
      activeSession,
      removeLegacyHistory: true,
    };
  }

  const session = createChatSession({
    createdAt: Date.now(),
    title: 'New chat',
    messages: [],
    chatHistoryMax,
  });
  return {
    sessions: [session],
    activeSession: session,
    removeLegacyHistory: false,
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
