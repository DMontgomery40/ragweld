/**
 * AGRO - Reusable Repository Selector Component
 * 
 * A dropdown component for selecting repositories that integrates with useRepoStore.
 * Can be used in two modes:
 * - Global: Selection updates the active repo across the entire app
 * - Local: Selection only affects the local component (e.g., per-query override)
 */

import { useEffect } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';

type RepoSelectorProps = {
  id?: string;
  /** If true, selecting repo updates global active repo via store */
  global?: boolean;
  /** Override selected value (for local-only selection) */
  value?: string;
  /** Called when selection changes */
  onChange?: (repo: string) => void;
  /** Include "Auto-detect" option as first choice */
  showAutoDetect?: boolean;
  /** Custom styling */
  style?: React.CSSProperties;
  /** Disabled state */
  disabled?: boolean;
  /** Compact mode (smaller padding/font) */
  compact?: boolean;
  /** Tooltip content */
  'data-tooltip'?: string;
  /** Additional className */
  className?: string;
};

export function RepoSelector({
  id = 'repo-selector',
  global = false,
  value,
  onChange,
  showAutoDetect = false,
  style,
  disabled = false,
  compact = false,
  'data-tooltip': dataTooltip,
  className
}: RepoSelectorProps) {
  const { repos, activeRepo, loading, switching, loadRepos, setActiveRepo, initialized } = useRepoStore();

  // Load repos once on mount if not yet initialized
  useEffect(() => {
    if (!initialized && !loading) {
      loadRepos();
    }
  }, [initialized, loading, loadRepos]);
  
  // Determine selected value: explicit value prop > store activeRepo
  const selectedValue = value !== undefined ? value : activeRepo;
  
  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const newRepo = e.target.value;
    
    // If global mode and repo selected, update store
    if (global && newRepo) {
      await setActiveRepo(newRepo);
    }
    
    // Always call onChange if provided
    onChange?.(newRepo);
  };
  
  const baseStyle: React.CSSProperties = {
    background: 'var(--input-bg)',
    border: '1px solid var(--line)',
    color: 'var(--fg)',
    padding: compact ? '4px 8px' : '6px 12px',
    borderRadius: '4px',
    fontSize: compact ? '11px' : '12px',
    cursor: disabled || loading || switching ? 'not-allowed' : 'pointer',
    opacity: disabled || loading || switching ? 0.6 : 1,
    minWidth: '120px',
    ...style
  };
  
  return (
    <select
      id={id}
      value={selectedValue}
      onChange={handleChange}
      disabled={disabled || loading || switching}
      style={baseStyle}
      aria-label="Select repository"
      data-tooltip={dataTooltip}
      className={className}
    >
      {showAutoDetect && (
        <option value="">Auto-detect repo</option>
      )}
      
      {loading && repos.length === 0 ? (
        <option value="" disabled>Loading...</option>
      ) : repos.length === 0 ? (
        <option value="" disabled>No repos found</option>
      ) : (
        repos.map(repo => (
          <option key={repo.corpus_id} value={repo.corpus_id}>
            {repo.name}
            {repo.branch ? ` (${repo.branch})` : ''}
          </option>
        ))
      )}
    </select>
  );
}

export default RepoSelector;


