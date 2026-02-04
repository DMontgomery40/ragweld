import { QuestionManager } from './QuestionManager';
import { RepoSelector } from '@/components/RAG/RepoSelector';

export function EvalDatasetSubtab() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <div style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        padding: '16px 20px',
      }}>
        <h2 style={{ margin: 0, fontSize: '16px', fontWeight: 700, color: 'var(--fg)' }}>Eval Dataset</h2>
        <p style={{ margin: '6px 0 0', fontSize: '12px', color: 'var(--fg-muted)' }}>
          Manage eval questions for the selected corpus.
        </p>
        <div style={{ marginTop: '12px' }}>
          <RepoSelector label="Corpus" />
        </div>
      </div>

      <QuestionManager />
    </div>
  );
}
