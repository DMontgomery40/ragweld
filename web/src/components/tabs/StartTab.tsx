// Get Started: a four-step onboarding that only promises what the app can do,
// on the real APIs (corpus registry, index run stream, chat). The previous
// wizard was a vanilla-JS-era mock whose folder/GitHub cards, sliders, eval and
// help controls had no code behind them (2026-08-25 drive finding M1).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { indexingApi } from '@/api/indexing';
import { AssistantMarkdown } from '@/components/ui/AssistantMarkdown';
import { confirmDialog } from '@/components/ui/confirmDialog';
import { useAPI } from '@/hooks/useAPI';
import { useIndexing } from '@/hooks/useIndexing';
import { useOnboarding } from '@/hooks/useOnboarding';
import { useRepoStore } from '@/stores/useRepoStore';
import type { ChatResponse, ChunkMatch, IndexStats } from '@/types/generated';

const INDEX_TERMINAL_ID = 'onboarding-index';

const STEP_TITLES = ['Welcome', 'Your corpus', 'Build indexes', 'Ask a question'];

function formatCitation(match: ChunkMatch): string {
  const lines = match.start_line && match.end_line ? `:${match.start_line}-${match.end_line}` : '';
  return `${match.file_path}${lines}`;
}

export default function StartTab() {
  const navigate = useNavigate();
  const { api } = useAPI();
  const { step, corpusId, maxStep, setStep, nextStep, prevStep, setCorpusId, reset } = useOnboarding();
  const { repos, loadRepos, initialized, addRepo, setActiveRepo } = useRepoStore();
  const { fetchStats, startAndStream, disconnectStream } = useIndexing();

  // Step 2 — corpus
  const [corpusName, setCorpusName] = useState('');
  const [corpusPath, setCorpusPath] = useState('');
  const [creating, setCreating] = useState(false);
  const [corpusError, setCorpusError] = useState<string | null>(null);

  // Step 3 — index
  const [indexStats, setIndexStats] = useState<IndexStats | null>(null);
  const [indexing, setIndexing] = useState(false);
  const [indexProgress, setIndexProgress] = useState(0);
  const [indexStatusText, setIndexStatusText] = useState('Ready to index');
  const [indexLog, setIndexLog] = useState<string[]>([]);
  const [indexError, setIndexError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement | null>(null);

  // Step 4 — first question
  const [question, setQuestion] = useState('');
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [askError, setAskError] = useState<string | null>(null);
  const conversationIdRef = useRef<string>(`onboarding-${Date.now().toString(36)}`);

  useEffect(() => {
    if (!initialized) void loadRepos();
  }, [initialized, loadRepos]);

  useEffect(() => () => disconnectStream(INDEX_TERMINAL_ID), [disconnectStream]);

  const corpus = useMemo(() => repos.find((r) => String(r.corpus_id) === corpusId) || null, [repos, corpusId]);

  // Keep the index summary current for the chosen corpus.
  useEffect(() => {
    if (!corpusId) {
      setIndexStats(null);
      return;
    }
    let cancelled = false;
    fetchStats(corpusId, { quiet: true })
      .then((stats) => {
        if (!cancelled) setIndexStats(stats);
      })
      .catch(() => {
        if (!cancelled) setIndexStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, fetchStats]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [indexLog.length]);

  const handleCreateCorpus = useCallback(async () => {
    const name = corpusName.trim();
    const path = corpusPath.trim();
    if (!name || !path) {
      setCorpusError('Give the corpus a name and the folder path to index.');
      return;
    }
    setCreating(true);
    setCorpusError(null);
    try {
      const created = await addRepo({ name, path });
      setCorpusId(String(created.corpus_id));
      setIndexStats(null);
      nextStep();
    } catch (error) {
      setCorpusError(error instanceof Error ? error.message : 'Failed to create the corpus');
    } finally {
      setCreating(false);
    }
  }, [addRepo, corpusName, corpusPath, nextStep, setCorpusId]);

  const handlePickExisting = useCallback(
    async (id: string) => {
      setCorpusError(null);
      if (!id) {
        setCorpusId('');
        return;
      }
      try {
        await setActiveRepo(id);
        setCorpusId(id);
      } catch (error) {
        setCorpusError(error instanceof Error ? error.message : 'Failed to activate the corpus');
      }
    },
    [setActiveRepo, setCorpusId]
  );

  const handleStartIndex = useCallback(async () => {
    if (!corpus) return;
    setIndexError(null);
    // The same estimate + confirmation gate as RAG → Indexing: no index run
    // (and no embedding/GraphRAG spend) starts before the operator sees the
    // file/chunk/cost/time estimate and agrees.
    const request = { corpus_id: corpus.corpus_id, repo_path: corpus.path, force_reindex: false };
    let estimate;
    try {
      // indexingApi.estimate waits out a cold or under-sampled estimator and only ever resolves
      // with a measured one, so the confirmation below cannot be built from a payload that has
      // no numbers in it. Surface the wait rather than sitting silent for up to two minutes.
      estimate = await indexingApi.estimate(request, {
        // Only reached while warming: an insufficient sample throws instead of waiting.
        onWaiting: (pending) =>
          setIndexStatusText(
            `Preparing the estimator (about ${Math.max(
              1,
              Math.ceil(Number(pending.warmup_seconds_remaining ?? 0))
            )}s)…`
          ),
      });
    } catch (error) {
      setIndexError(`Index estimate failed: ${error instanceof Error ? error.message : 'unknown error'}`);
      return;
    } finally {
      setIndexStatusText('');
    }
    const cost = estimate.total_cost_usd ?? estimate.embedding_cost_usd;
    const proceed = await confirmDialog({
      title: 'Build indexes?',
      message: [
        `Index estimate for "${corpus.name}"`,
        `Files: ${estimate.total_files} (${estimate.skipped_large_files ?? 0} skipped as too large)`,
        `Estimated tokens: ${estimate.estimated_total_tokens.toLocaleString()} (${estimate.estimated_tokens_low.toLocaleString()}–${estimate.estimated_tokens_high.toLocaleString()})`,
        `Estimated chunks: ${estimate.estimated_total_chunks.toLocaleString()} (${estimate.estimated_chunks_low.toLocaleString()}–${estimate.estimated_chunks_high.toLocaleString()})`,
        `Measured by chunking ${estimate.sampled_files.toLocaleString()} sampled files, band ±${Math.round(estimate.estimate_relative_error * 100)}%`,
        `Embeddings: ${estimate.embedding_backend} (${estimate.embedding_provider || 'n/a'} / ${estimate.embedding_model || 'n/a'})${estimate.skip_dense ? ' — dense skipped' : ''}`,
        `Estimated cost: ${cost == null ? 'N/A' : `$${Number(cost).toFixed(4)}`}`,
        estimate.estimated_seconds_low != null && estimate.estimated_seconds_high != null
          ? `Estimated time: ${Math.round(Number(estimate.estimated_seconds_low))}–${Math.round(Number(estimate.estimated_seconds_high))} s`
          : 'Estimated time: N/A',
      ].join('\n'),
      confirmLabel: 'Build indexes',
    });
    if (!proceed) return;
    setIndexing(true);
    setIndexProgress(0);
    setIndexLog([]);
    setIndexStatusText('Starting…');
    try {
      await startAndStream(
        request,
        {
          terminalId: INDEX_TERMINAL_ID,
          onLine: (line) => setIndexLog((prev) => [...prev.slice(-199), line]),
          onProgress: (percent, message) => {
            setIndexProgress(Math.max(0, Math.min(100, percent)));
            if (message) setIndexStatusText(message);
          },
          onError: (error) => {
            setIndexing(false);
            setIndexError(error);
            setIndexStatusText('Indexing failed');
          },
          onComplete: (_status, stats) => {
            setIndexing(false);
            setIndexProgress(100);
            setIndexStats(stats);
            setIndexStatusText(
              stats ? `Indexed ${stats.total_files} files into ${stats.total_chunks} chunks` : 'Indexing complete'
            );
          },
          onCancelled: () => {
            setIndexing(false);
            setIndexStatusText('Indexing cancelled');
          },
        }
      );
    } catch (error) {
      setIndexing(false);
      setIndexError(error instanceof Error ? error.message : 'Failed to start indexing');
      setIndexStatusText('Indexing failed');
    }
  }, [corpus, startAndStream]);

  const handleAsk = useCallback(async () => {
    const message = question.trim();
    if (!message || !corpusId) return;
    setAsking(true);
    setAskError(null);
    setAnswer(null);
    try {
      const response = await fetch(api('chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          corpus_id: corpusId,
          sources: { corpus_ids: [corpusId] },
          conversation_id: conversationIdRef.current,
          stream: false,
        }),
      });
      const contentType = response.headers.get('content-type') || '';
      const payload: unknown = contentType.includes('application/json') ? await response.json() : await response.text();
      if (!response.ok) {
        const detail =
          typeof payload === 'object' && payload && 'detail' in payload
            ? (payload as { detail: unknown }).detail
            : payload;
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
      }
      setAnswer(payload as ChatResponse);
    } catch (error) {
      setAskError(error instanceof Error ? error.message : 'The question failed');
    } finally {
      setAsking(false);
    }
  }, [api, corpusId, question]);

  const handleNext = () => {
    if (step >= maxStep) {
      reset();
      navigate(corpusId ? `/chat?corpus=${encodeURIComponent(corpusId)}` : '/dashboard');
      return;
    }
    nextStep();
  };

  const indexed = Boolean(indexStats && (indexStats.total_chunks ?? 0) > 0);
  const canAdvance = step === 2 ? Boolean(corpus) : step === 3 ? indexed && !indexing : true;

  return (
    <div id="tab-start" className="tab-content">
      <div className="ob-container">
        <div className="ob-progress-dots" role="list" aria-label="Onboarding steps">
          {STEP_TITLES.map((title, idx) => {
            const s = idx + 1;
            const classes = ['ob-dot', s === step ? 'active' : '', s < step ? 'completed' : ''].filter(Boolean).join(' ');
            return (
              <span
                key={s}
                className={classes}
                data-step={String(s)}
                data-testid={`onboarding-dot-${s}`}
                role="button"
                tabIndex={0}
                title={title}
                aria-current={s === step ? 'step' : undefined}
                onClick={() => setStep(s)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setStep(s);
                }}
              >
                {s}
              </span>
            );
          })}
        </div>

        {step === 1 && (
          <div className="ob-step active" data-testid="onboarding-step-1">
            <div className="ob-main">
              <h2 className="ob-title">Welcome to ragweld</h2>
              <p className="ob-subtitle">
                API-first retrieval and agent workflows with versioned config, prompts, and executable specs.
              </p>
              <div className="ob-info-box">
                <p>
                  In the next three steps you will register a folder as a corpus, build its indexes (Postgres chunk rows,
                  Qdrant dense + sparse vectors, Neo4j graph), and ask it a first grounded question with citations.
                </p>
                <p>
                  Everything runs against your local services; generation goes through the configured LiteLLM gateway
                  alias.
                </p>
              </div>
              <div className="ob-links">
                <h4>Where things live</h4>
                <div className="ob-link-grid">
                  <Link to="/rag?subtab=indexing">Indexing controls</Link>
                  <Link to="/rag?subtab=retrieval">Retrieval &amp; fusion</Link>
                  <Link to="/chat">Chat</Link>
                  <Link to="/eval?subtab=dataset">Eval dataset</Link>
                  <Link to="/admin?subtab=advanced">Every config field</Link>
                  <Link to="/infrastructure?subtab=mcp">MCP server</Link>
                </div>
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="ob-step active" data-testid="onboarding-step-2">
            <div className="ob-main">
              <h2 className="ob-title">Your corpus</h2>
              <p className="ob-subtitle">A corpus is any folder of documents or code that ragweld indexes and searches.</p>

              <div className="ob-input-group">
                <label htmlFor="onboarding-existing-corpus">Use an existing corpus</label>
                <select
                  id="onboarding-existing-corpus"
                  className="ob-text-input"
                  value={corpus ? corpus.corpus_id : ''}
                  onChange={(e) => void handlePickExisting(e.target.value)}
                  data-testid="onboarding-existing-corpus"
                >
                  <option value="">— pick one —</option>
                  {repos.map((r) => (
                    <option key={r.corpus_id} value={r.corpus_id}>
                      {r.name} ({r.corpus_id})
                    </option>
                  ))}
                </select>
              </div>

              <p className="ob-hint">Or register a new folder on this machine:</p>
              <div className="ob-input-group">
                <label htmlFor="onboarding-corpus-name">Corpus name</label>
                <input
                  id="onboarding-corpus-name"
                  type="text"
                  className="ob-text-input"
                  value={corpusName}
                  onChange={(e) => setCorpusName(e.target.value)}
                  placeholder="Aurora observatory runbooks"
                  data-testid="onboarding-corpus-name"
                />
              </div>
              <div className="ob-input-group">
                <label htmlFor="onboarding-corpus-path">Folder path</label>
                <input
                  id="onboarding-corpus-path"
                  type="text"
                  className="ob-text-input"
                  value={corpusPath}
                  onChange={(e) => setCorpusPath(e.target.value)}
                  placeholder="/path/to/your/documents"
                  data-testid="onboarding-corpus-path"
                />
                <p className="ob-hint">The API reads this path directly; it must be accessible from the machine running ragweld.</p>
              </div>
              <div className="ob-actions">
                <button
                  type="button"
                  className="ob-primary-btn"
                  onClick={() => void handleCreateCorpus()}
                  disabled={creating || !corpusName.trim() || !corpusPath.trim()}
                  data-testid="onboarding-create-corpus"
                >
                  {creating ? 'Creating…' : 'Create corpus'}
                </button>
              </div>
              {corpusError ? (
                <div className="ob-warning-box" role="alert" data-testid="onboarding-corpus-error">
                  {corpusError}
                </div>
              ) : null}
              {corpus ? (
                <div className="ob-info-box" data-testid="onboarding-corpus-summary">
                  Active corpus: <strong>{corpus.name}</strong> (<code>{corpus.corpus_id}</code>) at <code>{corpus.path}</code>
                  {indexed ? ` — already indexed (${indexStats?.total_chunks} chunks)` : ' — not indexed yet'}
                </div>
              ) : null}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="ob-step active" data-testid="onboarding-step-3">
            <div className="ob-main">
              <h2 className="ob-title">Build indexes</h2>
              {!corpus ? (
                <div className="ob-warning-box">Pick or create a corpus in the previous step first.</div>
              ) : (
                <>
                  <p className="ob-subtitle">
                    Index <strong>{corpus.name}</strong>: chunk the files, embed them, and write the Postgres, Qdrant and
                    Neo4j legs. Runs stage into a fresh generation and promote atomically when complete.
                  </p>
                  {indexed && !indexing ? (
                    <div className="ob-info-box" data-testid="onboarding-index-summary">
                      This corpus already has {indexStats?.total_chunks} {indexStats?.total_chunks === 1 ? 'chunk' : 'chunks'} from {indexStats?.total_files} {indexStats?.total_files === 1 ? 'file' : 'files'}
                      {indexStats?.last_indexed ? ` (last indexed ${new Date(indexStats.last_indexed).toLocaleString()})` : ''}.
                      You can continue, or rebuild it.
                    </div>
                  ) : null}
                  <div className="ob-actions">
                    <button
                      type="button"
                      className="ob-primary-btn"
                      onClick={() => void handleStartIndex()}
                      disabled={indexing}
                      data-testid="onboarding-index-start"
                    >
                      {indexing ? 'Indexing…' : indexed ? 'Rebuild indexes' : 'Build indexes'}
                    </button>
                  </div>
                  <div className="ob-progress-bar">
                    <div className="ob-progress-fill" style={{ width: `${indexProgress}%` }} data-testid="onboarding-index-bar" />
                  </div>
                  <div className="ob-progress-text" data-testid="onboarding-index-status">
                    {indexStatusText}
                  </div>
                  <div className="ob-log" ref={logRef} data-testid="onboarding-index-log">
                    {indexLog.map((line, idx) => (
                      <div key={`${idx}-${line.slice(0, 24)}`}>{line}</div>
                    ))}
                  </div>
                  {indexError ? (
                    <div className="ob-warning-box" role="alert" data-testid="onboarding-index-error">
                      {indexError}
                    </div>
                  ) : null}
                </>
              )}
            </div>
          </div>
        )}

        {step === 4 && (
          <div className="ob-step active" data-testid="onboarding-step-4">
            <div className="ob-main">
              <h2 className="ob-title">Ask your first question</h2>
              {!corpus || !indexed ? (
                <div className="ob-warning-box">Build the indexes in the previous step first.</div>
              ) : (
                <>
                  <p className="ob-subtitle">
                    Ask something a reader of <strong>{corpus.name}</strong> would ask. The answer is retrieved from the
                    corpus and cited; every real question also feeds the reranker training signal.
                  </p>
                  <div className="ob-question-item">
                    <input
                      type="text"
                      className="ob-question-input"
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && question.trim() && !asking) void handleAsk();
                      }}
                      placeholder="What does this corpus say about…?"
                      aria-label="Your first question"
                      data-testid="onboarding-question"
                    />
                    <button
                      type="button"
                      className="ob-ask-btn"
                      onClick={() => void handleAsk()}
                      disabled={asking || !question.trim()}
                      data-testid="onboarding-ask"
                    >
                      {asking ? 'Asking…' : 'Ask'}
                    </button>
                  </div>
                  {askError ? (
                    <div className="ob-warning-box" role="alert" data-testid="onboarding-ask-error">
                      {askError}
                    </div>
                  ) : null}
                  {answer ? (
                    <div className="ob-answer visible" data-testid="onboarding-answer">
                      <AssistantMarkdown content={answer.message.content} />
                      {answer.sources.length > 0 ? (
                        <div className="ob-hint" data-testid="onboarding-citations" style={{ marginTop: 10 }}>
                          Sources:{' '}
                          {answer.sources.slice(0, 5).map((m, idx) => (
                            <code key={`${m.chunk_id}-${idx}`} style={{ marginRight: 8 }}>
                              {formatCitation(m)}
                            </code>
                          ))}
                        </div>
                      ) : (
                        <div className="ob-hint" style={{ marginTop: 10 }}>
                          No corpus chunks were retrieved for this question.
                        </div>
                      )}
                    </div>
                  ) : null}
                  <div className="ob-actions">
                    <a
                      href={`/chat?corpus=${encodeURIComponent(corpus.corpus_id)}`}
                      className="ob-help-link"
                      onClick={(e) => {
                        e.preventDefault();
                        navigate(`/chat?corpus=${encodeURIComponent(corpus.corpus_id)}`);
                      }}
                      data-testid="onboarding-open-chat"
                    >
                      Open full Chat →
                    </a>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

        <div className="ob-footer">
          <button
            id="onboard-back"
            className="ob-nav-btn"
            data-testid="onboarding-back"
            style={{ display: step === 1 ? 'none' : 'block' }}
            onClick={prevStep}
          >
            ← Back
          </button>
          <button
            id="onboard-next"
            className="ob-nav-btn ob-nav-primary"
            data-testid="onboarding-next"
            onClick={handleNext}
            disabled={!canAdvance}
            title={!canAdvance ? (step === 2 ? 'Pick or create a corpus first' : 'Build the indexes first') : undefined}
          >
            {step === maxStep ? 'Done' : 'Next →'}
          </button>
        </div>
      </div>
    </div>
  );
}
