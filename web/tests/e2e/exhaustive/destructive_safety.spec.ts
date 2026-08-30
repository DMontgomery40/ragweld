// Destructive-action safety (GUI-drive M-11 / T7): the delete-index confirm dialog used to
// AUTOFOCUS the destructive "Delete index" button, so a stray Enter/Space right after it opened
// permanently destroyed the corpus's embeddings, chunks, Qdrant generations and Neo4j graph. The
// fix focuses Cancel and gates the irreversible action behind a typed corpus id. This drives the
// real app; it cancels the dialog and asserts no DELETE ever reaches the API, so nothing is
// destroyed.
import { expect, test } from '@playwright/test';

const CORPUS = process.env.CS_CORPUS ?? 'nasa-apollo-11';

test('delete-index confirm focuses Cancel and stays disabled until the corpus id is typed', async ({ page, baseURL }) => {
  const deleteCalls: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'DELETE' && /\/api\/index\//.test(req.url())) deleteCalls.push(req.url());
  });

  await page.goto(new URL(`rag?subtab=indexing&corpus=${CORPUS}`, baseURL).toString());

  const deleteBtn = page.getByTestId('delete-index');
  await expect(deleteBtn).toBeEnabled({ timeout: 60_000 });
  await deleteBtn.click();

  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 15_000 });

  // The dialog names exactly what is destroyed.
  const message = page.getByTestId('confirm-dialog-message');
  await expect(message).toContainText(/Neo4j graph/i);
  await expect(message).toContainText(/Qdrant/i);

  // M-11: focus is NEVER on the destructive confirm, so a stray Enter/Space right after the
  // dialog opens cannot destroy the index. For this typed variant it lands on the input the
  // operator must fill (and the confirm is disabled until then), which is the deliberate step.
  const focusedTestId = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') || '');
  expect(focusedTestId).not.toBe('confirm-dialog-accept');
  expect(focusedTestId).toBe('confirm-dialog-typed-input');

  // The confirm is disabled until the corpus id is typed verbatim (a deliberate second step for
  // an irreversible op).
  const accept = page.getByTestId('confirm-dialog-accept');
  await expect(accept).toBeDisabled();

  const typed = page.getByTestId('confirm-dialog-typed-input');
  await typed.fill('not-the-corpus');
  await expect(accept).toBeDisabled();

  await typed.fill(CORPUS);
  await expect(accept).toBeEnabled();

  // Cancel — never actually delete the index.
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).not.toBeVisible();
  await page.waitForTimeout(400);
  expect(deleteCalls, `cancelling must issue no DELETE: ${deleteCalls.join(' | ')}`).toEqual([]);
});

test('a danger confirm with no typed gate focuses Cancel (Paths save)', async ({ page, baseURL }) => {
  // The Paths "Save Configuration" confirm is danger with no requireTyped, so it exercises the
  // shared primitive's other focus branch: focus lands on Cancel, not the confirm.
  const writes: string[] = [];
  page.on('request', (req) => {
    const url = req.url();
    if ((req.method() === 'PATCH' || req.method() === 'PUT') && /\/api\/config/.test(url)) writes.push(url);
  });

  await page.goto(new URL(`infrastructure?subtab=paths&corpus=${CORPUS}`, baseURL).toString());

  const save = page.getByRole('button', { name: 'Save Configuration' });
  await expect(save).toBeVisible({ timeout: 60_000 });
  await save.click();

  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('confirm-dialog-message')).toContainText(/database connection/i);

  const focusedTestId = await page.evaluate(() => document.activeElement?.getAttribute('data-testid') || '');
  expect(focusedTestId).toBe('confirm-dialog-cancel');

  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).not.toBeVisible();
  await page.waitForTimeout(300);
  expect(writes, `cancelling the save must write nothing: ${writes.join(' | ')}`).toEqual([]);
});
