import type { TraceCostSummary } from '@/types/generated';

export function CostAttribution({
  summary,
  showDetail = false,
}: {
  summary?: TraceCostSummary | null;
  showDetail?: boolean;
}) {
  const amount = summary?.estimated_cost_usd;
  const known = summary?.cost_source !== 'unavailable'
    && typeof amount === 'number' && Number.isFinite(amount) && amount >= 0;
  const reported = known && summary?.cost_source === 'provider' && summary.authoritative;
  // Significant digits preserve small, nonzero reported charges instead of rounding them to $0.
  const dollars = known ? `$${amount.toLocaleString('en-US', { maximumSignificantDigits: 6, useGrouping: false })}` : '';
  const hasTokens = summary?.input_tokens != null || summary?.output_tokens != null;

  return (
    <div style={{ display: 'grid', gap: 4, fontSize: 12, lineHeight: 1.5 }} title={summary?.detail ?? undefined}>
      <strong style={{ color: known ? 'var(--fg)' : 'var(--warn)' }}>
        {known ? `${reported ? 'Gateway reported' : 'Estimated cost'}: ${dollars}` : 'Cost unknown'}
      </strong>
      {hasTokens ? (
        <span style={{ color: 'var(--fg-muted)' }}>
          {summary?.input_tokens ?? 'Unknown'} input · {summary?.output_tokens ?? 'unknown'} output tokens
        </span>
      ) : null}
      {showDetail && summary?.detail ? (
        <span style={{ color: 'var(--fg-muted)' }}>{summary.detail}</span>
      ) : null}
    </div>
  );
}
