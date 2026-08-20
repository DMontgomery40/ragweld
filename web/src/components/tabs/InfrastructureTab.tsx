// TriBridRAG - Infrastructure Tab Component (React)
// Main Infrastructure configuration tab with subtab navigation
// Only the active subtab is mounted so hidden panels do not keep polling or own duplicate state.

import { useSubtab } from '@/hooks';
import { InfrastructureSubtabs } from '@/components/Infrastructure/InfrastructureSubtabs';
import { ServicesSubtab } from '@/components/Infrastructure/ServicesSubtab';
import { DockerSubtab } from '@/components/Infrastructure/DockerSubtab';
import { MCPSubtab } from '@/components/Infrastructure/MCPSubtab';
import { PathsSubtab } from '@/components/Infrastructure/PathsSubtab';
import { MonitoringSubtab } from '@/components/Infrastructure/MonitoringSubtab';

export default function InfrastructureTab() {
  const { activeSubtab, setSubtab } = useSubtab<string>({ routePath: '/infrastructure', defaultSubtab: 'services' });

  const activeContent = (() => {
    if (activeSubtab === 'docker') return <DockerSubtab />;
    if (activeSubtab === 'mcp') return <MCPSubtab />;
    if (activeSubtab === 'paths') return <PathsSubtab />;
    if (activeSubtab === 'monitoring') return <MonitoringSubtab />;
    return <ServicesSubtab />;
  })();

  return (
    <div id="tab-infrastructure" className="tab-content">
      {/* Subtab navigation */}
      <InfrastructureSubtabs activeSubtab={activeSubtab} onSubtabChange={setSubtab} />

      <div id={`tab-infrastructure-${activeSubtab}`} className="infrastructure-subtab-content active">
        {activeContent}
      </div>
    </div>
  );
}
