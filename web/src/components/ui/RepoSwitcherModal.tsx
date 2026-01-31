/**
 * AGRO - Repository Switcher Modal
 * 
 * A modal dialog for switching the active repository from the dashboard.
 * Shows all available repos with visual indication of the active one.
 * 
 * Used by QuickActions and other components that need a full-screen repo selector.
 */

import { useEffect, useState } from 'react';
import { useRepoStore } from '@/stores/useRepoStore';

type RepoSwitcherModalProps = {
  isOpen: boolean;
  onClose: () => void;
};

export function RepoSwitcherModal({ isOpen, onClose }: RepoSwitcherModalProps) {
  const { repos, activeRepo, switching, loading, loadRepos, setActiveRepo, addRepo, error, initialized } = useRepoStore();
  const [newName, setNewName] = useState('');
  const [newPath, setNewPath] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);

  // Load repos when modal opens (if not yet initialized)
  useEffect(() => {
    if (isOpen && !initialized && !loading) {
      loadRepos();
    }
  }, [isOpen, initialized, loading, loadRepos]);
  
  // Close on escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    
    if (isOpen) {
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }
  }, [isOpen, onClose]);
  
  const handleSelect = async (repoName: string) => {
    if (repoName === activeRepo) {
      onClose();
      return;
    }
    
    await setActiveRepo(repoName);
    onClose();
  };
  
  if (!isOpen) return null;

  const handleCreate = async () => {
    setCreateError(null);
    try {
      await addRepo({
        name: newName.trim(),
        path: newPath.trim(),
        description: newDescription.trim() || null,
      });
      setNewName('');
      setNewPath('');
      setNewDescription('');
      onClose();
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Failed to create corpus');
    }
  };
  
  return (
    <div 
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        backdropFilter: 'blur(2px)'
      }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-labelledby="repo-switcher-title"
    >
      <div 
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '24px',
          minWidth: '360px',
          maxWidth: '520px',
          maxHeight: '70vh',
          overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.3)'
        }}
        onClick={e => e.stopPropagation()}
      >
        <h3 
          id="repo-switcher-title"
          style={{ 
            color: 'var(--accent)', 
            marginBottom: '8px',
            fontSize: '18px',
            fontWeight: 600,
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <span style={{ fontSize: '20px' }}>📁</span>
          Select Corpus
        </h3>
        
        <p style={{ 
          color: 'var(--fg-muted)', 
          fontSize: '12px', 
          marginBottom: '16px',
          lineHeight: 1.5
        }}>
          Switch the active corpus. All queries, indexing, and evaluations will use the selected corpus.
        </p>
        
        {error && (
          <div style={{
            background: 'var(--error-bg, rgba(255,0,0,0.1))',
            border: '1px solid var(--error, #ff4444)',
            color: 'var(--error, #ff4444)',
            padding: '8px 12px',
            borderRadius: '4px',
            fontSize: '12px',
            marginBottom: '12px'
          }}>
            {error}
          </div>
        )}
        
        {loading && repos.length === 0 ? (
          <div style={{ 
            padding: '24px', 
            textAlign: 'center', 
            color: 'var(--fg-muted)' 
          }}>
            Loading corpora...
          </div>
        ) : repos.length === 0 ? (
          <div style={{ 
            padding: '24px', 
            textAlign: 'center', 
            color: 'var(--fg-muted)' 
          }}>
            No corpora configured yet. Create one below.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {repos.map(repo => {
              const isActive = repo.corpus_id === activeRepo || repo.slug === activeRepo || repo.name === activeRepo;
              
              return (
                <button
                  key={repo.corpus_id}
                  onClick={() => handleSelect(repo.corpus_id)}
                  disabled={switching}
                  style={{
                    background: isActive ? 'var(--accent)' : 'var(--bg-elev2)',
                    color: isActive ? 'var(--accent-contrast)' : 'var(--fg)',
                    border: `1px solid ${isActive ? 'var(--accent)' : 'var(--line)'}`,
                    padding: '14px 16px',
                    borderRadius: '8px',
                    cursor: switching ? 'not-allowed' : 'pointer',
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    textAlign: 'left',
                    fontSize: '14px',
                    opacity: switching ? 0.6 : 1,
                    transition: 'all 0.15s ease'
                  }}
                >
                  <div>
                    <div style={{ 
                      fontWeight: 600, 
                      fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
                      marginBottom: repo.path || repo.branch ? '4px' : 0
                    }}>
                      {repo.name}
                    </div>
                    {repo.path && (
                      <div style={{ 
                        fontSize: '11px', 
                        color: isActive ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                        opacity: 0.8,
                        fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace"
                      }}>
                        {repo.path}
                      </div>
                    )}
                    {repo.branch && (
                      <div style={{ 
                        fontSize: '10px', 
                        color: isActive ? 'var(--accent-contrast)' : 'var(--link)',
                        marginTop: '2px'
                      }}>
                        Branch: {repo.branch}
                      </div>
                    )}
                  </div>
                  {isActive && (
                    <span style={{ 
                      fontSize: '12px', 
                      fontWeight: 600,
                      background: 'rgba(255,255,255,0.2)',
                      padding: '4px 8px',
                      borderRadius: '4px'
                    }}>
                      ✓ ACTIVE
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}

        <div style={{ marginTop: '16px' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, marginBottom: '8px', color: 'var(--fg)' }}>
            Create corpus
          </div>
          {createError && (
            <div style={{
              background: 'var(--error-bg, rgba(255,0,0,0.1))',
              border: '1px solid var(--error, #ff4444)',
              color: 'var(--error, #ff4444)',
              padding: '8px 12px',
              borderRadius: '4px',
              fontSize: '12px',
              marginBottom: '10px'
            }}>
              {createError}
            </div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Corpus name (e.g. tribrid-rag)"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
            />
            <input
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              placeholder="/absolute/path/to/corpus"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
            />
            <input
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              placeholder="Description (optional)"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                fontSize: '13px',
              }}
            />
            <button
              onClick={handleCreate}
              disabled={switching || loading || !newName.trim() || !newPath.trim()}
              style={{
                padding: '10px 16px',
                background: 'var(--accent)',
                border: '1px solid var(--accent)',
                color: 'var(--accent-contrast)',
                borderRadius: '6px',
                cursor: switching || loading ? 'not-allowed' : 'pointer',
                fontSize: '13px',
                fontWeight: 600,
                opacity: switching || loading ? 0.6 : 1,
              }}
            >
              ➕ Create & Select
            </button>
          </div>
        </div>
        
        <div style={{ 
          display: 'flex', 
          gap: '8px', 
          marginTop: '20px',
          borderTop: '1px solid var(--line)',
          paddingTop: '16px'
        }}>
          <button
            onClick={onClose}
            disabled={switching}
            style={{
              flex: 1,
              padding: '10px',
              background: 'transparent',
              border: '1px solid var(--line)',
              color: 'var(--fg-muted)',
              borderRadius: '6px',
              cursor: switching ? 'not-allowed' : 'pointer',
              fontSize: '13px',
              fontWeight: 500
            }}
          >
            Cancel
          </button>
          <button
            onClick={() => loadRepos()}
            disabled={loading || switching}
            style={{
              padding: '10px 16px',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              borderRadius: '6px',
              cursor: loading || switching ? 'not-allowed' : 'pointer',
              fontSize: '13px',
              fontWeight: 500,
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            🔄 Refresh
          </button>
        </div>
      </div>
    </div>
  );
}

export default RepoSwitcherModal;
