import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useAPI } from '@/hooks/useAPI';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import type { IndexRunAccounting, IndexRunSummary } from '@/types/generated';

const TERMINAL_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];
const ACTIVE_DELAY_MS = 10000;
const requests = new Map<string, Promise<IndexRunSummary>>();

// Main, dock, and Dashboard views may show the same run simultaneously. Share
// their bounded HTTP request; leaving one view must not cancel another's read.
function readRun(endpoint: string, reconcile: boolean): Promise<IndexRunSummary> {
  const key = `${reconcile ? 'POST' : 'GET'}:${endpoint}`;
  const existing = requests.get(key);
  if (existing) return existing;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20000);
  const pending = (async () => {
    try {
      const response = await fetch(reconcile ? `${endpoint}/costs/reconcile` : endpoint, {
        method: reconcile ? 'POST' : 'GET', signal: controller.signal,
      });
      if (!response.ok) throw new Error(`Unable to refresh accounting (HTTP ${response.status}).`);
      return await response.json() as IndexRunSummary;
    } catch (cause) {
      if (controller.signal.aborted) throw new Error('Accounting refresh timed out. Retry when the gateway is available.');
      throw cause;
    } finally {
      window.clearTimeout(timeout);
      requests.delete(key);
    }
  })();
  requests.set(key, pending);
  return pending;
}

function money(value: number | null | undefined): string {
  return value == null ? 'Unavailable' : `$${value.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 10 })}`;
}

function accountingState(accounting: IndexRunAccounting | null | undefined): string {
  if (!accounting) return 'Unavailable';
  if (accounting.reconciliation_error) return 'Check failed';
  if (accounting.owner_interrupted) return 'Incomplete · Interrupted';
  const state = accounting.costs?.state ?? 'pending';
  return state.charAt(0).toUpperCase() + state.slice(1);
}

function readableMoney(value: number): string {
  if (value > 0 && value < 0.01) return '<$0.01';
  return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function accountingIsComplete(run: IndexRunSummary | undefined): boolean {
  return run?.accounting?.costs?.state === 'complete'
    && !run.accounting.reconciliation_error
    && !run.accounting.owner_interrupted;
}

/** Render saved accounting only; current configuration cannot price a past run. */
export function IndexCostSummary({ accounting, compact = false, action, refreshError, refreshPaused = false }: {
  accounting: IndexRunAccounting | null | undefined;
  compact?: boolean;
  action?: ReactNode;
  refreshError?: string | null;
  refreshPaused?: boolean;
}) {
  const costs = accounting?.costs;
  const quote = accounting?.estimate;
  const census = Object.values(accounting?.census ?? {});
  const admitted = census.reduce((sum, lane) => sum + lane.started_requests, 0);
  const inflight = census.reduce((sum, lane) => sum + lane.inflight, 0);
  const workers = census.reduce((sum, lane) => sum + lane.active_producers, 0);
  const chunks = accounting?.processed_chunks ?? 0;
  const state = accountingState(accounting);
  const details = (
    <div style={{ display: 'grid', gap: 8, marginTop: 8, fontSize: 12, lineHeight: 1.5, overflowWrap: 'anywhere' }}>
      {!accounting && <div>This run has no saved native accounting.</div>}
      {refreshError && <div>{refreshError}</div>}
      {refreshPaused && <div data-testid="index-cost-refresh-paused">Automatic checks finished. Refresh to check again.</div>}
      {accounting && <>
      {accounting.reconciliation_error && <div role="status">Native accounting could not be refreshed: {accounting.reconciliation_error}</div>}
      {accounting.owner_interrupted && <div data-testid="index-cost-owner-interrupted" role="status">
        The run owner stopped before accounting closed. Automatic checks are bounded; refresh manually to check again.
      </div>}
      <div data-testid="index-cost-estimate">
        <strong>Frozen estimate: {money(quote?.total_usd)}</strong>
        {quote ? <>
          <div>Saved {new Date(quote.captured_at).toLocaleString()}. {quote.detail}</div>
          <div>Embedding {money(quote.embedding_usd)} · Semantic KG {money(quote.semantic_kg_usd)} · Figures {money(quote.figure_description_usd)}</div>
        </> : <div>No pre-run estimate was saved.</div>}
      </div>
      <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '5px 12px', margin: 0 }}>
        <dt>Provider reported</dt><dd style={{ margin: 0 }} data-testid="index-cost-provider">{costs && costs.provider_reported_requests > 0 ? money(costs.provider_reported_usd) : 'Not recorded'}</dd>
        <dt>Gateway calculated</dt><dd style={{ margin: 0 }} data-testid="index-cost-calculated">{costs && costs.gateway_calculated_requests > 0 ? money(costs.gateway_calculated_usd) : 'Not recorded'}</dd>
        <dt>Native logged amount</dt><dd style={{ margin: 0 }} data-testid="index-cost-native">{money(costs?.native_logged_usd)}{costs && state !== 'Complete' ? ' (partial accounting)' : ''}</dd>
        <dt>Request coverage</dt><dd style={{ margin: 0 }}>{costs?.coverage_state ?? 'Pending reconciliation'}</dd>
        <dt>Pricing</dt><dd style={{ margin: 0 }}>{costs?.pricing_state ?? 'Pending reconciliation'}</dd>
      </dl>
      {costs && <div data-testid="index-cost-coverage">
        {costs.matched_gateway_requests} matched requests · {costs.cached_requests} cached · {costs.unmeasured_requests} unmeasured · {costs.missing_requests} missing
        {(costs.unmeasured_requests > 0 || costs.missing_requests > 0) && <div>Missing or unpriced requests prevent a complete cost total.</div>}
      </div>}
      <div>{admitted} admitted requests · {inflight} in flight · {workers} retained workers</div>
      <div data-testid="index-cost-denominator">
        {chunks.toLocaleString()} chunks processed · {(accounting.processed_files ?? 0).toLocaleString()} files · {(accounting.processed_tokens ?? 0).toLocaleString()} tokens
        <div>{state === 'Complete' && costs?.native_logged_usd != null && chunks > 0
          ? `${money(costs.native_logged_usd / chunks)} native logged per processed chunk`
          : 'Per-chunk cost unavailable until accounting is complete and chunks have been processed.'}</div>
      </div>
      {((accounting.coverage_notes?.length ?? 0) > 0 || (costs?.reasons.length ?? 0) > 0) && <details>
        <summary style={{ cursor: 'pointer' }}>Accounting notes</summary>
        <ul style={{ margin: '6px 0', paddingLeft: 20 }}>
          {accounting.coverage_notes?.map((note) => <li key={note}>{note}</li>)}
          {costs?.reasons.map((reason) => <li key={reason}>{reason.replace(/_/g, ' ')}</li>)}
        </ul>
      </details>}
      {accounting.reconciled_at && <div style={{ color: 'var(--fg-muted)' }}>Last checked {new Date(accounting.reconciled_at).toLocaleString()}</div>}
      </>}
    </div>
  );
  return <div data-testid="index-cost-summary" style={{ textAlign: 'left', color: 'var(--fg)', minWidth: 0 }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '4px 12px' }}>
      <div data-testid="index-cost-headline" style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
        {costs?.native_logged_usd != null && <><strong data-testid="index-cost-amount">{readableMoney(costs.native_logged_usd)} recorded</strong><span aria-hidden="true"> · </span></>}
        <span data-testid="index-cost-state" role="status" style={{ color: 'var(--fg-muted)' }}>{state}</span>
      </div>
      {action}
    </div>
    {(refreshError || accounting?.reconciliation_error) && <div role="status" style={{ marginTop: 4, color: 'var(--warn)' }}>Cost check failed. Refresh to retry.</div>}
    <details key={accounting?.session_id ?? 'unavailable'} data-testid="index-cost-details" style={{ marginTop: compact ? 4 : 6 }}>
      <summary style={{ cursor: 'pointer', color: 'var(--fg-muted)', width: 'fit-content' }}>Details</summary>
      {details}
    </details>
  </div>;
}

// Parent listings and this panel can finish reads in either order. Census
// revisions outrank an older reconciliation so a new request cannot retain a
// stale "complete" cost result from a previous checkpoint.
function newerRun(previous: IndexRunSummary | undefined, incoming: IndexRunSummary): IndexRunSummary {
  if (!previous || previous.run_id !== incoming.run_id || previous.corpus_id !== incoming.corpus_id) return incoming;
  const version = (record: IndexRunAccounting | null | undefined) => Object.values(record?.census ?? {}).reduce((sum, lane) => sum + lane.revision + 1, 0);
  const before = version(previous.accounting);
  const after = version(incoming.accounting);
  if (before > after || (before === after && (Date.parse(previous.accounting?.reconciled_at ?? '') || 0) > (Date.parse(incoming.accounting?.reconciled_at ?? '') || 0))) {
    return { ...incoming, accounting: previous.accounting };
  }
  return incoming;
}

export function IndexRunCosts({ corpusId, runId, initialRun, compact = false, autoRefresh = true, title = 'Run cost' }: {
  corpusId: string;
  runId: string;
  initialRun?: IndexRunSummary;
  compact?: boolean;
  autoRefresh?: boolean;
  title?: string;
}) {
  const { api } = useAPI();
  const [run, setRun] = useState(initialRun);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const current = useRef(initialRun);
  const initial = useRef(initialRun);
  initial.current = initialRun;
  const retry = useRef<() => void>(() => {});

  useEffect(() => {
    if (initialRun?.run_id !== runId || initialRun.corpus_id !== corpusId) return;
    current.current = newerRun(current.current, initialRun);
    setRun(current.current);
    if (accountingIsComplete(current.current)) setPaused(false);
  }, [initialRun, corpusId, runId]);

  useEffect(() => {
    let disposed = false;
    let timer: number | undefined;
    let inflight: Promise<IndexRunSummary | undefined> | undefined;
    let terminalAttempt = 0;
    current.current = initial.current;
    setRun(initial.current);
    setError(null);
    setPaused(false);
    const endpoint = api(`index/${encodeURIComponent(corpusId)}/runs/${encodeURIComponent(runId)}`);

    const refresh = (reconcile: boolean): Promise<IndexRunSummary | undefined> => {
      if (inflight) return inflight;
      setLoading(true);
      inflight = (async () => {
        try {
          const next = await readRun(endpoint, reconcile);
          if (next.run_id !== runId || next.corpus_id !== corpusId) throw new Error('The accounting response belongs to a different run.');
          if (!disposed) {
            current.current = newerRun(current.current, next);
            setRun(current.current);
            setError(null);
            if (accountingIsComplete(current.current)) setPaused(false);
          }
          return disposed ? undefined : current.current;
        } catch (cause) {
          if (!disposed) setError(cause instanceof Error ? cause.message : 'Unable to refresh accounting.');
          return undefined;
        } finally {
          inflight = undefined;
          if (!disposed) setLoading(false);
        }
      })();
      return inflight;
    };
    const schedule = () => {
      if (disposed || !autoRefresh) return;
      const latest = current.current;
      if (latest && !latest.accounting) return;
      const ownerInterrupted = Boolean(latest?.accounting?.owner_interrupted);
      if (latest?.accounting?.costs?.state === 'complete' && !latest.accounting.reconciliation_error && !ownerInterrupted && latest.status !== 'indexing') return;
      const active = latest?.status === 'indexing' && !ownerInterrupted;
      const delay = active ? ACTIVE_DELAY_MS : TERMINAL_DELAYS_MS[terminalAttempt++];
      if (delay === undefined) { setPaused(true); return; }
      timer = window.setTimeout(() => { void refresh(true).then(schedule); }, delay);
    };
    retry.current = () => { void refresh(true); };
    void refresh(false).then(schedule);
    return () => {
      disposed = true;
      window.clearTimeout(timer);
      retry.current = () => {};
    };
  }, [api, corpusId, runId, autoRefresh]);

  const refreshAction = <button type="button" aria-label="Refresh cost" onClick={() => retry.current()} disabled={loading} style={{ padding: '4px 8px', color: 'var(--fg)', background: 'var(--bg-elev2)', border: '1px solid var(--line)', borderRadius: 5, cursor: loading ? 'wait' : 'pointer' }}>
    {loading ? 'Checking…' : 'Refresh'}
  </button>;
  return <section data-testid="index-run-costs" data-run-id={runId} style={{ marginTop: compact ? 0 : 12, padding: compact ? 0 : 12, border: compact ? undefined : '1px solid var(--line)', borderRadius: 8, minWidth: 0, fontSize: 12 }}>
    {!compact && <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontWeight: 700, marginBottom: 6 }}>
      <span data-testid="index-run-costs-title">{title}</span>
      <TooltipIcon name="INDEX_NATIVE_ACCOUNTING" />
    </div>}
    {run || error ? <IndexCostSummary key={`${corpusId}:${runId}`} accounting={run?.accounting} compact={compact} action={refreshAction} refreshError={error} refreshPaused={paused} />
      : <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}><span>Loading cost…</span>{refreshAction}</div>}
  </section>;
}
