// TriBridRAG - TabBar Component
// Vertical sidebar navigation for Warm Instrument theme

import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { useDockStore } from '@/stores';
import { getRouteByPath, routes } from '@/config/routes';
import { DOCK_DEFAULT_MODE_BY_PATH } from '@/config/dockCatalog';
import type { DockTarget } from '@/stores/useDockStore';

interface TabBarProps {
  mobileOpen?: boolean;
  onNavigate?: () => void;
}

const TAB_ROUTES = [...routes]
  .filter((r) => r.nav?.visible !== false)
  .sort((a, b) => (a.order - b.order) || a.label.localeCompare(b.label));

export function TabBar({ mobileOpen = false, onNavigate }: TabBarProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const docked = useDockStore((s) => s.docked);
  const setDocked = useDockStore((s) => s.setDocked);
  const setMode = useDockStore((s) => s.setMode);

  const handleClick = () => {
    // Close mobile menu after navigation
    if (onNavigate) onNavigate();
  };

  const pinned = (path: string) => (docked?.path === path ? ' 📌' : '');

  // Pointing at (or tabbing to) a lazily split workspace starts downloading its code, so the
  // click that usually follows does not wait on the network. import() caches the module, so
  // repeated hovers cost nothing; a failed prefetch is retried by the real navigation.
  const prefetch = (route: (typeof TAB_ROUTES)[number]) => () => {
    if (!route.prefetch) return;
    route.prefetch().catch(() => {});
  };

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
    <nav
      data-testid="tab-bar"
      className={`tab-bar ${mobileOpen ? 'mobile-open' : ''}`}
    >
      {TAB_ROUTES.map((route) => (
        <NavLink
          key={route.path}
          to={route.path}
          className={({ isActive }) =>
            [isActive ? 'active' : '', route.nav?.className ?? ''].filter(Boolean).join(' ')
          }
          onClick={handleDockAwareClick(route.path)}
          onMouseEnter={prefetch(route)}
          onFocus={prefetch(route)}
          title={route.nav?.title}
          // The link's name is its visible label. Two of the nine links carry a
          // `nav.title` description sentence, and that sentence was what assistive tech
          // announced ("Visible benchmark surface for runtime and prompt-regression
          // triage" instead of "Benchmark"), so the sidebar read inconsistently
          // (M-161/A-07). The description stays as the hover/`title` text.
          // `title` already carries the description for both pointer and AT users;
          // `aria-description` is still a draft attribute with thin support, so it
          // promised more than it delivered.
          aria-label={route.label}
        >
          {route.label}
          {pinned(route.path)}
        </NavLink>
      ))}
    </nav>
  );
}
