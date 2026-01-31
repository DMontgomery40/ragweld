// TriBrid - Chat Settings Component
// Configures chat-related TriBridConfig fields (Pydantic is the law).

import { useEffect, useState } from 'react';
import { useAPI, useConfig, useConfigField } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

const DEFAULT_SYSTEM_PROMPT =
  'You are a helpful AI assistant that answers questions about codebases using RAG (Retrieval-Augmented Generation). Provide accurate, concise answers with citations.';

export function ChatSettings() {
  const { api } = useAPI();
  const { config, saveConfig } = useConfig();

  const [saving, setSaving] = useState(false);
  const [saveStatus, setSaveStatus] = useState<string>('');
  const [modelOptions, setModelOptions] = useState<string[]>([]);

  // Core behavior
  const [systemPrompt, setSystemPrompt] = useConfigField<string>(
    'system_prompts.main_rag_chat',
    DEFAULT_SYSTEM_PROMPT
  );
  const [chatDefaultModel, setChatDefaultModel] = useConfigField<string>(
    'ui.chat_default_model',
    'gpt-4o-mini'
  );

  // Generation knobs (affect answer generation where supported)
  const [temperature, setTemperature] = useConfigField<number>('generation.gen_temperature', 0.0);
  const [maxTokens, setMaxTokens] = useConfigField<number>('generation.gen_max_tokens', 2048);
  const [topP, setTopP] = useConfigField<number>('generation.gen_top_p', 1.0);

  // Retrieval knobs
  const [finalK, setFinalK] = useConfigField<number>('retrieval.final_k', 10);

  // UI toggles
  const [streamingEnabled, setStreamingEnabled] = useConfigField<number>('ui.chat_streaming_enabled', 1);
  const [showConfidence, setShowConfidence] = useConfigField<number>('ui.chat_show_confidence', 0);
  const [showCitations, setShowCitations] = useConfigField<number>('ui.chat_show_citations', 1);
  const [showTrace, setShowTrace] = useConfigField<number>('ui.chat_show_trace', 0);

  // Load model options on mount
  useEffect(() => {
    (async () => {
      try {
        const r = await fetch(api('/api/models'));
        if (!r.ok) return;
        const d = await r.json();
        const list: string[] = (d.models || [])
          .map((m: any) => String(m.model || '').trim())
          .filter(Boolean);
        const uniq = Array.from(new Set(list));
        uniq.sort((a, b) => {
          const ao = a.toLowerCase().includes('gpt') ? 0 : 1;
          const bo = b.toLowerCase().includes('gpt') ? 0 : 1;
          return ao - bo || a.localeCompare(b);
        });
        setModelOptions(uniq);
      } catch {
        // Silent fallback to free-text input
      }
    })();
  }, [api]);

  const handleSave = async () => {
    if (!config) return;
    setSaving(true);
    setSaveStatus('');
    try {
      await saveConfig(config);
      setSaveStatus('Saved!');
      setTimeout(() => setSaveStatus(''), 2000);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      setSaveStatus(`Save failed: ${message}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ padding: '20px' }}>
      <h3 style={{ marginTop: 0 }}>Chat Settings</h3>

      {saveStatus && (
        <div style={{ fontSize: '12px', color: saveStatus.startsWith('Save failed') ? 'var(--err)' : 'var(--ok)' }}>
          {saveStatus}
        </div>
      )}

      <div className="settings-section" style={{ borderLeft: '3px solid var(--warn)' }}>
        <h3>Model & Prompt</h3>

        <div className="input-row">
          <div className="input-group">
            <label>
              Default Chat Model <TooltipIcon name="chat_default_model" />
            </label>
            {modelOptions.length ? (
              <select value={chatDefaultModel} onChange={(e) => setChatDefaultModel(e.target.value)}>
                {modelOptions.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={chatDefaultModel}
                onChange={(e) => setChatDefaultModel(e.target.value)}
                placeholder="e.g. gpt-4o-mini"
              />
            )}
          </div>
        </div>

        <div className="input-row">
          <div className="input-group full-width">
            <label>
              System Prompt <TooltipIcon name="main_rag_chat" />
            </label>
            <textarea
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              rows={6}
              style={{ width: '100%' }}
            />
          </div>
        </div>
      </div>

      <div className="settings-section" style={{ borderLeft: '3px solid var(--link)' }}>
        <h3>Generation</h3>
        <div className="input-row">
          <div className="input-group">
            <label>Temperature</label>
            <input
              type="number"
              value={temperature}
              step="0.1"
              min="0"
              max="2"
              onChange={(e) => setTemperature(Number(e.target.value))}
            />
          </div>
          <div className="input-group">
            <label>Top P</label>
            <input
              type="number"
              value={topP}
              step="0.05"
              min="0"
              max="1"
              onChange={(e) => setTopP(Number(e.target.value))}
            />
          </div>
          <div className="input-group">
            <label>Max Tokens</label>
            <input
              type="number"
              value={maxTokens}
              min="128"
              max="8192"
              onChange={(e) => setMaxTokens(Number(e.target.value))}
            />
          </div>
        </div>
      </div>

      <div className="settings-section" style={{ borderLeft: '3px solid var(--accent)' }}>
        <h3>Retrieval</h3>
        <div className="input-row">
          <div className="input-group">
            <label>Final K</label>
            <input
              type="number"
              value={finalK}
              min="1"
              max="200"
              onChange={(e) => setFinalK(Number(e.target.value))}
            />
            <p className="small">Number of retrieved chunks used for answering (higher = more context, slower).</p>
          </div>
        </div>
      </div>

      <div className="settings-section" style={{ borderLeft: '3px solid var(--ok)' }}>
        <h3>UI</h3>
        <div className="input-row">
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={streamingEnabled === 1}
                onChange={(e) => setStreamingEnabled(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">Enable streaming</span>
            </label>
          </div>
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={showCitations === 1}
                onChange={(e) => setShowCitations(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">Show citations</span>
            </label>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={showConfidence === 1}
                onChange={(e) => setShowConfidence(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">Show confidence</span>
            </label>
          </div>
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={showTrace === 1}
                onChange={(e) => setShowTrace(e.target.checked ? 1 : 0)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">Show routing trace</span>
            </label>
          </div>
        </div>
      </div>

      <div className="input-row" style={{ marginTop: '24px' }}>
        <button
          className="small-button"
          onClick={handleSave}
          disabled={saving || !config}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            fontWeight: 600,
          }}
        >
          {saving ? 'Saving…' : 'Save Chat Settings'}
        </button>
      </div>
    </div>
  );
}

export default ChatSettings;

