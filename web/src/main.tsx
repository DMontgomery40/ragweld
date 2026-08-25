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
// Inter is self-hosted; the workbench must not fetch fonts from Google at runtime
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/inter/800.css'
// CSS MUST be loaded in exact order to match /gui for ADA compliance
import './styles/tokens.css'
import './styles/main.css' // Inline styles from /gui/index.html
import './styles/style.css'
import './styles/global.css'
import './styles/learning-studio.css'
import './styles/micro-interactions.css'
import './styles/storage-calculator.css'
import './styles/slider-polish.css' // Range input polish for onboarding sliders

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

const BUILD_BASE = normalizeBuildBase(import.meta.env.VITE_BUILD_BASE);
const ROUTER_BASENAME = deriveRouterBasename(import.meta.env.VITE_ROUTER_BASENAME, BUILD_BASE);

function renderApp() {
  ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
      <BrowserRouter
        basename={ROUTER_BASENAME}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
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

renderApp();
