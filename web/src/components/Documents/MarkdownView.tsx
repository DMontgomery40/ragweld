import { useEffect, useRef } from 'react';

type Props = {
  markdown: string;
  charStart: number | null;
  charEnd: number | null;
};

/** The Docling markdown a rich document was chunked from, with the cited char span marked. */
export function MarkdownView({ markdown, charStart, charEnd }: Props) {
  const markRef = useRef<HTMLElement | null>(null);
  const hasSpan =
    charStart !== null && charEnd !== null && charStart >= 0 && charEnd <= markdown.length && charEnd > charStart;

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: 'center' });
  }, [markdown, charStart, charEnd]);

  const before = hasSpan ? markdown.slice(0, charStart) : markdown;
  const cited = hasSpan ? markdown.slice(charStart, charEnd) : '';
  const after = hasSpan ? markdown.slice(charEnd) : '';

  return (
    <pre
      data-testid="document-markdown-view"
      style={{
        margin: 0,
        height: '100%',
        overflow: 'auto',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
        fontFamily: 'var(--font-mono)',
        fontSize: '12.5px',
        lineHeight: 1.6,
        color: 'var(--fg)',
        background: 'var(--code-bg)',
        padding: '12px',
      }}
    >
      {before}
      {hasSpan ? (
        <mark
          ref={markRef}
          data-testid="document-highlight-span"
          style={{
            background: 'color-mix(in srgb, var(--accent) 30%, transparent)',
            color: 'var(--fg)',
            outline: '2px solid var(--accent)',
            borderRadius: '2px',
          }}
        >
          {cited}
        </mark>
      ) : null}
      {after}
    </pre>
  );
}
