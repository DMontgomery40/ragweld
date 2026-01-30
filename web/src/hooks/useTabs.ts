// AGRO - useTabs Hook
// Manages tab and subtab state for components

import { useState, useCallback } from 'react';

export interface UseTabsOptions {
  defaultSubtab?: string;
}

/**
 * ---agentspec
 * what: |
 *   React hook that manages tab/subtab state with localStorage persistence.
 *   Takes a UseTabsOptions object with optional defaultSubtab string parameter.
 *   Returns an object containing activeSubtab (current subtab ID string) and switchSubtab (callback function to change tabs).
 *   The switchSubtab callback updates state and persists the selection to localStorage under the key 'nav_current_subtab'.
 *   Handles localStorage errors silently with try-catch; if localStorage is unavailable (private browsing, quota exceeded), state updates still occur.
 *
 * why: |
 *   Centralizes tab state management and persistence logic into a reusable hook to avoid duplication across components.
 *   localStorage persistence ensures users return to their previously selected subtab on page reload, improving UX.
 *   Silent error handling prevents crashes in restricted environments (private browsing, incognito mode) while maintaining functionality.
 *
 * guardrails:
 *   - DO NOT remove the try-catch around localStorage.setItem; it prevents crashes in private browsing mode and quota-exceeded scenarios
 *   - ALWAYS initialize activeSubtab from options.defaultSubtab or empty string to ensure controlled component behavior
 *   - NOTE: localStorage key 'nav_current_subtab' is hardcoded; changing it will break persistence for existing users with stored values
 *   - NOTE: This hook does not validate that subtabId exists in a parent tab structure; invalid IDs will be stored and restored without warning
 *   - ASK USER: Before adding localStorage.getItem on mount, confirm whether initial state should hydrate from storage or always use defaultSubtab
 * ---/agentspec
 */
export function useTabs(options: UseTabsOptions = {}) {
  const [activeSubtab, setActiveSubtab] = useState<string>(options.defaultSubtab || '');

  const switchSubtab = useCallback((subtabId: string) => {
    setActiveSubtab(subtabId);

    // Store in localStorage for persistence
    try {
      localStorage.setItem('nav_current_subtab', subtabId);
    } catch (e) {
      console.warn('[useTabs] Failed to save subtab to localStorage:', e);
    }
  }, []);

  return {
    activeSubtab,
    switchSubtab
  };
}
