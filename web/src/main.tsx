import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback'
// CSS MUST be loaded in exact order to match /gui for ADA compliance
import './styles/tokens.css'
import './styles/main.css' // Inline styles from /gui/index.html
// inline-gui-styles.css is intentionally not imported due to duplicate/invalid blocks.
import './styles/style.css'
import './styles/global.css'
import './styles/micro-interactions.css'
import './styles/storage-calculator.css'
import './styles/slider-polish.css' // Range input polish for onboarding sliders

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <BrowserRouter basename="/web">
      <ErrorBoundary
        context="app-root"
        fallback={({ error, reset }) => (
          <div className="min-h-screen bg-bg p-6 text-fg">
            <SubtabErrorFallback
              title="AGRO failed to initialize"
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
