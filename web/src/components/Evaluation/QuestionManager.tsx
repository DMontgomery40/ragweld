/**
 * EvalDatasetManager (formerly QuestionManager)
 * Manages evaluation dataset entries for RAG testing
 *
 * Terminology: "golden questions" is banned - use "eval dataset" / "eval entries"
 */

import { useState, useEffect } from 'react';
import { useEvalDataset } from '@/hooks/useEvalDataset';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import type { EvalDatasetItem } from '@/types/generated';

interface QuestionManagerProps {
  className?: string;
}

// Recommended eval dataset entries for TriBridRAG testing
const RECOMMENDED_ENTRIES: Array<{ question: string; corpus_id: string; expected_paths: string[] }> = [
  { question: 'Where is hybrid retrieval implemented?', corpus_id: 'tribrid', expected_paths: ['retrieval/fusion.py'] },
  { question: 'Where is the graph search logic?', corpus_id: 'tribrid', expected_paths: ['retrieval/graph.py'] },
  { question: 'Where is the vector search implemented?', corpus_id: 'tribrid', expected_paths: ['retrieval/vector.py'] },
  { question: 'Where is the sparse/BM25 search logic?', corpus_id: 'tribrid', expected_paths: ['retrieval/sparse.py'] },
  { question: 'Where is the reranking logic?', corpus_id: 'tribrid', expected_paths: ['retrieval/rerank.py'] },
  { question: 'Where is the indexing pipeline implemented?', corpus_id: 'tribrid', expected_paths: ['indexing/embedder.py', 'indexing/chunker.py'] },
  { question: 'Where is the graph builder?', corpus_id: 'tribrid', expected_paths: ['indexing/graph_builder.py'] },
  { question: 'Where is the Pydantic config model?', corpus_id: 'tribrid', expected_paths: ['models/tribrid_config_model.py'] },
];

export const QuestionManager: React.FC<QuestionManagerProps> = ({ className = '' }) => {
  const {
    entries,
    loading,
    error,
    saving,
    addEntry,
    updateEntry,
    deleteEntry,
    refreshEntries,
  } = useEvalDataset();

  const { showToast } = useUIHelpers();

  const [newQuestion, setNewQuestion] = useState('');
  const [newCorpus, setNewCorpus] = useState('tribrid');
  const [newPaths, setNewPaths] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editQuestion, setEditQuestion] = useState('');
  const [editPaths, setEditPaths] = useState('');

  useEffect(() => {
    refreshEntries();
  }, [refreshEntries]);

  const handleAddEntry = async () => {
    if (!newQuestion.trim()) {
      showToast('Please enter a question', 'error');
      return;
    }

    const expectedChunks = newPaths
      .split(',')
      .map(p => p.trim())
      .filter(p => p);

    const result = await addEntry({
      question: newQuestion,
      expected_paths: expectedChunks,
      tags: [newCorpus],
    });

    if (result) {
      setNewQuestion('');
      setNewPaths('');
      showToast('Entry added', 'success');
    }
  };

  const handleUpdateEntry = async (entryId: string) => {
    const expectedChunks = editPaths
      .split(',')
      .map(p => p.trim())
      .filter(p => p);

    const result = await updateEntry(entryId, {
      question: editQuestion,
      expected_paths: expectedChunks,
    });

    if (result) {
      setEditingId(null);
      showToast('Entry updated', 'success');
    }
  };

  const handleDeleteEntry = async (entryId: string) => {
    if (!confirm('Delete this eval entry?')) return;

    const success = await deleteEntry(entryId);
    if (success) {
      showToast('Entry deleted', 'success');
    }
  };

  const handleBulkAdd = async () => {
    if (!confirm(`Add ${RECOMMENDED_ENTRIES.length} recommended eval entries?`)) return;

    let added = 0;
    for (const entry of RECOMMENDED_ENTRIES) {
      const result = await addEntry({
        question: entry.question,
        expected_paths: entry.expected_paths,
        tags: [entry.corpus_id],
      });
      if (result) added++;
    }

    showToast(`Added ${added} entries`, 'success');
  };

  const startEditing = (entry: EvalDatasetItem) => {
    if (!entry.entry_id) return;
    setEditingId(entry.entry_id);
    setEditQuestion(entry.question);
    setEditPaths(entry.expected_paths?.join(', ') || '');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditQuestion('');
    setEditPaths('');
  };

  if (loading && entries.length === 0) {
    return (
      <div className={className} style={{ padding: '20px', textAlign: 'center', color: 'var(--fg-muted)' }}>
        Loading eval dataset...
      </div>
    );
  }

  return (
    <div className={className} style={{ padding: '16px' }}>
      {error && (
        <div style={{
          background: 'var(--err-bg)',
          border: '1px solid var(--err)',
          borderRadius: '6px',
          padding: '12px',
          marginBottom: '16px',
          color: 'var(--err)'
        }}>
          {error}
        </div>
      )}

      {/* Add New Entry */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px',
        marginBottom: '16px'
      }}>
        <h3 style={{ fontSize: '14px', marginBottom: '12px', color: 'var(--fg)' }}>
          Add Eval Entry
        </h3>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <input
            type="text"
            placeholder="Question (e.g., Where is X implemented?)"
            value={newQuestion}
            onChange={(e) => setNewQuestion(e.target.value)}
            style={{
              width: '100%',
              padding: '10px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)',
            }}
          />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '8px' }}>
            <input
              type="text"
              placeholder="Corpus ID"
              value={newCorpus}
              onChange={(e) => setNewCorpus(e.target.value)}
              style={{
                padding: '10px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)',
              }}
            />
            <input
              type="text"
              placeholder="Expected chunks (comma-separated paths)"
              value={newPaths}
              onChange={(e) => setNewPaths(e.target.value)}
              style={{
                padding: '10px',
                background: 'var(--input-bg)',
                border: '1px solid var(--line)',
                borderRadius: '4px',
                color: 'var(--fg)',
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleAddEntry}
              disabled={saving || !newQuestion.trim()}
              style={{
                flex: 1,
                padding: '10px',
                background: 'var(--accent)',
                color: 'var(--accent-contrast)',
                border: 'none',
                borderRadius: '4px',
                fontWeight: 600,
                cursor: saving ? 'not-allowed' : 'pointer',
                opacity: saving ? 0.6 : 1,
              }}
            >
              {saving ? 'Adding...' : 'Add Entry'}
            </button>
            <button
              onClick={handleBulkAdd}
              disabled={saving}
              style={{
                padding: '10px 16px',
                background: 'var(--bg-elev1)',
                color: 'var(--link)',
                border: '1px solid var(--link)',
                borderRadius: '4px',
                cursor: saving ? 'not-allowed' : 'pointer',
              }}
            >
              Add Recommended ({RECOMMENDED_ENTRIES.length})
            </button>
          </div>
        </div>
      </div>

      {/* Entry List */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        overflow: 'hidden'
      }}>
        <div style={{
          padding: '12px 16px',
          borderBottom: '1px solid var(--line)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center'
        }}>
          <h3 style={{ fontSize: '14px', color: 'var(--fg)', margin: 0 }}>
            Eval Dataset ({entries.length} entries)
          </h3>
          <button
            onClick={() => refreshEntries()}
            disabled={loading}
            style={{
              padding: '6px 12px',
              background: 'transparent',
              color: 'var(--link)',
              border: '1px solid var(--link)',
              borderRadius: '4px',
              fontSize: '12px',
              cursor: 'pointer',
            }}
          >
            Refresh
          </button>
        </div>

        {entries.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--fg-muted)' }}>
            No eval entries yet. Add some above or use recommended entries.
          </div>
        ) : (
          <div style={{ maxHeight: '400px', overflow: 'auto' }}>
            {entries.map((entry) => (
              <div
                key={entry.entry_id}
                style={{
                  padding: '12px 16px',
                  borderBottom: '1px solid var(--line)',
                  background: editingId === entry.entry_id ? 'var(--bg-elev1)' : 'transparent',
                }}
              >
                {editingId === entry.entry_id ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <input
                      type="text"
                      value={editQuestion}
                      onChange={(e) => setEditQuestion(e.target.value)}
                      style={{
                        padding: '8px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        color: 'var(--fg)',
                      }}
                    />
                    <input
                      type="text"
                      value={editPaths}
                      onChange={(e) => setEditPaths(e.target.value)}
                      placeholder="Expected paths (comma-separated)"
                      style={{
                        padding: '8px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        color: 'var(--fg)',
                      }}
                    />
                    <div style={{ display: 'flex', gap: '8px' }}>
                      <button
                        onClick={() => entry.entry_id && handleUpdateEntry(entry.entry_id)}
                        disabled={saving || !entry.entry_id}
                        style={{
                          padding: '6px 12px',
                          background: 'var(--accent)',
                          color: 'var(--accent-contrast)',
                          border: 'none',
                          borderRadius: '4px',
                          fontSize: '12px',
                        }}
                      >
                        Save
                      </button>
                      <button
                        onClick={cancelEditing}
                        style={{
                          padding: '6px 12px',
                          background: 'transparent',
                          color: 'var(--fg-muted)',
                          border: '1px solid var(--line)',
                          borderRadius: '4px',
                          fontSize: '12px',
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ color: 'var(--fg)', fontSize: '13px', marginBottom: '4px' }}>
                        {entry.question}
                      </div>
                      {entry.expected_paths && entry.expected_paths.length > 0 && (
                        <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                          Expected: {entry.expected_paths.join(', ')}
                        </div>
                      )}
                      {entry.tags && entry.tags.length > 0 && (
                        <div style={{ fontSize: '10px', color: 'var(--link)', marginTop: '4px' }}>
                          {entry.tags.map(tag => `#${tag}`).join(' ')}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', gap: '4px', marginLeft: '12px' }}>
                      <button
                        onClick={() => startEditing(entry)}
                        style={{
                          padding: '4px 8px',
                          background: 'transparent',
                          color: 'var(--link)',
                          border: '1px solid var(--link)',
                          borderRadius: '4px',
                          fontSize: '11px',
                          cursor: 'pointer',
                        }}
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => entry.entry_id && handleDeleteEntry(entry.entry_id)}
                        style={{
                          padding: '4px 8px',
                          background: 'transparent',
                          color: 'var(--err)',
                          border: '1px solid var(--err)',
                          borderRadius: '4px',
                          fontSize: '11px',
                          cursor: 'pointer',
                        }}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

// Export with proper name (QuestionManager kept for backward compat in imports)
export { QuestionManager as EvalDatasetManager };
export default QuestionManager;
