import type React from 'react';
import { memo, useMemo, useRef } from 'react';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { advanceMarkdownSplit, type IncrementalMarkdownSplit } from './markdownBlocks';

/**
 * The one markdown renderer for LLM output across the app: GFM tables, bold,
 * inline code, fenced code with syntax highlighting, and nested lists. Kept
 * theme-tokened and above the legibility floor (body 14px, captions >= 11.5px,
 * no opacity on text), and wide tables scroll inside their own `overflow-x`
 * wrapper so they never break the panel layout.
 *
 * Rendered block by block (markdownBlocks.ts): each finished top-level block is a
 * memoized element that is parsed and highlighted once, so a streaming answer only
 * re-renders its last, still-growing block. While `streaming`, a code fence that has
 * not closed yet renders as plain text in the same box and is highlighted once it
 * closes, instead of being re-tokenized on every frame.
 */

type Props = {
  content: string;
  /** The content is still arriving (a streaming chat answer). */
  streaming?: boolean;
};

const REMARK_PLUGINS = [remarkGfm];
const CODE_BOX_STYLE: React.CSSProperties = { margin: '12px 0', borderRadius: '8px', overflow: 'hidden', border: '1px solid var(--line)' };
const CODE_HEADER_STYLE: React.CSSProperties = {
  background: 'var(--bg-elev2)',
  padding: '6px 12px',
  fontSize: '11.5px',
  color: 'var(--fg-muted)',
  borderBottom: '1px solid var(--line)',
};
const HIGHLIGHTER_STYLE: React.CSSProperties = { margin: 0, padding: '12px', fontSize: '13px', background: '#1e1e2e' };

type CodeProps = React.HTMLAttributes<HTMLElement> & {
  node?: { position?: { end?: { offset?: number } } };
};

/** `openFenceFrom`: code nodes ending at or after this offset are the fence still being written. */
function makeComponents(openFenceFrom: number | null): Components {
  return {
    code({ className, children, node, ...props }: CodeProps) {
      const match = /language-(\w+)/.exec(className || '');
      const codeString = String(children).replace(/\n$/, '');
      // remark-gfm no longer passes an `inline` prop (react-markdown v9+), so a
      // fenced block is discriminated by its language tag or an embedded newline;
      // everything else is an inline span.
      const isBlock = Boolean(match) || codeString.includes('\n');
      if (isBlock && match) {
        const endOffset = node?.position?.end?.offset ?? -1;
        const stillOpen = openFenceFrom !== null && endOffset >= openFenceFrom;
        return (
          <div style={CODE_BOX_STYLE}>
            <div style={CODE_HEADER_STYLE}>{match[1]}</div>
            <SyntaxHighlighter
              style={oneDark as Record<string, React.CSSProperties>}
              language={stillOpen ? 'text' : match[1]}
              PreTag="div"
              customStyle={HIGHLIGHTER_STYLE}
            >
              {codeString}
            </SyntaxHighlighter>
          </div>
        );
      }
      if (isBlock) {
        return (
          <pre
            style={{
              margin: '12px 0',
              padding: '12px',
              borderRadius: '8px',
              border: '1px solid var(--line)',
              background: 'var(--code-bg)',
              color: 'var(--fg)',
              fontSize: '13px',
              fontFamily: 'var(--font-mono, monospace)',
              overflowX: 'auto',
            }}
          >
            <code>{codeString}</code>
          </pre>
        );
      }
      return (
        <code
          style={{
            background: 'var(--code-bg)',
            padding: '1px 6px',
            borderRadius: '4px',
            fontSize: '13px',
            fontFamily: 'var(--font-mono, monospace)',
            color: 'var(--fg)',
          }}
          {...props}
        >
          {children}
        </code>
      );
    },
    p({ children }) {
      return <p style={{ margin: '0 0 12px 0' }}>{children}</p>;
    },
    h1({ children }) {
      return <h1 style={{ fontSize: '18px', fontWeight: 700, margin: '18px 0 10px', color: 'var(--fg)' }}>{children}</h1>;
    },
    h2({ children }) {
      return <h2 style={{ fontSize: '16px', fontWeight: 700, margin: '16px 0 8px', color: 'var(--fg)' }}>{children}</h2>;
    },
    h3({ children }) {
      return <h3 style={{ fontSize: '14.5px', fontWeight: 700, margin: '14px 0 6px', color: 'var(--fg)' }}>{children}</h3>;
    },
    ul({ children }) {
      return <ul style={{ margin: '8px 0', paddingLeft: '22px' }}>{children}</ul>;
    },
    ol({ children, start }) {
      return (
        <ol start={start} style={{ margin: '8px 0', paddingLeft: '22px' }}>
          {children}
        </ol>
      );
    },
    li({ children }) {
      return <li style={{ marginBottom: '4px' }}>{children}</li>;
    },
    strong({ children }) {
      return <strong style={{ fontWeight: 700, color: 'var(--fg)' }}>{children}</strong>;
    },
    table({ children }) {
      return (
        <div style={{ overflowX: 'auto', margin: '12px 0' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: '13px' }}>{children}</table>
        </div>
      );
    },
    thead({ children }) {
      return <thead style={{ background: 'var(--bg-elev2)' }}>{children}</thead>;
    },
    th({ children, style }) {
      return (
        <th
          style={{
            border: '1px solid var(--line)',
            padding: '6px 10px',
            textAlign: (style?.textAlign as React.CSSProperties['textAlign']) ?? 'left',
            fontWeight: 700,
            color: 'var(--fg)',
          }}
        >
          {children}
        </th>
      );
    },
    td({ children, style }) {
      return (
        <td
          style={{
            border: '1px solid var(--line)',
            padding: '6px 10px',
            textAlign: (style?.textAlign as React.CSSProperties['textAlign']) ?? 'left',
            color: 'var(--fg)',
          }}
        >
          {children}
        </td>
      );
    },
    a({ href, children }) {
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--link)', textDecoration: 'underline' }}>
          {children}
        </a>
      );
    },
    blockquote({ children }) {
      return (
        <blockquote
          style={{
            borderLeft: '3px solid var(--accent)',
            margin: '12px 0',
            padding: '4px 16px',
            color: 'var(--fg-muted)',
          }}
        >
          {children}
        </blockquote>
      );
    },
  };
}

const COMPONENTS = makeComponents(null);

/** One top-level block. Finished blocks never change, so this renders each of them once. */
const MarkdownBlock = memo(function MarkdownBlock({ source, openFence }: { source: string; openFence: boolean }) {
  const components = useMemo(
    // The unclosed fence runs to the end of the block, past its last non-blank character.
    () => (openFence ? makeComponents(source.replace(/\s+$/, '').length) : COMPONENTS),
    [openFence, source],
  );
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
      {source}
    </ReactMarkdown>
  );
});

export const AssistantMarkdown = memo(function AssistantMarkdown({ content, streaming = false }: Props) {
  const splitRef = useRef<IncrementalMarkdownSplit | null>(null);
  const next = advanceMarkdownSplit(splitRef.current, content);
  splitRef.current = next;
  const { blocks, tail, tailOpenFence } = next.split;
  return (
    <div
      data-testid="assistant-markdown"
      style={{ fontSize: '14px', lineHeight: 1.7, color: 'var(--fg)', wordBreak: 'break-word' }}
    >
      {blocks.map((block, index) => (
        <MarkdownBlock key={index} source={block} openFence={false} />
      ))}
      {tail ? <MarkdownBlock key={blocks.length} source={tail} openFence={streaming && tailOpenFence} /> : null}
    </div>
  );
});

export default AssistantMarkdown;
