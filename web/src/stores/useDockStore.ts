import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ChunkMatch } from '@/types/generated';

export type DockMode = 'dock' | 'settings' | 'document';
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

/** The document viewer consumes a location, whether reached from retrieval or the graph. */
export type DocumentSource = Pick<ChunkMatch, 'chunk_id' | 'file_path' | 'start_line' | 'end_line' | 'content' | 'metadata' | 'provenance'>;

/** A source opened in the right rail and the corpus it belongs to. */
export type DocumentTarget = {
  corpusId: string;
  source: DocumentSource;
};

interface DockStore {
  mode: DockMode;
  docked: DockTarget | null;
  lastDocked: DockTarget | null;
  activeDocument: DocumentTarget | null;

  setMode: (mode: DockMode) => void;
  openDocument: (target: DocumentTarget) => void;
  closeDocument: () => void;
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
      activeDocument: null,

      setMode: (mode) => set({ mode }),

      openDocument: (target) => set({ activeDocument: target, mode: 'document' }),

      closeDocument: () =>
        set((state) => ({
          activeDocument: null,
          mode: state.mode === 'document' ? (state.docked ? 'dock' : 'settings') : state.mode,
        })),

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
    {
      name: 'tribrid-dock-storage',
      // The open document is per-session UI state: never persisted, and a persisted
      // 'document' mode without a target would render an empty rail on reload.
      partialize: (state) => ({
        mode: state.mode === 'document' ? 'dock' : state.mode,
        docked: state.docked,
        lastDocked: state.lastDocked,
      }),
    }
  )
);
