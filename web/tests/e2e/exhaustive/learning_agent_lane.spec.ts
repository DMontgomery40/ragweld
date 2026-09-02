// S16: the Learning Agent Studio header states the training lane this host really has,
// read from GET /api/runtime-capabilities (training.learning_agent), never from copy baked
// into the page. Read-only: no run is started.
import { expect, test } from '@playwright/test';

const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:58012/api';

type LearningAgentLane = {
  execution_backend: string;
  execution_locus: 'host' | 'flyte_task';
  host_available: boolean;
  availability_detail: string;
  base_model: string;
  artifact_path: string;
};

test('S16: the studio header renders the host-truth training lane', async ({ page, request }) => {
  const caps = await request.get(`${API_BASE}/runtime-capabilities`);
  expect(caps.ok(), 'runtime capabilities must answer').toBeTruthy();
  const lane = (await caps.json()).training?.learning_agent as LearningAgentLane | undefined;
  expect(lane, 'training.learning_agent is a typed capability field').toBeTruthy();
  const expectedState =
    lane!.execution_locus === 'flyte_task' ? 'flyte_task' : lane!.host_available ? 'host_ready' : 'host_unavailable';

  await page.goto('rag?subtab=learning-agent', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('learning-agent-training-studio')).toBeVisible({ timeout: 60_000 });

  const summary = page.getByTestId('learning-agent-lane-summary');
  await expect(summary).toHaveAttribute('data-lane-state', expectedState, { timeout: 60_000 });
  await expect(summary).toContainText(lane!.base_model || '(unset)');
  await expect(summary).toContainText(lane!.artifact_path || '(unset)');
  await expect(summary).not.toContainText('Flyte / MLflow / Unsloth control plane');

  if (expectedState === 'host_unavailable') {
    await expect(summary).toContainText(
      `Training backend ${lane!.execution_backend} is not available on this host; runs will fail closed.`
    );
    await expect(summary).not.toContainText('Train local adapters for');
  } else if (expectedState === 'host_ready') {
    await expect(summary).toContainText(`on the host ${lane!.execution_backend} backend`);
  } else {
    await expect(summary).toContainText('Flyte task image');
  }

  // The Training Control Plane panel's operator hint (also the Grafana deck's Learning
  // Agent line) must agree with the lane truth.
  const controlPlane = await request.get(`${API_BASE}/agent/train/control-plane/status`);
  expect(controlPlane.ok()).toBeTruthy();
  const hint = String((await controlPlane.json()).operator_hint || '');
  if (lane!.execution_locus === 'host') {
    expect(hint).toContain(
      lane!.host_available
        ? `training executes on the host ${lane!.execution_backend} backend`
        : `training backend ${lane!.execution_backend} is not available on this host; runs will fail closed`
    );
  }
});
