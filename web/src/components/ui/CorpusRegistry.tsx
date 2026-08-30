/**
 * Corpus registry — the operator surface for listing, switching, creating and deleting corpora.
 *
 * Replaces RepoSwitcherModal, which rendered inline inside the route. `.tab-content` carries
 * `transform: translateZ(0)` (micro-interactions.css:836) and is also the route's scroll
 * container, so an inline `position: fixed` overlay anchors `inset: 0` to the scrolled content
 * box instead of the viewport and `.content` (`overflow: hidden`) clips the rest: the registry
 * opened off-screen and the product had no reachable corpus switch or delete at all
 * (M-163/X-18/A-34). It renders through a portal on `document.body`, the same way the
 * confirmDialog overlay that works on this page does.
 *
 * The delete confirmation names every store the backend actually clears, read off
 * `delete_repo` in `server/api/repos.py`: the Postgres rows (chunks, documents, chunk
 * summaries, the corpus's own config overrides, the registry row), every Qdrant generation
 * collection, the Neo4j graph, and the corpus's lineage records. Source files on disk are
 * never touched, which is the half an operator most needs to know before confirming.
 */

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import type { Corpus } from '@/types/generated';
import { useRepoStore } from '@/stores/useRepoStore';
import { useConfig } from '@/hooks';
import { confirmDialog } from '@/components/ui/confirmDialog';

type CorpusRegistryProps = {
  isOpen: boolean;
  onClose: () => void;
};

/** Exactly what `DELETE /api/corpora/{id}` removes, in the order the handler removes it. */
export function corpusDeleteConsequences(corpusId: string, corpusPath: string): string {
  return [
    `Delete corpus "${corpusId}" and everything indexed from it.`,
    '',
    'Removed:',
    '  - Postgres: chunk rows, document provenance, chunk summaries, this corpus’s config overrides, and the registry row',
    '  - Qdrant: every dense and sparse generation collection for this corpus',
    '  - Neo4j: this corpus’s graph',
    '  - Lineage: this corpus’s aliases and bundles',
    '',
    'Kept:',
    `  - The source files on disk (${corpusPath || 'no path recorded'}) are not touched.`,
    '',
    'A corpus held by a running index run is refused until that run stops.',
  ].join('\n');
}

function indexedLabel(corpus: Corpus): string {
  const at = String(corpus.last_indexed || '').trim();
  if (!at) return 'Never indexed';
  const parsed = new Date(at);
  if (Number.isNaN(parsed.getTime())) return `Indexed ${at}`;
  return `Indexed ${parsed.toLocaleString()}`;
}

const panelText = { fontSize: '14px', lineHeight: 1.5 } as const;
const labelText = { fontSize: '12px', lineHeight: 1.45 } as const;

function ErrorBanner({ message, testId }: { message: string; testId: string }) {
  return (
    <div
      data-testid={testId}
      role="alert"
      style={{
        background: 'var(--error-bg, rgba(229,72,77,0.12))',
        border: '1px solid var(--err, #e5484d)',
        color: 'var(--err, #e5484d)',
        padding: '10px 12px',
        borderRadius: '6px',
        marginBottom: '12px',
        ...panelText,
      }}
    >
      {message}
    </div>
  );
}

export function CorpusRegistry({ isOpen, onClose }: CorpusRegistryProps) {
  const {
    repos,
    activeRepo,
    switching,
    loading,
    loadRepos,
    setActiveRepo,
    addRepo,
    deleteCorpus,
    error,
    initialized,
  } = useRepoStore();
  const [newName, setNewName] = useState('');
  const [newPath, setNewPath] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Recall is written and re-created by the chat runtime itself, so it is listed but not
  // deletable here. Its id is config, not a constant hard-coded into the UI.
  const { config } = useConfig();
  const runtimeManagedId = String(config?.chat?.recall?.default_corpus_id || '').trim();

  useEffect(() => {
    if (isOpen && !initialized && !loading) {
      loadRepos();
    }
  }, [isOpen, initialized, loading, loadRepos]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const handleSelect = async (corpusId: string) => {
    if (corpusId === activeRepo) {
      onClose();
      return;
    }
    await setActiveRepo(corpusId);
    onClose();
  };

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

  const handleDelete = async (corpus: Corpus) => {
    setDeleteError(null);
    const corpusId = String(corpus.corpus_id || '').trim();
    if (!corpusId) return;
    const ok = await confirmDialog({
      title: `Delete corpus ${corpus.name}`,
      message: corpusDeleteConsequences(corpusId, String(corpus.path || '')),
      confirmLabel: 'Delete corpus',
      cancelLabel: 'Keep corpus',
      danger: true,
    });
    if (!ok) return;
    try {
      await deleteCorpus(corpusId);
    } catch (e) {
      setDeleteError(e instanceof Error ? e.message : 'Failed to delete corpus');
    }
  };

  const registry = (
    <div
      data-testid="corpus-registry"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 9000,
      }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="corpus-registry-title"
    >
      <div
        style={{
          background: 'var(--bg-elev1)',
          border: '1px solid var(--line)',
          borderRadius: '12px',
          padding: '24px',
          width: 'min(620px, calc(100vw - 48px))',
          maxHeight: 'min(80vh, 760px)',
          overflow: 'auto',
          boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
          color: 'var(--fg)',
        }}
      >
        <h3
          id="corpus-registry-title"
          style={{ color: 'var(--accent-text)', margin: '0 0 6px', fontSize: '18px', fontWeight: 600 }}
        >
          Corpus registry
        </h3>
        <p style={{ color: 'var(--fg-muted)', margin: '0 0 16px', ...panelText }}>
          Every corpus this deployment knows about. The active corpus is what queries, indexing
          and evaluation run against.
        </p>

        {error && <ErrorBanner message={error} testId="corpus-registry-error" />}
        {deleteError && <ErrorBanner message={deleteError} testId="corpus-registry-delete-error" />}

        {loading && repos.length === 0 ? (
          <div style={{ padding: '24px', textAlign: 'center', color: 'var(--fg-muted)', ...panelText }}>
            Loading corpora...
          </div>
        ) : repos.length === 0 ? (
          <div
            data-testid="corpus-registry-empty"
            style={{ padding: '24px', textAlign: 'center', color: 'var(--fg-muted)', ...panelText }}
          >
            No corpora registered yet. Create one below.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {repos.map((corpus) => {
              const corpusId = String(corpus.corpus_id || '');
              const isActive =
                corpusId === activeRepo || corpus.slug === activeRepo || corpus.name === activeRepo;
              const isInternal = Boolean(runtimeManagedId) && corpusId === runtimeManagedId;
              return (
                <div
                  key={corpusId}
                  data-testid={`corpus-row-${corpusId}`}
                  style={{ display: 'flex', gap: '8px', alignItems: 'stretch' }}
                >
                  <button
                    type="button"
                    onClick={() => void handleSelect(corpusId)}
                    disabled={switching}
                    data-testid={`corpus-select-${corpusId}`}
                    aria-current={isActive ? 'true' : undefined}
                    style={{
                      flex: 1,
                      background: isActive ? 'var(--accent)' : 'var(--bg-elev2)',
                      color: isActive ? 'var(--accent-contrast)' : 'var(--fg)',
                      border: `1px solid ${isActive ? 'var(--accent)' : 'var(--line)'}`,
                      padding: '12px 14px',
                      borderRadius: '8px',
                      cursor: switching ? 'not-allowed' : 'pointer',
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: '12px',
                      textAlign: 'left',
                      ...panelText,
                    }}
                  >
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: 'block', fontWeight: 600 }}>{corpus.name}</span>
                      <span
                        style={{
                          display: 'block',
                          color: isActive ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                          fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
                          ...labelText,
                        }}
                      >
                        {corpusId}
                      </span>
                      <span
                        style={{
                          display: 'block',
                          color: isActive ? 'var(--accent-contrast)' : 'var(--fg-muted)',
                          ...labelText,
                        }}
                      >
                        {indexedLabel(corpus)}
                        {corpus.path ? ` · ${corpus.path}` : ''}
                      </span>
                    </span>
                    <span style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                      {isInternal && (
                        <span
                          data-testid={`corpus-internal-${corpusId}`}
                          style={{
                            fontWeight: 600,
                            border: '1px solid currentColor',
                            padding: '3px 7px',
                            borderRadius: '4px',
                            ...labelText,
                          }}
                        >
                          Runtime-managed
                        </span>
                      )}
                      {isActive && (
                        <span
                          style={{
                            fontWeight: 600,
                            background: 'rgba(255,255,255,0.22)',
                            padding: '3px 7px',
                            borderRadius: '4px',
                            ...labelText,
                          }}
                        >
                          Active
                        </span>
                      )}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => void handleDelete(corpus)}
                    disabled={switching || isInternal}
                    data-testid={`corpus-delete-${corpusId}`}
                    aria-label={`Delete corpus ${corpus.name}`}
                    title={
                      isInternal
                        ? 'Runtime-managed corpora are recreated by the server and cannot be deleted here'
                        : `Delete corpus ${corpus.name}`
                    }
                    style={{
                      minWidth: '76px',
                      background: 'transparent',
                      color: isInternal ? 'var(--fg-muted)' : 'var(--err, #e5484d)',
                      border: `1px solid ${isInternal ? 'var(--line)' : 'var(--err, #e5484d)'}`,
                      borderRadius: '8px',
                      cursor: switching || isInternal ? 'not-allowed' : 'pointer',
                      fontWeight: 600,
                      ...panelText,
                    }}
                  >
                    Delete
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <div style={{ marginTop: '20px', borderTop: '1px solid var(--line)', paddingTop: '16px' }}>
          <div style={{ fontWeight: 600, marginBottom: '10px', ...panelText }}>Create corpus</div>
          {createError && <ErrorBanner message={createError} testId="corpus-registry-create-error" />}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              data-testid="corpus-create-name"
              aria-label="Corpus name"
              placeholder="Corpus name"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                ...panelText,
              }}
            />
            <input
              value={newPath}
              onChange={(e) => setNewPath(e.target.value)}
              data-testid="corpus-create-path"
              aria-label="Corpus root path"
              placeholder="/absolute/path/to/corpus"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                ...panelText,
              }}
            />
            <input
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              data-testid="corpus-create-description"
              aria-label="Corpus description"
              placeholder="Description (optional)"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: '6px',
                border: '1px solid var(--line)',
                background: 'var(--bg-elev2)',
                color: 'var(--fg)',
                ...panelText,
              }}
            />
            <button
              type="button"
              onClick={() => void handleCreate()}
              disabled={switching || loading || !newName.trim() || !newPath.trim()}
              data-testid="corpus-create-submit"
              style={{
                padding: '10px 16px',
                background: 'var(--accent)',
                border: '1px solid var(--accent)',
                color: 'var(--accent-contrast)',
                borderRadius: '6px',
                cursor: switching || loading ? 'not-allowed' : 'pointer',
                fontWeight: 600,
                ...panelText,
              }}
            >
              Create and select
            </button>
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            gap: '8px',
            marginTop: '20px',
            borderTop: '1px solid var(--line)',
            paddingTop: '16px',
          }}
        >
          <button
            type="button"
            onClick={onClose}
            data-testid="corpus-registry-close"
            style={{
              flex: 1,
              padding: '10px',
              background: 'transparent',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: 500,
              ...panelText,
            }}
          >
            Close
          </button>
          <button
            type="button"
            onClick={() => void loadRepos()}
            disabled={loading || switching}
            data-testid="corpus-registry-refresh"
            style={{
              padding: '10px 16px',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              borderRadius: '6px',
              cursor: loading || switching ? 'not-allowed' : 'pointer',
              fontWeight: 500,
              ...panelText,
            }}
          >
            Refresh
          </button>
        </div>
      </div>
    </div>
  );

  return createPortal(registry, document.body);
}

export default CorpusRegistry;
