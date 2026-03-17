import type { ChatSession } from '@/components/Chat/chatSessions';

type ChatHistorySidebarProps = {
  sessions: ChatSession[];
  activeConversationId: string;
  onSelectSession: (session: ChatSession) => void;
  onNewChat: () => void;
  onDeleteChat: () => void;
};

export function ChatHistorySidebar({
  sessions,
  activeConversationId,
  onSelectSession,
  onNewChat,
  onDeleteChat,
}: ChatHistorySidebarProps) {
  return (
    <div
      style={{
        width: '260px',
        borderRight: '1px solid var(--line)',
        background: 'var(--bg-elev1)',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          padding: '12px',
          borderBottom: '1px solid var(--line)',
          fontSize: '12px',
          fontWeight: 700,
          color: 'var(--fg)',
        }}
      >
        Chats
        <span style={{ color: 'var(--fg-muted)', fontWeight: 600 }}> ({sessions.length})</span>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '8px' }}>
        {sessions.map((session, index) => {
          const id = String(session.conversation_id || '').trim();
          const isActive = id && id === activeConversationId;
          const updatedAt = Number(session.updated_at || 0);
          const title = String(session.title || '').trim() || 'New chat';
          const messageCount = Array.isArray(session.messages) ? session.messages.length : 0;

          return (
            <button
              key={`${id || index}`}
              type="button"
              onClick={() => onSelectSession(session)}
              style={{
                width: '100%',
                textAlign: 'left',
                padding: '10px',
                borderRadius: '8px',
                border: `1px solid ${isActive ? 'var(--accent)' : 'var(--line)'}`,
                background: isActive ? 'rgba(0, 255, 136, 0.08)' : 'var(--card-bg)',
                color: 'var(--fg)',
                cursor: 'pointer',
                marginBottom: '8px',
              }}
              title={id ? `conversation_id: ${id}` : undefined}
            >
              <div
                style={{
                  fontSize: '12px',
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {title}
              </div>
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginTop: 4,
                  display: 'flex',
                  gap: 8,
                  flexWrap: 'wrap',
                }}
              >
                <span>{updatedAt ? new Date(updatedAt).toLocaleString() : '—'}</span>
                <span>msgs: {messageCount}</span>
                {isActive ? <span style={{ color: 'var(--accent)', fontWeight: 800 }}>active</span> : null}
              </div>
            </button>
          );
        })}

        {sessions.length === 0 && (
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', padding: '12px' }}>No chats yet</div>
        )}
      </div>

      <div style={{ padding: '8px', borderTop: '1px solid var(--line)', display: 'grid', gap: '8px' }}>
        <button
          type="button"
          onClick={onNewChat}
          style={{
            width: '100%',
            background: 'var(--bg-elev2)',
            color: 'var(--accent)',
            border: '1px solid var(--accent)',
            padding: '8px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          New chat
        </button>
        <button
          type="button"
          onClick={onDeleteChat}
          style={{
            width: '100%',
            background: 'var(--bg-elev2)',
            color: 'var(--err)',
            border: '1px solid var(--err)',
            padding: '8px',
            borderRadius: '6px',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
          }}
        >
          Delete chat
        </button>
      </div>
    </div>
  );
}
