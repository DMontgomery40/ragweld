// TriBridRAG - TabBar Component
// EXACT copy of /gui tab-bar structure

import { useEffect } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useDockStore } from '@/stores';
import { getRouteByPath } from '@/config/routes';
import { DOCK_DEFAULT_MODE_BY_PATH } from '@/config/dockCatalog';
import type { DockTarget } from '@/stores/useDockStore';

interface TabBarProps {
  mobileOpen?: boolean;
  onNavigate?: () => void;
}

export function TabBar({ mobileOpen = false, onNavigate }: TabBarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const docked = useDockStore((s) => s.docked);
  const setDocked = useDockStore((s) => s.setDocked);
  const setMode = useDockStore((s) => s.setMode);

  // Persist current tab for legacy compatibility + tests
  useEffect(() => {
    try {
      const rawPath = location.pathname.replace(/^\//, '');
      const withoutBase = rawPath.startsWith('web/') ? rawPath.slice('web/'.length) : rawPath;
      const currentTab = withoutBase.split('/')[0] || 'dashboard';
      localStorage.setItem('nav_current_tab', currentTab);
    } catch {
      // ignore localStorage errors
    }
  }, [location.pathname]);

  const handleClick = () => {
    // Close mobile menu after navigation
    if (onNavigate) onNavigate();
  };

  const pinned = (path: string) => (docked?.path === path ? ' 📌' : '');

  const buildCurrentMainTarget = (): DockTarget | null => {
    const route = getRouteByPath(location.pathname);
    if (!route) return null;
    const params = new URLSearchParams(location.search || '');
    const subtabId = params.get('subtab') || '';
    const subtabTitle =
      subtabId && Array.isArray(route.subtabs)
        ? route.subtabs.find((s) => s.id === subtabId)?.title
        : undefined;
    const renderMode = (DOCK_DEFAULT_MODE_BY_PATH[location.pathname] ?? 'iframe') as DockTarget['renderMode'];
    return {
      path: location.pathname,
      search: location.search || '',
      label: route.label,
      icon: route.icon,
      subtabTitle,
      renderMode,
    };
  };

  const handleDockAwareClick = (toPath: string) => (e: any) => {
    // If the user clicks the tab that is currently docked, swap instead of duplicating.
    if (docked && docked.path === toPath) {
      e.preventDefault();
      const current = buildCurrentMainTarget();
      if (current) {
        setDocked(current);
        setMode('dock');
      }
      navigate(docked.path + docked.search);
    }
    handleClick();
  };

  return (
    <div
      data-testid="tab-bar"
      className={`tab-bar ${mobileOpen ? 'mobile-open' : ''}`} 
      style={{ display: 'flex', gap: '8px', padding: '12px 24px', overflowX: 'auto' }}
    >
      <NavLink
        to="/start"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/start')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🚀 Get Started{pinned('/start')}
      </NavLink>
      
      <NavLink
        to="/dashboard"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/dashboard')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        📊 Dashboard{pinned('/dashboard')}
      </NavLink>

      <NavLink
        to="/chat"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/chat')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        💬 Chat{pinned('/chat')}
      </NavLink>

      <NavLink
        to="/grafana"
        className={({ isActive }) => `${isActive ? 'active' : ''} promoted-tab`}
        onClick={handleDockAwareClick('/grafana')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        📈 Grafana{pinned('/grafana')}
      </NavLink>

      <NavLink
        to="/benchmark"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/benchmark')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🏁 Benchmark{pinned('/benchmark')}
      </NavLink>

      <NavLink
        to="/rag"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/rag')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🧠 RAG{pinned('/rag')}
      </NavLink>

      <NavLink
        to="/eval"
        className={({ isActive }) => `${isActive ? 'active' : ''} keystone-tab`}
        onClick={handleDockAwareClick('/eval')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
        title="Deep-dive into evaluation runs with AI-powered analysis"
      >
        🔬 Eval Analysis{pinned('/eval')}
      </NavLink>

      {/* Profiles tab removed - banned feature per CLAUDE.md */}

      <NavLink
        to="/infrastructure"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/infrastructure')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        🔧 Infrastructure{pinned('/infrastructure')}
      </NavLink>

      <NavLink
        to="/admin"
        className={({ isActive }) => isActive ? 'active' : ''}
        onClick={handleDockAwareClick('/admin')}
        style={{
          background: 'var(--bg-elev2)',
          color: 'var(--fg-muted)',
          border: '1px solid var(--line)',
          padding: '9px 16px',
          borderRadius: '6px',
          cursor: 'pointer',
          fontSize: '13px',
          fontWeight: 500,
          whiteSpace: 'nowrap',
          transition: 'all 0.15s',
          minHeight: '44px',
          textDecoration: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
        }}
      >
        ⚙️ Admin{pinned('/admin')}
      </NavLink>
    </div>
  );
}
