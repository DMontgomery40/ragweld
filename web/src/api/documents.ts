/**
 * Source document evidence viewer API.
 *
 * Wire types come from generated.ts; this module only builds URLs and maps typed error details.
 */
import axios from 'axios';
import { apiClient, apiUrl } from '@/api/client';
import type {
  DocumentNotCapturedDetail,
  DocumentTooLargeDetail,
  DocumentView,
} from '@/types/generated';

export type PageVariant = 'page' | 'thumb';

function documentsBase(corpusId: string): string {
  return `/corpora/${encodeURIComponent(corpusId)}/documents`;
}

export async function getDocumentView(corpusId: string, path: string): Promise<DocumentView> {
  const res = await apiClient.get<DocumentView>(`${documentsBase(corpusId)}/view`, {
    params: { path },
  });
  return res.data;
}

export function documentPageUrl(
  corpusId: string,
  path: string,
  page: number,
  variant: PageVariant = 'page',
): string {
  const query = new URLSearchParams({ path, page: String(page), variant });
  return apiUrl(`${documentsBase(corpusId)}/page?${query.toString()}`);
}

export function documentRawUrl(corpusId: string, path: string): string {
  const query = new URLSearchParams({ path });
  return apiUrl(`${documentsBase(corpusId)}/raw?${query.toString()}`);
}

/** Local view model for a failed document fetch (typed 409/413/503 details or plain HTTP errors). */
export type DocumentViewError = {
  status: number;
  code: 'document_not_captured' | 'document_too_large' | 'dependency_unavailable' | 'unauthenticated' | 'http';
  message: string;
  operatorHint: string | null;
};

type TypedDetail = DocumentNotCapturedDetail | DocumentTooLargeDetail | Record<string, unknown>;

export function toDocumentViewError(err: unknown): DocumentViewError {
  if (axios.isAxiosError(err)) {
    const status = Number(err.response?.status ?? 0);
    if (status === 401 || status === 403) {
      // The auth proxy in front of the API refused the request: the sign-in session ended
      // (for example after a service restart). Nothing about the document is wrong.
      return {
        status,
        code: 'unauthenticated',
        message: 'Your sign-in session has ended, so the document could not be fetched.',
        operatorHint: 'Reload the page to sign in again, then reopen the citation.',
      };
    }
    const data = err.response?.data as { detail?: TypedDetail | string } | undefined;
    const detail = data?.detail;
    if (detail && typeof detail === 'object') {
      const code = String((detail as { code?: unknown }).code ?? '');
      const message = String((detail as { message?: unknown }).message ?? err.message);
      const hint = (detail as { operator_hint?: unknown }).operator_hint;
      if (code === 'document_not_captured' || code === 'document_too_large' || code === 'dependency_unavailable') {
        return { status, code, message, operatorHint: typeof hint === 'string' ? hint : null };
      }
      return { status, code: 'http', message, operatorHint: typeof hint === 'string' ? hint : null };
    }
    if (typeof detail === 'string') {
      return { status, code: 'http', message: detail, operatorHint: null };
    }
    return { status, code: 'http', message: err.message, operatorHint: null };
  }
  return { status: 0, code: 'http', message: err instanceof Error ? err.message : String(err), operatorHint: null };
}
