/**
 * IndexStatsPanel - Display index storage and stats
 *
 * Shows storage breakdown, chunk counts, and other index metrics.
 * Uses useDashboard hook to get index stats.
 */

import { useEffect, useState, useCallback } from 'react';
import { getIndexStats } from '@/api/dashboard';
import type { DashboardIndexStatsResponse } from '@/types/generated';

interface IndexStatsPanelProps {
  /** Auto-refresh interval in ms (0 = disabled) */
  refreshInterval?: number;
}

/**
 * Format bytes to human-readable string
 */
function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
}

export function IndexStatsPanel({ refreshInterval = 0 }: IndexStatsPanelProps) {
  const [stats, setStats] = useState<DashboardIndexStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    try {
      const data = await getIndexStats();
      setStats(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load stats');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadStats();

    if (refreshInterval > 0) {
      const interval = setInterval(loadStats, refreshInterval);
      return () => clearInterval(interval);
    }
  }, [loadStats, refreshInterval]);

  if (loading) {
    return (
      <div className="index-stats-panel" style={panelStyles}>
        <div style={{ color: 'var(--fg-muted)', fontSize: '13px' }}>
          Loading stats...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="index-stats-panel" style={panelStyles}>
        <div style={{ color: 'var(--error)', fontSize: '13px' }}>{error}</div>
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  const statItems = [
    {
      label: 'Total Storage',
      value: formatBytes(stats.total_storage || 0),
      icon: '💾',
    },
    {
      label: 'Postgres Total',
      value: formatBytes(stats.storage_breakdown.postgres_total_bytes || 0),
      icon: '🗄️',
    },
    {
      label: 'BM25 Index',
      value: formatBytes(stats.storage_breakdown.bm25_index_bytes || 0),
      icon: '📑',
    },
    {
      label: 'Chunks',
      value: formatBytes(stats.storage_breakdown.chunks_bytes || 0),
      icon: '📄',
    },
    {
      label: 'pgvector vectors',
      value: formatBytes(stats.storage_breakdown.embeddings_bytes || 0),
      icon: '🔷',
    },
    {
      label: 'Keywords',
      value: String(stats.keywords_count || 0),
      icon: '🔑',
    },
    {
      label: 'Neo4j Store',
      value: formatBytes(stats.storage_breakdown.neo4j_store_bytes || 0),
      icon: '🧠',
    },
  ];

  return (
    <div className="index-stats-panel" style={panelStyles}>
      <div style={headerStyles}>
        <span style={{ fontSize: '16px' }}>📊</span>
        <span>Index Stats</span>
        <button
          type="button"
          onClick={loadStats}
          style={refreshButtonStyles}
          title="Refresh stats"
        >
          🔄
        </button>
      </div>

      <div style={gridStyles}>
        {statItems.map(item => (
          <div key={item.label} style={statItemStyles}>
            <div style={statIconStyles}>{item.icon}</div>
            <div>
              <div style={statValueStyles}>{item.value}</div>
              <div style={statLabelStyles}>{item.label}</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// Styles
const panelStyles: React.CSSProperties = {
  background: 'var(--card-bg)',
  border: '1px solid var(--line)',
  borderRadius: '12px',
  padding: '16px',
  marginTop: '24px',
};

const headerStyles: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  fontSize: '14px',
  fontWeight: 600,
  color: 'var(--fg)',
  marginBottom: '16px',
};

const refreshButtonStyles: React.CSSProperties = {
  marginLeft: 'auto',
  background: 'transparent',
  border: 'none',
  cursor: 'pointer',
  fontSize: '14px',
  padding: '4px',
  borderRadius: '4px',
  transition: 'all 0.2s ease',
};

const gridStyles: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
  gap: '12px',
};

const statItemStyles: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  padding: '10px',
  background: 'var(--bg)',
  borderRadius: '8px',
  border: '1px solid var(--line)',
};

const statIconStyles: React.CSSProperties = {
  fontSize: '20px',
};

const statValueStyles: React.CSSProperties = {
  fontSize: '14px',
  fontWeight: 600,
  color: 'var(--fg)',
};

const statLabelStyles: React.CSSProperties = {
  fontSize: '11px',
  color: 'var(--fg-muted)',
};
