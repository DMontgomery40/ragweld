
import type { Notification } from '@/hooks/useNotification';

interface NotificationContainerProps {
  notifications: Notification[];
  onClose: (id: string) => void;
}

export function NotificationContainer({ notifications, onClose }: NotificationContainerProps) {
  if (!notifications || notifications.length === 0) return null;

  const badgeColor = (type: string) => {
    switch (type) {
      case 'success': return 'var(--success)';
      case 'error': return 'var(--err)';
      default: return 'var(--link)';
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        top: '16px',
        right: '16px',
        zIndex: 5000,
        display: 'flex',
        flexDirection: 'column',
        gap: '8px',
        maxWidth: '320px'
      }}
      aria-live="polite"
      aria-atomic="true"
    >
      {notifications.map(note => (
        <div
          key={note.id}
          style={{
            background: 'var(--bg-elev1)',
            border: `1px solid ${badgeColor(note.type)}`,
            borderLeft: `4px solid ${badgeColor(note.type)}`,
            color: 'var(--fg)',
            padding: '10px 12px',
            borderRadius: '6px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '10px'
          }}
          role="status"
        >
          <span style={{ fontSize: '12px', lineHeight: 1.4, wordBreak: 'break-word' }}>
            {note.message}
          </span>
          <button
            onClick={() => onClose(note.id)}
            aria-label="Dismiss notification"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--fg-muted)',
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: '14px',
              lineHeight: 1
            }}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
