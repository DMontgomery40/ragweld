import { useEffect, useState } from 'react';
import { getDocumentView, toDocumentViewError } from '@/api/documents';
import type { DocumentViewError } from '@/api/documents';
import type { DocumentView } from '@/types/generated';

export type DocumentViewState =
  | { status: 'loading' }
  | { status: 'ready'; view: DocumentView }
  | { status: 'error'; error: DocumentViewError };

export function useDocumentView(corpusId: string, path: string): DocumentViewState {
  const [state, setState] = useState<DocumentViewState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading' });
    getDocumentView(corpusId, path)
      .then((view) => {
        if (!cancelled) setState({ status: 'ready', view });
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: 'error', error: toDocumentViewError(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [corpusId, path]);

  return state;
}
