import { expect, test, type Locator } from '@playwright/test';

const PUBLIC_LINK_HINT = 'Browser links use this; ingestion/tracking uses the local URL.';

async function expectReadableMutedHint(hint: Locator) {
  await expect(hint).toHaveText(PUBLIC_LINK_HINT);
  const fontSize = await hint.evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
  expect(fontSize).toBeGreaterThanOrEqual(12);
}

test('Dedicated retrieval and training surfaces expose public browser link controls without mutating runtime state', async ({
  page,
  baseURL,
}) => {
  await page.goto(new URL('rag?subtab=retrieval', baseURL).toString());

  await expect(page.getByTestId('retrieval-subtab')).toBeVisible();
  await page.getByTestId('retrieval-card-ops_tracing').click();
  await page.getByTestId('retrieval-ops-tab-observability').click();

  const langfusePublicBaseUrl = page.getByTestId('retrieval-langfuse-public-base-url');
  await expect(langfusePublicBaseUrl).toBeVisible();
  await expect(langfusePublicBaseUrl).toBeEditable();
  await expectReadableMutedHint(page.getByTestId('retrieval-langfuse-public-base-url-hint'));
  await langfusePublicBaseUrl.focus();
  await expect(langfusePublicBaseUrl).toBeFocused();

  await page.goto(new URL('rag?subtab=learning-agent', baseURL).toString());

  const trainingStudio = page.getByTestId('learning-agent-training-studio');
  await expect(trainingStudio).toBeVisible();
  await trainingStudio.getByRole('button', { name: 'Config' }).click();
  await expect(page.getByTestId('studio-config-panel')).toBeVisible();
  const targetLaneSummary = page.getByTestId('learning-agent-target-lane-summary');
  const targetLane = targetLaneSummary.locator('..');
  if (!(await targetLane.evaluate((details) => (details as HTMLDetailsElement).open))) {
    await targetLaneSummary.click();
  }
  await page.waitForTimeout(750);
  await expect(targetLane).toHaveAttribute('open', '');

  const mlflowConsoleBaseUrl = page.getByTestId('learning-agent-mlflow-console-base-url');
  await expect(mlflowConsoleBaseUrl).toBeVisible();
  await expect(mlflowConsoleBaseUrl).toBeEditable();
  await expectReadableMutedHint(page.getByTestId('learning-agent-mlflow-console-base-url-hint'));
  await mlflowConsoleBaseUrl.focus();
  await expect(mlflowConsoleBaseUrl).toBeFocused();
});
