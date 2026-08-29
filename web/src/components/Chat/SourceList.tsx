import { documentPageUrl } from '@/api/documents';
import { RegionOverlay } from '@/components/Documents/RegionOverlay';
import { corpusIdOf, formatSourceLocation, hasPageRegions, regionsForPage } from '@/components/Documents/sourceLabels';
import { useDockStore } from '@/stores/useDockStore';
import { useRepoStore } from '@/stores/useRepoStore';
import type { ChunkMatch, WebCitation } from '@/types/generated';

type Props = {
  sources: ChunkMatch[];
  legacyCitations: string[];
  webCitations: WebCitation[];
};

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
export function SourceList({ sources, legacyCitations, webCitations }: Props) {
  const openDocument = useDockStore((s) => s.openDocument);
  const repos = useRepoStore((s) => s.repos);
  const corpusName = (id: string) => repos.find((r) => r.corpus_id === id)?.name || id;

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
      <strong style={{ fontSize: '12.5px' }}>Sources</strong>
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
                <span style={{ color: 'var(--fg-muted)' }}>
                  {formatSourceLocation(source)} · {corpusName(corpusId)}
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
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: '12.5px', color: 'var(--link)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              [{number}] {source.file_path}:{source.start_line}-{source.end_line}
            </span>
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
