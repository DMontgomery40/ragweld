import { documentRawUrl } from '@/api/documents';
import { MarkdownView } from '@/components/Documents/MarkdownView';
import { PdfPageView } from '@/components/Documents/PdfPageView';
import { TextView } from '@/components/Documents/TextView';
import { charSpanOf, formatSourceLocation } from '@/components/Documents/sourceLabels';
import { useDocumentView } from '@/components/Documents/useDocumentView';
import { useRepoStore } from '@/stores/useRepoStore';
import type { DocumentTarget } from '@/stores/useDockStore';
import type { DocumentView } from '@/types/generated';

const badge = (tone: 'neutral' | 'warn'): React.CSSProperties => ({
  display: 'inline-block',
  padding: '2px 8px',
  borderRadius: '999px',
  fontSize: '11.5px',
  fontWeight: 700,
  letterSpacing: '0.02em',
  border: `1px solid ${tone === 'warn' ? '#d97706' : 'var(--line)'}`,
  color: tone === 'warn' ? '#fbbf24' : 'var(--fg)',
  background: tone === 'warn' ? 'rgba(217,119,6,0.16)' : 'var(--bg-elev2)',
});

function Notice({ testId, title, message, hint }: { testId: string; title: string; message: string; hint: string | null }) {
  return (
    <div
      data-testid={testId}
      role="status"
      style={{
        margin: '12px',
        padding: '12px 14px',
        border: '1px solid #d97706',
        borderRadius: 'var(--radius-lg)',
        background: 'rgba(217,119,6,0.12)',
        color: 'var(--fg)',
        fontSize: '13px',
        lineHeight: 1.5,
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: '4px' }}>{title}</div>
      <div>{message}</div>
      {hint ? <div style={{ marginTop: '6px', color: 'var(--fg-muted)' }}>{hint}</div> : null}
    </div>
  );
}

function ViewerBody({ view, target }: { view: DocumentView; target: DocumentTarget }) {
  const { corpusId, source } = target;
  const content = view.content;
  if (content.kind === 'text') {
    return <TextView text={content.text} startLine={source.start_line} endLine={source.end_line} />;
  }
  if (content.kind === 'pdf') {
    return (
      <PdfPageView
        corpusId={corpusId}
        path={source.file_path}
        pageCount={content.page_count}
        pageSizes={content.page_sizes}
        source={source}
      />
    );
  }
  if (content.kind === 'rich') {
    const span = charSpanOf(source);
    return <MarkdownView markdown={content.markdown} charStart={span?.start ?? null} charEnd={span?.end ?? null} />;
  }
  // The generated discriminant is optional (Pydantic default), so TypeScript cannot prove
  // exhaustiveness; the API always sets it, and an unknown kind is a contract error.
  return (
    <Notice
      testId="document-view-error"
      title="Unsupported document kind"
      message={`The API returned a document kind this viewer does not render: ${String(content.kind)}`}
      hint={null}
    />
  );
}

/** The right-rail evidence viewer for one citation: header, provenance state, and the typed body. */
export function DocumentViewer({ target }: { target: DocumentTarget }) {
  const { corpusId, source } = target;
  const state = useDocumentView(corpusId, source.file_path);
  const repos = useRepoStore((s) => s.repos);
  const corpusName = repos.find((r) => r.corpus_id === corpusId)?.name || corpusId;
  const fileName = source.file_path.split('/').pop() || source.file_path;

  return (
    <div data-testid="document-viewer" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--line)', display: 'grid', gap: '6px' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', flexWrap: 'wrap' }}>
          <span data-testid="document-viewer-title" title={source.file_path} style={{ fontSize: '14px', fontWeight: 700, color: 'var(--fg)' }}>
            {fileName}
          </span>
          <span style={{ fontSize: '12.5px', color: 'var(--fg-muted)' }}>{formatSourceLocation(source)}</span>
          <a
            href={documentRawUrl(corpusId, source.file_path)}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="document-open-original"
            style={{ marginLeft: 'auto', fontSize: '12.5px', color: 'var(--link)', textDecoration: 'none', fontWeight: 600 }}
          >
            Open original ↗
          </a>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', fontSize: '12px', color: 'var(--fg-muted)' }}>
          <span title={source.file_path} style={{ fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '100%' }}>
            {corpusName} / {source.file_path}
          </span>
          {state.status === 'ready' ? <span style={badge('neutral')}>{state.view.content.kind}</span> : null}
          {state.status === 'ready' && state.view.provenance.state === 'captured' && state.view.provenance.stale ? (
            <span data-testid="document-stale-badge" style={badge('warn')} title="The file on disk changed after it was indexed; highlights may be offset.">
              changed since indexing
            </span>
          ) : null}
        </div>
      </div>

      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {state.status === 'loading' ? (
          <div data-testid="document-loading" style={{ padding: '16px', fontSize: '13px', color: 'var(--fg-muted)' }}>
            Loading {fileName}…
          </div>
        ) : state.status === 'error' ? (
          <Notice
            testId="document-view-error"
            title={
              state.error.code === 'document_not_captured'
                ? 'Document not captured'
                : state.error.code === 'document_too_large'
                  ? 'Document too large to display'
                  : state.error.code === 'dependency_unavailable'
                    ? 'Store unavailable'
                    : `Could not load document (HTTP ${state.error.status || 'error'})`
            }
            message={state.error.message}
            hint={state.error.operatorHint}
          />
        ) : (
          <>
            {state.view.provenance.state === 'not_captured' ? (
              <Notice
                testId="document-provenance-not-captured"
                title="Indexed before page provenance"
                message={state.view.provenance.message}
                hint={state.view.provenance.operator_hint}
              />
            ) : null}
            <div style={{ flex: '1 1 auto', minHeight: 0 }}>
              <ViewerBody view={state.view} target={target} />
            </div>
          </>
        )}
      </div>
    </div>
  );
}
