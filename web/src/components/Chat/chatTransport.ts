import type {
  ActiveSources,
  ChatDebugInfo,
  ChunkMatch,
  DependencyUnavailableDetail,
  GenerationUnavailableDetail,
  PromptBudgetExceededDetail,
  ImageAttachment,
  RecallIntensity,
  RequiredRetrievalLegFailureDetail,
  RetrievalContractMismatchDetail,
} from '@/types/generated';
import type { ThreadMessage, ThreadUserMessage } from '@assistant-ui/react';

const CHAT_STREAM_PATH = 'chat/stream';
const CHAT_PATH = 'chat';

export type RagweldTraceHeaders = {
  correlationId: string | null;
  rootSpanId: string | null;
  traceId: string | null;
};

export type RagweldChatResult = {
  conversationId: string;
  debug: ChatDebugInfo | null;
  endedAtMs?: number;
  headers: RagweldTraceHeaders;
  providerResponseId?: string | null;
  runId?: string;
  sources: ChunkMatch[];
  startedAtMs?: number;
  text: string;
};

type RagweldStreamTerminal = {
  conversationId: string;
  debug: ChatDebugInfo | null;
  endedAtMs?: number;
  providerResponseId?: string | null;
  runId?: string;
  sources: ChunkMatch[];
  startedAtMs?: number;
};

type SendRagweldChatArgs = {
  api: (path: string) => string;
  conversationId: string;
  includeGraph: boolean;
  includeSparse: boolean;
  includeVector: boolean;
  message: ThreadUserMessage;
  modelOverride: string;
  onTextDelta?: (delta: string) => void;
  recallIntensityOverride: RecallIntensity | null;
  requestSources: ActiveSources;
  signal: AbortSignal;
  streamPreferred: boolean;
};

export class ChatRequestAbortedError extends Error {
  reason: string;

  constructor(reason: string) {
    super('Chat request aborted');
    this.name = 'ChatRequestAbortedError';
    this.reason = String(reason || 'aborted');
  }
}

/**
 * A typed, structured failure detail returned by the chat API when a request
 * fails before completion: retrieval contract mismatch (409), required-leg
 * failure or dependency/generation-gateway unavailability (503), or an
 * in-stream generation failure event.
 *
 * The shape is derived from the generated wire contracts so the frontend never
 * hand-maintains these fields. `Partial` across the union lets one renderer
 * narrow by presence; `code` is always present.
 */
export type ChatStructuredErrorDetail = Partial<
  Omit<DependencyUnavailableDetail, 'code'> &
    Omit<GenerationUnavailableDetail, 'code'> &
    Omit<PromptBudgetExceededDetail, 'code'> &
    Omit<RequiredRetrievalLegFailureDetail, 'code'> &
    Omit<RetrievalContractMismatchDetail, 'code'>
> & { code: string };

export class ChatRequestFailedError extends Error {
  status: number;
  detail: ChatStructuredErrorDetail | null;

  constructor(message: string, status: number, detail: ChatStructuredErrorDetail | null) {
    super(message);
    this.name = 'ChatRequestFailedError';
    this.status = status;
    this.detail = detail;
  }
}

function parseStructuredDetail(value: unknown): ChatStructuredErrorDetail | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.code !== 'string' || !record.code.trim()) return null;
  return record as ChatStructuredErrorDetail;
}

class ChatStreamEventError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChatStreamEventError';
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

function readTraceHeaders(response: Response): RagweldTraceHeaders {
  return {
    correlationId: response.headers.get('X-Correlation-ID'),
    rootSpanId: response.headers.get('X-Root-Span-ID'),
    traceId: response.headers.get('X-Trace-ID'),
  };
}

async function toChatRequestFailedError(resp: Response, fallback: string): Promise<ChatRequestFailedError> {
  try {
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('application/json')) {
      const body: Record<string, unknown> = await resp.json();
      const detail = body?.detail ?? body?.message ?? body?.error ?? null;
      const structured = parseStructuredDetail(detail);
      if (structured) {
        const summary = structured.message || structured.code;
        return new ChatRequestFailedError(summary, resp.status, structured);
      }
      if (typeof detail === 'string' && detail.trim()) {
        return new ChatRequestFailedError(detail.trim(), resp.status, null);
      }
      return new ChatRequestFailedError(JSON.stringify(body).slice(0, 500), resp.status, null);
    }
    const text = await resp.text();
    return new ChatRequestFailedError((text || '').trim().slice(0, 500) || fallback, resp.status, null);
  } catch {
    return new ChatRequestFailedError(fallback, resp.status, null);
  }
}

function getUserMessageText(message: ThreadMessage): string {
  return (message.content || [])
    .filter((part): part is { type: 'text'; text: string } => part.type === 'text')
    .map((part) => part.text)
    .join('\n')
    .trim();
}

function getUserImages(message: ThreadMessage): ImageAttachment[] {
  return (message.content || []).flatMap((part) => {
    if (part.type !== 'image') return [];
    const raw = String(part.image || '').trim();
    const match = raw.match(/^data:(.+?);base64,(.+)$/);
    if (!match) return [];
    return [{
      mime_type: match[1] || 'image/png',
      base64: match[2] || '',
    }];
  });
}

function buildChatPayload(
  args: SendRagweldChatArgs,
  stream: boolean,
): Record<string, unknown> {
  return {
    message: getUserMessageText(args.message),
    sources: args.requestSources,
    conversation_id: args.conversationId,
    stream,
    images: getUserImages(args.message),
    model_override: args.modelOverride,
    include_vector: args.includeVector,
    include_sparse: args.includeSparse,
    include_graph: args.includeGraph,
    recall_intensity: args.recallIntensityOverride,
  };
}

async function runRegularChat(args: SendRagweldChatArgs): Promise<RagweldChatResult> {
  let response: Response;
  try {
    response = await fetch(args.api(CHAT_PATH), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: args.signal,
      body: JSON.stringify(buildChatPayload(args, false)),
    });
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) throw new ChatRequestAbortedError(abortReason);
    throw error;
  }

  if (!response.ok) {
    throw await toChatRequestFailedError(response, 'Failed to get response');
  }

  const data = await response.json();
  const text = String(data?.message?.content || '').trim();
  if (!text) {
    throw new Error('LLM returned an empty response');
  }

  return {
    conversationId: typeof data?.conversation_id === 'string' ? data.conversation_id : args.conversationId,
    debug: data && typeof data?.debug === 'object' ? (data.debug as ChatDebugInfo) : null,
    endedAtMs: typeof data?.ended_at_ms === 'number' ? data.ended_at_ms : undefined,
    headers: readTraceHeaders(response),
    providerResponseId: typeof data?.provider_response_id === 'string' ? data.provider_response_id : null,
    runId: typeof data?.run_id === 'string' ? data.run_id : undefined,
    sources: Array.isArray(data?.sources) ? (data.sources as ChunkMatch[]) : [],
    startedAtMs: typeof data?.started_at_ms === 'number' ? data.started_at_ms : undefined,
    text,
  };
}

async function runStreamingChat(args: SendRagweldChatArgs): Promise<RagweldChatResult> {
  let response: Response;
  try {
    response = await fetch(args.api(CHAT_STREAM_PATH), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: args.signal,
      body: JSON.stringify(buildChatPayload(args, true)),
    });
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) throw new ChatRequestAbortedError(abortReason);
    throw error;
  }

  if (!response.ok) {
    throw await toChatRequestFailedError(response, 'Failed to start streaming');
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('Response body is not readable');
  }

  const decoder = new TextDecoder();
  let streamBuffer = '';
  let accumulatedText = '';
  let doneEvent: RagweldStreamTerminal | null = null;

  const readNextChunk = async (): Promise<ReadableStreamReadResult<Uint8Array>> => {
    let onAbort: (() => void) | null = null;
    try {
      return await Promise.race([
        reader.read(),
        new Promise<never>((_, reject) => {
          onAbort = () => {
            const reason =
              typeof args.signal.reason === 'string' && args.signal.reason.trim()
                ? args.signal.reason.trim()
                : 'aborted';
            reject(new ChatRequestAbortedError(reason));
          };
          args.signal.addEventListener('abort', onAbort, { once: true });
        }),
      ]);
    } finally {
      if (onAbort) args.signal.removeEventListener('abort', onAbort);
    }
  };

  const processDataLine = (line: string) => {
    const trimmed = line.trim();
    if (!trimmed.startsWith('data:')) return;
    const data = trimmed.slice(5).trim();
    if (!data || data === '[DONE]') return;

    const parsed = JSON.parse(data) as Record<string, unknown>;
    switch (parsed.type) {
      case 'text': {
        const delta = typeof parsed.content === 'string' ? parsed.content : '';
        if (!delta) return;
        accumulatedText += delta;
        args.onTextDelta?.(delta);
        return;
      }
      case 'done': {
        doneEvent = {
          conversationId:
            typeof parsed.conversation_id === 'string' ? parsed.conversation_id : args.conversationId,
          debug: parsed && typeof parsed.debug === 'object' ? (parsed.debug as ChatDebugInfo) : null,
          endedAtMs: typeof parsed.ended_at_ms === 'number' ? parsed.ended_at_ms : undefined,
          providerResponseId:
            typeof parsed.provider_response_id === 'string' ? parsed.provider_response_id : null,
          runId: typeof parsed.run_id === 'string' ? parsed.run_id : undefined,
          sources: Array.isArray(parsed.sources) ? (parsed.sources as ChunkMatch[]) : [],
          startedAtMs: typeof parsed.started_at_ms === 'number' ? parsed.started_at_ms : undefined,
        };
        return;
      }
      case 'error': {
        const message = typeof parsed.message === 'string' && parsed.message.trim()
          ? parsed.message.trim()
          : 'Chat request failed';
        const structured = parseStructuredDetail(parsed.detail);
        if (structured) {
          throw new ChatRequestFailedError(structured.message || message, 200, structured);
        }
        throw new ChatStreamEventError(message);
      }
      default:
        return;
    }
  };

  while (true) {
    let readResult: ReadableStreamReadResult<Uint8Array>;
    try {
      readResult = await readNextChunk();
    } catch (error) {
      const abortReason = toAbortReason(error, args.signal);
      if (abortReason) throw new ChatRequestAbortedError(abortReason);
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
  if (remaining) streamBuffer += remaining;
  if (streamBuffer.trim()) {
    processDataLine(streamBuffer);
  }

  if (!doneEvent) {
    throw new Error('Chat stream ended without a terminal done event');
  }
  const finalEvent: RagweldStreamTerminal = doneEvent;

  return {
    conversationId: finalEvent.conversationId,
    debug: finalEvent.debug,
    endedAtMs: finalEvent.endedAtMs,
    headers: readTraceHeaders(response),
    providerResponseId: finalEvent.providerResponseId,
    runId: finalEvent.runId,
    sources: finalEvent.sources,
    startedAtMs: finalEvent.startedAtMs,
    text: accumulatedText,
  };
}

export async function sendRagweldChat(args: SendRagweldChatArgs): Promise<RagweldChatResult> {
  if (!args.streamPreferred) {
    return runRegularChat(args);
  }

  try {
    return await runStreamingChat(args);
  } catch (error) {
    const abortReason = toAbortReason(error, args.signal);
    if (abortReason) throw new ChatRequestAbortedError(abortReason);
    if (error instanceof ChatStreamEventError) throw error;
    if (!(error instanceof Error) || error.message !== 'Response body is not readable') throw error;
    return runRegularChat({ ...args, streamPreferred: false });
  }
}
