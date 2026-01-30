// AGRO - Grafana Subtabs Component
// Subtab navigation for Grafana tab (Dashboard and Config)

import { useEffect } from 'react';

interface GrafanaSubtabsProps {
  activeSubtab: string;
  onSubtabChange: (subtab: string) => void;
}

export function GrafanaSubtabs({ activeSubtab, onSubtabChange }: GrafanaSubtabsProps) {
  useEffect(() => {
    // Legacy module compatibility - dispatch event for legacy JS
    window.dispatchEvent(new CustomEvent('subtab-changed', {
      detail: { parent: 'grafana', subtab: activeSubtab }
    }));
  }, [activeSubtab]);

  return (
    <div id="grafana-subtabs" className="subtab-bar" data-state="visible" style={{ display: 'flex' }}>
      <button
        className={`subtab-btn ${activeSubtab === 'dashboard' ? 'active' : ''}`}
        data-subtab="dashboard"
        data-parent="grafana"
        onClick={() => onSubtabChange('dashboard')}
      >
        Dashboard
      </button>
      <button
        className={`subtab-btn ${activeSubtab === 'config' ? 'active' : ''}`}
        data-subtab="config"
        data-parent="grafana"
        onClick={() => onSubtabChange('config')}
      >
        Config
      </button>
    </div>
  );
}
