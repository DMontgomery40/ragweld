// Benchmark tab defects (wave 2b, lane chat2). Read-only: the model list comes from
// GET /api/chat/models and past runs from GET /api/benchmark/results. No benchmark is started
// here, so the file costs nothing; the one live run for proof is a separate manual step.
import { expect, test, type Page } from '@playwright/test';

async function gotoBenchmark(page: Page): Promise<void> {
  await page.goto('benchmark', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('benchmark-tab')).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId('benchmark-model-list')).toBeVisible({ timeout: 60_000 });
}

test.describe.serial('benchmark workbench (read-only)', () => {
  test('M-102: the model list is filterable and height-capped', async ({ page }) => {
    await gotoBenchmark(page);

    const checkboxes = page.getByTestId('benchmark-model-list').locator('input[type="checkbox"]');
    const initialCount = await checkboxes.count();
    expect(initialCount, 'expected the catalog to load some models').toBeGreaterThan(1);

    // The list scrolls within its own box instead of growing the page and pushing Run off
    // screen (B-14): a real max-height and its own vertical scroll.
    const listStyle = await page.getByTestId('benchmark-model-list').evaluate((el) => {
      const cs = getComputedStyle(el);
      return { maxHeight: cs.maxHeight, overflowY: cs.overflowY };
    });
    expect(listStyle.maxHeight).not.toBe('none');
    expect(['auto', 'scroll']).toContain(listStyle.overflowY);

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
