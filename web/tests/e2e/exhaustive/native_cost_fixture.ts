import { strict as assert } from 'node:assert';
import path from 'node:path';

/** This fixture has no live-runtime mode. Validate before creating any corpus. */
export function assertPrivateNativeTargets(env: NodeJS.ProcessEnv, cwd: string): void {
  assert(path.resolve(cwd).startsWith('/var/tmp/'), 'native cost fixtures require a private LXC overlay');
  for (const [key, port, pathname] of [
    ['EXHAUSTIVE_API_BASE_URL', '58123', '/api'],
    ['PLAYWRIGHT_WEB_BASE_URL', '5196', '/web'],
  ]) {
    assert(env[key], `${key} must be explicitly set; native cost fixtures never use endpoint defaults`);
    const url = new URL(env[key]!);
    assert(
      url.protocol === 'http:' && url.hostname === '127.0.0.1' && url.port === port &&
      url.pathname.replace(/\/$/, '') === pathname && !url.username && !url.password && !url.search && !url.hash,
      `${key} must address the private native fixture on loopback port ${port}`,
    );
  }
}

export type NativeFixtureConfig = {
  indexing: { postgres_url: string };
  qdrant: { url: string };
  graph_storage: { neo4j_uri: string };
  chat: {
    litellm: { enabled: boolean; base_url: string };
    vllm: { enabled: boolean; base_url: string };
    image_gen: { comfyui_api_endpoint: string };
  };
  tracing: Record<string, unknown>;
  training: Record<string, unknown>;
  ui: { grafana_embed_enabled: boolean; grafana_base_url: string };
};

export function assertPrivateNativeConfig(config: NativeFixtureConfig, gatewayUrl?: string): void {
  for (const [value, port] of [
    [config.indexing.postgres_url, '55439'],
    [config.qdrant.url, '56339'],
    [config.graph_storage.neo4j_uri, '57689'],
  ]) {
    const url = new URL(value.replace('[REDACTED]', 'redacted'));
    assert(url.hostname === '127.0.0.1' && url.port === port, `fixture dependency must use loopback port ${port}`);
  }
  const gateway = new URL(config.chat.litellm.base_url);
  assert(config.chat.litellm.enabled && gateway.protocol === 'http:' && gateway.hostname === '127.0.0.1');
  assert(gateway.port !== '' && gateway.port !== '4000' && gateway.port !== '58012');
  if (gatewayUrl) assert.equal(config.chat.litellm.base_url, `${gatewayUrl}/v1`);
  else assert.equal(config.chat.litellm.base_url, 'http://127.0.0.1:58081/v1');
  assert.equal(config.chat.vllm.enabled, false);
  assert.equal(config.chat.vllm.base_url, '');
  assert.equal(config.chat.image_gen.comfyui_api_endpoint, '');
  for (const key of ['tracing_enabled', 'langfuse_enabled', 'metrics_enabled', 'otel_export_enabled']) {
    assert.equal(config.tracing[key], false, `tracing.${key}`);
  }
  for (const [key, value] of Object.entries(config.tracing)) {
    if (key.endsWith('_url') || key.endsWith('_endpoint')) assert.equal(value, '', `tracing.${key}`);
  }
  for (const [key, value] of Object.entries(config.training)) {
    if (key.endsWith('_url')) assert.equal(value, '', `training.${key}`);
  }
  assert.equal(config.ui.grafana_embed_enabled, false);
  assert.equal(config.ui.grafana_base_url, '');
}
