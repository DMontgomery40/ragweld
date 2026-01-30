/**
 * System Status Widget
 * Displays real-time status for health, repo, chunk summaries, and MCP
 */

import { useState, useEffect, useCallback } from 'react';
import { useAPI } from '@/hooks/useAPI';

interface StatusData {
  health: string;
  repo: string;
  chunkSummaries: string;
  mcp: string;
}

export function SystemStatus() {
  const { api } = useAPI();
  const [status, setStatus] = useState<StatusData>({
    health: '—',
    repo: '—',
    chunkSummaries: '—',
    mcp: '—',
  });

  const refreshStatus = useCallback(async () => {
    const newStatus: StatusData = { ...status };

    // Fetch repo info
    try {
      const configRes = await fetch(api('/api/config'));
      const config = await configRes.json();
      const repo = (config.env && (config.env.REPO || config.default_repo)) || '(none)';
      const reposCount = (config.repos || []).length;
      newStatus.repo = `${repo} (${reposCount} repos)`;
    } catch (e) {
      console.error('[SystemStatus] Failed to fetch repo:', e);
    }

    // Fetch health
    try {
      const healthRes = await fetch(api('/health'));
      const health = await healthRes.json();
      newStatus.health = `${health.status}${health.graph_loaded ? ' (graph ready)' : ''}`;
    } catch (e) {
      console.error('[SystemStatus] Failed to fetch health:', e);
    }

    // Fetch chunk summaries (formerly "cards")
    try {
      const summariesRes = await fetch(api('/api/cards')); // API endpoint unchanged for now
      const summaries = await summariesRes.json();
      newStatus.chunkSummaries = `${summaries.count || 0} summaries`;
    } catch (e) {
      console.error('[SystemStatus] Failed to fetch chunk summaries:', e);
    }

    // Fetch MCP status
    try {
      const mcpRes = await fetch(api('/api/mcp/status'));
      if (mcpRes.ok) {
        const mcpData = await mcpRes.json();
        const parts = [];
        if (mcpData.python_http) {
          const ph = mcpData.python_http;
          parts.push(`py-http:${ph.host}:${ph.port}${ph.path} ${ph.running ? '' : '(stopped)'}`.trim());
        }
        if (mcpData.node_http) {
          const nh = mcpData.node_http;
          parts.push(`node-http:${nh.host}:${nh.port}${nh.path || ''} ${nh.running ? '' : '(stopped)'}`.trim());
        }
        if (mcpData.python_stdio_available !== undefined) {
          parts.push(`py-stdio:${mcpData.python_stdio_available ? 'available' : 'missing'}`);
        }
        newStatus.mcp = parts.join(' | ') || 'unknown';
      } else {
        newStatus.mcp = 'unknown';
      }
    } catch (e) {
      newStatus.mcp = 'unknown';
    }

    setStatus(newStatus);
  }, [api]);

  useEffect(() => {
    refreshStatus();
    const interval = setInterval(refreshStatus, 30000); // Refresh every 30 seconds
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
        <StatusItem label="Corpus" value={status.repo} color="var(--fg)" />
        <StatusItem label="Summaries" value={status.chunkSummaries} color="var(--link)" />
        <StatusItem label="MCP" value={status.mcp} color="var(--link)" />
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
