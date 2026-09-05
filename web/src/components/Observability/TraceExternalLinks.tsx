import { useEffect, useState } from 'react';

import * as DashAPI from '@/api/dashboard';
import type { LangfuseTraceAccess, TraceExternalLink } from '@/types/generated';

type Props = {
  links: TraceExternalLink[] | null | undefined;
  /** Canonical trace id these links belong to; enables the Langfuse existence check. */
  traceId?: string | null;
};

type AccessCheck = {
  traceId: string;
  access: LangfuseTraceAccess | null;
  error: string | null;
  pending: boolean;
};

// Six sequential checks over about half a minute cover normal asynchronous ingestion.
// A terminal failure or exhausted schedule stays explicit and can be retried by the user.
const INGESTION_RETRY_DELAYS_MS = [1000, 2000, 4000, 8000, 16000];

function isLangfuseTraceLink(link: TraceExternalLink): boolean {
  return link.kind === 'langfuse' && String(link.url || '').includes('/traces/');
}

/**
 * The external-link row for one trace, shared by every surface that shows one.
 *
 * M-16: "Langfuse trace" dead-ended on Langfuse's own "You do not have access to
 * this trace" from Chat and from Eval. Two things have to travel with the link
 * and previously did not: the API's check that Langfuse actually holds the
 * trace, and the fact that opening it needs a Langfuse account with membership
 * of the project - which no server-side check can stand in for, so it is stated
 * rather than assumed. Both live here so the Chat and Eval renderers stay a
 * one-line swap instead of each growing their own copy.
 */
export function TraceExternalLinks({ links, traceId }: Props) {
  const [check, setCheck] = useState<AccessCheck | null>(null);
  const [retry, setRetry] = useState(0);
  const id = String(traceId || '').trim();
  const hasLangfuseLink = (links || []).some(isLangfuseTraceLink);
  // Never grant the new trace access during the render before its effect runs.
  const currentCheck = check?.traceId === id ? check : null;
  const access = currentCheck?.access ?? null;
  const accessError = currentCheck?.error ?? null;
  const pending = Boolean(id && hasLangfuseLink && (currentCheck === null || currentCheck.pending));

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let attempt = 0;
    if (!id || !hasLangfuseLink) {
      setCheck(null);
      return;
    }
    setCheck({ traceId: id, access: null, error: null, pending: true });
    const checkAccess = async () => {
      try {
        const next = await DashAPI.getLangfuseTraceAccess(id);
        if (cancelled) return;
        const delay = next?.checked && !next.exists ? INGESTION_RETRY_DELAYS_MS[attempt++] : undefined;
        setCheck({ traceId: id, access: next, error: null, pending: delay !== undefined });
        if (delay !== undefined) {
          timer = window.setTimeout(() => { void checkAccess(); }, delay);
        }
      } catch (error: unknown) {
        if (cancelled) return;
        // The check failing is not the same as Langfuse saying no; say which.
        setCheck({
          traceId: id, access: null, pending: false,
          error: error instanceof Error ? error.message : 'the check did not complete',
        });
      }
    };
    void checkAccess();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [hasLangfuseLink, id, retry]);

  const visible = (links || []).filter(
    (link) => !isLangfuseTraceLink(link) || access?.exists === true
  );
  const withheld = hasLangfuseLink && !pending && access !== null && !access.exists;

  if (!visible.length && !withheld && !accessError && !pending) return null;

  return (
    <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {visible.map((link, index) => (
          <a
            key={`${link.url}-${index}`}
            href={link.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid={`trace-external-link-${link.kind}`}
            title={
              link.kind === 'langfuse' && access
                ? access.sign_in_hint
                : `${link.detail ? `${link.detail} ` : ''}Opens ${link.url} in a new tab.`
            }
            style={{
              fontSize: '11.5px',
              color: 'var(--accent-text)',
              textDecoration: 'none',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              padding: '4px 8px',
              background: 'var(--bg)',
            }}
          >
            {link.label}
          </a>
        ))}
      </div>
      {pending ? (
        <div data-testid="trace-langfuse-pending" role="status"
          style={{ fontSize: '11.5px', color: 'var(--fg-muted)', lineHeight: 1.5 }}>
          Waiting for Langfuse to receive this trace…
        </div>
      ) : null}
      {withheld ? (
        <div
          data-testid="trace-langfuse-withheld"
          style={{ fontSize: '11.5px', color: 'var(--fg-muted)', lineHeight: 1.5 }}
        >
          {`Langfuse trace link withheld: ${access?.detail}`}
        </div>
      ) : null}
      {accessError ? (
        <div
          data-testid="trace-langfuse-check-failed"
          style={{ fontSize: '11.5px', color: 'var(--fg-muted)', lineHeight: 1.5 }}
        >
          {`Could not check the Langfuse trace (${accessError}), so its link is not offered.`}
        </div>
      ) : null}
      {!pending && (withheld || accessError) ? (
        <button type="button" onClick={() => setRetry((value) => value + 1)}
          style={{ alignSelf: 'flex-start', fontSize: '11.5px' }}>
          Check Langfuse again
        </button>
      ) : null}
      {access?.exists ? (
        <div
          data-testid="trace-langfuse-access-note"
          style={{ fontSize: '11.5px', color: 'var(--fg-muted)', lineHeight: 1.5 }}
        >
          {access.sign_in_hint}
        </div>
      ) : null}
    </div>
  );
}
