// AGRO - Embedding Configuration Panel
// Shows current embedding model, dimensions, precision from backend

import { useEffect, useState } from 'react';

interface EmbeddingConfig {
  model: string;
  dimensions: number;
  precision: string;
}

export function EmbeddingConfigPanel() {
  const [config, setConfig] = useState<EmbeddingConfig>({
    model: 'text-embedding-3-large',
    dimensions: 512,
    precision: 'float32',
  });

  const loadConfig = async () => {
    try {
      const response = await fetch('/api/config');
      const data = await response.json();
      
      if (data.env) {
        setConfig({
          model: data.env.EMBEDDING_MODEL || 'text-embedding-3-large',
          dimensions: parseInt(data.env.EMBEDDING_DIMENSIONS || '512'),
          precision: data.env.EMBEDDING_PRECISION || 'float32',
        });
      }
    } catch (e) {
      console.error('[EmbeddingConfig] Failed to load:', e);
    }
  };

  useEffect(() => {
    loadConfig();
    const handleRefresh = () => loadConfig();
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => window.removeEventListener('dashboard-refresh', handleRefresh);
  }, []);

  return (
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
          fontSize: '11px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          marginBottom: '12px',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}
      >
        <span style={{ color: 'var(--accent)' }}>⚙</span>
        EMBEDDING CONFIGURATION
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span
            style={{
              color: 'var(--fg-muted)',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
          >
            MODEL
          </span>
          <a
            href="/rag?subtab=retrieval"
            style={{
              color: 'var(--link)',
              fontSize: '14px',
              fontWeight: 600,
              fontFamily: "'Monaco', 'Courier New', monospace",
              textDecoration: 'none',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--accent)';
              e.currentTarget.style.textDecoration = 'underline';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--link)';
              e.currentTarget.style.textDecoration = 'none';
            }}
            title="Click to configure in RAG → Retrieval"
          >
            {config.model}
          </a>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span
            style={{
              color: 'var(--fg-muted)',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
          >
            DIMENSIONS
          </span>
          <a
            href="/rag?subtab=retrieval"
            style={{
              color: 'var(--link)',
              fontSize: '14px',
              fontWeight: 600,
              fontFamily: "'Monaco', 'Courier New', monospace",
              textDecoration: 'none',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--accent)';
              e.currentTarget.style.textDecoration = 'underline';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--link)';
              e.currentTarget.style.textDecoration = 'none';
            }}
            title="Click to configure in RAG → Retrieval"
          >
            {config.dimensions}
          </a>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <span
            style={{
              color: 'var(--fg-muted)',
              fontSize: '11px',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}
          >
            PRECISION
          </span>
          <a
            href="/rag?subtab=retrieval"
            style={{
              color: 'var(--link)',
              fontSize: '14px',
              fontWeight: 600,
              fontFamily: "'Monaco', 'Courier New', monospace",
              textDecoration: 'none',
              cursor: 'pointer',
              transition: 'all 0.2s ease',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = 'var(--accent)';
              e.currentTarget.style.textDecoration = 'underline';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = 'var(--link)';
              e.currentTarget.style.textDecoration = 'none';
            }}
            title="Click to configure in RAG → Retrieval"
          >
            {config.precision}
          </a>
        </div>
      </div>
    </div>
  );
}

