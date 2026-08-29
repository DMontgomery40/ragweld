import { useEffect, useRef } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';

type Props = {
  text: string;
  startLine: number;
  endLine: number;
};

const ROW_HEIGHT = 22;

/** Full file text with 1-based line numbers; the cited span is highlighted and scrolled into view. */
export function TextView({ text, startLine, endLine }: Props) {
  const lines = text.split('\n');
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const gutter = Math.max(3, String(lines.length).length);

  const virtualizer = useVirtualizer({
    count: lines.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 30,
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
        overflow: 'auto',
        background: 'var(--code-bg)',
        fontFamily: 'var(--font-mono)',
        fontSize: '12.5px',
        lineHeight: `${ROW_HEIGHT}px`,
        color: 'var(--fg)',
      }}
    >
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative', minWidth: '100%' }}>
        {virtualizer.getVirtualItems().map((item) => {
          const lineNo = item.index + 1;
          const cited = lineNo >= startLine && lineNo <= endLine;
          return (
            <div
              key={item.key}
              data-testid={cited ? 'document-highlight-line' : undefined}
              data-line={lineNo}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                transform: `translateY(${item.start}px)`,
                height: `${ROW_HEIGHT}px`,
                display: 'flex',
                whiteSpace: 'pre',
                minWidth: '100%',
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
              <span style={{ paddingRight: '16px' }}>{lines[item.index]}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
