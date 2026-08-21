// TriBridRAG - InfrastructureSubtabs Component
// Subtab navigation for Infrastructure mega-tab

import { useEffect } from 'react';

interface InfrastructureSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

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
