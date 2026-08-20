import { create } from 'zustand';
import {
  dockerApi,
  type DevStackStatus,
  type RagweldDockerService,
} from '@/api/docker';
import type {
  DockerContainer,
  DockerServiceLogsResponse,
  DockerStatus,
} from '@/types/generated';

interface DockerStore {
  status: DockerStatus | null;
  containers: DockerContainer[];
  loading: boolean;
  error: string | null;

  // Dev Stack state
  devStackStatus: DevStackStatus | null;
  devStackLoading: boolean;

  // Actions
  refreshDocker: () => Promise<void>;
  startService: (service: RagweldDockerService) => Promise<void>;
  stopService: (service: RagweldDockerService) => Promise<void>;
  restartService: (service: RagweldDockerService) => Promise<void>;
  getServiceLogs: (service: RagweldDockerService, tail?: number) => Promise<DockerServiceLogsResponse>;

  // Dev Stack Actions
  fetchDevStackStatus: () => Promise<void>;

  reset: () => void;
}

export const useDockerStore = create<DockerStore>((set, get) => ({
  status: null,
  containers: [],
  loading: false,
  error: null,

  // Dev Stack state (mirrors Pydantic DevStackStatus from backend)
  devStackStatus: null,
  devStackLoading: false,

  refreshDocker: async () => {
    set({ loading: true, error: null });
    const [statusResult, servicesResult] = await Promise.allSettled([
      dockerApi.getStatus(),
      dockerApi.listServices(),
    ]);
    const failures: string[] = [];
    if (statusResult.status === 'rejected') {
      failures.push(statusResult.reason instanceof Error ? statusResult.reason.message : 'Docker status is unavailable');
    }
    if (servicesResult.status === 'rejected') {
      failures.push(servicesResult.reason instanceof Error ? servicesResult.reason.message : 'Ragweld service inventory is unavailable');
    }
    set({
      status: statusResult.status === 'fulfilled' ? statusResult.value : null,
      containers: servicesResult.status === 'fulfilled' ? servicesResult.value.containers ?? [] : [],
      loading: false,
      error: failures.length > 0 ? failures.join(' · ') : null,
    });
  },

  startService: async (service: RagweldDockerService) => {
    try {
      await dockerApi.startService(service);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to start ${service}`;
      set({
        error: message,
      });
      throw error;
    }
    await get().refreshDocker();
  },

  stopService: async (service: RagweldDockerService) => {
    try {
      await dockerApi.stopService(service);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to stop ${service}`;
      set({
        error: message,
      });
      throw error;
    }
    await get().refreshDocker();
  },

  restartService: async (service: RagweldDockerService) => {
    try {
      await dockerApi.restartService(service);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to restart ${service}`;
      set({
        error: message,
      });
      throw error;
    }
    await get().refreshDocker();
  },

  getServiceLogs: async (service: RagweldDockerService, tail: number = 100) => {
    try {
      return await dockerApi.getServiceLogs(service, tail);
    } catch (error) {
      const message = error instanceof Error ? error.message : `Failed to fetch ${service} logs`;
      set({ error: message });
      throw error;
    }
  },

  // Dev Stack status (Pydantic response model: DevStackStatusResponse)
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

  reset: () => set({
    status: null,
    containers: [],
    loading: false,
    error: null,
    devStackStatus: null,
    devStackLoading: false,
  }),
}));
