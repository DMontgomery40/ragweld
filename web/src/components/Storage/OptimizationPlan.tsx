// Storage Optimization Plan Comparison
// Displays aggressive vs conservative storage strategies


import type { Calculator2Results } from '@web/types/storage';
import { formatBytes } from '@web/utils/formatters';

interface OptimizationPlanProps {
  results: Calculator2Results;
}

export function OptimizationPlan({ results }: OptimizationPlanProps) {
  return (
    <div className="optimization-plan">
      {/* Status Message */}
      <div
        style={{
          padding: '16px',
          borderRadius: '8px',
          marginBottom: '24px',
          background:
            results.statusType === 'success'
              ? '#f0fdf4'
              : results.statusType === 'warning'
              ? '#fef3c7'
              : '#fee2e2',
          border: `1px solid ${
            results.statusType === 'success'
              ? '#86efac'
              : results.statusType === 'warning'
              ? '#fcd34d'
              : '#fca5a5'
          }`,
          color:
            results.statusType === 'success'
              ? '#166534'
              : results.statusType === 'warning'
              ? '#92400e'
              : '#991b1b'
        }}
      >
        <p style={{ fontSize: '14px', fontWeight: '500' }}>
          {results.statusMessage}
        </p>
      </div>

      {/* Precision Comparison */}
      <div
        style={{
          background: '#ffffff',
          padding: '20px',
          borderRadius: '8px',
          border: '1px solid #e5e7eb',
          marginBottom: '24px'
        }}
      >
        <h3 style={{ fontSize: '16px', fontWeight: '600', marginBottom: '12px' }}>
          Embedding Storage by Precision
        </h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
          <PrecisionCard label="float32" value={results.precisions.float32} />
          <PrecisionCard label="float16" value={results.precisions.float16} />
          <PrecisionCard label="int8" value={results.precisions.int8} />
          <PrecisionCard label="PQ8" value={results.precisions.pq8} highlight />
        </div>
      </div>

      {/* Plan Comparison */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        {/* Aggressive Plan */}
        <div
          style={{
            background: '#ffffff',
            padding: '24px',
            borderRadius: '8px',
            border: results.aggressivePlan.fits ? '2px solid #86efac' : '2px solid #fca5a5'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: '600', color: '#111827' }}>
              {results.aggressivePlan.name}
            </h3>
            {results.aggressivePlan.fits && (
              <span
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: '#dcfce7',
                  color: '#166534',
                  fontSize: '12px',
                  fontWeight: '600'
                }}
              >
                FITS
              </span>
            )}
            {!results.aggressivePlan.fits && (
              <span
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: '#fee2e2',
                  color: '#991b1b',
                  fontSize: '12px',
                  fontWeight: '600'
                }}
              >
                EXCEEDS
              </span>
            )}
          </div>

          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
              Single Instance
            </div>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#111827' }}>
              {formatBytes(results.aggressivePlan.total)}
            </div>
          </div>

          <div style={{ marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid #e5e7eb' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
              Replicated
            </div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: '#6b7280' }}>
              {formatBytes(results.aggressivePlan.replicated)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>
              Includes:
            </div>
            <ul style={{ paddingLeft: '20px', margin: 0, fontSize: '13px', color: '#6b7280', lineHeight: '1.6' }}>
              {results.aggressivePlan.description.map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
            </ul>
          </div>
        </div>

        {/* Conservative Plan */}
        <div
          style={{
            background: '#ffffff',
            padding: '24px',
            borderRadius: '8px',
            border: results.conservativePlan.fits ? '2px solid #86efac' : '2px solid #fca5a5'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
            <h3 style={{ fontSize: '18px', fontWeight: '600', color: '#111827' }}>
              {results.conservativePlan.name}
            </h3>
            {results.conservativePlan.fits && (
              <span
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: '#dcfce7',
                  color: '#166534',
                  fontSize: '12px',
                  fontWeight: '600'
                }}
              >
                FITS
              </span>
            )}
            {!results.conservativePlan.fits && (
              <span
                style={{
                  padding: '4px 8px',
                  borderRadius: '4px',
                  background: '#fee2e2',
                  color: '#991b1b',
                  fontSize: '12px',
                  fontWeight: '600'
                }}
              >
                EXCEEDS
              </span>
            )}
          </div>

          <div style={{ marginBottom: '16px' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
              Single Instance
            </div>
            <div style={{ fontSize: '24px', fontWeight: '700', color: '#111827' }}>
              {formatBytes(results.conservativePlan.total)}
            </div>
          </div>

          <div style={{ marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid #e5e7eb' }}>
            <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '4px' }}>
              Replicated
            </div>
            <div style={{ fontSize: '18px', fontWeight: '600', color: '#6b7280' }}>
              {formatBytes(results.conservativePlan.replicated)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>
              Includes:
            </div>
            <ul style={{ paddingLeft: '20px', margin: 0, fontSize: '13px', color: '#6b7280', lineHeight: '1.6' }}>
              {results.conservativePlan.description.map((item, idx) => (
                <li key={idx}>{item}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

// Helper component for precision cards
function PrecisionCard({ label, value, highlight = false }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div
      style={{
        padding: '12px',
        borderRadius: '6px',
        background: highlight ? '#eff6ff' : '#f9fafb',
        border: highlight ? '1px solid #60a5fa' : '1px solid #e5e7eb'
      }}
    >
      <div style={{ fontSize: '11px', color: '#6b7280', marginBottom: '4px' }}>
        {label}
      </div>
      <div style={{ fontSize: '14px', fontWeight: '600', color: highlight ? '#1e40af' : '#111827' }}>
        {formatBytes(value)}
      </div>
    </div>
  );
}
