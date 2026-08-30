import { useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

type Props = {
  text: string;
  startLine: number;
  endLine: number;
};

/** Height of an unwrapped row; also the estimate the virtualizer starts from. */
const ROW_HEIGHT = 22;

/**
 * Full file text with 1-based line numbers; the cited span is highlighted and scrolled into view.
 *
 * Lines wrap. They used to be `white-space: pre` rows in a fixed-height virtualizer, so a wide
 * line ran off the pane edge and could only be read through a horizontal scrollbar at the
 * bottom of the whole dock (M-110/B-08) - on the one flow this product exists for, checking
 * that a citation says what the answer claimed. Wrapping means rows have variable height, so
 * the virtualizer measures them instead of assuming ROW_HEIGHT.
 */
export function TextView({ text, startLine, endLine }: Props) {
  const lines = text.split('\n');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const gutter = Math.max(3, String(lines.length).length);

  const virtualizer = useVirtualizer({
    count: lines.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 30,
    measureElement: (element) => element.getBoundingClientRect().height,
  });

  useEffect(() => {
    const target = Math.min(Math.max(startLine - 1, 0), Math.max(lines.length - 1, 0));
    virtualizer.scrollToIndex(target, { align: 'center' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startLine, text]);

  return (
    <div
      ref={scrollRef}
      data-testid="document-text-view"
      style={{
        height: '100%',
        overflowY: 'auto',
        // Never sideways: the pane is the width the operator has, and the text fits it.
        overflowX: 'hidden',
        background: 'var(--code-bg)',
        fontFamily: 'var(--font-mono)',
        fontSize: '14px',
        lineHeight: `${ROW_HEIGHT}px`,
        color: 'var(--fg)',
      }}
    >
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative', width: '100%' }}>
        {virtualizer.getVirtualItems().map((item) => {
          const lineNo = item.index + 1;
          const cited = lineNo >= startLine && lineNo <= endLine;
          return (
            <div
              key={item.key}
              ref={virtualizer.measureElement}
              data-index={item.index}
              data-testid={cited ? 'document-highlight-line' : undefined}
              data-line={lineNo}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${item.start}px)`,
                minHeight: `${ROW_HEIGHT}px`,
                display: 'flex',
                alignItems: 'flex-start',
                background: cited ? 'color-mix(in srgb, var(--accent) 26%, transparent)' : 'transparent',
                borderLeft: cited ? '3px solid var(--accent)' : '3px solid transparent',
              }}
            >
              <span
                style={{
                  flex: `0 0 ${gutter + 1}ch`,
                  textAlign: 'right',
                  paddingRight: '10px',
                  color: cited ? 'var(--fg)' : 'var(--fg-muted)',
                  userSelect: 'none',
                }}
              >
                {lineNo}
              </span>
              <span
                style={{
                  flex: '1 1 auto',
                  minWidth: 0,
                  paddingRight: '16px',
                  // Indentation and runs of spaces are evidence too, so keep them and wrap.
                  whiteSpace: 'pre-wrap',
                  overflowWrap: 'anywhere',
                }}
              >
                {lines[item.index]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
