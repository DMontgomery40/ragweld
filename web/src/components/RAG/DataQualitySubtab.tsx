import { useCallback, useEffect, useMemo, useState } from 'react';
import { useConfigField } from '@/hooks';
import type {
  ChunkSummariesBuildRequest,
  ChunkSummariesLastBuild,
  ChunkSummariesResponse,
  ChunkSummary,
  KeywordsGenerateRequest,
  KeywordsGenerateResponse,
} from '@/types/generated';

function parseList(text: string): string[] {
  return text
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function DataQualitySubtab() {
  // Corpus selection (UI wording); API uses corpus_id.
  const [corpusId, setCorpusId] = useState<string>(() => {
    try {
      const u = new URL(window.location.href);
      return (
        u.searchParams.get('corpus') ||
        u.searchParams.get('repo') ||
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        'tribrid'
      );
    } catch {
      return (
        localStorage.getItem('tribrid_active_corpus') ||
        localStorage.getItem('tribrid_active_repo') ||
        'tribrid'
      );
    }
  });

  // Config fields (THE LAW)
  const [excludeDirs, setExcludeDirs] = useConfigField<string[]>(
    'chunk_summaries.exclude_dirs',
    []
  );
  const [excludePatterns, setExcludePatterns] = useConfigField<string[]>(
    'chunk_summaries.exclude_patterns',
    []
  );
  const [excludeKeywords, setExcludeKeywords] = useConfigField<string[]>(
    'chunk_summaries.exclude_keywords',
    []
  );
  const [chunkSummariesMax, setChunkSummariesMax] = useConfigField<number>(
    'enrichment.chunk_summaries_max',
    100
  );
  const [chunkSummariesEnrichDefault, setChunkSummariesEnrichDefault] = useConfigField<number>(
    'enrichment.chunk_summaries_enrich_default',
    1
  );

  const [keywordsMaxPerCorpus, setKeywordsMaxPerCorpus] = useConfigField<number>(
    'keywords.keywords_max_per_repo',
    50
  );
  const [keywordsMinFreq, setKeywordsMinFreq] = useConfigField<number>(
    'keywords.keywords_min_freq',
    3
  );
  const [keywordsBoost, setKeywordsBoost] = useConfigField<number>('keywords.keywords_boost', 1.3);
  const [keywordsAutoGenerate, setKeywordsAutoGenerate] = useConfigField<number>(
    'keywords.keywords_auto_generate',
    1
  );
  const [keywordsRefreshHours, setKeywordsRefreshHours] = useConfigField<number>(
    'keywords.keywords_refresh_hours',
    24
  );

  // Local draft textareas for list fields (avoid PATCH spam while typing)
  const [excludeDirsDraft, setExcludeDirsDraft] = useState('');
  const [excludePatternsDraft, setExcludePatternsDraft] = useState('');
  const [excludeKeywordsDraft, setExcludeKeywordsDraft] = useState('');

  useEffect(() => {
    setExcludeDirsDraft((excludeDirs || []).join('\n'));
  }, [excludeDirs]);
  useEffect(() => {
    setExcludePatternsDraft((excludePatterns || []).join('\n'));
  }, [excludePatterns]);
  useEffect(() => {
    setExcludeKeywordsDraft((excludeKeywords || []).join('\n'));
  }, [excludeKeywords]);

  // Data
  const [chunkSummaries, setChunkSummaries] = useState<ChunkSummary[]>([]);
  const [lastBuild, setLastBuild] = useState<ChunkSummariesLastBuild | null>(null);
  const [keywords, setKeywords] = useState<string[]>([]);

  // UI state
  const [loadingSummaries, setLoadingSummaries] = useState(false);
  const [buildingSummaries, setBuildingSummaries] = useState(false);
  const [generatingKeywords, setGeneratingKeywords] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  // Persist corpus selection + broadcast (keeps config store and other tabs in sync)
  useEffect(() => {
    const next = corpusId.trim();
    if (!next) return;
    localStorage.setItem('tribrid_active_corpus', next);
    // Legacy key (kept for any older code paths)
    localStorage.setItem('tribrid_active_repo', next);
    try {
      const url = new URL(window.location.href);
      url.searchParams.set('corpus', next);
      url.searchParams.delete('repo');
      window.history.replaceState({}, '', url.toString());
    } catch {
      // ignore
    }
    window.dispatchEvent(new CustomEvent('tribrid-corpus-changed', { detail: { corpus: next, repo: next } }));
    // Legacy event name (kept for any older listeners)
    window.dispatchEvent(new CustomEvent('agro-repo-changed', { detail: { repo: next } }));
  }, [corpusId]);

  const filteredSummaries = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return chunkSummaries;
    return chunkSummaries.filter((s) => {
      const hay = [
        s.file_path,
        s.purpose ?? '',
        (s.symbols || []).join(' '),
        s.technical_details ?? '',
        (s.domain_concepts || []).join(' '),
      ]
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [chunkSummaries, search]);

  const loadSummaries = useCallback(async () => {
    if (!corpusId.trim()) return;
    setLoadingSummaries(true);
    setError(null);
    try {
      const res = await fetch(`/api/chunk_summaries?corpus_id=${encodeURIComponent(corpusId.trim())}`);
      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new Error(detail || `Failed to load chunk summaries (${res.status})`);
      }
      const data: ChunkSummariesResponse = await res.json();
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setLastBuild(data.last_build ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chunk summaries');
    } finally {
      setLoadingSummaries(false);
    }
  }, [corpusId]);

  const buildSummaries = useCallback(async () => {
    if (!corpusId.trim()) return;
    setBuildingSummaries(true);
    setError(null);
    try {
      const body: ChunkSummariesBuildRequest = {
        corpus_id: corpusId.trim(),
      };
      const res = await fetch('/api/chunk_summaries/build', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new Error(detail || `Build failed (${res.status})`);
      }
      const data: ChunkSummariesResponse = await res.json();
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setLastBuild(data.last_build ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed');
    } finally {
      setBuildingSummaries(false);
    }
  }, [corpusId]);

  const deleteSummary = useCallback(
    async (chunkId: string) => {
      if (!corpusId.trim()) return;
      setError(null);
      try {
        const res = await fetch(
          `/api/chunk_summaries/${encodeURIComponent(chunkId)}?corpus_id=${encodeURIComponent(
            corpusId.trim()
          )}`,
          { method: 'DELETE' }
        );
        if (!res.ok) {
          const detail = await res.text().catch(() => '');
          throw new Error(detail || `Delete failed (${res.status})`);
        }
        setChunkSummaries((prev) => prev.filter((s) => s.chunk_id !== chunkId));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Delete failed');
      }
    },
    [corpusId]
  );

  const generateKeywords = useCallback(async () => {
    if (!corpusId.trim()) return;
    setGeneratingKeywords(true);
    setError(null);
    try {
      const body: KeywordsGenerateRequest = { corpus_id: corpusId.trim() };
      const res = await fetch('/api/keywords/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const detail = await res.text().catch(() => '');
        throw new Error(detail || `Keyword generation failed (${res.status})`);
      }
      const data: KeywordsGenerateResponse = await res.json();
      setKeywords(Array.isArray(data.keywords) ? data.keywords : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Keyword generation failed');
    } finally {
      setGeneratingKeywords(false);
    }
  }, [corpusId]);

  const applyFilters = useCallback(() => {
    setExcludeDirs(parseList(excludeDirsDraft));
    setExcludePatterns(parseList(excludePatternsDraft));
    setExcludeKeywords(parseList(excludeKeywordsDraft));
  }, [excludeDirsDraft, excludePatternsDraft, excludeKeywordsDraft, setExcludeDirs, setExcludeKeywords, setExcludePatterns]);

  return (
    <div className="subtab-panel" style={{ padding: '24px' }}>
      <div style={{ marginBottom: 18 }}>
        <h3 style={{ fontSize: 18, fontWeight: 600, color: 'var(--fg)', marginBottom: 6 }}>
          🧪 Data Quality
        </h3>
        <div style={{ fontSize: 13, color: 'var(--fg-muted)' }}>
          Build and review <strong>chunk summaries</strong> and <strong>keywords</strong> for a corpus.
        </div>
      </div>

      {error && (
        <div
          style={{
            padding: '10px 12px',
            borderRadius: 8,
            border: '1px solid var(--err)',
            background: 'rgba(var(--err-rgb), 0.08)',
            color: 'var(--fg)',
            marginBottom: 16,
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Corpus</div>
        <div className="input-row">
          <div className="input-group">
            <label>Corpus ID</label>
            <input value={corpusId} onChange={(e) => setCorpusId(e.target.value)} placeholder="tribrid" />
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 6 }}>
              Use the same ID you used for Indexing.
            </div>
          </div>
          <div className="input-group" />
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="small-button" onClick={() => void loadSummaries()} disabled={!corpusId.trim() || loadingSummaries}>
            {loadingSummaries ? 'Loading…' : 'Refresh chunk summaries'}
          </button>
          <button className="small-button" onClick={() => void generateKeywords()} disabled={!corpusId.trim() || generatingKeywords}>
            {generatingKeywords ? 'Generating…' : 'Generate keywords'}
          </button>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Chunk summaries configuration</div>
        <div className="input-row">
          <div className="input-group">
            <label>Max chunk summaries</label>
            <input
              type="number"
              min={10}
              max={1000}
              value={chunkSummariesMax}
              onChange={(e) => setChunkSummariesMax(parseInt(e.target.value || '100', 10))}
            />
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={chunkSummariesEnrichDefault !== 0}
                onChange={(e) => setChunkSummariesEnrichDefault(e.target.checked ? 1 : 0)}
              />{' '}
              Enrich by default
            </label>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Exclude directories (one per line)</label>
            <textarea
              rows={6}
              value={excludeDirsDraft}
              onChange={(e) => setExcludeDirsDraft(e.target.value)}
              placeholder="node_modules\nvenv\ndist"
            />
          </div>
          <div className="input-group">
            <label>Exclude patterns (one per line)</label>
            <textarea
              rows={6}
              value={excludePatternsDraft}
              onChange={(e) => setExcludePatternsDraft(e.target.value)}
              placeholder="*.min.js\n*.lock\n**/*.test.ts"
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>Exclude keywords (one per line)</label>
            <textarea
              rows={4}
              value={excludeKeywordsDraft}
              onChange={(e) => setExcludeKeywordsDraft(e.target.value)}
              placeholder="deprecated\nlegacy\nTODO"
            />
          </div>
          <div className="input-group" />
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="small-button" onClick={applyFilters}>
            Save filters
          </button>
          <button className="small-button" onClick={() => void buildSummaries()} disabled={!corpusId.trim() || buildingSummaries}>
            {buildingSummaries ? 'Building…' : 'Build chunk summaries'}
          </button>
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
          marginBottom: 18,
        }}
      >
        <div style={{ fontWeight: 600, marginBottom: 10 }}>Keywords configuration</div>
        <div className="input-row">
          <div className="input-group">
            <label>Max keywords per corpus</label>
            <input
              type="number"
              min={10}
              max={500}
              value={keywordsMaxPerCorpus}
              onChange={(e) => setKeywordsMaxPerCorpus(parseInt(e.target.value || '50', 10))}
            />
          </div>
          <div className="input-group">
            <label>Min frequency</label>
            <input
              type="number"
              min={1}
              max={10}
              value={keywordsMinFreq}
              onChange={(e) => setKeywordsMinFreq(parseInt(e.target.value || '3', 10))}
            />
          </div>
          <div className="input-group">
            <label>Boost</label>
            <input
              type="number"
              min={1.0}
              max={3.0}
              step={0.1}
              value={keywordsBoost}
              onChange={(e) => setKeywordsBoost(parseFloat(e.target.value || '1.3'))}
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label>Auto-generate</label>
            <select value={keywordsAutoGenerate} onChange={(e) => setKeywordsAutoGenerate(parseInt(e.target.value, 10))}>
              <option value={1}>Enabled</option>
              <option value={0}>Disabled</option>
            </select>
          </div>
          <div className="input-group">
            <label>Refresh hours</label>
            <input
              type="number"
              min={1}
              max={168}
              value={keywordsRefreshHours}
              onChange={(e) => setKeywordsRefreshHours(parseInt(e.target.value || '24', 10))}
            />
          </div>
          <div className="input-group" />
        </div>
      </div>

      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: 10,
          padding: 14,
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center', marginBottom: 10 }}>
          <div>
            <div style={{ fontWeight: 600 }}>Chunk summaries</div>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
              {lastBuild
                ? `Last build: ${
                    lastBuild.timestamp ? new Date(lastBuild.timestamp).toLocaleString() : '—'
                  } • ${lastBuild.total} summaries`
                : 'No builds yet.'}
            </div>
          </div>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search summaries…"
            style={{
              minWidth: 260,
              padding: '8px 10px',
              borderRadius: 8,
              border: '1px solid var(--line)',
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
            }}
          />
        </div>

        {filteredSummaries.length === 0 ? (
          <div style={{ fontSize: 12, color: 'var(--fg-muted)' }}>No chunk summaries to show.</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 12 }}>
            {filteredSummaries.map((s) => (
              <div
                key={s.chunk_id}
                style={{
                  background: 'var(--bg-elev2)',
                  border: '1px solid var(--line)',
                  borderRadius: 10,
                  padding: 12,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 8,
                }}
              >
                <div style={{ fontSize: 12, color: 'var(--link)', wordBreak: 'break-all' }}>
                  {s.file_path}:{s.start_line}
                </div>
                <div style={{ fontSize: 13, color: 'var(--fg)' }}>{s.purpose || '—'}</div>
                {s.symbols && s.symbols.length > 0 && (
                  <div style={{ fontSize: 11, color: 'var(--fg-muted)', fontFamily: 'monospace' }}>
                    {s.symbols.join(', ')}
                  </div>
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button className="small-button" onClick={() => void deleteSummary(s.chunk_id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {keywords.length > 0 && (
          <div style={{ marginTop: 18 }}>
            <div style={{ fontWeight: 600, marginBottom: 8 }}>Latest keywords ({keywords.length})</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {keywords.slice(0, 50).map((k) => (
                <span
                  key={k}
                  style={{
                    fontSize: 11,
                    padding: '4px 8px',
                    borderRadius: 999,
                    background: 'var(--bg-elev2)',
                    border: '1px solid var(--line)',
                    color: 'var(--fg-muted)',
                    fontFamily: 'monospace',
                  }}
                >
                  {k}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
