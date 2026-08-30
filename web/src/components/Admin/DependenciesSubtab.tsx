import { useEffect, useState } from 'react';

import { LoadingSpinner } from '@/components/ui/LoadingSpinner';
import { secretStatusesForSurface, stateChipStyle, useConfigControlPlaneData } from './configControlPlane';

/**
 * The readiness probe can take ~25s on a cold cache; the old bare sentence was
 * indistinguishable from a hung page (E-41). Show the section header, a spinner with an
 * elapsed counter, skeleton placeholders for the cards that are coming, and — once it runs
 * long — a message explaining why so the operator knows it is working, not stuck.
 */
function DependenciesLoading() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const slow = elapsed >= 8;

  return (
    <div className="settings-section">
      <h2 style={{ marginBottom: 8 }}>Dependencies &amp; Secrets</h2>
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}
      >
        <LoadingSpinner size="sm" />
        <span data-testid="dependencies-loading" style={{ color: 'var(--fg-muted)', fontSize: 13 }}>
          Loading dependency and secret readiness…{elapsed >= 3 ? ` (${elapsed}s)` : ''}
        </span>
      </div>
      {slow ? (
        <div data-testid="dependencies-slow" style={{ marginBottom: 16, fontSize: 12, color: 'var(--warn)' }}>
          This is taking longer than usual. The readiness probe inspects every integration and
          secret and can take up to ~30 seconds on a cold cache. Still working…
        </div>
      ) : null}
      <div style={{ display: 'grid', gap: 12 }} aria-hidden="true">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            style={{ padding: 14, borderRadius: 12, border: '1px solid var(--line)', background: 'var(--bg-elev1)' }}
          >
            <div className="skeleton" style={{ height: 16, width: '38%', marginBottom: 10 }} />
            <div className="skeleton" style={{ height: 12, width: '62%' }} />
          </div>
        ))}
      </div>
    </div>
  );
}

export function DependenciesSubtab() {
  const { readiness, loading, error, reload } = useConfigControlPlaneData();

  if (loading) {
    return <DependenciesLoading />;
  }

  if (error) {
    return (
      <div className="settings-section">
        <div style={{ color: 'var(--err)', marginBottom: 12 }}>Unable to load dependency readiness: {error}</div>
        <button type="button" onClick={() => { void reload(); }}>Retry</button>
      </div>
    );
  }

  const integrations = readiness?.integrations || [];
  return (
    <div className="settings-section">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 20 }}>
        <div>
          <h2 style={{ marginBottom: 8 }}>Dependencies & Secrets</h2>
          <p className="small" style={{ maxWidth: 860 }}>
            Env-only secrets, passwords, tokens, and webhooks are modeled as first-class dependencies here. Missing credentials show up as explicit blockers on the operator surfaces they affect.
          </p>
        </div>
        <button
          type="button"
          onClick={() => {
            void reload();
          }}
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--line)',
            background: 'var(--bg-elev2)',
            color: 'var(--fg)',
            cursor: 'pointer',
            fontWeight: 700,
          }}
        >
          Refresh
        </button>
      </div>

      {readiness?.operator_hint ? (
        <div
          style={{
            marginBottom: 18,
            padding: 14,
            borderRadius: 12,
            border: '1px solid var(--line)',
            background: 'var(--bg-elev1)',
            color: 'var(--fg)',
          }}
        >
          {readiness.operator_hint}
        </div>
      ) : null}

      <div style={{ display: 'grid', gap: 12, marginBottom: 22 }}>
        {integrations.map((integration) => (
          <div
            key={integration.id}
            style={{
              padding: 14,
              borderRadius: 12,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev1)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontWeight: 800, color: 'var(--fg)' }}>{integration.label}</div>
                <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)' }}>Surface: {integration.ui_surface}</div>
              </div>
              <span style={stateChipStyle(integration.state)}>{integration.state}</span>
            </div>

            {integration.operator_hint ? (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                {integration.operator_hint}
              </div>
            ) : null}

            {(integration.missing_config_paths || []).length > 0 ? (
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--err)' }}>
                Missing config: {(integration.missing_config_paths || []).join(', ')}
              </div>
            ) : null}

            {(integration.missing_secret_ids || []).length > 0 ? (
              <div style={{ marginTop: 6, fontSize: 12, color: 'var(--err)' }}>
                Missing secrets: {(integration.missing_secret_ids || []).join(', ')}
              </div>
            ) : null}

            {(integration.blocked_surfaces || []).length > 0 ? (
              <div style={{ marginTop: 6, fontSize: 12, color: 'var(--fg-muted)' }}>
                Blocked surfaces: {(integration.blocked_surfaces || []).join(', ')}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gap: 18 }}>
        {(['runtime', 'retrieval', 'observability', 'training', 'eval', 'graph', 'shell'] as const).map((surface) => {
          const surfaceSecrets = secretStatusesForSurface(readiness || null, surface);
          if (surfaceSecrets.length === 0) return null;
          return (
            <section
              key={surface}
              style={{
                padding: 14,
                borderRadius: 12,
                border: '1px solid var(--line)',
                background: 'var(--bg-elev1)',
              }}
            >
              <div style={{ fontWeight: 800, color: 'var(--fg)', marginBottom: 12, textTransform: 'capitalize' }}>{surface}</div>
              <div style={{ display: 'grid', gap: 10 }}>
                {surfaceSecrets.map((secret) => (
                  <div
                    key={secret.requirement.id}
                    style={{
                      padding: 12,
                      borderRadius: 10,
                      border: '1px solid var(--line)',
                      background: 'var(--bg)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
                      <div>
                        <div style={{ fontWeight: 700, color: 'var(--fg)' }}>{secret.requirement.label}</div>
                        <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)' }}>
                          {secret.requirement.env_var}
                        </div>
                      </div>
                      <span style={stateChipStyle(secret.configured ? 'ready' : 'unconfigured')}>
                        {secret.configured ? 'configured' : 'missing'}
                      </span>
                    </div>
                    <div style={{ marginTop: 8, fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.5 }}>
                      {secret.requirement.description}
                    </div>
                    {(secret.blocker_for_integrations || []).length > 0 ? (
                      <div style={{ marginTop: 8, fontSize: 12, color: 'var(--err)' }}>
                        Blocking: {(secret.blocker_for_integrations || []).join(', ')}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
