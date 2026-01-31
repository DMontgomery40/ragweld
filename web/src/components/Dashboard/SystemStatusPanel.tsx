// TriBridRAG - System Status Panel Component
// Uses Zustand stores per CLAUDE.md requirements

import { useEffect, useState } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { apiUrl } from '@/api/client';

interface SystemStats {
  health: string;
  corpus: string;
  chunks: string;
}

export function SystemStatusPanel() {
  const { repos, activeRepo } = useRepoStore();
  const [stats, setStats] = useState<SystemStats>({
    health: '—',
    corpus: '—',
    chunks: '—',
  });

  const loadStats = async () => {
    try {
      // Health from API
      const healthResp = await fetch(apiUrl('/health'));
      const health = await healthResp.json();

      // Index stats from API
      let totalChunks = 0;
      if (activeRepo) {
        try {
          const indexResp = await fetch(apiUrl(`/index/stats?corpus_id=${encodeURIComponent(activeRepo)}`));
          if (indexResp.ok) {
            const indexData = await indexResp.json();
            totalChunks = indexData.total_chunks || 0;
          }
        } catch {
          // Index stats not available
        }
      }

      setStats({
        health: health.status === 'healthy' ? 'healthy' : 'degraded',
        corpus: activeRepo ? `${activeRepo} (${repos.length} corpora)` : `(${repos.length} corpora)`,
        chunks: `${totalChunks} chunks`,
      });
    } catch (e) {
      console.error('[SystemStatusPanel] Failed to load stats:', e);
    }
  };

  useEffect(() => {
    loadStats();
    const interval = setInterval(loadStats, 30000);

    const handleRefresh = () => loadStats();
    window.addEventListener('dashboard-refresh', handleRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, [activeRepo, repos.length]);

  return (
    <div>
      <h3
        style={{
          fontSize: '14px',
          marginBottom: '16px',
          color: 'var(--accent)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
        }}
      >
        <span
          style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: 'var(--accent)',
            boxShadow: '0 0 8px var(--accent)',
          }}
        />
        System Status
      </h3>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        {/* Health */}
        <StatusRow label="Health" value={stats.health} color="var(--ok)" id="dash-health" />
        {/* Corpus */}
        <StatusRow label="Corpus" value={stats.corpus} color="var(--fg)" id="dash-corpus" />
        {/* Chunks */}
        <StatusRow label="Chunks" value={stats.chunks} color="var(--link)" id="dash-chunks" />
      </div>
    </div>
  );
}

interface StatusRowProps {
  label: string;
  value: string;
  color: string;
  id?: string;
}

function StatusRow({ label, value, color, id }: StatusRowProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        padding: '8px 12px',
        background: 'var(--card-bg)',
        borderRadius: '4px',
        border: '1px solid var(--line)',
      }}
    >
      <span style={{ fontSize: '11px', color: 'var(--fg-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        {label}
      </span>
      <span id={id} className="mono" style={{ color, fontWeight: 600 }}>
        {value}
      </span>
    </div>
  );
}
