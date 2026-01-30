// AGRO - Secrets Subtab Component
// API keys are configured in .env only - never stored in frontend state

import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';

const API_KEYS = [
  { keyName: 'OPENAI_API_KEY', label: 'OpenAI API Key' },
  { keyName: 'ANTHROPIC_API_KEY', label: 'Anthropic API Key' },
  { keyName: 'COHERE_API_KEY', label: 'Cohere API Key' },
  { keyName: 'VOYAGE_API_KEY', label: 'Voyage API Key' },
  { keyName: 'JINA_API_KEY', label: 'Jina API Key' },
];

export function SecretsSubtab() {
  return (
    <div className="settings-section">
      <h2>Secrets Management</h2>
      <p className="small" style={{ marginBottom: '24px' }}>
        Secrets are configured in <code>.env</code>. This panel shows whether keys are present without exposing values.
      </p>

      <div
        style={{
          background: 'var(--bg-elev2)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '20px',
          marginBottom: '20px'
        }}
      >
        <h3 style={{ marginTop: 0 }}>API Key Status</h3>
        <p className="small" style={{ marginBottom: '16px' }}>
          Add keys to <code>.env</code> and restart the server to apply changes.
        </p>

        <div className="input-row">
          {API_KEYS.slice(0, 2).map(({ keyName, label }) => (
            <div className="input-group" key={keyName}>
              <ApiKeyStatus keyName={keyName} label={label} />
            </div>
          ))}
        </div>

        <div className="input-row">
          {API_KEYS.slice(2, 4).map(({ keyName, label }) => (
            <div className="input-group" key={keyName}>
              <ApiKeyStatus keyName={keyName} label={label} />
            </div>
          ))}
        </div>

        <div className="input-row">
          <div className="input-group">
            <ApiKeyStatus keyName={API_KEYS[4].keyName} label={API_KEYS[4].label} />
          </div>
          <div className="input-group" />
        </div>
      </div>
    </div>
  );
}
