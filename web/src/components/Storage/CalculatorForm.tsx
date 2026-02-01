// Storage Calculator Form - Input Controls
// Provides accessible form inputs with proper labeling and validation


import type { CalculatorInputs, Calculator2Inputs } from '@web/types/storage';

interface CalculatorFormProps {
  inputs: CalculatorInputs | Calculator2Inputs;
  onUpdate: (key: string, value: number) => void;
  mode: 'full' | 'optimize';
}

export function CalculatorForm({ inputs, onUpdate, mode }: CalculatorFormProps) {
  const isFullMode = mode === 'full';
  const fullInputs = isFullMode ? (inputs as CalculatorInputs) : null;
  const optInputs = !isFullMode ? (inputs as Calculator2Inputs) : null;

  return (
    <div className="calculator-form" style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Repository Size */}
      <div>
        <label htmlFor="repo-size" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
          Repository Size
        </label>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            id="repo-size"
            type="number"
            min="0"
            step="0.1"
            value={inputs.repoSize}
            onChange={(e) => onUpdate('repoSize', parseFloat(e.target.value))}
            style={{
              flex: 1,
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Repository size value"
          />
          <select
            value={inputs.repoUnit}
            onChange={(e) => onUpdate('repoUnit', parseFloat(e.target.value))}
            style={{
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Repository size unit"
          >
            <option value={1024}>KiB</option>
            <option value={1048576}>MiB</option>
            <option value={1073741824}>GiB</option>
            <option value={1099511627776}>TiB</option>
          </select>
        </div>
      </div>

      {/* Target Size (Optimization only) */}
      {!isFullMode && optInputs && (
        <div>
          <label htmlFor="target-size" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
            Target Storage Limit
          </label>
          <div style={{ display: 'flex', gap: '8px' }}>
            <input
              id="target-size"
              type="number"
              min="0"
              step="0.1"
              value={optInputs.targetSize}
              onChange={(e) => onUpdate('targetSize', parseFloat(e.target.value))}
              style={{
                flex: 1,
                padding: '8px 12px',
                border: '1px solid #d1d5db',
                borderRadius: '4px',
                fontSize: '14px'
              }}
              aria-label="Target storage limit value"
            />
            <select
              value={optInputs.targetUnit}
              onChange={(e) => onUpdate('targetUnit', parseFloat(e.target.value))}
              style={{
                padding: '8px 12px',
                border: '1px solid #d1d5db',
                borderRadius: '4px',
                fontSize: '14px'
              }}
              aria-label="Target storage limit unit"
            >
              <option value={1024}>KiB</option>
              <option value={1048576}>MiB</option>
              <option value={1073741824}>GiB</option>
              <option value={1099511627776}>TiB</option>
            </select>
          </div>
        </div>
      )}

      {/* Chunk Size */}
      <div>
        <label htmlFor="chunk-size" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
          Chunk Size
        </label>
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            id="chunk-size"
            type="number"
            min="0.1"
            step="0.1"
            value={inputs.chunkSize}
            onChange={(e) => onUpdate('chunkSize', parseFloat(e.target.value))}
            style={{
              flex: 1,
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Chunk size value"
          />
          <select
            value={inputs.chunkUnit}
            onChange={(e) => onUpdate('chunkUnit', parseFloat(e.target.value))}
            style={{
              padding: '8px 12px',
              border: '1px solid #d1d5db',
              borderRadius: '4px',
              fontSize: '14px'
            }}
            aria-label="Chunk size unit"
          >
            <option value={1}>B</option>
            <option value={1024}>KiB</option>
            <option value={1048576}>MiB</option>
          </select>
        </div>
      </div>

      {/* Embedding Dimensions */}
      <div>
        <label htmlFor="embedding-dim" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
          Embedding Dimensions
        </label>
        <input
          id="embedding-dim"
          type="number"
          min="1"
          step="1"
          value={inputs.embeddingDim}
          onChange={(e) => onUpdate('embeddingDim', parseInt(e.target.value))}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid #d1d5db',
            borderRadius: '4px',
            fontSize: '14px'
          }}
          aria-label="Embedding dimensions"
        />
        <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
          Common: 512, 768, 1024, 1536
        </p>
      </div>

      {/* Full Mode Specific Controls */}
      {isFullMode && fullInputs && (
        <>
          {/* Precision */}
          <div>
            <label htmlFor="precision" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              Precision
            </label>
            <select
              id="precision"
              value={fullInputs.precision}
              onChange={(e) => onUpdate('precision', parseFloat(e.target.value) as 1 | 2 | 4)}
              style={{
                width: '100%',
                padding: '8px 12px',
                border: '1px solid #d1d5db',
                borderRadius: '4px',
                fontSize: '14px'
              }}
              aria-label="Vector precision"
            >
              <option value={4}>float32 (4 bytes)</option>
              <option value={2}>float16 (2 bytes)</option>
              <option value={1}>int8 (1 byte)</option>
            </select>
          </div>

          {/* Qdrant Overhead */}
          <div>
            <label htmlFor="qdrant-overhead" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              Qdrant Multiplier: {fullInputs.qdrantOverhead.toFixed(2)}x
            </label>
            <input
              id="qdrant-overhead"
              type="range"
              min="1.0"
              max="3.0"
              step="0.1"
              value={fullInputs.qdrantOverhead}
              onChange={(e) => onUpdate('qdrantOverhead', parseFloat(e.target.value))}
              style={{ width: '100%' }}
              aria-label="Qdrant overhead multiplier"
            />
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Index overhead (typically 1.5x)
            </p>
          </div>

          {/* Hydration Percentage */}
          <div>
            <label htmlFor="hydration" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              Hydration: {fullInputs.hydrationPercent}%
            </label>
            <input
              id="hydration"
              type="range"
              min="0"
              max="100"
              step="5"
              value={fullInputs.hydrationPercent}
              onChange={(e) => onUpdate('hydrationPercent', parseFloat(e.target.value))}
              style={{ width: '100%' }}
              aria-label="Hydration percentage"
            />
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Percentage of raw data cached in RAM
            </p>
          </div>

          {/* Replication Factor */}
          <div>
            <label htmlFor="replication" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              Replication Factor: {fullInputs.replicationFactor}
            </label>
            <input
              id="replication"
              type="range"
              min="1"
              max="5"
              step="1"
              value={fullInputs.replicationFactor}
              onChange={(e) => onUpdate('replicationFactor', parseFloat(e.target.value))}
              style={{ width: '100%' }}
              aria-label="Replication factor"
            />
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Number of replicas (1 = no replication)
            </p>
          </div>
        </>
      )}

      {/* Optimization Mode Specific Controls */}
      {!isFullMode && optInputs && (
        <>
          {/* BM25 Percent */}
          <div>
            <label htmlFor="bm25-percent" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              BM25 Index: {optInputs.bm25Percent}% of repo
            </label>
            <input
              id="bm25-percent"
              type="range"
              min="0"
              max="50"
              step="5"
              value={optInputs.bm25Percent}
              onChange={(e) => onUpdate('bm25Percent', parseFloat(e.target.value))}
              style={{ width: '100%' }}
              aria-label="BM25 index size percentage"
            />
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Typically 20% of repository size
            </p>
          </div>

          {/* Cards Percent */}
          <div>
            <label htmlFor="cards-percent" style={{ display: 'block', fontSize: '14px', fontWeight: '500', marginBottom: '6px' }}>
              Cards/Metadata: {optInputs.cardsPercent}% of repo
            </label>
            <input
              id="cards-percent"
              type="range"
              min="0"
              max="30"
              step="5"
              value={optInputs.cardsPercent}
              onChange={(e) => onUpdate('cardsPercent', parseFloat(e.target.value))}
              style={{ width: '100%' }}
              aria-label="Cards and metadata size percentage"
            />
            <p style={{ fontSize: '12px', color: '#6b7280', marginTop: '4px' }}>
              Typically 10% of repository size
            </p>
          </div>
        </>
      )}
    </div>
  );
}
