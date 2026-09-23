import { createElement, isValidElement, useCallback, useEffect, useLayoutEffect, useRef } from 'react';
import { Route, Routes } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';
import type { DockTarget } from '@/stores/useDockStore';
import { useDockStore } from '@/stores/useDockStore';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback';

type DockViewProps = {
  target: DockTarget;
};

function IframeDockView({ target }: DockViewProps) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const reportedTarget = useRef<DockTarget | null>(null);
  const loading = useRef(true);

  const syncLocation = useCallback(() => {
    const frame = frameRef.current;
    if (!frame || loading.current) return;
    let url: URL;
    try {
      url = new URL(frame.contentWindow!.location.href);
    } catch {
      // A login redirect or an external document is not a dockable app route.
      return;
    }
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/web/')) return;
    const path = url.pathname.slice('/web'.length);
    const route = getRouteByPath(path);
    if (!route) return;
    url.searchParams.delete('embed');
    url.searchParams.delete('dock');
    const { docked, setDocked } = useDockStore.getState();
    if (!docked || docked.renderMode !== 'iframe') return;
    const subtabTitle = route.subtabs?.find((tab) => tab.id === url.searchParams.get('subtab'))?.title;
    if (docked.path === path && docked.search === url.search && docked.subtabTitle === subtabTitle) return;
    const next: DockTarget = {
      path, search: url.search, label: route.label, icon: route.icon,
      subtabTitle, renderMode: 'iframe',
    };
    reportedTarget.current = next;
    setDocked(next, { rememberLast: false });
  }, []);

  useLayoutEffect(() => {
    // Updating the parent's saved location must not reload the live workspace.
    // Only an external selection (chooser, Swap, undo) navigates the frame.
    if (target === reportedTarget.current || !frameRef.current) return;
    const url = new URL('/web' + target.path + target.search, window.location.origin);
    url.searchParams.set('embed', '1');
    url.searchParams.set('dock', '1');
    reportedTarget.current = null;
    loading.current = true;
    frameRef.current.src = url.href;
  }, [target]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frameRef.current?.contentWindow) return;
      if (event.data !== 'ragweld:dock-location') return;
      // Read the actual same-origin URL, never a URL supplied by message data.
      syncLocation();
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [syncLocation]);

  return (
      <iframe
        ref={frameRef}
        data-testid="dock-iframe"
        title={`${target.label}${target.subtabTitle ? ` — ${target.subtabTitle}` : ''}`}
        onLoad={() => { loading.current = false; syncLocation(); }}
        loading="lazy"
        style={{
          width: '100%',
          height: '100%',
          border: 0,
          background: 'var(--bg)',
        }}
      />
  );
}

export function DockView({ target }: DockViewProps) {
  if (target.renderMode === 'iframe') {
    return <IframeDockView target={target} />;
  }

  const route = getRouteByPath(target.path);
  if (!route) {
    return (
      <div data-testid="dock-native" style={{ padding: '16px', color: 'var(--fg-muted)' }}>
        Unknown dock target: <code>{target.path}</code>
      </div>
    );
  }

  const element = isValidElement(route.element)
    ? route.element
    : createElement(route.element as any);

  // NOTE: React Router does not allow nesting a <Router> (e.g., MemoryRouter) inside another <Router>.
  // To give docked content the correct "virtual" location/search params, render it under a <Routes>
  // with an overridden `location` prop instead.
  const dockLocation = {
    pathname: target.path,
    search: target.search ?? '',
    hash: '',
    state: null,
    key: 'dock',
  };

  return (
    <div
      data-testid="dock-native"
      className="dock-native"
      style={{
        // Column flex with a definite height so a docked page's `.tab-content`
        // (flex: 1; height: 0; overflow-y: auto) is its own scroll container
        // exactly as in the main pane (2026-08-25 finding M3).
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        overflow: 'hidden',
      }}
    >
      <Routes location={dockLocation as any}>
        <Route
          path={target.path}
          element={
            <ErrorBoundary
              context={`dock:${target.path}`}
              fallback={({ error, reset }) => (
                <div className="p-4">
                  <SubtabErrorFallback
                    title="Docked view crashed"
                    context={`Route path: ${target.path}`}
                    error={error}
                    onRetry={reset}
                  />
                </div>
              )}
            >
              {element}
            </ErrorBoundary>
          }
        />
      </Routes>
    </div>
  );
}
