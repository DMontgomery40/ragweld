import { useEffect, useState } from 'react';

import * as DashAPI from '@/api/dashboard';
import type { LangfuseTraceAccess, TraceExternalLink } from '@/types/generated';

type Props = {
  links: TraceExternalLink[] | null | undefined;
  /** Canonical trace id these links belong to; enables the Langfuse existence check. */
  traceId?: string | null;
};

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
  const [access, setAccess] = useState<LangfuseTraceAccess | null>(null);
  const [accessError, setAccessError] = useState<string | null>(null);
  const id = String(traceId || '').trim();

  useEffect(() => {
    let cancelled = false;
    if (!id) {
      setAccess(null);
      setAccessError(null);
      return;
    }
    void DashAPI.getLangfuseTraceAccess(id)
      .then((next) => {
        if (!cancelled) {
          setAccess(next);
          setAccessError(null);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setAccess(null);
        // The check failing is not the same as Langfuse saying no; say which.
        setAccessError(error instanceof Error ? error.message : 'the check did not complete');
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const visible = (links || []).filter(
    (link) => !isLangfuseTraceLink(link) || access?.exists === true
  );
  const withheld = (links || []).some(isLangfuseTraceLink) && access !== null && !access.exists;

  if (!visible.length && !withheld && !accessError) return null;

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
