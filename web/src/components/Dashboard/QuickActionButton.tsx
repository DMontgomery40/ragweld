// AGRO - Quick Action Button Component
// Reusable action button with icon and label

import React from 'react';

interface QuickActionButtonProps {
  id: string;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  dataAction?: string;
  disabled?: boolean;
}

export function QuickActionButton({ id, icon, label, onClick, dataAction, disabled = false }: QuickActionButtonProps) {
  const [isActive, setIsActive] = React.useState(false);

  return (
    <button
      id={id}
      className="action-btn"
      data-action={dataAction}
      disabled={disabled}
      onClick={(_e) => {
        if (disabled) return;
        setIsActive(true);
        onClick();
        setTimeout(() => setIsActive(false), 600);
      }}
      onMouseDown={() => !disabled && setIsActive(true)}
      onMouseUp={() => setIsActive(false)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        padding: '14px 11px',
        background: 'var(--panel)',
        border: '1px solid var(--line)',
        borderRadius: '8px',
        color: 'var(--fg-muted)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        fontSize: '14px',
        fontWeight: 500,
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
        opacity: disabled ? 0.5 : 1,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = 'var(--panel)';
        e.currentTarget.style.borderColor = 'var(--accent)';
        e.currentTarget.style.color = 'var(--accent)';
        e.currentTarget.style.transform = 'translateY(-2px)';
        e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 255, 136, 0.2)';
        
        // Icon glow
        const iconEl = e.currentTarget.querySelector('div');
        if (iconEl) {
          (iconEl as HTMLElement).style.filter = 'drop-shadow(0 0 4px rgba(0, 255, 136, 0.5))';
        }
      }}
      onMouseLeave={(e) => {
        setIsActive(false);
        e.currentTarget.style.background = 'var(--panel)';
        e.currentTarget.style.borderColor = 'var(--line)';
        e.currentTarget.style.color = 'var(--fg-muted)';
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = 'none';
        
        // Remove icon glow
        const iconEl = e.currentTarget.querySelector('div');
        if (iconEl) {
          (iconEl as HTMLElement).style.filter = 'none';
        }
      }}
    >
      {/* Ripple effect pseudo-element via actual DOM element */}
      <div
        style={{
          content: '',
          position: 'absolute',
          top: '50%',
          left: '50%',
          width: isActive ? '300px' : '0',
          height: isActive ? '300px' : '0',
          borderRadius: '50%',
          background: 'rgba(0, 255, 136, 0.3)',
          transform: 'translate(-50%, -50%)',
          transition: 'width 0.6s, height 0.6s',
          pointerEvents: 'none',
        }}
      />
      
      <div style={{ color: 'var(--link)', fontSize: '24px', zIndex: 1, position: 'relative', transition: 'all 0.2s' }}>
        {icon}
      </div>
      <span style={{ zIndex: 1, position: 'relative' }}>{label}</span>
    </button>
  );
}

