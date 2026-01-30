// AGRO - InfrastructureSubtabs Component
// Subtab navigation for Infrastructure mega-tab

import { useEffect } from 'react';

interface InfrastructureSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

/**
 * ---agentspec
 * what: |
 *   React component that renders a tabbed navigation interface for Infrastructure configuration sections.
 *   Accepts activeSubtab (string) and onSubtabChange (callback function) as props.
 *   Renders four subtab buttons: Services, MCP Servers, Paths & Stores, and Monitoring.
 *   Returns JSX with tab navigation UI; no side effects beyond React re-renders.
 *   Handles edge case where activeSubtab is undefined by ensuring a default selection (implementation incomplete in provided code).
 *
 * why: |
 *   Separates Infrastructure configuration into logical domains (services, MCP servers, storage paths, observability).
 *   Provides consistent tab-based UX pattern for switching between related configuration views.
 *   Centralizes subtab definitions in one component to avoid duplication across Infrastructure section.
 *
 * guardrails:
 *   - DO NOT hardcode subtab IDs in child components; always pass activeSubtab via props to maintain single source of truth
 *   - ALWAYS validate that onSubtabChange callback is defined before rendering; missing callback will silently fail to update state
 *   - NOTE: Default subtab selection logic is incomplete in current implementation; confirm intended default behavior (e.g., 'services' or first tab)
 *   - ASK USER: Before adding new subtabs, confirm whether they should be conditionally rendered based on user permissions or feature flags
 * ---/agentspec
 */
export function InfrastructureSubtabs({ activeSubtab, onSubtabChange }: InfrastructureSubtabsProps) {
  const subtabs = [
    { id: 'services', title: 'Services' },
    { id: 'docker', title: 'Docker' },
    { id: 'mcp', title: 'MCP Servers' },
    { id: 'paths', title: 'Paths & Stores' },
    { id: 'monitoring', title: 'Monitoring' }
  ];

  // Ensure a default subtab is selected
  useEffect(() => {
    if (!activeSubtab) {
      onSubtabChange('services');
    }
  }, [activeSubtab, onSubtabChange]);

  return (
    <div className="subtab-bar" id="infrastructure-subtabs" style={{ display: 'flex' }}>
      {subtabs.map(subtab => (
        <button
          key={subtab.id}
          className={`subtab-btn ${activeSubtab === subtab.id ? 'active' : ''}`}
          data-subtab={subtab.id}
          onClick={() => onSubtabChange(subtab.id)}
        >
          {subtab.title}
        </button>
      ))}
    </div>
  );
}
