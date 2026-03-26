// TriBridRAG - Grafana Subtabs Component
// Subtab navigation for Grafana tab (Overview, Dashboards, Incidents, and Config)

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
        className={`subtab-btn ${activeSubtab === 'overview' ? 'active' : ''}`}
        data-subtab="overview"
        data-parent="grafana"
        onClick={() => onSubtabChange('overview')}
      >
        Overview
      </button>
      <button
        className={`subtab-btn ${activeSubtab === 'dashboards' ? 'active' : ''}`}
        data-subtab="dashboards"
        data-parent="grafana"
        onClick={() => onSubtabChange('dashboards')}
      >
        Dashboards
      </button>
      <button
        className={`subtab-btn ${activeSubtab === 'incidents' ? 'active' : ''}`}
        data-subtab="incidents"
        data-parent="grafana"
        onClick={() => onSubtabChange('incidents')}
      >
        Incidents
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
