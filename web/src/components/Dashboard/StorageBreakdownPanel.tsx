// AGRO - Storage Requirements Breakdown Panel
// Shows detailed storage usage from backend data

import { useEffect, useState } from 'react';

interface StorageItem {
  label: string;
  size: string;
}

interface StorageData {
  items: StorageItem[];
  totalStorage: string;
  profileCount: number;
}

export function StorageBreakdownPanel() {
  const [storage, setStorage] = useState<StorageData>({
    items: [],
    totalStorage: '—',
    profileCount: 0,
  });

  const loadStorage = async () => {
    try {
      const response = await fetch('/api/index/stats');
      const data = await response.json();

      if (data) {
        const items: StorageItem[] = [
          { label: 'CHUNKS JSON', size: formatBytes(data.chunks_json_size || 0) },
          { label: 'RAM EMBEDDINGS', size: formatBytes(data.ram_embeddings_size || 0) },
          { label: 'QDRANT (W/OVERHEAD)', size: formatBytes(data.qdrant_size || 0) },
          { label: 'BM25 INDEX', size: formatBytes(data.bm25_index_size || 0) },
          { label: 'CHUNK SUMMARIES', size: formatBytes(data.cards_size || 0) },
          { label: 'RERANKER CACHE', size: formatBytes(data.reranker_cache_size || 0) },
          { label: 'REDIS CACHE', size: formatBytes(data.redis_cache_size || 0) },
          { label: 'KEYWORDS', size: data.keyword_count?.toString() || '0' },
        ];

        setStorage({
          items,
          totalStorage: formatBytes(data.total_storage || 0),
          profileCount: data.profile_count || 0,
        });
      }
    } catch (e) {
      console.error('[StorageBreakdown] Failed to load:', e);
    }
  };

  const formatBytes = (bytes: number): string => {
    if (!bytes || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KiB', 'MiB', 'GiB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return (bytes / Math.pow(k, i)).toFixed(3) + ' ' + sizes[i];
  };

  useEffect(() => {
    loadStorage();
    const handleRefresh = () => loadStorage();
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => window.removeEventListener('dashboard-refresh', handleRefresh);
  }, []);

  return (
    <div
      style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '20px',
        marginBottom: '24px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '20px' }}>
        <span style={{ fontSize: '20px' }}>📦</span>
        <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600 }}>Storage Requirements</h3>
      </div>

      {/* Storage Grid - 4 columns */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4, 1fr)',
          gap: '16px',
          marginBottom: '20px',
        }}
      >
        {storage.items.map((item, idx) => (
          <div
            key={idx}
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              padding: '12px',
              background: 'rgba(0, 0, 0, 0.3)',
              borderRadius: '4px',
              border: '1px solid rgba(255, 255, 255, 0.05)',
            }}
          >
            <span
              style={{
                color: 'var(--fg-muted)',
                fontSize: '11px',
                textTransform: 'uppercase',
                letterSpacing: '0.3px',
              }}
            >
              {item.label}
            </span>
            <span
              style={{
                color: 'var(--ok)',
                fontSize: '13px',
                fontWeight: 600,
                fontFamily: "'Monaco', 'Courier New', monospace",
              }}
            >
              {item.size}
            </span>
          </div>
        ))}
      </div>

      {/* Profiles section removed - banned feature per CLAUDE.md */}

      {/* Total Storage */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          padding: '16px',
          background: 'rgba(0, 255, 136, 0.05)',
          border: '2px solid #00ff88',
          borderRadius: '6px',
        }}
      >
        <span
          style={{
            color: 'var(--fg-muted)',
            fontSize: '13px',
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
            fontWeight: 600,
          }}
        >
          TOTAL INDEX STORAGE
        </span>
        <span
          style={{
            color: '#00ff88',
            fontSize: '20px',
            fontWeight: 700,
            fontFamily: "'Monaco', 'Courier New', monospace",
          }}
        >
          {storage.totalStorage}
        </span>
      </div>
    </div>
  );
}

