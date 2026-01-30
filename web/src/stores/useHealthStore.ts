import { create } from 'zustand';
import { healthApi } from '@/api/health';
import type { HealthStatus } from '@web/types';

interface HealthStore {
  status: HealthStatus | null;
  loading: boolean;
  error: string | null;
  lastChecked: Date | null;

  // Actions
  checkHealth: () => Promise<void>;
  reset: () => void;
}

export const useHealthStore = create<HealthStore>((set) => ({
  status: null,
  loading: false,
  error: null,
  lastChecked: null,

  checkHealth: async () => {
    set({ loading: true, error: null });
    try {
      const status = await healthApi.check();
      set({
        status,
        loading: false,
        error: null,
        lastChecked: new Date()
      });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to check health',
        status: null
      });
    }
  },

  reset: () => set({
    status: null,
    loading: false,
    error: null,
    lastChecked: null
  }),
}));
