import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useHealthStore } from '@/stores';

// Navigation components
import { TabBar } from './components/Navigation/TabBar';
import { TabRouter } from './components/Navigation/TabRouter';

// Sidepanel component
import { Sidepanel } from './components/Sidepanel';

// UI Components
import { EmbeddingMismatchWarning } from './components/ui/EmbeddingMismatchWarning';
import { ErrorBoundary } from '@/components/ui/ErrorBoundary';
import { SubtabErrorFallback } from '@/components/ui/SubtabErrorFallback';

// Hooks
import { useAppInit, useModuleLoader, useApplyButton, useTheme } from '@/hooks';

// Import errorHelpers to expose window.ErrorHelpers BEFORE legacy modules load
import '@/utils/errorHelpers';
// Import api/client to expose window.CoreUtils BEFORE legacy modules load
// This replaces /modules/core-utils.js
import '@/api/client';
// Import uiHelpers to expose window.UiHelpers BEFORE legacy modules load
// This replaces /modules/ui-helpers.js (Zustand-backed)
import '@/utils/uiHelpers';

function App() {
  const [healthDisplay, setHealthDisplay] = useState('—');
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const { status, checkHealth } = useHealthStore();
  const navigate = useNavigate();

  // Initialize hooks
  const { isInitialized, initError } = useAppInit();
  const { modulesLoaded, loadError, loadProgress } = useModuleLoader();
  const { handleApply: handleSaveAllChanges, isDirty, isSaving, saveError } = useApplyButton();

  // Initialize theme - exposes window.Theme for legacy modules
  useTheme();

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

  // Load legacy modules for backward compatibility with existing tabs
  // This ensures window.* globals are available for tabs that haven't been refactored yet
  useEffect(() => {
    const loadModules = async () => {
      console.log('[App] DOM ready, loading legacy modules...');

      try {
        // Load in dependency order
        // 1. Core utilities (must load first)
        // MIGRATED: fetch-shim.js removed - was no-op (Phase 2.5)
        // MIGRATED: core-utils.js → /api/client.ts (exposes window.CoreUtils)
        // MIGRATED: ui-helpers.js → /utils/uiHelpers.ts (Zustand-backed, exposes window.UiHelpers)
        // MIGRATED: theme.js → /hooks/useTheme.ts (UIStore-backed, exposes window.Theme)

        // 2. Test instrumentation (for debugging)
        // @ts-ignore - legacy JS module (no exports)
        await import('./modules/test-instrumentation.js');

        // 4. Navigation and tabs - REMOVED, now using React Router
        // Legacy navigation modules replaced by TabBar/TabRouter components

        // 5. Search and tooltips (UI enhancements)
        // @ts-ignore - legacy JS modules (no exports)
        await import('./modules/search.js');
        // @ts-ignore - legacy JS module
        await import('./modules/tooltips.js');

        // 6. Configuration and health (backend integration)
        // @ts-ignore - legacy JS modules (no exports)
        await import('./modules/config.js');
        // @ts-ignore - legacy JS module
        await import('./modules/health.js');

        // 7. Feature modules (ensure feedback tools load before chat)
        // @ts-ignore - legacy JS module
        await import('./modules/reranker.js');
        await Promise.all([
          // @ts-ignore - legacy JS modules (no exports, attach to window)
          import('./modules/git-hooks.js'),
          // @ts-ignore
          import('./modules/git-commit-meta.js'),
          // @ts-ignore
          import('./modules/keywords.js'),
          // @ts-ignore
          import('./modules/autotune.js'),
          // @ts-ignore
          import('./modules/editor.js'),
          // @ts-ignore
          import('./modules/editor-settings.js'),
          // @ts-ignore
          import('./modules/secrets.js'),
          // @ts-ignore
          import('./modules/model_flows.js'),
          // @ts-ignore
          import('./modules/index_status.js'),
          // @ts-ignore
          import('./modules/mcp_rag.js'),
          // @ts-ignore
          import('./modules/mcp_server.js'),
          // REMOVED: Legacy JS indexing modules - IndexingSubtab now uses pure React/TypeScript
          // import('./modules/index_profiles.js'),
          // import('./modules/indexing.js'),
          // import('./modules/simple_index.js'),
          // @ts-ignore
          import('./modules/docker.js'),
          // @ts-ignore
          import('./modules/grafana.js'),
          // @ts-ignore
          import('./modules/vscode.js'),
          // @ts-ignore
          import('./modules/onboarding.js'),
          // @ts-ignore
          import('./modules/index-display.js'),
          // @ts-ignore
          import('./modules/cards_builder.js'),
          // @ts-ignore
          import('./modules/cost_logic.js'),
          // @ts-ignore
          import('./modules/storage-calculator-template.js'),
          // @ts-ignore
          import('./modules/storage-calculator.js'),
          // @ts-ignore
          import('./modules/profile_logic.js'),
          // @ts-ignore
          import('./modules/profile_renderer.js'),
          // @ts-ignore
          import('./modules/autoprofile_v2.js'),
          // REMOVED: Legacy JS modules - EvaluateSubtab now uses pure React/TypeScript
          // import('./modules/golden_questions.js'),
          // import('./modules/eval_runner.js'),
          // @ts-ignore
          import('./modules/eval_history.js'),
          // MIGRATED: error-helpers.js → /utils/errorHelpers.ts (exposes window.ErrorHelpers)
          // @ts-ignore
          import('./modules/layout_fix.js'),
          // @ts-ignore
          import('./modules/live-terminal.js'),
          // @ts-ignore
          import('./modules/trace.js'),
          // @ts-ignore
          import('./modules/ux-feedback.js'),
          // @ts-ignore
          import('./modules/langsmith.js'),
          // @ts-ignore
          import('./modules/dino.js')
        ]);

        // 8. Main app coordinator (must load last)
        // @ts-ignore - legacy JS module
        await import('./modules/app.js');

        console.log('[App] All legacy modules loaded successfully');

        // Dispatch a custom event so modules know React is ready
        window.dispatchEvent(new Event('react-ready'));
      } catch (err) {
        console.error('[App] Error loading modules:', err);
      }
    };

    // Give React a tick to render before loading modules
    setTimeout(loadModules, 100);
  }, []);

  // Show loading screen while modules are loading
  if (!modulesLoaded || !isInitialized) {
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
          {loadProgress || 'Loading application...'}
        </div>
        {(loadError || initError) && (
          <div style={{ color: 'var(--err)', fontSize: '12px', marginTop: '12px', maxWidth: '400px', textAlign: 'center' }}>
            {loadError || initError}
          </div>
        )}
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
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
          <input id="global-search" type="search" placeholder="Search settings (Ctrl+K)" />
          <div id="search-results"></div>
          <select
            id="theme-mode"
            name="THEME_MODE"
            title="Theme Mode"
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

      {/* Main Layout */}
      <div className="layout">
        <div className="resize-handle"></div>
        <div className="content" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
          {/* Tab Bar - React Router navigation */}
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

          {/* Scrollable content wrapper */}
          <div style={{ flex: 1, overflowY: 'auto' }}>
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

        {/* Sidepanel */}
        <div className="sidepanel" id="sidepanel">
          <div className="sidepanel-header">
            <h3 className="sidepanel-title" id="sidepanel-title">Settings</h3>
          </div>
          <div id="sidepanel-content" style={{flex: 1, overflowY: 'auto', padding: '20px'}}>
            {/* React Sidepanel component with all widgets */}
            <ErrorBoundary
              context="sidepanel"
              fallback={({ error, reset }) => (
                <SubtabErrorFallback
                  title="Sidepanel failed to render"
                  context="An error inside the Settings sidepanel prevented it from mounting."
                  error={error}
                  onRetry={reset}
                />
              )}
            >
            <Sidepanel />
            </ErrorBoundary>
          </div>
        </div>
      </div>
    </>
  );
}

export default App;
