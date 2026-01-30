import { apiClient, api } from './client';

/**
 * Webhook configuration interface for saving
 */
export interface WebhookSaveRequest {
  slack_url?: string;
  discord_url?: string;
  enabled?: boolean;
  severity?: {
    critical: boolean;
    warning: boolean;
    info: boolean;
  };
  include_resolved?: boolean;
  timeout_seconds?: number;
}

export interface WebhookConfig {
  slack_webhook_url: string;
  discord_webhook_url: string;
  alert_notify_enabled: boolean;
  alert_notify_severities: string;
  alert_include_resolved: boolean;
  alert_webhook_timeout_seconds: number;
}

export interface WebhookSaveResponse {
  status: 'success' | 'error';
  message: string;
}

const severityToString = (severity?: WebhookSaveRequest['severity']) => {
  if (!severity) return 'critical,warning';
  const levels: string[] = [];
  if (severity.critical) levels.push('critical');
  if (severity.warning) levels.push('warning');
  if (severity.info) levels.push('info');
  return levels.length ? levels.join(',') : 'critical';
};

export const webhooksApi = {
  async save(config: WebhookSaveRequest): Promise<WebhookSaveResponse> {
    const payload: Record<string, any> = {
      alert_notify_severities: severityToString(config.severity),
    };

    if (config.slack_url !== undefined) {
      payload.slack_webhook_url = config.slack_url;
    }
    if (config.discord_url !== undefined) {
      payload.discord_webhook_url = config.discord_url;
    }
    if (config.enabled !== undefined) {
      payload.alert_notify_enabled = config.enabled;
    }
    if (config.include_resolved !== undefined) {
      payload.alert_include_resolved = config.include_resolved;
    }
    if (config.timeout_seconds !== undefined) {
      payload.alert_webhook_timeout_seconds = config.timeout_seconds;
    }

    const { data } = await apiClient.post<{ status: string; updated: number; failed: number; message?: string }>(
      api('/monitoring/webhooks/config'),
      payload
    );
    return {
      status: data.status === 'ok' ? 'success' : 'error',
      message:
        data.status === 'ok'
          ? `Webhook configuration saved (${data.updated} setting${data.updated === 1 ? '' : 's'})`
          : data.message || 'Failed to save webhook configuration',
    };
  },

  async getConfig(): Promise<WebhookConfig> {
    const { data } = await apiClient.get<WebhookConfig>(api('/monitoring/webhooks/config'));
    return data;
  },
};
