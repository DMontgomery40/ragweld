import { useCallback, useState } from 'react';

export type NotificationKind = 'success' | 'error' | 'info';

export interface Notification {
  id: string;
  type: NotificationKind;
  message: string;
}

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
