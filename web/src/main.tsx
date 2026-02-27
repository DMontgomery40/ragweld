import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback'
import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/700.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
// CSS MUST be loaded in exact order to match /gui for ADA compliance
import './styles/tokens.css'
import './styles/main.css' // Inline styles from /gui/index.html
// inline-gui-styles.css is intentionally not imported due to duplicate/invalid blocks.
import './styles/style.css'
import './styles/global.css'
import './styles/learning-studio.css'
import './styles/micro-interactions.css'
import './styles/storage-calculator.css'
import './styles/slider-polish.css' // Range input polish for onboarding sliders

type DemoMswMode = 'off' | 'partial' | 'full';

function normalizeBuildBase(input: string | undefined): string {
  const raw = String(input || '').trim() || '/web/';
  let normalized = raw.startsWith('/') ? raw : `/${raw}`;
  normalized = normalized.replace(/\/{2,}/g, '/');
  if (!normalized.endsWith('/')) normalized += '/';
  return normalized;
}

function deriveRouterBasename(input: string | undefined, buildBase: string): string {
  const raw = String(input || '').trim();
  if (raw) {
    let normalized = raw.startsWith('/') ? raw : `/${raw}`;
    normalized = normalized.replace(/\/{2,}/g, '/').replace(/\/+$/, '');
    return normalized || '/';
  }
  return buildBase.replace(/\/+$/, '') || '/';
}

function resolveWorkerUrl(basename: string): string {
  if (basename === '/') return '/mockServiceWorker.js';
  return `${basename}/mockServiceWorker.js`;
}

function isWithinBasename(pathname: string, basename: string): boolean {
  if (basename === '/') return true;
  if (pathname === basename) return true;
  return pathname.startsWith(`${basename}/`);
}

const BUILD_BASE = normalizeBuildBase(import.meta.env.VITE_BUILD_BASE);
const ROUTER_BASENAME = deriveRouterBasename(import.meta.env.VITE_ROUTER_BASENAME, BUILD_BASE);
const rawMswMode = String(import.meta.env.VITE_DEMO_MSW_MODE || 'off').toLowerCase();
const DEMO_MSW_MODE: DemoMswMode =
  rawMswMode === 'partial' || rawMswMode === 'full' || rawMswMode === 'off'
    ? rawMswMode
    : 'off';

async function enableMockingIfConfigured(): Promise<void> {
  if (DEMO_MSW_MODE === 'off') return;
  if (!isWithinBasename(window.location.pathname, ROUTER_BASENAME)) return;

  const params = new URLSearchParams(window.location.search || '');
  const forceFullMode = params.get('mock') === '1';
  const mode: DemoMswMode = forceFullMode ? 'full' : DEMO_MSW_MODE;

  const { worker } = await import('./mocks/browser');
  const { handlersFull, handlersPartial } = await import('./mocks/handlers');
  worker.resetHandlers(...(mode === 'full' ? handlersFull : handlersPartial));

  await worker.start({
    serviceWorker: {
      url: resolveWorkerUrl(ROUTER_BASENAME),
    },
    onUnhandledRequest: 'bypass',
    quiet: true,
  });
}

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter basename={ROUTER_BASENAME}>
        <ErrorBoundary
          context="app-root"
          fallback={({ error, reset }) => (
            <div className="min-h-screen bg-bg p-6 text-fg">
              <SubtabErrorFallback
                title="Tri-Brid RAG failed to initialize"
                context="A fatal error occurred while bootstrapping the workspace."
                error={error}
                retryLabel="Reload application"
                onRetry={() => {
                  reset()
                  window.location.reload()
                }}
                className="mx-auto w-full max-w-3xl"
              />
            </div>
          )}
        >
          <App />
        </ErrorBoundary>
      </BrowserRouter>
    </React.StrictMode>,
  )
}

enableMockingIfConfigured()
  .catch((error) => {
    console.error('[MSW] Failed to initialize mock worker:', error);
  })
  .finally(() => {
    renderApp();
  })
