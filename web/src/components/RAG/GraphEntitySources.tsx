import { useEffect, useRef, useState } from 'react';
import { getEntitySources } from '@/api/graph';
import { toDocumentViewError } from '@/api/documents';
import { formatSourceLocation } from '@/components/Documents/sourceLabels';
import { useDockStore } from '@/stores/useDockStore';
import type { GraphEntitySourcesResponse } from '@/types/generated';

/** A mounted instance belongs to one corpus/entity; the caller keys it by that identity. */
export function GraphEntitySources({ corpusId, entityId }: { corpusId: string; entityId: string }) {
  const [page, setPage] = useState<GraphEntitySourcesResponse | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const openDocument = useDockStore((state) => state.openDocument);

  useEffect(() => {
    const abort = new AbortController();
    controller.current = abort;
    setPage(null);
    setPending(true);
    setError(null);
    getEntitySources(corpusId, entityId, { signal: abort.signal })
      .then((result) => { if (!abort.signal.aborted) setPage(result); })
      .catch((reason) => { if (!abort.signal.aborted) setError(toDocumentViewError(reason).message); })
      .finally(() => { if (!abort.signal.aborted) setPending(false); });
    return () => controller.current?.abort();
  }, [corpusId, entityId, retryNonce]);

  async function loadMore() {
    if (!page || page.next_offset == null || pending) return;
    const abort = new AbortController();
    controller.current = abort;
    setPending(true);
    setError(null);
    try {
      const result = await getEntitySources(corpusId, entityId, {
        offset: page.next_offset, runId: page.run_id, signal: abort.signal,
      });
      if (!abort.signal.aborted) setPage({ ...result, sources: [...page.sources, ...result.sources] });
    } catch (reason) {
      if (!abort.signal.aborted) {
        const failure = toDocumentViewError(reason);
        if (failure.status === 409) setPage(null);
        setError(failure.message);
      }
    } finally {
      if (!abort.signal.aborted) setPending(false);
    }
  }

  return (
    <section data-testid="graph-entity-sources" aria-label="Entity source mentions" style={{ marginTop: '14px', fontSize: '12px' }}>
      <strong>Source mentions</strong>
      <p style={{ color: 'var(--fg-muted)', margin: '6px 0' }}>
        Source chunks for this entity. A mention alone does not verify a relationship.
      </p>
      {page?.sources.map((source) => (
        <div key={source.chunk_id} style={{ borderTop: '1px solid var(--line)', padding: '8px 0' }}>
          <button
            type="button"
            data-testid="graph-source-open"
            onClick={() => openDocument({ corpusId, source })}
            style={{ color: 'var(--link)', background: 'transparent', border: 0, padding: 0, cursor: 'pointer', textAlign: 'left' }}
          >
            Open {source.file_path} · {formatSourceLocation(source)}
          </button>
          <div style={{ color: 'var(--fg-muted)', marginTop: '4px', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
            {source.content.slice(0, 300)}{source.content.length > 300 ? '…' : ''}
          </div>
        </div>
      ))}
      {pending ? <p role="status">Loading source mentions…</p> : null}
      {error ? (
        <div><p role="alert">{error}</p><button type="button" onClick={() => setRetryNonce((value) => value + 1)}>Reload sources</button></div>
      ) : null}
      {!pending && !error && page?.sources.length === 0 ? <p>No source chunks were recorded for this entity.</p> : null}
      {page?.next_offset != null ? (
        <button type="button" disabled={pending} onClick={() => void loadMore()}>Load more sources</button>
      ) : null}
    </section>
  );
}
