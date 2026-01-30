// AGRO - Monitoring Subtab Component
// Grafana metrics display and alert configuration

import { useState, useEffect } from 'react';
import { useAlertThresholdsStore, useAlertThresholdField } from '@/stores/useAlertThresholdsStore';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

/**
 * ---agentspec
 * what: |
 *   React component that renders a monitoring configuration subtab for alert threshold management.
 *   Accepts no props; uses Zustand hooks to access alert thresholds store (load, save, loaded, loading states) and tooltip context.
 *   Returns JSX displaying threshold input fields (error_rate_threshold_percent via useAlertThresholdField hook) with save/loading UI states.
 *   Manages local UI state: actionMessage (string | null) for user feedback, saving (boolean) for async save operations.
 *   Handles edge cases: loading state prevents premature renders, thresholdsLoaded gate prevents duplicate loads, error states surfaced via actionMessage.
 *
 * why: |
 *   Centralizes monitoring configuration UI in a reusable subtab component following React composition patterns.
 *   Uses Zustand store (useAlertThresholdsStore) for shared threshold state across the application, avoiding prop drilling.
 *   Custom hook useAlertThresholdField abstracts field binding logic, reducing boilerplate and keeping component focused on layout/UX.
 *   Separates loading (thresholdsLoading) from loaded (thresholdsLoaded) states to handle initial fetch vs. subsequent renders correctly.
 *
 * guardrails:
 *   - DO NOT convert Zustand store selectors to useState; the store is the source of truth and must remain the single state container for thresholds
 *   - ALWAYS check thresholdsLoaded before rendering threshold values to prevent stale or undefined data from displaying
 *   - ALWAYS call loadThresholds on mount or when thresholdsLoaded is false to ensure fresh data; use useEffect with proper dependency array
 *   - NOTE: useAlertThresholdField is a custom hook that must return [value, setValue] tuple compatible with Pydantic model validation on save
 *   - ASK USER: Confirm whether actionMessage should auto-clear after a timeout, or if manual dismissal is required; current implementation does not specify cleanup behavior
 * ---/agentspec
 */
export function MonitoringSubtab() {
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const loadThresholds = useAlertThresholdsStore((state) => state.load);
  const thresholdsLoaded = useAlertThresholdsStore((state) => state.loaded);
  const thresholdsLoading = useAlertThresholdsStore((state) => state.loading && !state.loaded);
  const saveThresholds = useAlertThresholdsStore((state) => state.save);
  const [errorRateThreshold, setErrorRateThreshold] = useAlertThresholdField('error_rate_threshold_percent');
  const [latencyP99, setLatencyP99] = useAlertThresholdField('request_latency_p99_seconds');
  const [timeoutErrors, setTimeoutErrors] = useAlertThresholdField('timeout_errors_per_5min');
  const [rateLimitErrors, setRateLimitErrors] = useAlertThresholdField('rate_limit_errors_per_5min');
  const [endpointCallFreq, setEndpointCallFreq] = useAlertThresholdField('endpoint_call_frequency_per_minute');
  const [sustainedDuration, setSustainedDuration] = useAlertThresholdField('endpoint_frequency_sustained_minutes');
  const [cohereRerankCalls, setCohereRerankCalls] = useAlertThresholdField('cohere_rerank_calls_per_minute');

  useEffect(() => {
    if (!thresholdsLoaded) {
      loadThresholds();
    }
  }, [thresholdsLoaded, loadThresholds]);

  async function saveAlertConfig() {
    setSaving(true);
    setActionMessage('Saving alert configuration...');
    try {
      const { updated, status } = await saveThresholds([
        'error_rate_threshold_percent',
        'request_latency_p99_seconds',
        'timeout_errors_per_5min',
        'rate_limit_errors_per_5min',
        'endpoint_call_frequency_per_minute',
        'endpoint_frequency_sustained_minutes',
        'cohere_rerank_calls_per_minute',
      ]);
      if (status === 'ok') {
        setActionMessage(`Alert configuration saved successfully! Updated ${updated} threshold(s).`);
      } else {
        setActionMessage('Failed to save alert configuration: backend returned an error.');
      }
    } catch (error: any) {
      setActionMessage(`Error saving alert configuration: ${error.message ?? 'Unknown error'}`);
    } finally {
      setSaving(false);
      setTimeout(() => setActionMessage(null), 3000);
    }
  }

  if (thresholdsLoading) {
    return (
      <div style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Loading alert configuration...
      </div>
    );
  }

  return (
    <div className="settings-section">
      {/* Action message */}
      {actionMessage && (
        <div style={{
          padding: '12px',
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          marginBottom: '16px',
          fontSize: '12px',
          color: 'var(--fg)'
        }}>
          {actionMessage}
        </div>
      )}

      <h2>Performance & Reliability Alerts</h2>
      <p className="small" style={{ marginBottom: '24px' }}>
        Set thresholds for error rates, latency, and timeout incidents.
      </p>

      {/* Performance Alerts */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Performance Thresholds</h3>

        <div className="input-row">
          <div className="input-group">
            <label>
              Error Rate Threshold (%)
              <TooltipIcon name="ERROR_RATE_THRESHOLD" />
            </label>
            <input
              type="number"
              value={errorRateThreshold}
              onChange={(e) => setErrorRateThreshold(e.target.value)}
              min="0.1"
              max="50"
              step="0.1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when error rate exceeds this percentage
            </p>
          </div>
          <div className="input-group">
            <label>
              Latency P99 Threshold (s)
              <TooltipIcon name="LATENCY_P99_THRESHOLD" />
            </label>
            <input
              type="number"
              value={latencyP99}
              onChange={(e) => setLatencyP99(e.target.value)}
              min="0.1"
              max="60"
              step="0.1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when 99th percentile latency exceeds this
            </p>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Timeout Errors Threshold
              <TooltipIcon name="TIMEOUT_ERRORS_THRESHOLD" />
            </label>
            <input
              type="number"
              value={timeoutErrors}
              onChange={(e) => setTimeoutErrors(e.target.value)}
              min="1"
              max="1000"
              step="1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when timeout count exceeds this
            </p>
          </div>
          <div className="input-group">
            <label>
              Rate Limit Errors Threshold
              <TooltipIcon name="RATE_LIMIT_ERRORS_THRESHOLD" />
            </label>
            <input
              type="number"
              value={rateLimitErrors}
              onChange={(e) => setRateLimitErrors(e.target.value)}
              min="1"
              max="1000"
              step="1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when rate limit hits exceed this
            </p>
          </div>
        </div>
      </div>

      {/* API Anomaly Alerts */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>API Anomaly Alerts</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Detect unusual API calling patterns that might indicate issues or loops.
        </p>

        <div className="input-row">
          <div className="input-group">
            <label>
              Endpoint Call Frequency
              <TooltipIcon name="ENDPOINT_CALL_FREQUENCY" />
            </label>
            <input
              type="number"
              value={endpointCallFreq}
              onChange={(e) => setEndpointCallFreq(e.target.value)}
              min="1"
              max="1000"
              step="1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when a single endpoint gets called this frequently
            </p>
          </div>
          <div className="input-group">
            <label>
              Sustained Duration (min)
              <TooltipIcon name="ENDPOINT_SUSTAINED_DURATION" />
            </label>
            <input
              type="number"
              value={sustainedDuration}
              onChange={(e) => setSustainedDuration(e.target.value)}
              min="1"
              max="60"
              step="1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Duration threshold for sustained frequency alert
            </p>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Cohere Rerank Calls/min
              <TooltipIcon name="COHERE_RERANK_CALLS" />
            </label>
            <input
              type="number"
              value={cohereRerankCalls}
              onChange={(e) => setCohereRerankCalls(e.target.value)}
              min="1"
              max="1000"
              step="1"
              style={{
                width: '100%',
                padding: '8px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)'
              }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
              Alert when Cohere reranking calls spike
            </p>
          </div>
          <div className="input-group"></div>
        </div>
      </div>

      {/* Grafana Metrics Display */}
      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>Grafana Metrics</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Access detailed metrics and dashboards via Grafana.
        </p>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px', marginBottom: '16px' }}>
          <button
            className="small-button"
            onClick={() => window.open('http://127.0.0.1:3000', '_blank')}
            style={{
              background: 'var(--link)',
              color: 'var(--accent-contrast)',
              fontWeight: '600',
              padding: '10px'
            }}
          >
            Open Grafana Dashboard
          </button>
          <button
            className="small-button"
            onClick={() => window.open('http://127.0.0.1:9090', '_blank')}
            style={{
              background: 'var(--warn)',
              color: 'var(--accent-contrast)',
              fontWeight: '600',
              padding: '10px'
            }}
          >
            Open Prometheus
          </button>
        </div>

        <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
          <p style={{ marginBottom: '8px' }}>Available Metrics:</p>
          <ul style={{ marginLeft: '20px', lineHeight: '1.6' }}>
            <li>Request latency (P50, P95, P99)</li>
            <li>Error rates and counts</li>
            <li>API token usage and costs</li>
            <li>Retrieval quality scores</li>
            <li>Container resource usage</li>
          </ul>
        </div>
      </div>

      {/* Save Button */}
      <button
        className="small-button"
        onClick={saveAlertConfig}
        disabled={saving}
        style={{
          width: '100%',
          background: 'var(--accent)',
          color: 'var(--accent-contrast)',
          fontWeight: '600',
          padding: '12px'
        }}
      >
        {saving ? 'Saving...' : 'Save Alert Configuration'}
      </button>
    </div>
  );
}
