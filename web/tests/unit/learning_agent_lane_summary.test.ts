// Unit rules for the Learning Agent Studio header (S16: the blurb states the training lane
// this host really has, from the runtime capability payload, never from copy baked into
// the page). Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { describeLearningAgentLane, learningAgentLaneBlurb } from '../../src/components/AgentTraining/laneSummary.ts';
import type { LearningAgentRuntimeCapability } from '../../src/types/generated.ts';

const MAC_ERA_MODEL = 'mlx-community/Qwen3-4B-Instruct-2507-4bit';

function lane(overrides: Partial<LearningAgentRuntimeCapability>): LearningAgentRuntimeCapability {
  return {
    execution_backend: 'mlx_qwen3',
    execution_locus: 'host',
    host_available: false,
    availability_detail: 'Training backend mlx_qwen3 is not available on this host; runs will fail closed.',
    base_model: 'example-org/base-model-v9',
    artifact_path: 'models/agent-store',
    ...overrides,
  };
}

test('a host without the configured backend renders the fail-closed state, not promotional copy', () => {
  const summary = describeLearningAgentLane(lane({}));
  assert.equal(summary.state, 'host_unavailable');

  const blurb = learningAgentLaneBlurb(summary);
  assert.match(blurb, /Training backend mlx_qwen3 is not available on this host; runs will fail closed\./);
  assert.match(blurb, /Configured base model example-org\/base-model-v9; adapters promote to models\/agent-store/);
  assert.doesNotMatch(blurb, /Train local adapters for/);
  assert.doesNotMatch(blurb, /Flyte \/ MLflow \/ Unsloth control plane/);
  assert.equal(blurb.includes(MAC_ERA_MODEL), false, 'no model name is baked into the page');
});

test('a host that has the backend renders the training lane with the configured base model', () => {
  const summary = describeLearningAgentLane(
    lane({ host_available: true, availability_detail: 'Training backend mlx_qwen3 runs on this host (MLX (mlx + mlx_lm) is importable).' })
  );
  assert.equal(summary.state, 'host_ready');
  const blurb = learningAgentLaneBlurb(summary);
  assert.match(blurb, /^Train local adapters for example-org\/base-model-v9 on the host mlx_qwen3 backend\./);
  assert.doesNotMatch(blurb, /fail closed/);
});

test('an unsloth lane is described as a Flyte task, never as host execution', () => {
  const summary = describeLearningAgentLane(
    lane({
      execution_backend: 'unsloth',
      execution_locus: 'flyte_task',
      availability_detail: 'Unsloth executes inside the Flyte task image, not on this host; the Training Control Plane reports lane readiness.',
    })
  );
  assert.equal(summary.state, 'flyte_task');
  assert.match(learningAgentLaneBlurb(summary), /^Unsloth executes inside the Flyte task image/);
});

test('blank configured values are shown as unset instead of an invented default', () => {
  const summary = describeLearningAgentLane(lane({ base_model: '', artifact_path: '  ' }));
  assert.equal(summary.baseModel, '(unset)');
  assert.equal(summary.artifactPath, '(unset)');
  assert.equal(learningAgentLaneBlurb(summary).includes(MAC_ERA_MODEL), false);
});
