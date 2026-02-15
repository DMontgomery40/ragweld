import { apiClient, api } from './client';
import type {
  DevStackRestartResponse,
  DevStackStatusResponse,
  DockerContainersResponse,
  DockerStatus,
  LokiStatus,
} from '@/types/generated';

async function devLauncherJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { method: 'GET', ...init });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`Dev launcher request failed (${res.status}): ${text || path}`);
  }
  return (await res.json()) as T;
}

export const dockerApi = {
  /**
   * Get Docker daemon status
   */
  async getStatus(): Promise<DockerStatus> {
    const { data } = await apiClient.get<DockerStatus>(api('/docker/status'));
    return data;
  },

  /**
   * List all Docker containers
   */
  async listContainers(): Promise<DockerContainersResponse> {
    const { data } = await apiClient.get<DockerContainersResponse>(api('/docker/containers/all'));
    return data;
  },

  /**
   * Start a container by ID
   */
  async startContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/start`));
  },

  /**
   * Stop a container by ID
   */
  async stopContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/stop`));
  },

  /**
   * Restart a container by ID
   */
  async restartContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/restart`));
  },

  /**
   * Pause a container by ID
   */
  async pauseContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/pause`));
  },

  /**
   * Unpause a container by ID
   */
  async unpauseContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/unpause`));
  },

  /**
   * Remove a container by ID
   */
  async removeContainer(id: string): Promise<void> {
    await apiClient.post(api(`/docker/container/${id}/remove`));
  },

  /**
   * Get container logs
   */
  async getContainerLogs(id: string, tail: number = 100): Promise<{ success: boolean; logs: string; error?: string }> {
    const { data } = await apiClient.get<{ success: boolean; logs: string; error?: string }>(
      api(`/docker/container/${id}/logs?tail=${tail}`)
    );
    return data;
  },

  /**
   * Get Loki status
   */
  async getLokiStatus(): Promise<LokiStatus> {
    const { data } = await apiClient.get<LokiStatus>(api('/loki/status'));
    return data;
  },

  // ============================================================================
  // Dev Stack API (Frontend/Backend restart)
  // ============================================================================

  /**
   * Get dev stack status (frontend/backend running state)
   */
  async getDevStackStatus(): Promise<DevStackStatus> {
    try {
      const { data } = await apiClient.get<DevStackStatus>(api('/dev/status'));
      return data;
    } catch {
      // If the backend is down, the /api proxy can't reach it. Vite serves a dev-only
      // launcher endpoint so the UI can recover.
      return await devLauncherJson<DevStackStatus>('/__dev__/dev/status');
    }
  },

  /**
   * Restart the dev frontend (Vite)
   */
  async restartFrontend(): Promise<DevStackRestartResult> {
    const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/frontend/restart'));
    return data;
  },

  /**
   * Restart the dev backend (Uvicorn)
   */
  async restartBackend(): Promise<DevStackRestartResult> {
    try {
      const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/backend/restart'));
      return data;
    } catch (e: any) {
      // Backend is unreachable: try starting it via Vite dev server.
      await devLauncherJson('/__dev__/dev/backend/start', { method: 'POST' });
      return { success: true, message: 'Backend started', backend_port: 8012 };
    }
  },

  /**
   * Restart both frontend and backend
   */
  async restartStack(): Promise<DevStackRestartResult> {
    try {
      const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/stack/restart'));
      return data;
    } catch {
      // If the backend is down, we can't restart the full stack. At minimum, bring the backend back.
      await devLauncherJson('/__dev__/dev/backend/start', { method: 'POST' });
      return { success: true, message: 'Backend started (frontend already running)', frontend_port: 5173, backend_port: 8012 };
    }
  },

  /**
   * Clear Python bytecode cache and restart the backend.
   * Use this when code changes aren't being picked up by normal restarts.
   */
  async clearCacheAndRestart(): Promise<DevStackRestartResult> {
    try {
      const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/backend/clear-cache-restart'));
      return data;
    } catch {
      // If the backend is down, just start it. Cache clear requires a running backend.
      await devLauncherJson('/__dev__/dev/backend/start', { method: 'POST' });
      return { success: true, message: 'Backend started (cache clear requires running backend)', backend_port: 8012 };
    }
  },
};

// Dev Stack Types
export type DevStackStatus = DevStackStatusResponse;
export type DevStackRestartResult = DevStackRestartResponse;
