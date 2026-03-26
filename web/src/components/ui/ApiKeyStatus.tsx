import { useEffect, useState } from 'react';
import { useAPI } from '@/hooks/useAPI';

interface ApiKeyStatusProps {
  keyName: string;  // e.g., "COHERE_API_KEY", "OPENAI_API_KEY", "NEO4J_PASSWORD"
  label?: string;   // Optional display label, defaults to keyName
}

/**
 * ApiKeyStatus - Shows whether an env-only secret is configured
 * 
 * Uses useAPI hook for proper Zustand/Pydantic compliance.
 * NEVER reads or exposes the actual secret value.
 * Only checks via backend if the key exists and is non-empty.
 * 
 * States:
 * - Loading: "Checking..."
 * - Configured: Green checkmark with "Configured" 
 * - Not configured: Orange warning with instructions to add to the backend environment
 */
export function ApiKeyStatus({ keyName, label }: ApiKeyStatusProps) {
  const [isConfigured, setIsConfigured] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const { api } = useAPI();

  useEffect(() => {
    if (!keyName) {
      setLoading(false);
      return;
    }

    setLoading(true);
    
    // Use the API helper for proper routing (dev/docker)
    fetch(api(`/secrets/check?keys=${keyName}`))
      .then(r => r.json())
      .then(data => {
        setIsConfigured(data[keyName] === true);
        setLoading(false);
      })
      .catch(() => {
        setIsConfigured(null);
        setLoading(false);
      });
  }, [keyName, api]);

  const displayName = label || keyName;

  if (loading) {
    return (
      <div style={{
        padding: '12px 16px',
        background: 'var(--bg-elev1)',
        borderRadius: '8px',
        border: '1px solid var(--line)',
        fontSize: '12px',
        color: 'var(--fg-muted)'
      }}>
        <span>🔑 {displayName}: Checking...</span>
      </div>
    );
  }

  if (isConfigured === true) {
    return (
      <div style={{
        padding: '12px 16px',
        background: 'rgba(var(--ok-rgb), 0.1)',
        borderRadius: '8px',
        border: '1px solid var(--ok)',
        fontSize: '12px',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: 'var(--ok)'
        }}>
          <span style={{ fontSize: '14px' }}>✓</span>
          <span style={{ fontWeight: 600 }}>
            {displayName}: Configured
          </span>
        </div>
        <div style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
          Secret is present in the backend environment and ready to use.
        </div>
      </div>
    );
  }

  if (isConfigured === null) {
    return (
      <div style={{
        padding: '12px 16px',
        background: 'var(--bg-elev1)',
        borderRadius: '8px',
        border: '1px solid var(--line)',
        fontSize: '12px',
      }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          color: 'var(--fg-muted)'
        }}>
          <span style={{ fontSize: '14px' }}>?</span>
          <span style={{ fontWeight: 600 }}>
            {displayName}: Unable to check
          </span>
        </div>
        <div style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
          The backend may be unreachable, misconfigured, or blocked by CORS. Verify the API is running, then reload.
        </div>
      </div>
    );
  }

  // Not configured or unknown
  return (
    <div style={{
      padding: '12px 16px',
      background: 'rgba(var(--warn-rgb), 0.1)',
      borderRadius: '8px',
      border: '1px solid var(--warn)',
      fontSize: '12px',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
        color: 'var(--warn)'
      }}>
        <span style={{ fontSize: '14px' }}>⚠</span>
        <span style={{ fontWeight: 600 }}>
          {displayName}: Not configured
        </span>
      </div>
      <div style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>
        Add <code style={{
          background: 'var(--bg-elev2)',
          padding: '2px 6px',
          borderRadius: '4px',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px'
        }}>{keyName}=your_value</code> to your backend environment or <code style={{
          background: 'var(--bg-elev2)',
          padding: '2px 6px',
          borderRadius: '4px',
          fontFamily: 'var(--font-mono)',
          fontSize: '11px'
        }}>.env</code> file.
      </div>
    </div>
  );
}

export default ApiKeyStatus;
