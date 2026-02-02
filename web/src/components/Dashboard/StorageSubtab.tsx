// TriBrid RAG - Storage Subtab
// Disk usage, index storage breakdown, and capacity planning

import { useState, useEffect } from 'react';
import * as DashAPI from '@/api/dashboard';
import { StorageCalculatorSuite } from './StorageCalculatorSuite';

interface StorageItem {
  label: string;
  size: string;
  bytes: number;
}

export function StorageSubtab() {
  const [items, setItems] = useState<StorageItem[]>([]);
  const [totalStorage, setTotalStorage] = useState<string>('—');
  const [totalBytes, setTotalBytes] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const formatBytes = (bytes: number): string => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
  };

  const loadStorage = async () => {
    setLoading(true);
    setError(null);

    try {
      const data = await DashAPI.getIndexStats();
      const storage = data.storage_breakdown;

      const storageItems: StorageItem[] = [
        {
          label: 'CHUNKS',
          bytes: storage?.chunks_bytes || 0,
          size: formatBytes(storage?.chunks_bytes || 0)
        },
        {
          label: 'PGVECTOR VECTORS',
          bytes: storage?.embeddings_bytes || 0,
          size: formatBytes(storage?.embeddings_bytes || 0)
        },
        {
          label: 'PGVECTOR INDEX (optional)',
          bytes: storage?.pgvector_index_bytes || 0,
          size: formatBytes(storage?.pgvector_index_bytes || 0)
        },
        {
          label: 'BM25 INDEX',
          bytes: storage?.bm25_index_bytes || 0,
          size: formatBytes(storage?.bm25_index_bytes || 0)
        },
        {
          label: 'NEO4J STORE',
          bytes: storage?.neo4j_store_bytes || 0,
          size: formatBytes(storage?.neo4j_store_bytes || 0)
        },
        {
          label: 'CHUNK SUMMARIES',
          bytes: storage?.chunk_summaries_bytes || 0,
          size: formatBytes(storage?.chunk_summaries_bytes || 0)
        },
        {
          label: 'KEYWORDS',
          bytes: data.keywords_count || 0,
          size: `${data.keywords_count || 0} keywords`
        }
      ];

      setItems(storageItems);
      setTotalBytes(data.total_storage || 0);
      setTotalStorage(formatBytes(data.total_storage || 0));
      setLoading(false);
    } catch (err) {
      console.error('[StorageSubtab] Failed to load storage:', err);
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStorage();

    // Listen for refresh events
    const handleRefresh = () => loadStorage();
    const handleCorpusChanged = () => loadStorage();
    window.addEventListener('dashboard-refresh', handleRefresh);
    window.addEventListener('tribrid-corpus-changed', handleCorpusChanged);
    window.addEventListener('tribrid-corpus-loaded', handleCorpusChanged);

    return () => {
      window.removeEventListener('dashboard-refresh', handleRefresh);
      window.removeEventListener('tribrid-corpus-changed', handleCorpusChanged);
      window.removeEventListener('tribrid-corpus-loaded', handleCorpusChanged);
    };
  }, []);


  // Calculate percentage for each item
  const getPercentage = (bytes: number): number => {
    if (totalBytes === 0) return 0;
    return (bytes / totalBytes) * 100;
  };

  return (
    <div
      id="tab-dashboard-storage"
      className="dashboard-subtab"
      style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}
    >
      {/* Storage Requirements Section */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--ok)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
          <span style={{ fontSize: '32px' }}>📦</span>
          <div>
            <h3 style={{ margin: 0, fontSize: '20px', fontWeight: 600 }}>Storage Requirements</h3>
            <p style={{ margin: '4px 0 0 0', fontSize: '12px', color: 'var(--fg-muted)' }}>
              Detailed breakdown of index and cache storage usage
            </p>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: '60px', textAlign: 'center', color: 'var(--fg-muted)' }}>
            <div
              style={{
                width: '48px',
                height: '48px',
                border: '3px solid var(--line)',
                borderTopColor: 'var(--accent)',
                borderRadius: '50%',
                animation: 'spin 1s linear infinite',
                margin: '0 auto 16px'
              }}
            />
            Loading storage data...
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </div>
        ) : error ? (
          <div
            style={{
              padding: '40px',
              textAlign: 'center',
              color: 'var(--err)',
              background: 'var(--card-bg)',
              borderRadius: '8px',
              border: '1px solid var(--err)'
            }}
          >
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>⚠️</div>
            <div style={{ fontSize: '14px', fontWeight: '600', marginBottom: '8px' }}>Failed to load storage data</div>
            <div style={{ fontSize: '12px', opacity: '0.8' }}>{error}</div>
            <button
              onClick={loadStorage}
              style={{
                marginTop: '16px',
                padding: '8px 16px',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)',
                cursor: 'pointer'
              }}
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            {/* Storage Grid - Responsive auto-fit */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
                gap: '16px',
                marginBottom: '24px'
              }}
            >
              {items.map((item, idx) => (
                <div
                  key={idx}
                  style={{
                    background: 'var(--card-bg)',
                    border: '1px solid var(--line)',
                    borderRadius: '6px',
                    padding: '16px',
                    position: 'relative',
                    overflow: 'hidden'
                  }}
                >
                  {/* Background bar showing percentage */}
                  <div
                    style={{
                      position: 'absolute',
                      bottom: 0,
                      left: 0,
                      right: 0,
                      height: `${Math.min(getPercentage(item.bytes), 100)}%`,
                      background: 'linear-gradient(to top, rgba(0, 255, 136, 0.1), transparent)',
                      opacity: 0.5,
                      pointerEvents: 'none'
                    }}
                  />

                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div
                      style={{
                        color: 'var(--fg-muted)',
                        fontSize: '10px',
                        textTransform: 'uppercase',
                        letterSpacing: '0.5px',
                        marginBottom: '8px',
                        fontWeight: '600'
                      }}
                    >
                      {item.label}
                    </div>
                    <div
                      style={{
                        color: 'var(--ok)',
                        fontSize: '16px',
                        fontWeight: '700',
                        fontFamily: "'Monaco', 'Courier New', monospace"
                      }}
                    >
                      {item.size}
                    </div>
                    {totalBytes > 0 && item.label !== 'KEYWORDS' && (
                      <div
                        style={{
                          color: 'var(--fg-muted)',
                          fontSize: '9px',
                          marginTop: '4px'
                        }}
                      >
                        {getPercentage(item.bytes).toFixed(1)}% of total
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Profiles section removed - banned feature per CLAUDE.md */}

            {/* Total Storage */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                padding: '20px',
                background: 'rgba(0, 255, 136, 0.05)',
                border: '2px solid #00ff88',
                borderRadius: '8px'
              }}
            >
              <span
                style={{
                  color: 'var(--fg-muted)',
                  fontSize: '14px',
                  textTransform: 'uppercase',
                  letterSpacing: '0.8px',
                  fontWeight: '700'
                }}
              >
                TOTAL INDEX STORAGE
              </span>
              <span
                style={{
                  color: '#00ff88',
                  fontSize: '28px',
                  fontWeight: '700',
                  fontFamily: "'Monaco', 'Courier New', monospace"
                }}
              >
                {totalStorage}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Storage Calculator Suite */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--accent)' }}>
        <StorageCalculatorSuite />
      </div>

      {/* Storage Tips & Optimization */}
      <div className="settings-section" style={{ background: 'var(--panel)', borderLeft: '3px solid var(--link)' }}>
        <h3
          style={{
            fontSize: '16px',
            marginBottom: '16px',
            display: 'flex',
            alignItems: 'center',
            gap: '10px'
          }}
        >
          <span style={{ fontSize: '24px' }}>💡</span>
          Storage Optimization Tips
        </h3>

        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '16px'
          }}
        >
          <ul style={{ margin: 0, paddingLeft: '20px', lineHeight: '1.8', fontSize: '13px', color: 'var(--fg)' }}>
            <li>
              <strong>pgvector Index:</strong> HNSW index overhead is typically 10-20% of raw embeddings (lower than standalone vector DBs)
            </li>
            <li>
              <strong>BM25 Index:</strong> Sparse retrieval index is compact but grows with unique terms
            </li>
            <li>
              <strong>Neo4j Graph:</strong> Knowledge graph stores entities and relationships for graph-based retrieval
            </li>
            <li>
              <strong>Chunk Summaries:</strong> Pre-computed summaries enable faster retrieval with minimal storage cost
            </li>
            <li>
              <strong>Reranker Cache:</strong> Stores cross-encoder scores to avoid re-computation
            </li>
            <li>
              <strong>Keywords:</strong> BM25 keyword extraction for improved sparse retrieval
            </li>
          </ul>
        </div>
      </div>
    </div>
  );
}
