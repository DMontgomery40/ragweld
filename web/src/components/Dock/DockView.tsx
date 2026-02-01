import { createElement, isValidElement } from 'react';
import { Route, Routes } from 'react-router-dom';
import { getRouteByPath } from '@/config/routes';
import type { DockTarget } from '@/stores/useDockStore';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback';

type DockViewProps = {
  target: DockTarget;
};

export function DockView({ target }: DockViewProps) {
  if (target.renderMode === 'iframe') {
    const src =
      '/web' +
      target.path +
      target.search +
      (target.search ? '&' : '?') +
      'embed=1&dock=1';

    return (
      <iframe
        data-testid="dock-iframe"
        title={`${target.label}${target.subtabTitle ? ` — ${target.subtabTitle}` : ''}`}
        src={src}
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
      style={{
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

