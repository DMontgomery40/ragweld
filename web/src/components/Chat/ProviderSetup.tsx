import { useEffect, useMemo, useState } from 'react';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { useRepoStore } from '@/stores/useRepoStore';
import type {
  ChatModelInfo,
  ChatModelsResponse,
  LiteLLMConfig,
  ProviderHealth,
  ProvidersHealthResponse,
  RuntimeCapabilitiesResponse,
  VLLMConfig,
} from '@/types/generated';

export function ProviderSetup() {
  const { api } = useAPI();
  const { config, loading, error } = useConfig();
  const { activeRepo } = useRepoStore();
  const [litellm, setLitellm] = useConfigField<LiteLLMConfig>('chat.litellm', {});
  const [vllm, setVllm] = useConfigField<VLLMConfig>('chat.vllm', {});
  const [health, setHealth] = useState<ProvidersHealthResponse | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);
  const [models, setModels] = useState<ChatModelInfo[]>([]);
  const [modelError, setModelError] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<RuntimeCapabilitiesResponse | null>(null);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  const litellmHealth = useMemo(
    () => ((health?.providers || []) as ProviderHealth[]).find((item) => item.kind === 'litellm'),
    [health],
  );

  useEffect(() => {
    if (!config) return;
    const controller = new AbortController();
    const scope = String(activeRepo || '').trim();
    const qs = scope ? `?corpus_id=${encodeURIComponent(scope)}` : '';
    setHealthError(null);
    setModelError(null);
    setRuntimeError(null);

    const fetchJson = async <T,>(path: string, label: string): Promise<T> => {
      const response = await fetch(api(path), { signal: controller.signal });
      if (!response.ok) throw new Error(`${label}: ${response.status}`);
      return response.json() as Promise<T>;
    };

    Promise.allSettled([
      fetchJson<ProvidersHealthResponse>(`chat/health${qs}`, 'Health'),
      fetchJson<ChatModelsResponse>(`chat/models${qs}`, 'Models'),
      fetchJson<RuntimeCapabilitiesResponse>(`runtime-capabilities${qs}`, 'Runtime'),
    ]).then(([healthResult, modelResult, runtimeResult]) => {
      if (controller.signal.aborted) return;

      if (healthResult.status === 'fulfilled') {
        setHealth(healthResult.value);
      } else {
        setHealth(null);
        setHealthError(healthResult.reason instanceof Error ? healthResult.reason.message : String(healthResult.reason));
      }

      if (modelResult.status === 'fulfilled') {
        setModels(Array.isArray(modelResult.value.models) ? modelResult.value.models : []);
      } else {
        setModels([]);
        setModelError(modelResult.reason instanceof Error ? modelResult.reason.message : String(modelResult.reason));
      }

      if (runtimeResult.status === 'fulfilled') {
        setRuntime(runtimeResult.value);
      } else {
        setRuntime(null);
        setRuntimeError(runtimeResult.reason instanceof Error ? runtimeResult.reason.message : String(runtimeResult.reason));
      }
      });
    return () => controller.abort();
  }, [activeRepo, api, config, litellm.base_url, litellm.default_model, litellm.enabled, vllm.base_url, vllm.default_model, vllm.enabled]);

  if (!config) {
    return (
      <div className="subtab-panel" style={{ padding: '24px' }}>
        <div style={{ color: 'var(--fg-muted)' }}>{loading ? 'Loading configuration…' : 'No configuration loaded.'}</div>
        {error && <div style={{ marginTop: 10, color: 'var(--err)' }}>{error}</div>}
      </div>
    );
  }

  const route = runtime?.generation?.default_route;

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: 'var(--fg)' }}>Generation Gateway</h3>
        <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)' }}>
          Ragweld sends every generation request through LiteLLM. vLLM is the managed local serving backend.
        </div>
      </div>

      {error && <div style={{ marginBottom: 14, color: 'var(--err)', fontSize: 13 }}>{error}</div>}
      {healthError && <div style={{ marginBottom: 14, color: 'var(--err)', fontSize: 13 }}>{healthError}</div>}
      {modelError && <div style={{ marginBottom: 14, color: 'var(--err)', fontSize: 13 }}>{modelError}</div>}
      {runtimeError && <div style={{ marginBottom: 14, color: 'var(--err)', fontSize: 13 }}>{runtimeError}</div>}

      <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 18 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Current route</div>
        <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
          {route ? <>{route.provider_name} → <code>{route.model}</code> @ <code>{route.base_url}</code></> : 'No gateway route is ready.'}
        </div>
      </div>

      <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 14, marginBottom: 18 }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>LiteLLM gateway</div>
        <div className="input-row" style={{ alignItems: 'start' }}>
          <div className="input-group">
            <label className="toggle">
              <input type="checkbox" checked={litellm.enabled === true} onChange={(event) => setLitellm({ ...litellm, enabled: event.target.checked })} />
              <span className="toggle-track" aria-hidden="true"><span className="toggle-thumb" /></span>
              <span className="toggle-label">Enable LiteLLM</span>
            </label>
          </div>
          <div className="input-group"><ApiKeyStatus keyName="LITELLM_API_KEY" label="LiteLLM client key" /></div>
        </div>
        <div className="input-row" style={{ marginTop: 10 }}>
          <div className="input-group">
            <label>Base URL</label>
            <input value={String(litellm.base_url || '')} onChange={(event) => setLitellm({ ...litellm, base_url: event.target.value })} placeholder="http://127.0.0.1:54000/v1" />
          </div>
          <div className="input-group">
            <label>Default alias</label>
            <input value={String(litellm.default_model || '')} onChange={(event) => setLitellm({ ...litellm, default_model: event.target.value })} placeholder="ragweld-local" />
          </div>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: litellmHealth?.reachable ? 'var(--ok)' : 'var(--warn)' }}>
          {litellmHealth?.reachable ? `Authenticated and reachable (${models.length} catalog-backed gateway alias${models.length === 1 ? '' : 'es'})` : `Unavailable${litellmHealth?.detail ? ` — ${litellmHealth.detail}` : ''}`}
        </div>
      </div>

      <div style={{ background: 'var(--bg-elev1)', border: '1px solid var(--line)', borderRadius: 10, padding: 14 }}>
        <div style={{ fontWeight: 600, marginBottom: 10 }}>vLLM serving</div>
        <label className="toggle">
          <input type="checkbox" checked={vllm.enabled === true} onChange={(event) => setVllm({ ...vllm, enabled: event.target.checked })} />
          <span className="toggle-track" aria-hidden="true"><span className="toggle-thumb" /></span>
          <span className="toggle-label">Enable managed vLLM</span>
        </label>
        <div className="input-row" style={{ marginTop: 10 }}>
          <div className="input-group">
            <label>Base URL</label>
            <input value={String(vllm.base_url || '')} onChange={(event) => setVllm({ ...vllm, base_url: event.target.value })} placeholder="http://127.0.0.1:58080/v1" />
          </div>
          <div className="input-group">
            <label>Expected served model</label>
            <input value={String(vllm.default_model || '')} onChange={(event) => setVllm({ ...vllm, default_model: event.target.value })} placeholder="Qwen/Qwen3-4B-Instruct-2507" />
          </div>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
          vLLM is not a direct application route. LiteLLM owns the alias that targets this serving endpoint. Readiness verifies the
          model vLLM reports (and its context window) against this value and the catalog&apos;s ragweld-local row.
        </div>
      </div>
    </div>
  );
}
