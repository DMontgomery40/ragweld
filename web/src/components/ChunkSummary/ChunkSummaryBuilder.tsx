/**
 * ChunkSummaryBuilder - Builds chunk summaries for a corpus
 *
 * Uses types from generated.ts (Pydantic-first):
 * - ChunkSummariesBuildRequest
 * - ChunkSummariesResponse
 * - ChunkSummary
 */

import { useState, useCallback } from 'react';
import { useRepoStore } from '@/stores';
import type { ChunkSummariesBuildRequest, ChunkSummariesResponse } from '@/types/generated';

const CHUNK_SUMMARIES_API = '/api/chunk_summaries';

interface ChunkSummaryBuilderProps {
  onBuildComplete?: (response: ChunkSummariesResponse) => void;
  onError?: (error: string) => void;
}

export function ChunkSummaryBuilder({ onBuildComplete, onError }: ChunkSummaryBuilderProps) {
  const { activeRepo } = useRepoStore();
  const [enrich, setEnrich] = useState(true);
  const [max, setMax] = useState<number | undefined>(undefined);
  const [isBuilding, setIsBuilding] = useState(false);
  const [result, setResult] = useState<ChunkSummariesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const startBuild = useCallback(async () => {
    if (!activeRepo) {
      const msg = 'No corpus selected';
      setError(msg);
      onError?.(msg);
      return;
    }

    setIsBuilding(true);
    setError(null);
    setResult(null);

    try {
      const request: ChunkSummariesBuildRequest = {
        corpus_id: activeRepo,
        enrich,
        max: max ?? null,
      };

      const response = await fetch(`${CHUNK_SUMMARIES_API}/build`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Build failed: ${response.status}`);
      }

      const data: ChunkSummariesResponse = await response.json();
      setResult(data);
      onBuildComplete?.(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Build failed';
      setError(message);
      onError?.(message);
    } finally {
      setIsBuilding(false);
    }
  }, [activeRepo, enrich, max, onBuildComplete, onError]);

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ marginBottom: '24px' }}>
        <h3 style={{ margin: '0 0 16px 0', fontSize: '18px', fontWeight: 600 }}>
          Build Chunk Summaries
        </h3>

        <div style={{ display: 'grid', gap: '12px', maxWidth: '600px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 500 }}>
              Corpus
            </label>
            <input
              type="text"
              value={activeRepo || ''}
              disabled
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '4px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg-muted)'
              }}
            />
            <p style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '4px' }}>
              Select a corpus from the Repository selector
            </p>
          </div>

          <div>
            <label style={{ display: 'flex', alignItems: 'center', fontSize: '13px', cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={enrich}
                onChange={(e) => setEnrich(e.target.checked)}
                disabled={isBuilding}
                style={{ marginRight: '8px' }}
              />
              Enrich with technical details
            </label>
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '4px', fontSize: '13px', fontWeight: 500 }}>
              Max Summaries (optional)
            </label>
            <input
              type="number"
              value={max ?? ''}
              onChange={(e) => setMax(e.target.value ? parseInt(e.target.value, 10) : undefined)}
              disabled={isBuilding}
              placeholder="Leave empty for config default"
              min={1}
              style={{
                width: '100%',
                padding: '8px',
                borderRadius: '4px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev1)',
                color: 'var(--fg)'
              }}
            />
          </div>

          <div style={{ marginTop: '8px' }}>
            <button
              onClick={startBuild}
              disabled={isBuilding || !activeRepo}
              style={{
                padding: '10px 20px',
                borderRadius: '6px',
                border: 'none',
                background: isBuilding || !activeRepo ? 'var(--fg-muted)' : 'var(--accent)',
                color: 'white',
                fontWeight: 600,
                cursor: isBuilding || !activeRepo ? 'not-allowed' : 'pointer',
                fontSize: '14px'
              }}
            >
              {isBuilding ? 'Building...' : 'Build Chunk Summaries'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div style={{
          padding: '12px',
          borderRadius: '6px',
          background: 'var(--err-bg)',
          border: '1px solid var(--err)',
          color: 'var(--err)',
          fontSize: '13px',
          marginBottom: '16px'
        }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{
          padding: '16px',
          borderRadius: '8px',
          border: '2px solid var(--ok)',
          background: 'var(--bg-elev1)'
        }}>
          <div style={{ marginBottom: '12px', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '14px', fontWeight: 600, color: 'var(--ok)' }}>
              Build Complete
            </span>
            <span style={{ fontSize: '13px', color: 'var(--fg-muted)' }}>
              {result.chunk_summaries.length} summaries generated
            </span>
          </div>

          {result.last_build && (
            <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
              <div>Corpus: {result.last_build.corpus_id}</div>
              <div>Total: {result.last_build.total}</div>
              {result.last_build.enriched !== undefined && (
                <div>Enriched: {result.last_build.enriched}</div>
              )}
              {result.last_build.timestamp && (
                <div>Built: {new Date(result.last_build.timestamp).toLocaleString()}</div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
