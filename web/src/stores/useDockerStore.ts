import { create } from 'zustand';
import { dockerApi, type DevStackStatus } from '@/api/docker';
import type { DockerStatus, DockerContainer } from '@web/types';

interface DockerStore {
  status: DockerStatus | null;
  containers: DockerContainer[];
  loading: boolean;
  error: string | null;

  // Dev Stack state
  devStackStatus: DevStackStatus | null;
  devStackLoading: boolean;
  restartingFrontend: boolean;
  restartingBackend: boolean;
  restartingStack: boolean;
  clearingCache: boolean;

  // Actions
  fetchStatus: () => Promise<void>;
  fetchContainers: () => Promise<void>;
  startContainer: (id: string) => Promise<void>;
  stopContainer: (id: string) => Promise<void>;
  restartContainer: (id: string) => Promise<void>;
  pauseContainer: (id: string) => Promise<void>;
  unpauseContainer: (id: string) => Promise<void>;
  removeContainer: (id: string) => Promise<void>;
  getContainerLogs: (id: string, tail?: number) => Promise<{ success: boolean; logs: string; error?: string }>;

  // Dev Stack Actions
  fetchDevStackStatus: () => Promise<void>;
  restartFrontend: () => Promise<void>;
  restartBackend: () => Promise<void>;
  restartStack: () => Promise<void>;
  clearCacheAndRestart: () => Promise<void>;

  reset: () => void;

  // Infrastructure stubs (will be properly implemented)
  startInfrastructure: () => Promise<void>;
  stopInfrastructure: () => Promise<void>;
  pingService: (service: string) => Promise<boolean>;
}

export const useDockerStore = create<DockerStore>((set, get) => ({
  status: null,
  containers: [],
  loading: false,
  error: null,

  // Dev Stack state (mirrors Pydantic DevStackStatus from backend)
  devStackStatus: null,
  devStackLoading: false,
  restartingFrontend: false,
  restartingBackend: false,
  restartingStack: false,
  clearingCache: false,

  fetchStatus: async () => {
    set({ loading: true, error: null });
    try {
      const status = await dockerApi.getStatus();
      set({ status, loading: false, error: null });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch Docker status'
      });
    }
  },

  fetchContainers: async () => {
    set({ loading: true, error: null });
    try {
      const { containers } = await dockerApi.listContainers();
      set({ containers, loading: false, error: null });
    } catch (error) {
      set({
        loading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch containers'
      });
    }
  },

  startContainer: async (id: string) => {
    try {
      await dockerApi.startContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to start container'
      });
    }
  },

  stopContainer: async (id: string) => {
    try {
      await dockerApi.stopContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to stop container'
      });
    }
  },

  restartContainer: async (id: string) => {
    try {
      await dockerApi.restartContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to restart container'
      });
    }
  },

  pauseContainer: async (id: string) => {
    try {
      await dockerApi.pauseContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to pause container'
      });
    }
  },

  unpauseContainer: async (id: string) => {
    try {
      await dockerApi.unpauseContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to unpause container'
      });
    }
  },

  removeContainer: async (id: string) => {
    try {
      await dockerApi.removeContainer(id);
      await get().fetchContainers();
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : 'Failed to remove container'
      });
    }
  },

  getContainerLogs: async (id: string, tail: number = 100) => {
    try {
      return await dockerApi.getContainerLogs(id, tail);
    } catch (error) {
      return {
        success: false,
        logs: '',
        error: error instanceof Error ? error.message : 'Failed to fetch logs'
      };
    }
  },

  // Dev Stack Actions (Pydantic response models: DevStackStatusResponse, DevStackRestartResponse)
  fetchDevStackStatus: async () => {
    set({ devStackLoading: true, error: null });
    try {
      const devStackStatus = await dockerApi.getDevStackStatus();
      set({ devStackStatus, devStackLoading: false, error: null });
    } catch (error) {
      set({
        devStackLoading: false,
        error: error instanceof Error ? error.message : 'Failed to fetch dev stack status'
      });
    }
  },

  restartFrontend: async () => {
    set({ restartingFrontend: true, error: null });
    try {
      const result = await dockerApi.restartFrontend();
      if (!result.success) {
        set({ restartingFrontend: false, error: result.error || 'Frontend restart failed' });
        return;
      }
      // Refresh status after restart
      setTimeout(() => get().fetchDevStackStatus(), 3000);
      set({ restartingFrontend: false });
    } catch (error) {
      set({
        restartingFrontend: false,
        error: error instanceof Error ? error.message : 'Failed to restart frontend'
      });
    }
  },

  restartBackend: async () => {
    set({ restartingBackend: true, error: null });
    try {
      const result = await dockerApi.restartBackend();
      if (!result.success) {
        set({ restartingBackend: false, error: result.error || 'Backend restart failed' });
        return;
      }
      set({ restartingBackend: false });
      // Backend restarts itself - refresh after delay
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    } catch (error) {
      // Request may fail because backend restarted - expected behavior
      set({ restartingBackend: false });
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    }
  },

  restartStack: async () => {
    set({ restartingStack: true, error: null });
    try {
      const result = await dockerApi.restartStack();
      if (!result.success) {
        set({ restartingStack: false, error: result.error || 'Stack restart failed' });
        return;
      }
      set({ restartingStack: false });
      // Stack restarts - refresh after delay
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    } catch (error) {
      // Request may fail because backend restarted - expected behavior
      set({ restartingStack: false });
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    }
  },

  clearCacheAndRestart: async () => {
    set({ clearingCache: true, error: null });
    try {
      const result = await dockerApi.clearCacheAndRestart();
      if (!result.success) {
        set({ clearingCache: false, error: result.error || 'Cache clear failed' });
        return;
      }
      set({ clearingCache: false });
      // Backend restarts - refresh after delay
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    } catch (error) {
      // Request may fail because backend restarted - expected behavior
      set({ clearingCache: false });
      setTimeout(() => get().fetchDevStackStatus(), 5000);
    }
  },

  reset: () => set({
    status: null,
    containers: [],
    loading: false,
    error: null,
    devStackStatus: null,
    devStackLoading: false,
    restartingFrontend: false,
    restartingBackend: false,
    restartingStack: false,
    clearingCache: false,
  }),

  // Infrastructure operations - call real APIs
  startInfrastructure: async () => {
    set({ loading: true, error: null });
    try {
      // Infrastructure start/stop not yet implemented in backend
      // When implemented, will call POST /api/docker/infrastructure/start
      const response = await fetch('/api/docker/infrastructure/start', { method: 'POST' });
      if (!response.ok) {
        throw new Error('Infrastructure start not implemented');
      }
      await get().fetchStatus();
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to start infrastructure' });
    } finally {
      set({ loading: false });
    }
  },

  stopInfrastructure: async () => {
    set({ loading: true, error: null });
    try {
      // Infrastructure start/stop not yet implemented in backend
      // When implemented, will call POST /api/docker/infrastructure/stop
      const response = await fetch('/api/docker/infrastructure/stop', { method: 'POST' });
      if (!response.ok) {
        throw new Error('Infrastructure stop not implemented');
      }
      await get().fetchStatus();
    } catch (error) {
      set({ error: error instanceof Error ? error.message : 'Failed to stop infrastructure' });
    } finally {
      set({ loading: false });
    }
  },

  pingService: async (service: string) => {
    try {
      // Call the real health endpoint
      const response = await fetch('/api/health');
      if (!response.ok) {
        return false;
      }
      const health = await response.json();
      const serviceStatus = health.services?.[service]?.status;
      return serviceStatus === 'up' || serviceStatus === 'healthy';
    } catch {
      return false;
    }
  },
}));
