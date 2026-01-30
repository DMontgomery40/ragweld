// AGRO - AdminSubtabs Component
// Subtab navigation for Admin mega-tab

import { useEffect } from 'react';

interface AdminSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function AdminSubtabs({ activeSubtab, onSubtabChange }: AdminSubtabsProps) {
  const subtabs = [
    { id: 'general', title: 'General' },
    { id: 'git', title: 'Git Integration' },
    { id: 'secrets', title: 'Secrets' },
    { id: 'integrations', title: 'Integrations' }
  ];

  // Ensure a default subtab is selected
  useEffect(() => {
    if (!activeSubtab) {
      onSubtabChange('general');
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
