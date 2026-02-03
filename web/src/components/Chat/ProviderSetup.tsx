import { useEffect, useMemo, useState } from 'react';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { useRepoStore } from '@/stores/useRepoStore';
import type { LocalModelConfig, OpenRouterConfig } from '@/types/generated';
import type { ProvidersHealthResponse, ProviderHealth } from '@/types/generated';

export function ProviderSetup() {
  const { api } = useAPI();
  const { config, loading, error } = useConfig();
  const { activeRepo } = useRepoStore();

  // NOTE: We bind to the nested objects (not leaf fields) to avoid clobbering sibling fields
  // due to shallow merges in config section patching.
  const [openrouter, setOpenrouter] = useConfigField<OpenRouterConfig>('chat.openrouter', {});
  const [localModels, setLocalModels] = useConfigField<LocalModelConfig>('chat.local_models', {});

  if (!config) {
    return (
      <div className="subtab-panel" style={{ padding: '24px' }}>
        <div style={{ color: 'var(--fg-muted)' }}>{loading ? 'Loading configuration…' : 'No configuration loaded.'}</div>
        {error && <div style={{ marginTop: 10, color: 'var(--err)' }}>{error}</div>}
      </div>
    );
  }

  const providers = Array.isArray(localModels.providers) ? localModels.providers : [];

  const [health, setHealth] = useState<ProvidersHealthResponse | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState<string | null>(null);

  const healthByProvider = useMemo(() => {
    const items = (health?.providers || []) as ProviderHealth[];
    const byName = new Map<string, ProviderHealth>();
    for (const p of items) {
      const key = `${p.kind}:${p.provider}`;
      byName.set(key, p);
    }
    return byName;
  }, [health]);

  useEffect(() => {
    if (!config) return;
    const scope = String(activeRepo || '').trim();
    const qs = scope ? `?corpus_id=${encodeURIComponent(scope)}` : '';

    setHealthLoading(true);
    setHealthError(null);

    fetch(api(`chat/health${qs}`))
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
        return r.json();
      })
      .then((d) => setHealth(d as ProvidersHealthResponse))
      .catch((e) => setHealthError(e instanceof Error ? e.message : String(e)))
      .finally(() => setHealthLoading(false));
  }, [activeRepo, api, config, openrouter?.enabled, providers]);

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: 'var(--fg)' }}>Providers</h3>
        <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)' }}>
          Configure OpenRouter and local OpenAI-compatible provider endpoints.
        </div>
      </div>

      {error && (
        <div style={{ marginBottom: 14, color: 'var(--err)', fontSize: 13 }}>
          {error}
        </div>
      )}

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>OpenRouter</div>

        <div className="input-row" style={{ alignItems: 'start' }}>
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={openrouter.enabled === true}
                onChange={(e) => setOpenrouter({ ...(openrouter || {}), enabled: e.target.checked })}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">Enable OpenRouter</span>
            </label>
          </div>

          <div className="input-group">
            <ApiKeyStatus keyName="OPENROUTER_API_KEY" label="OpenRouter API Key" />
          </div>
        </div>

        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
          {healthLoading ? (
            <span>Checking provider status…</span>
          ) : healthError ? (
            <span style={{ color: 'var(--err)' }}>Health check failed: {healthError}</span>
          ) : (
            (() => {
              const h = healthByProvider.get('openrouter:OpenRouter');
              if (!h) return <span>Provider status: unknown</span>;
              if (h.reachable) return <span style={{ color: 'var(--ok)' }}>Provider status: reachable</span>;
              return (
                <span style={{ color: 'var(--warn)' }}>
                  Provider status: unreachable{h.detail ? ` — ${h.detail}` : ''}
                </span>
              );
            })()
          )}
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Local providers</div>

        {providers.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No local providers configured.</div>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {providers.map((p, idx) => (
              <div
                key={`${p.name}-${idx}`}
                style={{
                  padding: 12,
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 14, alignItems: 'center' }}>
                  <div style={{ minWidth: 180 }}>
                    <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--fg)' }}>{p.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--fg-muted)', marginTop: 2 }}>{p.provider_type}</div>
                  </div>

                  <div style={{ fontSize: 11, color: 'var(--fg-muted)' }}>
                    {(() => {
                      const h = healthByProvider.get(`local:${p.name}`);
                      if (!h) return 'status: unknown';
                      if (h.reachable) return <span style={{ color: 'var(--ok)' }}>status: reachable</span>;
                      return <span style={{ color: 'var(--warn)' }}>status: unreachable</span>;
                    })()}
                  </div>

                  <label className="toggle" style={{ marginLeft: 'auto' }}>
                    <input
                      type="checkbox"
                      checked={p.enabled !== false}
                      onChange={(e) => {
                        const nextProviders = providers.map((cur, i) =>
                          i === idx ? { ...cur, enabled: e.target.checked } : cur
                        );
                        setLocalModels({ ...(localModels || {}), providers: nextProviders });
                      }}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">Enabled</span>
                  </label>
                </div>

                <div className="input-row" style={{ marginTop: 10 }}>
                  <div className="input-group">
                    <label>Base URL</label>
                    <input
                      type="text"
                      value={p.base_url}
                      onChange={(e) => {
                        const nextProviders = providers.map((cur, i) =>
                          i === idx ? { ...cur, base_url: e.target.value } : cur
                        );
                        setLocalModels({ ...(localModels || {}), providers: nextProviders });
                      }}
                      placeholder="http://127.0.0.1:11434"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

