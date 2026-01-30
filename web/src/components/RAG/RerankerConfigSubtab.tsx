import { useEffect, useState, useCallback, useMemo } from 'react';
import { useConfig } from '@/hooks';
import { useReranker } from '@/hooks/useReranker';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

// CostLogic is loaded globally from cost_logic.js
declare global {
  interface Window {
    CostLogic: {
      listProviders: () => Promise<string[]>;
      listModels: (provider: string, type?: string) => Promise<string[]>;
    };
  }
}

/**
 * RerankerConfigSubtab - Unified Reranker Configuration
 * 
 * Supports 4 modes:
 * - none: Reranking disabled
 * - local: Any local reranker model (RERANKER_LOCAL_MODEL)
 * - learning: AGRO self-learning cross-encoder (AGRO_RERANKER_MODEL_PATH)
 * - cloud: External API (RERANKER_CLOUD_PROVIDER + RERANKER_CLOUD_MODEL)
 * 
 * All model lists loaded from models.json via CostLogic (same as sidepanel).
 */

interface RerankerInfo {
  reranker_mode?: string;
  reranker_cloud_provider?: string;
  reranker_cloud_model?: string;
  reranker_local_model?: string;
  path?: string;
  device?: string;
  alpha?: number;
  topn?: number;
  batch?: number;
  maxlen?: number;
  snippet_chars?: number;
  trust_remote_code?: boolean;
}

const RERANKER_MODES = ['none', 'local', 'learning', 'cloud'] as const;
type RerankerMode = typeof RERANKER_MODES[number];

export function RerankerConfigSubtab() {
  const { get, set, error: configError } = useConfig();
  const { getInfo } = useReranker();
  
  // Live server state
  const [serverInfo, setServerInfo] = useState<RerankerInfo | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(true);
  const [infoError, setInfoError] = useState<string | null>(null);
  
  // Models from models.json via CostLogic (same source as sidepanel)
  const [allProviders, setAllProviders] = useState<string[]>([]);
  const [rerankModels, setRerankModels] = useState<string[]>([]);
  const [localModels, setLocalModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  
  // Custom model input state
  const [customLocalModel, setCustomLocalModel] = useState('');
  
  // API key status (checked via backend, never exposed)
  const [apiKeyConfigured, setApiKeyConfigured] = useState<boolean | null>(null);
  
  // Current mode from config
  const currentMode = String(get('RERANKER_MODE', 'local')) as RerankerMode;
  const currentProvider = String(get('RERANKER_CLOUD_PROVIDER', ''));
  const currentCloudModel = String(get('RERANKER_CLOUD_MODEL', ''));
  const currentLocalModel = String(get('RERANKER_LOCAL_MODEL', ''));
  const currentLearningPath = String(get('AGRO_RERANKER_MODEL_PATH', 'models/cross-encoder-agro'));
  const snippetChars = Number(get('RERANK_INPUT_SNIPPET_CHARS', 700));
  const trustRemoteCode = String(get('TRANSFORMERS_TRUST_REMOTE_CODE', '1'));
  
  // API keys are in .env ONLY - not in config
  // Check via backend endpoint whether keys are configured (never expose values)
  useEffect(() => {
    if (currentMode === 'cloud' && currentProvider) {
      const keyName = (() => {
        switch (currentProvider.toLowerCase()) {
          case 'cohere': return 'COHERE_API_KEY';
          case 'voyage': return 'VOYAGE_API_KEY';
          case 'jina': return 'JINA_API_KEY';
          default: return `${currentProvider.toUpperCase()}_API_KEY`;
        }
      })();
      
      // Check via API - only returns true/false, never the actual key
      fetch(`/api/secrets/check?keys=${keyName}`)
        .then(r => r.json())
        .then(data => {
          setApiKeyConfigured(data[keyName] === true);
        })
        .catch(() => setApiKeyConfigured(null));
    } else {
      setApiKeyConfigured(null);
    }
  }, [currentMode, currentProvider]);

  // Load reranker info from server
  const loadServerInfo = useCallback(async () => {
    setLoadingInfo(true);
    setInfoError(null);
    try {
      const info = await getInfo();
      setServerInfo(info as RerankerInfo);
    } catch (e: any) {
      console.error('[RerankerConfig] Failed to load info:', e);
      setInfoError(e?.message || 'Failed to load reranker info');
    } finally {
      setLoadingInfo(false);
    }
  }, [getInfo]);

  // Load providers from models.json via CostLogic (same as sidepanel)
  const loadProviders = useCallback(async () => {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const providers = await window.CostLogic.listProviders();
      setAllProviders(providers);
      
      // Also load local models
      const local = await window.CostLogic.listModels('Local', 'rerank');
      setLocalModels(local);
    } catch (e: any) {
      console.error('[RerankerConfig] Failed to load providers:', e);
      setModelsError(e?.message || 'Failed to load model providers');
    } finally {
      setModelsLoading(false);
    }
  }, []);

  // Load rerank models when provider changes
  const loadRerankModels = useCallback(async (provider: string) => {
    if (!provider) {
      setRerankModels([]);
      return;
    }
    try {
      const models = await window.CostLogic.listModels(provider, 'rerank');
      setRerankModels(models);
      // Auto-select first model if current not in list
      if (models.length > 0 && !models.includes(currentCloudModel)) {
        set('RERANKER_CLOUD_MODEL', models[0]);
      }
    } catch (e: any) {
      console.error('[RerankerConfig] Failed to load rerank models:', e);
      setRerankModels([]);
    }
  }, [currentCloudModel, set]);

  useEffect(() => {
    loadServerInfo();
    loadProviders();
  }, [loadServerInfo, loadProviders]);

  // Reload rerank models when provider changes
  useEffect(() => {
    if (currentProvider) {
      loadRerankModels(currentProvider);
    }
  }, [currentProvider, loadRerankModels]);

  // Filter providers that have rerank models
  const rerankProviders = useMemo(() => {
    // The sidepanel shows all providers, then filters models by type
    // We do the same - show all providers, the model dropdown will be empty if no rerank models
    return allProviders.filter(p => p !== 'Local');
  }, [allProviders]);

  // API key config name for display
  const apiKeyEnvName = useMemo(() => {
    switch (currentProvider.toLowerCase()) {
      case 'cohere': return 'COHERE_API_KEY';
      case 'voyage': return 'VOYAGE_API_KEY';
      case 'jina': return 'JINA_API_KEY';
      default: return `${currentProvider.toUpperCase()}_API_KEY`;
    }
  }, [currentProvider]);


  // Handle mode change
  const handleModeChange = (mode: RerankerMode) => {
    set('RERANKER_MODE', mode);
    
    // Set sensible defaults when switching modes
    if (mode === 'cloud' && !currentProvider && rerankProviders.length > 0) {
      set('RERANKER_CLOUD_PROVIDER', rerankProviders[0]);
    }
  };

  // Handle provider change
  const handleProviderChange = (provider: string) => {
    set('RERANKER_CLOUD_PROVIDER', provider);
    // Models will reload via useEffect
  };

  // Handle local model change
  const handleLocalModelChange = (value: string) => {
    if (value === 'custom') {
      setCustomLocalModel(currentLocalModel);
    } else {
      set('RERANKER_LOCAL_MODEL', value);
      setCustomLocalModel('');
    }
  };

  const getModeIcon = (mode: RerankerMode) => {
    switch (mode) {
      case 'none': return '🚫';
      case 'local': return '💻';
      case 'learning': return '🧠';
      case 'cloud': return '☁️';
    }
  };

  const getModeLabel = (mode: RerankerMode) => {
    switch (mode) {
      case 'none': return 'Disabled';
      case 'local': return 'Local';
      case 'learning': return 'Learning';
      case 'cloud': return 'Cloud';
    }
  };

  const getModeDescription = (mode: RerankerMode) => {
    switch (mode) {
      case 'none': return 'No reranking—BM25/vector fusion only';
      case 'local': return 'Any local reranker model (BGE, Jina, etc.)';
      case 'learning': return 'AGRO cross-encoder that trains on your usage';
      case 'cloud': return 'External API (Cohere, Voyage, Jina)';
    }
  };

  // Is current local model in the dropdown or custom?
  const isLocalModelCustom = currentLocalModel && !localModels.includes(currentLocalModel);

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      {/* Header */}
      <div style={{ marginBottom: '28px' }}>
        <h3 style={{ 
          fontSize: '18px', 
          fontWeight: 600, 
          color: 'var(--fg)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          marginBottom: '8px'
        }}>
          <span style={{ fontSize: '22px' }}>⚡</span>
          Reranker Configuration
          <TooltipIcon name="RERANKER_MODE" />
        </h3>
        <p style={{ 
          fontSize: '14px', 
          color: 'var(--fg-muted)', 
          lineHeight: 1.6,
          maxWidth: '800px'
        }}>
          Reranking improves retrieval precision by re-scoring candidates with a cross-encoder model.
          Choose the mode that fits your latency, cost, and quality requirements.
        </p>
      </div>

      {/* Mode Selection Cards */}
      <div style={{ 
        display: 'grid', 
        gridTemplateColumns: 'repeat(4, 1fr)', 
        gap: '16px',
        marginBottom: '32px'
      }}>
        {RERANKER_MODES.map(mode => (
          <button
            key={mode}
            onClick={() => handleModeChange(mode)}
            style={{
              padding: '20px 16px',
              background: currentMode === mode 
                ? 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.15), rgba(var(--accent-rgb), 0.05))'
                : 'var(--card-bg)',
              border: currentMode === mode 
                ? '2px solid var(--accent)' 
                : '1px solid var(--line)',
              borderRadius: '12px',
              cursor: 'pointer',
              textAlign: 'left',
              transition: 'all 0.2s ease',
              position: 'relative',
              overflow: 'hidden'
            }}
          >
            {currentMode === mode && (
              <div style={{
                position: 'absolute',
                top: '8px',
                right: '8px',
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                background: 'var(--accent)',
                boxShadow: '0 0 8px var(--accent)'
              }} />
            )}
            <div style={{ fontSize: '28px', marginBottom: '10px' }}>
              {getModeIcon(mode)}
            </div>
            <div style={{ 
              fontSize: '14px', 
              fontWeight: 600, 
              color: currentMode === mode ? 'var(--accent)' : 'var(--fg)',
              marginBottom: '6px'
            }}>
              {getModeLabel(mode)}
            </div>
            <div style={{ 
              fontSize: '12px', 
              color: 'var(--fg-muted)',
              lineHeight: 1.4
            }}>
              {getModeDescription(mode)}
            </div>
          </button>
        ))}
      </div>

      {/* Config error banner */}
      {(configError || modelsError) && (
        <div style={{
          background: 'rgba(var(--error-rgb), 0.1)',
          border: '1px solid var(--error)',
          borderRadius: '8px',
          padding: '12px 16px',
          marginBottom: '20px',
          color: 'var(--error)',
          fontSize: '13px'
        }}>
          {configError || modelsError}
        </div>
      )}

      {/* Mode-specific configuration panels */}
      <div style={{ 
        background: 'var(--card-bg)', 
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '24px'
      }}>
        {/* Disabled Mode */}
        {currentMode === 'none' && (
          <div style={{ textAlign: 'center', padding: '40px 20px' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px', opacity: 0.5 }}>🚫</div>
            <div style={{ fontSize: '16px', color: 'var(--fg-muted)' }}>
              Reranking is disabled. Results will use BM25 + vector fusion only.
            </div>
          </div>
        )}

        {/* Local Mode */}
        {currentMode === 'local' && (
          <div>
            <h4 style={{ 
              fontSize: '14px', 
              fontWeight: 600, 
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              💻 Local Reranker Model
            </h4>
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Model
                  <TooltipIcon name="RERANKER_LOCAL_MODEL" />
                </label>
                {localModels.length > 0 ? (
                  <select
                    value={isLocalModelCustom ? 'custom' : currentLocalModel}
                    onChange={(e) => handleLocalModelChange(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  >
                    <option value="">Select model...</option>
                    {localModels.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                    <option value="custom">Custom model path...</option>
                  </select>
                ) : (
                  <input
                    type="text"
                    value={currentLocalModel}
                    onChange={(e) => set('RERANKER_LOCAL_MODEL', e.target.value)}
                    placeholder="e.g., BAAI/bge-reranker-v2-m3"
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      fontFamily: 'var(--font-mono)'
                    }}
                  />
                )}
                {(isLocalModelCustom || customLocalModel !== '') && localModels.length > 0 && (
                  <input
                    type="text"
                    value={customLocalModel || currentLocalModel}
                    onChange={(e) => {
                      setCustomLocalModel(e.target.value);
                      set('RERANKER_LOCAL_MODEL', e.target.value);
                    }}
                    placeholder="e.g., /models/my-reranker or org/model-name"
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      marginTop: '8px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px',
                      fontFamily: 'var(--font-mono)'
                    }}
                  />
                )}
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Trust Remote Code
                  <TooltipIcon name="TRANSFORMERS_TRUST_REMOTE_CODE" />
                </label>
                <select
                  value={trustRemoteCode}
                  onChange={(e) => set('TRANSFORMERS_TRUST_REMOTE_CODE', e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                >
                  <option value="1">Yes (required for some models)</option>
                  <option value="0">No</option>
                </select>
              </div>
            </div>
            {localModels.length === 0 && !modelsLoading && (
              <p style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '12px' }}>
                No local rerank models found in models.json. Enter a HuggingFace model ID or local path above.
              </p>
            )}
          </div>
        )}

        {/* Learning Mode */}
        {currentMode === 'learning' && (
          <div>
            <h4 style={{ 
              fontSize: '14px', 
              fontWeight: 600, 
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              🧠 AGRO Learning Cross-Encoder
            </h4>
            <div style={{ 
              background: 'linear-gradient(135deg, rgba(var(--success-rgb), 0.1), transparent)',
              borderRadius: '8px',
              padding: '16px',
              marginBottom: '16px'
            }}>
              <p style={{ fontSize: '13px', color: 'var(--fg)', lineHeight: 1.6 }}>
                A <strong>sentence-transformers CrossEncoder</strong> that continuously trains on your usage.
                It mines triplets from click patterns and explicit feedback to optimize for your specific codebase.
                The model improves with every search interaction.
              </p>
            </div>
            <div className="input-group">
              <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                Model Path
                <TooltipIcon name="AGRO_RERANKER_MODEL_PATH" />
              </label>
              <input
                type="text"
                value={currentLearningPath}
                onChange={(e) => set('AGRO_RERANKER_MODEL_PATH', e.target.value)}
                placeholder="models/cross-encoder-agro"
                style={{
                  width: '100%',
                  maxWidth: '400px',
                  padding: '10px 12px',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  borderRadius: '6px',
                  color: 'var(--fg)',
                  fontSize: '13px',
                  fontFamily: 'var(--font-mono)'
                }}
              />
            </div>
            <p style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '12px' }}>
              Configure training parameters in the <strong>Learning Ranker</strong> subtab →
            </p>
          </div>
        )}

        {/* Cloud Mode */}
        {currentMode === 'cloud' && (
          <div>
            <h4 style={{ 
              fontSize: '14px', 
              fontWeight: 600, 
              color: 'var(--fg)',
              marginBottom: '16px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              ☁️ Cloud Reranking API
            </h4>
            <div className="input-row" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Provider
                  <TooltipIcon name="RERANKER_CLOUD_PROVIDER" />
                </label>
                <select
                  value={currentProvider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                  disabled={modelsLoading}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px'
                  }}
                >
                  <option value="">{modelsLoading ? 'Loading...' : 'Select provider...'}</option>
                  {rerankProviders.map(p => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
              <div className="input-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                  Model
                  <TooltipIcon name="RERANKER_CLOUD_MODEL" />
                </label>
                <select
                  value={currentCloudModel}
                  onChange={(e) => set('RERANKER_CLOUD_MODEL', e.target.value)}
                  disabled={!currentProvider || rerankModels.length === 0}
                  style={{
                    width: '100%',
                    padding: '10px 12px',
                    background: 'var(--input-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    color: 'var(--fg)',
                    fontSize: '13px',
                    opacity: currentProvider && rerankModels.length > 0 ? 1 : 0.5
                  }}
                >
                  <option value="">
                    {!currentProvider ? 'Select provider first...' : 
                     rerankModels.length === 0 ? 'No rerank models for this provider' : 
                     'Select model...'}
                  </option>
                  {rerankModels.map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* API Key status - keys are in .env only, we only check if configured */}
            {currentProvider && (
              <div style={{ 
                marginBottom: '16px',
                padding: '12px 16px',
                background: apiKeyConfigured === true ? 'rgba(var(--ok-rgb), 0.1)' : 'rgba(var(--warn-rgb), 0.1)',
                borderRadius: '8px',
                border: `1px solid ${apiKeyConfigured === true ? 'var(--ok)' : 'var(--warn)'}`,
                fontSize: '12px',
              }}>
                <div style={{ 
                  display: 'flex', 
                  alignItems: 'center', 
                  gap: '8px',
                  marginBottom: '4px',
                  color: apiKeyConfigured === true ? 'var(--ok)' : 'var(--warn)'
                }}>
                  <span style={{ fontSize: '14px' }}>{apiKeyConfigured === true ? '✓' : '⚠'}</span>
                  <span style={{ fontWeight: 600 }}>
                    {apiKeyEnvName}: {apiKeyConfigured === true ? 'Configured' : 'Not configured'}
                  </span>
                </div>
                <div style={{ color: 'var(--fg-muted)' }}>
                  {apiKeyConfigured === true 
                    ? 'Key is set in .env file and ready to use.'
                    : <>Add <code style={{ 
                        background: 'var(--bg-elev2)', 
                        padding: '2px 6px', 
                        borderRadius: '4px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px'
                      }}>{apiKeyEnvName}=your_key</code> to your <code style={{ 
                        background: 'var(--bg-elev2)', 
                        padding: '2px 6px', 
                        borderRadius: '4px',
                        fontFamily: 'var(--font-mono)',
                        fontSize: '11px'
                      }}>.env</code> file.</>
                  }
                </div>
              </div>
            )}

            {rerankProviders.length === 0 && !modelsLoading && (
              <div style={{ 
                background: 'rgba(var(--warn-rgb), 0.1)', 
                border: '1px solid var(--warn)',
                borderRadius: '8px',
                padding: '12px 16px',
                fontSize: '13px',
                color: 'var(--warn)'
              }}>
                No cloud providers loaded. Check that the API server is running and models.json is accessible.
              </div>
            )}
          </div>
        )}
      </div>

      {/* Advanced Settings - MODE SPECIFIC */}
      {currentMode !== 'none' && (
        <details style={{ marginTop: '24px' }}>
          <summary style={{ 
            cursor: 'pointer', 
            fontSize: '14px', 
            fontWeight: 500,
            color: 'var(--fg-muted)',
            padding: '12px 0'
          }}>
            Advanced Settings
          </summary>
          <div style={{ 
            background: 'var(--card-bg)', 
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '20px',
            marginTop: '8px'
          }}>
            {/* CLOUD: Only cloud-relevant settings */}
            {currentMode === 'cloud' && (
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Top-N to Rerank (Cloud)
                    <TooltipIcon name="RERANKER_CLOUD_TOP_N" />
                  </label>
                  <input
                    type="number"
                    value={Number(get('RERANKER_CLOUD_TOP_N', 50))}
                    onChange={(e) => set('RERANKER_CLOUD_TOP_N', parseInt(e.target.value) || 50)}
                    min={1}
                    max={200}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  />
                  <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
                    Number of candidates to send to cloud API
                  </p>
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Timeout (seconds)
                    <TooltipIcon name="RERANKER_TIMEOUT" />
                  </label>
                  <input
                    type="number"
                    value={Number(get('RERANKER_TIMEOUT', 10))}
                    onChange={(e) => set('RERANKER_TIMEOUT', parseInt(e.target.value) || 10)}
                    min={5}
                    max={60}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  />
                </div>
              </div>
            )}

            {/* LOCAL: Local model settings */}
            {currentMode === 'local' && (
              <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Input Snippet Chars
                    <TooltipIcon name="RERANK_INPUT_SNIPPET_CHARS" />
                  </label>
                  <input
                    type="number"
                    value={snippetChars}
                    onChange={(e) => set('RERANK_INPUT_SNIPPET_CHARS', parseInt(e.target.value) || 700)}
                    min={100}
                    max={2000}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  />
                </div>
                <div className="input-group">
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                    Top-N Candidates
                    <TooltipIcon name="AGRO_RERANKER_TOPN" />
                  </label>
                  <input
                    type="number"
                    value={Number(get('AGRO_RERANKER_TOPN', 50))}
                    onChange={(e) => set('AGRO_RERANKER_TOPN', parseInt(e.target.value) || 50)}
                    min={10}
                    max={200}
                    style={{
                      width: '100%',
                      padding: '10px 12px',
                      background: 'var(--input-bg)',
                      border: '1px solid var(--line)',
                      borderRadius: '6px',
                      color: 'var(--fg)',
                      fontSize: '13px'
                    }}
                  />
                </div>
              </div>
            )}

            {/* LEARNING: Full learning reranker settings */}
            {currentMode === 'learning' && (
              <div>
                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '20px', marginBottom: '20px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Blend Alpha
                      <TooltipIcon name="AGRO_RERANKER_ALPHA" />
                    </label>
                    <input
                      type="number"
                      value={Number(get('AGRO_RERANKER_ALPHA', 0.7))}
                      onChange={(e) => set('AGRO_RERANKER_ALPHA', parseFloat(e.target.value) || 0.7)}
                      min={0}
                      max={1}
                      step={0.05}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                      }}
                    />
                    <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
                      Weight for learning score vs original
                    </p>
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Top-N Candidates
                      <TooltipIcon name="AGRO_RERANKER_TOPN" />
                    </label>
                    <input
                      type="number"
                      value={Number(get('AGRO_RERANKER_TOPN', 50))}
                      onChange={(e) => set('AGRO_RERANKER_TOPN', parseInt(e.target.value) || 50)}
                      min={10}
                      max={200}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Batch Size
                      <TooltipIcon name="AGRO_RERANKER_BATCH" />
                    </label>
                    <input
                      type="number"
                      value={Number(get('AGRO_RERANKER_BATCH', 16))}
                      onChange={(e) => set('AGRO_RERANKER_BATCH', parseInt(e.target.value) || 16)}
                      min={1}
                      max={64}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                      }}
                    />
                  </div>
                </div>
                <div className="input-row" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Max Token Length
                      <TooltipIcon name="AGRO_RERANKER_MAXLEN" />
                    </label>
                    <input
                      type="number"
                      value={Number(get('AGRO_RERANKER_MAXLEN', 512))}
                      onChange={(e) => set('AGRO_RERANKER_MAXLEN', parseInt(e.target.value) || 512)}
                      min={128}
                      max={2048}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                      }}
                    />
                  </div>
                  <div className="input-group">
                    <label style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                      Input Snippet Chars
                      <TooltipIcon name="RERANK_INPUT_SNIPPET_CHARS" />
                    </label>
                    <input
                      type="number"
                      value={snippetChars}
                      onChange={(e) => set('RERANK_INPUT_SNIPPET_CHARS', parseInt(e.target.value) || 700)}
                      min={100}
                      max={2000}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '6px',
                        color: 'var(--fg)',
                        fontSize: '13px'
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>
        </details>
      )}

      {/* Server Status - MODE SPECIFIC */}
      <div style={{ 
        marginTop: '32px',
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px'
      }}>
        <div style={{ 
          display: 'flex', 
          alignItems: 'center', 
          justifyContent: 'space-between',
          marginBottom: '12px'
        }}>
          <h4 style={{ fontSize: '13px', fontWeight: 600, color: 'var(--fg-muted)', margin: 0 }}>
            ACTIVE RERANKER (SERVER)
          </h4>
          <button
            onClick={loadServerInfo}
            disabled={loadingInfo}
            style={{
              padding: '4px 10px',
              fontSize: '11px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg-muted)',
              cursor: loadingInfo ? 'wait' : 'pointer'
            }}
          >
            {loadingInfo ? '...' : '↻ Refresh'}
          </button>
        </div>
        {serverInfo ? (
          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: '8px',
            fontSize: '12px',
            fontFamily: 'var(--font-mono)'
          }}>
            {/* Always show mode */}
            <div><span style={{ color: 'var(--fg-muted)' }}>Mode:</span> <span style={{ color: 'var(--accent)' }}>{serverInfo.reranker_mode || 'unknown'}</span></div>
            
            {/* Cloud-specific fields */}
            {serverInfo.reranker_mode === 'cloud' && (
              <>
                <div><span style={{ color: 'var(--fg-muted)' }}>Provider:</span> {serverInfo.reranker_cloud_provider || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>Model:</span> {serverInfo.reranker_cloud_model || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>TopN:</span> {serverInfo.topn ?? '—'}</div>
              </>
            )}
            
            {/* Local-specific fields */}
            {serverInfo.reranker_mode === 'local' && (
              <>
                <div><span style={{ color: 'var(--fg-muted)' }}>Model:</span> {serverInfo.reranker_local_model || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>Device:</span> {serverInfo.device || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>TopN:</span> {serverInfo.topn ?? '—'}</div>
              </>
            )}
            
            {/* Learning-specific fields */}
            {serverInfo.reranker_mode === 'learning' && (
              <>
                <div><span style={{ color: 'var(--fg-muted)' }}>Model:</span> {serverInfo.path || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>Device:</span> {serverInfo.device || '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>Alpha:</span> {serverInfo.alpha ?? '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>TopN:</span> {serverInfo.topn ?? '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>Batch:</span> {serverInfo.batch ?? '—'}</div>
                <div><span style={{ color: 'var(--fg-muted)' }}>MaxLen:</span> {serverInfo.maxlen ?? '—'}</div>
              </>
            )}
            
            {/* None mode - minimal info */}
            {serverInfo.reranker_mode === 'none' && (
              <div style={{ color: 'var(--fg-muted)', gridColumn: '1 / -1' }}>Reranking disabled</div>
            )}
          </div>
        ) : (
          <div style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>
            {loadingInfo ? 'Loading...' : infoError || 'Could not load reranker info'}
          </div>
        )}
      </div>
    </div>
  );
}
