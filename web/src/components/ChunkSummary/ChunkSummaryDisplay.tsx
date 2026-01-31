/**
 * ChunkSummaryDisplay - Displays chunk summaries in a grid layout
 *
 * Uses types from generated.ts (Pydantic-first):
 * - ChunkSummary
 */

import React from 'react';
import type { ChunkSummary } from '@/types/generated';

interface ChunkSummaryDisplayProps {
  chunkSummaries: ChunkSummary[];
  onChunkClick?: (chunk: ChunkSummary) => void;
  isLoading?: boolean;
}

export function ChunkSummaryDisplay({ chunkSummaries, onChunkClick, isLoading }: ChunkSummaryDisplayProps) {
  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
        <div style={{ animation: 'spin 1s linear infinite', width: '48px', height: '48px', margin: '0 auto' }}>
          ⏳
        </div>
        <div style={{ marginTop: '12px' }}>Loading chunk summaries...</div>
      </div>
    );
  }

  if (!chunkSummaries || chunkSummaries.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.3, marginBottom: '12px' }}>
          <rect x="3" y="4" width="18" height="16" rx="2" ry="2"></rect>
          <line x1="3" y1="9" x2="21" y2="9"></line>
          <line x1="9" y1="4" x2="9" y2="20"></line>
        </svg>
        <div>No chunk summaries available</div>
        <div style={{ fontSize: '11px', marginTop: '8px' }}>Click "Build Chunk Summaries" to generate summaries from indexed content</div>
      </div>
    );
  }

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
      gap: '16px',
      padding: '16px'
    }}>
      {chunkSummaries.map((chunk, index) => (
        <ChunkSummaryItem key={chunk.chunk_id || `${chunk.file_path}:${chunk.start_line ?? ''}:${index}`} chunk={chunk} onClick={onChunkClick} />
      ))}
    </div>
  );
}

interface ChunkSummaryItemProps {
  chunk: ChunkSummary;
  onClick?: (chunk: ChunkSummary) => void;
}

function ChunkSummaryItem({ chunk, onClick }: ChunkSummaryItemProps) {
  const [isHovered, setIsHovered] = React.useState(false);

  const handleClick = () => {
    if (onClick) {
      onClick(chunk);
    }
  };

  const title = (chunk.symbols && chunk.symbols[0]) ? chunk.symbols[0] : (chunk.file_path || '').split('/').pop() || 'Unknown';
  const description = chunk.purpose || 'No description available';
  const location = `${chunk.file_path}${chunk.start_line ? `:${chunk.start_line}` : ''}`;

  return (
    <div
      onClick={handleClick}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      style={{
        background: isHovered ? 'var(--bg-elev1)' : 'var(--bg-elev2)',
        border: `1px solid ${isHovered ? 'var(--accent)' : 'var(--line)'}`,
        borderRadius: '8px',
        padding: '16px',
        cursor: 'pointer',
        transition: 'all 0.2s',
        minHeight: '180px',
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'space-between',
        boxShadow: isHovered ? '0 4px 12px rgba(0,0,0,0.15)' : '0 1px 3px rgba(0,0,0,0.1)'
      }}
    >
      <div>
        <h4 style={{
          margin: '0 0 8px 0',
          color: 'var(--accent)',
          fontSize: '14px',
          fontWeight: 600,
          wordBreak: 'break-word'
        }}>
          {title}
        </h4>
        <p style={{
          margin: '0 0 8px 0',
          color: 'var(--fg-muted)',
          fontSize: '12px',
          lineHeight: 1.4,
          wordBreak: 'break-word',
          overflow: 'hidden',
          display: '-webkit-box',
          WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical'
        }}>
          {description}
        </p>
      </div>
      <div style={{
        fontSize: '10px',
        color: 'var(--fg-muted)',
        wordBreak: 'break-all'
      }}>
        <span style={{ color: 'var(--link)' }}>{location}</span>
      </div>
    </div>
  );
}
