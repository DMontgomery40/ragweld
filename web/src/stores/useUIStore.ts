import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface UIStore {
  // Tab/subtab state
  activeSubtab: Record<string, string>; // key: tab name, value: subtab id

  // Collapsed sections state (persisted)
  collapsedSections: Record<string, boolean>; // key: section id, value: collapsed

  // Sidepanel width (persisted)
  sidepanelWidth: number;

  // Theme mode (persisted)
  themeMode: 'auto' | 'dark' | 'light';

  // Actions
  setActiveSubtab: (tab: string, subtab: string) => void;
  setCollapsed: (sectionId: string, collapsed: boolean) => void;
  toggleCollapsed: (sectionId: string) => boolean; // returns new state
  isCollapsed: (sectionId: string) => boolean;
  setSidepanelWidth: (width: number) => void;
  setThemeMode: (mode: 'auto' | 'dark' | 'light') => void;
}

export const UI_CONSTANTS = {
  DEFAULT_SIDEPANEL_WIDTH: 360,
  MIN_SIDEPANEL_WIDTH: 280,
  MAX_SIDEPANEL_WIDTH: 900,
} as const;

export const useUIStore = create<UIStore>()(
  persist(
    (set, get) => ({
      activeSubtab: {},
      collapsedSections: {},
      sidepanelWidth: UI_CONSTANTS.DEFAULT_SIDEPANEL_WIDTH,
      themeMode: 'auto',

      setActiveSubtab: (tab: string, subtab: string) => {
        set((state) => ({
          activeSubtab: {
            ...state.activeSubtab,
            [tab]: subtab,
          },
        }));
      },

      setCollapsed: (sectionId: string, collapsed: boolean) => {
        set((state) => ({
          collapsedSections: {
            ...state.collapsedSections,
            [sectionId]: collapsed,
          },
        }));
      },

      toggleCollapsed: (sectionId: string) => {
        const current = get().collapsedSections[sectionId] ?? false;
        const newState = !current;
        set((state) => ({
          collapsedSections: {
            ...state.collapsedSections,
            [sectionId]: newState,
          },
        }));
        return newState;
      },

      isCollapsed: (sectionId: string) => {
        return get().collapsedSections[sectionId] ?? false;
      },

      setSidepanelWidth: (width: number) => {
        // Clamp width to valid range
        const clampedWidth = Math.max(
          UI_CONSTANTS.MIN_SIDEPANEL_WIDTH,
          Math.min(UI_CONSTANTS.MAX_SIDEPANEL_WIDTH, width)
        );
        set({ sidepanelWidth: clampedWidth });
      },

      setThemeMode: (mode: 'auto' | 'dark' | 'light') => {
        set({ themeMode: mode });
      },
    }),
    {
      name: 'agro-ui-storage',
    }
  )
);
