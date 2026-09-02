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
  WebGroundingMetadata,
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
  webGrounding: WebGroundingMetadata;
};

type RagweldStreamTerminal = {
  conversationId: string;
  debug: ChatDebugInfo | null;
  endedAtMs?: number;
  providerResponseId?: string | null;
  runId?: string;
  sources: ChunkMatch[];
  startedAtMs?: number;
  webGrounding: WebGroundingMetadata;
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
  /** Per-message override of the corpus's retrieval.final_k; null uses the corpus default. */
  topK: number | null;
  webEnabled: boolean;
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

/** What the server had already committed about a request whose generation failed in-stream.
 * The stream's `error` event arrives BEFORE its terminal `done` event, and `done` is where the
 * run id lives; the transport used to throw on `error` and never read it, so a failed send had
 * no run to publish and the Routing Trace panel kept showing the previous, successful run
 * (2026-09-02 drive, S10). Reading through to `done` gives the failure the same identity a
 * success gets: run id, timing, and the trace headers. */
export type ChatFailedRun = {
  conversationId: string;
  endedAtMs?: number;
  headers: RagweldTraceHeaders;
  runId?: string;
  startedAtMs?: number;
};

export class ChatRequestFailedError extends Error {
  status: number;
  detail: ChatStructuredErrorDetail | null;
  /** Set when the failure came from the stream and its `done` event was read. */
  run: ChatFailedRun | null = null;

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

export class ChatStreamEventError extends Error {
  /** Set when the stream's `done` event was read after the untyped `error` event. */
  run: ChatFailedRun | null = null;

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
    top_k: args.topK,
    web_enabled: args.webEnabled,
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
    webGrounding: (data?.web_grounding || {
      web_requested: args.webEnabled,
      web_grounded: false,
      web_search_requests: null,
      citations: [],
    }) as WebGroundingMetadata,
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
  // The first in-stream failure; the stream is still read to its `done` event so the
  // failure can carry the run the server recorded.
  let streamFailure: ChatRequestFailedError | ChatStreamEventError | null = null;

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
          webGrounding: (parsed.web_grounding || {
            web_requested: args.webEnabled,
            web_grounded: false,
            web_search_requests: null,
            citations: [],
          }) as WebGroundingMetadata,
        };
        return;
      }
      case 'error': {
        if (streamFailure) return;
        const message = typeof parsed.message === 'string' && parsed.message.trim()
          ? parsed.message.trim()
          : 'Chat request failed';
        const structured = parseStructuredDetail(parsed.detail);
        streamFailure = structured
          ? new ChatRequestFailedError(structured.message || message, 200, structured)
          : new ChatStreamEventError(message);
        return;
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

  // Both are assigned inside processDataLine, so control-flow narrowing still sees the
  // initial nulls here; the casts restore the declared unions.
  const failure = streamFailure as ChatRequestFailedError | ChatStreamEventError | null;
  if (failure) {
    const terminal = doneEvent as RagweldStreamTerminal | null;
    if (terminal) {
      failure.run = {
        conversationId: terminal.conversationId,
        endedAtMs: terminal.endedAtMs,
        headers: readTraceHeaders(response),
        runId: terminal.runId,
        startedAtMs: terminal.startedAtMs,
      };
    }
    throw failure;
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
    webGrounding: finalEvent.webGrounding,
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
