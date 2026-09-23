import type { MessageStatus, ThreadAssistantMessage, ThreadUserMessage } from '@assistant-ui/react';
import type { RerankDebugInfo } from '@/types/generated';
import {
  clampChatHistory,
  deriveSessionTitle,
  getMessageCustom,
  getMessageImages,
  INTERRUPTED_STREAM_MESSAGE,
  loadChatSessionsFromStorage,
  persistChatSessions,
  setMessageCustom,
  type RagweldMessageCustom,
} from './chatSessions.ts';
import {
  ChatRequestFailedError,
  ChatStreamEventError,
  toAbortReason,
  type ChatFailedRun,
  type RagweldChatResult,
  type SendRagweldChatArgs,
} from './chatTransport.ts';
import { createFrameCoalescer, type FrameCoalescer, type FrameScheduler } from './frameCoalescer.ts';

/**
 * Owns every chat answer while it streams, independently of the views that show it.
 *
 * An answer used to live inside the ChatInterface that sent it: leaving the Chat tab unmounted
 * that component, aborted the request and left the thread saying "interrupted". The Chat tab and
 * the docked Chat are now two views of one controller. The controller runs the request, holds the
 * accumulating text, publishes it at most once per animation frame, and writes the finished answer
 * into the stored thread exactly once, whether or not any view is mounted when it lands. A view
 * subscribes to the turn of the conversation it shows; mounting a view never starts a stream.
 *
 * Two subscriptions, so a thread only pays for what changes:
 * - `subscribe` + `runningAssistantId(conversationId)`: changes on start and end only, which is
 *   all the ChatInterface shell needs (Send vs Stop);
 * - `subscribeContent(assistantId)` + `liveContent(assistantId)`: the answer's text, reasoning and
 *   waiting stage, at most once per frame, read by the one streaming message.
 *
 * Only relative imports, so `node --test` can drive it against a real local server
 * (web/tests/unit/chat_stream_controller.test.ts).
 */

export type ChatTurnOutcome = 'ok' | 'error' | 'timeout' | 'cancelled' | 'interrupted';

/** Why a running turn is stopped. */
export type ChatTurnAbortReason = 'user_cancel' | 'timeout' | 'superseded' | 'deleted';

export type LiveTurnContent = {
  readonly assistantId: string;
  readonly text: string;
  readonly thinking: string;
  readonly waitStage: 'searching' | 'generating';
  readonly waitSourcesCount?: number;
  readonly running: boolean;
  /** Set once the turn has settled: the assistant message exactly as it was written to storage. */
  readonly final: ThreadAssistantMessage | null;
};

export type ChatTurnSettled = {
  /** The conversation id the turn was sent under. */
  clientConversationId: string;
  /** The conversation id the server answered under (normally the same). */
  conversationId: string;
  assistantId: string;
  outcome: ChatTurnOutcome;
  result: RagweldChatResult | null;
};

/** The transport arguments a view decides (everything but the callbacks and the signal). */
export type ChatTurnRequest = Pick<
  SendRagweldChatArgs,
  | 'api'
  | 'includeGraph'
  | 'includeSparse'
  | 'includeVector'
  | 'modelOverride'
  | 'recallIntensityOverride'
  | 'requestSources'
  | 'topK'
  | 'webEnabled'
>;

export type StartChatTurn = {
  conversationId: string;
  /** The running placeholder, already in the stored thread (the view persisted it). */
  assistant: ThreadAssistantMessage;
  userMessage: ThreadUserMessage;
  request: ChatTurnRequest;
  timeoutMs: number;
  chatHistoryMax: number;
  maxSessions: number;
};

export type ChatJourney = {
  name: 'chat_send_to_status' | 'chat_send_to_first_text' | 'chat_send_to_done';
  durationMs: number;
  model: string;
  outcome: ChatTurnOutcome;
};

export type ChatStreamControllerDeps = {
  send: (args: SendRagweldChatArgs) => Promise<RagweldChatResult>;
  /** Where the threads live (localStorage in the app). */
  storage: () => Storage | null;
  /** Writer id on this controller's storage broadcasts, so every view reloads the result. */
  writerId: string;
  scheduler: FrameScheduler;
  /** Wall clock for message timestamps. */
  now: () => number;
  /** Monotonic clock for journey durations. */
  monotonic: () => number;
  setTimer: (callback: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
  toast?: (message: string, kind: 'error' | 'info' | 'success') => void;
  /** `tribrid:chat:run-complete` for the Routing Trace panel. */
  runComplete?: (detail: { run_id?: string; started_at_ms?: number; ended_at_ms?: number }) => void;
  journey?: (journey: ChatJourney) => void;
  /** Whether any turn is streaming (layout-shift phase). */
  streaming?: (active: boolean) => void;
  /** How many settled turns keep their final snapshot for views that have not reloaded yet. */
  retainSettled?: number;
};

type Turn = {
  conversationId: string;
  assistantId: string;
  assistant: ThreadAssistantMessage;
  userMessage: ThreadUserMessage;
  input: StartChatTurn;
  abort: AbortController;
  abortReason: ChatTurnAbortReason | null;
  timeout: unknown;
  text: string;
  thinking: string;
  waitStage: 'searching' | 'generating';
  waitSourcesCount?: number;
  startedAt: number;
  statusAt: number | null;
  firstTextAt: number | null;
  coalescer: FrameCoalescer;
  settled: boolean;
};

export type ChatStreamController = {
  start: (input: StartChatTurn) => void;
  cancel: (conversationId: string, reason: ChatTurnAbortReason) => boolean;
  runningAssistantId: (conversationId: string) => string | null;
  isRunning: (assistantId: string) => boolean;
  hasRunning: () => boolean;
  liveContent: (assistantId: string) => LiveTurnContent | null;
  subscribe: (listener: () => void) => () => void;
  subscribeContent: (assistantId: string, listener: () => void) => () => void;
  onSettled: (listener: (event: ChatTurnSettled) => void) => () => void;
};

const CANCELLED_TEXT = 'Error: Chat request was cancelled.';
const TIMEOUT_TEXT = 'Error: Chat timed out before completion.';

function statusOf(type: 'complete' | 'error' | 'running', errorText?: string): MessageStatus {
  if (type === 'running') return { type: 'running' };
  if (type === 'error') return { type: 'incomplete', reason: 'error', error: errorText || 'Chat failed' };
  return { type: 'complete', reason: 'stop' };
}

/** The identity a failed send shares with a successful one (run id, timing, trace headers). */
function failedRunCustom(run: ChatFailedRun | null): Partial<RagweldMessageCustom> {
  if (!run) return {};
  return {
    correlationId: run.headers.correlationId,
    endedAtMs: run.endedAtMs,
    eventId: run.runId,
    rootSpanId: run.headers.rootSpanId,
    runId: run.runId,
    startedAtMs: run.startedAtMs,
    traceId: run.headers.traceId,
  };
}

/** The toast a finished answer's reranker outcome deserves, if any. */
export function rerankOutcomeToast(rerank: RerankDebugInfo | null | undefined): { message: string; kind: 'error' | 'info' } | null {
  if (!rerank || !rerank.enabled) return null;
  const mode = String(rerank.mode || 'rerank').trim() || 'rerank';
  const skipped = String(rerank.skipped_reason || '').trim();
  const errMsg = String(rerank.error_message || '').trim();
  const errRaw = String(rerank.error || '').trim();
  const traceId = String(rerank.debug_trace_id || '').trim();
  if (rerank.ok === false) {
    const message = errMsg || errRaw || 'Unknown error';
    return { message: `Rerank failed (${mode}): ${message}${traceId ? ` (trace ${traceId})` : ''}`, kind: 'error' };
  }
  if (!rerank.applied && skipped) {
    const lowered = skipped.toLowerCase();
    if (lowered === 'no_candidates' || lowered === 'empty_query') return null;
    return { message: `Rerank skipped (${mode}): ${skipped}`, kind: 'info' };
  }
  return null;
}

export function createChatStreamController(deps: ChatStreamControllerDeps): ChatStreamController {
  const retain = Math.max(1, deps.retainSettled ?? 16);
  /** Running turns by conversation id. */
  const running = new Map<string, Turn>();
  /** Current content snapshot per assistant id (running and recently settled turns). */
  const content = new Map<string, LiveTurnContent>();
  const settledOrder: string[] = [];
  const listeners = new Set<() => void>();
  const contentListeners = new Map<string, Set<() => void>>();
  const settledListeners = new Set<(event: ChatTurnSettled) => void>();

  const notify = () => {
    for (const listener of [...listeners]) listener();
  };
  const notifyContent = (assistantId: string) => {
    const set = contentListeners.get(assistantId);
    if (!set) return;
    for (const listener of [...set]) listener();
  };

  const publish = (turn: Turn) => {
    const previous = content.get(turn.assistantId);
    if (
      previous &&
      previous.running &&
      previous.text === turn.text &&
      previous.thinking === turn.thinking &&
      previous.waitStage === turn.waitStage &&
      previous.waitSourcesCount === turn.waitSourcesCount
    ) {
      return;
    }
    content.set(turn.assistantId, {
      assistantId: turn.assistantId,
      text: turn.text,
      thinking: turn.thinking,
      waitStage: turn.waitStage,
      waitSourcesCount: turn.waitSourcesCount,
      running: true,
      final: null,
    });
    notifyContent(turn.assistantId);
  };

  /** Merge the settled answer into the stored thread. Never writes a view's snapshot back. */
  const commit = (turn: Turn, finalMessage: ThreadAssistantMessage, conversationId: string): void => {
    const storage = deps.storage();
    if (!storage) return;
    const { chatHistoryMax, maxSessions } = turn.input;
    let loaded;
    try {
      loaded = loadChatSessionsFromStorage(storage, chatHistoryMax);
    } catch {
      return;
    }
    const sessions = loaded.sessions.slice();
    const index = sessions.findIndex((session) => String(session.conversation_id || '').trim() === turn.conversationId);
    // The conversation was deleted while it streamed: nothing to land the answer in.
    if (index < 0) return;
    const session = sessions[index];
    const messages = session.messages.slice();
    const at = messages.findIndex((message) => message.id === turn.assistantId);
    if (at >= 0) {
      messages[at] = finalMessage;
    } else {
      // The view's send-time write had not reached storage; land the whole turn.
      if (!messages.some((message) => message.id === turn.userMessage.id)) messages.push(turn.userMessage);
      messages.push(finalMessage);
    }
    const nextMessages = clampChatHistory(messages, chatHistoryMax);
    sessions[index] = {
      ...session,
      conversation_id: conversationId,
      messages: nextMessages,
      title: session.title && session.title !== 'New chat' ? session.title : deriveSessionTitle(nextMessages),
      updated_at: deps.now(),
    };
    sessions.sort((a, b) => Number(b.updated_at || 0) - Number(a.updated_at || 0));
    const activeId = String(loaded.activeSession?.conversation_id || '').trim();
    const nextActive = activeId === turn.conversationId ? conversationId : activeId || conversationId;
    try {
      persistChatSessions(storage, sessions.slice(0, maxSessions), nextActive, { writerId: deps.writerId });
    } catch {
      // storage full or unavailable: the views still show the settled snapshot
    }
  };

  const settle = (
    turn: Turn,
    outcome: ChatTurnOutcome,
    finalMessage: ThreadAssistantMessage | null,
    result: RagweldChatResult | null,
  ) => {
    if (turn.settled) return;
    turn.settled = true;
    turn.coalescer.cancel();
    deps.clearTimer(turn.timeout);
    if (running.get(turn.conversationId) === turn) running.delete(turn.conversationId);
    const conversationId = result?.conversationId || turn.conversationId;

    // Views learn the outcome first (a renamed conversation must be followed before the reload).
    const event: ChatTurnSettled = {
      clientConversationId: turn.conversationId,
      conversationId,
      assistantId: turn.assistantId,
      outcome,
      result,
    };
    for (const listener of [...settledListeners]) listener(event);

    if (finalMessage) {
      content.set(turn.assistantId, {
        assistantId: turn.assistantId,
        text: turn.text,
        thinking: turn.thinking,
        waitStage: turn.waitStage,
        waitSourcesCount: turn.waitSourcesCount,
        running: false,
        final: finalMessage,
      });
      settledOrder.push(turn.assistantId);
      while (settledOrder.length > retain) content.delete(settledOrder.shift()!);
    } else {
      content.delete(turn.assistantId);
    }
    notifyContent(turn.assistantId);
    notify();
    deps.streaming?.(running.size > 0);

    if (finalMessage) commit(turn, finalMessage, conversationId);

    const model = String(turn.input.request.modelOverride || '').trim() || 'default';
    const end = deps.monotonic();
    if (turn.statusAt !== null) {
      deps.journey?.({ name: 'chat_send_to_status', durationMs: turn.statusAt - turn.startedAt, model, outcome });
    }
    if (turn.firstTextAt !== null) {
      deps.journey?.({ name: 'chat_send_to_first_text', durationMs: turn.firstTextAt - turn.startedAt, model, outcome });
    }
    deps.journey?.({ name: 'chat_send_to_done', durationMs: end - turn.startedAt, model, outcome });
  };

  const finishOk = (turn: Turn, result: RagweldChatResult) => {
    const attachedImageCount = getMessageImages(turn.userMessage).length;
    const custom: RagweldMessageCustom = {
      attachedImageCount: attachedImageCount > 0 ? attachedImageCount : undefined,
      confidence: typeof result.debug?.confidence === 'number' ? result.debug.confidence : undefined,
      correlationId: result.headers.correlationId,
      debug: result.debug,
      endedAtMs: result.endedAtMs,
      eventId: result.runId,
      providerResponseId: result.providerResponseId ?? null,
      rootSpanId: result.headers.rootSpanId,
      runId: result.runId,
      sources: result.sources,
      startedAtMs: result.startedAtMs,
      thinking: turn.thinking || undefined,
      traceId: result.headers.traceId,
      webGrounding: result.webGrounding,
    };
    turn.text = result.text;
    const finalMessage = setMessageCustom(
      {
        ...turn.assistant,
        content: result.text ? [{ type: 'text', text: result.text }] : [],
        status: statusOf('complete'),
      },
      custom,
    );
    settle(turn, 'ok', finalMessage, result);
    deps.runComplete?.({ run_id: result.runId, started_at_ms: result.startedAtMs, ended_at_ms: result.endedAtMs });
    const toast = rerankOutcomeToast(result.debug?.rerank);
    if (toast) deps.toast?.(toast.message, toast.kind);
  };

  const finishError = (turn: Turn, error: unknown) => {
    const reason = turn.abortReason ?? (toAbortReason(error, turn.abort.signal) as ChatTurnAbortReason | null);
    if (reason) {
      if (reason === 'deleted') {
        settle(turn, 'cancelled', null, null);
        return;
      }
      if (reason === 'superseded') {
        // A newer turn in the same conversation owns the thread; keep what arrived, marked
        // interrupted, exactly as a reload would reconcile it.
        const interrupted = setMessageCustom(
          {
            ...turn.assistant,
            content: turn.text ? [{ type: 'text', text: turn.text }] : [],
            status: { type: 'incomplete', reason: 'error', error: INTERRUPTED_STREAM_MESSAGE },
          },
          { ...getMessageCustom(turn.assistant) },
        );
        settle(turn, 'interrupted', interrupted, null);
        return;
      }
      const text = reason === 'timeout' ? TIMEOUT_TEXT : CANCELLED_TEXT;
      const aborted = setMessageCustom(
        { ...turn.assistant, content: [{ type: 'text', text }], status: statusOf('error', text) },
        { ...getMessageCustom(turn.assistant), thinking: turn.thinking || undefined },
      );
      settle(turn, reason === 'timeout' ? 'timeout' : 'cancelled', aborted, null);
      if (reason === 'timeout') deps.toast?.('Chat timed out before completion.', 'error');
      return;
    }

    // A failure the stream reported after the server had started a run carries that run; it is
    // published exactly like a success so the Routing Trace panel follows it.
    const failedRun = error instanceof ChatRequestFailedError || error instanceof ChatStreamEventError ? error.run : null;
    const runPatch = failedRunCustom(failedRun);
    if (error instanceof ChatRequestFailedError && error.detail) {
      const structured = { ...error.detail, http_status: error.status };
      const summary = error.detail.message || error.detail.code;
      const failed = setMessageCustom(
        { ...turn.assistant, content: [], status: statusOf('error', summary) },
        { ...getMessageCustom(turn.assistant), ...runPatch, structuredError: structured },
      );
      settle(turn, 'error', failed, null);
      if (failedRun) deps.runComplete?.({ run_id: failedRun.runId, started_at_ms: failedRun.startedAtMs, ended_at_ms: failedRun.endedAtMs });
      deps.toast?.(summary, 'error');
      return;
    }
    const message = error instanceof Error ? error.message : 'Failed to get response';
    const errorText = `Error: ${message}`;
    const failed = setMessageCustom(
      { ...turn.assistant, content: [{ type: 'text', text: errorText }], status: statusOf('error', errorText) },
      { ...getMessageCustom(turn.assistant), ...runPatch },
    );
    settle(turn, 'error', failed, null);
    if (failedRun) deps.runComplete?.({ run_id: failedRun.runId, started_at_ms: failedRun.startedAtMs, ended_at_ms: failedRun.endedAtMs });
    deps.toast?.(message, 'error');
  };

  const abortTurn = (turn: Turn, reason: ChatTurnAbortReason) => {
    if (turn.settled) return;
    turn.abortReason = reason;
    try {
      turn.abort.abort(reason);
    } catch {
      // ignore abort races
    }
  };

  const start = (input: StartChatTurn) => {
    const previous = running.get(input.conversationId);
    if (previous) abortTurn(previous, 'superseded');

    const abort = new AbortController();
    const turn: Turn = {
      conversationId: input.conversationId,
      assistantId: input.assistant.id,
      assistant: input.assistant,
      userMessage: input.userMessage,
      input,
      abort,
      abortReason: null,
      timeout: null,
      text: '',
      thinking: '',
      waitStage: getMessageCustom(input.assistant).waitStage ?? 'searching',
      startedAt: deps.monotonic(),
      statusAt: null,
      firstTextAt: null,
      coalescer: createFrameCoalescer(() => publish(turn), { scheduler: deps.scheduler }),
      settled: false,
    };
    turn.timeout = deps.setTimer(() => abortTurn(turn, 'timeout'), input.timeoutMs);
    running.set(input.conversationId, turn);
    publish(turn);
    notify();
    deps.streaming?.(true);

    void deps
      .send({
        ...input.request,
        conversationId: input.conversationId,
        message: input.userMessage,
        signal: abort.signal,
        streamPreferred: true,
        onStatus: (status) => {
          if (turn.settled) return;
          if (turn.statusAt === null) turn.statusAt = deps.monotonic();
          turn.waitStage = status.stage;
          turn.waitSourcesCount = status.sourcesCount;
          turn.coalescer.schedule();
        },
        onThinkingDelta: (delta) => {
          if (turn.settled) return;
          turn.thinking += delta;
          turn.coalescer.schedule();
        },
        onTextDelta: (delta) => {
          if (turn.settled) return;
          if (turn.firstTextAt === null) turn.firstTextAt = deps.monotonic();
          turn.text += delta;
          turn.coalescer.schedule();
        },
      })
      .then(
        (result) => {
          if (turn.settled) return;
          if (turn.abortReason) {
            finishError(turn, null);
            return;
          }
          finishOk(turn, result);
        },
        (error) => {
          if (turn.settled) return;
          finishError(turn, error);
        },
      );
  };

  return {
    start,
    cancel(conversationId, reason) {
      const turn = running.get(conversationId);
      if (!turn) return false;
      abortTurn(turn, reason);
      return true;
    },
    runningAssistantId: (conversationId) => running.get(conversationId)?.assistantId ?? null,
    isRunning: (assistantId) => {
      for (const turn of running.values()) if (turn.assistantId === assistantId) return true;
      return false;
    },
    hasRunning: () => running.size > 0,
    liveContent: (assistantId) => content.get(assistantId) ?? null,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    subscribeContent(assistantId, listener) {
      let set = contentListeners.get(assistantId);
      if (!set) {
        set = new Set();
        contentListeners.set(assistantId, set);
      }
      set.add(listener);
      return () => {
        const current = contentListeners.get(assistantId);
        if (!current) return;
        current.delete(listener);
        if (!current.size) contentListeners.delete(assistantId);
      };
    },
    onSettled(listener) {
      settledListeners.add(listener);
      return () => settledListeners.delete(listener);
    },
  };
}
