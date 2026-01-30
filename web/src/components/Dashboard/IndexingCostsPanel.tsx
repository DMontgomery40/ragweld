// AGRO - Indexing Costs Panel
// Shows total tokens and embedding cost from backend

import React, { useEffect, useState } from 'react';

interface CostMetrics {
  totalTokens: string;
  embeddingCost: string;
}

export function IndexingCostsPanel() {
  const [costs, setCosts] = useState<CostMetrics>({
    totalTokens: '—',
    embeddingCost: '—',
  });

  const loadCosts = async () => {
    try {
      const response = await fetch('/api/index/stats');
      const data = await response.json();
      
      if (data) {
        setCosts({
          totalTokens: (data.total_tokens || 0).toLocaleString(),
          embeddingCost: `$${(data.embedding_cost || 0).toFixed(4)}`,
        });
      }
    } catch (e) {
      console.error('[IndexingCosts] Failed to load:', e);
    }
  };

  useEffect(() => {
    loadCosts();
    const handleRefresh = () => loadCosts();
    window.addEventListener('dashboard-refresh', handleRefresh);
    return () => window.removeEventListener('dashboard-refresh', handleRefresh);
  }, []);

  return (
    <div style={{ marginBottom: '24px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
        <span style={{ fontSize: '20px' }}>💰</span>
        <h3 style={{ margin: 0, fontSize: '18px', fontWeight: 600, color: 'var(--fg)' }}>
          Indexing Costs
        </h3>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '20px' }}>
        {/* Total Tokens */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <span style={{ fontSize: '32px' }}>📊</span>
            <div>
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}
              >
                TOTAL TOKENS
              </div>
              <div
                style={{
                  fontSize: '24px',
                  fontWeight: 700,
                  color: '#00ff88',
                  fontFamily: "'Monaco', 'Courier New', monospace",
                }}
              >
                {costs.totalTokens}
              </div>
            </div>
          </div>
        </div>

        {/* Embedding Cost */}
        <div
          style={{
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            borderRadius: '8px',
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
            <span style={{ fontSize: '32px' }}>💵</span>
            <div>
              <div
                style={{
                  fontSize: '11px',
                  color: 'var(--fg-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.5px',
                }}
              >
                EMBEDDING COST
              </div>
              <div
                style={{
                  fontSize: '24px',
                  fontWeight: 700,
                  color: '#00ff88',
                  fontFamily: "'Monaco', 'Courier New', monospace",
                }}
              >
                {costs.embeddingCost}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

