// AGRO - System Status Panel Component
// Status boxes: Health, Repo, Chunk Summaries, MCP

import React, { useEffect, useState } from 'react';

interface SystemStats {
  health: string;
  repo: string;
  branch: string;
  chunkSummaries: string;
  mcp: string;
}

export function SystemStatusPanel() {
  const [stats, setStats] = useState<SystemStats>({
    health: '—',
    repo: '—',
    branch: '—',
    chunkSummaries: '—',
    mcp: '—',
  });

  const loadStats = async () => {
    try {
      // Health
      const healthResp = await fetch('/api/health');
      const health = await healthResp.json();

      // Index stats
      const indexResp = await fetch('/api/index/stats');
      const indexData = await indexResp.json();

      // Config
      const configResp = await fetch('/api/config');
      const config = await configResp.json();

      // Get repo count
      const repoCount = config.repos?.length || 1;
      
      // Get MCP status from config
      const mcpHost = config.env?.MCP_HTTP_HOST || '0.0.0.0';
      const mcpPort = config.env?.MCP_HTTP_PORT || '8013';
      const mcpPath = config.env?.MCP_HTTP_PATH || '/mcp';
      
      setStats({
        health: health.status === 'healthy' ? 'healthy (graph ready)' : 'degraded',
        repo: `${config.env?.REPO || 'agro'} (${repoCount} repos)`,
        branch: config.git_branch || 'development',
        chunkSummaries: `${indexData.total_chunks || 0} chunks`,
        mcp: `${mcpHost}:${mcpPort}${mcpPath}`,
      });
    } catch (e) {
      console.error('[SystemStatus] Failed to load stats:', e);
    }
  };

  useEffect(() => {
    loadStats();
    const interval = setInterval(loadStats, 30000); // Refresh every 30s
    
    // Listen for refresh events
    const handleRefresh = () => loadStats();
    window.addEventListener('dashboard-refresh', handleRefresh);

    return () => {
      clearInterval(interval);
      window.removeEventListener('dashboard-refresh', handleRefresh);
    };
  }, []);

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
            Health
          </span>
          <span id="dash-health" className="mono" style={{ color: 'var(--ok)', fontWeight: 600 }}>
            {stats.health}
          </span>
        </div>

        {/* Repo */}
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
            Repo
          </span>
          <span id="dash-repo" className="mono" style={{ color: 'var(--fg)', fontWeight: 600 }}>
            {stats.repo}
          </span>
        </div>

        {/* Branch */}
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
            Branch
          </span>
          <span id="dash-branch" className="mono" style={{ color: 'var(--link)', fontWeight: 600 }}>
            {stats.branch}
          </span>
        </div>

        {/* Chunk Summaries (formerly "Cards") */}
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
            Chunks
          </span>
          <span id="dash-chunks" className="mono" style={{ color: 'var(--link)', fontWeight: 600 }}>
            {stats.chunkSummaries}
          </span>
        </div>

        {/* MCP */}
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
            MCP
          </span>
          <div
            id="dash-mcp"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '4px',
              fontSize: '10px',
              fontFamily: "'SF Mono', monospace",
              color: 'var(--link)',
            }}
          >
            {stats.mcp}
          </div>
        </div>
      </div>
    </div>
  );
}

