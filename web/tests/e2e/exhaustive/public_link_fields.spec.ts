import { expect, test } from '@playwright/test';

const PUBLIC_LINK_HINT = 'Browser links use this; ingestion/tracking uses the local URL.';

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
  await expect(page.getByTestId('retrieval-langfuse-public-base-url-hint')).toHaveText(PUBLIC_LINK_HINT);
  await langfusePublicBaseUrl.focus();
  await expect(langfusePublicBaseUrl).toBeFocused();

  await page.goto(new URL('rag?subtab=learning-agent', baseURL).toString());

  const trainingStudio = page.getByTestId('learning-agent-training-studio');
  await expect(trainingStudio).toBeVisible();
  await trainingStudio.getByRole('button', { name: 'Config' }).click();
  await expect(page.getByTestId('studio-config-panel')).toBeVisible();
  await page.getByTestId('learning-agent-target-lane-summary').click();

  const mlflowConsoleBaseUrl = page.getByTestId('learning-agent-mlflow-console-base-url');
  await expect(mlflowConsoleBaseUrl).toBeVisible();
  await expect(mlflowConsoleBaseUrl).toBeEditable();
  await expect(page.getByTestId('learning-agent-mlflow-console-base-url-hint')).toHaveText(PUBLIC_LINK_HINT);
  await mlflowConsoleBaseUrl.focus();
  await expect(mlflowConsoleBaseUrl).toBeFocused();
});
