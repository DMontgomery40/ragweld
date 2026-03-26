import React from 'react';
import { useSubtab } from '@/hooks';
import { GrafanaSubtabs } from '../Grafana/GrafanaSubtabs';
import { GrafanaDashboard } from '../Grafana/GrafanaDashboard';
import { GrafanaConfig } from '../Grafana/GrafanaConfig';
import { ObservabilityOperatorDeck } from '../Observability/OperatorDeck';
import { ObservabilityIncidentsBoard } from '../Observability/IncidentsBoard';

type GrafanaSubtab = 'overview' | 'dashboards' | 'incidents' | 'config';

export default function GrafanaTab(): React.ReactElement {
  const { activeSubtab, setSubtab } = useSubtab<GrafanaSubtab>({ routePath: '/grafana', defaultSubtab: 'overview' });

  return (
    <div id="tab-grafana" className="tab-content" style={{ padding: 0, overflow: 'hidden' }}>
      <GrafanaSubtabs activeSubtab={activeSubtab} onSubtabChange={(s) => setSubtab(s as GrafanaSubtab)} />

      <div
        id="tab-grafana-overview"
        className={`section-subtab ${activeSubtab === 'overview' ? 'active' : ''}`}
        style={{ padding: '24px' }}
      >
        <ObservabilityOperatorDeck
          title="Grafana Command Center"
          subtitle="Overview first: active incidents, cross-stack health, recent evidence, and ML-quality regression context before you dive into a specific dashboard."
        />
      </div>

      <div
        id="tab-grafana-dashboards"
        className={`section-subtab fullscreen ${activeSubtab === 'dashboards' ? 'active' : ''}`}
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

      <div
        id="tab-grafana-incidents"
        className={`section-subtab ${activeSubtab === 'incidents' ? 'active' : ''}`}
        style={{ padding: '24px' }}
      >
        <ObservabilityIncidentsBoard />
      </div>

      <div
        id="tab-grafana-config"
        className={`section-subtab ${activeSubtab === 'config' ? 'active' : ''}`}
        style={{ padding: '24px' }}
      >
        <GrafanaConfig />
      </div>
    </div>
  );
}
