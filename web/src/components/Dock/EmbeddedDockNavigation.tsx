import { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/** Notify the hosting Dock after router navigation, including Back/Forward. */
export function EmbeddedDockNavigation() {
  const location = useLocation();
  const navigate = useNavigate();
  const [isDock] = useState(() => window.parent !== window && new URLSearchParams(window.location.search).get('dock') === '1');
  useEffect(() => {
    if (!isDock) return;
    const params = new URLSearchParams(location.search);
    if (params.get('embed') !== '1' || params.get('dock') !== '1') {
      params.set('embed', '1');
      params.set('dock', '1');
      navigate({ pathname: location.pathname, search: `?${params}`, hash: location.hash }, { replace: true });
      return;
    }
    window.parent.postMessage('ragweld:dock-location', window.location.origin);
  }, [isDock, location.pathname, location.search, location.hash, navigate]);
  return null;
}
