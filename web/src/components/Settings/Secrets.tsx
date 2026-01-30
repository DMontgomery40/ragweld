import { ApiKeyStatus } from '@/components/ui/ApiKeyStatus';

const API_KEYS = [
  { keyName: 'OPENAI_API_KEY', label: 'OpenAI API Key' },
  { keyName: 'ANTHROPIC_API_KEY', label: 'Anthropic API Key' },
  { keyName: 'COHERE_API_KEY', label: 'Cohere API Key' },
  { keyName: 'VOYAGE_API_KEY', label: 'Voyage API Key' },
  { keyName: 'GOOGLE_API_KEY', label: 'Google API Key' },
];

export function Secrets() {
  return (
    <div style={{ padding: '24px' }}>
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '6px',
          padding: '16px',
          marginBottom: '24px',
        }}
      >
        <h3 style={{ margin: '0 0 16px 0', fontSize: '16px', color: 'var(--fg)' }}>
          Secrets
        </h3>
        <p style={{ color: 'var(--fg-muted)', fontSize: '13px', marginBottom: '16px' }}>
          Secrets are configured in <code>.env</code> and are never stored in the browser. Add keys and restart to apply changes.
        </p>

        <div style={{ display: 'grid', gap: '16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {API_KEYS.slice(0, 2).map(({ keyName, label }) => (
              <ApiKeyStatus key={keyName} keyName={keyName} label={label} />
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {API_KEYS.slice(2, 4).map(({ keyName, label }) => (
              <ApiKeyStatus key={keyName} keyName={keyName} label={label} />
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <ApiKeyStatus keyName={API_KEYS[4].keyName} label={API_KEYS[4].label} />
            <div />
          </div>
        </div>
      </div>
    </div>
  );
}
