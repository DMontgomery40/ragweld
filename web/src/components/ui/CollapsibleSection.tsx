import { useState, useCallback, useEffect, ReactNode } from 'react';
import { useUIStore } from '@/stores';

interface CollapsibleSectionProps {
  title: string;
  description?: string;
  children: ReactNode;
  defaultExpanded?: boolean;
  storageKey?: string;
}

export function CollapsibleSection({
  title,
  description,
  children,
  defaultExpanded = true,
  storageKey,
}: CollapsibleSectionProps) {
  const collapsedSections = useUIStore((state) => state.collapsedSections);
  const setCollapsed = useUIStore((state) => state.setCollapsed);
  const toggleCollapsed = useUIStore((state) => state.toggleCollapsed);

  const [localExpanded, setLocalExpanded] = useState(defaultExpanded);
  const storedCollapsed = storageKey ? collapsedSections[storageKey] : undefined;
  const isExpanded = storageKey ? !(storedCollapsed ?? !defaultExpanded) : localExpanded;

  useEffect(() => {
    if (!storageKey) return;
    if (storedCollapsed === undefined) {
      setCollapsed(storageKey, !defaultExpanded);
    }
  }, [storageKey, storedCollapsed, defaultExpanded, setCollapsed]);

  const toggleExpanded = useCallback(() => {
    if (storageKey) {
      toggleCollapsed(storageKey);
      return;
    }
    setLocalExpanded((prev) => !prev);
  }, [storageKey, toggleCollapsed]);

  return (
    <div
      className="settings-section"
      style={{
        background: 'var(--card-bg)',
        border: '1px solid var(--line)',
        borderRadius: '12px',
        marginBottom: '16px',
        overflow: 'hidden',
      }}
    >
      <button
        type="button"
        onClick={toggleExpanded}
        aria-expanded={isExpanded}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
        }}
      >
        <div>
          <h3
            style={{
              margin: 0,
              fontSize: '14px',
              fontWeight: 600,
              color: 'var(--fg)',
            }}
          >
            {title}
          </h3>
          {description && (
            <p
              style={{
                margin: '4px 0 0',
                fontSize: '12px',
                color: 'var(--fg-muted)',
              }}
            >
              {description}
            </p>
          )}
        </div>
        <span
          style={{
            fontSize: '18px',
            color: 'var(--fg-muted)',
            transition: 'transform 0.2s ease',
            transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
          aria-hidden="true"
        >
          ▼
        </span>
      </button>

      <div
        style={{
          display: isExpanded ? 'block' : 'none',
          padding: '0 20px 20px',
        }}
      >
        {children}
      </div>
    </div>
  );
}
