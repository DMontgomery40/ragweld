import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import * as DashAPI from '@/api/dashboard';
import { useActiveRepo } from '@/stores/useRepoStore';
import type {
  AgentTrainControlPlaneStatusResponse,
  BenchmarkObservabilitySummaryResponse,
  EvalObservabilitySummaryResponse,
  LangfuseTraceAccess,
  LokiStatus,
  ObservabilityCatalogResponse,
  ObservabilityComponentStatus,
  ObservabilityIncidentsResponse,
  ObservabilityStatusResponse,
  PromptObservabilitySummaryResponse,
  Trace,
  ObservabilityWorkbenchLink,
  TraceExternalLink,
  TracesLatestResponse,
} from '@/types/generated';

type Props = {
  title?: string;
  subtitle?: string;
  corpusId?: string | null;
};

type SurfaceTone = 'good' | 'warn' | 'bad' | 'dim';

function toneFromComponent(component: ObservabilityComponentStatus | null | undefined): SurfaceTone {
  if (!component) return 'dim';
  // The API already applied probe hysteresis and probeability when it computed
  // `severity`; re-deriving here is how a single missed probe used to paint a
  // card red while the deck header said the opposite.
  if (component.severity === 'healthy') return 'good';
  if (component.severity === 'critical') return 'bad';
  if (component.severity === 'warning') return 'warn';
  return 'dim';
}

/** The one status word for a component, drawn from the same evidence as its detail text. */
function componentStatusWord(component: ObservabilityComponentStatus): string {
  if (!component.enabled) return 'off';
  if (!component.configured) return 'not configured';
  if (component.probeable === false) return 'not probeable';
  if (component.reachable === true) return 'reachable';
  if (component.reachable === false) return component.severity === 'critical' ? 'down' : 'degraded';
  return 'configured';
}

function toneFromControlPlane(status: AgentTrainControlPlaneStatusResponse | null): SurfaceTone {
  if (!status) return 'dim';
  if (status.ready) return 'good';
  if (status.lane === 'legacy_local') return 'warn';
  return 'bad';
}

function toneFromLoki(status: LokiStatus | null): SurfaceTone {
  if (!status) return 'dim';
  return status.reachable ? 'good' : 'warn';
}

function toneFromEval(summary: EvalObservabilitySummaryResponse | null): SurfaceTone {
  if (!summary || !summary.latest_run_id) return 'dim';
  if (Number(summary.regressed_count || 0) > 0 || Number(summary.top1_accuracy?.absolute_delta || 0) < 0) return 'bad';
  if (!summary.ai_comparison_ready) return 'warn';
  return 'good';
}

function toneFromBenchmark(summary: BenchmarkObservabilitySummaryResponse | null): SurfaceTone {
  if (!summary || !summary.latest_run_id) return 'dim';
  if (Number(summary.latest_error_count || 0) > Number(summary.previous_error_count || 0)) return 'bad';
  if (Number(summary.average_latency_ms?.absolute_delta || 0) > 250) return 'warn';
  return 'good';
}

function toneFromPrompt(summary: PromptObservabilitySummaryResponse | null): SurfaceTone {
  if (!summary || !summary.current_prompt_set_ref) return 'dim';
  if (summary.eval_regression_suspected || summary.benchmark_regression_suspected) return 'bad';
  if (summary.pending_verification) return 'warn';
  return 'good';
}

function toneClassName(tone: SurfaceTone): string {
  return `obs-card obs-card-${tone}`;
}

function formatUsd(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return 'Unavailable';
  return `$${Number(value).toFixed(6)}`;
}

function formatWhen(value: string | null | undefined): string {
  const raw = String(value || '').trim();
  if (!raw) return 'No timestamp yet';
  const date = new Date(raw);
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString();
}

function dedupeLinks(...groups: Array<Array<TraceExternalLink> | null | undefined>): TraceExternalLink[] {
  const deduped: TraceExternalLink[] = [];
  for (const group of groups) {
    for (const link of group || []) {
      const url = String(link?.url || '').trim();
      const label = String(link?.label || '').trim();
      if (!url || !label) continue;
      if (deduped.some((existing) => existing.url === url && existing.label === label)) continue;
      deduped.push(link);
    }
  }
  return deduped;
}

function dedupeWorkbenchLinks(
  ...groups: Array<Array<ObservabilityWorkbenchLink> | null | undefined>
): ObservabilityWorkbenchLink[] {
  const deduped: ObservabilityWorkbenchLink[] = [];
  for (const group of groups) {
    for (const link of group || []) {
      const path = String(link?.path || '').trim();
      const label = String(link?.label || '').trim();
      if (!path || !label) continue;
      if (deduped.some((existing) => existing.path === path && existing.label === label)) continue;
      deduped.push(link);
    }
  }
  return deduped;
}

export function ObservabilityOperatorDeck({
  title = 'Observability Operator Deck',
  subtitle = 'A human-facing command surface for traces, logs, metrics, workflow truth, and retrieval lane health.',
  corpusId,
}: Props) {
  const activeRepo = useActiveRepo();
  const scopedCorpusId = String(corpusId ?? activeRepo ?? '').trim();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [observability, setObservability] = useState<ObservabilityStatusResponse | null>(null);
  const [catalog, setCatalog] = useState<ObservabilityCatalogResponse | null>(null);
  const [incidents, setIncidents] = useState<ObservabilityIncidentsResponse | null>(null);
  const [evalSummary, setEvalSummary] = useState<EvalObservabilitySummaryResponse | null>(null);
  const [benchmarkSummary, setBenchmarkSummary] = useState<BenchmarkObservabilitySummaryResponse | null>(null);
  const [promptSummary, setPromptSummary] = useState<PromptObservabilitySummaryResponse | null>(null);
  const [latestTraceResponse, setLatestTraceResponse] = useState<TracesLatestResponse | null>(null);
  const [lokiStatus, setLokiStatus] = useState<LokiStatus | null>(null);
  const [langfuseAccess, setLangfuseAccess] = useState<LangfuseTraceAccess | null>(null);
  const [langfuseAccessError, setLangfuseAccessError] = useState<string | null>(null);
  const [controlPlane, setControlPlane] = useState<AgentTrainControlPlaneStatusResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const [
          nextObservability,
          nextCatalog,
          nextIncidents,
          nextEvalSummary,
          nextBenchmarkSummary,
          nextPromptSummary,
          nextTrace,
          nextLoki,
          nextControlPlane,
        ] = await Promise.all([
          DashAPI.getObservabilityStatus(),
          DashAPI.getObservabilityCatalog(scopedCorpusId || undefined),
          DashAPI.getObservabilityIncidents(scopedCorpusId || undefined),
          DashAPI.getEvalObservabilitySummary(scopedCorpusId || undefined),
          DashAPI.getBenchmarkObservabilitySummary(scopedCorpusId || undefined),
          DashAPI.getPromptObservabilitySummary(scopedCorpusId || undefined),
          DashAPI.getLatestTrace(),
          DashAPI.getLokiStatus(),
          DashAPI.getAgentControlPlaneStatus(scopedCorpusId || undefined),
        ]);

        if (cancelled) return;

        setObservability(nextObservability);
        setCatalog(nextCatalog);
        setIncidents(nextIncidents);
        setEvalSummary(nextEvalSummary);
        setBenchmarkSummary(nextBenchmarkSummary);
        setPromptSummary(nextPromptSummary);
        setLatestTraceResponse(nextTrace);
        setLokiStatus(nextLoki);
        // Only offer the per-trace Langfuse deep link once Langfuse says it
        // holds the trace; the drive landed on "You do not have access to this
        // trace" twice from links the deck offered unconditionally.
        const traceId = String(nextTrace?.trace?.trace_id || '').trim();
        if (!traceId) {
          setLangfuseAccess(null);
          setLangfuseAccessError(null);
        } else {
          try {
            setLangfuseAccess(await DashAPI.getLangfuseTraceAccess(traceId));
            setLangfuseAccessError(null);
          } catch (accessError) {
            // The check failing is not the same as Langfuse saying no. Without
            // this the link was filtered out of deckLinks and nothing said why -
            // the one case where the deck went quiet.
            setLangfuseAccess(null);
            setLangfuseAccessError(
              accessError instanceof Error ? accessError.message : 'the check did not complete'
            );
          }
        }
        setControlPlane(nextControlPlane);
        setLastUpdated(new Date().toISOString());

        if (!nextObservability && !nextCatalog && !nextIncidents && !nextTrace && !nextControlPlane) {
          setError('No observability surfaces responded. Check the API and configured backends.');
        }
      } catch (loadError) {
        if (cancelled) return;
        setError(loadError instanceof Error ? loadError.message : 'Failed to load observability surfaces');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    const interval = window.setInterval(() => {
      void load();
    }, 30000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [refreshNonce, scopedCorpusId]);

  const trace: Trace | null = latestTraceResponse?.trace ?? null;
  const traceDurationMs =
    trace?.ended_at_ms != null && trace?.started_at_ms != null
      ? Math.max(0, trace.ended_at_ms - trace.started_at_ms)
      : null;

  const componentMap = Object.fromEntries(
    (observability?.components || []).map((component) => [component.id, component])
  ) as Record<string, ObservabilityComponentStatus | undefined>;

  const isLangfuseTraceLink = (link: TraceExternalLink): boolean =>
    link.kind === 'langfuse' && String(link.url || '').includes('/traces/');
  const deckLinks = dedupeLinks(
    observability?.links,
    catalog?.external_links,
    trace?.external_links,
    controlPlane?.links
  ).filter((link) => !isLangfuseTraceLink(link) || langfuseAccess?.exists === true);
  // Which external surfaces the matrix reports as off, so a chip that opens
  // nothing is marked rather than looking identical to a live one.
  const offSurfaceUrls = new Set(
    (observability?.components || [])
      .filter((component) => !component.enabled && String(component.url || '').trim())
      .map((component) => String(component.url))
  );
  const langfuseTraceNotice =
    trace?.trace_id && langfuseAccess && !langfuseAccess.exists ? langfuseAccess.detail : null;
  const workbenchLinks = dedupeWorkbenchLinks(catalog?.workbench_links);
  const recentIncidents = (incidents?.incidents || []).slice(0, 4);
  const retrievalComponent = componentMap.haystack_docling_qdrant || null;

  const metricsComponent = componentMap.grafana || componentMap.otlp_export || componentMap.alloy || null;
  const tracesComponent = componentMap.tempo || componentMap.langfuse || componentMap.local_trace_buffer || null;
  const gatewayComponent = componentMap.litellm || componentMap.vllm || null;

  return (
    <section className="obs-deck-root">
      <div className="obs-deck-shell">
        <div className="obs-deck-header">
          <div>
            <div className="obs-deck-kicker">Operator Surface</div>
            <h3 className="obs-deck-title">{title}</h3>
            <p className="obs-deck-subtitle">{subtitle}</p>
          </div>

          <div className="obs-deck-controls">
            {lastUpdated ? <span className="obs-deck-updated">Updated {formatWhen(lastUpdated)}</span> : null}
            <button type="button" className="obs-deck-refresh" onClick={() => setRefreshNonce((value) => value + 1)}>
              Refresh Surface
            </button>
          </div>
        </div>

        <div className="obs-deck-chip-row">
          <span className="obs-chip">mode={observability?.mode || 'unknown'}</span>
          <span className="obs-chip">corpus={scopedCorpusId || 'global'}</span>
          <span className="obs-chip">severity={observability?.severity || 'unknown'}</span>
          <span className="obs-chip">incidents={incidents?.total_count || observability?.incident_count || 0}</span>
          <span className="obs-chip">
            workflow={controlPlane?.lane === 'flyte_mlflow_unsloth' ? 'flyte+mlflow+unsloth' : 'legacy_local'}
          </span>
          <span className="obs-chip">
            latest_route={trace?.route_summary ? `${trace.route_summary.method} ${trace.route_summary.path}` : 'none'}
          </span>
        </div>

        {error ? <div className="obs-banner obs-banner-error">{error}</div> : null}
        {!error && observability?.operator_hint ? <div className="obs-banner">{observability.operator_hint}</div> : null}
        {!error && controlPlane?.operator_hint ? <div className="obs-banner obs-banner-subtle">{controlPlane.operator_hint}</div> : null}
        {loading ? <div className="obs-banner obs-banner-subtle">Refreshing live observability surfaces…</div> : null}
        {langfuseTraceNotice ? (
          <div className="obs-banner obs-banner-subtle" data-testid="obs-langfuse-trace-notice">
            {`Langfuse trace link withheld: ${langfuseTraceNotice}`}
          </div>
        ) : null}
        {langfuseAccessError ? (
          <div className="obs-banner obs-banner-subtle" data-testid="obs-langfuse-check-failed">
            {`Could not check the Langfuse trace (${langfuseAccessError}), so its link is not offered.`}
          </div>
        ) : null}
        {langfuseAccess?.exists ? (
          // Visible, not hover-only: the API can prove Langfuse holds the trace,
          // but not that this operator's Langfuse account may read it. Saying so
          // before the click is the whole difference from the dead end the
          // drive hit.
          <div className="obs-banner obs-banner-subtle" data-testid="obs-langfuse-access-note">
            {langfuseAccess.sign_in_hint}
          </div>
        ) : null}

        {deckLinks.length ? (
          <div className="obs-link-group">
            <span className="obs-link-group-label">External surfaces, open in a new tab</span>
            <div className="obs-link-row">
            {deckLinks.map((link) => (
              <a
                key={`${link.label}-${link.url}`}
                href={link.url}
                target="_blank"
                rel="noreferrer"
                className="obs-link-pill"
                data-testid={`obs-external-link-${link.kind}`}
                title={
                  link.kind === 'langfuse' && langfuseAccess
                    ? langfuseAccess.sign_in_hint
                    : `${link.detail ? `${link.detail} ` : ''}${
                        offSurfaceUrls.has(link.url)
                          ? 'This surface is reported off in the Integration Matrix below. '
                          : ''
                      }Opens ${link.url} in a new tab.`
                }
              >
                {link.label}
                {offSurfaceUrls.has(link.url) ? ' (off)' : ''}
              </a>
            ))}
            </div>
          </div>
        ) : null}

        {workbenchLinks.length ? (
          <div className="obs-link-group">
            <span className="obs-link-group-label">In this app</span>
            <div className="obs-link-row">
              {workbenchLinks.map((link) => (
                <Link
                  key={`${link.label}-${link.path}`}
                  to={link.path}
                  className="obs-link-pill obs-link-pill-internal"
                  title={link.description || `Opens ${link.label} in this app.`}
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        ) : null}

        <div className="obs-signal-grid">
          <article className={toneClassName(toneFromComponent(metricsComponent))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Metrics</span>
              <span className="obs-card-status">{metricsComponent?.label || 'Not surfaced'}</span>
            </div>
            <div className="obs-card-title">Dashboards & Export Path</div>
            <div className="obs-card-metric">
              {componentMap.grafana?.reachable === true ? 'Grafana reachable' : componentMap.grafana?.configured ? 'Grafana configured' : 'Grafana missing'}
            </div>
            <p className="obs-card-detail">
              OTLP export, Grafana, and Alloy should be the first place an operator looks for service-wide blast radius.
            </p>
          </article>

          <article className={toneClassName(toneFromComponent(tracesComponent))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Traces</span>
              <span className="obs-card-status">{trace?.trace_id ? 'Live trace present' : 'Waiting for request'}</span>
            </div>
            <div className="obs-card-title">Tempo + Langfuse</div>
            <div className="obs-card-metric">
              {trace?.route_summary ? `${trace.route_summary.method} ${trace.route_summary.path}` : 'No recent request yet'}
            </div>
            <p className="obs-card-detail">
              {trace?.trace_id
                ? `Trace ${trace.trace_id}${traceDurationMs != null ? ` · ${traceDurationMs} ms` : ''}`
                : 'Run a live request to light up route, trace, root span, and external trace links.'}
            </p>
          </article>

          <article className={toneClassName(toneFromLoki(lokiStatus))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Logs</span>
              <span className="obs-card-status">{lokiStatus?.reachable ? 'Loki reachable' : 'Proxy status only'}</span>
            </div>
            <div className="obs-card-title">Loki & Alert Stream</div>
            <div className="obs-card-metric">{lokiStatus?.status || 'Unknown'}</div>
            <p className="obs-card-detail">
              Log search and wake-up path for API, Postgres, and Neo4j need to be visible next to traces, not buried behind backend-only tooling.
            </p>
          </article>

          <article className={toneClassName(toneFromComponent(gatewayComponent))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Gateway</span>
              <span className="obs-card-status">{componentMap.litellm?.enabled ? 'LiteLLM on' : 'LiteLLM off'}</span>
            </div>
            <div className="obs-card-title">LiteLLM + vLLM</div>
            <div className="obs-card-metric">
              {trace?.cost_summary?.provider || componentMap.litellm?.label || 'Gateway not active'}
            </div>
            <p className="obs-card-detail">
              {trace?.cost_summary
                ? `${formatUsd(trace.cost_summary.estimated_cost_usd)} · ${trace.cost_summary.cost_source || 'unavailable'} · ${trace.cost_summary.total_tokens ?? 0} tokens`
                : 'Gateway routing and request cost should sit in the same operator surface as logs and traces.'}
            </p>
          </article>

          <article className={toneClassName(toneFromControlPlane(controlPlane))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Workflow</span>
              <span className="obs-card-status">{controlPlane?.ready ? 'Ready' : controlPlane?.lane || 'Unknown'}</span>
            </div>
            <div className="obs-card-title">Flyte + MLflow + Unsloth</div>
            <div className="obs-card-metric">
              {controlPlane?.lane === 'flyte_mlflow_unsloth' ? 'Target lane selected' : 'Legacy local lane'}
            </div>
            <p className="obs-card-detail">
              Workflow execution, run tracking, and training execution need to show up together because this is what wakes someone up at 2AM.
            </p>
          </article>

          <article className={toneClassName(toneFromComponent(retrievalComponent))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Retrieval</span>
              <span className="obs-card-status">
                {retrievalComponent?.reachable === true
                  ? 'Qdrant generation live'
                  : retrievalComponent?.reachable === false
                    ? 'Vector lane degraded'
                    : 'Not indexed'}
              </span>
            </div>
            <div className="obs-card-title">Haystack + Qdrant + Docling</div>
            <div className="obs-card-metric">{retrievalComponent?.detail || 'No retrieval lane status yet'}</div>
            <p className="obs-card-detail">
              Retrieval health belongs in the same command surface as gateway and tracing, because operator pain rarely respects subsystem boundaries.
            </p>
          </article>

          <article className={toneClassName(toneFromEval(evalSummary))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Evals</span>
              <span className="obs-card-status">{evalSummary?.latest_run_id ? 'Run present' : 'No baseline'}</span>
            </div>
            <div className="obs-card-title">Eval Regression Surface</div>
            <div className="obs-card-metric">
              {evalSummary?.latest_run_id
                ? `top1 ${(Number(evalSummary.top1_accuracy?.current_value || 0) * 100).toFixed(1)}%`
                : 'No eval run yet'}
            </div>
            <p className="obs-card-detail">
              {evalSummary?.operator_hint || 'Eval Analysis should be reachable from the operator surface whenever quality shifts.'}
            </p>
          </article>

          <article className={toneClassName(toneFromBenchmark(benchmarkSummary))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Benchmark</span>
              <span className="obs-card-status">{benchmarkSummary?.latest_run_id ? 'Run present' : 'No run'}</span>
            </div>
            <div className="obs-card-title">Runtime Comparison Surface</div>
            <div className="obs-card-metric">
              {benchmarkSummary?.latest_run_id
                ? `${Number(benchmarkSummary.average_latency_ms?.current_value || 0).toFixed(1)} ms avg`
                : 'No benchmark run yet'}
            </div>
            <p className="obs-card-detail">
              {benchmarkSummary?.operator_hint || 'Benchmark must stay visible so runtime regressions are not buried behind hidden routes.'}
            </p>
          </article>

          <article className={toneClassName(toneFromPrompt(promptSummary))}>
            <div className="obs-card-heading">
              <span className="obs-card-kicker">Prompts</span>
              <span className="obs-card-status">
                {promptSummary?.pending_verification ? 'Verification required' : promptSummary?.current_prompt_set_ref ? 'Tracked' : 'No prompt set'}
              </span>
            </div>
            <div className="obs-card-title">Prompt Regression Surface</div>
            <div className="obs-card-metric">
              {promptSummary?.current_prompt_set_ref?.version_id
                ? promptSummary.current_prompt_set_ref.version_id.slice(0, 12)
                : 'Prompt set unavailable'}
            </div>
            <p className="obs-card-detail">
              {promptSummary?.operator_hint || 'Prompt changes need immediate correlation against eval and benchmark evidence.'}
            </p>
          </article>
        </div>

        <div className="obs-detail-grid">
          <article className="obs-panel">
            <div className="obs-panel-header">
              <span className="obs-panel-kicker">Integration Matrix</span>
              <span className="obs-panel-title">Cross-stack status</span>
            </div>

            <div className="obs-component-grid">
              {[
                componentMap.grafana,
                componentMap.alloy,
                componentMap.otlp_export,
                componentMap.tempo,
                componentMap.mimir,
                componentMap.pyroscope,
                componentMap.faro,
                componentMap.opencost,
                componentMap.alertmanager,
                componentMap.langfuse,
                componentMap.litellm,
                componentMap.vllm,
                componentMap.flyte,
                componentMap.mlflow,
                componentMap.unsloth,
                componentMap.haystack_docling_qdrant,
              ]
                .filter(Boolean)
                .map((component) => (
                  <div key={component!.id} className={toneClassName(toneFromComponent(component))}>
                    <div className="obs-card-heading">
                      <span className="obs-card-kicker">{component!.id}</span>
                      <span className="obs-card-status" data-testid={`obs-status-${component!.id}`}>
                        {componentStatusWord(component!)}
                      </span>
                    </div>
                    <div className="obs-card-title">{component!.label}</div>
                    <p className="obs-card-detail">{component!.detail || 'No operator detail yet.'}</p>
                    {component!.probe_history?.length ? (
                      <div
                        className="obs-probe-history"
                        data-testid={`obs-probe-history-${component!.id}`}
                        title={`Readiness probes, oldest first: ${component!.probe_history.join(', ')}`}
                      >
                        <span className="obs-probe-strip" aria-hidden="true">
                          {component!.probe_history.map((sample, index) => (
                            <span key={index} className={`obs-probe-dot obs-probe-${sample}`} />
                          ))}
                        </span>
                        <span className="obs-probe-label">
                          {`last ${component!.probe_history?.length ?? 0} probes`}
                          {(component!.consecutive_failures ?? 0) > 0
                            ? `, ${component!.consecutive_failures} failing`
                            : ''}
                        </span>
                      </div>
                    ) : null}
                    {component!.url ? (
                      <a href={component!.url} target="_blank" rel="noreferrer" className="obs-inline-link">
                        Open surface
                      </a>
                    ) : null}
                  </div>
                ))}

              <div className={toneClassName(toneFromLoki(lokiStatus))}>
                <div className="obs-card-heading">
                  <span className="obs-card-kicker">loki</span>
                  <span className="obs-card-status">{lokiStatus?.reachable ? 'reachable' : 'needs check'}</span>
                </div>
                <div className="obs-card-title">Loki log search</div>
                <p className="obs-card-detail">{lokiStatus?.url ? `${lokiStatus.status} · ${lokiStatus.url}` : lokiStatus?.status || 'No Loki status yet.'}</p>
              </div>
            </div>
          </article>

          <article className="obs-panel">
            <div className="obs-panel-header">
              <span className="obs-panel-kicker">Live Evidence</span>
              <span className="obs-panel-title">Latest request + workflow + retrieval</span>
            </div>

            <div className="obs-evidence-stack">
              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Latest request trace</div>
                {trace ? (
                  <>
                    <div className="obs-evidence-mono">{trace.trace_id || 'no-trace-id'}</div>
                    <div className="obs-evidence-copy">
                      {trace.route_summary?.method || '—'} {trace.route_summary?.path || '—'}
                    </div>
                    <div className="obs-evidence-copy">
                      root_span={trace.root_span_id || 'n/a'} · correlation={trace.correlation_id || 'n/a'}
                    </div>
                    <div className="obs-evidence-copy">
                      cost={formatUsd(trace.cost_summary?.estimated_cost_usd)} · provider={trace.cost_summary?.provider || 'n/a'}
                    </div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">No trace captured yet for the selected scope.</div>
                )}
              </div>

              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Workflow control plane</div>
                {controlPlane ? (
                  <>
                    <div className="obs-evidence-mono">{controlPlane.lane}</div>
                    <div className="obs-evidence-copy">
                      workflow={controlPlane.workflow_backend} · tracking={controlPlane.tracking_backend} · execution={controlPlane.execution_backend}
                    </div>
                    <div className="obs-evidence-copy">{controlPlane.operator_hint || 'No operator hint yet.'}</div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">Training control plane status has not loaded yet.</div>
                )}
              </div>

              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Retrieval vector lane</div>
                {retrievalComponent ? (
                  <>
                    <div className="obs-evidence-mono">{retrievalComponent.url || 'qdrant'}</div>
                    <div className="obs-evidence-copy">{retrievalComponent.detail}</div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">No retrieval lane status is available yet.</div>
                )}
              </div>
            </div>
          </article>
        </div>

        <div className="obs-detail-grid">
          <article className="obs-panel">
            <div className="obs-panel-header">
              <span className="obs-panel-kicker">ML Quality</span>
              <span className="obs-panel-title">Eval, benchmark, and prompt correlation</span>
            </div>

            <div className="obs-evidence-stack">
              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Eval summary</div>
                {evalSummary?.latest_run_id ? (
                  <>
                    <div className="obs-evidence-mono">{evalSummary.latest_run_id}</div>
                    <div className="obs-evidence-copy">
                      top1={(Number(evalSummary.top1_accuracy?.current_value || 0) * 100).toFixed(1)}% · topk=
                      {(Number(evalSummary.topk_accuracy?.current_value || 0) * 100).toFixed(1)}%
                    </div>
                    <div className="obs-evidence-copy">
                      delta_top1={Number(evalSummary.top1_accuracy?.absolute_delta || 0).toFixed(3)} · regressed=
                      {evalSummary.regressed_count || 0}
                    </div>
                    <div className="obs-evidence-copy">{evalSummary.operator_hint || 'No eval operator hint yet.'}</div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">No eval summary available yet.</div>
                )}
              </div>

              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Benchmark summary</div>
                {benchmarkSummary?.latest_run_id ? (
                  <>
                    <div className="obs-evidence-mono">{benchmarkSummary.latest_run_id}</div>
                    <div className="obs-evidence-copy">
                      avg_latency_ms={Number(benchmarkSummary.average_latency_ms?.current_value || 0).toFixed(1)} · p95=
                      {Number(benchmarkSummary.p95_latency_ms?.current_value || 0).toFixed(1)}
                    </div>
                    <div className="obs-evidence-copy">
                      errors={benchmarkSummary.latest_error_count || 0} · routes=
                      {(benchmarkSummary.provider_routes || []).slice(0, 3).join(' · ') || 'none'}
                    </div>
                    <div className="obs-evidence-copy">{benchmarkSummary.operator_hint || 'No benchmark operator hint yet.'}</div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">No benchmark summary available yet.</div>
                )}
              </div>

              <div className="obs-evidence-card">
                <div className="obs-evidence-title">Prompt-set correlation</div>
                {promptSummary?.current_prompt_set_ref ? (
                  <>
                    <div className="obs-evidence-mono">{promptSummary.current_prompt_set_ref.version_id}</div>
                    <div className="obs-evidence-copy">
                      since_eval={promptSummary.changed_since_latest_eval ? 'changed' : 'aligned'} · since_benchmark=
                      {promptSummary.changed_since_latest_benchmark ? 'changed' : 'aligned'}
                    </div>
                    <div className="obs-evidence-copy">
                      pending_verification={promptSummary.pending_verification ? 'yes' : 'no'} · recent_prompt_sets=
                      {promptSummary.recent_prompt_set_count || 0}
                    </div>
                    <div className="obs-evidence-copy">{promptSummary.operator_hint || 'No prompt operator hint yet.'}</div>
                  </>
                ) : (
                  <div className="obs-evidence-copy">No prompt summary available yet.</div>
                )}
              </div>
            </div>
          </article>

          <article className="obs-panel">
            <div className="obs-panel-header">
              <span className="obs-panel-kicker">Incident Feed</span>
              <span className="obs-panel-title">Recent incidents + deep links</span>
            </div>

            {recentIncidents.length ? (
              <div className="obs-evidence-stack">
                {recentIncidents.map((incident) => (
                  <div key={incident.id} className="obs-evidence-card">
                    <div className="obs-evidence-title">
                      {incident.title} · {incident.severity}
                    </div>
                    <div className="obs-evidence-copy">{incident.summary}</div>
                    {incident.operator_hint ? <div className="obs-evidence-copy">{incident.operator_hint}</div> : null}
                    {incident.workbench_links?.length ? (
                      <div className="obs-link-row" style={{ marginTop: 8 }}>
                        {incident.workbench_links.slice(0, 3).map((link) => (
                          <a key={`${incident.id}-${link.label}-${link.path}`} href={link.path} className="obs-inline-link">
                            {link.label}
                          </a>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="obs-evidence-card">
                <div className="obs-evidence-title">No incidents in payload</div>
                <div className="obs-evidence-copy">
                  When an infrastructure lane, workflow, eval, benchmark, or prompt surface regresses, the incident cards land here first.
                </div>
              </div>
            )}
          </article>
        </div>
      </div>

      <style>{`
        .obs-deck-root {
          display: flex;
          flex-direction: column;
          gap: 18px;
        }

        .obs-deck-shell {
          /* The deck is always painted on its own dark gradient, so its text
             tokens stay the dark-palette values under the Light theme as well
             (2026-08-25 drive finding M4: title/chips/buttons flipped to ~1.2:1). */
          --fg: #e4e4e7;
          --fg-muted: #a1a1aa;
          --line: #3f3f46;
          --bg: #09090b;
          --bg-elev1: #0f0f12;
          --bg-elev2: #18181b;
          --card-bg: #0f0f12;
          --panel: #0f0f12;
          --code-bg: #111114;
          --chip-bg: #18181b;
          --link: #94a3b8;
          --accent-contrast: #ffffff;
          color: var(--fg);
          position: relative;
          display: flex;
          flex-direction: column;
          gap: 18px;
          padding: 20px;
          border-radius: 18px;
          border: 1px solid rgba(112, 130, 156, 0.22);
          background:
            radial-gradient(circle at top right, rgba(42, 157, 143, 0.18), transparent 26%),
            radial-gradient(circle at bottom left, rgba(244, 162, 97, 0.12), transparent 24%),
            linear-gradient(180deg, rgba(13, 26, 38, 0.94), rgba(9, 18, 27, 0.98));
          box-shadow: 0 18px 48px rgba(3, 9, 15, 0.28);
          overflow: hidden;
        }

        .obs-deck-header {
          display: flex;
          justify-content: space-between;
          gap: 16px;
          align-items: flex-start;
          flex-wrap: wrap;
        }

        .obs-deck-kicker,
        .obs-panel-kicker,
        .obs-card-kicker {
          font-size: 10px;
          letter-spacing: 0.18em;
          text-transform: uppercase;
          color: rgba(180, 193, 210, 0.72);
        }

        .obs-deck-title {
          margin: 6px 0 8px;
          font-size: 24px;
          line-height: 1.1;
          color: var(--fg);
        }

        .obs-deck-subtitle {
          margin: 0;
          max-width: 72ch;
          font-size: 13px;
          line-height: 1.6;
          color: rgba(198, 209, 222, 0.78);
        }

        .obs-deck-controls {
          display: flex;
          align-items: center;
          gap: 12px;
          flex-wrap: wrap;
        }

        .obs-deck-updated {
          font-size: 11px;
          color: rgba(180, 193, 210, 0.76);
        }

        .obs-deck-refresh,
        .obs-link-pill,
        .obs-inline-link {
          appearance: none;
          border: 1px solid rgba(130, 154, 180, 0.24);
          background: rgba(10, 23, 35, 0.88);
          color: var(--fg);
          border-radius: 999px;
          padding: 8px 12px;
          font-size: 12px;
          font-weight: 600;
          text-decoration: none;
          cursor: pointer;
          transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
        }

        .obs-deck-refresh:hover,
        .obs-link-pill:hover,
        .obs-inline-link:hover {
          transform: translateY(-1px);
          border-color: rgba(42, 157, 143, 0.42);
          background: rgba(16, 33, 47, 0.96);
        }

        .obs-deck-chip-row,
        .obs-link-row {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
        }

        .obs-chip {
          padding: 5px 10px;
          border-radius: 999px;
          background: rgba(255, 255, 255, 0.04);
          border: 1px solid rgba(130, 154, 180, 0.18);
          color: rgba(214, 224, 236, 0.82);
          font-size: 11px;
          font-family: "IBM Plex Mono", monospace;
        }

        .obs-banner {
          padding: 12px 14px;
          border-radius: 12px;
          border: 1px solid rgba(42, 157, 143, 0.28);
          background: rgba(14, 40, 44, 0.62);
          color: rgba(222, 238, 236, 0.9);
          font-size: 12px;
          line-height: 1.5;
        }

        .obs-banner-subtle {
          border-color: rgba(130, 154, 180, 0.18);
          background: rgba(255, 255, 255, 0.03);
        }

        .obs-banner-error {
          border-color: rgba(231, 111, 81, 0.34);
          background: rgba(82, 23, 24, 0.72);
          color: rgba(255, 225, 219, 0.96);
        }

        .obs-signal-grid,
        .obs-detail-grid,
        .obs-component-grid {
          display: grid;
          gap: 12px;
        }

        .obs-signal-grid {
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        }

        .obs-detail-grid {
          grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
        }

        .obs-component-grid {
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        }

        .obs-panel,
        .obs-card {
          display: flex;
          flex-direction: column;
          gap: 10px;
          min-height: 0;
          padding: 16px;
          border-radius: 16px;
          border: 1px solid rgba(130, 154, 180, 0.16);
          background: rgba(6, 15, 24, 0.78);
        }

        .obs-card-good {
          border-color: rgba(42, 157, 143, 0.34);
          box-shadow: inset 0 0 0 1px rgba(42, 157, 143, 0.08);
        }

        .obs-card-warn {
          border-color: rgba(244, 162, 97, 0.34);
          box-shadow: inset 0 0 0 1px rgba(244, 162, 97, 0.08);
        }

        .obs-card-bad {
          border-color: rgba(231, 111, 81, 0.34);
          box-shadow: inset 0 0 0 1px rgba(231, 111, 81, 0.08);
        }

        .obs-card-dim {
          border-style: dashed;
        }

        .obs-card-heading,
        .obs-panel-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
          flex-wrap: wrap;
        }

        .obs-link-group {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }

        .obs-link-group-label {
          font-size: 11.5px;
          font-family: "IBM Plex Mono", monospace;
          letter-spacing: 0.04em;
          text-transform: uppercase;
          color: rgba(214, 224, 236, 0.86);
        }

        .obs-link-pill-internal {
          border-style: dashed;
        }

        .obs-probe-history {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .obs-probe-strip {
          display: inline-flex;
          gap: 3px;
        }

        .obs-probe-dot {
          width: 8px;
          height: 8px;
          border-radius: 2px;
          background: rgba(198, 209, 222, 0.35);
        }

        .obs-probe-ok {
          background: var(--ok);
        }

        .obs-probe-failed {
          background: var(--err);
        }

        .obs-probe-unprobeable {
          background: rgba(198, 209, 222, 0.35);
        }

        .obs-probe-label {
          font-size: 11.5px;
          font-family: "IBM Plex Mono", monospace;
          color: rgba(214, 224, 236, 0.86);
        }

        .obs-card-status {
          font-size: 11.5px;
          font-family: "IBM Plex Mono", monospace;
          color: rgba(214, 224, 236, 0.86);
        }

        .obs-card-title,
        .obs-panel-title,
        .obs-evidence-title {
          font-size: 15px;
          font-weight: 700;
          color: var(--fg);
        }

        .obs-card-metric,
        .obs-evidence-mono {
          font-family: "IBM Plex Mono", monospace;
          font-size: 12px;
          color: rgba(239, 245, 251, 0.94);
        }

        .obs-card-detail,
        .obs-evidence-copy {
          margin: 0;
          font-size: 12.5px;
          line-height: 1.55;
          color: rgba(198, 209, 222, 0.78);
        }

        .obs-evidence-stack {
          display: grid;
          gap: 12px;
        }

        .obs-evidence-card {
          display: flex;
          flex-direction: column;
          gap: 8px;
          padding: 14px;
          border-radius: 14px;
          border: 1px solid rgba(130, 154, 180, 0.14);
          background: rgba(255, 255, 255, 0.03);
        }

        @media (max-width: 720px) {
          .obs-deck-shell {
            padding: 16px;
          }

          .obs-deck-title {
            font-size: 21px;
          }

          .obs-detail-grid {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </section>
  );
}
