import React, { useState } from 'react';
import { useGoldenQuestions, GoldenQuestion } from '@/hooks/useGoldenQuestions';
import { useUIHelpers } from '@/hooks/useUIHelpers';

interface QuestionManagerProps {
  className?: string;
}

const RECOMMENDED_GOLDEN: GoldenQuestion[] = [
  { q: 'Where is hybrid retrieval implemented?', repo: 'agro', expect_paths: ['retrieval/hybrid_search.py'] },
  { q: 'Where is keyword generation handled server-side?', repo: 'agro', expect_paths: ['server/app.py', 'keywords/generate'] },
  { q: 'Where is the metadata enrichment logic for code/keywords?', repo: 'agro', expect_paths: ['metadata_enricher.py'] },
  { q: 'Where is the indexing pipeline (BM25 and dense) implemented?', repo: 'agro', expect_paths: ['indexer/index_repo.py'] },
  { q: 'Where is comprehensive index status computed?', repo: 'agro', expect_paths: ['server/app.py', 'server/index_stats.py', 'index/status'] },
  { q: 'Where are semantic cards built or listed?', repo: 'agro', expect_paths: ['server/app.py', 'api/cards', 'indexer/build_cards.py'] },
  { q: 'Where are golden questions API routes defined?', repo: 'agro', expect_paths: ['server/app.py', 'api/golden'] },
  { q: 'Where is the endpoint to test a single golden question?', repo: 'agro', expect_paths: ['server/app.py', 'api/golden/test'] },
  { q: 'Where are GUI assets mounted and served?', repo: 'agro', expect_paths: ['server/app.py', '/gui', 'gui/index.html'] },
  { q: 'Where is repository configuration (repos.json) loaded?', repo: 'agro', expect_paths: ['config_loader.py'] },
  { q: 'Where are MCP stdio tools implemented (rag_answer, rag_search)?', repo: 'agro', expect_paths: ['server/mcp/server.py'] },
  { q: 'Where can I list or fetch latest LangGraph traces?', repo: 'agro', expect_paths: ['server/app.py', 'api/traces'] }
];

export const QuestionManager: React.FC<QuestionManagerProps> = ({ className = '' }) => {
  const {
    questions,
    isLoading,
    loadQuestions,
    addQuestion,
    updateQuestion,
    deleteQuestion,
    testQuestion,
    bulkAddRecommended,
    runAllTests,
    exportQuestions
  } = useGoldenQuestions();

  const { showToast } = useUIHelpers();

  const [newQuestion, setNewQuestion] = useState('');
  const [newRepo, setNewRepo] = useState('agro');
  const [newPaths, setNewPaths] = useState('');
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [testResults, setTestResults] = useState<Map<number, any>>(new Map());
  const [isRunningTests, setIsRunningTests] = useState(false);

  const handleAddQuestion = async () => {
    if (!newQuestion.trim()) {
      alert('Please enter a question');
      return;
    }

    try {
      const expectPaths = newPaths
        .split(',')
        .map(p => p.trim())
        .filter(p => p);

      await addQuestion({
        q: newQuestion,
        repo: newRepo,
        expect_paths: expectPaths
      });

      // Clear form
      setNewQuestion('');
      setNewPaths('');
      showToast('Question added successfully', 'success');
    } catch (error) {
      console.error('Failed to add question:', error);
      alert(`Failed to add question: ${error}`);
    }
  };

  const handleTestQuestion = async (index: number) => {
    const question = questions[index];
    if (!question) return;

    try {
      const result = await testQuestion(question);
      setTestResults(prev => new Map(prev).set(index, result));
    } catch (error) {
      console.error('Test failed:', error);
      alert(`Test failed: ${error}`);
    }
  };

  const handleDeleteQuestion = async (index: number) => {
    if (!confirm('Delete this question?')) return;

    try {
      await deleteQuestion(index);
      showToast('Question deleted', 'success');
      // Clear test result if exists
      setTestResults(prev => {
        const next = new Map(prev);
        next.delete(index);
        return next;
      });
    } catch (error) {
      console.error('Failed to delete:', error);
      alert(`Failed to delete: ${error}`);
    }
  };

  const handleLoadRecommended = async () => {
    try {
      const result = await bulkAddRecommended(RECOMMENDED_GOLDEN);
      showToast(`Loaded ${result.added} recommended questions`, result.added > 0 ? 'success' : 'error');
      if (result.errors.length > 0) {
        console.error('Bulk add errors:', result.errors);
      }
    } catch (error) {
      console.error('Failed to load recommended:', error);
      alert(`Failed to load recommended questions: ${error}`);
    }
  };

  const handleRunAllTests = async () => {
    setIsRunningTests(true);
    try {
      const summary = await runAllTests();
      showToast(
        `Tests complete: Top-1 ${summary.top1}/${summary.total}, Top-K ${summary.topk}/${summary.total}`,
        'success'
      );

      // Update test results map
      const newResults = new Map<number, any>();
      summary.results.forEach(({ result }, index) => {
        newResults.set(index, result);
      });
      setTestResults(newResults);
    } catch (error) {
      console.error('Run all tests failed:', error);
      alert(`Run all tests failed: ${error}`);
    } finally {
      setIsRunningTests(false);
    }
  };

  const handleExport = () => {
    exportQuestions();
    showToast('Questions exported', 'success');
  };

  return (
    <div className={`question-manager ${className}`}>
      {/* Add Question Form */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px',
        marginBottom: '20px'
      }}>
        <h3 style={{
          fontSize: '14px',
          fontWeight: 600,
          color: 'var(--fg)',
          marginBottom: '16px',
          textTransform: 'uppercase',
          letterSpacing: '0.5px'
        }}>
          Add Golden Question
        </h3>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="golden-new-q" style={{
            fontSize: '12px',
            color: 'var(--fg-muted)',
            display: 'block',
            marginBottom: '6px'
          }}>
            Question
          </label>
          <textarea
            id="golden-new-q"
            value={newQuestion}
            onChange={(e) => setNewQuestion(e.target.value)}
            placeholder="e.g., Where is the hybrid retrieval implemented?"
            style={{
              width: '100%',
              background: 'var(--bg-elev2)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px',
              borderRadius: '4px',
              fontSize: '13px',
              minHeight: '60px',
              fontFamily: 'inherit',
              resize: 'vertical'
            }}
          />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '12px', marginBottom: '12px' }}>
          <div>
            <label htmlFor="golden-new-repo" style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              display: 'block',
              marginBottom: '6px'
            }}>
              Repository
            </label>
            <select
              id="golden-new-repo"
              value={newRepo}
              onChange={(e) => setNewRepo(e.target.value)}
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            >
              <option value="agro">agro</option>
            </select>
          </div>

          <div>
            <label htmlFor="golden-new-paths" style={{
              fontSize: '12px',
              color: 'var(--fg-muted)',
              display: 'block',
              marginBottom: '6px'
            }}>
              Expected Paths (comma-separated)
            </label>
            <input
              type="text"
              id="golden-new-paths"
              value={newPaths}
              onChange={(e) => setNewPaths(e.target.value)}
              placeholder="e.g., retrieval/hybrid_search.py, server/app.py"
              style={{
                width: '100%',
                background: 'var(--bg-elev2)',
                border: '1px solid var(--line)',
                color: 'var(--fg)',
                padding: '8px',
                borderRadius: '4px',
                fontSize: '13px'
              }}
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button
            onClick={handleAddQuestion}
            style={{
              flex: 1,
              minWidth: '120px',
              background: 'var(--accent)',
              color: 'var(--accent-contrast)',
              border: 'none',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            Add Question
          </button>

          <button
            onClick={handleLoadRecommended}
            style={{
              background: 'var(--link)',
              color: 'white',
              border: 'none',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            Load Recommended
          </button>

          <button
            onClick={handleRunAllTests}
            disabled={isRunningTests || questions.length === 0}
            style={{
              background: isRunningTests ? 'var(--bg-elev2)' : 'var(--warn)',
              color: isRunningTests ? 'var(--fg-muted)' : 'var(--bg)',
              border: 'none',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: isRunningTests || questions.length === 0 ? 'not-allowed' : 'pointer',
              opacity: isRunningTests || questions.length === 0 ? 0.7 : 1
            }}
          >
            {isRunningTests ? 'Running...' : 'Run All Tests'}
          </button>

          <button
            onClick={handleExport}
            disabled={questions.length === 0}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: questions.length === 0 ? 'not-allowed' : 'pointer',
              opacity: questions.length === 0 ? 0.7 : 1
            }}
          >
            Export
          </button>

          <button
            onClick={() => loadQuestions()}
            style={{
              background: 'var(--bg-elev2)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '10px 16px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            Refresh
          </button>
        </div>
      </div>

      {/* Questions List */}
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        padding: '16px'
      }}>
        <h3 style={{
          fontSize: '14px',
          fontWeight: 600,
          color: 'var(--fg)',
          marginBottom: '16px',
          textTransform: 'uppercase',
          letterSpacing: '0.5px'
        }}>
          Golden Questions ({questions.length})
        </h3>

        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
            Loading questions...
          </div>
        ) : questions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
            <div style={{ marginBottom: '12px', opacity: 0.3 }}>
              <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>
            </div>
            <div>No golden questions yet. Add one above!</div>
          </div>
        ) : (
          <div>
            {questions.map((question, index) => {
              const testResult = testResults.get(index);
              const isEditing = editingIndex === index;

              return (
                <div
                  key={index}
                  style={{
                    background: 'var(--bg-elev2)',
                    border: '1px solid var(--line)',
                    borderRadius: '4px',
                    padding: '12px',
                    marginBottom: '10px'
                  }}
                >
                  {isEditing ? (
                    <EditQuestionForm
                      question={question}
                      index={index}
                      onSave={async (updated) => {
                        await updateQuestion(index, updated);
                        setEditingIndex(null);
                        showToast('Question updated', 'success');
                      }}
                      onCancel={() => setEditingIndex(null)}
                    />
                  ) : (
                    <>
                      <div style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'start',
                        marginBottom: '8px'
                      }}>
                        <div style={{ flex: 1 }}>
                          <div style={{
                            fontWeight: 600,
                            color: 'var(--fg)',
                            marginBottom: '4px',
                            wordBreak: 'break-word'
                          }}>
                            {question.q}
                          </div>
                          <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                            <span style={{
                              background: 'var(--bg)',
                              padding: '2px 6px',
                              borderRadius: '3px',
                              marginRight: '6px'
                            }}>
                              {question.repo}
                            </span>
                            {question.expect_paths.map((path, i) => (
                              <span key={i} style={{ color: 'var(--accent)', marginRight: '4px' }}>
                                {path}
                              </span>
                            ))}
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px', marginLeft: '12px' }}>
                          <button
                            onClick={() => handleTestQuestion(index)}
                            style={{
                              background: 'var(--bg)',
                              color: 'var(--link)',
                              border: '1px solid var(--link)',
                              padding: '4px 8px',
                              borderRadius: '3px',
                              fontSize: '11px',
                              cursor: 'pointer',
                              whiteSpace: 'nowrap'
                            }}
                          >
                            Test
                          </button>
                          <button
                            onClick={() => setEditingIndex(index)}
                            style={{
                              background: 'var(--bg)',
                              color: 'var(--warn)',
                              border: '1px solid var(--warn)',
                              padding: '4px 8px',
                              borderRadius: '3px',
                              fontSize: '11px',
                              cursor: 'pointer'
                            }}
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => handleDeleteQuestion(index)}
                            style={{
                              background: 'var(--bg)',
                              color: 'var(--err)',
                              border: '1px solid var(--err)',
                              padding: '4px 8px',
                              borderRadius: '3px',
                              fontSize: '11px',
                              cursor: 'pointer'
                            }}
                          >
                            ✗
                          </button>
                        </div>
                      </div>

                      {testResult && (
                        <div style={{
                          marginTop: '8px',
                          paddingTop: '8px',
                          borderTop: '1px solid var(--line)',
                          fontSize: '12px'
                        }}>
                          <div style={{ marginBottom: '8px' }}>
                            <span style={{
                              color: testResult.top1_hit ? 'var(--accent)' : 'var(--err)',
                              fontWeight: 600
                            }}>
                              {testResult.top1_hit ? '✓' : '✗'} Top-1
                            </span>
                            <span style={{
                              marginLeft: '12px',
                              color: testResult.topk_hit ? 'var(--accent)' : 'var(--warn)',
                              fontWeight: 600
                            }}>
                              {testResult.topk_hit ? '✓' : '✗'} Top-K
                            </span>
                          </div>

                          {testResult.all_results && testResult.all_results.length > 0 && (
                            <div style={{ fontSize: '11px', color: 'var(--fg-muted)' }}>
                              <div style={{ marginBottom: '4px' }}>
                                <strong>Top Results:</strong>
                              </div>
                              {testResult.all_results.slice(0, 3).map((r: any, i: number) => {
                                const color = i === 0 && testResult.top1_hit ? 'var(--accent)' : 'var(--fg-muted)';
                                return (
                                  <div
                                    key={i}
                                    style={{
                                      color,
                                      fontFamily: "'SF Mono', monospace",
                                      fontSize: '10px',
                                      marginLeft: '8px',
                                      marginTop: '2px'
                                    }}
                                  >
                                    {r.file_path}:{r.start_line} (score: {r.rerank_score.toFixed(3)})
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

// Helper component for editing questions inline
const EditQuestionForm: React.FC<{
  question: GoldenQuestion;
  index: number;
  onSave: (question: GoldenQuestion) => Promise<void>;
  onCancel: () => void;
}> = ({ question, index, onSave, onCancel }) => {
  const [q, setQ] = useState(question.q);
  const [repo, setRepo] = useState(question.repo);
  const [paths, setPaths] = useState(question.expect_paths.join(', '));

  const handleSave = async () => {
    if (!q.trim()) {
      alert('Question cannot be empty');
      return;
    }

    const expectPaths = paths
      .split(',')
      .map(p => p.trim())
      .filter(p => p);

    await onSave({ q, repo, expect_paths: expectPaths });
  };

  return (
    <div style={{ background: 'var(--panel)', padding: '12px', borderRadius: '4px' }}>
      <div style={{ marginBottom: '8px' }}>
        <label style={{
          fontSize: '11px',
          color: 'var(--fg-muted)',
          display: 'block',
          marginBottom: '4px'
        }}>
          Question
        </label>
        <textarea
          value={q}
          onChange={(e) => setQ(e.target.value)}
          style={{
            width: '100%',
            background: 'var(--card-bg)',
            border: '1px solid var(--line)',
            color: 'var(--fg)',
            padding: '8px',
            borderRadius: '3px',
            fontSize: '13px',
            minHeight: '60px',
            fontFamily: 'inherit',
            resize: 'vertical'
          }}
        />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '8px', marginBottom: '8px' }}>
        <div>
          <label style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            display: 'block',
            marginBottom: '4px'
          }}>
            Repo
          </label>
          <select
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
            style={{
              width: '100%',
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px',
              borderRadius: '3px'
            }}
          >
            <option value="agro">agro</option>
          </select>
        </div>

        <div>
          <label style={{
            fontSize: '11px',
            color: 'var(--fg-muted)',
            display: 'block',
            marginBottom: '4px'
          }}>
            Expected Paths (comma-separated)
          </label>
          <input
            type="text"
            value={paths}
            onChange={(e) => setPaths(e.target.value)}
            style={{
              width: '100%',
              background: 'var(--card-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '6px',
              borderRadius: '3px',
              fontSize: '12px'
            }}
          />
        </div>
      </div>

      <div style={{ display: 'flex', gap: '6px' }}>
        <button
          onClick={handleSave}
          style={{
            flex: 1,
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '8px',
            borderRadius: '3px',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer'
          }}
        >
          Save
        </button>
        <button
          onClick={onCancel}
          style={{
            flex: 1,
            background: 'var(--bg-elev2)',
            color: 'var(--fg-muted)',
            border: '1px solid var(--line)',
            padding: '8px',
            borderRadius: '3px',
            fontSize: '12px',
            cursor: 'pointer'
          }}
        >
          Cancel
        </button>
      </div>
    </div>
  );
};
