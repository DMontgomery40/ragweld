import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '@/stores';

// Navigation components
import { TabBar } from './components/Navigation/TabBar';
import { TabRouter } from './components/Navigation/TabRouter';
import { Breadcrumbs } from './components/Navigation/Breadcrumbs';

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

function App() {
  const [healthDisplay, setHealthDisplay] = useState('—');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
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

  useEffect(() => {
    // Initial health check
    checkHealth();

    // Poll health status
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
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
      <div style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        background: 'var(--bg)',
        color: 'var(--fg)'
      }}>
        <div style={{
          width: '48px',
          height: '48px',
          border: '3px solid var(--line)',
          borderTopColor: 'var(--accent)',
          borderRadius: '50%',
          animation: 'spin 1s linear infinite',
          marginBottom: '16px'
        }}></div>
        <div style={{ fontSize: '14px', color: 'var(--fg-muted)' }}>
          Loading application...
        </div>
        {initError && (
          <div style={{ color: 'var(--err)', fontSize: '12px', marginTop: '12px', maxWidth: '400px', textAlign: 'center' }}>
            {initError}
          </div>
        )}
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (isEmbed) {
    return (
      <div style={{ height: '100vh', background: 'var(--bg)', color: 'var(--fg)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ flex: 1, minHeight: 0, overflow: 'auto' }}>
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
          <span className="brand">TriBrid RAG</span>
          <span className="tagline">Vector + Sparse + Graph</span>
        </h1>
        <div className="top-actions">
          <button
            id="btn-learn"
            title="Open Parameter Glossary"
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
            onClick={() => navigate('/dashboard?subtab=glossary')}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"></circle>
              <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"></path>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            <span>Learn</span>
          </button>
          <GlobalSearch />
          <select
            id="theme-mode"
            name="THEME_MODE"
            title="Theme Mode"
            value={theme}
            onChange={(e) => applyTheme(e.target.value as any)}
            style={{
              background: 'var(--input-bg)',
              color: 'var(--fg)',
              border: '1px solid var(--line)',
              padding: '6px 8px',
              borderRadius: '6px'
            }}
          >
            <option value="auto">Auto</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
          </select>
          <button id="btn-health" onClick={checkHealth}>Health</button>
          <span id="health-status">{healthDisplay}</span>
        </div>
      </div>

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
            <div style={{ flex: 1, overflowY: 'auto', paddingBottom: '60px' }}>
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
            <div className="action-buttons" style={{
              background: 'var(--bg)',
              padding: '12px 24px',
              borderTop: '1px solid var(--accent)',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              gap: '16px',
            }}>
              <button
                id="save-btn"
                onClick={handleSaveAllChanges}
                disabled={!isDirty || isSaving}
                style={{
                  opacity: (!isDirty || isSaving) ? 0.6 : 1,
                  cursor: (!isDirty || isSaving) ? 'not-allowed' : 'pointer'
                }}
              >
                {isSaving ? 'Saving...' : 'Apply All Changes'}
                {isDirty && !isSaving && ' *'}
              </button>
              {saveError && (
                <span style={{ color: 'var(--err)', marginLeft: '12px' }}>
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
          className="sidepanel"
          id="sidepanel"
          style={{
            padding: 0,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            background: 'var(--card-bg)',
          }}
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
