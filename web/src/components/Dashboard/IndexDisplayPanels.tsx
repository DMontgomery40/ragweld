import { useEffect, useState } from 'react';
import * as DashAPI from '@/api/dashboard';

type ExtendedMetadata = DashAPI.IndexStatusMetadata & {
  embedding_config?: {
    provider?: string;
    model?: string;
    dimensions?: number;
    precision?: string;
  };
  costs?: {
    total_tokens?: number;
    embedding_cost?: number;
  };
  storage_breakdown?: {
    chunks_json?: number;
    embeddings_raw?: number;
    qdrant_overhead?: number;
    bm25_index?: number;
    cards?: number;
    reranker_cache?: number;
    redis?: number;
  };
};

const formatBytes = (bytes?: number) => {
  if (!bytes || bytes <= 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`;
};

export function IndexDisplayPanels() {
  const [metadata, setMetadata] = useState<ExtendedMetadata | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const status = await DashAPI.getIndexStatus();
      setMetadata((status.metadata || null) as ExtendedMetadata | null);
      setLines(status.lines || []);
    } catch (err) {
      console.error('[IndexDisplay] Failed to load status:', err);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 30000);
    const handleRefresh = () => loadStatus();
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, []);

  if (loading) {
    return <div style={{ color: 'var(--fg-muted)', fontSize: '13px' }}>Loading index readiness…</div>;
  }

  if (error) {
    return (
      <div style={{ color: 'var(--err)', fontSize: '13px' }}>
        Unable to load index stats: {error}
      </div>
    );
  }

  if (!metadata) {
    return (
      <pre
        style={{
          color: 'var(--fg-muted)',
          fontSize: '13px',
          fontFamily: "'SF Mono', monospace",
          background: 'var(--code-bg)',
          borderRadius: '6px',
          padding: '12px',
          margin: 0,
          whiteSpace: 'pre-wrap'
        }}
      >
        {lines.length ? lines.join('\n') : 'Ready to index…'}
      </pre>
    );
  }

  const embedding = metadata.embedding_config || {};
  const costs = metadata.costs || {};
  const storage = metadata.storage_breakdown || {};
  const qdrantWithOverhead = (storage.embeddings_raw || 0) + (storage.qdrant_overhead || 0);

  const storageCards = [
    { label: 'Chunks JSON', value: formatBytes(storage.chunks_json), accent: 'var(--link)' },
    { label: 'RAM Embeddings', value: formatBytes(storage.embeddings_raw), accent: 'var(--link)' },
    { label: 'Qdrant (w/overhead)', value: formatBytes(qdrantWithOverhead), accent: 'var(--warn)' },
    { label: 'BM25 Index', value: formatBytes(storage.bm25_index), accent: 'var(--accent)' },
    { label: 'Cards/Summary', value: formatBytes(storage.cards), accent: 'var(--accent)' },
    { label: 'Reranker Cache', value: formatBytes(storage.reranker_cache), accent: 'var(--warn)' },
    { label: 'Redis Cache', value: formatBytes(storage.redis), accent: 'var(--link)' },
    { label: 'Keywords', value: (metadata.keywords_count ?? 0).toLocaleString(), accent: 'var(--warn)' }
  ];

  return (
    <div
      data-tooltip="DASHBOARD_INDEX_PANEL"
      style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          paddingBottom: '12px',
          borderBottom: '2px solid var(--line)'
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
          <div
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: 'var(--accent)',
              boxShadow: '0 0 12px var(--accent)'
            }}
          />
          <div>
            <div style={{ fontSize: '20px', fontWeight: 700, color: 'var(--fg)', letterSpacing: '-0.5px' }}>
              {metadata.current_repo}
            </div>
            <div
              style={{
                fontSize: '11px',
                color: 'var(--fg-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.8px',
                marginTop: '4px'
              }}
            >
              Branch: <span style={{ color: 'var(--link)', fontWeight: 600 }}>{metadata.current_branch}</span>
            </div>
          </div>
        </div>
        <div style={{ fontSize: '10px', color: 'var(--fg-muted)', fontFamily: "'SF Mono', monospace" }}>
          {metadata.timestamp ? new Date(metadata.timestamp).toLocaleString() : ''}
        </div>
      </div>

      <div
        style={{
          background: 'linear-gradient(135deg,var(--card-bg) 0%,var(--code-bg) 100%)',
          padding: '16px',
          borderRadius: '8px',
          border: '1px solid var(--line)'
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            color: 'var(--link)',
            textTransform: 'uppercase',
            letterSpacing: '1px',
            marginBottom: '12px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--link)" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M12 6v6l4 2" />
          </svg>
          Embedding Configuration
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: '10px' }}>
          <EmbeddingStat label="Model" value={embedding.model || embedding.provider || 'N/A'} />
          <EmbeddingStat
            label="Dimensions"
            value={embedding.dimensions ? embedding.dimensions.toLocaleString() : 'N/A'}
          />
          <EmbeddingStat label="Precision" value={embedding.precision || 'N/A'} accent="var(--warn)" />
        </div>
      </div>

      {costs.total_tokens ? (
        <div
          style={{
            background: 'linear-gradient(135deg,color-mix(in oklch,var(--ok) 6%,var(--bg)) 0%,var(--card-bg) 100%)',
            padding: '16px',
            borderRadius: '8px',
            border: '1px solid color-mix(in oklch, var(--ok) 30%, var(--bg))'
          }}
        >
          <div
            style={{
              fontSize: '11px',
              fontWeight: 700,
              color: 'var(--accent)',
              textTransform: 'uppercase',
              letterSpacing: '1px',
              marginBottom: '12px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2">
              <line x1="12" y1="1" x2="12" y2="23" />
              <path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" />
            </svg>
            Indexing Costs
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <CostStat label="Total Tokens" value={costs.total_tokens?.toLocaleString() || '0'} />
            <CostStat label="Embedding Cost" value={`$${Number(costs.embedding_cost || 0).toFixed(4)}`} />
          </div>
        </div>
      ) : null}

      <div
        style={{
          background: 'linear-gradient(135deg,var(--code-bg) 0%,var(--card-bg) 100%)',
          padding: '18px',
          borderRadius: '8px',
          border: '1px solid var(--line)'
        }}
      >
        <div
          style={{
            fontSize: '11px',
            fontWeight: 700,
            color: 'var(--warn)',
            textTransform: 'uppercase',
            letterSpacing: '1px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--warn)" strokeWidth="2">
            <rect x="2" y="3" width="20" height="18" rx="2" ry="2" />
            <line x1="2" y1="9" x2="22" y2="9" />
            <line x1="2" y1="15" x2="22" y2="15" />
          </svg>
          Storage Requirements
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2,1fr)', gap: '10px' }}>
          {storageCards.map(card => (
            <div
              key={card.label}
              style={{
                background: 'var(--card-bg)',
                padding: '12px',
                borderRadius: '6px',
                border: '1px solid var(--bg-elev2)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center'
              }}
            >
              <span
                style={{
                  fontSize: '10px',
                  color: 'var(--fg-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px'
                }}
              >
                {card.label}
              </span>
              <span
                style={{
                  fontSize: '13px',
                  fontWeight: 700,
                  color: card.accent,
                  fontFamily: "'SF Mono', monospace"
                }}
              >
                {card.value}
              </span>
            </div>
          ))}
        </div>
      </div>

      {metadata.repos && metadata.repos.length > 0 && (
        <details style={{ marginBottom: '4px' }}>
          <summary
            style={{
              cursor: 'pointer',
              fontSize: '11px',
              fontWeight: 700,
              color: 'var(--fg-muted)',
              textTransform: 'uppercase',
              letterSpacing: '1px',
              padding: '12px',
              background: 'var(--card-bg)',
              borderRadius: '6px',
              border: '1px solid var(--line)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center'
            }}
          >
            <span style={{ color: 'var(--link)' }}>▸ Index Profiles</span>
            <span>{metadata.repos.length}</span>
          </summary>
          <div
            style={{
              marginTop: '12px',
              padding: '12px',
              background: 'var(--card-bg)',
              borderRadius: '6px',
              border: '1px solid var(--line)',
              display: 'flex',
              flexDirection: 'column',
              gap: '8px'
            }}
          >
            {metadata.repos.map(repo => {
              const totalSize =
                (repo.sizes?.chunks || 0) + (repo.sizes?.bm25 || 0) + (repo.sizes?.cards || 0);
              const profileLabel = repo.profile || 'default';
              return (
                <div
                  key={`${profileLabel}-${repo.name}`}
                  style={{
                    padding: '10px',
                    background: 'var(--code-bg)',
                    borderRadius: '4px',
                    border: `1px solid ${
                      repo.has_cards ? 'color-mix(in oklch, var(--ok) 30%, var(--line))' : 'var(--line)'
                    }`
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                    <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--fg)' }}>
                      {repo.name}{' '}
                      <span style={{ color: 'var(--fg-muted)', fontWeight: 400 }}>/ {profileLabel}</span>
                    </div>
                    <div
                      style={{
                        fontSize: '12px',
                        fontWeight: 700,
                        color: 'var(--accent)',
                        fontFamily: "'SF Mono', monospace"
                      }}
                    >
                      {formatBytes(totalSize)}
                    </div>
                  </div>
                  <div style={{ fontSize: '10px', color: 'var(--fg-muted)' }}>
                    {repo.chunk_count.toLocaleString()} chunks{' '}
                    {repo.has_cards ? <span style={{ color: 'var(--ok)' }}>• ✓ Cards</span> : null}
                  </div>
                </div>
              );
            })}
          </div>
        </details>
      )}

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '18px',
          background: 'var(--panel)',
          borderRadius: '8px',
          border: '2px solid var(--accent)'
        }}
      >
        <div
          style={{
            fontSize: '13px',
            fontWeight: 700,
            color: 'var(--fg-muted)',
            textTransform: 'uppercase',
            letterSpacing: '1px'
          }}
        >
          Total Index Storage
        </div>
        <div
          style={{ fontSize: '24px', fontWeight: 900, color: 'var(--accent)', fontFamily: "'SF Mono', monospace" }}
        >
          {formatBytes(metadata.total_storage)}
        </div>
      </div>
    </div>
  );
}

function EmbeddingStat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div
      style={{
        background: 'var(--card-bg)',
        padding: '10px',
        borderRadius: '6px',
        border: '1px solid var(--bg-elev2)'
      }}
    >
      <div
        style={{
          fontSize: '9px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          marginBottom: '4px'
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: '13px',
          fontWeight: 700,
          color: accent || 'var(--link)',
          fontFamily: "'SF Mono', monospace"
        }}
      >
        {value}
      </div>
    </div>
  );
}

function CostStat({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        background: 'var(--card-bg)',
        padding: '10px',
        borderRadius: '6px',
        border: '1px solid color-mix(in oklch, var(--ok) 25%, var(--bg))'
      }}
    >
      <div
        style={{
          fontSize: '9px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
          marginBottom: '4px'
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: '15px',
          fontWeight: 700,
          color: 'var(--accent)',
          fontFamily: "'SF Mono', monospace"
        }}
      >
        {value}
      </div>
    </div>
  );
}
