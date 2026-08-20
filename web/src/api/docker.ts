import { apiClient, api } from './client';
import type {
  DevStackStatusResponse,
  DockerContainersResponse,
  DockerServiceLogsResponse,
  DockerStatus,
  LokiStatus,
} from '@/types/generated';

export const RAGWELD_DOCKER_SERVICES = [
  'postgres',
  'postgres-exporter',
  'neo4j',
  'grafana',
  'prometheus',
  'loki',
  'promtail',
  'api',
  'tempo',
  'alloy',
  'litellm',
  'vllm',
] as const;

export type RagweldDockerService = (typeof RAGWELD_DOCKER_SERVICES)[number];

export const dockerApi = {
  /**
   * Get Docker daemon status
   */
  async getStatus(): Promise<DockerStatus> {
    const { data } = await apiClient.get<DockerStatus>(api('/docker/status'));
    return data;
  },

  async listServices(): Promise<DockerContainersResponse> {
    const { data } = await apiClient.get<DockerContainersResponse>(api('/docker/services'));
    return data;
  },

  async startService(service: RagweldDockerService): Promise<void> {
    await apiClient.post(api(`/docker/services/${service}/start`));
  },

  async stopService(service: RagweldDockerService): Promise<void> {
    await apiClient.post(api(`/docker/services/${service}/stop`));
  },

  async restartService(service: RagweldDockerService): Promise<void> {
    await apiClient.post(api(`/docker/services/${service}/restart`));
  },

  async getServiceLogs(
    service: RagweldDockerService,
    tail: number = 100,
  ): Promise<DockerServiceLogsResponse> {
    const { data } = await apiClient.get<DockerServiceLogsResponse>(
      api(`/docker/services/${service}/logs?tail=${tail}`)
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
