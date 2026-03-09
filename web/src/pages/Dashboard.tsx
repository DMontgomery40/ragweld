// TriBridRAG - Dashboard Page
// Main dashboard with System Status, Monitoring, Storage, Help, and Glossary subtabs

import { useEffect } from 'react';
import { useSubtab } from '@/hooks';
import { DashboardSubtabs } from '../components/Dashboard/DashboardSubtabs';
import { SystemStatusSubtab } from '../components/Dashboard/SystemStatusSubtab';
import { MonitoringSubtab } from '../components/Dashboard/MonitoringSubtab';
import { StorageSubtab } from '../components/Dashboard/StorageSubtab';
import { HelpSubtab } from '../components/Dashboard/HelpSubtab';
import { GlossarySubtab } from '../components/Dashboard/GlossarySubtab';

export function Dashboard() {
  const { activeSubtab, setSubtab } = useSubtab<string>({ routePath: '/dashboard', defaultSubtab: 'system' });

  // Flag for legacy modules so they can avoid mutating React-rendered dashboard DOM
  useEffect(() => {
    (window as any).__TRIBRID_REACT_DASHBOARD__ = true;
    window.dispatchEvent(new CustomEvent('react-dashboard-ready'));
    return () => {
      delete (window as any).__TRIBRID_REACT_DASHBOARD__;
      window.dispatchEvent(new CustomEvent('react-dashboard-unmount'));
    };
  }, []);

  return (
    <div
      id="tab-dashboard"
      className="tab-content"
      data-react-dashboard="true"
    >
      {/* Subtab navigation */}
      <DashboardSubtabs activeSubtab={activeSubtab} onSubtabChange={setSubtab} />

      {/* System Status Subtab */}
      <div style={{ display: activeSubtab === 'system' ? 'block' : 'none' }}>
        {activeSubtab === 'system' ? <SystemStatusSubtab /> : null}
      </div>

      {/* Monitoring Subtab */}
      <div style={{ display: activeSubtab === 'monitoring' ? 'block' : 'none' }}>
        {activeSubtab === 'monitoring' ? <MonitoringSubtab /> : null}
      </div>

      {/* Storage Subtab */}
      <div style={{ display: activeSubtab === 'storage' ? 'block' : 'none' }}>
        {activeSubtab === 'storage' ? <StorageSubtab /> : null}
      </div>

      {/* Help Subtab */}
      <div style={{ display: activeSubtab === 'help' ? 'block' : 'none' }}>
        <HelpSubtab />
      </div>

      {/* Glossary Subtab */}
      <div style={{ display: activeSubtab === 'glossary' ? 'block' : 'none' }}>
        <GlossarySubtab />
      </div>
    </div>
  );
}
