// Storage Calculator Results Display
// Shows calculated storage requirements with formatted bytes


import type { StorageResults } from '@web/types/storage';
import { formatBytes, formatNumber } from '@web/utils/formatters';

interface ResultsDisplayProps {
  results: StorageResults;
}

export function ResultsDisplay({ results }: ResultsDisplayProps) {
  return (
    <div className="results-display" style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Chunks */}
      <div style={{
        padding: '12px',
        background: '#f9fafb',
        borderRadius: '6px',
        border: '1px solid #e5e7eb'
      }}>
        <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
          Number of Chunks
        </div>
        <div style={{ fontSize: '20px', fontWeight: '600', color: '#111827' }}>
          {formatNumber(results.chunks)}
        </div>
      </div>

      {/* Storage Components */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <h3 style={{ fontSize: '14px', fontWeight: '600', color: '#374151', marginBottom: '4px' }}>
          Storage Components
        </h3>

        <ResultRow label="Raw Embeddings" value={results.rawEmbeddings} />
        <ResultRow label="Qdrant Index" value={results.qdrantSize} />
        <ResultRow label="BM25 Index" value={results.bm25Index} />
        <ResultRow label="Cards/Metadata" value={results.cardsSummary} />
        <ResultRow label="Hydration Cache" value={results.hydration} />
        <ResultRow label="Reranker Cache" value={results.reranker} />
      </div>

      {/* Totals */}
      <div style={{
        marginTop: '8px',
        paddingTop: '16px',
        borderTop: '2px solid #e5e7eb'
      }}>
        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: '12px'
        }}>
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#374151' }}>
            Single Instance Total
          </span>
          <span style={{ fontSize: '18px', fontWeight: '700', color: '#059669' }}>
            {formatBytes(results.singleInstance)}
          </span>
        </div>

        <div style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '12px',
          background: '#f0fdf4',
          borderRadius: '6px',
          border: '1px solid #86efac'
        }}>
          <span style={{ fontSize: '14px', fontWeight: '600', color: '#166534' }}>
            Replicated Total
          </span>
          <span style={{ fontSize: '20px', fontWeight: '700', color: '#166534' }}>
            {formatBytes(results.replicated)}
          </span>
        </div>
      </div>
    </div>
  );
}

// Helper component for result rows
function ResultRow({ label, value }: { label: string; value: number }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      padding: '8px 12px',
      background: '#ffffff',
      borderRadius: '4px',
      border: '1px solid #e5e7eb'
    }}>
      <span style={{ fontSize: '13px', color: '#6b7280' }}>
        {label}
      </span>
      <span style={{ fontSize: '14px', fontWeight: '600', color: '#111827' }}>
        {formatBytes(value)}
      </span>
    </div>
  );
}
