// Operator confirmations must never use native window.confirm/alert/prompt:
// native dialogs block the renderer's main thread (freezing SSE streams and
// any automation driving the workbench) and present as a hard hang when the
// window is hidden. Regression for the 2026-08-24 Phase B finding where
// "Index Now" opened a blocking window.confirm. No request interception: the
// native functions are made to throw so any regression fails loudly, and the
// flow is driven against the real app and API.
import { expect, test } from '@playwright/test';

const API_BASE = process.env.RAGWELD_API_BASE_URL ?? 'http://127.0.0.1:58012';

test('Index Now confirmation is an in-app dialog and cancel starts no run', async ({ page, baseURL, request }) => {
  await page.addInitScript(() => {
    window.confirm = () => {
      throw new Error('native window.confirm called');
    };
    window.alert = () => {
      throw new Error('native window.alert called');
    };
    window.prompt = () => {
      throw new Error('native window.prompt called');
    };
  });

  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  const runBefore = await request
    .get(`${API_BASE}/api/index/aurora_acceptance/runs/latest`)
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);

  await page.goto(new URL('rag?subtab=indexing&corpus=aurora_acceptance', baseURL).toString());

  const indexNow = page.getByRole('button', { name: 'Index Now' });
  await expect(indexNow).toBeEnabled({ timeout: 60_000 });
  await indexNow.click();

  // The cost/time estimate confirmation renders as the in-app dialog.
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('confirm-dialog-message')).toContainText('Index estimate');

  // Cancelling must close the dialog and start no run.
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).not.toBeVisible();

  await page.waitForTimeout(1_500);
  const runAfter = await request
    .get(`${API_BASE}/api/index/aurora_acceptance/runs/latest`)
    .then((r) => (r.ok() ? r.json() : null))
    .catch(() => null);
  expect(runAfter?.run_id ?? null).toEqual(runBefore?.run_id ?? null);

  // The throwing native stubs prove nothing fell back to window.confirm/alert.
  expect(consoleErrors.filter((e) => e.includes('native window.'))).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
