/**
 * RepoSelector - Repository dropdown using useRepoStore
 *
 * Single source of truth for repository selection.
 * Uses centralized useRepoStore instead of local state.
 */

import { useEffect } from 'react';
import { useRepoStore, useRepos, useActiveRepo, useRepoLoading, useRepoInitialized } from '@/stores';
import { TooltipIcon } from '@/components/ui/TooltipIcon';

type RepoSelectorProps = {
  /** Tooltip key from tooltips.js */
  tooltipKey?: string;
  /** Label text */
  label?: string;
  /** Show loading indicator */
  showLoading?: boolean;
  /** Disabled state */
  disabled?: boolean;
  /** Callback when repo changes (in addition to store update) */
  onRepoChange?: (repo: string) => void;
};

export function RepoSelector({
  tooltipKey = 'REPO',
  label = 'Corpus',
  showLoading = true,
  disabled = false,
  onRepoChange,
}: RepoSelectorProps) {
  const repos = useRepos();
  const activeRepo = useActiveRepo();
  const isLoading = useRepoLoading();
  const initialized = useRepoInitialized();
  const { loadRepos, setActiveRepo, error } = useRepoStore();

  // Load repos on mount if not already loaded
  useEffect(() => {
    if (!initialized && !isLoading) {
      loadRepos();
    }
  }, [initialized, isLoading, loadRepos]);

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newRepo = e.target.value;
    await setActiveRepo(newRepo);
    onRepoChange?.(newRepo);
  };

  return (
    <div className="setting-row repo-selector">
      <label>
        {label}
        {tooltipKey && <TooltipIcon name={tooltipKey} />}
      </label>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <select
          value={activeRepo}
          onChange={handleChange}
          disabled={disabled || isLoading}
          style={{ minWidth: '180px' }}
        >
          {repos.length === 0 ? (
            <option value="">No corpora</option>
          ) : (
            repos.map(repo => (
              <option key={repo.corpus_id} value={repo.corpus_id}>
                {repo.name}
                {repo.branch && ` (${repo.branch})`}
              </option>
            ))
          )}
        </select>

        {showLoading && isLoading && (
          <span
            style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              animation: 'pulse 1s ease-in-out infinite',
            }}
          >
            {initialized ? 'Switching...' : 'Loading...'}
          </span>
        )}
      </div>

      {error && (
        <div
          style={{
            fontSize: '12px',
            color: 'var(--error)',
            marginTop: '4px',
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}

/**
 * Compact repo selector without label - for inline use
 */
export function RepoSelectorCompact({
  disabled = false,
  onRepoChange,
}: Pick<RepoSelectorProps, 'disabled' | 'onRepoChange'>) {
  const repos = useRepos();
  const activeRepo = useActiveRepo();
  const isLoading = useRepoLoading();
  const initialized = useRepoInitialized();
  const { loadRepos, setActiveRepo } = useRepoStore();

  useEffect(() => {
    if (!initialized && !isLoading) {
      loadRepos();
    }
  }, [initialized, isLoading, loadRepos]);

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newRepo = e.target.value;
    await setActiveRepo(newRepo);
    onRepoChange?.(newRepo);
  };

  return (
    <select
      value={activeRepo}
      onChange={handleChange}
      disabled={disabled || isLoading}
      style={{
        padding: '6px 10px',
        fontSize: '13px',
        borderRadius: '6px',
        border: '1px solid var(--line)',
        background: 'var(--card-bg)',
        color: 'var(--fg)',
        cursor: disabled || isLoading ? 'not-allowed' : 'pointer',
      }}
    >
      {repos.map(repo => (
        <option key={repo.corpus_id} value={repo.corpus_id}>
          {repo.name}
        </option>
      ))}
    </select>
  );
}
