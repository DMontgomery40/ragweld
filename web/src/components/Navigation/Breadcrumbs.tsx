// TriBridRAG - Breadcrumbs Component
// Shows current route > subtab path in main content header

import { useLocation } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';

export function Breadcrumbs() {
  const location = useLocation();
  const route = getRouteByPath(location.pathname);
  const params = new URLSearchParams(location.search);
  const subtabId = params.get('subtab');
  const subtab = route?.subtabs?.find(s => s.id === subtabId);

  return (
    <div className="breadcrumbs">
      <span>{route?.label || 'Home'}</span>
      {subtab && (
        <>
          <span className="sep">/</span>
          <span>{subtab.title}</span>
        </>
      )}
    </div>
  );
}
