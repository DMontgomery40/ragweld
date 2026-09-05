import { strict as assert } from 'node:assert';
import test from 'node:test';
import { assertPrivateNativeConfig, assertPrivateNativeTargets, type NativeFixtureConfig } from '../e2e/exhaustive/native_cost_fixture.ts';

const env = { EXHAUSTIVE_API_BASE_URL: 'http://127.0.0.1:58123/api', PLAYWRIGHT_WEB_BASE_URL: 'http://127.0.0.1:5196/web' };
const cwd = '/var/tmp/native-fixture';
const config: NativeFixtureConfig = {
  indexing: { postgres_url: 'postgresql://postgres:redacted@127.0.0.1:55439/tribrid_test' },
  qdrant: { url: 'http://127.0.0.1:56339' }, graph_storage: { neo4j_uri: 'bolt://127.0.0.1:57689' },
  chat: { litellm: { enabled: true, base_url: 'http://127.0.0.1:58081/v1' }, vllm: { enabled: false, base_url: '' }, image_gen: { comfyui_api_endpoint: '' } },
  tracing: { tracing_enabled: false, langfuse_enabled: false, metrics_enabled: false, otel_export_enabled: false, pyroscope_server_url: '' },
  training: { prometheus_url: '' }, ui: { grafana_embed_enabled: false, grafana_base_url: '' },
};

test('native fixtures require explicit private API and browser targets before setup', () => {
  assert.doesNotThrow(() => assertPrivateNativeTargets(env, cwd));
  for (const key of Object.keys(env)) {
    for (const value of [undefined, '', 'http://127.0.0.1:58012/api', 'https://ragweld.dtmont.com/web', 'http://192.168.68.225:58123/api', 'http://user:pass@127.0.0.1:58123/api', 'http://127.0.0.1:58123/api?x=1']) {
      assert.throws(() => assertPrivateNativeTargets({ ...env, [key]: value }, cwd));
    }
  }
  assert.throws(() => assertPrivateNativeTargets({ EXHAUSTIVE_API_BASE: env.EXHAUSTIVE_API_BASE_URL, PLAYWRIGHT_WEB_BASE_URL: env.PLAYWRIGHT_WEB_BASE_URL }, cwd));
  for (const dir of ['/opt/ragweld', '/Users/davidmontgomery/ragweld', '/var/tmp/../../opt/ragweld']) {
    assert.throws(() => assertPrivateNativeTargets(env, dir));
  }
});

test('resolved config rejects live dependencies, gateways, and telemetry before fixture creation', () => {
  assert.doesNotThrow(() => assertPrivateNativeConfig(config));
  const mutations = [
    (c: NativeFixtureConfig) => { c.indexing.postgres_url = 'postgresql://localhost:5432/tribrid_rag'; },
    (c: NativeFixtureConfig) => { c.qdrant.url = 'http://127.0.0.1:6333'; },
    (c: NativeFixtureConfig) => { c.graph_storage.neo4j_uri = 'bolt://192.168.68.225:57689'; },
    (c: NativeFixtureConfig) => { c.chat.litellm.base_url = 'http://127.0.0.1:4000/v1'; },
    (c: NativeFixtureConfig) => { c.chat.vllm.enabled = true; },
    (c: NativeFixtureConfig) => { c.tracing.tracing_enabled = true; },
    (c: NativeFixtureConfig) => { c.tracing.pyroscope_server_url = 'http://127.0.0.1:4040'; },
    (c: NativeFixtureConfig) => { c.training.prometheus_url = 'http://127.0.0.1:9090'; },
    (c: NativeFixtureConfig) => { c.ui.grafana_base_url = 'http://127.0.0.1:3000'; },
  ];
  for (const mutate of mutations) {
    const changed = structuredClone(config);
    mutate(changed);
    assert.throws(() => assertPrivateNativeConfig(changed));
  }
  const scoped = structuredClone(config);
  scoped.chat.litellm.base_url = 'http://127.0.0.1:49155/v1';
  assert.doesNotThrow(() => assertPrivateNativeConfig(scoped, 'http://127.0.0.1:49155'));
  assert.throws(() => assertPrivateNativeConfig(scoped, 'http://127.0.0.1:49156'));
});
