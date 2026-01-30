// AGRO - RAG Data Quality Subtab
// Complete 1:1 port from /gui/index.html (tab-rag-data-quality)
// Repository configuration and Code Cards Builder with 37 element IDs
// Fully wired to repos.json for all repository configuration

import { useState, useEffect, useCallback } from 'react';
import { useAPI, useConfigField } from '@/hooks';
import { useCards } from '@/hooks/useCards';
import { RepositoryConfig } from './RepositoryConfig';
import { useRepoStore } from '@/stores/useRepoStore';
import { CardsViewer } from './CardsViewer';
import { CardsBuilderPanel } from './CardsBuilderPanel';
import { LiveTerminal } from '@/components/ui/LiveTerminal';
import { PromptLink } from '@/components/ui/PromptLink';

type CardItem = {
  file_path: string;
  start_line?: number;
  purpose?: string;
  symbols?: string[];
  technical_details?: string;
  domain_concepts?: string[];
};

declare global {
  interface Window {
    Cards?: { load: () => Promise<void> | void };
    initCards?: () => void;
  }
}

/**
 * ---agentspec
 * what: |
 *   Renders data quality UI subtab. Maps centralized repo store to repo names; manages selectedRepo, excludeDirs, excludePatterns state.
 *
 * why: |
 *   Centralizes repo state via useRepoStore to avoid duplication across tabs.
 *
 * guardrails:
 *   - DO NOT fetch repos directly; use storeLoadRepos for consistency
 *   - NOTE: repos derived from storeRepos.map(r => r.name); sync state if store updates
 * ---/agentspec
 */
export function DataQualitySubtab() {
  const { api } = useAPI();

  // Use centralized repo store
  const { repos: storeRepos, activeRepo, loadRepos: storeLoadRepos, loading, error: repoError, initialized } = useRepoStore();

  // Use cards store for build state - NO LOCAL USESTATE
  const { buildInProgress, buildStage, progressRepo } = useCards();
  /**
   * ---agentspec
   * what: |
   *   React component managing repository indexing UI. Accepts repo selection, exclusion filters (dirs/patterns/keywords), card limit, enrichment toggle. Tracks build progress & stage.
   *
   * why: |
   *   Centralizes indexing config state to decouple UI from API calls and enable real-time progress feedback.
   *
   * guardrails:
   *   - DO NOT allow cardsMax < 10 or > Pydantic limit; validate before submit
   *   - NOTE: enrichEnabled defaults true; confirm user intent if toggled off
   *   - ASK USER: Clarify excludePatterns format (regex vs glob) before implementation
   * ---/agentspec
   */
  const repos = storeRepos.map(r => r.name);
  const [selectedRepo, setSelectedRepo] = useState('');

  // Config values via useConfigField (auto-sync with backend)
  const [excludeDirs, setExcludeDirs] = useConfigField<string>('CARDS_EXCLUDE_DIRS', '');
  const [excludePatterns, setExcludePatterns] = useConfigField<string>('CARDS_EXCLUDE_PATTERNS', '');
  const [excludeKeywords, setExcludeKeywords] = useConfigField<string>('CARDS_EXCLUDE_KEYWORDS', '');
  const [cardsMax, setCardsMax] = useConfigField<number>('CARDS_MAX', 100);
  const [enrichEnabled, setEnrichEnabled] = useConfigField<string>('CARDS_ENRICH', '1');

  // Keywords Manager config
  const [keywordsMaxPerRepo, setKeywordsMaxPerRepo] = useConfigField<number>('KEYWORDS_MAX_PER_REPO', 50);
  const [keywordsMinFreq, setKeywordsMinFreq] = useConfigField<number>('KEYWORDS_MIN_FREQ', 3);
  const [keywordsBoost, setKeywordsBoost] = useConfigField<number>('KEYWORDS_BOOST', 1.3);
  const [keywordsAutoGenerate, setKeywordsAutoGenerate] = useConfigField<number>('KEYWORDS_AUTO_GENERATE', 1);
  const [keywordsRefreshHours, setKeywordsRefreshHours] = useConfigField<number>('KEYWORDS_REFRESH_HOURS', 24);

  // Local UI state
  const [error, setError] = useState<string>('');

  // Keyword generation state
  const [keywordsGenerating, setKeywordsGenerating] = useState<boolean>(false);
  const [keywordsGenerateStatus, setKeywordsGenerateStatus] = useState<string>('');
  const [generatedKeywordsCount, setGeneratedKeywordsCount] = useState<number | null>(null);

  // Terminal state for build logs
  const [showTerminal, setShowTerminal] = useState<boolean>(false);
  const [terminalLines, setTerminalLines] = useState<string[]>([]);
  const [terminalProgress, setTerminalProgress] = useState<{ percent: number; message: string } | null>(null);

  // Load repos list via store (once if not initialized)
  useEffect(() => {
    if (!initialized && !loading) {
      storeLoadRepos();
    }
  }, [initialized, loading, storeLoadRepos]);

  // Show error if repo loading failed
  useEffect(() => {
    if (repoError) {
      console.error('[DataQualitySubtab] Failed to load repos:', repoError);
      // Optionally show error to user
    }
  }, [repoError]);

  // Sync selectedRepo with store's activeRepo or first repo when available
  useEffect(() => {
    if (repos.length > 0 && !selectedRepo) {
      const initialRepo = activeRepo || repos[0];
      console.log('[DataQualitySubtab] Setting selectedRepo to:', initialRepo);
      setSelectedRepo(initialRepo);
    }
  }, [repos, activeRepo, selectedRepo]);

  // Config loading is handled automatically by useConfigField hooks


  // Config updates are handled automatically by useConfigField setters

  /**
   * Generate keywords for the selected repository
   * Calls /api/keywords/generate endpoint
   */
  /**
   * ---agentspec
   * what: |
   *   Generates keywords for selected repository. Validates repo selection, sets loading state, updates UI with generation status.
   *
   * why: |
   *   Centralizes keyword generation trigger with validation and user feedback.
   *
   * guardrails:
   *   - DO NOT proceed without selectedRepo; return early with error message
   *   - NOTE: Sets three state vars (generating flag, status text, count reset) atomically
   * ---/agentspec
   */
  const handleGenerateKeywords = async () => {
    if (!selectedRepo) {
      setError('Please select a repository first');
      return;
    }

    setKeywordsGenerating(true);
    setKeywordsGenerateStatus('Generating keywords...');
    setGeneratedKeywordsCount(null);
    setError('');

    try {
      const response = await fetch(api('keywords/generate'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo: selectedRepo })
      });

      const data = await response.json();

      if (response.ok && data.ok !== false) {
        const count = data.count || data.keywords?.length || 0;
        setGeneratedKeywordsCount(count);
        setKeywordsGenerateStatus(`✓ Generated ${count} keywords for ${selectedRepo}`);
        console.log(`[DataQualitySubtab] Generated ${count} keywords for ${selectedRepo}`);
      } else {
        const errorMsg = data.error || data.detail || 'Unknown error generating keywords';
        setKeywordsGenerateStatus(`✗ Error: ${errorMsg}`);
        setError(errorMsg);
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : 'Failed to generate keywords';
      setKeywordsGenerateStatus(`✗ Failed: ${errorMsg}`);
      setError(errorMsg);
      console.error('[DataQualitySubtab] Keyword generation error:', err);
    } finally {
      setKeywordsGenerating(false);
    }
  };

  return (
    <div id="tab-rag-data-quality" className="rag-subtab-content active">
      {/* Error Display */}
      {error && (
        <div
          style={{
            marginBottom: '16px',
            padding: '12px',
            background: 'rgba(255, 80, 80, 0.1)',
            border: '1px solid var(--err)',
            borderRadius: '6px',
            color: 'var(--err)',
            fontSize: '12px'
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Loading Panel */}
      <div
        id="data-quality-loading"
        className="loading-panel"
        role="status"
        aria-live="polite"
        style={{
          display: 'none',
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
          marginBottom: '16px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
          <span id="data-quality-loading-label" style={{ fontWeight: 600, color: 'var(--fg)' }}>
            Preparing Data Quality…
          </span>
          <span id="data-quality-loading-percent" className="mono" style={{ color: 'var(--accent)' }}>
            0%
          </span>
        </div>
        <div style={{ background: 'var(--bg-elev1)', height: '6px', borderRadius: '999px', overflow: 'hidden' }}>
          <div
            id="data-quality-loading-bar"
            style={{
              width: '0%',
              height: '100%',
              background: 'linear-gradient(90deg, var(--accent) 0%, var(--link) 100%)',
              transition: 'width 0.3s ease',
            }}
          ></div>
        </div>
        <div id="data-quality-loading-step" className="small" style={{ marginTop: '8px', color: 'var(--fg-muted)' }}>
          Initializing…
        </div>
      </div>

      {/* Repository Configuration */}
      <div className="settings-section">
        <h3>Repository Configuration</h3>
        <RepositoryConfig
          onExcludePathsChange={(paths) => {
            // Sync exclude_paths changes from RepositoryConfig to Cards Builder field
            setExcludeDirs(paths.join(', '));
          }}
        />
      </div>

      {/* Keywords Manager */}
      <div className="settings-section">
        <h3>
          <span className="accent-purple">●</span> Keywords Manager
        </h3>
        <p style={{ fontSize: '13px', color: 'var(--fg-muted)', marginBottom: '20px', lineHeight: '1.6' }}>
          Discriminative keywords extraction and boosting configuration. Keywords are automatically extracted from your codebase to improve search relevance.
        </p>

        <div className="input-row">
          <div className="input-group">
            <label>
              Max Keywords Per Repo
              <span className="help-icon" data-tooltip="KEYWORDS_MAX_PER_REPO">?</span>
            </label>
            <input
              type="number"
              id="KEYWORDS_MAX_PER_REPO"
              name="KEYWORDS_MAX_PER_REPO"
              value={keywordsMaxPerRepo}
              min="10"
              max="500"
              step="10"
              onChange={(e) => setKeywordsMaxPerRepo(parseInt(e.target.value, 10) || 50)}
            />
          </div>
          <div className="input-group">
            <label>
              Min Frequency
              <span className="help-icon" data-tooltip="KEYWORDS_MIN_FREQ">?</span>
            </label>
            <input
              type="number"
              id="KEYWORDS_MIN_FREQ"
              name="KEYWORDS_MIN_FREQ"
              value={keywordsMinFreq}
              min="1"
              max="10"
              step="1"
              onChange={(e) => setKeywordsMinFreq(parseInt(e.target.value, 10) || 3)}
            />
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Keywords Multiplicative Boost
              <span className="help-icon" data-tooltip="KEYWORDS_BOOST">?</span>
            </label>
            <input
              type="number"
              id="KEYWORDS_BOOST"
              name="KEYWORDS_BOOST"
              value={keywordsBoost}
              min="1.0"
              max="3.0"
              step="0.1"
              onChange={(e) => setKeywordsBoost(parseFloat(e.target.value) || 1.3)}
            />
          </div>
          <div className="input-group">
            <label>
              Auto-Generate Keywords
              <span className="help-icon" data-tooltip="KEYWORDS_AUTO_GENERATE">?</span>
            </label>
            <select
              id="KEYWORDS_AUTO_GENERATE"
              name="KEYWORDS_AUTO_GENERATE"
              value={keywordsAutoGenerate}
              onChange={(e) => setKeywordsAutoGenerate(parseInt(e.target.value, 10))}
            >
              <option value="1">Enabled</option>
              <option value="0">Disabled</option>
            </select>
          </div>
        </div>

        <div className="input-row">
          <div className="input-group">
            <label>
              Refresh Hours
              <span className="help-icon" data-tooltip="KEYWORDS_REFRESH_HOURS">?</span>
            </label>
            <input
              type="number"
              id="KEYWORDS_REFRESH_HOURS"
              name="KEYWORDS_REFRESH_HOURS"
              value={keywordsRefreshHours}
              min="1"
              max="168"
              step="1"
              onChange={(e) => setKeywordsRefreshHours(parseInt(e.target.value, 10) || 24)}
            />
          </div>
        </div>

        {/* Generate Keywords Button */}
        <div className="input-row" style={{ marginTop: '20px' }}>
          <div className="input-group">
            <button
              id="btn-generate-keywords"
              onClick={handleGenerateKeywords}
              disabled={keywordsGenerating || !selectedRepo}
              data-tooltip="GENERATE_KEYWORDS"
              title="Extract discriminative keywords from the indexed codebase using TF-IDF analysis"
              style={{
                width: '100%',
                background: keywordsGenerating ? 'var(--fg-muted)' : 'var(--link)',
                color: keywordsGenerating ? 'var(--bg)' : 'var(--on-link)',
                border: 'none',
                padding: '14px 24px',
                borderRadius: '8px',
                fontSize: '14px',
                fontWeight: 700,
                cursor: keywordsGenerating ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '10px',
                transition: 'all 0.2s ease'
              }}
            >
              <span style={{ fontSize: '18px' }}>⭐</span>
              {keywordsGenerating ? 'Generating...' : 'Generate Keywords'}
            </button>
          </div>
        </div>

        {/* Generation Status */}
        {keywordsGenerateStatus && (
          <div
            style={{
              marginTop: '12px',
              padding: '12px',
              background: keywordsGenerateStatus.includes('✓') ? 'rgba(0, 255, 136, 0.1)' : 
                         keywordsGenerateStatus.includes('✗') ? 'rgba(255, 80, 80, 0.1)' : 
                         'var(--card-bg)',
              border: `1px solid ${keywordsGenerateStatus.includes('✓') ? 'var(--ok)' : 
                                  keywordsGenerateStatus.includes('✗') ? 'var(--err)' : 
                                  'var(--line)'}`,
              borderRadius: '6px',
              fontSize: '13px',
              fontFamily: "'SF Mono', monospace",
              color: keywordsGenerateStatus.includes('✓') ? 'var(--ok)' : 
                     keywordsGenerateStatus.includes('✗') ? 'var(--err)' : 
                     'var(--fg-muted)'
            }}
          >
            {keywordsGenerateStatus}
          </div>
        )}
      </div>

      {/* Code Cards Builder & Viewer */}
      <div className="settings-section">
        <h3>
          <span className="accent-green">●</span> Code Cards Builder & Viewer
          <span className="help-icon" data-tooltip="CODE_CARDS">?</span>
        </h3>

        {/* Repository Selection */}
        <div className="input-row" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <label>Repository to Build Cards For</label>
            <select
              id="cards-repo-select"
              value={selectedRepo}
              onChange={(e) => setSelectedRepo(e.target.value)}
              style={{ width: '100%' }}
            >
              {repos.length === 0 && <option value="">Loading...</option>}
              {repos.map((repo) => (
                <option key={repo} value={repo}>
                  {repo}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Filters */}
        <div className="input-row" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <label>
              Exclude Directories (comma-separated)
              <span className="help-icon" data-tooltip="CARDS_EXCLUDE_DIRS">?</span>
            </label>
            <input
              type="text"
              id="cards-exclude-dirs"
              name="CARDS_EXCLUDE_DIRS"
              placeholder="e.g., node_modules, vendor, dist"
              value={excludeDirs}
              onChange={(e) => setExcludeDirs(e.target.value)}
              style={{ width: '100%' }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)' }}>
              Directories skipped during cards builds. Stored in agro_config.json (CARDS_EXCLUDE_DIRS).
            </p>
          </div>
        </div>

        <div className="input-row" style={{ marginBottom: '12px' }}>
          <div className="input-group">
            <label>
              Exclude Patterns (comma-separated)
              <span className="help-icon" data-tooltip="CARDS_EXCLUDE_PATTERNS">?</span>
            </label>
            <input
              type="text"
              id="cards-exclude-patterns"
              name="CARDS_EXCLUDE_PATTERNS"
              placeholder="e.g., .test.js, .spec.ts, .min.js"
              value={excludePatterns}
              onChange={(e) => setExcludePatterns(e.target.value)}
              style={{ width: '100%' }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)' }}>
              File patterns to skip (CARDS_EXCLUDE_PATTERNS).
            </p>
          </div>
        </div>

        <div className="input-row" style={{ marginBottom: '16px' }}>
          <div className="input-group">
            <label>
              Exclude Keywords (comma-separated)
              <span className="help-icon" data-tooltip="CARDS_EXCLUDE_KEYWORDS">?</span>
            </label>
            <input
              type="text"
              id="cards-exclude-keywords"
              name="CARDS_EXCLUDE_KEYWORDS"
              placeholder="e.g., deprecated, legacy, TODO"
              value={excludeKeywords}
              onChange={(e) => setExcludeKeywords(e.target.value)}
              style={{ width: '100%' }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)' }}>
              Skip chunks containing these keywords (CARDS_EXCLUDE_KEYWORDS).
            </p>
          </div>
        </div>

        {/* Options */}
        <div className="input-row" style={{ marginBottom: '16px', alignItems: 'flex-end' }}>
          <div className="input-group">
            <label>Cards Max</label>
            <input
              type="number"
              id="cards-max"
              name="CARDS_MAX"
              value={cardsMax}
              onChange={(e) => {
                const val = Number(e.target.value);
                // Enforce Pydantic constraint: ge=10
                setCardsMax(Math.max(10, val));
              }}
              min="10"
              step="10"
              style={{ maxWidth: '160px' }}
            />
            <p className="small" style={{ color: 'var(--fg-muted)' }}>
              Max chunks to process (min: 10, default: 100)
            </p>
          </div>
          <div className="input-group">
            <label>
              <input
                type="checkbox"
                id="cards-enrich-gui"
                name="CARDS_ENRICH"
                checked={enrichEnabled === '1'}
                onChange={(e) => setEnrichEnabled(e.target.checked ? '1' : '0')}
              />{' '}
              Enrich with AI
            </label>
            <p className="small" style={{ color: 'var(--fg-muted)' }}>
              Use LLM for rich semantic cards
            </p>
            {/* Quick links to edit card-related system prompts */}
            <div className="related-prompts" style={{ marginTop: '10px' }}>
              <span className="related-prompts-label">Edit:</span>
              <PromptLink promptKey="semantic_cards">Semantic Cards</PromptLink>
              <PromptLink promptKey="code_enrichment">Code Enrichment</PromptLink>
            </div>
          </div>
        </div>

        {/* Progress Container */}
        <div
          id="cards-progress-container"
          style={{
            display: buildInProgress ? 'block' : 'none',
            background: 'var(--card-bg)',
            border: '2px solid var(--accent)',
            borderRadius: '8px',
            padding: '16px',
            marginBottom: '16px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ fontWeight: 700, fontSize: '16px', color: 'var(--fg)' }}>⚡ Building Cards...</div>
            <div id="cards-progress-repo" style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent)' }}>
              {progressRepo}
            </div>
          </div>

          <div
            id="cards-progress-models"
            style={{
              fontFamily: "'SF Mono', monospace",
              fontSize: '11px',
              color: 'var(--fg-muted)',
              marginBottom: '8px',
              display: 'none',
            }}
          >
            Models — embed: <span data-model="embed">—</span> • enrich: <span data-model="enrich">—</span> • rerank:{' '}
            <span data-model="rerank">—</span>
          </div>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '12px', flexWrap: 'wrap' }}>
            <div id="cards-progress-stage-scan" className="cards-stage-pill">scan</div>
            <div id="cards-progress-stage-chunk" className="cards-stage-pill">chunk</div>
            <div id="cards-progress-stage-summarize" className="cards-stage-pill">summarize</div>
            <div id="cards-progress-stage-sparse" className="cards-stage-pill">sparse</div>
            <div id="cards-progress-stage-write" className="cards-stage-pill">write</div>
            <div id="cards-progress-stage-finalize" className="cards-stage-pill">finalize</div>
          </div>

          <div
            style={{
              background: 'var(--bg-elev1)',
              height: '8px',
              borderRadius: '999px',
              overflow: 'hidden',
              marginBottom: '10px',
            }}
          >
            <div
              id="cards-progress-bar"
              style={{
                width: '0%',
                height: '100%',
                background: 'linear-gradient(90deg, var(--accent) 0%, var(--link) 100%)',
                transition: 'width 0.3s ease',
              }}
            ></div>
          </div>

          <div id="cards-progress-stats" className="mono" style={{ fontSize: '11px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
            —
          </div>
          <div id="cards-progress-throughput" className="mono" style={{ fontSize: '10px', color: 'var(--fg-muted)', marginBottom: '4px' }}>
            —
          </div>
          <div id="cards-progress-eta" className="mono" style={{ fontSize: '10px', color: 'var(--fg-muted)', marginBottom: '8px' }}>
            —
          </div>
          <div id="cards-progress-tip" className="small" style={{ color: 'var(--link)', marginBottom: '8px' }}>
            💡 Tip: —
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button id="cards-progress-cancel" className="small-button" style={{ background: 'var(--err)', color: 'var(--on-err)' }}>
              Cancel Build
            </button>
            <button
              id="cards-progress-logs"
              className="small-button"
              onClick={() => {
                setShowTerminal(true);
                // Demo: add some test log lines
                setTerminalLines(prev => [
                  ...prev,
                  '\x1b[32m✓\x1b[0m Connected to build server',
                  'Scanning repository files...'
                ]);
                setTerminalProgress({ percent: 10, message: 'Scanning files...' });
              }}
            >
              View Logs
            </button>
            <button id="cards-progress-clear" className="small-button" onClick={() => {
              setTerminalLines([]);
              setTerminalProgress(null);
            }}>
              Clear
            </button>
          </div>
        </div>

        {/* Live Terminal for Build Logs */}
        <LiveTerminal
          title="Cards Build Logs"
          isVisible={showTerminal}
          onClose={() => setShowTerminal(false)}
          lines={terminalLines}
          progress={terminalProgress}
        />

        {/* Action Buttons */}
        <CardsBuilderPanel
          api={api}
          repos={repos}
          selectedRepo={selectedRepo}
          onSelectRepo={setSelectedRepo}
          excludeDirs={excludeDirs}
          onChangeExcludeDirs={setExcludeDirs}
          excludePatterns={excludePatterns}
          onChangeExcludePatterns={setExcludePatterns}
          excludeKeywords={excludeKeywords}
          onChangeExcludeKeywords={setExcludeKeywords}
          cardsMax={cardsMax}
          onChangeCardsMax={setCardsMax}
          enrichEnabled={enrichEnabled}
          onChangeEnrich={setEnrichEnabled}
          onError={setError}
        />

        <CardsViewer api={api} />
      </div>
    </div>
  );
}
