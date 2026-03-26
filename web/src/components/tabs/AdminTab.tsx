// TriBridRAG - Admin Tab Component (React)
// Main Admin configuration tab with subtab navigation
// Structure matches /gui/index.html exactly with all subtabs rendered and visibility controlled by className

import { useState } from 'react';

import { useSubtab } from '@/hooks';
import { AdminSubtabs } from '@/components/Admin/AdminSubtabs';
import { ConfigBasicsSubtab } from '@/components/Admin/ConfigBasicsSubtab';
import { ConfigExplorerSubtab } from '@/components/Admin/ConfigExplorerSubtab';
import { ConfigRawSubtab } from '@/components/Admin/ConfigRawSubtab';
import { DependenciesSubtab } from '@/components/Admin/DependenciesSubtab';

export default function AdminTab() {
  const { activeSubtab, setSubtab } = useSubtab<string>({ routePath: '/admin', defaultSubtab: 'basic' });
  const [rawSection, setRawSection] = useState<string | undefined>(undefined);

  const openRaw = (section: string) => {
    setRawSection(section);
    setSubtab('raw');
  };

  return (
    <div id="tab-admin" className="tab-content">
      {/* Subtab navigation */}
      <AdminSubtabs activeSubtab={activeSubtab} onSubtabChange={setSubtab} />

      {/* All subtabs rendered with visibility controlled by style */}
      <div id="tab-admin-basic" style={{ display: activeSubtab === 'basic' ? 'block' : 'none' }}>
        <ConfigBasicsSubtab onOpenRaw={openRaw} />
      </div>

      <div id="tab-admin-advanced" style={{ display: activeSubtab === 'advanced' ? 'block' : 'none' }}>
        <ConfigExplorerSubtab onOpenRaw={openRaw} />
      </div>

      <div id="tab-admin-raw" style={{ display: activeSubtab === 'raw' ? 'block' : 'none' }}>
        <ConfigRawSubtab selectedSection={rawSection} />
      </div>

      <div id="tab-admin-dependencies" style={{ display: activeSubtab === 'dependencies' ? 'block' : 'none' }}>
        <DependenciesSubtab />
      </div>
    </div>
  );
}
