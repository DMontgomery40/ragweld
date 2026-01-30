import { useCallback, useEffect, useState } from 'react';
import { ChatSubtabs } from '@/components/Chat/ChatSubtabs';
import { ChatInterface, TraceStep } from '@/components/Chat/ChatInterface';
import { ChatSettings } from '@/components/Chat/ChatSettings';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';

// React-native Chat tab with UI and Settings subtabs
export default function ChatTab() {
  const [activeSubtab, setActiveSubtab] = useState<'ui' | 'settings'>('ui');
  const [traceSteps, setTraceSteps] = useState<TraceStep[]>([]);
  const [traceOpen, setTraceOpen] = useState(false);

  const handleTraceUpdate = useCallback((steps: TraceStep[], open: boolean) => {
    setTraceSteps(steps);
    setTraceOpen(open);
  }, []);

  const handleTracePreferenceChange = useCallback((open: boolean) => {
    setTraceOpen(open);
  }, []);

  useEffect(() => {
    if (traceOpen) {
      requestAnimationFrame(() => {
        try {
          (window as any).Trace?.loadLatestTrace?.('chat-trace-output');
        } catch {}
      });
    }
  }, [traceOpen]);

  return (
    <div id="tab-chat" className="tab-content">
      <ChatSubtabs activeSubtab={activeSubtab} onSubtabChange={(s) => setActiveSubtab(s as any)} />

      <div
        id="tab-chat-ui"
        className={`section-subtab ${activeSubtab === 'ui' ? 'active' : ''}`}
      >
        <div className="settings-section" style={{ borderLeft: '3px solid var(--link)', padding: 0 }}>
          <ErrorBoundary>
            <ChatInterface
              traceOpen={traceOpen}
              onTraceUpdate={handleTraceUpdate}
              onTracePreferenceChange={handleTracePreferenceChange}
            />
          </ErrorBoundary>
        </div>

        <div className="settings-section" style={{ padding: '0 12px 12px 12px' }}>
          <details
            id="chat-trace"
            open={traceOpen}
            onToggle={(e) => setTraceOpen((e.target as HTMLDetailsElement).open)}
            style={{
              border: '1px solid var(--line)',
              borderRadius: '6px',
              background: 'var(--bg-elev1)',
              padding: '12px'
            }}
            title="Latest routing trace steps (retrieve, bm25, vector, rrf, hydrate)"
          >
            <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--accent)', fontSize: '13px' }}>
              Routing Trace {traceSteps.length ? `(${traceSteps.length} steps)` : ''}
            </summary>
            <div
              id="chat-trace-output"
              aria-live="polite"
              style={{
                marginTop: '10px',
                fontFamily: 'monospace',
                fontSize: '11px',
                whiteSpace: 'pre-wrap',
                minHeight: '90px',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                padding: '10px',
                background: 'var(--code-bg)'
              }}
            >
              {!traceSteps.length && 'Trace output will load after your next message (enable Show Trace in Chat Settings).'}
            </div>
            {traceSteps.length > 0 && (
              <div style={{ marginTop: '10px', fontSize: '11px', color: 'var(--fg-muted)' }}>
                <strong style={{ color: 'var(--fg)' }}>Recent steps:</strong>
                <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
                  {traceSteps.slice(0, 8).map((step, idx) => (
                    <li key={`${step.step}-${idx}`} style={{ marginBottom: '4px' }}>
                      <span style={{ color: 'var(--accent)' }}>{step.step}</span>
                      {typeof step.duration === 'number' ? ` · ${Math.round(step.duration)}ms` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </details>
        </div>
      </div>

      {activeSubtab === 'settings' && (
        <div
          id="tab-chat-settings"
          className={`section-subtab ${activeSubtab === 'settings' ? 'active' : ''}`}
        >
          <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)', marginTop: '16px' }}>
            <ErrorBoundary>
              <ChatSettings />
            </ErrorBoundary>
          </div>
        </div>
      )}
    </div>
  );
}
