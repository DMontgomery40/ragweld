import { apiClient, api } from './client';
import type {
  DevStackStatusResponse,
  DockerContainersResponse,
  DockerStatus,
  LokiStatus,
} from '@/types/generated';

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
    const { data } = await apiClient.get<DevStackStatus>(api('/dev/status'));
    return data;
  },
};

// Dev Stack Types
export type DevStackStatus = DevStackStatusResponse;
