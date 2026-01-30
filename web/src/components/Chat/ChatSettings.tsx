// AGRO - Chat Settings Component
// Configuration for chat model, behavior, and display options

import { useState, useEffect } from 'react';
import { useAPI, useConfig } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

interface ChatConfig {
  systemPrompt: string;
  model: string;
  temperature: number;
  maxTokens: number;
  topP: number;
  finalK: number;
  frequencyPenalty: number;
  presencePenalty: number;
  streaming: boolean;
  showConfidence: boolean;
  showCitations: boolean;
  showTrace: boolean;
  autoSave: boolean;
}

const DEFAULT_SYSTEM_PROMPT =
  'You are a helpful AI assistant that answers questions about codebases using RAG (Retrieval-Augmented Generation). Provide accurate, concise answers with citations.';

export function ChatSettings() {
  const { api } = useAPI();
  const { get, set, env } = useConfig();
  const [config, setConfig] = useState<ChatConfig>(() => ({
    systemPrompt: get('PROMPT_MAIN_RAG_CHAT', DEFAULT_SYSTEM_PROMPT),
    model: get('GEN_MODEL', ''),
    temperature: get('GEN_TEMPERATURE', 0),
    maxTokens: get('GEN_MAX_TOKENS', 1000),
    topP: get('GEN_TOP_P', 1),
    finalK: get('FINAL_K', 10),
    topK: get('FINAL_K', 10),
    frequencyPenalty: 0,
    presencePenalty: 0,
    streaming: Boolean(get('CHAT_STREAMING_ENABLED', 1)),
    showConfidence: Boolean(get('CHAT_SHOW_CONFIDENCE', 0)),
    showCitations: Boolean(get('CHAT_SHOW_CITATIONS', 1)),
    showTrace: Boolean(get('CHAT_SHOW_TRACE', 0)),
    autoSave: true
  }));
  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string>('');
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const broadcastConfig = (cfg: ChatConfig) => {
    window.dispatchEvent(new CustomEvent('agro-chat-config-updated', { detail: cfg }));
  };

  // Load model options on mount
  useEffect(() => {
    loadModelOptions();
  }, []);

  // Sync form with Pydantic/Zustand config
  useEffect(() => {
    setConfig(prev => ({
      ...prev,
      systemPrompt: get('PROMPT_MAIN_RAG_CHAT', prev.systemPrompt || DEFAULT_SYSTEM_PROMPT),
      model: get('GEN_MODEL', prev.model),
      temperature: get('GEN_TEMPERATURE', prev.temperature),
      maxTokens: get('GEN_MAX_TOKENS', prev.maxTokens),
      topP: get('GEN_TOP_P', prev.topP),
      finalK: get('FINAL_K', prev.finalK),
      topK: get('FINAL_K', prev.topK),
      streaming: Boolean(get('CHAT_STREAMING_ENABLED', prev.streaming ? 1 : 0)),
      showConfidence: Boolean(get('CHAT_SHOW_CONFIDENCE', prev.showConfidence ? 1 : 0)),
      showCitations: Boolean(get('CHAT_SHOW_CITATIONS', prev.showCitations ? 1 : 0)),
      showTrace: Boolean(get('CHAT_SHOW_TRACE', prev.showTrace ? 1 : 0)),
    }));
  }, [env, get]);

  const loadModelOptions = async () => {
    try {
      const r = await fetch(api('/api/models'));
      if (!r.ok) return;
      const d = await r.json();
      const list: string[] = (d.models || [])
        .filter((m: any) => {
          const comps = Array.isArray(m.components) ? m.components : [];
          const unit = String(m.unit || '').toLowerCase();
          return comps.includes('GEN') || unit === '1k_tokens' || unit === 'request';
        })
        .map((m: any) => String(m.model || '').trim())
        .filter(Boolean);
      const uniq = Array.from(new Set(list));
      // Put OpenAI/GPT family first for sanity; preserve others
      uniq.sort((a, b) => {
        const ao = a.toLowerCase().includes('gpt') ? 0 : 1;
        const bo = b.toLowerCase().includes('gpt') ? 0 : 1;
        return ao - bo || a.localeCompare(b);
      });
      setModelOptions(uniq);
    } catch (e) {
      // Silent fallback to text input
      console.debug('[ChatSettings] models fetch failed:', e);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveStatus('');

    try {
      set({
        GEN_MODEL: config.model,
        GEN_TEMPERATURE: config.temperature,
        GEN_MAX_TOKENS: config.maxTokens,
        GEN_TOP_P: config.topP,
        FINAL_K: config.finalK,
        CHAT_STREAMING_ENABLED: config.streaming ? 1 : 0,
        CHAT_SHOW_CONFIDENCE: config.showConfidence ? 1 : 0,
        CHAT_SHOW_CITATIONS: config.showCitations ? 1 : 0,
        CHAT_SHOW_TRACE: config.showTrace ? 1 : 0,
        CHAT_DEFAULT_MODEL: config.model,
        PROMPT_MAIN_RAG_CHAT: config.systemPrompt,
      });
      setSaveStatus('Settings saved successfully!');
      broadcastConfig(config);
    } catch (error) {
      console.error('[ChatSettings] Failed to save config:', error);
      setSaveStatus('Failed to save settings');
    } finally {
      setSaving(false);
      setTimeout(() => setSaveStatus(''), 3000);
    }
  };

  const handleReset = () => {
    if (confirm('Reset all chat settings to defaults?')) {
      const resetConfig: ChatConfig = {
        systemPrompt: DEFAULT_SYSTEM_PROMPT,
        model: get('GEN_MODEL', ''),
        temperature: 0,
        maxTokens: 1000,
        topP: 1,
        finalK: 10,
        frequencyPenalty: 0,
        presencePenalty: 0,
        streaming: true,
        showConfidence: false,
        showCitations: true,
        showTrace: false,
        autoSave: true
      };
      setConfig(resetConfig);
      set({
        GEN_MODEL: resetConfig.model,
        GEN_TEMPERATURE: resetConfig.temperature,
        GEN_MAX_TOKENS: resetConfig.maxTokens,
        GEN_TOP_P: resetConfig.topP,
        FINAL_K: resetConfig.finalK,
        CHAT_STREAMING_ENABLED: resetConfig.streaming ? 1 : 0,
        CHAT_SHOW_CONFIDENCE: resetConfig.showConfidence ? 1 : 0,
        CHAT_SHOW_CITATIONS: resetConfig.showCitations ? 1 : 0,
        CHAT_SHOW_TRACE: resetConfig.showTrace ? 1 : 0,
        CHAT_DEFAULT_MODEL: resetConfig.model,
        PROMPT_MAIN_RAG_CHAT: resetConfig.systemPrompt,
      });
      setSaveStatus('Settings reset to defaults');
      broadcastConfig(resetConfig);
      setTimeout(() => setSaveStatus(''), 3000);
    }
  };

  const handleUseDefault = () => {
    setConfig(prev => ({ ...prev, systemPrompt: DEFAULT_SYSTEM_PROMPT }));
  };

  const handleSaveAsTemplate = async () => {
    const templateName = prompt('Enter template name:');
    if (!templateName) return;

    try {
      await fetch(api('chat/templates'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: templateName,
          prompt: config.systemPrompt
        })
      });
      alert(`Template "${templateName}" saved!`);
    } catch (error) {
      console.error('[ChatSettings] Failed to save template:', error);
      alert('Failed to save template');
    }
  };

  return (
    <div style={{
      maxWidth: '900px',
      margin: '0 auto',
      padding: '24px'
    }}>
      <h2 style={{
        margin: '0 0 24px 0',
        fontSize: '20px',
        fontWeight: '600',
        color: 'var(--fg)'
      }}>
        Chat Settings
      </h2>

      {/* System Prompt Section */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--fg)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px'
        }}>
          System Prompt
          <TooltipIcon name="PROMPT_MAIN_RAG_CHAT" />
        </h3>

        <textarea
          id="chat-system-prompt"
          value={config.systemPrompt}
          onChange={(e) => setConfig(prev => ({ ...prev, systemPrompt: e.target.value }))}
          style={{
            width: '100%',
            background: 'var(--input-bg)',
            border: '1px solid var(--line)',
            color: 'var(--fg)',
            padding: '12px',
            borderRadius: '4px',
            fontSize: '13px',
            fontFamily: 'inherit',
            resize: 'vertical',
            minHeight: '120px',
            marginBottom: '12px'
          }}
          placeholder="Enter system prompt..."
          aria-label="System prompt"
        />

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleUseDefault}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '8px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer'
            }}
          >
            Use Default
          </button>
          <button
            onClick={handleSaveAsTemplate}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--accent)',
              border: '1px solid var(--accent)',
              padding: '8px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: '600',
              cursor: 'pointer'
            }}
          >
            Save as Template
          </button>
        </div>
      </div>

      {/* Model Configuration */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          Model Configuration
        </h3>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Model
              <TooltipIcon name="GEN_MODEL" />
            </label>
            {modelOptions.length > 0 ? (
              <select
                id="chat-model"
                value={config.model}
                onChange={(e) => setConfig(prev => ({ ...prev, model: e.target.value }))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '13px'
                }}
              >
                {modelOptions.map(m => (<option key={m} value={m}>{m}</option>))}
              </select>
            ) : (
              <input
                type="text"
                id="chat-model"
                value={config.model}
                onChange={(e) => setConfig(prev => ({ ...prev, model: e.target.value }))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '13px'
                }}
                placeholder=""
              />
            )}
          </div>

          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Max Tokens (1-32000)
              <TooltipIcon name="GEN_MAX_TOKENS" />
            </label>
            <input
              type="number"
              id="chat-max-tokens"
              value={config.maxTokens}
              onChange={(e) => setConfig(prev => ({ ...prev, maxTokens: parseInt(e.target.value) || 1000 }))}
              min="1"
              max="32000"
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }} title="Final K: number of results to keep after fusion and reranking. Higher = broader context, more latency.">
              Final K (results)
              <TooltipIcon name="FINAL_K" />
            </label>
            <input
              type="number"
              id="chat-final-k"
              value={config.finalK}
              onChange={(e) => setConfig(prev => ({ ...prev, finalK: Math.max(1, parseInt(e.target.value) || 10) }))}
              min="1"
              max="200"
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            />
          </div>
          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Top-K (results)
              <TooltipIcon name="FINAL_K" />
            </label>
              <input
                type="number"
                id="chat-top-k"
                value={config.topK}
                onChange={(e) => setConfig(prev => ({ ...prev, topK: Math.max(1, parseInt(e.target.value) || 10) }))}
                min="1"
                max="100"
              style={{
                width: '100%',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px 12px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            />
          </div>

          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Temperature
              <TooltipIcon name="GEN_TEMPERATURE" />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px', gap: '8px', alignItems: 'center' }}>
              <input
                type="range"
                min="0"
                max="2"
                step="0.1"
                value={config.temperature}
                onChange={(e) => setConfig(prev => ({ ...prev, temperature: parseFloat(e.target.value) }))}
                style={{ width: '100%' }}
                aria-label="Temperature"
              />
              <input
                id="chat-temperature"
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={config.temperature}
                onChange={(e) => setConfig(prev => ({ ...prev, temperature: Math.max(0, Math.min(2, parseFloat(e.target.value) || 0)) }))}
                style={{
                  width: '100%',
                  background: 'var(--input-bg)',
                  border: '1px solid var(--line)',
                  color: 'var(--fg)',
                  padding: '8px 12px',
                  borderRadius: '4px',
                  fontSize: '13px'
                }}
                aria-label="Temperature input"
              />
            </div>
          </div>

          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Top-p: {config.topP.toFixed(2)}
              <TooltipIcon name="GEN_TOP_P" />
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={config.topP}
              onChange={(e) => setConfig(prev => ({ ...prev, topP: parseFloat(e.target.value) }))}
              style={{ width: '100%' }}
            />
          </div>

          {/* Duplicate Top-K removed; single control above with id=chat-top-k */}

          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Frequency Penalty: {config.frequencyPenalty.toFixed(1)}
              <TooltipIcon name="FREQUENCY_PENALTY" />
            </label>
            <input
              type="range"
              min="-2"
              max="2"
              step="0.1"
              value={config.frequencyPenalty}
              onChange={(e) => setConfig(prev => ({ ...prev, frequencyPenalty: parseFloat(e.target.value) }))}
              style={{ width: '100%' }}
            />
          </div>

          <div>
            <label style={{
              display: 'block',
              fontSize: '12px',
              fontWeight: '600',
              color: 'var(--fg-muted)',
              marginBottom: '6px',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}>
              Presence Penalty: {config.presencePenalty.toFixed(1)}
              <TooltipIcon name="PRESENCE_PENALTY" />
            </label>
            <input
              type="range"
              min="-2"
              max="2"
              step="0.1"
              value={config.presencePenalty}
              onChange={(e) => setConfig(prev => ({ ...prev, presencePenalty: parseFloat(e.target.value) }))}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </div>

      {/* Chat Behavior */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '6px',
        padding: '20px',
        marginBottom: '24px'
      }}>
        <h3 style={{
          margin: '0 0 16px 0',
          fontSize: '16px',
          fontWeight: '600',
          color: 'var(--fg)'
        }}>
          Chat Behavior
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }} title="Stream tokens as they generate (requires streaming backend)">
            <input
              id="chat-streaming"
              type="checkbox"
              checked={config.streaming}
              onChange={(e) => setConfig(prev => ({ ...prev, streaming: e.target.checked }))}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Enable streaming responses
            <TooltipIcon name="CHAT_STREAMING_ENABLED" />
          </label>

          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }} title="Show retrieval trace steps beneath chat responses">
            <input
              id="chat-show-trace"
              type="checkbox"
              checked={config.showTrace}
              onChange={(e) => setConfig(prev => ({ ...prev, showTrace: e.target.checked }))}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Show routing trace
            <TooltipIcon name="CHAT_SHOW_TRACE" />
          </label>

          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }} title="Prefix answers with confidence when available">
            <input
              id="chat-show-confidence"
              type="checkbox"
              checked={config.showConfidence}
              onChange={(e) => setConfig(prev => ({ ...prev, showConfidence: e.target.checked }))}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Show confidence score
            <TooltipIcon name="CHAT_SHOW_CONFIDENCE" />
          </label>

          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }} title="Toggle citations under each answer">
            <input
              id="chat-show-citations"
              type="checkbox"
              checked={config.showCitations}
              onChange={(e) => setConfig(prev => ({ ...prev, showCitations: e.target.checked }))}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Show citations
            <TooltipIcon name="CHAT_SHOW_CITATIONS" />
          </label>

          <label style={{
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            cursor: 'pointer',
            fontSize: '13px'
          }}>
            <input
              type="checkbox"
              checked={config.autoSave}
              onChange={(e) => setConfig(prev => ({ ...prev, autoSave: e.target.checked }))}
              style={{ width: '16px', height: '16px', cursor: 'pointer' }}
            />
            Auto-save conversations
            <span style={{ fontSize: '11px', color: 'var(--fg-muted)', marginLeft: 'auto' }}>
              (saves to browser storage)
            </span>
          </label>
        </div>
      </div>

      {/* Action Buttons */}
      <div style={{
        display: 'flex',
        gap: '12px',
        justifyContent: 'flex-end'
      }}>
        <button
          id="chat-reset-settings"
          onClick={handleReset}
          style={{
            background: 'var(--bg-elev2)',
            color: 'var(--err)',
            border: '1px solid var(--err)',
            padding: '10px 20px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: 'pointer'
          }}
        >
          Reset to Defaults
        </button>

        <button
          id="chat-save-settings"
          onClick={handleSave}
          disabled={saving}
          style={{
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '10px 20px',
            borderRadius: '6px',
            fontSize: '14px',
            fontWeight: '600',
            cursor: saving ? 'wait' : 'pointer',
            opacity: saving ? 0.7 : 1
          }}
        >
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>

      {saveStatus && (
        <div style={{
          marginTop: '16px',
          padding: '12px',
          background: 'var(--success)',
          color: 'white',
          borderRadius: '6px',
          fontSize: '13px',
          textAlign: 'center'
        }}>
          {saveStatus}
        </div>
      )}
    </div>
  );
}
