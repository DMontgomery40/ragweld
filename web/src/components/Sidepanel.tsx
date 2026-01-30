import { useState, useEffect } from 'react';
import { useConfigStore } from '@/stores';
import { CostLogic } from '@/modules/cost_logic';
import { EmbeddingMismatchWarning } from './ui/EmbeddingMismatchWarning';

export function Sidepanel() {
  const { config, loadConfig } = useConfigStore();
  
  // Track if initial load from config is done
  const [configLoaded, setConfigLoaded] = useState(false);

  // Live Cost Calculator state - ALWAYS from Pydantic config
  const [costProvider, setCostProvider] = useState('openai');
  const [costModel, setCostModel] = useState('');
  const [costEmbeddingProvider, setCostEmbeddingProvider] = useState('openai');
  const [costEmbeddingModel, setCostEmbeddingModel] = useState('');
  const [costRerankProvider, setCostRerankProvider] = useState('cohere');
  const [costRerankModel, setCostRerankModel] = useState('');

  // Load config values on mount - MUST come from Pydantic config
  useEffect(() => {
    if (config?.env && !configLoaded) {
      // Sync inference model from GEN_MODEL (required by Pydantic)
      if (config.env.GEN_MODEL) {
        setCostModel(config.env.GEN_MODEL);
      }
      // Sync embedding model from EMBEDDING_MODEL (required by Pydantic)
      if (config.env.EMBEDDING_MODEL) {
        setCostEmbeddingModel(config.env.EMBEDDING_MODEL);
      }
      // Sync rerank model from RERANKER_CLOUD_MODEL
      if (config.env.RERANKER_CLOUD_MODEL) {
        setCostRerankModel(config.env.RERANKER_CLOUD_MODEL);
      }
      setConfigLoaded(true);
    }
  }, [config?.env, configLoaded]);
  const [tokensIn, setTokensIn] = useState(5000);
  const [tokensOut, setTokensOut] = useState(800);
  const [embeds, setEmbeds] = useState(4);
  const [reranks, setReranks] = useState(3);
  const [costRequestsPerDay, setCostRequestsPerDay] = useState(100);
  const [dailyCost, setDailyCost] = useState('--');
  const [monthlyCost, setMonthlyCost] = useState('--');
  
  // Model lists from models.json
  const [providers, setProviders] = useState<string[]>([]);
  const [chatModels, setChatModels] = useState<string[]>([]);
  const [embedModels, setEmbedModels] = useState<string[]>([]);
  const [rerankModels, setRerankModels] = useState<string[]>([]);

  // Quick Profile state
  const [selectedProfile, setSelectedProfile] = useState('High Accuracy');

  // Storage state
  const [storageUsed, setStorageUsed] = useState(0);
  const [storageTotal, setStorageTotal] = useState(100);
  const [storagePercent, setStoragePercent] = useState(0);

  // Load providers and models from models.json
  useEffect(() => {
    async function loadModels() {
      try {
        const providersList = await CostLogic.listProviders();
        setProviders(providersList);
        
        if (providersList.length > 0 && !costProvider) {
          setCostProvider(providersList[0]);
        }
      } catch (e) {
        console.error('[Sidepanel] Failed to load providers:', e);
      }
    }
    loadModels();
  }, []);

  // Load models when provider changes
  useEffect(() => {
    async function loadModelsForProvider() {
      if (!costProvider) return;
      try {
        const chat = await CostLogic.listModels(costProvider, 'chat');
        setChatModels(chat);
        if (chat.length > 0 && !chat.includes(costModel)) {
          setCostModel(chat[0]);
        }
      } catch (e) {
        console.error('[Sidepanel] Failed to load chat models:', e);
      }
    }
    loadModelsForProvider();
  }, [costProvider]);

  useEffect(() => {
    async function loadEmbedModels() {
      if (!costEmbeddingProvider) return;
      try {
        const embed = await CostLogic.listModels(costEmbeddingProvider, 'embed');
        setEmbedModels(embed);
        if (embed.length > 0 && !embed.includes(costEmbeddingModel)) {
          setCostEmbeddingModel(embed[0]);
        }
      } catch (e) {
        console.error('[Sidepanel] Failed to load embed models:', e);
      }
    }
    loadEmbedModels();
  }, [costEmbeddingProvider]);

  useEffect(() => {
    async function loadRerankModels() {
      if (!costRerankProvider) return;
      try {
        const rerank = await CostLogic.listModels(costRerankProvider, 'rerank');
        setRerankModels(rerank);
        if (rerank.length > 0 && !rerank.includes(costRerankModel)) {
          setCostRerankModel(rerank[0]);
        }
      } catch (e) {
        console.error('[Sidepanel] Failed to load rerank models:', e);
      }
    }
    loadRerankModels();
  }, [costRerankProvider]);

  // Load defaults from config store
  useEffect(() => {
    if (config?.env) {
      if (config.env.GEN_MODEL) setCostModel(config.env.GEN_MODEL);
      if (config.env.EMBEDDING_MODEL) setCostEmbeddingModel(config.env.EMBEDDING_MODEL);
      // Try to infer provider
      const genModel = config.env.GEN_MODEL?.toLowerCase() || '';
      if (genModel.includes('gpt')) setCostProvider('openai');
      else if (genModel.includes('claude')) setCostProvider('anthropic');
      else if (genModel.includes('gemini')) setCostProvider('google');
    }
  }, [config]);

  useEffect(() => {
    setStoragePercent(storageTotal > 0 ? Math.round((storageUsed / storageTotal) * 100) : 0);
  }, [storageUsed, storageTotal]);

  const handleCalculateCost = async () => {
    try {
      const response = await fetch('/api/cost/estimate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          gen_provider: costProvider,
          gen_model: costModel,
          tokens_in: tokensIn,
          tokens_out: tokensOut,
          embeds: embeds,
          reranks: reranks,
          requests_per_day: costRequestsPerDay,
          embed_provider: costEmbeddingProvider,
          embed_model: costEmbeddingModel,
          rerank_provider: costRerankProvider,
          rerank_model: costRerankModel,
        }),
      });

      if (response.ok) {
        const data = await response.json();
        setDailyCost(`$${(data.daily || 0).toFixed(2)}`);
        setMonthlyCost(`$${(data.monthly || 0).toFixed(2)}`);
      } else {
        const errorText = await response.text();
        console.error('[Sidepanel] Cost estimate failed:', errorText);
        setDailyCost('Error');
        setMonthlyCost('Error');
      }
    } catch (e) {
      console.error('[Sidepanel] Cost estimate error:', e);
      setDailyCost('Error');
      setMonthlyCost('Error');
    }
  };

  const handleApplyProfile = async () => {
    try {
      const response = await fetch('/api/profiles/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile_name: selectedProfile }),
      });

      if (response.ok) {
        alert('Profile applied successfully');
      } else {
        alert('Failed to apply profile');
      }
    } catch (e) {
      console.error('[Sidepanel] Apply profile error:', e);
      alert('Error applying profile');
    }
  };

  const handleSaveProfile = async () => {
    const profileName = prompt('Enter profile name:');
    if (!profileName) return;

    try {
      const response = await fetch('/api/profiles/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: profileName,
          config: {}, // Current config would be gathered from state
        }),
      });

      if (response.ok) {
        alert('Profile saved successfully');
      } else {
        alert('Failed to save profile');
      }
    } catch (e) {
      console.error('[Sidepanel] Save profile error:', e);
      alert('Error saving profile');
    }
  };


  const handleCleanUpStorage = async () => {
    if (!confirm('Clean up storage (remove old indexes, caches)?')) return;

    try {
      const response = await fetch('/api/storage/cleanup', { method: 'POST' });
      if (response.ok) {
        const data = await response.json();
        alert(`Cleaned up ${data.bytes_freed || 0} bytes`);
      } else {
        alert('Cleanup failed');
      }
    } catch (e) {
      console.error('[Sidepanel] Cleanup error:', e);
      alert('Storage cleanup not available');
    }
  };

  const handleApplyChanges = async () => {
    try {
      const envUpdates: Record<string, string> = {};

      // Generation
      if (costModel) envUpdates.GEN_MODEL = costModel;

      // Embedding
      if (costEmbeddingModel) envUpdates.EMBEDDING_MODEL = costEmbeddingModel;
      if (costEmbeddingProvider) {
        const p = costEmbeddingProvider.toLowerCase();
        if (['local', 'ollama', 'huggingface'].includes(p)) {
          envUpdates.EMBEDDING_TYPE = 'local';
        } else {
          envUpdates.EMBEDDING_TYPE = p;
        }
      }

      // Reranker
      if (costRerankProvider) {
        const p = costRerankProvider.toLowerCase();
        if (p === 'cohere') {
          envUpdates.RERANKER_MODE = 'cloud';
          envUpdates.RERANKER_CLOUD_PROVIDER = 'cohere';
          envUpdates.RERANKER_CLOUD_MODEL = costRerankModel;
        } else if (p === 'voyage') {
          envUpdates.RERANKER_MODE = 'cloud';
          envUpdates.RERANKER_CLOUD_PROVIDER = 'voyage';
          envUpdates.RERANKER_CLOUD_MODEL = costRerankModel;
        } else if (['local', 'ollama', 'huggingface'].includes(p)) {
          envUpdates.RERANKER_MODE = 'local';
          envUpdates.RERANKER_LOCAL_MODEL = costRerankModel;
        }
      }

      // Send updates to backend
      const response = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          env: envUpdates
        }),
      });

      const payload = await response.json().catch(() => ({}));

      if (response.ok && payload?.status !== 'error') {
        alert('Changes applied successfully');
      } else {
        const detail = payload?.detail || payload?.error || 'Failed to apply changes';
        alert(detail);
      }
    } catch (e) {
      console.error('[Sidepanel] Apply changes error:', e);
      alert('Error applying changes');
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '16px' }}>
      {/* Embedding Mismatch Warning - Critical visibility */}
      <EmbeddingMismatchWarning variant="inline" showActions={true} />

      {/* Live Cost Calculator Widget */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '12px',
          }}
        >
          <span style={{ color: 'var(--accent)', fontSize: '8px' }}>●</span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
            Live Cost Calculator
          </span>
          <span
            style={{
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              fontSize: '9px',
              fontWeight: 600,
              padding: '2px 6px',
              borderRadius: '4px',
              marginLeft: 'auto',
            }}
          >
            LIVE
          </span>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                color: 'var(--fg-muted)',
                marginBottom: '4px',
              }}
            >
              INFERENCE PROVIDER
            </label>
            <select
              value={costProvider}
              onChange={(e) => setCostProvider(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '6px 8px',
                borderRadius: '4px',
              }}
            >
              {providers.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                color: 'var(--fg-muted)',
                marginBottom: '4px',
              }}
            >
              INFERENCE MODEL
            </label>
            <select
              value={costModel}
              onChange={(e) => setCostModel(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '6px 8px',
                borderRadius: '4px',
              }}
            >
              {chatModels.length > 0 ? (
                chatModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))
              ) : (
                <option value={costModel}>{costModel}</option>
              )}
            </select>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                EMBEDDINGS PROVIDER
              </label>
              <select
                value={costEmbeddingProvider}
                onChange={(e) => setCostEmbeddingProvider(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                EMBEDDING MODEL
              </label>
              <select
                value={costEmbeddingModel}
                onChange={(e) => setCostEmbeddingModel(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              >
                {embedModels.length > 0 ? (
                  embedModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={costEmbeddingModel}>{costEmbeddingModel}</option>
                )}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                RERANKER
              </label>
              <select
                value={costRerankProvider}
                onChange={(e) => setCostRerankProvider(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              >
                {providers.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                RERANK MODEL
              </label>
              <select
                value={costRerankModel}
                onChange={(e) => setCostRerankModel(e.target.value)}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              >
                {rerankModels.length > 0 ? (
                  rerankModels.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))
                ) : (
                  <option value={costRerankModel}>{costRerankModel}</option>
                )}
              </select>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                TOKENS IN
              </label>
              <input
                type="number"
                value={tokensIn}
                onChange={(e) => setTokensIn(Number(e.target.value))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              />
            </div>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                TOKENS OUT
              </label>
              <input
                type="number"
                value={tokensOut}
                onChange={(e) => setTokensOut(Number(e.target.value))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              />
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                EMBEDS
              </label>
              <input
                type="number"
                value={embeds}
                onChange={(e) => setEmbeds(Number(e.target.value))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              />
            </div>
            <div>
              <label
                style={{
                  display: 'block',
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                RERANKS
              </label>
              <input
                type="number"
                value={reranks}
                onChange={(e) => setReranks(Number(e.target.value))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '6px 8px',
                  borderRadius: '4px',
                }}
              />
            </div>
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '11px',
                color: 'var(--fg-muted)',
                marginBottom: '4px',
              }}
            >
              REQUESTS / DAY
            </label>
            <input
              type="number"
              value={costRequestsPerDay}
              onChange={(e) => setCostRequestsPerDay(Number(e.target.value))}
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '6px 8px',
                borderRadius: '4px',
              }}
            />
          </div>

          <button
            onClick={handleCalculateCost}
            style={{
              width: '100%',
              background: 'var(--link)',
              color: 'white',
              border: 'none',
              padding: '10px',
              borderRadius: '4px',
              fontWeight: 600,
              cursor: 'pointer',
              marginTop: '4px',
            }}
          >
            CALCULATE COST
          </button>

          <button
            style={{
              width: '100%',
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              border: 'none',
              padding: '10px',
              borderRadius: '4px',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            ADD MODEL
          </button>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '8px',
              marginTop: '8px',
            }}
          >
            <div>
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                DAILY
              </div>
              <div
                style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: 'var(--fg)',
                }}
              >
                {dailyCost}
              </div>
            </div>
            <div>
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  marginBottom: '4px',
                }}
              >
                MONTHLY
              </div>
              <div
                style={{
                  fontSize: '16px',
                  fontWeight: 600,
                  color: 'var(--fg)',
                }}
              >
                {monthlyCost}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Quick Profiles Widget - REMOVED (profiles are banned per CLAUDE.md) */}

      {/* Storage Widget */}
      <div
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            marginBottom: '12px',
          }}
        >
          <span style={{ color: 'var(--accent)', fontSize: '8px' }}>●</span>
          <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)' }}>
            Secrets Ingest
          </span>
        </div>

        <div
          style={{
            border: '2px dashed var(--line)',
            borderRadius: '6px',
            padding: '32px 16px',
            textAlign: 'center',
            color: 'var(--fg-muted)',
            fontSize: '12px',
            marginBottom: '8px',
          }}
        >
          Drop any .env / .ini / .md
          <br />
          or click to upload
        </div>

        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
          <input
            type="checkbox"
            defaultChecked
            style={{
              width: '16px',
              height: '16px',
              cursor: 'pointer',
            }}
          />
          <span style={{ fontSize: '11px', color: 'var(--fg)' }}>Persist to defaults.json</span>
        </label>
      </div>

      {/* Apply Changes Button - Always at bottom */}
      <div
        style={{
          marginTop: 'auto',
          paddingTop: '16px',
        }}
      >
        <button
          onClick={handleApplyChanges}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '14px',
            borderRadius: '6px',
            fontWeight: 700,
            fontSize: '14px',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
          }}
        >
          Apply Changes
        </button>
      </div>
    </div>
  );
}
