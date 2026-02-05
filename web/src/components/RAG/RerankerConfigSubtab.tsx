import { useCallback, useEffect, useMemo, useState } from 'react';
import { useConfigField } from '@/hooks';
import { useReranker } from '@/hooks/useReranker';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';
import { modelsApi } from '@/api';
import type { TrainingConfig } from '@/types/generated';

const RERANKER_MODES = ['none', 'local', 'learning', 'cloud'] as const;
type RerankerMode = (typeof RERANKER_MODES)[number];
type LearningBackend = NonNullable<TrainingConfig['learning_reranker_backend']>;

type RerankModelEntry = {
  provider?: string;
  model?: string;
  family?: string;
  notes?: string;
};

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

function toApiKeyName(provider: string): string {
  const p = (provider || '').toLowerCase();
  switch (p) {
    case 'cohere':
      return 'COHERE_API_KEY';
    case 'voyage':
      return 'VOYAGE_API_KEY';
    case 'jina':
      return 'JINA_API_KEY';
    default:
      return `${p.toUpperCase()}_API_KEY`;
  }
}

export function RerankerConfigSubtab() {
  // Config (LAW)
  const [mode, setMode] = useConfigField<RerankerMode>('reranking.reranker_mode', 'local');
  const [cloudProvider, setCloudProvider] = useConfigField<string>('reranking.reranker_cloud_provider', 'cohere');
  const [cloudModel, setCloudModel] = useConfigField<string>('reranking.reranker_cloud_model', 'rerank-v3.5');
  const [cloudTopN, setCloudTopN] = useConfigField<number>('reranking.reranker_cloud_top_n', 50);

  const [localModel, setLocalModel] = useConfigField<string>(
    'reranking.reranker_local_model',
    'cross-encoder/ms-marco-MiniLM-L-12-v2'
  );

  // Learning reranker is configured under training + reranking
  const [learningModelPath, setLearningModelPath] = useConfigField<string>(
    'training.tribrid_reranker_model_path',
    'models/cross-encoder-tribrid'
  );
  const [learningBackend, setLearningBackend] = useConfigField<LearningBackend>(
    'training.learning_reranker_backend',
    'auto'
  );
  const [learningBaseModel, setLearningBaseModel] = useConfigField<string>(
    'training.learning_reranker_base_model',
    'Qwen/Qwen3-Reranker-0.6B'
  );
  const [learningUnloadAfterSec, setLearningUnloadAfterSec] = useConfigField<number>(
    'training.learning_reranker_unload_after_sec',
    0
  );
  const [alpha, setAlpha] = useConfigField<number>('reranking.tribrid_reranker_alpha', 0.7);
  const [topN, setTopN] = useConfigField<number>('reranking.tribrid_reranker_topn', 50);
  const [batch, setBatch] = useConfigField<number>('reranking.tribrid_reranker_batch', 16);
  const [maxLen, setMaxLen] = useConfigField<number>('reranking.tribrid_reranker_maxlen', 512);

  const [snippetChars, setSnippetChars] = useConfigField<number>('reranking.rerank_input_snippet_chars', 700);
  const [trustRemoteCode, setTrustRemoteCode] = useConfigField<number>(
    'reranking.transformers_trust_remote_code',
    1
  );

  // Model catalog (from /api/models)
  const [rerankModels, setRerankModels] = useState<RerankModelEntry[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const load = async () => {
      setModelsLoading(true);
      setModelsError(null);
      try {
        const data = await modelsApi.listByType('RERANK');
        const list = Array.isArray(data) ? (data as RerankModelEntry[]) : [];
        if (mounted) setRerankModels(list);
      } catch (e) {
        if (mounted) setModelsError(e instanceof Error ? e.message : 'Failed to load reranker models');
      } finally {
        if (mounted) setModelsLoading(false);
      }
    };
    void load();
    return () => {
      mounted = false;
    };
  }, []);

  const cloudProviders = useMemo(() => {
    const providers = uniqueSorted(rerankModels.map((m) => m.provider || ''));
    return providers.filter((p) => !['huggingface', 'local'].includes(p.toLowerCase()));
  }, [rerankModels]);

  const cloudModelOptions = useMemo(() => {
    const p = (cloudProvider || '').toLowerCase();
    return uniqueSorted(
      rerankModels
        .filter((m) => (m.provider || '').toLowerCase() === p)
        .map((m) => m.model || '')
    );
  }, [rerankModels, cloudProvider]);

  const localModelOptions = useMemo(() => {
    return uniqueSorted(
      rerankModels
        .filter((m) => ['huggingface', 'local'].includes((m.provider || '').toLowerCase()))
        .map((m) => m.model || '')
    );
  }, [rerankModels]);

  // Keep config values sane when switching modes / providers
  useEffect(() => {
    if (mode !== 'cloud') return;
    if (!cloudProviders.length) return;
    if (!cloudProviders.includes(cloudProvider)) {
      setCloudProvider(cloudProviders[0]);
    }
  }, [mode, cloudProviders, cloudProvider, setCloudProvider]);

  useEffect(() => {
    if (mode !== 'cloud') return;
    if (!cloudModelOptions.length) return;
    if (!cloudModelOptions.includes(cloudModel)) {
      setCloudModel(cloudModelOptions[0]);
    }
  }, [mode, cloudModelOptions, cloudModel, setCloudModel]);

  useEffect(() => {
    if (mode !== 'local') return;
    if (!localModelOptions.length) return;
    if (!localModelOptions.includes(localModel)) {
      setLocalModel(localModelOptions[0]);
    }
  }, [mode, localModelOptions, localModel, setLocalModel]);

  // Runtime info (server)
  const { getInfo } = useReranker();
  const [runtimeInfo, setRuntimeInfo] = useState<any>(null);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  const [runtimeError, setRuntimeError] = useState<string | null>(null);

  const loadRuntime = useCallback(async () => {
    setRuntimeLoading(true);
    setRuntimeError(null);
    try {
      const info = await getInfo();
      setRuntimeInfo(info);
    } catch (e) {
      setRuntimeError(e instanceof Error ? e.message : 'Failed to load reranker runtime info');
    } finally {
      setRuntimeLoading(false);
    }
  }, [getInfo]);

  useEffect(() => {
    void loadRuntime();
  }, [loadRuntime]);

  const cloudKeyName = useMemo(() => {
    return mode === 'cloud' ? toApiKeyName(cloudProvider) : '';
  }, [mode, cloudProvider]);

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3
          style={{
            fontSize: '18px',
            fontWeight: 600,
            color: 'var(--fg)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            marginBottom: '6px',
          }}
        >
          <span style={{ fontSize: 22 }}>⚡</span>
          Reranker
          <TooltipIcon name="RERANKER_MODE" />
        </h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Configure reranking for TriBrid retrieval (local, cloud, or learning).
        </div>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 10,
          marginBottom: 18,
        }}
      >
        {RERANKER_MODES.map((m) => (
          <button
            key={m}
            className="small-button"
            onClick={() => setMode(m)}
            style={{
              padding: '10px 12px',
              borderRadius: 8,
              border: `1px solid ${mode === m ? 'var(--accent)' : 'var(--line)'}`,
              background: mode === m ? 'rgba(var(--accent-rgb), 0.12)' : 'var(--bg-elev1)',
              color: mode === m ? 'var(--fg)' : 'var(--fg-muted)',
              cursor: 'pointer',
              textAlign: 'left',
            }}
          >
            <div style={{ fontWeight: 600, marginBottom: 4 }}>
              {m === 'none' && '🚫 Disabled'}
              {m === 'local' && '💻 Local'}
              {m === 'cloud' && '☁️ Cloud'}
              {m === 'learning' && '🧠 Learning'}
            </div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
              {m === 'none' && 'No reranking'}
              {m === 'local' && 'Run a local cross-encoder'}
              {m === 'cloud' && 'Use a hosted reranker API'}
              {m === 'learning' && 'Use the trainable learning reranker'}
            </div>
          </button>
        ))}
      </div>

      {modelsError && (
        <div style={{ marginBottom: 14, color: 'var(--err)' }}>
          Failed to load models: {modelsError}
        </div>
      )}

      {mode === 'cloud' && (
        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 10,
            padding: 14,
            marginBottom: 18,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 10 }}>Cloud reranker</div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Provider <TooltipIcon name="RERANKER_CLOUD_PROVIDER" />
              </label>
              <select
                value={cloudProvider}
                onChange={(e) => setCloudProvider(e.target.value)}
                disabled={modelsLoading || cloudProviders.length === 0}
              >
                {cloudProviders.length === 0 && <option value="">No providers found</option>}
                {cloudProviders.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>

            <div className="input-group">
              <label>
                Model <TooltipIcon name="RERANKER_CLOUD_MODEL" />
              </label>
              <select
                value={cloudModel}
                onChange={(e) => setCloudModel(e.target.value)}
                disabled={modelsLoading || cloudModelOptions.length === 0}
              >
                {cloudModelOptions.length === 0 && <option value="">No models for provider</option>}
                {cloudModelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Cloud Top-N <TooltipIcon name="RERANKER_CLOUD_TOP_N" />
              </label>
              <input
                type="number"
                min={1}
                max={100}
                value={cloudTopN}
                onChange={(e) => setCloudTopN(parseInt(e.target.value || '50', 10))}
              />
            </div>
            <div className="input-group">
              {cloudKeyName ? <ApiKeyStatus keyName={cloudKeyName} /> : null}
            </div>
          </div>
        </div>
      )}

      {mode === 'local' && (
        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 10,
            padding: 14,
            marginBottom: 18,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 10 }}>Local reranker</div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Local model <TooltipIcon name="RERANKER_LOCAL_MODEL" />
              </label>
              <select
                value={localModel}
                onChange={(e) => setLocalModel(e.target.value)}
                disabled={modelsLoading || localModelOptions.length === 0}
              >
                {localModelOptions.length === 0 && <option value="">No local rerank models</option>}
                {localModelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>

            <div className="input-group">
              <label>
                Trust remote code <TooltipIcon name="TRANSFORMERS_TRUST_REMOTE_CODE" />
              </label>
              <select
                value={trustRemoteCode}
                onChange={(e) => setTrustRemoteCode(parseInt(e.target.value, 10))}
              >
                <option value={1}>Yes</option>
                <option value={0}>No</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {mode === 'learning' && (
        <div
          style={{
            background: 'var(--bg-elev1)',
            border: '1px solid var(--line)',
            borderRadius: 10,
            padding: 14,
            marginBottom: 18,
          }}
        >
          <div style={{ fontWeight: 600, marginBottom: 10 }}>Learning reranker</div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Model path <TooltipIcon name="TRIBRID_RERANKER_MODEL_PATH" />
              </label>
              <input
                type="text"
                value={learningModelPath}
                onChange={(e) => setLearningModelPath(e.target.value)}
                placeholder="models/cross-encoder-tribrid"
              />
            </div>
            <div className="input-group" />
          </div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Backend <TooltipIcon name="LEARNING_RERANKER_BACKEND" />
              </label>
              <select value={learningBackend} onChange={(e) => setLearningBackend(e.target.value as LearningBackend)}>
                <option value="auto">auto (prefer MLX Qwen3)</option>
                <option value="transformers">transformers (HF)</option>
                <option value="mlx_qwen3">mlx_qwen3 (force)</option>
              </select>
            </div>
            <div className="input-group">
              <label>
                Base model <TooltipIcon name="LEARNING_RERANKER_BASE_MODEL" />
              </label>
              <input
                type="text"
                value={learningBaseModel}
                onChange={(e) => setLearningBaseModel(e.target.value)}
              />
            </div>
          </div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Alpha <TooltipIcon name="TRIBRID_RERANKER_ALPHA" />
              </label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={alpha}
                onChange={(e) => setAlpha(parseFloat(e.target.value || '0.7'))}
              />
            </div>
            <div className="input-group">
              <label>
                Top-N <TooltipIcon name="TRIBRID_RERANKER_TOPN" />
              </label>
              <input
                type="number"
                min={10}
                max={200}
                value={topN}
                onChange={(e) => setTopN(parseInt(e.target.value || '10', 10))}
              />
            </div>
            <div className="input-group">
              <label>
                Batch <TooltipIcon name="TRIBRID_RERANKER_BATCH" />
              </label>
              <input
                type="number"
                min={1}
                max={128}
                value={batch}
                onChange={(e) => setBatch(parseInt(e.target.value || '16', 10))}
              />
            </div>
          </div>

          <div className="input-row">
            <div className="input-group">
              <label>
                Max length <TooltipIcon name="TRIBRID_RERANKER_MAXLEN" />
              </label>
              <input
                type="number"
                min={64}
                max={2048}
                value={maxLen}
                onChange={(e) => setMaxLen(parseInt(e.target.value || '512', 10))}
              />
            </div>
            <div className="input-group">
              <label>
                Unload after sec <TooltipIcon name="LEARNING_RERANKER_UNLOAD_AFTER_SEC" />
              </label>
              <input
                type="number"
                min={0}
                max={86400}
                value={learningUnloadAfterSec}
                onChange={(e) => setLearningUnloadAfterSec(parseInt(e.target.value || '0', 10))}
              />
            </div>
            <div className="input-group" />
          </div>
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
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Shared reranking behavior</div>
        <div className="input-row">
          <div className="input-group">
            <label>
              Input snippet chars <TooltipIcon name="RERANK_INPUT_SNIPPET_CHARS" />
            </label>
            <input
              type="number"
              min={100}
              max={5000}
              step={50}
              value={snippetChars}
              onChange={(e) => setSnippetChars(parseInt(e.target.value || '700', 10))}
            />
          </div>
          <div className="input-group" />
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
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <div style={{ fontWeight: 600 }}>Runtime info</div>
          <button className="small-button" onClick={loadRuntime} disabled={runtimeLoading}>
            {runtimeLoading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {runtimeError && <div style={{ color: 'var(--err)', marginBottom: 8 }}>{runtimeError}</div>}
        {!runtimeError && runtimeInfo && (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)', lineHeight: 1.6 }}>
            <div>
              <strong style={{ color: 'var(--fg)' }}>Enabled:</strong> {String(runtimeInfo.enabled ?? '—')}
            </div>
            <div>
              <strong style={{ color: 'var(--fg)' }}>Device:</strong> {runtimeInfo.device ?? '—'}
            </div>
            <div>
              <strong style={{ color: 'var(--fg)' }}>Model:</strong> {runtimeInfo.resolved_path || runtimeInfo.path || '—'}
            </div>
          </div>
        )}

        {!runtimeError && !runtimeInfo && (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            {runtimeLoading ? 'Loading…' : 'No info available'}
          </div>
        )}
      </div>

      {modelsLoading && (
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--fg-muted)' }}>
          Loading reranker model catalog…
        </div>
      )}
    </div>
  );
}
