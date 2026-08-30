import { useCallback, useState } from 'react';
import { showToast } from '@/utils/toast';

// Middle-truncation budget for an inline identifier. Ids at or below the
// inline max render whole; longer ones keep their head and tail so the kind
// prefix and the distinguishing suffix both stay visible
// (`bundle__5f15...288a23`).
const HEAD = 12;
const TAIL = 12;
const INLINE_MAX = 28;

/** Middle-truncate a long identifier for inline display; '—' for empty. */
export function truncateId(value: string | null | undefined): string {
  const text = String(value || '').trim();
  if (!text) return '—';
  if (text.length <= INLINE_MAX) return text;
  return `${text.slice(0, HEAD)}...${text.slice(-TAIL)}`;
}

/**
 * A middle-truncated identifier that stays operable (M-112): the full value is
 * on the `title` (hover) and one click copies it to the clipboard. Use for any
 * id an operator pastes into a CLI or a ticket -- bundle / eval-run / version
 * ids in the LINEAGE panel and the Synthetic Lab artifacts list, which were
 * otherwise middle-truncated with no way to see or copy the whole value.
 */
export function TruncatedId({
  value,
  className,
  testId,
}: {
  value: string | null | undefined;
  className?: string;
  testId?: string;
}) {
  const full = String(value || '').trim();
  const [copied, setCopied] = useState(false);

  const copy = useCallback(async () => {
    if (!full) return;
    try {
      await navigator.clipboard.writeText(full);
      setCopied(true);
      showToast('Full id copied to the clipboard', 'success');
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      showToast('Could not copy the id to the clipboard', 'error');
    }
  }, [full]);

  if (!full) return <span className={className}>—</span>;

  const shown = truncateId(full);
  const isTruncated = shown !== full;

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', verticalAlign: 'bottom' }}>
      <span className={className} title={isTruncated ? full : undefined}>
        {shown}
      </span>
      <button
        type="button"
        data-testid={testId}
        onClick={copy}
        title={`Copy full id: ${full}`}
        aria-label={`Copy full id ${full} to the clipboard`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '20px',
          height: '20px',
          padding: 0,
          flex: '0 0 auto',
          border: '1px solid var(--line)',
          borderRadius: '4px',
          background: 'var(--bg-elev2)',
          color: copied ? 'var(--ok)' : 'var(--fg-muted)',
          cursor: 'pointer',
        }}
      >
        {copied ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M20 6 9 17l-5-5" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="9" y="9" width="11" height="11" rx="2" />
            <path d="M5 15V5a2 2 0 0 1 2-2h10" />
          </svg>
        )}
      </button>
    </span>
  );
}
