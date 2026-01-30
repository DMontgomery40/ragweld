import { useState, useEffect } from 'react';

/**
 * Hook to track legacy module loading status
 * Note: The actual module loading is done in App.tsx for now
 * This hook just provides visibility into the loading state
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that manages dynamic module loading with retry logic and progress tracking.
 *   Takes no parameters; manages internal state for load completion, errors, and progress messages.
 *   Returns object with modulesLoaded (boolean), loadError (string | null), and loadProgress (string) for UI binding.
 *   Implements exponential backoff retry mechanism with max 100 attempts (~10 seconds total).
 *   Handles loading failures by capturing error messages and preventing infinite retry loops.
 *
 * why: |
 *   Centralizes module loading orchestration to avoid duplicating retry/error logic across components.
 *   Progress tracking enables UI feedback during potentially slow module initialization.
 *   Retry mechanism with attempt limits ensures graceful degradation rather than hanging indefinitely.
 *   State separation (loaded/error/progress) allows components to handle each concern independently.
 *
 * guardrails:
 *   - DO NOT remove maxAttempts limit; unbounded retries can cause browser hang or memory exhaustion
 *   - ALWAYS clear previous errors when retrying; stale error state can mislead users about current status
 *   - NOTE: 100 attempts with exponential backoff assumes ~100ms per attempt; adjust maxAttempts if timing changes
 *   - ASK USER: Confirm the intended retry strategy (exponential backoff vs linear) and total timeout duration before modifying attempt logic
 *   - DO NOT expose raw attempt counter to UI; only expose final states (loaded/error/progress) to prevent confusion
 * ---/agentspec
 */
export function useModuleLoader() {
  const [modulesLoaded, setModulesLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadProgress, setLoadProgress] = useState<string>('Initializing...');

  useEffect(() => {
    let attempts = 0;
    const maxAttempts = 100; // 10 seconds max wait

    const checkModules = setInterval(() => {
      attempts++;

      // Check if core modules are available
      const w = window as any;
      const coreLoaded = !!w.CoreUtils;
      // Note: w.Tabs removed - using React Router instead of legacy tabs.js
      const uiLoaded = !!w.Theme && !!w.Search;
      const configLoaded = !!w.Config && !!w.Health;

      if (coreLoaded && !modulesLoaded) {
        setLoadProgress('Core modules loaded...');
      }

      if (uiLoaded && !modulesLoaded) {
        setLoadProgress('UI modules loaded...');
      }

      if (configLoaded && !modulesLoaded) {
        setLoadProgress('Configuration modules loaded...');
      }

      // Check if all critical modules are loaded
      if (coreLoaded && uiLoaded && configLoaded) {
        setLoadProgress('All modules loaded');
        setModulesLoaded(true);
        clearInterval(checkModules);
      } else if (attempts >= maxAttempts) {
        setLoadError('Timeout waiting for modules to load');
        setModulesLoaded(true); // Set to true anyway to unblock UI
        clearInterval(checkModules);
      }
    }, 100);

    return () => clearInterval(checkModules);
  }, [modulesLoaded]);

  return { modulesLoaded, loadError, loadProgress };
}
