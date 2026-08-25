import { useCallback, useEffect, useRef, useState } from 'react';
import { evalApi } from '@/api/eval';
import { CollapsibleSection } from '@/components/ui/CollapsibleSection';
import type { PromptfooRun, PromptfooRunResult } from '@/types/generated';

// After a transport-level launch failure the server-side promptfoo run may
// still be executing; poll this often, for at most this long, so a recorded
// run never stays hidden until the next visit.
const RECOVERY_POLL_INTERVAL_MS = 15_000;
const RECOVERY_POLL_MAX_MS = 30 * 60_000;

type Props = {
  corpusId: string;
};

type StructuredDetail = {
  code?: string;
  dependency?: string;
  message?: string;
  operator_hint?: string;
};

function readDetail(error: unknown): StructuredDetail | null {
  const response = (error as { response?: { data?: { detail?: unknown } } })?.response;
  const detail = response?.data?.detail;
  if (detail && typeof detail === 'object') return detail as StructuredDetail;
  return null;
}

export function PromptfooRegressionPanel({ corpusId }: Props) {
  const [runs, setRuns] = useState<PromptfooRun[]>([]);
  const [running, setRunning] = useState(false);
  const [sampleSize, setSampleSize] = useState<string>('25');
  const [failure, setFailure] = useState<StructuredDetail | null>(null);
  const [plainError, setPlainError] = useState<string | null>(null);

  // The panel does not remount on corpus switch: a slow response for the old
  // corpus must never overwrite the new corpus's list.
  const activeCorpusRef = useRef(corpusId);
  useEffect(() => {
    activeCorpusRef.current = corpusId;
  }, [corpusId]);
  const recoveryPollRef = useRef<number | null>(null);

  const refresh = useCallback(async (): Promise<PromptfooRun[]> => {
    if (!corpusId) return [];
    try {
      const data = await evalApi.listPromptfooRuns(corpusId);
      const next = data.runs || [];
      if (activeCorpusRef.current === corpusId) setRuns(next);
      return next;
    } catch (error) {
      if (activeCorpusRef.current === corpusId) {
        setPlainError(error instanceof Error ? error.message : 'Failed to load Promptfoo runs');
      }
      return [];
    }
  }, [corpusId]);

  const stopRecoveryPoll = useCallback(() => {
    if (recoveryPollRef.current !== null) {
      window.clearInterval(recoveryPollRef.current);
      recoveryPollRef.current = null;
    }
  }, []);

  const startRecoveryPoll = useCallback(
    (lastKnownRunId: string | null) => {
      stopRecoveryPoll();
      const startedAt = Date.now();
      const pollCorpus = corpusId;
      recoveryPollRef.current = window.setInterval(() => {
        if (activeCorpusRef.current !== pollCorpus || Date.now() - startedAt > RECOVERY_POLL_MAX_MS) {
          stopRecoveryPoll();
          return;
        }
        void refresh().then((next) => {
          if (next.length && next[0].run_id !== lastKnownRunId) {
            stopRecoveryPoll();
            if (activeCorpusRef.current === pollCorpus) setPlainError(null);
          }
        });
      }, RECOVERY_POLL_INTERVAL_MS);
    },
    [corpusId, refresh, stopRecoveryPoll],
  );

  useEffect(() => {
    void refresh();
    return stopRecoveryPoll;
  }, [refresh, stopRecoveryPoll]);

  const launch = async () => {
    setRunning(true);
    setFailure(null);
    setPlainError(null);
    const lastKnownRunId = runs[0]?.run_id ?? null;
    try {
      await evalApi.runPromptfoo({
        corpus_id: corpusId,
        sample_size: sampleSize ? parseInt(sampleSize, 10) : undefined,
      });
    } catch (error) {
      const detail = readDetail(error);
      if (detail) {
        setFailure(detail);
      } else {
        // Transport-level failure: the server-side run may still be executing
        // and will be saved when it finishes — keep polling so the recorded
        // run never stays hidden until the next visit.
        setPlainError(error instanceof Error ? error.message : 'Promptfoo run failed');
        startRecoveryPoll(lastKnownRunId);
      }
    } finally {
      await refresh();
      setRunning(false);
    }
  };

  const latest = runs[0];

  return (
    <section
      data-testid="promptfoo-regression-panel"
      style={{
        margin: '16px 24px',
        padding: '16px',
        border: '1px solid var(--line)',
        borderRadius: '10px',
        background: 'var(--bg-elev1)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '14px', fontWeight: 700, color: 'var(--fg)' }}>Promptfoo regression</div>
          <div style={{ fontSize: '12px', color: 'var(--fg-muted)', marginTop: '4px' }}>
            Answers sampled eval entries with an expected answer through the LiteLLM gateway and grades each with an
            llm-rubric assertion. Runs execute the real promptfoo CLI; nothing is simulated.
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
          <label
            htmlFor="promptfoo-sample-size"
            style={{ fontSize: '12px', color: 'var(--fg-muted)' }}
          >
            Sample size
          </label>
          <select
            id="promptfoo-sample-size"
            data-testid="promptfoo-sample-size"
            value={sampleSize}
            disabled={running}
            onChange={(e) => setSampleSize(e.target.value)}
            style={{
              background: 'var(--input-bg)',
              border: '1px solid var(--line)',
              color: 'var(--fg)',
              padding: '8px 10px',
              borderRadius: '8px',
              fontSize: '12.5px',
              cursor: running ? 'not-allowed' : 'pointer',
            }}
          >
            <option value="10">10 entries</option>
            <option value="25">25 entries</option>
            <option value="50">50 entries</option>
            <option value="100">100 entries</option>
            <option value="">All entries (full dataset)</option>
          </select>
          <button type="button" className="small-button" onClick={() => void launch()} disabled={running || !corpusId}>
            {running ? 'Running promptfoo…' : 'Run Promptfoo regression'}
          </button>
        </div>
      </div>
      {!sampleSize ? (
        <div style={{ marginTop: '8px', fontSize: '12px', color: 'var(--warn, var(--fg-muted))' }}>
          Full-dataset runs answer and grade every entry with an expected answer — expect a long run and real LLM cost.
        </div>
      ) : null}

      {failure ? (
        <div
          data-testid="promptfoo-failure-card"
          style={{
            marginTop: '12px',
            padding: '10px 12px',
            borderRadius: '8px',
            background: 'rgba(214, 79, 79, 0.12)',
            border: '1px solid rgba(214, 79, 79, 0.4)',
            fontSize: '12.5px',
          }}
        >
          <div style={{ fontFamily: 'var(--font-mono, monospace)', fontWeight: 700, color: 'var(--err)' }}>
            {failure.code || 'error'} {failure.dependency ? `· ${failure.dependency}` : ''}
          </div>
          {failure.message ? <div style={{ marginTop: '4px' }}>{failure.message}</div> : null}
          {failure.operator_hint ? (
            <div style={{ marginTop: '4px', color: 'var(--fg-muted)' }}>{failure.operator_hint}</div>
          ) : null}
        </div>
      ) : null}
      {plainError ? <div style={{ marginTop: '12px', color: 'var(--err)', fontSize: '12.5px' }}>{plainError}</div> : null}

      {latest ? (
        <div style={{ marginTop: '14px' }}>
          <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--fg-muted)' }}>
            <span>
              latest <code>{latest.run_id}</code>
            </span>
            <span>
              passed <strong style={{ color: 'var(--ok)' }}>{latest.passed}</strong> / {latest.total}
            </span>
            <span>
              failed <strong style={{ color: latest.failed ? 'var(--err)' : 'var(--fg)' }}>{latest.failed}</strong>
            </span>
            <span>skipped (no expected_answer) {latest.skipped_entries}</span>
            <span>
              provider {latest.provider_alias} · grader {latest.grader_alias} · promptfoo {latest.promptfoo_version}
            </span>
          </div>
          <div style={{ marginTop: '12px' }}>
            <CollapsibleSection
              title={`Run results (${(latest.results as PromptfooRunResult[]).length})`}
              description="Per-entry verdicts. Expand a card for the generated answer and the grader's reasoning."
              defaultExpanded={false}
              storageKey="promptfoo_run_results"
            >
              {(() => {
                const results = latest.results as PromptfooRunResult[];
                const failed = results.filter((r) => !r.passed);
                const passed = results.filter((r) => r.passed);
                const renderCard = (result: PromptfooRunResult) => (
                  <details
                    key={result.entry_id}
                    data-testid="promptfoo-result-card"
                    style={{
                      borderRadius: '8px',
                      border: '1px solid var(--line)',
                      background: 'var(--bg)',
                      fontSize: '12.5px',
                    }}
                  >
                    <summary
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'baseline',
                        gap: '12px',
                        padding: '10px 12px',
                        cursor: 'pointer',
                        listStyle: 'none',
                      }}
                    >
                      <span style={{ minWidth: 0 }}>
                        <strong style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '11.5px' }}>
                          {result.entry_id}
                        </strong>
                        <span
                          style={{
                            display: 'block',
                            color: 'var(--fg-muted)',
                            marginTop: '2px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                        >
                          {result.question}
                        </span>
                      </span>
                      <span
                        style={{
                          color: result.passed ? 'var(--ok)' : 'var(--err)',
                          fontWeight: 700,
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {result.passed ? 'PASS' : 'FAIL'} · {result.score.toFixed(2)}
                      </span>
                    </summary>
                    <div style={{ padding: '0 12px 10px', borderTop: '1px solid var(--line)' }}>
                      <div style={{ color: 'var(--fg-muted)', marginTop: '8px' }}>{result.question}</div>
                      {result.response ? (
                        <div style={{ marginTop: '6px', whiteSpace: 'pre-wrap' }}>
                          {result.response.split('</think>').pop()?.trim()}
                        </div>
                      ) : null}
                      {result.reason ? (
                        <div style={{ marginTop: '6px', fontSize: '11.5px', color: 'var(--fg-muted)' }}>
                          grader: {result.reason}
                        </div>
                      ) : null}
                    </div>
                  </details>
                );
                const groupSummaryStyle = {
                  cursor: 'pointer',
                  fontSize: '12.5px',
                  fontWeight: 700,
                  padding: '6px 2px',
                } as const;
                return (
                  <div style={{ display: 'grid', gap: '10px' }}>
                    {failed.length > 0 ? (
                      <details open data-testid="promptfoo-failed-group">
                        <summary style={{ ...groupSummaryStyle, color: 'var(--err)' }}>
                          Failed ({failed.length})
                        </summary>
                        <div style={{ display: 'grid', gap: '8px', marginTop: '6px' }}>{failed.map(renderCard)}</div>
                      </details>
                    ) : null}
                    <details data-testid="promptfoo-passed-group">
                      <summary style={{ ...groupSummaryStyle, color: 'var(--ok)' }}>
                        Passed ({passed.length})
                      </summary>
                      <div style={{ display: 'grid', gap: '8px', marginTop: '6px' }}>{passed.map(renderCard)}</div>
                    </details>
                  </div>
                );
              })()}
            </CollapsibleSection>
          </div>
        </div>
      ) : (
        <div style={{ marginTop: '12px', fontSize: '12px', color: 'var(--fg-muted)' }}>
          No Promptfoo runs recorded for this corpus yet.
        </div>
      )}
    </section>
  );
}
