import { useEffect } from 'react';
import { useTooltipStore } from '../stores/useTooltipStore';

/**
 * useTooltips Hook
 *
 * THIN WRAPPER around useTooltipStore (Zustand) - SINGLE SOURCE OF TRUTH
 *
 * All tooltip definitions live in data/glossary.json (served as /web/glossary.json)
 * This hook provides React-friendly access to that data via Zustand.
 *
 * DO NOT add tooltip definitions here - add them to data/glossary.json instead.
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
