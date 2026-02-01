import React, { useState } from 'react';
import { GrafanaSubtabs } from '../Grafana/GrafanaSubtabs';
import { GrafanaDashboard } from '../Grafana/GrafanaDashboard';
import { GrafanaConfig } from '../Grafana/GrafanaConfig';

export default function GrafanaTab(): React.ReactElement {
  const [activeSubtab, setActiveSubtab] = useState<string>('dashboard');

  return (
    <div id="tab-grafana" className="tab-content" style={{ padding: 0, overflow: 'hidden' }}>
      <GrafanaSubtabs activeSubtab={activeSubtab} onSubtabChange={setActiveSubtab} />

      <div
        id="tab-grafana-config"
        className={`section-subtab ${activeSubtab === 'config' ? 'active' : ''}`}
        style={{ padding: '24px' }}
      >
        <GrafanaConfig />
      </div>

      <div
        id="tab-grafana-dashboard"
        className={`section-subtab fullscreen ${activeSubtab === 'dashboard' ? 'active' : ''}`}
        style={{ flex: 1, minHeight: 0 }}
      >
        <div
          id="grafana-embed"
          style={{
            display: 'flex',
            flex: 1,
            minHeight: 0,
            overflow: 'hidden',
            background: 'var(--card-bg)',
          }}
        >
          <GrafanaDashboard />
        </div>
      </div>
    </div>
  );
}
