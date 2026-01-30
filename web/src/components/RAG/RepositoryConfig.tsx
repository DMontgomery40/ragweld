// AGRO - Repository Configuration Component
// Refactored to use Zustand stores per CLAUDE.md requirements
// Uses useRepoStore for repo list/selection, useConfigStore.updateRepo() for persistence

import { useState, useEffect, useCallback, useRef } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';
import { useConfigStore } from '@/stores/useConfigStore';
import { KeywordManager } from '@/components/KeywordManager';

interface RepositoryConfigProps {
  // Only keep the callback that parent needs for syncing UI state
  onExcludePathsChange?: (paths: string[]) => void;
}

/**
 * ---agentspec
 * what: |
 *   Repository config using Zustand stores. Gets repos/activeRepo from useRepoStore,
 *   persists changes via useConfigStore.updateRepo(). Local state ONLY for debounced text inputs.
 *
 * why: |
 *   Single source of truth via Zustand; no duplicate state, fetch logic, or event listeners.
 *
 * guardrails:
 *   - DO NOT use local useState for config values - derive from store
 *   - NOTE: Local state ONLY for text input fields that need debouncing before save
 *   - DO NOT duplicate API calls - use store actions exclusively
 * ---/agentspec
 */
export function RepositoryConfig({ onExcludePathsChange }: RepositoryConfigProps) {
  // Get repos and active repo from Zustand store
  const { repos, activeRepo, loading: reposLoading, getRepoByName, loadRepos, initialized } = useRepoStore();
  const { updateRepo, saving } = useConfigStore();
  
  // Get current repo data from store (reactive to store changes)
  const repoData = getRepoByName(activeRepo);
  
  // Local state ONLY for text inputs that need debouncing before save
  const [repoPathInput, setRepoPathInput] = useState('');
  const [excludePathInput, setExcludePathInput] = useState('');
  const [keywordsInput, setKeywordsInput] = useState('');
  const [pathBoostsInput, setPathBoostsInput] = useState('');
  const [layerBonusesInput, setLayerBonusesInput] = useState('');
  
  // Ref to track if we're initializing from store (prevent save on mount)
  const isInitializing = useRef(true);

  // Load repos once on mount if not yet initialized
  useEffect(() => {
    if (!initialized && !reposLoading) {
      loadRepos();
    }
  }, [initialized, reposLoading, loadRepos]);

  // Sync local inputs from store when repo changes
  useEffect(() => {
    if (!repoData) return;
    isInitializing.current = true;
    
    setRepoPathInput(repoData.path || '');
    setKeywordsInput((repoData.keywords || []).join(', '));
    setPathBoostsInput((repoData.path_boosts || []).join(', '));
    setLayerBonusesInput(
      repoData.layer_bonuses ? JSON.stringify(repoData.layer_bonuses, null, 2) : ''
    );
    
    // Allow saves after initial sync
    setTimeout(() => { isInitializing.current = false; }, 100);
  }, [repoData?.name]); // Only re-sync when repo changes

  // NOTE: Path auto-save removed to prevent overwriting relative paths with absolute paths.
  // Path changes now require explicit save. See: Pydantic migration for repos.json

  /**
   * ---agentspec
   * what: |
   *   Debounced save for keywords. Parses comma-separated, sorts, compares to store.
   *
   * why: |
   *   Sort + compare prevents redundant saves for reordered input.
   *
   * guardrails:
   *   - DO NOT save if keywords unchanged after normalization
   * ---/agentspec
   */
  useEffect(() => {
    if (!repoData || isInitializing.current) return;
    
    const timeoutId = setTimeout(() => {
      const keywordsArray = keywordsInput.split(',').map(s => s.trim()).filter(Boolean);
      const currentKeywords = (repoData.keywords || []).sort().join(',');
      const newKeywords = keywordsArray.sort().join(',');
      if (currentKeywords !== newKeywords) {
        updateRepo(activeRepo, { keywords: keywordsArray });
      }
    }, 1000);
    return () => clearTimeout(timeoutId);
  }, [keywordsInput, repoData, activeRepo, updateRepo]);

  /**
   * ---agentspec
   * what: |
   *   Debounced save for path_boosts. Parses comma-separated, sorts, compares to store.
   *
   * why: |
   *   Sort + compare prevents redundant saves for reordered input.
   *
   * guardrails:
   *   - DO NOT save if boosts unchanged after normalization
   * ---/agentspec
   */
  useEffect(() => {
    if (!repoData || isInitializing.current) return;
    
    const timeoutId = setTimeout(() => {
      const pathBoostsArray = pathBoostsInput.split(',').map(s => s.trim()).filter(Boolean);
      const currentBoosts = (repoData.path_boosts || []).sort().join(',');
      const newBoosts = pathBoostsArray.sort().join(',');
      if (currentBoosts !== newBoosts) {
        updateRepo(activeRepo, { path_boosts: pathBoostsArray });
      }
    }, 1000);
    return () => clearTimeout(timeoutId);
  }, [pathBoostsInput, repoData, activeRepo, updateRepo]);

  /**
   * ---agentspec
   * what: |
   *   Debounced save for layer_bonuses JSON. Parses, validates, compares stringified.
   *
   * why: |
   *   JSON parse validation prevents saving invalid data; stringify compare catches changes.
   *
   * guardrails:
   *   - DO NOT save if JSON parse fails (silent skip)
   *   - NOTE: Order-dependent equality check via stringify
   * ---/agentspec
   */
  useEffect(() => {
    if (!repoData || isInitializing.current) return;
    
    const timeoutId = setTimeout(() => {
      try {
        const parsed = JSON.parse(layerBonusesInput || '{}');
        if (typeof parsed === 'object' && parsed !== null) {
          const currentBonuses = JSON.stringify(repoData.layer_bonuses || {});
          const newBonuses = JSON.stringify(parsed);
          if (currentBonuses !== newBonuses) {
            updateRepo(activeRepo, { layer_bonuses: parsed });
          }
        }
      } catch {
        // Invalid JSON, don't save yet
      }
    }, 1000);
    return () => clearTimeout(timeoutId);
  }, [layerBonusesInput, repoData, activeRepo, updateRepo]);

  // Exclude paths - derive from store, save via store
  const excludePaths = repoData?.exclude_paths || [];

  /**
   * ---agentspec
   * what: |
   *   Adds exclude path to repo config via store. Clears input, calls parent callback.
   *
   * why: |
   *   Centralized save through Zustand store; callback notifies parent for UI sync.
   *
   * guardrails:
   *   - DO NOT add empty strings; trim + validate before save
   * ---/agentspec
   */
  const handleAddExcludePath = useCallback(() => {
    if (!excludePathInput.trim() || !activeRepo) return;
    const newPaths = [...excludePaths, excludePathInput.trim()];
    setExcludePathInput('');
    updateRepo(activeRepo, { exclude_paths: newPaths });
    onExcludePathsChange?.(newPaths);
  }, [excludePathInput, excludePaths, activeRepo, updateRepo, onExcludePathsChange]);

  /**
   * ---agentspec
   * what: |
   *   Removes exclude path from repo config via store. Calls parent callback.
   *
   * why: |
   *   Centralized save through Zustand store; callback notifies parent for UI sync.
   *
   * guardrails:
   *   - DO NOT mutate excludePaths directly; use filter to create new array
   * ---/agentspec
   */
  const handleRemoveExcludePath = useCallback((path: string) => {
    const newPaths = excludePaths.filter(p => p !== path);
    updateRepo(activeRepo, { exclude_paths: newPaths });
    onExcludePathsChange?.(newPaths);
  }, [excludePaths, activeRepo, updateRepo, onExcludePathsChange]);

  if (reposLoading) {
    return (
      <div style={{ padding: '16px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Loading repository configuration...
      </div>
    );
  }

  if (!activeRepo || !repoData) {
    return (
      <div style={{ padding: '16px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Select a repository to configure
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--card-bg)', border: '1px solid var(--line)', borderRadius: '6px', padding: '16px', marginBottom: '16px' }}>
      <h4 style={{ color: 'var(--accent)', fontSize: '14px', marginBottom: '12px' }}>Repo: {repoData.name}</h4>

      {/* Path */}
      <div className="input-group" style={{ marginBottom: '12px' }}>
        <label>Path</label>
        <input
          type="text"
          value={repoPathInput}
          onChange={(e) => setRepoPathInput(e.target.value)}
        />
      </div>

      {/* Exclude Paths */}
      <div className="input-group" style={{ marginBottom: '12px' }}>
        <label>Exclude Paths (paths/patterns to skip during indexing)</label>
        <div
          id={`exclude-paths-container-${repoData.name}`}
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: '6px',
            marginBottom: '8px',
            minHeight: '32px',
            padding: '8px',
            background: 'var(--bg-elev2)',
            border: '1px solid var(--line)',
            borderRadius: '4px'
          }}
        >
          {excludePaths.map((path, idx) => (
            <span
              key={idx}
              style={{
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                padding: '4px 8px',
                borderRadius: '4px',
                fontSize: '12px',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
            >
              {path}
              <button
                type="button"
                onClick={() => handleRemoveExcludePath(path)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--accent-contrast)',
                  cursor: 'pointer',
                  padding: 0,
                  fontSize: '14px',
                  lineHeight: 1
                }}
              >
                ×
              </button>
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          <input
            type="text"
            id={`exclude-path-input-${repoData.name}`}
            placeholder="e.g., /website, *.pyc, /node_modules"
            value={excludePathInput}
            onChange={(e) => setExcludePathInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleAddExcludePath();
              }
            }}
            style={{ flex: 1 }}
          />
          <button
            type="button"
            className="small-button"
            id={`exclude-path-add-${repoData.name}`}
            onClick={handleAddExcludePath}
            style={{ background: 'var(--accent)', color: 'var(--accent-contrast)', padding: '6px 12px' }}
          >
            Add
          </button>
        </div>
      </div>

      {/* Keywords */}
      <div className="input-group" style={{ marginBottom: '12px' }}>
        <label>Keywords (comma-separated)</label>
        <input
          type="text"
          value={keywordsInput}
          onChange={(e) => setKeywordsInput(e.target.value)}
          list="keywords-list"
          placeholder="search or type to add"
        />
      </div>

      {/* Path Boosts */}
      <div className="input-group" style={{ marginBottom: '12px' }}>
        <label>Path Boosts (comma-separated)</label>
        <input
          type="text"
          value={pathBoostsInput}
          onChange={(e) => setPathBoostsInput(e.target.value)}
        />
      </div>

      {/* Layer Bonuses */}
      <div className="input-group">
        <label>Layer Bonuses (JSON)</label>
        <textarea
          value={layerBonusesInput}
          onChange={(e) => setLayerBonusesInput(e.target.value)}
          rows={3}
        />
      </div>

      {/* Keyword Manager */}
      <div className="input-group full-width" style={{ marginTop: '12px' }}>
        <KeywordManager
          repo={{
            name: repoData.name,
            path: repoData.path || '',
            keywords: repoData.keywords || [],
            path_boosts: repoData.path_boosts || [],
            layer_bonuses: repoData.layer_bonuses || {}
          }}
        />
      </div>

      {saving && (
        <div
          style={{
            padding: '8px',
            background: 'var(--card-bg)',
            border: '1px solid var(--accent)',
            borderRadius: '4px',
            fontSize: '12px',
            color: 'var(--accent)',
            marginTop: '8px'
          }}
        >
          Saving to repos.json...
        </div>
      )}
    </div>
  );
}
