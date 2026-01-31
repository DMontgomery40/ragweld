/**
 * KeywordManager - Manages discriminative keywords for a corpus
 *
 * Uses types from generated.ts (Pydantic-first):
 * - KeywordsGenerateRequest, KeywordsGenerateResponse
 */

import { useState, useCallback } from 'react';
import { useRepoStore } from '@/stores';
import type { KeywordsGenerateResponse } from '@/types/generated';

const KEYWORDS_API = '/api/keywords';

export function KeywordManager() {
  const { activeRepo } = useRepoStore();
  const [keywords, setKeywords] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const generateKeywords = useCallback(async () => {
    if (!activeRepo) {
      setError('No corpus selected');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${KEYWORDS_API}/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ corpus_id: activeRepo }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `Failed to generate keywords: ${response.status}`);
      }

      const data: KeywordsGenerateResponse = await response.json();
      setKeywords(data.keywords);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to generate keywords');
    } finally {
      setLoading(false);
    }
  }, [activeRepo]);

  return (
    <div style={{ padding: '16px' }}>
      <div style={{ marginBottom: '16px', display: 'flex', gap: '12px', alignItems: 'center' }}>
        <h3 style={{ margin: 0, fontSize: '14px', color: 'var(--fg)' }}>
          Discriminative Keywords
        </h3>
        <button
          onClick={generateKeywords}
          disabled={loading || !activeRepo}
          style={{
            padding: '6px 12px',
            background: loading ? 'var(--bg-elev2)' : 'var(--accent)',
            color: loading ? 'var(--fg-muted)' : 'var(--accent-contrast)',
            border: 'none',
            borderRadius: '4px',
            fontSize: '12px',
            cursor: loading ? 'not-allowed' : 'pointer',
          }}
        >
          {loading ? 'Generating...' : 'Generate Keywords'}
        </button>
      </div>

      {error && (
        <div style={{
          padding: '12px',
          background: 'var(--err-bg)',
          border: '1px solid var(--err)',
          borderRadius: '4px',
          color: 'var(--err)',
          marginBottom: '12px',
          fontSize: '12px',
        }}>
          {error}
        </div>
      )}

      {keywords.length > 0 ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {keywords.map((kw) => (
            <span
              key={kw}
              style={{
                padding: '4px 8px',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                fontSize: '11px',
                color: 'var(--fg)',
              }}
            >
              {kw}
            </span>
          ))}
        </div>
      ) : (
        <div style={{ color: 'var(--fg-muted)', fontSize: '12px' }}>
          No keywords generated yet. Click "Generate Keywords" to extract discriminative terms from indexed content.
        </div>
      )}
    </div>
  );
}

export default KeywordManager;
