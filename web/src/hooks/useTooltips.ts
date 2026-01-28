import { useEffect } from 'react';
import { useTooltipStore } from '../stores/useTooltipStore';

/**
 * useTooltips Hook
 *
 * THIN WRAPPER around useTooltipStore (Zustand) - SINGLE SOURCE OF TRUTH
 *
 * All tooltip definitions live in web/src/modules/tooltips.js
 * This hook provides React-friendly access to that data via Zustand.
 *
 * DO NOT add tooltip definitions here - add them to tooltips.js instead.
 */
/**
 * ---agentspec
 * what: |
 *   Custom React hook that provides access to tooltip data and initialization logic from a centralized tooltip store.
 *   Takes no parameters and returns an object containing: tooltips (Map of tooltip data), loading (boolean), initialized (boolean), initialize (function), and getTooltip (function to retrieve individual tooltips).
 *   On first mount, automatically triggers store initialization if not already done via useEffect dependency.
 *   Handles the lazy initialization pattern where tooltip data is fetched/loaded on demand rather than at app startup.
 *
 * why: |
 *   Encapsulates tooltip store access behind a hook interface to provide consistent, reusable access across components.
 *   The automatic initialization in useEffect ensures tooltips are ready before components attempt to render them, preventing race conditions.
 *   This pattern decouples tooltip data fetching from component lifecycle, allowing tooltips to load asynchronously without blocking render.
 *
 * guardrails:
 *   - DO NOT call initialize() manually in components; the hook handles this automatically to prevent duplicate initialization calls
 *   - ALWAYS check the loading state before rendering tooltips to avoid displaying stale or undefined data
 *   - NOTE: The useEffect dependency array [initialized, initialize] may cause re-initialization if initialize function reference changes; ensure useTooltipStore memoizes initialize
 *   - ASK USER: Confirm whether tooltips should be preloaded at app startup or remain lazy-loaded on first useTooltips() call, as this affects performance characteristics
 * ---/agentspec
 */
export function useTooltips() {
  const { tooltips, loading, initialized, initialize, getTooltip } = useTooltipStore();

  // Initialize store on first use
  useEffect(() => {
    if (!initialized) {
      initialize();
    }
  }, [initialized, initialize]);

  return {
    tooltips,
    loading,
    getTooltip,
    count: Object.keys(tooltips).length
  };
}

// Re-export types for convenience
export type { TooltipMap } from '../stores/useTooltipStore';
