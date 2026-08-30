import { useNavigate } from 'react-router-dom';
import { EmbeddingMismatchWarning } from './ui/EmbeddingMismatchWarning';

/**
 * Settings-rail panel.
 *
 * The rail used to carry a "Quick Model Switcher" - a second copy of the
 * generation / embedding / reranker model assignment with its own "Apply Changes"
 * button, so one screen showed two apply controls with no statement of what each
 * committed. Model assignment lives in exactly one place now (RAG > Retrieval); the
 * rail links out to it instead of duplicating it.
 */
export function Sidepanel() {
  const navigate = useNavigate();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: '16px' }}>
      {/* Embedding Mismatch Warning - Critical visibility */}
      <EmbeddingMismatchWarning variant="inline" showActions={true} />

      <div
        data-testid="sidepanel-model-assignments-link"
        style={{
          background: 'var(--card-bg)',
          border: '1px solid var(--line)',
          borderRadius: '8px',
          padding: '16px',
        }}
      >
        <div style={{ fontSize: '14px', fontWeight: 600, color: 'var(--fg)', marginBottom: '10px' }}>
          Model assignments
        </div>
        <p style={{ fontSize: '13px', color: 'var(--fg-muted)', lineHeight: 1.5, margin: '0 0 12px' }}>
          Generation, embedding and reranker models are chosen and applied on one
          surface: RAG › Retrieval. The rail no longer keeps a second copy with its
          own apply button.
        </p>
        <button
          type="button"
          data-testid="sidepanel-open-model-assignments"
          onClick={() => navigate('/rag?subtab=retrieval')}
          style={{
            width: '100%',
            background: 'var(--accent)',
            color: 'var(--accent-contrast)',
            border: 'none',
            padding: '12px',
            borderRadius: '6px',
            fontWeight: 700,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          Open model assignments
        </button>
      </div>
    </div>
  );
}
