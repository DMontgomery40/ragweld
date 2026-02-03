import { useState } from 'react';
import { useConfig, useConfigField } from '@/hooks';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { ProviderSetup } from '@/components/Chat/ProviderSetup';
import type { ChatMultimodalConfig, RecallConfig, RecallGateConfig, RecallIntensity } from '@/types/generated';

const TABS = ['Model', 'Sources', 'Recall', 'Multimodal', 'Local', 'OpenRouter', 'Benchmark', 'UI'];

export function ChatSettings2() {
  const { config, loading, error, saving } = useConfig();
  const [activeTab, setActiveTab] = useState(TABS[0]);

  // Chat core
  const [systemPromptBase, setSystemPromptBase] = useConfigField(
    'chat.system_prompt_base',
    'You are a helpful assistant.'
  );
  const [systemPromptDirect, setSystemPromptDirect] = useConfigField('chat.system_prompt_direct', '');
  const [systemPromptRag, setSystemPromptRag] = useConfigField('chat.system_prompt_rag', '');
  const [systemPromptRecall, setSystemPromptRecall] = useConfigField('chat.system_prompt_recall', '');
  const [systemPromptRagAndRecall, setSystemPromptRagAndRecall] = useConfigField(
    'chat.system_prompt_rag_and_recall',
    ''
  );
  const [temperature, setTemperature] = useConfigField('chat.temperature', 0.3);
  const [temperatureNoRetrieval, setTemperatureNoRetrieval] = useConfigField('chat.temperature_no_retrieval', 0.7);
  const [maxTokens, setMaxTokens] = useConfigField('chat.max_tokens', 4096);

  // Recall (nested) — update the whole object to avoid shallow-merge clobbering.
  const [recall, setRecall] = useConfigField<RecallConfig>('chat.recall', {});
  const [recallAutoIndex] = useConfigField('chat.recall.auto_index', true);
  const [recallDelaySeconds] = useConfigField('chat.recall.index_delay_seconds', 5);

  // Recall gate (nested) — update the whole object to avoid shallow-merge clobbering.
  const [recallGate, setRecallGate] = useConfigField<RecallGateConfig>('chat.recall_gate', {});
  const gate = (recallGate || {}) as Partial<RecallGateConfig>;
  const gateEnabled = gate.enabled ?? true;
  const gateDefaultIntensity = (gate.default_intensity ?? 'standard') as RecallIntensity;
  const gateSkipGreetings = gate.skip_greetings ?? true;
  const gateSkipStandaloneQuestions = gate.skip_standalone_questions ?? true;
  const gateSkipWhenRagActive = gate.skip_when_rag_active ?? false;
  const gateSkipMaxTokens = Number(gate.skip_max_tokens ?? 4);
  const gateLightForShortQuestions = gate.light_for_short_questions ?? true;
  const gateLightTopK = Number(gate.light_top_k ?? 3);
  const gateStandardTopK = Number(gate.standard_top_k ?? 5);
  const gateStandardRecencyWeight = Number(gate.standard_recency_weight ?? 0.3);
  const gateDeepOnExplicitReference = gate.deep_on_explicit_reference ?? true;
  const gateDeepTopK = Number(gate.deep_top_k ?? 10);
  const gateDeepRecencyWeight = Number(gate.deep_recency_weight ?? 0.5);
  const gateShowDecision = gate.show_gate_decision ?? true;
  const gateShowSignals = gate.show_signals ?? false;

  // Multimodal (nested) — update the whole object to avoid shallow-merge clobbering.
  const [multimodal, setMultimodal] = useConfigField<ChatMultimodalConfig>('chat.multimodal', {});
  const [visionEnabled] = useConfigField('chat.multimodal.vision_enabled', true);

  // UI
  const [chatStreamingEnabled, setChatStreamingEnabled] = useConfigField('ui.chat_streaming_enabled', 1);

  const panel = (() => {
    switch (activeTab) {
      case 'Model':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <div style={{ marginBottom: 14 }}>
              <h3 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: 'var(--fg)' }}>Model</h3>
              <div style={{ marginTop: 6, fontSize: 13, color: 'var(--fg-muted)' }}>
                Prompt + generation knobs, plus provider configuration.
              </div>
            </div>

            <div className="input-row">
              <div className="input-group full-width">
                <label>
                  System prompt (base) <TooltipIcon name="chat.system_prompt_base" />
                </label>
                <textarea
                  value={systemPromptBase}
                  onChange={(e) => setSystemPromptBase(e.target.value)}
                  rows={6}
                  style={{ width: '100%' }}
                />
                <p className="small">
                  Used as the baseline prompt. Recall/RAG suffixes are appended automatically when those sources are
                  enabled.
                </p>
              </div>
            </div>

            <div style={{ marginTop: 18 }}>
              <h4 style={{ margin: '0 0 10px 0', fontSize: 14, fontWeight: 600, color: 'var(--fg)' }}>
                System prompts (4 states)
              </h4>
              <div style={{ marginBottom: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
                One of these is sent to the model based on whether RAG and/or Recall context is present.
                If a selected prompt is empty, the system falls back to the legacy base+suffix prompt composition.
              </div>

              <div className="input-row">
                <div className="input-group full-width">
                  <label>
                    Direct (no context) <TooltipIcon name="chat.system_prompt_direct" />
                  </label>
                  <textarea
                    value={systemPromptDirect}
                    onChange={(e) => setSystemPromptDirect(e.target.value)}
                    rows={6}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>

              <div className="input-row">
                <div className="input-group full-width">
                  <label>
                    RAG only <TooltipIcon name="chat.system_prompt_rag" />
                  </label>
                  <textarea
                    value={systemPromptRag}
                    onChange={(e) => setSystemPromptRag(e.target.value)}
                    rows={8}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>

              <div className="input-row">
                <div className="input-group full-width">
                  <label>
                    Recall only <TooltipIcon name="chat.system_prompt_recall" />
                  </label>
                  <textarea
                    value={systemPromptRecall}
                    onChange={(e) => setSystemPromptRecall(e.target.value)}
                    rows={8}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>

              <div className="input-row">
                <div className="input-group full-width">
                  <label>
                    RAG + Recall <TooltipIcon name="chat.system_prompt_rag_and_recall" />
                  </label>
                  <textarea
                    value={systemPromptRagAndRecall}
                    onChange={(e) => setSystemPromptRagAndRecall(e.target.value)}
                    rows={10}
                    style={{ width: '100%' }}
                  />
                </div>
              </div>
            </div>

            <div className="input-row">
              <div className="input-group">
                <label>
                  Temperature <TooltipIcon name="chat.temperature" />
                </label>
                <input
                  type="number"
                  value={temperature}
                  min="0"
                  max="2"
                  step="0.05"
                  onChange={(e) => setTemperature(Number(e.target.value))}
                />
              </div>

              <div className="input-group">
                <label>
                  Temperature (no retrieval) <TooltipIcon name="chat.temperature_no_retrieval" />
                </label>
                <input
                  type="number"
                  value={temperatureNoRetrieval}
                  min="0"
                  max="2"
                  step="0.05"
                  onChange={(e) => setTemperatureNoRetrieval(Number(e.target.value))}
                />
              </div>

              <div className="input-group">
                <label>
                  Max tokens <TooltipIcon name="chat.max_tokens" />
                </label>
                <input
                  type="number"
                  value={maxTokens}
                  min="100"
                  max="16384"
                  step="1"
                  onChange={(e) => setMaxTokens(Number(e.target.value))}
                />
              </div>
            </div>

            <div style={{ marginTop: 18 }}>
              <ProviderSetup />
            </div>
          </div>
        );

      case 'Sources':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>Sources</h3>
            <div style={{ color: 'var(--fg-muted)', fontSize: 13 }}>
              This tab is a placeholder for source selection defaults. Sources are primarily chosen per-conversation in
              the chat UI (e.g., Corpora + Recall).
            </div>
          </div>
        );

      case 'Recall':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>Recall</h3>
            <div className="input-row" style={{ alignItems: 'start' }}>
              <div className="input-group">
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={recallAutoIndex === true}
                    onChange={(e) => setRecall({ ...(recall || {}), auto_index: e.target.checked })}
                  />
                  <span className="toggle-track" aria-hidden="true">
                    <span className="toggle-thumb"></span>
                  </span>
                  <span className="toggle-label">
                    Auto-index conversations <TooltipIcon name="chat.recall.auto_index" />
                  </span>
                </label>
              </div>

              <div className="input-group">
                <label>
                  Index delay (seconds) <TooltipIcon name="chat.recall.index_delay_seconds" />
                </label>
                <input
                  type="number"
                  value={recallDelaySeconds}
                  min="1"
                  max="60"
                  step="1"
                  onChange={(e) => setRecall({ ...(recall || {}), index_delay_seconds: Number(e.target.value) })}
                />
                <p className="small">Delay before indexing a new message into Recall memory.</p>
              </div>
            </div>

            <div style={{ marginTop: 18 }}>
              <h4 style={{ margin: '0 0 10px 0', fontSize: 14, fontWeight: 600, color: 'var(--fg)' }}>
                Retrieval Gate
              </h4>
              <div style={{ marginBottom: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
                This gate only controls whether/how to query <span className="mono">Recall</span> (chat memory) per message.
                RAG corpora are always queried when checked.
              </div>

              <div className="input-row" style={{ alignItems: 'start' }}>
                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateEnabled === true}
                      onChange={(e) => setRecallGate({ ...(recallGate || {}), enabled: e.target.checked })}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Enable smart gating <TooltipIcon name="chat.recall_gate.enabled" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label>
                    Default intensity <TooltipIcon name="chat.recall_gate.default_intensity" />
                  </label>
                  <select
                    value={gateDefaultIntensity}
                    onChange={(e) =>
                      setRecallGate({ ...(recallGate || {}), default_intensity: e.target.value as RecallIntensity })
                    }
                    style={{ width: '100%' }}
                  >
                    <option value="standard">standard</option>
                    <option value="light">light</option>
                    <option value="deep">deep</option>
                    <option value="skip">skip</option>
                  </select>
                </div>

                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateShowDecision === true}
                      onChange={(e) => setRecallGate({ ...(recallGate || {}), show_gate_decision: e.target.checked })}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Show decision in status bar <TooltipIcon name="chat.recall_gate.show_gate_decision" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateShowSignals === true}
                      onChange={(e) => setRecallGate({ ...(recallGate || {}), show_signals: e.target.checked })}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Show raw signals (dev) <TooltipIcon name="chat.recall_gate.show_signals" />
                    </span>
                  </label>
                </div>
              </div>

              <div className="input-row" style={{ alignItems: 'start' }}>
                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateSkipGreetings === true}
                      onChange={(e) => setRecallGate({ ...(recallGate || {}), skip_greetings: e.target.checked })}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Skip greetings/acknowledgments <TooltipIcon name="chat.recall_gate.skip_greetings" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateSkipStandaloneQuestions === true}
                      onChange={(e) =>
                        setRecallGate({ ...(recallGate || {}), skip_standalone_questions: e.target.checked })
                      }
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Skip standalone questions <TooltipIcon name="chat.recall_gate.skip_standalone_questions" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateSkipWhenRagActive === true}
                      onChange={(e) => setRecallGate({ ...(recallGate || {}), skip_when_rag_active: e.target.checked })}
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Skip when RAG active <TooltipIcon name="chat.recall_gate.skip_when_rag_active" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label>
                    Max skip tokens <TooltipIcon name="chat.recall_gate.skip_max_tokens" />
                  </label>
                  <input
                    type="number"
                    value={gateSkipMaxTokens}
                    min="1"
                    max="20"
                    step="1"
                    onChange={(e) =>
                      setRecallGate({ ...(recallGate || {}), skip_max_tokens: Number(e.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="input-row" style={{ alignItems: 'start' }}>
                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateLightForShortQuestions === true}
                      onChange={(e) =>
                        setRecallGate({ ...(recallGate || {}), light_for_short_questions: e.target.checked })
                      }
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Light for short questions <TooltipIcon name="chat.recall_gate.light_for_short_questions" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label>
                    Light top_k <TooltipIcon name="chat.recall_gate.light_top_k" />
                  </label>
                  <input
                    type="number"
                    value={gateLightTopK}
                    min="1"
                    max="10"
                    step="1"
                    onChange={(e) => setRecallGate({ ...(recallGate || {}), light_top_k: Number(e.target.value) })}
                  />
                </div>
              </div>

              <div className="input-row" style={{ alignItems: 'start' }}>
                <div className="input-group">
                  <label>
                    Standard top_k <TooltipIcon name="chat.recall_gate.standard_top_k" />
                  </label>
                  <input
                    type="number"
                    value={gateStandardTopK}
                    min="1"
                    max="20"
                    step="1"
                    onChange={(e) =>
                      setRecallGate({ ...(recallGate || {}), standard_top_k: Number(e.target.value) })
                    }
                  />
                </div>

                <div className="input-group">
                  <label>
                    Standard recency weight <TooltipIcon name="chat.recall_gate.standard_recency_weight" />
                  </label>
                  <input
                    type="number"
                    value={gateStandardRecencyWeight}
                    min="0"
                    max="1"
                    step="0.05"
                    onChange={(e) =>
                      setRecallGate({ ...(recallGate || {}), standard_recency_weight: Number(e.target.value) })
                    }
                  />
                </div>
              </div>

              <div className="input-row" style={{ alignItems: 'start' }}>
                <div className="input-group">
                  <label className="toggle">
                    <input
                      type="checkbox"
                      checked={gateDeepOnExplicitReference === true}
                      onChange={(e) =>
                        setRecallGate({ ...(recallGate || {}), deep_on_explicit_reference: e.target.checked })
                      }
                    />
                    <span className="toggle-track" aria-hidden="true">
                      <span className="toggle-thumb"></span>
                    </span>
                    <span className="toggle-label">
                      Deep on explicit reference <TooltipIcon name="chat.recall_gate.deep_on_explicit_reference" />
                    </span>
                  </label>
                </div>

                <div className="input-group">
                  <label>
                    Deep top_k <TooltipIcon name="chat.recall_gate.deep_top_k" />
                  </label>
                  <input
                    type="number"
                    value={gateDeepTopK}
                    min="3"
                    max="30"
                    step="1"
                    onChange={(e) => setRecallGate({ ...(recallGate || {}), deep_top_k: Number(e.target.value) })}
                  />
                </div>

                <div className="input-group">
                  <label>
                    Deep recency weight <TooltipIcon name="chat.recall_gate.deep_recency_weight" />
                  </label>
                  <input
                    type="number"
                    value={gateDeepRecencyWeight}
                    min="0"
                    max="1"
                    step="0.05"
                    onChange={(e) =>
                      setRecallGate({ ...(recallGate || {}), deep_recency_weight: Number(e.target.value) })
                    }
                  />
                </div>
              </div>
            </div>
          </div>
        );

      case 'Multimodal':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>Multimodal</h3>
            <div className="input-row">
              <div className="input-group">
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={visionEnabled === true}
                    onChange={(e) => setMultimodal({ ...(multimodal || {}), vision_enabled: e.target.checked })}
                  />
                  <span className="toggle-track" aria-hidden="true">
                    <span className="toggle-thumb"></span>
                  </span>
                  <span className="toggle-label">
                    Vision enabled <TooltipIcon name="chat.multimodal.vision_enabled" />
                  </span>
                </label>
                <p className="small">Enables image upload + vision model inputs when supported by the selected model.</p>
              </div>
            </div>
          </div>
        );

      case 'Local':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>Local</h3>
            <div style={{ color: 'var(--fg-muted)', fontSize: 13, marginBottom: 14 }}>
              Configure local OpenAI-compatible provider endpoints (Ollama, llama.cpp, etc).
            </div>
            <ProviderSetup />
          </div>
        );

      case 'OpenRouter':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>OpenRouter</h3>
            <div style={{ color: 'var(--fg-muted)', fontSize: 13, marginBottom: 14 }}>
              Configure OpenRouter and verify your API key status.
            </div>
            <ProviderSetup />
          </div>
        );

      case 'Benchmark':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>Benchmark</h3>
            <div style={{ color: 'var(--fg-muted)', fontSize: 13 }}>
              Split-screen model comparison + pipeline profiling controls live here (coming soon).
            </div>
          </div>
        );

      case 'UI':
        return (
          <div className="subtab-panel" style={{ padding: 24 }}>
            <h3 style={{ marginTop: 0 }}>UI</h3>
            <div className="input-row">
              <div className="input-group">
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={chatStreamingEnabled === 1}
                    onChange={(e) => setChatStreamingEnabled(e.target.checked ? 1 : 0)}
                  />
                  <span className="toggle-track" aria-hidden="true">
                    <span className="toggle-thumb"></span>
                  </span>
                  <span className="toggle-label">
                    Streaming responses <TooltipIcon name="ui.chat_streaming_enabled" />
                  </span>
                </label>
                <p className="small">Streams tokens as they’re generated (recommended).</p>
              </div>
            </div>
          </div>
        );

      default:
        return null;
    }
  })();

  return (
    <div style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
        <div>
          <h3 style={{ margin: 0 }}>Chat Settings</h3>
          <div style={{ marginTop: 4, fontSize: 12, color: 'var(--fg-muted)' }}>
            {loading ? 'Loading…' : saving ? 'Saving…' : config ? 'Ready' : 'No config loaded'}
          </div>
        </div>
      </div>

      {error && (
        <div
          style={{
            marginBottom: 12,
            background: 'rgba(255, 107, 107, 0.1)',
            border: '1px solid var(--err)',
            borderRadius: 10,
            padding: '10px 12px',
            color: 'var(--err)',
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      <div className="tab-bar" style={{ marginBottom: 12 }}>
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            className={t === activeTab ? 'active' : ''}
            onClick={() => setActiveTab(t)}
            aria-pressed={t === activeTab}
          >
            {t}
          </button>
        ))}
      </div>

      {panel}
    </div>
  );
}

export default ChatSettings2;
