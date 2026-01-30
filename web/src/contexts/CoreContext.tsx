import React, { createContext, useContext, useEffect, ReactNode } from 'react';
import { useAPI } from '../hooks/useAPI';
import { useTheme } from '../hooks/useTheme';
import { useUIHelpers } from '../hooks/useUIHelpers';

/**
 * Core Application State
 * Replaces window.CoreUtils.state from core-utils.js
 */
interface CoreState {
  models: any | null;
  config: any | null;
  profiles: any[];
  defaultProfile: any | null;
}

interface CoreContextValue {
  // API utilities
  apiBase: string;
  api: (path?: string) => string;

  // Theme utilities
  theme: 'light' | 'dark' | 'auto';
  resolvedTheme: 'light' | 'dark';
  applyTheme: (mode: 'light' | 'dark' | 'auto') => void;
  toggleTheme: () => void;

  // UI utilities
  $: <T extends Element = Element>(selector: string) => T | null;
  $$: <T extends Element = Element>(selector: string) => T[];
  getNum: (id: string) => number;
  setNum: (id: string, n: number) => void;
  attachCommaFormatting: (ids: string[]) => void;
  bindCollapsibleSections: () => void;
  bindResizableSidepanel: () => void;
  wireDayConverters: () => void;
  syncThemeSelectors: () => void;

  // Application state
  state: CoreState;
  updateState: (updates: Partial<CoreState>) => void;
}

const CoreContext = createContext<CoreContextValue | undefined>(undefined);

interface CoreProviderProps {
  children: ReactNode;
}

/**
 * CoreProvider
 * Provides all core utilities (API, Theme, UI helpers) and application state
 * Replaces the functionality from core-utils.js, theme.js, and ui-helpers.js
 */
export function CoreProvider({ children }: CoreProviderProps) {
  const { apiBase, api } = useAPI();
  const { theme, resolvedTheme, applyTheme, toggleTheme } = useTheme();
  const uiHelpers = useUIHelpers();

  // Application state (replaces window.CoreUtils.state)
  const [state, setState] = React.useState<CoreState>({
    models: null,
    config: null,
    profiles: [],
    defaultProfile: null
  });

  const updateState = React.useCallback((updates: Partial<CoreState>) => {
    setState(prev => ({ ...prev, ...updates }));
  }, []);

  // Expose CoreUtils to window for backwards compatibility during migration
  useEffect(() => {
    (window as any).CoreUtils = {
      API_BASE: apiBase,
      api,
      $: uiHelpers.$,
      $$: uiHelpers.$$,
      state
    };
  }, [apiBase, api, uiHelpers.$, uiHelpers.$$, state]);

  const value: CoreContextValue = {
    apiBase,
    api,
    theme,
    resolvedTheme,
    applyTheme,
    toggleTheme,
    ...uiHelpers,
    state,
    updateState
  };

  return (
    <CoreContext.Provider value={value}>
      {children}
    </CoreContext.Provider>
  );
}

/**
 * useCore Hook
 * Access all core utilities and state from any component
 *
 * @example
 * const { api, theme, $, state } = useCore();
 */
export function useCore(): CoreContextValue {
  const context = useContext(CoreContext);
  if (!context) {
    throw new Error('useCore must be used within a CoreProvider');
  }
  return context;
}

// Export individual hooks for fine-grained usage
export { useAPI } from '../hooks/useAPI';
export { useTheme } from '../hooks/useTheme';
export { useUIHelpers } from '../hooks/useUIHelpers';
