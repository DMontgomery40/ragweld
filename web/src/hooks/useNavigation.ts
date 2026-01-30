// AGRO - useNavigation Hook
// Replaces legacy navigation.js DOM manipulation with React Router

import { useCallback, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { routes } from '../config/routes';

/**
 * ---agentspec
 * what: |
 *   Custom React hook that provides tab navigation functionality for a single-page application.
 *   Takes no parameters; uses React Router's useNavigate and useLocation hooks internally.
 *   Returns an object with activeTab (string, derived from current pathname) and navigateTo (function that accepts tabId string).
 *   The navigateTo function updates the browser location to /{tabId}, enabling URL-based tab state persistence.
 *   Defaults to 'dashboard' tab when pathname is root or empty.
 *
 * why: |
 *   Centralizes tab navigation logic to avoid duplicating useNavigate/useLocation calls across multiple components.
 *   Derives activeTab from URL pathname rather than component state, ensuring tab state survives page refreshes and browser back/forward.
 *   Provides a simple, consistent API (navigateTo) for all tab-switching behavior throughout the app.
 *
 * guardrails:
 *   - DO NOT store activeTab in local component state; URL-derived state ensures consistency across browser navigation
 *   - ALWAYS validate tabId before calling navigateTo to prevent navigation to undefined or invalid routes
 *   - NOTE: This hook assumes a flat routing structure where tabs map directly to top-level paths (e.g., /dashboard, /settings); nested routes may require path parsing logic
 *   - ASK USER: Confirm whether navigateTo should validate tabId against an allowed list of tabs, or if any string is acceptable
 * ---/agentspec
 */
export function useNavigation() {
  const navigate = useNavigate();
  const location = useLocation();

  // Get current tab from location
  const activeTab = location.pathname.slice(1) || 'dashboard';

  // Navigate to a tab
  const navigateTo = useCallback((tabId: string) => {
    // Ensure leading slash
    const path = tabId.startsWith('/') ? tabId : `/${tabId}`;
    navigate(path);

    // Store in localStorage for compatibility with legacy modules
    try {
      localStorage.setItem('nav_current_tab', tabId.replace('/', ''));
    } catch (e) {
      console.warn('[useNavigation] Failed to save to localStorage:', e);
    }
  }, [navigate]);

  // Handle browser back/forward
  useEffect(() => {
    // Update localStorage when location changes
    try {
      const currentTab = location.pathname.slice(1) || 'dashboard';
      localStorage.setItem('nav_current_tab', currentTab);
    } catch (e) {
      console.warn('[useNavigation] Failed to save to localStorage:', e);
    }
  }, [location]);

  // Restore last tab from localStorage on mount
  useEffect(() => {
    try {
      const lastTab = localStorage.getItem('nav_current_tab');
      if (lastTab && location.pathname === '/') {
        // Only navigate if we're at root
        const route = routes.find(r => r.path === `/${lastTab}`);
        if (route) {
          navigate(`/${lastTab}`, { replace: true });
        }
      }
    } catch (e) {
      console.warn('[useNavigation] Failed to restore from localStorage:', e);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return {
    activeTab,
    navigateTo,
    currentPath: location.pathname
  };
}
