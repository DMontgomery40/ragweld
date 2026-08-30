import { useCallback, useEffect, useMemo, useState } from 'react';
import { useConfigField } from '@/hooks';
import { NumberField } from '@/components/ui/NumberField';
import type {
  ChunkSummariesBuildRequest,
  ChunkSummariesLastBuild,
  ChunkSummariesResponse,
  ChunkSummary,
  Corpus,
  KeywordsGenerateRequest,
  KeywordsGenerateResponse,
} from '@/types/generated';
import { useActiveRepo, useRepoStore } from '@/stores';
import { RepoSelectorCompact } from '@/components/RAG/RepoSelector';
import { SyntheticCallout } from '@/components/RAG/SyntheticCallout';
import { TooltipIcon } from '@/components/ui/TooltipIcon';
import { chunkSummariesApi, corporaApi, keywordsApi } from '@/api';

function parseList(text: string): string[] {
  return text
    .split(/[\n,]/g)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function DataQualitySubtab() {
  const activeRepo = useActiveRepo();
  const loadRepos = useRepoStore((state) => state.loadRepos);

  // Validated public config fields
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
  const [chunkSummariesEnrichDefault, setChunkSummariesEnrichDefault] = useConfigField<boolean>(
    'enrichment.chunk_summaries_enrich_default',
    true
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
  const [keywordsAutoGenerate, setKeywordsAutoGenerate] = useConfigField<boolean>(
    'keywords.keywords_auto_generate',
    true
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
  const [keywordsLoaded, setKeywordsLoaded] = useState(false);
  const [summariesLoaded, setSummariesLoaded] = useState(false);

  // UI state
  const [loadingSummaries, setLoadingSummaries] = useState(false);
  const [buildingSummaries, setBuildingSummaries] = useState(false);
  const [generatingKeywords, setGeneratingKeywords] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

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
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    setLoadingSummaries(true);
    setError(null);
    try {
      const data: ChunkSummariesResponse = await chunkSummariesApi.list(rid);
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setSummariesLoaded(true);
      setLastBuild(data.last_build ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load chunk summaries');
    } finally {
      setLoadingSummaries(false);
    }
  }, [activeRepo]);

  const buildSummaries = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    setBuildingSummaries(true);
    setError(null);
    try {
      const body: ChunkSummariesBuildRequest = {
        corpus_id: rid,
      };
      const data: ChunkSummariesResponse = await chunkSummariesApi.build(body);
      setChunkSummaries(Array.isArray(data.chunk_summaries) ? data.chunk_summaries : []);
      setLastBuild(data.last_build ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Build failed');
    } finally {
      setBuildingSummaries(false);
    }
  }, [activeRepo]);

  const deleteSummary = useCallback(
    async (chunkId: string) => {
      const rid = String(activeRepo || '').trim();
      if (!rid) return;
      setError(null);
      try {
        await chunkSummariesApi.deleteOne({ corpusId: rid, chunkId });
        setChunkSummaries((prev) => prev.filter((s) => s.chunk_id !== chunkId));
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Delete failed');
      }
    },
    [activeRepo]
  );

  // The page showed "No builds yet / No chunk summaries to show" for every corpus, including
  // a fully indexed one, and the network log held no request matching `summar` or `keyword`:
  // nothing was ever fetched. Both panels load with the corpus now, and their empty states
  // say whether the answer is "none exist" or "not loaded yet".
  const loadKeywords = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) {
      setKeywords([]);
      setKeywordsLoaded(false);
      return;
    }
    try {
      const corpus: Corpus = await corporaApi.get(rid);
      setKeywords(Array.isArray(corpus.keywords) ? corpus.keywords : []);
      setKeywordsLoaded(true);
    } catch (e) {
      setKeywordsLoaded(false);
      setError(e instanceof Error ? e.message : 'Failed to load corpus keywords');
    }
  }, [activeRepo]);

  useEffect(() => {
    setChunkSummaries([]);
    setLastBuild(null);
    setSummariesLoaded(false);
    setKeywords([]);
    setKeywordsLoaded(false);
    void loadSummaries();
    void loadKeywords();
  }, [loadKeywords, loadSummaries]);

  // One corpus source of truth across subtabs: this tab and Indexing both ask the shared store
  // on entry, so neither can be showing a corpus list the other has already moved past. The
  // drive found a deleted test corpus still offered here and not there.
  useEffect(() => {
    void loadRepos();
  }, [loadRepos]);

  const generateKeywords = useCallback(async () => {
    const rid = String(activeRepo || '').trim();
    if (!rid) return;
    setGeneratingKeywords(true);
    setError(null);
    try {
      const body: KeywordsGenerateRequest = { corpus_id: rid };
      const data: KeywordsGenerateResponse = await keywordsApi.generate(body);
      setKeywords(Array.isArray(data.keywords) ? data.keywords : []);
      setKeywordsLoaded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Keyword generation failed');
    } finally {
      setGeneratingKeywords(false);
    }
  }, [activeRepo]);

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
          Build and review <strong>chunk summaries</strong>, and generate and review the{' '}
          <strong>corpus keywords</strong> that weight retrieval. Both are corpus-scoped and both
          need an indexed corpus.
        </div>
      </div>

      <SyntheticCallout context="data-quality" />

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
            <label>Corpus</label>
            <RepoSelectorCompact />
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginTop: 6 }}>
              Use the same ID you used for Indexing.
            </div>
          </div>
          <div className="input-group" />
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="small-button" onClick={() => void loadSummaries()} disabled={!String(activeRepo || '').trim() || loadingSummaries}>
            {loadingSummaries ? 'Loading…' : 'Refresh chunk summaries'}
          </button>
          <button className="small-button" onClick={() => void generateKeywords()} disabled={!String(activeRepo || '').trim() || generatingKeywords}>
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
            <label>
              Max chunk summaries
              <TooltipIcon name="CHUNK_SUMMARIES_MAX" />
            </label>
            <NumberField
              data-testid="data-quality-chunk-summaries-max"
              configPath="enrichment.chunk_summaries_max"
              min={10}
              max={1000}
              value={chunkSummariesMax}
              onCommit={setChunkSummariesMax}
            />
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                checked={chunkSummariesEnrichDefault}
                onChange={(e) => setChunkSummariesEnrichDefault(e.target.checked)}
              />{' '}
              Enrich by default
              <TooltipIcon name="CHUNK_SUMMARIES_ENRICH_DEFAULT" />
            </label>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Exclude directories (one per line)
              <TooltipIcon name="CHUNK_SUMMARIES_EXCLUDE_DIRS" />
            </label>
            <textarea
              rows={6}
              value={excludeDirsDraft}
              onChange={(e) => setExcludeDirsDraft(e.target.value)}
              placeholder={'node_modules\nvenv\ndist'}
            />
          </div>
          <div className="input-group">
            <label>
              Exclude patterns (one per line)
              <TooltipIcon name="CHUNK_SUMMARIES_EXCLUDE_PATTERNS" />
            </label>
            <textarea
              rows={6}
              value={excludePatternsDraft}
              onChange={(e) => setExcludePatternsDraft(e.target.value)}
              placeholder={'*.min.js\n*.lock\n**/*.test.ts'}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Exclude keywords (one per line)
              <TooltipIcon name="CHUNK_SUMMARIES_EXCLUDE_KEYWORDS" />
            </label>
            <textarea
              rows={4}
              value={excludeKeywordsDraft}
              onChange={(e) => setExcludeKeywordsDraft(e.target.value)}
              placeholder={'deprecated\nlegacy\nTODO'}
            />
          </div>
          <div className="input-group" />
        </div>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <button className="small-button" onClick={applyFilters}>
            Save filters
          </button>
          <button
            className="small-button"
            onClick={() => void buildSummaries()}
            disabled={!String(activeRepo || '').trim() || buildingSummaries}
          >
            {buildingSummaries ? 'Building…' : 'Build chunk summaries'}
          </button>
        </div>
        <div style={{ marginTop: 10, fontSize: 12, color: 'var(--fg-muted)' }}>
          Cost estimate placeholder: current chunk summary build is deterministic (no LLM billing). When LLM-based enrichment is added, an estimate will be shown before build.
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
            <label>
              Max keywords per corpus
              <TooltipIcon name="KEYWORDS_MAX_PER_REPO" />
            </label>
            <NumberField
              configPath="keywords.keywords_max_per_repo"
              min={10}
              max={500}
              value={keywordsMaxPerCorpus}
              onCommit={setKeywordsMaxPerCorpus}
            />
          </div>
          <div className="input-group">
            <label>
              Min frequency
              <TooltipIcon name="KEYWORDS_MIN_FREQ" />
            </label>
            <NumberField
              configPath="keywords.keywords_min_freq"
              min={1}
              max={10}
              value={keywordsMinFreq}
              onCommit={setKeywordsMinFreq}
            />
          </div>
          <div className="input-group">
            <label>
              Boost
              <TooltipIcon name="KEYWORDS_BOOST" />
            </label>
            <NumberField
              configPath="keywords.keywords_boost"
              min={1.0}
              max={3.0}
              step={0.1}
              value={keywordsBoost}
              onCommit={setKeywordsBoost}
            />
          </div>
        </div>
        <div className="input-row">
          <div className="input-group">
            <label className="toggle">
              <input
                type="checkbox"
                checked={keywordsAutoGenerate}
                onChange={(e) => setKeywordsAutoGenerate(e.target.checked)}
              />
              <span className="toggle-track" aria-hidden="true">
                <span className="toggle-thumb"></span>
              </span>
              <span className="toggle-label">
                Auto-generate <TooltipIcon name="KEYWORDS_AUTO_GENERATE" />
              </span>
            </label>
          </div>
          <div className="input-group">
            <label>
              Refresh hours
              <TooltipIcon name="KEYWORDS_REFRESH_HOURS" />
            </label>
            <NumberField
              configPath="keywords.keywords_refresh_hours"
              min={1}
              max={168}
              value={keywordsRefreshHours}
              onCommit={setKeywordsRefreshHours}
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
                : loadingSummaries
                  ? 'Loading…'
                  : summariesLoaded
                    ? 'No build has been run for this corpus yet.'
                    : 'Not loaded.'}
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
          <div data-testid="chunk-summaries-empty" style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
            {loadingSummaries
              ? 'Loading chunk summaries…'
              : !String(activeRepo || '').trim()
                ? 'Select a corpus to see its chunk summaries.'
                : !summariesLoaded
                  ? 'Chunk summaries could not be loaded — see the error above.'
                  : chunkSummaries.length > 0
                    ? `None of the ${chunkSummaries.length} chunk summaries match "${search}".`
                    : 'This corpus has no chunk summaries yet. They are built from indexed chunks: index the corpus, then use Build chunk summaries above.'}
          </div>
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

        <div data-testid="corpus-keywords-panel" style={{ marginTop: 18 }}>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>
            Corpus keywords {keywords.length > 0 ? `(${keywords.length})` : ''}
          </div>
          {keywords.length === 0 ? (
            <div data-testid="corpus-keywords-empty" style={{ fontSize: 12, color: 'var(--fg-muted)' }}>
              {!String(activeRepo || '').trim()
                ? 'Select a corpus to see its keywords.'
                : !keywordsLoaded
                  ? 'Keywords could not be loaded — see the error above.'
                  : 'This corpus has no stored keywords. They are counted from indexed chunks: index the corpus, then use Generate keywords above.'}
            </div>
          ) : null}
        </div>

        {keywords.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div style={{ fontSize: 12, color: 'var(--fg-muted)', marginBottom: 8 }}>
              Showing the first {Math.min(50, keywords.length)} by frequency.
            </div>
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
