// TriBridRAG - Monitoring Subtab Component
// Live alert rules (as Prometheus evaluates them) + Grafana/Prometheus deep links.
//
// The former "alert thresholds" form posted to /api/monitoring/alert-thresholds,
// a route that never existed (2026-08-25 drive finding M10); the real alert
// configuration is infra/prometheus-rules.yml, read back here from Prometheus.

import { useCallback, useEffect, useState } from 'react';
import { apiClient, api } from '@/api/client';
import { useConfigField } from '@/hooks/useConfig';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { ObservabilityOperatorDeck } from '@/components/Observability/OperatorDeck';
import type { ObservabilityAlertRule, ObservabilityAlertRulesResponse } from '@/types/generated';

function stateTone(state: string): { fg: string; label: string } {
  if (state === 'firing') return { fg: 'var(--err)', label: 'FIRING' };
  if (state === 'pending') return { fg: 'var(--warn)', label: 'PENDING' };
  return { fg: 'var(--ok)', label: 'OK' };
}

function formatDuration(seconds: number): string {
  if (!seconds) return 'immediate';
  if (seconds % 3600 === 0) return `${seconds / 3600}h`;
  if (seconds % 60 === 0) return `${seconds / 60}m`;
  return `${seconds}s`;
}

function normalizeBase(url: string): string {
  return String(url || '').trim().replace(/\/$/, '');
}

function AlertRuleRow({ rule }: { rule: ObservabilityAlertRule }) {
  const tone = stateTone(rule.state);
  return (
    <tr data-testid={`alert-rule-${rule.name}`} data-state={rule.state}>
      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
        <span style={{ color: tone.fg, fontWeight: 700, fontSize: '12px' }}>{tone.label}</span>
        {(rule.active_alerts ?? 0) > 0 ? (
          <span style={{ marginLeft: 6, fontSize: '11.5px', color: 'var(--fg-muted)' }}>×{rule.active_alerts}</span>
        ) : null}
      </td>
      <td style={{ padding: '8px 10px' }}>
        <div style={{ fontWeight: 700, color: 'var(--fg)', fontSize: '13px' }}>{rule.name}</div>
        {rule.summary ? <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: 2 }}>{rule.summary}</div> : null}
      </td>
      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap', fontSize: '12px', color: 'var(--fg)' }}>{rule.severity || '—'}</td>
      <td style={{ padding: '8px 10px', whiteSpace: 'nowrap', fontSize: '12px', color: 'var(--fg)' }}>{formatDuration(rule.duration_seconds ?? 0)}</td>
      <td style={{ padding: '8px 10px', fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--fg)', wordBreak: 'break-all' }}>
        {rule.query}
      </td>
    </tr>
  );
}

export function MonitoringSubtab() {
  const [grafanaBaseUrl] = useConfigField<string>('ui.grafana_base_url', '');
  const [prometheusBaseUrl] = useConfigField<string>('tracing.prometheus_base_url', '');
  const [alertmanagerBaseUrl] = useConfigField<string>('tracing.alertmanager_base_url', '');
  const [rules, setRules] = useState<ObservabilityAlertRulesResponse | null>(null);
  const ruleRows: ObservabilityAlertRule[] = rules?.rules ?? [];
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [rulesLoading, setRulesLoading] = useState(true);
  const [lastLoaded, setLastLoaded] = useState<Date | null>(null);

  const loadRules = useCallback(async () => {
    setRulesLoading(true);
    setRulesError(null);
    try {
      const { data } = await apiClient.get<ObservabilityAlertRulesResponse>(api('/observability/alert-rules'));
      setRules(data);
      setLastLoaded(new Date());
    } catch (error) {
      setRules(null);
      setRulesError(error instanceof Error ? error.message : 'Failed to load alert rules');
    } finally {
      setRulesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRules();
  }, [loadRules]);

  const grafanaHref = normalizeBase(grafanaBaseUrl);
  const prometheusHref = normalizeBase(prometheusBaseUrl);
  const alertmanagerHref = normalizeBase(alertmanagerBaseUrl);
  const linkStyle = (enabled: boolean, bg: string) => ({
    background: enabled ? bg : 'var(--bg-elev2)',
    color: enabled ? 'var(--accent-contrast)' : 'var(--fg-muted)',
    border: enabled ? 'none' : '1px solid var(--line)',
    fontWeight: 700,
    padding: '10px',
    borderRadius: '6px',
    textAlign: 'center' as const,
    textDecoration: 'none',
    fontSize: '13px',
    pointerEvents: enabled ? ('auto' as const) : ('none' as const),
  });

  return (
    <div className="settings-section">
      <ObservabilityOperatorDeck />

      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginTop: '20px',
          marginBottom: '20px',
        }}
        data-testid="alert-rules-panel"
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0 }}>
            Alert Rules <TooltipIcon name="PROMETHEUS_BASE_URL" />
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
              {lastLoaded ? `Read ${lastLoaded.toLocaleTimeString()}` : ''}
            </span>
            <button type="button" className="small-button" onClick={() => void loadRules()} disabled={rulesLoading}>
              {rulesLoading ? 'Loading…' : '↻ Refresh'}
            </button>
          </div>
        </div>
        <p className="small" style={{ marginTop: 8, marginBottom: 14 }}>
          These are the alerting rules Prometheus is evaluating right now (source: <code>infra/prometheus-rules.yml</code>);
          firing rules route to Alertmanager and appear in the incident feed above. Edit the rules file and reload Prometheus to
          change thresholds.
        </p>

        {rulesError ? (
          <div role="alert" style={{ color: 'var(--err)', fontSize: '13px' }} data-testid="alert-rules-error">
            Failed to load alert rules: {rulesError}
          </div>
        ) : null}
        {rules && !rules.ok ? (
          <div role="alert" style={{ color: 'var(--warn)', fontSize: '13px' }} data-testid="alert-rules-unavailable">
            {rules.error}
          </div>
        ) : null}
        {rules && rules.ok ? (
          <div style={{ overflowX: 'auto' }}>
            <div style={{ fontSize: '12.5px', color: 'var(--fg-muted)', marginBottom: 8 }} data-testid="alert-rules-summary">
              {ruleRows.length} rule{ruleRows.length === 1 ? '' : 's'} · {rules.firing_count ?? 0} firing · {rules.pending_count ?? 0}{' '}
              pending · read from <code>{rules.source_url}</code>
            </div>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }} data-testid="alert-rules-table">
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--fg-muted)', fontSize: '11.5px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                  <th style={{ padding: '6px 10px' }}>State</th>
                  <th style={{ padding: '6px 10px' }}>Rule</th>
                  <th style={{ padding: '6px 10px' }}>Severity</th>
                  <th style={{ padding: '6px 10px' }}>For</th>
                  <th style={{ padding: '6px 10px' }}>Expression</th>
                </tr>
              </thead>
              <tbody>
                {ruleRows.map((rule) => (
                  <AlertRuleRow key={`${rule.group}:${rule.name}`} rule={rule} />
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </div>

      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px',
        }}
      >
        <h3 style={{ marginTop: 0 }}>Metrics Backends</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Links resolve from the configured base URLs (Grafana Config → Observability endpoints). A greyed link means that URL is
          not configured.
        </p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
          <a
            href={grafanaHref || undefined}
            target="_blank"
            rel="noopener noreferrer"
            aria-disabled={!grafanaHref}
            style={linkStyle(Boolean(grafanaHref), 'var(--link)')}
            data-testid="open-grafana"
          >
            {grafanaHref ? 'Open Grafana' : 'Grafana URL not configured'}
          </a>
          <a
            href={prometheusHref || undefined}
            target="_blank"
            rel="noopener noreferrer"
            aria-disabled={!prometheusHref}
            style={linkStyle(Boolean(prometheusHref), 'var(--warn)')}
            data-testid="open-prometheus"
          >
            {prometheusHref ? 'Open Prometheus' : 'Prometheus URL not configured'}
          </a>
          <a
            href={alertmanagerHref || undefined}
            target="_blank"
            rel="noopener noreferrer"
            aria-disabled={!alertmanagerHref}
            style={linkStyle(Boolean(alertmanagerHref), 'var(--accent)')}
            data-testid="open-alertmanager"
          >
            {alertmanagerHref ? 'Open Alertmanager' : 'Alertmanager URL not configured'}
          </a>
        </div>
      </div>
    </div>
  );
}
