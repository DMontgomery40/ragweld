import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '@/stores';

// Navigation components
import { TabBar } from './components/Navigation/TabBar';
import { TabRouter } from './components/Navigation/TabRouter';
import { Breadcrumbs } from './components/Navigation/Breadcrumbs';
import { CorpusParamGuard, DocumentTitle } from './components/Navigation/RouteGuards';

// Right panel (Dock / Settings)
import { DockPanel } from './components/Dock/DockPanel';

// UI Components
import { EmbeddingMismatchWarning } from './components/ui/EmbeddingMismatchWarning';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback';

// Hooks
import { useAppInit, useApplyButton, useTheme } from '@/hooks';
import { GlobalSearch } from '@/components/Search/GlobalSearch';
import { UiHelpers } from '@/utils/uiHelpers';
import { CorpusRegistry } from '@/components/ui/CorpusRegistry';
import { useRepoStore } from '@/stores/useRepoStore';

/** How often a VISIBLE tab re-checks health. Unchanged from the original interval. */
const HEALTH_POLL_INTERVAL_MS = 30_000;

function App() {
  const [healthDisplay, setHealthDisplay] = useState('—');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [showCorpusRegistry, setShowCorpusRegistry] = useState(false);
  const activeRepo = useRepoStore((state) => state.activeRepo);
  const corpusName = useRepoStore(
    (state) => state.repos.find((repo) => repo.corpus_id === state.activeRepo)?.name,
  );
  const { status, checkHealth } = useHealthStore();
  const navigate = useNavigate();
  const isEmbed = new URLSearchParams(window.location.search).get('embed') === '1';

  // Initialize hooks
  const { isInitialized, initError } = useAppInit();
  const { handleApply: handleSaveAllChanges, isDirty, isSaving, saveError } = useApplyButton();

  // Initialize theme
  const { theme, applyTheme } = useTheme();

  // Bind resizable sidepanel AFTER the layout (and handle) is mounted.
  // Note: `useAppInit()` can flip isInitialized before the main layout renders, so we
  // retry briefly until the `.resize-handle` exists.
  useEffect(() => {
    if (isEmbed) return;
    if (!isInitialized) return;

    let cancelled = false;
    let attempts = 0;
    const maxAttempts = 60; // ~3s @ 50ms

    const tick = () => {
      if (cancelled) return;

      const handle = document.querySelector('.resize-handle') as HTMLElement | null;
      if (handle?.dataset?.sidepanelResizeBound === '1') return;

      try {
        UiHelpers.bindResizableSidepanel();
      } catch (e) {
        // best effort: keep retrying until layout exists
        console.warn('[App] Failed to bind resizable sidepanel', e);
      }

      attempts += 1;
      if (attempts < maxAttempts) {
        setTimeout(tick, 50);
      }
    };

    tick();
    return () => {
      cancelled = true;
    };
  }, [isEmbed, isInitialized]);

  // Toggle mobile navigation
  const toggleMobileNav = () => {
    setMobileNavOpen(prev => !prev);
  };

  // Close mobile nav when clicking outside or navigating
  const closeMobileNav = () => {
    setMobileNavOpen(false);
  };

  // Health polling follows the tab's visibility. A tab nobody is looking at has nothing to
  // report, and the drive found an idle Chat page still paying for a header no one could
  // see - every probe also shipping a Faro event with it (M-130/B-35). Becoming visible
  // re-checks immediately, so the indicator is never stale on return.
  useEffect(() => {
    let interval: number | undefined;

    const stopPolling = () => {
      if (interval === undefined) return;
      window.clearInterval(interval);
      interval = undefined;
    };

    const syncToVisibility = () => {
      if (document.visibilityState === 'hidden') {
        stopPolling();
        return;
      }
      checkHealth();
      if (interval === undefined) {
        interval = window.setInterval(checkHealth, HEALTH_POLL_INTERVAL_MS);
      }
    };

    syncToVisibility();
    document.addEventListener('visibilitychange', syncToVisibility);
    return () => {
      document.removeEventListener('visibilitychange', syncToVisibility);
      stopPolling();
    };
  }, [checkHealth]);

  useEffect(() => {
    if (status) {
      const isOk = status.ok || status.status === 'healthy';
      const timestamp = status.ts ? new Date(status.ts).toLocaleTimeString() : new Date().toLocaleTimeString();
      setHealthDisplay(isOk ? `OK @ ${timestamp}` : 'Not OK');
    }
  }, [status]);

  // Show loading screen while app initializes
  if (!isInitialized) {
    return (
      <div className="app-loading-screen">
        <div className="app-loading-spinner"></div>
        <div className="app-loading-message">Loading application...</div>
        {initError && (
          <div className="app-loading-error">{initError}</div>
        )}
      </div>
    );
  }

  if (isEmbed) {
    return (
      <div className="app-embed-root">
        <DocumentTitle />
        <div className="app-embed-scroll">
          <ErrorBoundary
            context="embed-tab-router"
            fallback={({ error, reset }) => (
              <div className="p-6">
                <SubtabErrorFallback
                  title="Unable to load embedded tab"
                  context={`Route path: ${window.location.pathname}`}
                  error={error}
                  onRetry={reset}
                />
              </div>
            )}
          >
            <TabRouter />
          </ErrorBoundary>
        </div>
      </div>
    );
  }

  return (
    <>
      <DocumentTitle />
      <CorpusParamGuard />
      {/* Topbar */}
      <div className="topbar">
        <button 
          className={`mobile-nav-toggle ${mobileNavOpen ? 'active' : ''}`} 
          id="mobile-nav-toggle" 
          aria-label="Toggle navigation"
          aria-expanded={mobileNavOpen}
          onClick={toggleMobileNav}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            {mobileNavOpen ? (
              <>
                <line x1="18" y1="6" x2="6" y2="18"></line>
                <line x1="6" y1="6" x2="18" y2="18"></line>
              </>
            ) : (
              <>
                <line x1="3" y1="6" x2="21" y2="6"></line>
                <line x1="3" y1="12" x2="21" y2="12"></line>
                <line x1="3" y1="18" x2="21" y2="18"></line>
              </>
            )}
          </svg>
        </button>
        <h1>
          <span className="brand">ragweld</span>
          <span className="tagline">Versioned Config · API / MCP</span>
        </h1>
        <div className="top-actions">
          {/* One name for one thing. This was labelled LEARN, named "Open Parameter
              Glossary" to assistive tech, and navigated to a tab called Glossary
              (M-160/A-39). */}
          <button
            id="btn-learn"
            title="Open the parameter glossary"
            className="icon-btn"
            onClick={() => navigate('/dashboard?subtab=glossary')}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <span>Glossary</span>
          </button>
          <button
            id="btn-corpus"
            className="icon-btn"
            data-testid="topbar-corpus"
            title={activeRepo ? `Corpus registry - active: ${activeRepo}` : 'Choose a corpus'}
            aria-haspopup="dialog"
            onClick={() => setShowCorpusRegistry(true)}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>
            </svg>
            <span>{corpusName || activeRepo || 'Choose corpus'}</span>
          </button>
          <GlobalSearch />
          <select
            id="theme-mode"
            name="THEME_MODE"
            title="Theme Mode"
            value={theme}
            onChange={(e) => applyTheme(e.target.value as any)}
            className="theme-mode-select"
          >
            <option value="auto">Auto</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
          <button id="btn-health" onClick={checkHealth}>Health</button>
          <span id="health-status">{healthDisplay}</span>
        </div>
      </div>

      {/* The corpus registry is reachable from every page through the top bar (M-163). */}
      <CorpusRegistry isOpen={showCorpusRegistry} onClose={() => setShowCorpusRegistry(false)} />

      {/* Main Layout - 3-column grid: sidebar | main | sidepanel */}
      <div className="layout">
        {/* Left sidebar (TabBar) */}
        <aside className={`sidebar ${mobileNavOpen ? 'mobile-open' : ''}`}>
          <ErrorBoundary
            context="tab-bar"
            fallback={({ error, reset }) => (
              <div className="p-4">
                <SubtabErrorFallback
                  title="Navigation failed to render"
                  context="The tab list crashed while initializing. Retry to re-mount navigation."
                  error={error}
                  onRetry={reset}
                />
              </div>
            )}
          >
            <TabBar mobileOpen={mobileNavOpen} onNavigate={closeMobileNav} />
          </ErrorBoundary>
        </aside>

        {/* Main content area */}
        <div className="main-content">
          <Breadcrumbs />
          <div className="content">
            {/* Scrollable content wrapper - paddingBottom reserves space above action-buttons */}
            <div className="content-scroll">
              {/* Routes - All tab routing */}
              <ErrorBoundary
                context="tab-router"
                fallback={({ error, reset }) => (
                  <div className="p-6">
                    <SubtabErrorFallback
                      title="Unable to load tab content"
                      context="The active route crashed during render. Retry to attempt a clean mount."
                      error={error}
                      onRetry={reset}
                    />
                  </div>
                )}
              >
                <TabRouter />
              </ErrorBoundary>
            </div>

            {/* Apply All Changes button - Fixed footer outside scrollable area */}
            <div className="action-buttons app-footer-actions">
              <button
                id="save-btn"
                onClick={handleSaveAllChanges}
                disabled={!isDirty || isSaving}
                className={!isDirty || isSaving ? 'is-disabled' : ''}
              >
                {isSaving ? 'Saving...' : 'Apply All Changes'}
                {isDirty && !isSaving && ' *'}
              </button>
              {saveError && (
                <span className="save-error-text">
                  Error: {saveError}
                </span>
              )}
              {/* Global embedding mismatch warning - appears next to Apply button */}
              <EmbeddingMismatchWarning variant="compact" />
            </div>
          </div>
        </div>

        {/* Resize handle */}
        <div className="resize-handle"></div>

        {/* Right panel */}
        <div
          className="sidepanel sidepanel-shell"
          id="sidepanel"
        >
          <ErrorBoundary
            context="dock-panel"
            fallback={({ error, reset }) => (
              <SubtabErrorFallback
                title="Right panel failed to render"
                context="An error inside the Dock/Settings panel prevented it from mounting."
                error={error}
                onRetry={reset}
              />
            )}
          >
            <DockPanel />
          </ErrorBoundary>
        </div>
      </div>
    </>
  );
}

export default App;
