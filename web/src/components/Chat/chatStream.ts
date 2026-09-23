import { useCallback, useSyncExternalStore } from 'react';
import { reportJourney, setRumStreaming } from '@/observability/rum';
import { showToast } from '@/utils/toast';
import { createChatStreamController, type LiveTurnContent } from './chatStreamController';
import { sendRagweldChat } from './chatTransport';
import { browserFrameScheduler } from './frameCoalescer';

/**
 * The page's one chat stream controller (see chatStreamController.ts). Module scope on purpose:
 * it outlives every ChatInterface, so an answer keeps streaming while the Chat tab is closed and
 * the docked Chat shows the same answer instead of starting its own.
 */
export const chatStream = createChatStreamController({
  send: sendRagweldChat,
  storage: () => {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  },
  writerId: 'chat-stream-controller',
  scheduler: browserFrameScheduler(),
  now: () => Date.now(),
  monotonic: () => performance.now(),
  setTimer: (callback, ms) => window.setTimeout(callback, ms),
  clearTimer: (handle) => window.clearTimeout(handle as number),
  toast: (message, kind) => showToast(message, kind),
  runComplete: (detail) => {
    try {
      window.dispatchEvent(new CustomEvent('tribrid:chat:run-complete', { detail }));
    } catch {
      // ignore event dispatch failures
    }
  },
  journey: ({ name, durationMs, model, outcome }) => reportJourney(name, durationMs, { model, outcome }),
  streaming: setRumStreaming,
});

/** The assistant message streaming in `conversationId`, or null. Re-renders on start and end only. */
export function useRunningAssistantId(conversationId: string): string | null {
  return useSyncExternalStore(chatStream.subscribe, () => chatStream.runningAssistantId(conversationId));
}

/** The live text, reasoning and stage of one answer, at most once per frame; null when not live. */
export function useLiveTurnContent(assistantId: string | null): LiveTurnContent | null {
  const subscribe = useCallback(
    (listener: () => void) => (assistantId ? chatStream.subscribeContent(assistantId, listener) : () => {}),
    [assistantId],
  );
  return useSyncExternalStore(subscribe, () => (assistantId ? chatStream.liveContent(assistantId) : null));
}
