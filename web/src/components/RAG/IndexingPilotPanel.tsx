import { useEffect, useMemo, useState } from 'react';
import { indexingApi } from '@/api';
import type {
  RetrievalPilotSearchPreviewResult,
  RetrievalPilotStatusResponse,
} from '@/types/generated';

type IndexingPilotPanelProps = {
  corpusId: string;
  repoPath: string;
};

const PANEL_STYLE = {
  background: 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.09), rgba(0, 0, 0, 0))',
  border: '1px solid rgba(var(--accent-rgb), 0.22)',
  borderRadius: '14px',
  padding: '18px',
  marginBottom: '18px',
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

export function IndexingPilotPanel({ corpusId, repoPath }: IndexingPilotPanelProps) {
  const [status, setStatus] = useState<RetrievalPilotStatusResponse | null>(null);
  const [results, setResults] = useState<RetrievalPilotSearchPreviewResult[]>([]);
  const [query, setQuery] = useState('fibonacci');
  const [loadingStatus, setLoadingStatus] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const ready = Boolean(corpusId && repoPath);
  const packageSummary = useMemo(
    () =>
      (status?.package_status || []).map((pkg) => ({
        ...pkg,
        tone: pkg.available ? 'var(--ok)' : 'var(--warn)',
      })),
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
          setError(err instanceof Error ? err.message : 'Failed to load OSS retrieval pilot status');
          setStatus(null);
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

  const refreshStatus = async () => {
    if (!ready) return;
    const data = await indexingApi.getPilotStatus(corpusId, repoPath);
    setStatus(data);
    return data;
  };

  const handleExport = async () => {
    if (!ready || exporting) return;
    setExporting(true);
    setError(null);
    try {
      const response = await indexingApi.exportPilot(corpusId, {
        corpus_id: corpusId,
        repo_path: repoPath,
        force_rebuild: Boolean(status?.export_exists),
      });
      setStatus(response.status);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to prepare OSS retrieval pilot export');
    } finally {
      setExporting(false);
    }
  };

  const handlePreview = async () => {
    if (!ready || previewing || !query.trim()) return;
    setPreviewing(true);
    setError(null);
    try {
      const response = await indexingApi.searchPilotPreview(
        corpusId,
        {
          corpus_id: corpusId,
          query: query.trim(),
          top_k: 5,
        },
        repoPath
      );
      setStatus(response.status);
      setResults(response.results || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to preview pilot search');
      setResults([]);
      try {
        await refreshStatus();
      } catch {
        // keep the original user-visible error
      }
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div style={PANEL_STYLE} data-testid="indexing-pilot-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap', marginBottom: '14px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '6px' }}>
            <span style={{ fontSize: '18px' }}>🧪</span>
            <div style={{ fontSize: '15px', fontWeight: 800, color: 'var(--fg)' }}>OSS Retrieval Pilot</div>
            <span style={{ ...BADGE_STYLE, color: 'var(--accent)' }}>Docling + Haystack + Qdrant target</span>
          </div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', lineHeight: 1.5, maxWidth: '880px' }}>
            Prepare a provenance-preserving sidecar export for the first OSS retrieval lane, then run preview search against that export inside the workbench.
          </div>
        </div>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'flex-start' }}>
          <button
            type="button"
            style={{ ...BUTTON_STYLE, opacity: ready ? 1 : 0.6 }}
            disabled={!ready || exporting}
            onClick={() => {
              void handleExport();
            }}
          >
            {exporting ? 'Preparing…' : status?.export_exists ? 'Rebuild Pilot Export' : 'Prepare Pilot Export'}
          </button>
          <button
            type="button"
            style={{ ...BUTTON_STYLE, opacity: ready && status?.search_preview_ready ? 1 : 0.6 }}
            disabled={!ready || !status?.search_preview_ready || previewing}
            onClick={() => {
              void handlePreview();
            }}
          >
            {previewing ? 'Searching…' : 'Preview Search'}
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
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Export</div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
            {loadingStatus ? 'Loading…' : status?.export_exists ? 'Ready' : 'Not prepared'}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
            {(status?.exported_file_count || 0).toLocaleString()} files
            {' · '}
            {(status?.exported_chunk_count || 0).toLocaleString()} chunks
          </div>
        </div>
        <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>Provenance</div>
          <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--fg)' }}>
            {status?.provenance_fields?.length || 0} fields preserved
          </div>
          <div style={{ fontSize: '11px', color: 'var(--fg-muted)', marginTop: '6px' }}>
            file path, line range, token count, chunk identity, graph parity mode
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
          {error || status?.operator_hint || 'Select a corpus and prepare the pilot export.'}
        </div>
      </div>

      <div style={{ border: '1px solid var(--line)', borderRadius: '10px', padding: '12px', background: 'var(--card-bg)' }}>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center', marginBottom: '10px' }}>
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Preview query"
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
            Preview runs against the exported sidecar, not the legacy online search path.
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
                    score {result.score.toFixed(1)}
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
            {status?.search_preview_ready ? 'Run preview search to inspect pilot results here.' : 'Prepare the pilot export to enable preview search.'}
          </div>
        )}
      </div>
    </div>
  );
}
