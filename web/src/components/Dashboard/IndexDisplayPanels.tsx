import { useCallback, useEffect, useRef, useState } from 'react';
import * as DashAPI from '@/api/dashboard';
import { useRepoStore } from '@/stores/useRepoStore';
import { IndexCostSummary } from '@/components/RAG/IndexRunCosts';
import type { DashboardIndexStatusMetadata } from '@/types/generated';

const formatBytes = (bytes?: number) => {
  if (!bytes || bytes <= 0) return '0 B';
  const k = 1024;
  // Binary units (KiB/MiB/...) because the division is by 1024, not 1000. This card and the
  // Storage subtab showed the same byte figure as "MB" here and "MiB" there (M-138); the
  // MiB label is the one that is correct against the raw bytes, so both now agree.
  const sizes = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${Math.round((bytes / Math.pow(k, i)) * 100) / 100} ${sizes[i]}`;
};

export function IndexDisplayPanels() {
  const activeRepo = useRepoStore((state) => state.activeRepo);
  const [metadata, setMetadata] = useState<DashboardIndexStatusMetadata | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestGeneration = useRef(0);

  const loadStatus = useCallback(async () => {
    // A corpus-change event can reach the previous render's listener before React
    // replaces it. Such a listener must not supersede the new corpus's request.
    if (useRepoStore.getState().activeRepo !== activeRepo) return;
    const generation = ++requestGeneration.current;
    const isCurrent = () => requestGeneration.current === generation && useRepoStore.getState().activeRepo === activeRepo;
    if (!activeRepo) {
      setMetadata(null);
      setLines(['Create or select a corpus to see index readiness.']);
      setError(null);
      setLoading(false);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      const status = await DashAPI.getIndexStatus(activeRepo);
      if (!isCurrent()) return;
      setMetadata((status.metadata || null) as DashboardIndexStatusMetadata | null);
      setLines(status.lines || []);
    } catch (err) {
      if (!isCurrent()) return;
      console.error('[IndexDisplay] Failed to load status:', err);
      const detail = (err as any)?.response?.data?.detail;
      setError(String(detail || (err instanceof Error ? err.message : String(err))));
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [activeRepo]);

  useEffect(() => {
    loadStatus();
    const interval = setInterval(loadStatus, 30000);
    const handleRefresh = () => loadStatus();
    const handleCorpusChanged = () => loadStatus();
    window.addEventListener('dashboard-refresh', handleRefresh);
    window.addEventListener('tribrid-corpus-changed', handleCorpusChanged);
    window.addEventListener('tribrid-corpus-loaded', handleCorpusChanged);
    return () => {
      ++requestGeneration.current;
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
      window.removeEventListener('tribrid-corpus-changed', handleCorpusChanged);
      window.removeEventListener('tribrid-corpus-loaded', handleCorpusChanged);
    };
  }, [loadStatus]);

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
  const storage = metadata.storage_breakdown;

  const storageCards: Array<{ label: string; value: string; accent: string; note?: string }> = [
    { label: 'Chunks', value: formatBytes(storage.chunks_bytes), accent: 'var(--link)' },
    { label: 'Qdrant points', value: (storage.qdrant_points ?? 0).toLocaleString(), accent: 'var(--link)' },
    { label: 'Qdrant dense vectors (est.)', value: formatBytes(storage.qdrant_dense_vector_bytes), accent: 'var(--accent-text)' },
    { label: 'Chunk Summaries', value: formatBytes(storage.chunk_summaries_bytes), accent: 'var(--accent-text)' },
    {
      label: 'Neo4j Store',
      // Unmeasured is "n/a" with the reason, never a measured-looking "0 B" (S5).
      value: storage.neo4j_store_bytes == null ? 'n/a' : formatBytes(storage.neo4j_store_bytes),
      accent: 'var(--warn)',
      note: storage.neo4j_store_bytes == null ? (storage.neo4j_store_note ?? undefined) : undefined
    },
    { label: 'Keywords', value: (metadata.keywords_count ?? 0).toLocaleString(), accent: 'var(--warn)' },
    { label: 'Postgres Total', value: formatBytes(storage.postgres_total_bytes), accent: 'var(--link)' }
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
              Branch:{' '}
              <span style={{ color: 'var(--link)', fontWeight: 600 }}>
                {metadata.current_branch || '—'}
              </span>
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

      {(
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
              color: 'var(--accent-text)',
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
            Live index accounting
          </div>
          <IndexCostSummary accounting={costs.accounting} />
        </div>
      )}

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
              data-testid={`storage-card-${card.label.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/-+$/, '')}`}
              title={card.note}
              style={{
                background: 'var(--card-bg)',
                padding: '12px',
                borderRadius: '6px',
                border: '1px solid var(--bg-elev2)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: '10px'
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
              <span style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '2px', minWidth: 0 }}>
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
                {card.note ? (
                  <span style={{ fontSize: '11.5px', lineHeight: 1.35, color: 'var(--fg-muted)', textAlign: 'right' }}>
                    {card.note}
                  </span>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      </div>

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
          style={{ fontSize: '24px', fontWeight: 900, color: 'var(--accent-text)', fontFamily: "'SF Mono', monospace" }}
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
