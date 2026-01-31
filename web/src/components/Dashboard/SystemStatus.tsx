/**
 * System Status Widget
 * Uses Zustand stores per CLAUDE.md requirements
 */

import { useState, useEffect, useCallback } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { apiUrl } from '@/api/client';

interface StatusData {
  health: string;
  corpus: string;
  chunkSummaries: string;
}

export function SystemStatus() {
  const { repos, activeRepo } = useRepoStore();
  const [status, setStatus] = useState<StatusData>({
    health: '—',
    corpus: '—',
    chunkSummaries: '—',
  });

  const refreshStatus = useCallback(async () => {
    const newStatus: StatusData = { ...status };

    // Corpus info from store
    newStatus.corpus = activeRepo
      ? `${activeRepo} (${repos.length} corpora)`
      : `(${repos.length} corpora)`;

    // Fetch health
    try {
      const healthRes = await fetch(apiUrl('/health'));
      const health = await healthRes.json();
      newStatus.health = health.status === 'healthy' ? 'healthy' : 'degraded';
    } catch (e) {
      console.error('[SystemStatus] Failed to fetch health:', e);
    }

    // Fetch chunk summaries count
    if (activeRepo) {
      try {
        const summariesRes = await fetch(apiUrl(`/chunk_summaries?corpus_id=${encodeURIComponent(activeRepo)}`));
        if (summariesRes.ok) {
          const summaries = await summariesRes.json();
          newStatus.chunkSummaries = `${summaries.total || 0} summaries`;
        }
      } catch (e) {
        console.error('[SystemStatus] Failed to fetch chunk summaries:', e);
      }
    }

    setStatus(newStatus);
  }, [activeRepo, repos.length]);

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(refreshStatus, 30000);
    return () => clearInterval(interval);
  }, [refreshStatus]);

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
        ></span>
        System Status
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <StatusItem label="Health" value={status.health} color="var(--ok)" />
        <StatusItem label="Corpus" value={status.corpus} color="var(--fg)" />
        <StatusItem label="Summaries" value={status.chunkSummaries} color="var(--link)" />
      </div>
    </div>
  );
}

interface StatusItemProps {
  label: string;
  value: string;
  color: string;
}

function StatusItem({ label, value, color }: StatusItemProps) {
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
      <span
        style={{
          fontSize: '11px',
          color: 'var(--fg-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}
      >
        {label}
      </span>
      <span className="mono" style={{ color, fontWeight: '600' }}>
        {value}
      </span>
    </div>
  );
}
