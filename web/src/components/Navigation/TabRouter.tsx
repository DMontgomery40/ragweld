// AGRO - TabRouter Component
// Routes configuration for all tabs

import { Routes, Route, Navigate } from 'react-router-dom';
import { routes } from '../../config/routes';
import { createElement, isValidElement } from 'react';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback';

export function TabRouter() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      {routes.map(route => {
        // Handle both component types and elements
        const element = isValidElement(route.element)
          ? route.element
          : createElement(route.element as any);

        const wrappedElement = (
          <ErrorBoundary
            context={`route:${route.path}`}
            fallback={({ error, reset }) => (
              <div className="p-6">
                <SubtabErrorFallback
                  title={`${route.label} tab crashed`}
                  context={`Route path: ${route.path}`}
                  error={error}
                  onRetry={reset}
                />
              </div>
            )}
          >
            {element}
          </ErrorBoundary>
        );

        return (
          <Route key={route.path} path={route.path} element={wrappedElement} />
        );
      })}
    </Routes>
  );
}
