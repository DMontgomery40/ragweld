// TriBridRAG - AdminSubtabs Component
// Subtab navigation for Admin mega-tab

import { useEffect } from 'react';

interface AdminSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function AdminSubtabs({ activeSubtab, onSubtabChange }: AdminSubtabsProps) {
  const subtabs = [
    { id: 'basic', title: 'Basic' },
    { id: 'advanced', title: 'Advanced' },
    { id: 'raw', title: 'Raw' },
    { id: 'dependencies', title: 'Dependencies' }
  ];

  // Ensure a default subtab is selected
  useEffect(() => {
    if (!activeSubtab) {
      onSubtabChange('basic');
    }
  }, [activeSubtab, onSubtabChange]);

  return (
    <div className="subtab-bar" id="admin-subtabs" style={{ display: 'flex' }}>
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
