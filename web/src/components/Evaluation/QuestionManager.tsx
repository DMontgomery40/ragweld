/**
 * EvalDatasetManager (formerly QuestionManager)
 * Manages evaluation dataset entries for RAG testing
 *
 * Terminology: the legacy curated-eval term is banned - use "eval dataset" / "eval entries"
 */

import { useState, useEffect } from 'react';
import { useEvalDataset } from '@/hooks/useEvalDataset';
import { useUIHelpers } from '@/hooks/useUIHelpers';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { useActiveRepo } from '@/stores';
import type { EvalDatasetItem } from '@/types/generated';
import {
  EMPTY_DRAFT,
  buildExpectedLocations,
  draftsFromLocations,
  formatLocation,
  locationFor,
  parseExpectedPaths,
  type LocationDraft,
} from './evalLocations';

interface QuestionManagerProps {
  className?: string;
}

const LOCATION_HINT =
  'Optional: pin each path to the pages (PDF) or lines (text, code) that hold the answer. ' +
  'A whole-file path cannot fail on a single-document corpus, so it is reported as uninformative.';

const fieldStyle: React.CSSProperties = {
  padding: '6px 8px',
  background: 'var(--input-bg)',
  border: '1px solid var(--line)',
  borderRadius: '4px',
  color: 'var(--fg)',
  fontSize: '13px',
};

interface LocationEditorProps {
  paths: string[];
  drafts: Record<string, LocationDraft>;
  onChange: (path: string, draft: LocationDraft) => void;
  testIdPrefix: string;
}

/** One row per expected path: whole file, or a page/line span. */
const LocationEditor: React.FC<LocationEditorProps> = ({ paths, drafts, onChange, testIdPrefix }) => {
  if (paths.length === 0) return null;
  return (
    <div data-testid={`${testIdPrefix}-locations`} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {paths.map((path, index) => {
        const draft = drafts[path] ?? EMPTY_DRAFT;
        const unitLabel = draft.unit === 'page' ? 'page' : 'line';
        return (
          <div
            key={path}
            data-testid={`${testIdPrefix}-location-${index}`}
            style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: '8px' }}
          >
            <span
              style={{
                fontFamily: 'monospace',
                fontSize: '12px',
                color: 'var(--fg)',
                minWidth: '120px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
                flex: '1 1 160px',
              }}
              title={path}
            >
              {path}
            </span>
            <select
              aria-label={`Location for ${path}`}
              data-testid={`${testIdPrefix}-location-unit-${index}`}
              value={draft.unit}
              onChange={(e) => onChange(path, { ...draft, unit: e.target.value as LocationDraft['unit'] })}
              style={fieldStyle}
            >
              <option value="">Whole file</option>
              <option value="page">Pages</option>
              <option value="line">Lines</option>
            </select>
            {draft.unit ? (
              <>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  aria-label={`First ${unitLabel} for ${path}`}
                  data-testid={`${testIdPrefix}-location-start-${index}`}
                  placeholder={`first ${unitLabel}`}
                  value={draft.start}
                  onChange={(e) => onChange(path, { ...draft, start: e.target.value })}
                  style={{ ...fieldStyle, width: '96px' }}
                />
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  aria-label={`Last ${unitLabel} for ${path}`}
                  data-testid={`${testIdPrefix}-location-end-${index}`}
                  placeholder={`last ${unitLabel}`}
                  value={draft.end}
                  onChange={(e) => onChange(path, { ...draft, end: e.target.value })}
                  style={{ ...fieldStyle, width: '96px' }}
                />
              </>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};

function describeExpected(entry: EvalDatasetItem): string {
  return (entry.expected_paths ?? [])
    .map((path) => {
      const location = locationFor(entry.expected_locations, path);
      return location ? `${path} (${formatLocation(location)})` : path;
    })
    .join(', ');
}

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
  const activeRepo = useActiveRepo();

  const [newQuestion, setNewQuestion] = useState('');
  const [newPaths, setNewPaths] = useState('');
  const [newAnswer, setNewAnswer] = useState('');
  const [newDrafts, setNewDrafts] = useState<Record<string, LocationDraft>>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editQuestion, setEditQuestion] = useState('');
  const [editPaths, setEditPaths] = useState('');
  const [editAnswer, setEditAnswer] = useState('');
  const [editDrafts, setEditDrafts] = useState<Record<string, LocationDraft>>({});

  const newPathList = parseExpectedPaths(newPaths);
  const editPathList = parseExpectedPaths(editPaths);

  useEffect(() => {
    refreshEntries();
  }, [refreshEntries]);

  const handleAddEntry = async () => {
    if (!activeRepo) {
      showToast('Select a corpus first', 'error');
      return;
    }
    if (!newQuestion.trim()) {
      showToast('Please enter a question', 'error');
      return;
    }

    const { locations, error: locationError } = buildExpectedLocations(newPathList, newDrafts);
    if (locationError) {
      showToast(locationError, 'error');
      return;
    }

    const result = await addEntry({
      question: newQuestion,
      expected_paths: newPathList,
      expected_locations: locations,
      expected_answer: newAnswer.trim() || undefined,
    });

    if (result) {
      setNewQuestion('');
      setNewPaths('');
      setNewAnswer('');
      setNewDrafts({});
      showToast('Entry added', 'success');
    }
  };

  const handleUpdateEntry = async (entryId: string) => {
    const { locations, error: locationError } = buildExpectedLocations(editPathList, editDrafts);
    if (locationError) {
      showToast(locationError, 'error');
      return;
    }

    const result = await updateEntry(entryId, {
      question: editQuestion,
      expected_paths: editPathList,
      expected_locations: locations,
      expected_answer: editAnswer.trim() || undefined,
    });

    if (result) {
      setEditingId(null);
      showToast('Entry updated', 'success');
    }
  };

  const handleDeleteEntry = async (entryId: string, question?: string) => {
    const q = String(question || '').trim();
    const quoted = q ? `"${q.length > 120 ? `${q.slice(0, 117)}…` : q}"` : 'this eval entry';
    const proceed = await confirmDialog({
      title: 'Delete eval entry',
      message:
        `Delete ${quoted} from the eval dataset. This removes the question and its expected ` +
        `evidence; eval and promptfoo runs already computed against it keep their results, but ` +
        `no future run will include it. This cannot be undone.`,
      confirmLabel: 'Delete entry',
      cancelLabel: 'Keep entry',
      danger: true,
    });
    if (!proceed) return;

    const success = await deleteEntry(entryId);
    if (success) {
      showToast('Entry deleted', 'success');
    }
  };

  const startEditing = (entry: EvalDatasetItem) => {
    if (!entry.entry_id) return;
    setEditingId(entry.entry_id);
    setEditQuestion(entry.question);
    setEditPaths(entry.expected_paths?.join(', ') || '');
    setEditDrafts(draftsFromLocations(entry.expected_locations));
    setEditAnswer(entry.expected_answer || '');
  };

  const cancelEditing = () => {
    setEditingId(null);
    setEditQuestion('');
    setEditPaths('');
    setEditDrafts({});
    setEditAnswer('');
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

          <input
            type="text"
            placeholder="Expected paths (comma-separated)"
            aria-label="Expected paths"
            data-testid="eval-new-expected-paths"
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

          <LocationEditor
            paths={newPathList}
            drafts={newDrafts}
            onChange={(path, draft) => setNewDrafts((prev) => ({ ...prev, [path]: draft }))}
            testIdPrefix="eval-new"
          />
          <div data-testid="eval-location-hint" style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
            {LOCATION_HINT}
          </div>

          <textarea
            placeholder="Expected answer (optional — the rubric the Promptfoo grader scores against)"
            aria-label="Expected answer"
            data-testid="eval-new-expected-answer"
            value={newAnswer}
            onChange={(e) => setNewAnswer(e.target.value)}
            rows={2}
            style={{
              padding: '10px',
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              borderRadius: '4px',
              color: 'var(--fg)',
              fontSize: '13px',
              resize: 'vertical',
            }}
          />
          <div style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
            Entries without an expected answer are skipped by the Promptfoo regression grader.
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={handleAddEntry}
              disabled={saving || !newQuestion.trim() || !activeRepo}
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
            No eval entries yet. Add one above.
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
                      aria-label="Expected paths"
                      data-testid="eval-edit-expected-paths"
                      style={{
                        padding: '8px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        color: 'var(--fg)',
                      }}
                    />
                    <LocationEditor
                      paths={editPathList}
                      drafts={editDrafts}
                      onChange={(path, draft) => setEditDrafts((prev) => ({ ...prev, [path]: draft }))}
                      testIdPrefix="eval-edit"
                    />
                    <textarea
                      value={editAnswer}
                      onChange={(e) => setEditAnswer(e.target.value)}
                      placeholder="Expected answer (optional — scored by the Promptfoo grader)"
                      aria-label="Expected answer"
                      data-testid="eval-edit-expected-answer"
                      rows={2}
                      style={{
                        padding: '8px',
                        background: 'var(--input-bg)',
                        border: '1px solid var(--line)',
                        borderRadius: '4px',
                        color: 'var(--fg)',
                        fontSize: '13px',
                        resize: 'vertical',
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
                        <div data-testid="eval-entry-expected" style={{ fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                          Expected: {describeExpected(entry)}
                        </div>
                      )}
                      {entry.expected_answer && entry.expected_answer.trim() ? (
                        <div data-testid="eval-entry-expected-answer" style={{ fontSize: '11.5px', color: 'var(--fg-muted)', marginTop: '2px' }}>
                          Expected answer: {entry.expected_answer}
                        </div>
                      ) : null}
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
                        onClick={() => entry.entry_id && handleDeleteEntry(entry.entry_id, entry.question)}
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
