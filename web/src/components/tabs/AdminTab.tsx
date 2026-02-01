// AGRO - Admin Tab Component (React)
// Main Admin configuration tab with subtab navigation
// Structure matches /gui/index.html exactly with all subtabs rendered and visibility controlled by className

import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { AdminSubtabs } from '@/components/Admin/AdminSubtabs';
import { GeneralSubtab } from '@/components/Admin/GeneralSubtab';
import { SecretsSubtab } from '@/components/Admin/SecretsSubtab';
import { IntegrationsSubtab } from '@/components/Admin/IntegrationsSubtab';

export default function AdminTab() {
  const [activeSubtab, setActiveSubtab] = useState('general');
  const [searchParams] = useSearchParams();
  const subtabParam = searchParams.get('subtab');

  // Read ?subtab=... (no writeback)
  useEffect(() => {
    if (!subtabParam) return;
    const allowed = new Set(['general', 'secrets', 'integrations']);
    if (allowed.has(subtabParam)) setActiveSubtab(subtabParam);
  }, [subtabParam]);

  return (
    <div id="tab-admin" className="tab-content">
      {/* Subtab navigation */}
      <AdminSubtabs activeSubtab={activeSubtab} onSubtabChange={setActiveSubtab} />

      {/* All subtabs rendered with visibility controlled by style */}
      <div id="tab-admin-general" style={{ display: activeSubtab === 'general' ? 'block' : 'none' }}>
        <GeneralSubtab />
      </div>

      <div id="tab-admin-secrets" style={{ display: activeSubtab === 'secrets' ? 'block' : 'none' }}>
        <SecretsSubtab />
      </div>

      <div id="tab-admin-integrations" style={{ display: activeSubtab === 'integrations' ? 'block' : 'none' }}>
        <IntegrationsSubtab />
      </div>
    </div>
  );
}
