import { documentPageUrl } from '@/api/documents';
import { FigureBadge } from '@/components/Documents/FigureBadge';
import { RegionOverlay } from '@/components/Documents/RegionOverlay';
import { corpusIdOf, formatSourceLocation, hasPageRegions, regionsForPage } from '@/components/Documents/sourceLabels';
import { useDockStore } from '@/stores/useDockStore';
import { useRepoStore } from '@/stores/useRepoStore';
import type { ChunkMatch, WebCitation } from '@/types/generated';

type Props = {
  sources: ChunkMatch[];
  legacyCitations: string[];
  webCitations: WebCitation[];
  /** Images the prompting user turn attached, listed as real answer sources so an image-only
   * answer does not look grounded purely in low-scoring corpus chunks (M-95/B-18). */
  attachedImageCount?: number;
};

const RECALL_CORPUS_ID = 'recall_default';

/** A recall citation points at a conversation markdown file (`conversations/<id>.md`), whose
 * raw path is meaningless to a reader. Show the first line of the recalled turn instead. */
function isRecallSource(source: ChunkMatch): boolean {
  return String(source.file_path || '').startsWith('conversations/') || corpusIdOf(source) === RECALL_CORPUS_ID;
}

function recallTitle(source: ChunkMatch): string {
  const line = String(source.content || '')
    .split('\n')
    .map((part) => part.trim())
    .find((part) => part.length > 0 && !part.startsWith('#'));
  const title = line || 'Recall memory';
  return title.length > 80 ? `${title.slice(0, 77)}…` : title;
}

const rowButton: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  width: '100%',
  textAlign: 'left',
  background: 'transparent',
  border: '1px solid transparent',
  borderRadius: 'var(--radius-md)',
  padding: '4px 6px',
  cursor: 'pointer',
  color: 'var(--fg)',
};

/**
 * Citations under an assistant answer. PDF citations with page regions render as a small
 * "paper" thumbnail card; everything else is a compact clickable file:line row. Both open the
 * source in the right rail at the cited location.
 */
export function SourceList({ sources, legacyCitations, webCitations, attachedImageCount = 0 }: Props) {
  const openDocument = useDockStore((s) => s.openDocument);
  const repos = useRepoStore((s) => s.repos);
  const corpusName = (id: string) => repos.find((r) => r.corpus_id === id)?.name || id;

  const totalCount =
    sources.length + legacyCitations.length + webCitations.length + (attachedImageCount > 0 ? 1 : 0);

  return (
    <div
      data-testid="chat-sources"
      style={{
        marginTop: '12px',
        paddingTop: '12px',
        borderTop: '1px solid var(--line)',
        fontSize: '12.5px',
        display: 'grid',
        gap: '6px',
      }}
    >
      <strong data-testid="chat-sources-header" style={{ fontSize: '12.5px' }}>
        Sources ({totalCount})
      </strong>
      {attachedImageCount > 0 ? (
        <div
          data-testid="chat-source-attached-images"
          style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--fg)', padding: '4px 6px' }}
        >
          <span
            aria-hidden="true"
            style={{
              fontSize: '11px',
              fontWeight: 700,
              color: 'var(--accent-text)',
              border: '1px solid var(--line)',
              borderRadius: '999px',
              padding: '1px 8px',
            }}
          >
            IMAGE
          </span>
          <span>
            {attachedImageCount} attached image{attachedImageCount === 1 ? '' : 's'} used as an answer input
          </span>
        </div>
      ) : null}
      {sources.map((source, index) => {
        const corpusId = corpusIdOf(source);
        const number = index + 1;
        const fileName = source.file_path.split('/').pop() || source.file_path;
        const open = () => {
          if (corpusId) openDocument({ corpusId, source });
        };
        if (hasPageRegions(source) && corpusId) {
          const page = source.provenance?.page_start ?? 1;
          return (
            <button
              key={`${source.chunk_id}-${index}`}
              type="button"
              data-testid="chat-citation-open-pdf"
              title={`Open ${source.file_path} at ${formatSourceLocation(source)}`}
              onClick={open}
              style={{ ...rowButton, alignItems: 'flex-start' }}
            >
              <span
                aria-hidden="true"
                style={{
                  position: 'relative',
                  flex: '0 0 72px',
                  width: '72px',
                  aspectRatio: '612 / 792',
                  background: '#ffffff',
                  border: '1px solid var(--line)',
                  boxShadow: '0 1px 4px rgba(0,0,0,0.4)',
                  overflow: 'hidden',
                  display: 'block',
                }}
              >
                <img
                  src={documentPageUrl(corpusId, source.file_path, page, 'thumb')}
                  alt=""
                  data-testid="chat-citation-thumb"
                  style={{ display: 'block', width: '100%', height: '100%' }}
                />
                <RegionOverlay regions={regionsForPage(source.provenance, page)} thin />
              </span>
              <span style={{ display: 'grid', gap: '2px', minWidth: 0 }}>
                <span style={{ fontWeight: 700, fontSize: '13px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  [{number}] {fileName}
                </span>
                <span style={{ color: 'var(--fg-muted)', display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                  <span>
                    {formatSourceLocation(source)} · {corpusName(corpusId)}
                  </span>
                  <FigureBadge source={source} testId="chat-citation-figure-badge" />
                </span>
                <span style={{ color: 'var(--fg-muted)' }}>score {Number(source.score || 0).toFixed(3)}</span>
              </span>
            </button>
          );
        }
        return (
          <button
            key={`${source.chunk_id}-${index}`}
            type="button"
            data-testid="chat-citation-open"
            title={corpusId ? `Open ${source.file_path} at ${formatSourceLocation(source)}` : 'No corpus id on this citation'}
            onClick={open}
            disabled={!corpusId}
            style={{ ...rowButton, cursor: corpusId ? 'pointer' : 'not-allowed', opacity: corpusId ? 1 : 0.8 }}
          >
            {isRecallSource(source) ? (
              <span
                data-testid="chat-citation-recall-title"
                style={{ fontSize: '12.5px', color: 'var(--link)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
              >
                [{number}] Recall · {recallTitle(source)}
              </span>
            ) : (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12.5px', color: 'var(--link)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                [{number}] {source.file_path}:{source.start_line}-{source.end_line}
              </span>
            )}
            <FigureBadge source={source} testId="chat-citation-figure-badge" />
            <span style={{ color: 'var(--fg-muted)', whiteSpace: 'nowrap' }}>
              {source.provenance?.extraction === 'docling' ? `${formatSourceLocation(source)} · ` : ''}
              score {Number(source.score || 0).toFixed(3)}
            </span>
          </button>
        );
      })}
      {legacyCitations.map((citation, index) => (
        <div key={`${citation}-${index}`} style={{ color: 'var(--fg-muted)' }}>
          {citation}
        </div>
      ))}
      {webCitations.map((citation, index) => (
        <a
          key={`${citation.url}-${citation.start_index}-${citation.end_index}-${index}`}
          href={citation.url}
          target="_blank"
          rel="noreferrer noopener"
          data-testid="chat-web-citation-link"
          style={{
            color: 'var(--link)',
            textDecoration: 'none',
            border: '1px solid var(--line)',
            borderRadius: 'var(--radius-md)',
            padding: '7px 9px',
            display: 'grid',
            gap: '2px',
          }}
        >
          <span style={{ fontWeight: 700 }}>{citation.title || citation.url}</span>
          <span style={{ color: 'var(--fg-muted)', fontSize: '11px', wordBreak: 'break-all' }}>
            {citation.url}
          </span>
        </a>
      ))}
    </div>
  );
}
