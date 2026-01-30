import React from 'react';
import type { Card } from '@web/types/cards';

interface CardDisplayProps {
  cards: Card[];
  onCardClick?: (card: Card) => void;
  isLoading?: boolean;
}

export function CardDisplay({ cards, onCardClick, isLoading }: CardDisplayProps) {
  if (isLoading) {
    return (
      <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
        <div style={{ animation: 'spin 1s linear infinite', width: '48px', height: '48px', margin: '0 auto' }}>
          ⏳
        </div>
        <div style={{ marginTop: '12px' }}>Loading cards...</div>
      </div>
    );
  }

  if (!cards || cards.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px', color: 'var(--fg-muted)' }}>
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ opacity: 0.3, marginBottom: '12px' }}>
          <rect x="3" y="4" width="18" height="16" rx="2" ry="2"></rect>
          <line x1="3" y1="9" x2="21" y2="9"></line>
          <line x1="9" y1="4" x2="9" y2="20"></line>
        </svg>
        <div>No cards available</div>
        <div style={{ fontSize: '11px', marginTop: '8px' }}>Click "Build Cards" to generate code cards</div>
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
      {cards.map((card, index) => (
        <CardItem key={card.id || index} card={card} onClick={onCardClick} />
      ))}
    </div>
  );
}

interface CardItemProps {
  card: Card;
  onClick?: (card: Card) => void;
}

function CardItem({ card, onClick }: CardItemProps) {
  const [isHovered, setIsHovered] = React.useState(false);

  const handleClick = () => {
    if (onClick) {
      onClick(card);
    }
  };

  const title = (card.symbols && card.symbols[0]) ? card.symbols[0] : (card.file_path || '').split('/').pop() || 'Unknown';
  const description = card.purpose || 'No description available';
  const location = `${card.file_path}${card.start_line ? `:${card.start_line}` : ''}`;

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
