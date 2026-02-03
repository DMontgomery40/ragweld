import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ChatSubtabs } from '@/components/Chat/ChatSubtabs';
import { ChatInterface } from '@/components/Chat/ChatInterface';
import { ChatSettings2 } from '@/components/Chat/ChatSettings2';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useAPI, useConfig } from '@/hooks';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import { useRepoStore } from '@/stores/useRepoStore';
import type { Trace, TracesLatestResponse } from '@/types/generated';

// React-native Chat tab with UI and Settings subtabs
export default function ChatTab() {
  const { api } = useAPI();
  const { config } = useConfig();
  const { activeRepo } = useRepoStore();
  const [activeSubtab, setActiveSubtab] = useState<'ui' | 'settings'>('ui');
  const [traceOpen, setTraceOpen] = useState(false);

  const traceInitRef = useRef(false);
  const terminalRef = useRef<LiveTerminalHandle>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  const [logService, setLogService] = useState<'all' | 'api' | 'postgres' | 'neo4j'>('all');
  const [lokiStatus, setLokiStatus] = useState<{ reachable: boolean; status: string; url?: string } | null>(null);

  const chatShowTraceDefault = Boolean(config?.ui?.chat_show_trace ?? 1);

  useEffect(() => {
    // Apply config default once (do not override manual toggles).
    if (!traceInitRef.current && config) {
      traceInitRef.current = true;
      setTraceOpen(chatShowTraceDefault);
    }
  }, [chatShowTraceDefault, config]);

  const loadTrace = useCallback(
    async (opts?: { runId?: string | null }) => {
      const runId = (opts?.runId || selectedRunId || '').trim();
      const qs = new URLSearchParams();
      if (runId) qs.set('run_id', runId);
      else if (activeRepo) qs.set('repo', activeRepo);

      setTraceLoading(true);
      setTraceError(null);
      try {
        const r = await fetch(api(`traces/latest${qs.toString() ? `?${qs.toString()}` : ''}`));
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        const d = (await r.json()) as TracesLatestResponse;
        setSelectedRunId((d.run_id || runId || null) as string | null);
        setTrace((d.trace || null) as Trace | null);
      } catch (e) {
        setTrace(null);
        setTraceError(e instanceof Error ? e.message : String(e));
      } finally {
        setTraceLoading(false);
      }
    },
    [activeRepo, api, selectedRunId]
  );

  const refreshLokiStatus = useCallback(async () => {
    try {
      const r = await fetch(api('loki/status'));
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      const d = (await r.json()) as { reachable: boolean; status: string; url?: string };
      setLokiStatus(d);
    } catch (e) {
      setLokiStatus({
        reachable: false,
        status: e instanceof Error ? e.message : String(e),
      });
    }
  }, [api]);

  // Listen for "View trace & logs" clicks from ChatInterface
  useEffect(() => {
    const onOpen = (ev: Event) => {
      const detail = (ev as CustomEvent).detail || {};
      const runId = typeof detail.run_id === 'string' ? detail.run_id : null;
      setActiveSubtab('ui');
      setSelectedRunId(runId);
      setTraceOpen(true);
      // Load immediately (uses run_id if present)
      void loadTrace({ runId });
    };
    window.addEventListener('tribrid:chat:open-trace', onOpen as EventListener);
    return () => window.removeEventListener('tribrid:chat:open-trace', onOpen as EventListener);
  }, [loadTrace]);

  // When a chat run completes, refresh the trace panel if open.
  useEffect(() => {
    const onComplete = (ev: Event) => {
      if (!traceOpen) return;
      const detail = (ev as CustomEvent).detail || {};
      const runId = typeof detail.run_id === 'string' ? detail.run_id : null;
      void loadTrace({ runId });
    };
    window.addEventListener('tribrid:chat:run-complete', onComplete as EventListener);
    return () => window.removeEventListener('tribrid:chat:run-complete', onComplete as EventListener);
  }, [loadTrace, traceOpen]);

  // Load trace when panel opens (or when selection changes while open)
  useEffect(() => {
    if (!traceOpen) return;
    void loadTrace();
    void refreshLokiStatus();
  }, [loadTrace, refreshLokiStatus, traceOpen]);

  const lokiQuery = useMemo(() => {
    switch (logService) {
      case 'api':
        return '{compose_service="api"}';
      case 'postgres':
        return '{compose_service="postgres"}';
      case 'neo4j':
        return '{compose_service="neo4j"}';
      case 'all':
      default:
        return '{compose_service=~"api|postgres|neo4j"}';
    }
  }, [logService]);

  const connectLogs = useCallback(() => {
    if (!traceOpen) return;
    const t = trace;
    if (!t) return;

    const startMs = Math.max(0, Number(t.started_at_ms || 0) - 1500);
    const endMs = typeof t.ended_at_ms === 'number' ? Number(t.ended_at_ms) + 2000 : undefined;

    terminalRef.current?.setTitle(
      `Chat logs (${logService === 'all' ? 'api|postgres|neo4j' : logService})${lokiStatus?.reachable === false ? ' — Loki unreachable' : ''}`
    );
    terminalRef.current?.setContent([`LogQL: ${lokiQuery}`, `time: ${startMs}${endMs ? ` → ${endMs}` : ' → now'}`, '---']);

    const qs = new URLSearchParams();
    qs.set('query', lokiQuery);
    qs.set('start_ms', String(startMs));
    if (endMs !== undefined) qs.set('end_ms', String(endMs));
    qs.set('limit', '2000');
    qs.set('poll_ms', '1000');

    TerminalService.connectToStream('chat_loki', `loki/tail?${qs.toString()}`, {
      onLine: (line) => terminalRef.current?.appendLine(line),
      onError: (err) => terminalRef.current?.appendLine(`\u001b[31mERROR: ${err}\u001b[0m`),
      onComplete: () => terminalRef.current?.appendLine('\u001b[90m[complete]\u001b[0m'),
    });
  }, [logService, lokiQuery, lokiStatus?.reachable, trace, traceOpen]);

  // Reconnect logs when selection/filter changes
  useEffect(() => {
    if (!traceOpen) return;
    TerminalService.disconnect('chat_loki');
    connectLogs();
    return () => TerminalService.disconnect('chat_loki');
  }, [connectLogs, traceOpen]);

  const formattedTrace = useMemo(() => {
    if (!trace) return '';
    const lines: string[] = [];
    const start = new Date(trace.started_at_ms).toISOString();
    const end = typeof trace.ended_at_ms === 'number' ? new Date(trace.ended_at_ms).toISOString() : '…';
    lines.push(`run_id: ${trace.run_id}`);
    lines.push(`corpus_id: ${trace.corpus_id}`);
    lines.push(`started: ${start}`);
    lines.push(`ended:   ${end}`);
    lines.push('');
    for (const ev of trace.events || []) {
      const ts = new Date(ev.ts).toISOString();
      lines.push(`[${ts}] ${ev.kind}${ev.msg ? ` — ${ev.msg}` : ''}`);
      if (ev.data && Object.keys(ev.data).length) {
        lines.push(JSON.stringify(ev.data, null, 2));
      }
      lines.push('');
    }
    return lines.join('\n');
  }, [trace]);

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
              Routing Trace {trace?.events?.length ? `(${trace.events.length} events)` : ''}
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
              {traceLoading
                ? 'Loading trace...'
                : traceError
                  ? `Trace error: ${traceError}`
                  : trace
                    ? formattedTrace || '(empty trace)'
                    : 'No local trace available yet.'}
            </div>

            {/* Logs (Loki drilldown) */}
            <div style={{ marginTop: '12px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '8px' }}>
                <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--fg)' }}>Logs</div>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                  {lokiStatus
                    ? lokiStatus.reachable
                      ? `Loki: ${lokiStatus.status}${lokiStatus.url ? ` (${lokiStatus.url})` : ''}`
                      : `Loki unreachable (${lokiStatus.status})`
                    : 'Loki: unknown'}
                </div>
                <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <label style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>Filter</label>
                  <select
                    value={logService}
                    onChange={(e) => setLogService(e.target.value as any)}
                    style={{
                      fontSize: '12px',
                      background: 'var(--input-bg)',
                      color: 'var(--fg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      padding: '6px 8px',
                    }}
                  >
                    <option value="all">api + postgres + neo4j</option>
                    <option value="api">api</option>
                    <option value="postgres">postgres (pgvector)</option>
                    <option value="neo4j">neo4j</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => {
                      TerminalService.disconnect('chat_loki');
                      connectLogs();
                    }}
                    style={{
                      fontSize: '12px',
                      background: 'var(--bg-elev2)',
                      color: 'var(--fg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      padding: '6px 10px',
                      cursor: 'pointer',
                    }}
                    title="Reconnect log stream"
                  >
                    Refresh
                  </button>
                </div>
              </div>

              <LiveTerminal
                ref={terminalRef}
                id="chat_loki"
                title="Chat logs (Loki)"
                initialContent={['Open an answer trace to load logs.']}
              />
            </div>
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
              <ChatSettings2 />
            </ErrorBoundary>
          </div>
        </div>
      )}
    </div>
  );
}
