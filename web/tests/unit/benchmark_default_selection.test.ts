// Unit rules for the Benchmark tab's default model selection (S11: a first run must never
// start with a lane the host does not serve pre-checked). Runs under `node --test` with
// Node's built-in type stripping: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  defaultBenchmarkSelection,
  describeLocalLane,
  localLaneState,
} from '../../src/components/Benchmark/defaultSelection.ts';
import type { ChatModelInfo, ReadinessStatus, RuntimeCapabilitiesResponse } from '../../src/types/generated.ts';

function model(id: string, provider: string, display: string): ChatModelInfo {
  return {
    id,
    override: `litellm:${id}`,
    provider: 'LiteLLM',
    provider_key: 'litellm',
    catalog_model: id,
    components: ['GEN'],
    source: 'litellm',
    provider_type: 'litellm',
    supports_vision: false,
    catalog_provider: provider,
    display_name: display,
    context: 32768,
    input_per_1k: 0,
    output_per_1k: 0,
  };
}

// The order the page shows: local serving row first, then providers A-Z, names A-Z.
const ORDERED: ChatModelInfo[] = [
  model('ragweld-local', 'ragweld', 'Ragweld local (self-hosted)'),
  model('aion-labs.aion-2.0', 'aion-labs', 'AionLabs: Aion-2.0'),
  model('aion-labs.aion-3.0', 'aion-labs', 'AionLabs: Aion-3.0'),
  model('openai.gpt-5.6-luna', 'openai', 'OpenAI: GPT-5.6 Luna'),
];

function capabilities(enabled: boolean): RuntimeCapabilitiesResponse {
  return {
    generation: {
      routing_backends: [],
      serving_backends: [{ id: 'vllm', label: 'vLLM', description: 'self-hosted serving' }],
      default_route: null,
      local_serving: { alias: 'ragweld-local', backend: 'vllm', backend_label: 'vLLM', enabled, model: 'Qwen/Qwen3.8-27B' },
    },
  };
}

function readiness(vllmOk: boolean, status: string): ReadinessStatus {
  return {
    ready: true,
    dependencies: {
      postgres: { ok: true },
      litellm: { ok: true },
      vllm: { ok: vllmOk, info: { status } },
    },
  };
}

test('a disabled local lane is never a default; the next two ordered candidates are', () => {
  const lane = localLaneState(capabilities(false), readiness(true, 'disabled by configuration'));
  assert.equal(lane.enabled, false);
  assert.equal(lane.reachable, false, 'readiness ok=true for a disabled lane means "not required", not "serving"');
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, {}), ['litellm:aion-labs.aion-2.0', 'litellm:aion-labs.aion-3.0']);
  assert.equal(describeLocalLane(lane), 'vLLM lane disabled on this host');
});

test('an enabled, reachable local lane is the first default', () => {
  const lane = localLaneState(capabilities(true), readiness(true, 'reachable'));
  assert.equal(lane.reachable, true);
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, {}), ['litellm:ragweld-local', 'litellm:aion-labs.aion-2.0']);
  assert.equal(describeLocalLane(lane), 'vLLM lane on');
});

test('an enabled lane whose serving probe fails is skipped like a disabled one', () => {
  const lane = localLaneState(capabilities(true), readiness(false, 'unreachable'));
  assert.equal(lane.enabled, true);
  assert.equal(lane.reachable, false);
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, {}), ['litellm:aion-labs.aion-2.0', 'litellm:aion-labs.aion-3.0']);
  assert.equal(describeLocalLane(lane), 'vLLM lane enabled but not serving');
});

test('without a readiness answer the lane is not proven serving, so it is skipped', () => {
  const lane = localLaneState(capabilities(true), null);
  assert.equal(lane.reachable, false);
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, {}), ['litellm:aion-labs.aion-2.0', 'litellm:aion-labs.aion-3.0']);
});

test('the lane alias comes from capabilities, not from a name baked into the page', () => {
  const caps = capabilities(false);
  caps.generation!.local_serving!.alias = 'ragweld-house';
  const rows = [model('ragweld-house', 'ragweld', 'House lane'), ...ORDERED.slice(1)];
  const lane = localLaneState(caps, readiness(true, 'disabled by configuration'));
  assert.deepEqual(defaultBenchmarkSelection(rows, lane, {}), ['litellm:aion-labs.aion-2.0', 'litellm:aion-labs.aion-3.0']);
});

test('selection honours the requested count, skips blank and duplicate values, and never pads', () => {
  const lane = localLaneState(capabilities(false), readiness(true, 'disabled by configuration'));
  const rows = [ORDERED[0], { ...ORDERED[1], override: '', id: '' }, ORDERED[2], ORDERED[2], ORDERED[3]];
  assert.deepEqual(defaultBenchmarkSelection(rows, lane, { count: 3 }), ['litellm:aion-labs.aion-3.0', 'litellm:openai.gpt-5.6-luna']);
  assert.deepEqual(defaultBenchmarkSelection([ORDERED[0]], lane, {}), []);
});

// S41: a first benchmark must compare the alias this corpus actually answers with, not the
// two rows that happen to sort first in the catalog (which preselected two AionLabs models
// on the live deployment). The anchor is chat.litellm.default_model, matched the way the
// chat picker matches it (model id or catalog model), and the second slot is filled from
// display order.
test('the answering alias is the first default, and display order fills the rest', () => {
  const lane = localLaneState(capabilities(false), readiness(false, 'disabled'));
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, { answeringAlias: 'openai.gpt-5.6-luna' }), [
    'litellm:openai.gpt-5.6-luna',
    'litellm:aion-labs.aion-2.0',
  ]);
});

test('an answering alias absent from the catalog leaves the display order untouched', () => {
  const lane = localLaneState(capabilities(false), readiness(false, 'disabled'));
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, { answeringAlias: 'openai.gpt-9.9-nope' }), [
    'litellm:aion-labs.aion-2.0',
    'litellm:aion-labs.aion-3.0',
  ]);
});

test('the answering alias is never the local lane while that lane is not serving', () => {
  const lane = localLaneState(capabilities(true), readiness(false, 'not serving'));
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, { answeringAlias: 'ragweld-local' }), [
    'litellm:aion-labs.aion-2.0',
    'litellm:aion-labs.aion-3.0',
  ]);
});

test('a serving local lane named by the config is the first default', () => {
  const lane = localLaneState(capabilities(true), readiness(true, 'serving'));
  assert.deepEqual(defaultBenchmarkSelection(ORDERED, lane, { answeringAlias: 'ragweld-local' }), [
    'litellm:ragweld-local',
    'litellm:aion-labs.aion-2.0',
  ]);
});
