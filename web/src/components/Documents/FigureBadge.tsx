import { figureBadgeLabel } from '@/components/Documents/sourceLabels';
import type { ChunkMatch } from '@/types/generated';

type Props = {
  source: ChunkMatch;
  /** Test id for this placement; the same pill appears in citations and in the viewer. */
  testId: string;
};

/**
 * Pill marking a citation whose chunk is a figure description rather than page text.
 * Renders nothing for ordinary citations.
 *
 * `--accent` under `--accent-contrast` clears 4.5:1 in both themes (4.7:1 dark, 7.5:1
 * light); the label stays at 11.5px and full opacity so it holds up at 93 PPI.
 */
export function FigureBadge({ source, testId }: Props) {
  const label = figureBadgeLabel(source);
  if (!label) return null;
  return (
    <span
      data-testid={testId}
      style={{
        display: 'inline-block',
        background: 'var(--accent)',
        color: 'var(--accent-contrast)',
        fontSize: '11.5px',
        fontWeight: 700,
        lineHeight: 1.4,
        letterSpacing: '0.2px',
        padding: '1px 6px',
        borderRadius: 'var(--radius-md)',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </span>
  );
}
