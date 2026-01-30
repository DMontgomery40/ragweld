/**
 * ProviderCard - Selectable card for embedding provider selection
 *
 * Follows the same pattern as RerankerConfigSubtab mode cards.
 * Uses CSS variables for theming and cubic-bezier for transitions.
 */

import type { CSSProperties } from 'react';

interface ProviderCardProps {
  id: string;
  icon: string;
  label: string;
  description: string;
  selected: boolean;
  onClick: () => void;
  disabled?: boolean;
}

const cardStyles: CSSProperties = {
  padding: '20px 16px',
  border: '1px solid var(--line)',
  borderRadius: '12px',
  cursor: 'pointer',
  textAlign: 'left',
  transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
  position: 'relative',
  overflow: 'hidden',
  background: 'var(--card-bg)',
};

const selectedStyles: CSSProperties = {
  background: 'linear-gradient(135deg, rgba(var(--accent-rgb), 0.15), rgba(var(--accent-rgb), 0.05))',
  border: '2px solid var(--accent)',
};

const disabledStyles: CSSProperties = {
  opacity: 0.5,
  cursor: 'not-allowed',
};

export function ProviderCard({
  id,
  icon,
  label,
  description,
  selected,
  onClick,
  disabled = false,
}: ProviderCardProps) {
  const handleClick = () => {
    if (!disabled) {
      onClick();
    }
  };

  const combinedStyles: CSSProperties = {
    ...cardStyles,
    ...(selected ? selectedStyles : {}),
    ...(disabled ? disabledStyles : {}),
  };

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      style={combinedStyles}
      aria-pressed={selected}
      data-provider={id}
    >
      {/* Selection indicator */}
      {selected && (
        <div
          style={{
            position: 'absolute',
            top: '8px',
            right: '8px',
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: 'var(--accent)',
            boxShadow: '0 0 8px var(--accent)',
          }}
        />
      )}

      {/* Icon */}
      <div style={{ fontSize: '28px', marginBottom: '10px' }}>{icon}</div>

      {/* Label */}
      <div
        style={{
          fontSize: '14px',
          fontWeight: 600,
          color: selected ? 'var(--accent)' : 'var(--fg)',
          marginBottom: '6px',
        }}
      >
        {label}
      </div>

      {/* Description */}
      <div
        style={{
          fontSize: '12px',
          color: 'var(--fg-muted)',
          lineHeight: 1.4,
        }}
      >
        {description}
      </div>
    </button>
  );
}

// Provider definitions removed - providers now loaded dynamically from models.json via useModels('EMB')
