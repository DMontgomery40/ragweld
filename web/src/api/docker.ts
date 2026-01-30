import { apiClient, api } from './client';
import type { DockerStatus, DockerContainer } from '@web/types';

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
  async listContainers(): Promise<{ containers: DockerContainer[] }> {
    const { data } = await apiClient.get<{ containers: DockerContainer[] }>(
      api('/docker/containers/all')
    );
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
  async getLokiStatus(): Promise<{ reachable: boolean; url?: string; status: string }> {
    const { data } = await apiClient.get<{ reachable: boolean; url?: string; status: string }>(
      api('/loki/status')
    );
    return data;
  },

  // ============================================================================
  // Dev Stack API (Frontend/Backend restart)
  // ============================================================================

  /**
   * Get dev stack status (frontend/backend running state)
   */
  async getDevStackStatus(): Promise<DevStackStatus> {
    const { data } = await apiClient.get<DevStackStatus>(api('/dev/status'));
    return data;
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
    const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/backend/restart'));
    return data;
  },

  /**
   * Restart both frontend and backend
   */
  async restartStack(): Promise<DevStackRestartResult> {
    const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/stack/restart'));
    return data;
  },

  /**
   * Clear Python bytecode cache and restart the backend.
   * Use this when code changes aren't being picked up by normal restarts.
   */
  async clearCacheAndRestart(): Promise<DevStackRestartResult> {
    const { data } = await apiClient.post<DevStackRestartResult>(api('/dev/backend/clear-cache-restart'));
    return data;
  },
};

// Dev Stack Types
export interface DevStackStatus {
  frontend_running: boolean;
  backend_running: boolean;
  frontend_port: number;
  backend_port: number;
}

export interface DevStackRestartResult {
  success: boolean;
  message?: string;
  error?: string;
  port?: number;
  frontend_port?: number;
  backend_port?: number;
}
