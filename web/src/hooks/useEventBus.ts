import { useMemo, useCallback } from 'react';

// Typed event definitions for legacy JS → React communication
export interface EventPayloads {
  'config:updated': void;
  'config:loaded': void;
  'repo:changed': { repo: string };
  'repo:loaded': { repo: string };
  'chat:mount': void;
  'chat:unmount': void;
  'reranker:mount': void;
  'reranker:unmount': void;
  'indexing:started': { repo: string };
  'indexing:completed': { repo: string; chunks: number };
  'indexing:failed': { repo: string; error: string };
  'cards:built': { repo: string; count: number };
  'health:changed': { status: string };
  'tab:switched': { tab: string; subtab?: string };
  'theme:changed': { theme: string };
  'react:ready': void;
  'keywords:loaded': { count: number };
  'profiles:loaded': { count: number };
}

export type EventName = keyof EventPayloads;

// Legacy event name mapping for gradual migration
export const LEGACY_EVENT_MAP: Record<string, EventName> = {
  'react-ready': 'react:ready',
  'agro:chat:mount': 'chat:mount',
  'agro:reranker:mount': 'reranker:mount',
  'tab-switched': 'tab:switched',
  'agro-repo-loaded': 'repo:loaded',
  'agro-repo-changed': 'repo:changed',
  'tribrid-corpus-loaded': 'repo:loaded',
  'tribrid-corpus-changed': 'repo:changed',
  'repo-updated': 'repo:changed',
  'config-updated': 'config:updated',
};

/**
 * Hook for application-wide event bus
 * Provides pub/sub mechanism for cross-component communication
 */
export function useEventBus() {
  // Use window as the event target for global events
  const eventBus = useMemo(() => window, []);

  const emit = useCallback((event: string, data?: any) => {
    const customEvent = new CustomEvent(event, { detail: data });
    eventBus.dispatchEvent(customEvent);
  }, [eventBus]);

  const on = useCallback((event: string, handler: (e: CustomEvent) => void) => {
    const listener = handler as EventListener;
    eventBus.addEventListener(event, listener);
    return () => eventBus.removeEventListener(event, listener);
  }, [eventBus]);

  const once = useCallback((event: string, handler: (e: CustomEvent) => void) => {
    /**
     * ---agentspec
     * what: |
     *   Creates a one-time event listener that automatically removes itself after the first invocation.
     *   Takes an event name (string) and handler function (callback) as parameters.
     *   Returns nothing; the handler is invoked once when the event is emitted, then the listener is detached from the eventBus.
     *   The listener is registered via addEventListener and manually removed via removeEventListener after execution.
     *   Handles the cleanup by removing the listener immediately after the handler executes, preventing memory leaks from accumulated listeners.
     *
     * why: |
     *   Provides a convenience wrapper for single-use event subscriptions without requiring manual cleanup code at call sites.
     *   Reduces boilerplate compared to manually adding and removing listeners, improving code readability.
     *   The immediate removal after invocation ensures listeners don't accumulate in memory for events that should only fire once.
     *
     * guardrails:
     *   - DO NOT rely on the returned cleanup function for the once() listener; the listener is already removed after first invocation, so calling the cleanup function is redundant but harmless
     *   - ALWAYS ensure the handler function is synchronous; asynchronous handlers may not complete before the listener is removed
     *   - NOTE: If the same event is emitted multiple times before the first listener fires, only the first emission will trigger the handler; subsequent emissions will have no listener attached
     *   - ASK USER: Confirm whether the eventBus should support listener priority or ordering before adding multiple once() listeners for the same event
     * ---/agentspec
     */
    const listener = (e: Event) => {
      handler(e as CustomEvent);
      eventBus.removeEventListener(event, listener);
    };
    eventBus.addEventListener(event, listener);
    return () => eventBus.removeEventListener(event, listener);
  }, [eventBus]);

  return { emit, on, once };
}
