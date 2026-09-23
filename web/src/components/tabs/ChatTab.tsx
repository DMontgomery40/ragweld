import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { TraceExternalLinks } from '@/components/Observability/TraceExternalLinks';
import { ChatSubtabs } from '@/components/Chat/ChatSubtabs';
import { ChatInterface } from '@/components/Chat/ChatInterface';
import { CHAT_SESSIONS_CHANGED_EVENT, readActiveConversationRunIds } from '@/components/Chat/chatSessions';
import { ChatSettings } from '@/components/Chat/ChatSettings';
import {
  CHAT_WORKBENCH_MIN_PX,
  DEFAULT_CHAT_PANE_LAYOUT,
  chatWorkbenchHeightForKey,
  chatWorkbenchMaxHeight,
  normalizeChatWorkbenchHeight,
  readChatPaneLayout,
  resolveChatWorkbenchHeight,
  writeChatPaneLayout,
  type ChatPaneLayout,
  type ChatPaneSurface,
} from '@/components/Chat/chatPaneLayout';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { useAPI, useConfig, useSubtab } from '@/hooks';
import { LiveTerminal, type LiveTerminalHandle } from '@/components/LiveTerminal/LiveTerminal';
import { TerminalService } from '@/services/TerminalService';
import { useRepoStore } from '@/stores/useRepoStore';
import type { Trace, TracesLatestResponse } from '@/types/generated';

// React-native Chat tab with UI and Settings subtabs
type ChatSubtab = 'ui' | 'settings';

// Room kept under the workbench inside the visible pane: the resize handle (16px) plus a small
// gap by default; only the section padding when expanded (the handle is not shown then).
const CHAT_HANDLE_RESERVE_PX = 24;
const CHAT_EXPANDED_RESERVE_PX = 8;

function layoutStorage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

export default function ChatTab() {
  const { api } = useAPI();
  const { config } = useConfig();
  const { activeRepo } = useRepoStore();
  const { activeSubtab, setSubtab } = useSubtab<ChatSubtab>({ routePath: '/chat', defaultSubtab: 'ui' });
  const [traceOpen, setTraceOpen] = useState(false);

  // Workbench layout (GUI-050): per viewer and per surface, UI-only (never config).
  const workbenchFrameRef = useRef<HTMLDivElement>(null);
  const workbenchId = `chat-workbench-${useId().replace(/:/g, '')}`;
  const [paneSurface, setPaneSurface] = useState<ChatPaneSurface | null>(null);
  const [paneLayout, setPaneLayout] = useState<ChatPaneLayout>(DEFAULT_CHAT_PANE_LAYOUT);
  const [paneAvailablePx, setPaneAvailablePx] = useState<number | null>(null);
  const [resizing, setResizing] = useState(false);
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);

  const traceInitRef = useRef(false);
  const terminalRef = useRef<LiveTerminalHandle>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);

  const [logService, setLogService] = useState<'all' | 'api' | 'postgres' | 'neo4j'>('all');
  const [lokiStatus, setLokiStatus] = useState<{ reachable: boolean; status: string; url?: string } | null>(null);

  const chatShowTraceDefault = config?.ui?.chat_show_trace ?? true;
  const traceRouteSummary = trace?.route_summary ?? null;
  const traceDurationMs =
    trace?.ended_at_ms != null && trace?.started_at_ms != null
      ? Math.max(0, trace.ended_at_ms - trace.started_at_ms)
      : null;

  // Which surface this Chat tab is (the main pane or the Dock) decides its layout key, so the
  // docked chat keeps its own Expand/height choice.
  useLayoutEffect(() => {
    const frame = workbenchFrameRef.current;
    if (!frame) return;
    const docked =
      frame.closest('.dock-native') !== null || new URLSearchParams(window.location.search).get('dock') === '1';
    const surface: ChatPaneSurface = docked ? 'dock' : 'main';
    setPaneSurface(surface);
    setPaneLayout(readChatPaneLayout(layoutStorage(), surface));
  }, []);

  // The workbench is sized to the pane it lives in: the height left in the tab's scroll
  // container below the subtab bar, re-measured whenever that container resizes.
  useLayoutEffect(() => {
    if (activeSubtab !== 'ui') return;
    const frame = workbenchFrameRef.current;
    const scroller = frame?.closest('.tab-content') as HTMLElement | null;
    if (!frame || !scroller) return;
    const reserve = paneLayout.expanded ? CHAT_EXPANDED_RESERVE_PX : CHAT_HANDLE_RESERVE_PX;
    const measure = () => {
      const section = frame.firstElementChild as HTMLElement | null;
      if (!section || frame.offsetParent === null) return;
      const sectionStyle = getComputedStyle(section);
      const sectionBorderY = parseFloat(sectionStyle.borderTopWidth) + parseFloat(sectionStyle.borderBottomWidth);
      const offset = frame.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
      // Capped by the window so a container that grows with its content can never feed back.
      const paneHeight = Math.min(scroller.clientHeight, window.innerHeight);
      setPaneAvailablePx(Math.floor(paneHeight - offset - sectionBorderY - reserve));
    };
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(scroller);
    const subtabBar = scroller.querySelector(':scope > .subtab-bar');
    if (subtabBar) observer?.observe(subtabBar);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [activeSubtab, paneLayout.expanded]);

  const updatePaneLayout = useCallback(
    (next: ChatPaneLayout) => {
      setPaneLayout(next);
      if (paneSurface) writeChatPaneLayout(layoutStorage(), paneSurface, next);
    },
    [paneSurface]
  );

  const workbenchHeight = resolveChatWorkbenchHeight(paneLayout, paneAvailablePx);
  const workbenchMaxHeight = chatWorkbenchMaxHeight(paneAvailablePx);

  const toggleExpanded = useCallback(() => {
    const next = { ...paneLayout, expanded: !paneLayout.expanded };
    updatePaneLayout(next);
    if (next.expanded) {
      // The conversation takes the pane; the diagnostics fold away below it.
      setTraceOpen(false);
      const scroller = workbenchFrameRef.current?.closest('.tab-content') as HTMLElement | null;
      scroller?.scrollTo({ top: 0 });
    }
  }, [paneLayout, updatePaneLayout]);

  const onResizeKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const next = chatWorkbenchHeightForKey(event.key, workbenchHeight, paneAvailablePx);
      if (!next) return;
      event.preventDefault();
      updatePaneLayout({ ...paneLayout, height: next.height });
    },
    [paneAvailablePx, paneLayout, updatePaneLayout, workbenchHeight]
  );

  const onResizePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
      dragRef.current = { startY: event.clientY, startHeight: workbenchHeight };
      setResizing(true);
    },
    [workbenchHeight]
  );

  const onResizePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      const height = normalizeChatWorkbenchHeight(drag.startHeight + event.clientY - drag.startY, paneAvailablePx);
      // Live while dragging; persisted once, when the drag ends.
      setPaneLayout((prev) => (prev.height === height ? prev : { ...prev, height }));
    },
    [paneAvailablePx]
  );

  const onResizePointerEnd = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const drag = dragRef.current;
      if (!drag) return;
      dragRef.current = null;
      setResizing(false);
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      // A cancelled pointer can report stale coordinates: keep the last live height instead.
      const height =
        event.type === 'pointercancel'
          ? paneLayout.height
          : normalizeChatWorkbenchHeight(drag.startHeight + event.clientY - drag.startY, paneAvailablePx);
      updatePaneLayout({ ...paneLayout, height });
    },
    [paneAvailablePx, paneLayout, updatePaneLayout]
  );

  useEffect(() => {
    // Apply config default once (do not override manual toggles). An expanded workbench keeps
    // Routing Trace folded: the operator asked for the conversation to have the pane.
    if (!traceInitRef.current && config && paneSurface) {
      traceInitRef.current = true;
      setTraceOpen(chatShowTraceDefault && !paneLayout.expanded);
    }
  }, [chatShowTraceDefault, config, paneLayout.expanded, paneSurface]);

  const loadTrace = useCallback(
    async (opts?: { runId?: string | null }) => {
      // An explicit null asks for the corpus's latest run; only an omitted option falls back to
      // the remembered selection. `null || selectedRunId` used to pin the panel to the previous
      // run whenever a caller had no run id to offer.
      const runId = (opts && opts.runId !== undefined ? opts.runId || '' : selectedRunId || '').trim();
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

  // The runs THIS conversation produced, so the panel can say when what it is showing came
  // from somewhere else on this corpus (an MCP probe, a Retrieval-tab search): the fallback
  // query asks for the corpus's latest run, not the conversation's (S37).
  //
  // Derived from the stored thread rather than from what this tab happened to witness. A run
  // id collected only from `open-trace`/`run-complete` belongs to the tab's lifetime: after a
  // reload it was empty, so the conversation's own run was labelled foreign, and switching
  // conversations left the previous one's run unlabelled. It is a set, not the last run,
  // because "View trace" on an older answer opens a run this conversation still produced.
  const readConversationRunIds = useCallback((): Set<string> => {
    try {
      return readActiveConversationRunIds(localStorage);
    } catch {
      return new Set<string>();
    }
  }, []);
  const [conversationRunIds, setConversationRunIds] = useState<Set<string>>(readConversationRunIds);

  useEffect(() => {
    const refresh = () => setConversationRunIds(readConversationRunIds());
    // Every write to the stored threads announces itself, so selecting a saved session,
    // restoring one after a reload and finishing a run all land here.
    refresh();
    window.addEventListener(CHAT_SESSIONS_CHANGED_EVENT, refresh);
    return () => window.removeEventListener(CHAT_SESSIONS_CHANGED_EVENT, refresh);
  }, [readConversationRunIds]);

  // Listen for "View trace & logs" clicks from ChatInterface
  useEffect(() => {
    const onOpen = (ev: Event) => {
      const detail = (ev as CustomEvent).detail || {};
      const runId = typeof detail.run_id === 'string' ? detail.run_id : null;
      setSubtab('ui', { replace: true });
      setSelectedRunId(runId);
      // Asking for a run's trace brings Routing Trace back into the pane.
      if (paneLayout.expanded) updatePaneLayout({ ...paneLayout, expanded: false });
      setTraceOpen(true);
      // Load immediately (uses run_id if present)
      void loadTrace({ runId });
    };
    window.addEventListener('tribrid:chat:open-trace', onOpen as EventListener);
    return () => window.removeEventListener('tribrid:chat:open-trace', onOpen as EventListener);
  }, [loadTrace, paneLayout, updatePaneLayout]);

  // When a chat run completes (answered or failed), the panel follows it: the run id is
  // remembered even while the panel is closed, so opening it later shows this conversation's
  // latest run rather than whichever run was selected before (2026-09-02 drive, S10).
  useEffect(() => {
    const onComplete = (ev: Event) => {
      const detail = (ev as CustomEvent).detail || {};
      const runId = typeof detail.run_id === 'string' ? detail.run_id : null;
      setSelectedRunId(runId);
      if (!traceOpen) return;
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
        return '{ragweld_service="api"}';
      case 'postgres':
        return '{ragweld_service="postgres"}';
      case 'neo4j':
        return '{ragweld_service="neo4j"}';
      case 'all':
      default:
        return '{ragweld_service=~"api|postgres|neo4j"}';
    }
  }, [logService]);

  const connectLogs = useCallback(() => {
    if (!traceOpen) return;
    const t = trace;
    if (!t) return;

    const startMs = Math.max(0, Number(t.started_at_ms || 0) - 1500);
    const endMs = typeof t.ended_at_ms === 'number' ? Number(t.ended_at_ms) + 2000 : undefined;

    terminalRef.current?.setContent([`LogQL: ${lokiQuery}`, `time: ${startMs}${endMs ? ` → ${endMs}` : ' → now'}`, '---']);

    const qs = new URLSearchParams();
    qs.set('query', lokiQuery);
    qs.set('start_ms', String(startMs));
    if (endMs !== undefined) qs.set('end_ms', String(endMs));
    qs.set('limit', '2000');
    qs.set('poll_ms', '1000');

    TerminalService.connectToStream('chat_loki', `loki/tail?${qs.toString()}`, {
      onLine: (line) => terminalRef.current?.appendLine(line),
      // The tail is still open and still resolving Loki: re-read the status so the header
      // stops saying "unreachable" the moment the box frees up, without a page reload.
      onTransient: () => {
        void refreshLokiStatus();
      },
      onError: (err) => terminalRef.current?.appendLine(`\u001b[31mERROR: ${err}\u001b[0m`),
      onComplete: () => terminalRef.current?.appendLine('\u001b[90m[complete]\u001b[0m'),
    });
    // `lokiStatus` is deliberately NOT a dependency. It only ever fed the terminal title,
    // and the title now has its own effect: leaving it here made every reachability flip
    // change this callback's identity, which disconnected and reopened the tail. On a
    // flapping box that restarted the server's two-minute retry budget from zero every
    // time, so the bounded give-up was never reached and each reconnect paid for another
    // candidate resolve.
  }, [logService, lokiQuery, refreshLokiStatus, trace, traceOpen]);

  // The header tracks Loki's reachability; the stream must not.
  useEffect(() => {
    terminalRef.current?.setTitle(
      `Chat logs (${logService === 'all' ? 'api|postgres|neo4j' : logService})${lokiStatus?.reachable === false ? ' — Loki unreachable' : ''}`
    );
  }, [logService, lokiStatus?.reachable]);

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
      <ChatSubtabs activeSubtab={activeSubtab} onSubtabChange={(s) => setSubtab(s as ChatSubtab)} />

      <div
        id="tab-chat-ui"
        className={`section-subtab ${activeSubtab === 'ui' ? 'active' : ''}${paneLayout.expanded ? ' chat-ui--expanded' : ''}`}
      >
        <div ref={workbenchFrameRef} className="chat-workbench-frame">
          <div className="settings-section" style={{ borderLeft: '3px solid var(--link)', padding: 0, margin: 0 }}>
            <ErrorBoundary>
              <ChatInterface
                workbenchId={workbenchId}
                height={workbenchHeight}
                expanded={paneLayout.expanded}
                onToggleExpanded={toggleExpanded}
              />
            </ErrorBoundary>
          </div>
          {paneLayout.expanded ? null : (
            <div
              role="separator"
              aria-orientation="horizontal"
              aria-label="Resize chat workbench"
              aria-controls={workbenchId}
              aria-valuenow={workbenchHeight}
              aria-valuemin={CHAT_WORKBENCH_MIN_PX}
              aria-valuemax={workbenchMaxHeight}
              aria-valuetext={`${workbenchHeight} pixels tall`}
              tabIndex={0}
              data-testid="chat-resize-handle"
              className={`chat-resize-handle${resizing ? ' is-dragging' : ''}`}
              onKeyDown={onResizeKeyDown}
              onPointerDown={onResizePointerDown}
              onPointerMove={onResizePointerMove}
              onPointerUp={onResizePointerEnd}
              onPointerCancel={onResizePointerEnd}
            />
          )}
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
            <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--accent-text)', fontSize: '13px' }}>
              Routing Trace {trace?.events?.length ? `(${trace.events.length} events)` : ''}
            </summary>
            {trace && !conversationRunIds.has(String(trace.run_id || '')) ? (
              <div
                data-testid="chat-trace-foreign-run"
                style={{ marginTop: '8px', fontSize: '12px', color: 'var(--fg-muted)' }}
              >
                This is the most recent run on {trace.corpus_id || 'this corpus'}, not an answer from this
                conversation. A search, an MCP probe or another tab can produce it.
              </div>
            ) : null}
            {trace && (
              <div
                style={{
                  marginTop: '10px',
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: '10px',
                }}
              >
                <div style={{ border: '1px solid var(--line)', borderRadius: '4px', padding: '10px', background: 'var(--bg)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Canonical Trace</div>
                  <div style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--fg)' }}>{trace.trace_id || 'n/a'}</div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
                    Correlation: {trace.correlation_id || 'n/a'}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
                    Root span: {trace.root_span_id || 'n/a'}
                  </div>
                </div>
                <div style={{ border: '1px solid var(--line)', borderRadius: '4px', padding: '10px', background: 'var(--bg)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Request Route</div>
                  <div style={{ fontSize: '12px', color: 'var(--fg)' }}>
                    {traceRouteSummary?.method || '—'} {traceRouteSummary?.path || '—'}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
                    {traceRouteSummary?.route_name || 'n/a'}
                    {traceDurationMs != null ? ` · ${traceDurationMs} ms` : ''}
                  </div>
                </div>
                <div style={{ border: '1px solid var(--line)', borderRadius: '4px', padding: '10px', background: 'var(--bg)' }}>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Cost</div>
                  <div style={{ fontSize: '12px', color: 'var(--fg)' }}>
                    {trace.cost_summary?.estimated_cost_usd != null
                      ? `$${Number(trace.cost_summary.estimated_cost_usd).toFixed(6)}`
                      : 'Unavailable'}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
                    {trace.cost_summary?.cost_source || 'unavailable'}
                    {trace.cost_summary?.total_tokens != null ? ` · ${trace.cost_summary.total_tokens} tokens` : ''}
                  </div>
                </div>
              </div>
            )}
            <TraceExternalLinks links={trace?.external_links} traceId={trace?.trace_id} />
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
                <div
                  style={{ fontSize: '11px', color: 'var(--fg-muted)' }}
                  data-testid="chat-loki-status"
                >
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
                    <option value="postgres">postgres</option>
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
              <ChatSettings />
            </ErrorBoundary>
          </div>
        </div>
      )}
    </div>
  );
}
