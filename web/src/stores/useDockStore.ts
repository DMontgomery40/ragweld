import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type DockMode = 'dock' | 'settings';
export type DockRenderMode = 'native' | 'iframe';

export type DockTarget = {
  path: string;
  search: string;
  label: string;
  icon: string;
  subtabTitle?: string;
  renderMode: DockRenderMode;
};

type SetDockedOptions = {
  rememberLast?: boolean;
};

interface DockStore {
  mode: DockMode;
  docked: DockTarget | null;
  lastDocked: DockTarget | null;

  setMode: (mode: DockMode) => void;
  setDocked: (target: DockTarget | null, opts?: SetDockedOptions) => void;
  swapDocked: (nextDocked: DockTarget) => DockTarget | null;
  clearDocked: () => void;
}

export const useDockStore = create<DockStore>()(
  persist(
    (set, get) => ({
      mode: 'settings',
      docked: null,
      lastDocked: null,

      setMode: (mode) => set({ mode }),

      setDocked: (target, opts) => {
        const rememberLast = opts?.rememberLast ?? true;
        const prevDocked = get().docked;
        set({
          docked: target,
          lastDocked: rememberLast ? prevDocked : get().lastDocked,
        });
      },

      swapDocked: (nextDocked) => {
        const prev = get().docked;
        set({
          docked: nextDocked,
          lastDocked: prev,
        });
        return prev;
      },

      clearDocked: () => {
        const prev = get().docked;
        set({
          docked: null,
          lastDocked: prev,
        });
      },
    }),
    { name: 'agro-dock-storage' }
  )
);

