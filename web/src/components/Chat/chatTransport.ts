import type React from 'react';
import type {
  ActiveSources,
  ChatDebugInfo,
  ChunkMatch,
  RecallIntensity,
  RecallPlan,
  RerankDebugInfo,
} from '@/types/generated';
import type { Message } from '@/components/Chat/chatSessions';

const CHAT_STREAM_PATH = 'chat/stream';
const CHAT_PATH = 'chat';

export class ChatRequestAbortedError extends Error {
  reason: string;

  constructor(reason: string) {
    super('Chat request aborted');
    this.name = 'ChatRequestAbortedError';
    this.reason = String(reason || 'aborted');
  }
}

export function toAbortReason(error: unknown, signal?: AbortSignal): string | null {
  if (error instanceof ChatRequestAbortedError) {
    return String(error.reason || 'aborted');
  }
  if (error instanceof DOMException && error.name === 'AbortError') {
    const reason = signal?.reason;
    return typeof reason === 'string' && reason.trim() ? reason.trim() : 'aborted';
  }
  return null;
}

type ChatTransportContext = {
  api: (path: string) => string;
  conversationId: string;
  modelOverride: string;
  includeVector: boolean;
  includeSparse: boolean;
  includeGraph: boolean;
  fastMode: boolean;
  chatHistoryMax: number;
  messagesContainerRef: React.RefObject<HTMLDivElement | null>;
  messagesEndRef: React.RefObject<HTMLDivElement | null>;
  isRequestTokenActive: (token: number) => boolean;
  setStreaming: React.Dispatch<React.SetStateAction<boolean>>;
  setConversationId: React.Dispatch<React.SetStateAction<string>>;
  setMessages: React.Dispatch<React.SetStateAction<Message[]>>;
  setLastMatches: React.Dispatch<React.SetStateAction<ChunkMatch[]>>;
  setLastLatencyMs: React.Dispatch<React.SetStateAction<number | null>>;
  setLastRecallPlan: React.Dispatch<React.SetStateAction<RecallPlan | null>>;
  maybeToastRerankOutcome: (rerank: RerankDebugInfo | null | undefined) => void;
  showToast: (message: string, tone?: 'success' | 'error' | 'info') => void;
  saveChatHistory: (messages: Message[]) => void;
};

type SendChatTransportArgs = {
  userMessage: Message;
  recallIntensityOverride: RecallIntensity | null;
  requestToken: number;
  signal: AbortSignal;
  requestSources: ActiveSources;
  streamPreferred: boolean;
  markStreamingSupported?: () => void;
  markStreamingUnsupported?: () => void;
};

function readChatErrorDetail(resp: Response): Promise<string> {
  return (async () => {
    try {
      const contentType = resp.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        const body: any = await resp.json();
        const detail = body?.detail ?? body?.message ?? body?.error ?? null;
        if (typeof detail === 'string' && detail.trim()) return detail.trim();
        return JSON.stringify(body).slice(0, 500);
      }
      const text = await resp.text();
      return (text || '').trim().slice(0, 500);
    } catch {
      return '';
    }
  })();
}

function buildChatPayload(
  ctx: ChatTransportContext,
  args: Pick<SendChatTransportArgs, 'userMessage' | 'requestSources' | 'recallIntensityOverride'>,
  stream: boolean
): Record<string, unknown> {
  return {
    message: args.userMessage.content,
    sources: args.requestSources,
    conversation_id: ctx.conversationId,
    stream,
    images: Array.isArray(args.userMessage.images) ? args.userMessage.images : [],
    model_override: ctx.modelOverride,
    include_vector: ctx.includeVector,
    include_sparse: ctx.includeSparse,
    include_graph: ctx.includeGraph,
    recall_intensity: args.recallIntensityOverride,
  };
}

function buildCitations(sources: ChunkMatch[]): string[] {
  return sources
    .map((source: any) => {
      const filePath = source?.file_path;
      const startLine = source?.start_line;
      const endLine = source?.end_line;
      if (!filePath) return null;
      return `${filePath}:${startLine ?? 0}-${endLine ?? startLine ?? 0}`;
    })
    .filter(Boolean) as string[];
}

function buildProviderMeta(debug: ChatDebugInfo | null): Record<string, string> | undefined {
  const provider = (debug as any)?.provider;
  if (!provider || typeof provider !== 'object') return undefined;
  const backend = String((provider as any).provider_name || '').trim();
  const model = String((provider as any).model || '').trim();
  const kind = String((provider as any).kind || '').trim();
  const baseUrl = String((provider as any).base_url || '').trim();
  const meta: Record<string, string> = {};
  if (backend) meta.backend = backend;
  if (model) meta.model = model;
  if (kind) meta.kind = kind;
  if (baseUrl) meta.base_url = baseUrl;
  return Object.keys(meta).length ? meta : undefined;
}

function emitRunComplete(runId?: string, startedAtMs?: number, endedAtMs?: number): void {
  try {
    window.dispatchEvent(
      new CustomEvent('tribrid:chat:run-complete', {
        detail: {
          run_id: runId,
          started_at_ms: startedAtMs,
          ended_at_ms: endedAtMs,
        },
      })
    );
  } catch {
    // ignore event dispatch failures
  }
}

async function runRegularChat(ctx: ChatTransportContext, args: Omit<SendChatTransportArgs, 'streamPreferred' | 'markStreamingSupported' | 'markStreamingUnsupported'>): Promise<void> {
  if (!ctx.isRequestTokenActive(args.requestToken)) {
    throw new ChatRequestAbortedError('stale');
  }

  const params = new URLSearchParams(window.location.search || '');
  const fast = ctx.fastMode || params.get('fast') === '1' || params.get('smoke') === '1';
  void fast;

  let response: Response;
  try {
    response = await fetch(ctx.api(CHAT_PATH), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: args.signal,
      body: JSON.stringify(buildChatPayload(ctx, args, false)),
    });
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) throw new ChatRequestAbortedError(abortReason);
    throw error;
  }

  if (!response.ok) {
    const detail = await readChatErrorDetail(response);
    throw new Error(detail || 'Failed to get response');
  }

  const data = await response.json();
  if (!ctx.isRequestTokenActive(args.requestToken)) {
    throw new ChatRequestAbortedError('stale');
  }

  const nextConversationId = data && typeof data.conversation_id === 'string' ? data.conversation_id : null;
  if (nextConversationId && ctx.isRequestTokenActive(args.requestToken)) {
    ctx.setConversationId(nextConversationId);
  }

  const sources: ChunkMatch[] = Array.isArray(data?.sources) ? (data.sources as ChunkMatch[]) : [];
  ctx.setLastMatches(sources);
  const citations = buildCitations(sources);

  let assistantText = String(data?.message?.content || '');
  if (!assistantText.trim()) {
    const provider = data?.debug?.provider?.provider_name ? String(data.debug.provider.provider_name) : '';
    const model = data?.debug?.provider?.model ? String(data.debug.provider.model) : '';
    assistantText = `Error: Empty response from model${provider || model ? ` (${[provider, model].filter(Boolean).join(' ')})` : ''}`;
    ctx.showToast('Chat failed: empty model response.', 'error');
  }

  const runId = typeof data?.run_id === 'string' ? data.run_id : undefined;
  const startedAtMs = typeof data?.started_at_ms === 'number' ? data.started_at_ms : undefined;
  const endedAtMs = typeof data?.ended_at_ms === 'number' ? data.ended_at_ms : undefined;
  if (typeof startedAtMs === 'number' && typeof endedAtMs === 'number') {
    ctx.setLastLatencyMs(Math.max(0, endedAtMs - startedAtMs));
  }

  const debug = data && typeof data?.debug === 'object' ? (data.debug as ChatDebugInfo) : null;
  if (ctx.isRequestTokenActive(args.requestToken)) {
    ctx.setLastRecallPlan((debug as any)?.recall_plan ?? null);
    ctx.maybeToastRerankOutcome(debug?.rerank);
  }

  const confidence = typeof data?.debug?.confidence === 'number' ? data.debug.confidence : undefined;
  const assistantMessage: Message = {
    id: `assistant-${Date.now()}`,
    role: 'assistant',
    content: assistantText,
    timestamp: Date.now(),
    citations,
    runId,
    eventId: runId,
    startedAtMs,
    endedAtMs,
    debug,
    confidence,
    meta: buildProviderMeta(debug),
  };

  emitRunComplete(runId, startedAtMs, endedAtMs);

  ctx.setMessages((prev) => {
    if (!ctx.isRequestTokenActive(args.requestToken)) return prev;
    const updated = [...prev, assistantMessage];
    const trimmed = updated.length <= ctx.chatHistoryMax ? updated : updated.slice(-ctx.chatHistoryMax);
    ctx.saveChatHistory(trimmed);
    return trimmed;
  });
}

async function runStreamingChat(ctx: ChatTransportContext, args: Omit<SendChatTransportArgs, 'streamPreferred' | 'markStreamingSupported' | 'markStreamingUnsupported'>): Promise<void> {
  if (!ctx.isRequestTokenActive(args.requestToken)) {
    throw new ChatRequestAbortedError('stale');
  }

  ctx.setStreaming(true);

  let response: Response;
  try {
    response = await fetch(ctx.api(CHAT_STREAM_PATH), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: args.signal,
      body: JSON.stringify(buildChatPayload(ctx, args, true)),
    });
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) throw new ChatRequestAbortedError(abortReason);
    throw error;
  }

  if (!response.ok) {
    const detail = await readChatErrorDetail(response);
    throw new Error(detail ? `Failed to start streaming: ${detail}` : 'Failed to start streaming');
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable');
  }

  const decoder = new TextDecoder();
  let streamBuffer = '';
  let accumulatedContent = '';
  let sawTerminalChunk = false;
  let sawChunk = false;
  const assistantMessageId = `assistant-${Date.now()}`;
  const assistantTimestamp = Date.now();
  let citations: string[] = [];
  let runId: string | undefined;
  let startedAtMs: number | undefined;
  let endedAtMs: number | undefined;
  let debug: ChatDebugInfo | null = null;
  let confidence: number | undefined;
  let rafPending = false;
  let persistAfterNextRender = false;

  const scheduleAssistantRender = (persist: boolean = false) => {
    if (!ctx.isRequestTokenActive(args.requestToken)) return;
    if (persist) persistAfterNextRender = true;
    if (rafPending) return;

    const container = ctx.messagesContainerRef.current;
    const shouldAutoscroll =
      !!container && container.scrollHeight - container.scrollTop - container.clientHeight < 160;
    rafPending = true;

    requestAnimationFrame(() => {
      rafPending = false;
      if (!ctx.isRequestTokenActive(args.requestToken)) return;

      const assistantMessage: Message = {
        id: assistantMessageId,
        role: 'assistant',
        content: accumulatedContent,
        timestamp: assistantTimestamp,
        citations,
        runId,
        eventId: runId,
        startedAtMs,
        endedAtMs,
        debug,
        confidence,
        meta: buildProviderMeta(debug),
      };

      ctx.setMessages((prev) => {
        if (!ctx.isRequestTokenActive(args.requestToken)) return prev;
        const last = prev[prev.length - 1];
        let next: Message[];
        if (last && last.id === assistantMessageId) {
          next = prev.slice();
          next[next.length - 1] = assistantMessage;
        } else {
          next = [...prev, assistantMessage];
        }

        if (next.length > ctx.chatHistoryMax) {
          next = next.slice(-ctx.chatHistoryMax);
        }

        if (persistAfterNextRender) {
          persistAfterNextRender = false;
          ctx.saveChatHistory(next);
        }

        return next;
      });

      if (shouldAutoscroll) {
        requestAnimationFrame(() => {
          if (!ctx.isRequestTokenActive(args.requestToken)) return;
          ctx.messagesEndRef.current?.scrollIntoView({ behavior: 'auto' });
        });
      }
    });
  };

  const processDataLine = (line: string) => {
    if (!ctx.isRequestTokenActive(args.requestToken)) return;
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const data = trimmed.slice(5).trim();
    if (!data || data === '[DONE]') return;

    try {
      const parsed = JSON.parse(data);
      const chunkType = parsed.type;
      sawChunk = true;

      switch (chunkType) {
        case 'text':
          if (typeof parsed.content === 'string') {
            accumulatedContent += parsed.content;
          }
          break;

        case 'done':
          sawTerminalChunk = true;
          if (typeof parsed.conversation_id === 'string' && ctx.isRequestTokenActive(args.requestToken)) {
            ctx.setConversationId(parsed.conversation_id);
          }
          if (Array.isArray(parsed.sources) && ctx.isRequestTokenActive(args.requestToken)) {
            const nextSources = parsed.sources as ChunkMatch[];
            ctx.setLastMatches(nextSources);
            citations = buildCitations(nextSources);
          }
          if (typeof parsed.run_id === 'string') {
            runId = parsed.run_id;
          }
          if (typeof parsed.started_at_ms === 'number') {
            startedAtMs = parsed.started_at_ms;
          }
          if (typeof parsed.ended_at_ms === 'number') {
            const ended = parsed.ended_at_ms;
            endedAtMs = ended;
            if (typeof startedAtMs === 'number' && ctx.isRequestTokenActive(args.requestToken)) {
              ctx.setLastLatencyMs(Math.max(0, ended - startedAtMs));
            }
          }
          debug = parsed && typeof parsed.debug === 'object' ? (parsed.debug as ChatDebugInfo) : null;
          confidence = typeof parsed?.debug?.confidence === 'number' ? parsed.debug.confidence : undefined;
          if (ctx.isRequestTokenActive(args.requestToken)) {
            ctx.setLastRecallPlan((debug as any)?.recall_plan ?? null);
            ctx.maybeToastRerankOutcome(debug?.rerank);
          }
          if (!accumulatedContent.trim()) {
            accumulatedContent = 'Error: Empty response from model (stream finished without content)';
            if (ctx.isRequestTokenActive(args.requestToken)) {
              ctx.showToast('Chat failed: empty model response.', 'error');
            }
          }
          emitRunComplete(runId, startedAtMs, endedAtMs);
          break;

        case 'error':
          sawTerminalChunk = true;
          console.error('[ChatInterface] Stream error:', parsed.message);
          accumulatedContent = `Error: ${parsed.message || 'Unknown error'}`;
          if (ctx.isRequestTokenActive(args.requestToken)) {
            ctx.showToast(`Chat error: ${parsed.message || 'Unknown error'}`, 'error');
          }
          break;

        default:
          if (typeof parsed.content === 'string') {
            accumulatedContent += parsed.content;
          }
      }

      scheduleAssistantRender(chunkType === 'done' || chunkType === 'error');
    } catch (error) {
      console.error('[ChatInterface] Failed to parse SSE data:', error, data);
    }
  };

  const readNextChunk = async (): Promise<ReadableStreamReadResult<Uint8Array>> => {
    let onAbort: (() => void) | null = null;
    try {
      return await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          onAbort = () => {
            const reason =
              typeof args.signal.reason === 'string' && args.signal.reason.trim() ? args.signal.reason.trim() : 'aborted';
            reject(new ChatRequestAbortedError(reason));
          };
          args.signal.addEventListener('abort', onAbort, { once: true });
        }),
      ]);
    } finally {
      if (onAbort) {
        args.signal.removeEventListener('abort', onAbort);
      }
    }
  };

  while (true) {
    if (!ctx.isRequestTokenActive(args.requestToken)) {
      throw new ChatRequestAbortedError('stale');
    }

    let readResult: ReadableStreamReadResult<Uint8Array>;
    try {
      readResult = await readNextChunk();
    } catch (error) {
      const abortReason = toAbortReason(error, args.signal);
      if (abortReason) throw new ChatRequestAbortedError(abortReason);
      if (sawChunk || accumulatedContent.trim()) {
        sawTerminalChunk = true;
        if (!accumulatedContent.trim()) {
          accumulatedContent = 'Error: Chat stream interrupted before completion';
        }
        if (ctx.isRequestTokenActive(args.requestToken)) {
          ctx.showToast('Chat stream interrupted before completion.', 'error');
          scheduleAssistantRender(true);
        }
        return;
      }
      throw error;
    }

    const { done, value } = readResult;
    if (done) break;

    streamBuffer += decoder.decode(value, { stream: true });
    const lines = streamBuffer.split('\n');
    streamBuffer = lines.pop() || '';

    for (const line of lines) {
      processDataLine(line);
    }
  }

  const remaining = decoder.decode();
  if (remaining) {
    streamBuffer += remaining;
  }
  if (streamBuffer.trim()) {
    processDataLine(streamBuffer);
  }

  if (!ctx.isRequestTokenActive(args.requestToken)) {
    throw new ChatRequestAbortedError('stale');
  }
  if (!sawTerminalChunk && !accumulatedContent.trim()) {
    accumulatedContent = 'Error: Chat stream ended without a response (no SSE events received)';
    ctx.showToast('Chat failed: stream ended without response.', 'error');
  }

  scheduleAssistantRender(true);
}

export async function sendChatTransport(ctx: ChatTransportContext, args: SendChatTransportArgs): Promise<void> {
  const runArgs = {
    userMessage: args.userMessage,
    recallIntensityOverride: args.recallIntensityOverride,
    requestToken: args.requestToken,
    signal: args.signal,
    requestSources: args.requestSources,
  };

  if (!args.streamPreferred) {
    await runRegularChat(ctx, runArgs);
    return;
  }

  try {
    await runStreamingChat(ctx, runArgs);
    args.markStreamingSupported?.();
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) {
      throw new ChatRequestAbortedError(abortReason);
    }
    args.markStreamingUnsupported?.();
    await runRegularChat(ctx, runArgs);
  }
}
