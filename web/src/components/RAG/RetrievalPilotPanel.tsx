import { useEffect, useMemo, useState } from 'react';
import { indexingApi } from '@/api';
import type {
  RetrievalPilotSearchResult,
  RetrievalPilotStatusResponse,
} from '@/types/generated';

type RetrievalPilotPanelProps = {
  corpusId: string;
  repoPath: string;
};

const PANEL_STYLE = {
  background: 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.08), rgba(0, 0, 0, 0))',
  border: '1px solid rgba(var(--accent-rgb), 0.22)',
  borderRadius: '14px',
  padding: '18px',
  marginBottom: '18px',
};

const BUTTON_STYLE = {
  padding: '10px 12px',
  borderRadius: '8px',
  border: '1px solid var(--line)',
  background: 'var(--bg-elev1)',
  color: 'var(--fg)',
  cursor: 'pointer',
  fontSize: '12px',
  fontWeight: 700,
};

const BADGE_STYLE = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '6px',
  padding: '4px 8px',
  borderRadius: '999px',
  border: '1px solid var(--line)',
  fontSize: '11px',
  fontWeight: 700,
};

export function RetrievalPilotPanel({ corpusId, repoPath }: RetrievalPilotPanelProps) {
  const [status, setStatus] = useState<RetrievalPilotStatusResponse | null>(null);
  const [results, setResults] = useState<RetrievalPilotSearchResult[]>([]);
  const [query, setQuery] = useState('fibonacci');
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [ingesting, setIngesting] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = Boolean(corpusId && repoPath);
  const packageSummary = useMemo(
    () => (status?.package_status || []).map((pkg) => ({ ...pkg, tone: pkg.available ? 'var(--ok)' : 'var(--warn)' })),
    [status?.package_status]
  );

  useEffect(() => {
    let cancelled = false;
    if (!ready) {
      setStatus(null);
      setResults([]);
      return;
    }
    setLoadingStatus(true);
    setError(null);
    void indexingApi
      .getPilotStatus(corpusId, repoPath)
      .then((data) => {
        if (!cancelled) {
          setStatus(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus(null);
          setError(err instanceof Error ? err.message : 'Failed to load OSS retrieval lane status');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoadingStatus(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, ready, repoPath]);

  const handleIngest = async () => {
    if (!ready || ingesting) return;
    setIngesting(true);
    setError(null);
    try {
      const response = await indexingApi.ingestPilot(
        corpusId,
        { corpus_id: corpusId, force_rebuild: Boolean(status?.execution_ready) },
        repoPath
      );
      setStatus(response.status);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to hydrate Haystack/Qdrant lane');
    } finally {
      setIngesting(false);
    }
  };

  const handleSearch = async () => {
    if (!ready || searching || !query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const response = await indexingApi.searchPilot(
        corpusId,
        { corpus_id: corpusId, query: query.trim(), top_k: 5 },
        repoPath
      );
      setStatus(response.status);
      setResults(response.results || []);
    } catch (err: unknown) {
      setResults([]);
      setError(err instanceof Error ? err.message : 'Failed to run Haystack/Qdrant search');
    } finally {
      setSearching(false);
    }
  };

  return (
    <div style={PANEL_STYLE} data-testid="retrieval-pilot-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap', marginBottom: '14px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '6px' }}>
            <span style={{ fontSize: '18px' }}>🚀</span>
            <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--fg)' }}>OSS Retrieval Execution Lane</div>
            <span style={{ ...BADGE_STYLE, color: status?.execution_ready ? 'var(--ok)' : 'var(--warn)' }}>
              {loadingStatus ? 'loading' : status?.execution_ready ? 'haystack/qdrant ready' : 'not hydrated'}
            </span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5, maxWidth: '880px' }}>
            This is the real pilot retrieval path on top of the sidecar export: local Qdrant storage plus Haystack retrieval, with the same provenance contract visible inside the workbench.
          </div>
        </div>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <button
            type="button"
            style={{ ...BUTTON_STYLE, opacity: ready ? 1 : 0.6 }}
            disabled={!ready || ingesting}
            onClick={() => {
              void handleIngest();
            }}
          >
            {ingesting ? 'Hydrating…' : status?.execution_ready ? 'Rebuild Haystack/Qdrant Lane' : 'Hydrate Haystack/Qdrant Lane'}
          </button>
          <button
            type="button"
            style={{ ...BUTTON_STYLE, opacity: ready && status?.execution_ready ? 1 : 0.6 }}
            disabled={!ready || !status?.execution_ready || searching}
            onClick={() => {
              void handleSearch();
            }}
          >
            {searching ? 'Searching…' : 'Run OSS Search'}
          </button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px', marginBottom: '14px' }}>
        <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Corpus</div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>{corpusId || 'Select a corpus'}</div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px', fontFamily: 'var(--font-mono)' }}>
            {repoPath || 'No corpus path available yet'}
          </div>
        </div>
        <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Hydrated Chunks</div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
            {(status?.indexed_document_count || 0).toLocaleString()}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
            collection {status?.collection_name || 'pilot_chunks'}
          </div>
        </div>
        <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Local Store</div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
            {status?.execution_backend || 'haystack_qdrant_local'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px', fontFamily: 'var(--font-mono)' }}>
            {status?.qdrant_path || 'No local Qdrant path yet'}
          </div>
        </div>
      </div>

      <div style={{ marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Backend Readiness
        </div>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          {packageSummary.map((pkg) => (
            <span key={pkg.package} style={{ ...BADGE_STYLE, color: pkg.tone }}>
              {pkg.label}: {pkg.available ? 'ready' : 'missing'}
            </span>
          ))}
        </div>
      </div>

      <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)', marginBottom: '14px' }}>
        <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
          Operator Hint
        </div>
        <div style={{ fontSize: '13px', color: 'var(--fg)', lineHeight: 1.6 }}>
          {error || status?.operator_hint || 'Select a corpus, then hydrate the local Haystack/Qdrant lane.'}
        </div>
      </div>

      <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '10px' }}>
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="OSS retrieval query"
            style={{
              flex: '1 1 280px',
              minWidth: 220,
              padding: '10px 12px',
              borderRadius: '8px',
              border: '1px solid var(--line)',
              background: 'var(--bg)',
              color: 'var(--fg)',
            }}
          />
          <span style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
            Search runs against the hydrated Haystack/Qdrant lane, not the preview scorer.
          </span>
        </div>

        {results.length ? (
          <div style={{ display: 'grid', gap: '10px' }}>
            {results.map((result) => (
              <div
                key={result.chunk_id}
                style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--bg-elev1)' }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', flexWrap: 'wrap', marginBottom: '6px' }}>
                  <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
                    {result.file_path}:{result.start_line}-{result.end_line}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--fg-muted)', fontFamily: 'var(--font-mono)' }}>
                    score {result.score.toFixed(3)}
                  </div>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '8px', fontFamily: 'var(--font-mono)' }}>
                  {result.source_path}
                </div>
                <div style={{ fontSize: '12px', color: 'var(--fg)', lineHeight: 1.6 }}>{result.excerpt}</div>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)' }}>
            {status?.execution_ready ? 'Run OSS Search to inspect Haystack/Qdrant results here.' : 'Hydrate the Haystack/Qdrant lane to enable real OSS retrieval.'}
          </div>
        )}
      </div>
    </div>
  );
}
