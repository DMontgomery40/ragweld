import { useCallback, useEffect, useState } from 'react';
import { evalApi } from '@/api/eval';
import type { PromptfooRun, PromptfooRunResult } from '@/types/generated';

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
  const [failure, setFailure] = useState<StructuredDetail | null>(null);
  const [plainError, setPlainError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!corpusId) return;
    try {
      const data = await evalApi.listPromptfooRuns(corpusId);
      setRuns(data.runs || []);
    } catch (error) {
      setPlainError(error instanceof Error ? error.message : 'Failed to load Promptfoo runs');
    }
  }, [corpusId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const launch = async () => {
    setRunning(true);
    setFailure(null);
    setPlainError(null);
    try {
      await evalApi.runPromptfoo({ corpus_id: corpusId });
      await refresh();
    } catch (error) {
      const detail = readDetail(error);
      if (detail) setFailure(detail);
      else setPlainError(error instanceof Error ? error.message : 'Promptfoo run failed');
    } finally {
      setRunning(false);
    }
  };

  const latest = runs[0];

  return (
    <section
      data-testid="promptfoo-regression-panel"
      style={{
        margin: '0 24px 16px',
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
            Answers every eval entry with an expected answer through the LiteLLM gateway and grades it with an
            llm-rubric assertion. Runs execute the real promptfoo CLI; nothing is simulated.
          </div>
        </div>
        <button type="button" className="small-button" onClick={() => void launch()} disabled={running || !corpusId}>
          {running ? 'Running promptfoo…' : 'Run Promptfoo regression'}
        </button>
      </div>

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
          <div style={{ marginTop: '10px', display: 'grid', gap: '8px' }}>
            {(latest.results as PromptfooRunResult[]).map((result: PromptfooRunResult) => (
              <div
                key={result.entry_id}
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  border: '1px solid var(--line)',
                  background: 'var(--bg)',
                  fontSize: '12.5px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px' }}>
                  <strong>{result.entry_id}</strong>
                  <span style={{ color: result.passed ? 'var(--ok)' : 'var(--err)', fontWeight: 700 }}>
                    {result.passed ? 'PASS' : 'FAIL'} · {result.score.toFixed(2)}
                  </span>
                </div>
                <div style={{ color: 'var(--fg-muted)', marginTop: '4px' }}>{result.question}</div>
                {result.response ? (
                  <div style={{ marginTop: '6px', whiteSpace: 'pre-wrap' }}>{result.response.split('</think>').pop()?.trim()}</div>
                ) : null}
                {result.reason ? (
                  <div style={{ marginTop: '6px', fontSize: '11.5px', color: 'var(--fg-muted)' }}>grader: {result.reason}</div>
                ) : null}
              </div>
            ))}
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
