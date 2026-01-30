import { useCallback, useState } from 'react';

export type NotificationKind = 'success' | 'error' | 'info';

export interface Notification {
  id: string;
  type: NotificationKind;
  message: string;
}

/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages a notification queue with add and remove operations.
 *   Accepts notification type (NotificationKind enum) and message string as inputs to the push function.
 *   Returns an object containing the notifications array and removeNotification callback function.
 *   Generates unique IDs using timestamp + random hex suffix to ensure collision-free removal.
 *   Notifications persist in state until explicitly removed via removeNotification(id).
 *
 * why: |
 *   Centralizes notification state management to avoid prop drilling across components.
 *   Timestamp-based ID generation ensures uniqueness without requiring external UUID libraries.
 *   useCallback memoization prevents unnecessary re-renders of dependent components.
 *   Separates concerns: hook manages state, consumers handle UI rendering and auto-dismiss logic.
 *
 * guardrails:
 *   - DO NOT rely on this hook for auto-dismissal; implement timeout logic in consuming components because notifications will accumulate indefinitely without explicit removal
 *   - ALWAYS pair push() calls with removeNotification() cleanup or set timeouts to prevent memory leaks in long-running applications
 *   - NOTE: Random ID generation has theoretical collision risk at high frequency (>1000 notifications/second); consider UUID library for production systems with extreme load
 *   - ASK USER: Confirm whether notifications should auto-dismiss after a duration or if manual removal is the intended behavior before adding timer logic
 * ---/agentspec
 */
export function useNotification() {
  const [notifications, setNotifications] = useState<Notification[]>([]);

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id));
  }, []);

  const push = useCallback((type: NotificationKind, message: string) => {
    const id = `${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
    setNotifications(prev => [...prev, { id, type, message }]);
    return id;
  }, []);

  const success = useCallback((message: string) => push('success', message), [push]);
  const error = useCallback((message: string) => push('error', message), [push]);
  const info = useCallback((message: string) => push('info', message), [push]);

  return {
    notifications,
    removeNotification,
    success,
    error,
    info
  };
}
