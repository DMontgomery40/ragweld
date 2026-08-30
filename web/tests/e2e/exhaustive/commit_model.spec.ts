// Commit model unification (GUI-drive M-08 / T6): a field edit stages LOCALLY and is written
// only by "Apply". Selecting a chunking strategy used to fire PATCH /api/config/chunking -> 200
// immediately, silently, with no dirty marker and no undo, while the footer's "Apply All
// Changes" implied edits were staged. This drives the real app + API and asserts: the selection
// fires no immediate PATCH, the Apply button reflects the staged count, and applying an
// index-invalidating change (chunking/embedding/tokenization) warns before it writes. Cancelling
// the confirmation writes nothing, so the test mutates no config.
import { expect, test } from '@playwright/test';

const CORPUS = process.env.CS_CORPUS ?? 'nasa-apollo-11';

test('chunking strategy stages locally, Apply counts the change and warns it invalidates the index', async ({ page, baseURL }) => {
  const configWrites: string[] = [];
  page.on('request', (req) => {
    const url = req.url();
    const method = req.method();
    if ((method === 'PATCH' && /\/api\/config\//.test(url)) || (method === 'PUT' && /\/api\/config(\?|$)/.test(url))) {
      configWrites.push(`${method} ${url}`);
    }
  });

  await page.goto(new URL(`rag?subtab=indexing&component=chunking&corpus=${CORPUS}`, baseURL).toString());

  const group = page.getByTestId('chunking-strategy-group');
  await expect(group).toBeVisible({ timeout: 60_000 });

  // Click a strategy card that is NOT the current selection, so the config actually changes.
  // Pin the target by its strategy id: `[aria-checked="false"].first()` is a live locator that
  // would re-resolve to the NEXT unselected card once this one becomes selected.
  const unselected = group.locator('[role="radio"][aria-checked="false"]').first();
  await expect(unselected).toBeVisible();
  const targetStrategy = await unselected.getAttribute('data-strategy');
  await unselected.click();
  const target = group.locator(`[data-strategy="${targetStrategy}"]`);
  await expect(target).toHaveAttribute('aria-checked', 'true');

  // Nothing may be written on selection: no PATCH, no PUT, well past the old 300ms debounce.
  await page.waitForTimeout(1200);
  expect(configWrites, `selecting a strategy must not write config: ${configWrites.join(' | ')}`).toEqual([]);

  // The Apply button now reflects the staged change: an enabled "Apply N changes" with a count.
  const apply = page.getByTestId('apply-changes');
  await expect(apply).toBeEnabled();
  await expect(apply).toContainText(/Apply \d+ change/);
  const dirty = Number(await apply.getAttribute('data-dirty-count'));
  expect(dirty).toBeGreaterThan(0);

  // Applying an index-invalidating change warns first, naming the index and the section.
  await apply.click();
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(page.getByTestId('confirm-dialog-message')).toContainText(/index/i);
  await expect(page.getByTestId('confirm-dialog-message')).toContainText(/chunking/i);

  // Cancel: no write happens, and the change is still staged.
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).not.toBeVisible();
  await page.waitForTimeout(500);
  expect(configWrites, `cancelling Apply must write nothing: ${configWrites.join(' | ')}`).toEqual([]);
  await expect(apply).toContainText(/Apply \d+ change/);
});
