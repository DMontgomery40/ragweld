// Benchmark tab defects (wave 2b, lane chat2). Read-only: the model list comes from
// GET /api/chat/models and past runs from GET /api/benchmark/results. No benchmark is started
// here, so the file costs nothing; the one live run for proof is a separate manual step.
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:58012/api';

async function gotoBenchmark(page: Page): Promise<void> {
  await page.goto('benchmark', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('benchmark-tab')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('benchmark-model-list')).toBeVisible({ timeout: 60_000 });
}

type LocalLane = { alias: string; backend: string; backend_label: string; enabled: boolean };

/** The local serving lane as the host really reports it: capabilities switch + readiness probe. */
async function liveLocalLane(request: APIRequestContext): Promise<{ lane: LocalLane; selectable: boolean }> {
  const caps = await request.get(`${API_BASE}/runtime-capabilities`);
  expect(caps.ok(), 'runtime capabilities must answer').toBeTruthy();
  const lane = (await caps.json()).generation?.local_serving as LocalLane | undefined;
  expect(lane, 'generation.local_serving is a typed capability field').toBeTruthy();
  const ready = await request.get(`${API_BASE}/ready`);
  expect([200, 503], 'readiness answers 200 or 503 with the same shape').toContain(ready.status());
  const probe = (await ready.json()).dependencies?.[lane!.backend] as { ok?: boolean } | undefined;
  return { lane: lane!, selectable: lane!.enabled === true && probe?.ok === true };
}

test.describe.serial('benchmark workbench (read-only)', () => {
  test('S11: the default selection only pre-checks the local lane when this host serves it', async ({ page, request }) => {
    const { lane, selectable } = await liveLocalLane(request);
    await gotoBenchmark(page);

    const rows = page.getByTestId('benchmark-model-row');
    const checked = page.getByTestId('benchmark-model-list').locator('input[type="checkbox"]:checked');
    await expect(checked, 'two models are pre-selected once the lane truth has loaded').toHaveCount(2, { timeout: 60_000 });

    const aliases = await rows.evaluateAll((els) => els.map((el) => String(el.getAttribute('data-alias') || '')));
    const checkedAliases = await page
      .getByTestId('benchmark-model-list')
      .locator('label:has(input[type="checkbox"]:checked)')
      .evaluateAll((els) => els.map((el) => String(el.getAttribute('data-alias') || '')));
    const expected = aliases.filter((alias) => selectable || alias !== lane.alias).slice(0, 2);
    expect(checkedAliases, `defaults follow the page order, skipping ${lane.alias} unless its lane is live`).toEqual(expected);

    const localRow = rows.filter({ has: page.locator(`[data-alias="${lane.alias}"]`) }).or(page.locator(`[data-testid="benchmark-model-row"][data-alias="${lane.alias}"]`));
    if (await localRow.count()) {
      const laneState = localRow.first().getByTestId('benchmark-local-lane-state');
      await expect(laneState).toBeVisible();
      await expect(laneState).toHaveAttribute('data-reachable', selectable ? 'true' : 'false');
      await expect(laneState).toContainText(lane.backend_label);
      await expect(localRow.first().locator('input[type="checkbox"]')).toBeChecked({ checked: selectable });
      // The row name must not claim a serving backend: that is the lane state's job.
      await expect(localRow.first()).not.toContainText(/Metal|MLX|Apple/);
    }
  });


  test('M-102: the model list is filterable and height-capped', async ({ page }) => {
    await gotoBenchmark(page);

    const checkboxes = page.getByTestId('benchmark-model-list').locator('input[type="checkbox"]');
    const initialCount = await checkboxes.count();
    expect(initialCount, 'expected the catalog to load some models').toBeGreaterThan(1);

    // The outcome B-14 is about: scrolling through the models must NOT push Run off screen.
    // Scroll the model list to its bottom, then assert the Run button is still in the viewport.
    await page.getByTestId('benchmark-model-list').evaluate((el) => {
      el.scrollTop = el.scrollHeight;
    });
    const runBox = await page.getByTestId('benchmark-run').boundingBox();
    const viewport = page.viewportSize();
    expect(runBox, 'Run button should be laid out').not.toBeNull();
    if (runBox && viewport) {
      expect(runBox.y, 'Run stays on screen after scrolling the model list').toBeGreaterThanOrEqual(0);
      expect(runBox.y + runBox.height, 'Run bottom stays within the viewport').toBeLessThanOrEqual(viewport.height);
    }

    // Filtering narrows the list; a nonsense query yields an explicit empty message.
    await page.getByTestId('benchmark-model-filter').fill('zzzz-not-a-real-model-zzzz');
    await expect(page.getByTestId('benchmark-model-list')).toHaveCount(0);
    await expect(page.getByText(/No models match/)).toBeVisible();

    await page.getByTestId('benchmark-model-filter').fill('');
    await expect(page.getByTestId('benchmark-model-list').locator('input[type="checkbox"]')).toHaveCount(initialCount);
  });

  test('M-103: an un-run benchmark shows an honest empty state and past-runs area', async ({ page }) => {
    await gotoBenchmark(page);

    const empty = page.getByTestId('benchmark-empty-state');
    await expect(empty).toBeVisible();
    await expect(empty).toContainText('What a benchmark produces');
    // Either recorded runs render, or an explicit "no past runs" line — never a blank panel.
    const hasPast = await page.getByTestId('benchmark-past-runs').count();
    const hasNone = await page.getByTestId('benchmark-no-past-runs').count();
    expect(hasPast + hasNone).toBeGreaterThan(0);
  });

  test('M-103: selecting models and a prompt shows an estimated cost', async ({ page }) => {
    await gotoBenchmark(page);
    // The tab auto-selects the first two models; entering a prompt satisfies the run gate.
    await page.getByPlaceholder('Enter a prompt to run across multiple models…').fill('Summarize the retrieval pipeline in one sentence.');
    const estimate = page.getByTestId('benchmark-cost-estimate');
    await expect(estimate).toBeVisible();
    await expect(estimate).toContainText(/Estimated cost/);
    await expect(estimate).toContainText(/\$/);
  });
});
