import { create } from 'zustand';
import { healthApi } from '@/api/health';
import type { HealthStatus } from '@/types/generated';

interface HealthStore {
  status: HealthStatus | null;
  loading: boolean;
  error: string | null;
  lastChecked: Date | null;

  // Actions
  checkHealth: () => Promise<void>;
  reset: () => void;
}

// One GET /api/health in flight at a time: the top bar's mount probe, its 30 s poll and
// the manual Health button all landed on the same tick during startup (M-129). Shared,
// not cached -- the entry is dropped as soon as the probe settles, so a later poll or a
// click on Health always asks the server again.
let inFlightHealthCheck: Promise<void> | null = null;

export const useHealthStore = create<HealthStore>((set) => ({
  status: null,
  loading: false,
  error: null,
  lastChecked: null,

  checkHealth: async () => {
    if (inFlightHealthCheck) return inFlightHealthCheck;
    const run = (async () => {
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
    })();
    inFlightHealthCheck = run;
    try {
      await run;
    } finally {
      if (inFlightHealthCheck === run) inFlightHealthCheck = null;
    }
  },

  reset: () => set({
    status: null,
    loading: false,
    error: null,
    lastChecked: null
  }),
}));
