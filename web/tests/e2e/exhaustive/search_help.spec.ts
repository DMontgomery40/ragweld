// Help, search and keyboard-accessibility regressions from the 2026-08-29 GUI drive,
// driven against the real app and API with no request interception:
//   M-135 Ctrl+K result titles must carry the parent group, not the leaf alone,
//   M-136 the top bar must not open the search modal on focus, and must trap focus,
//   M-137 the dock picker must be operable from the keyboard like Ctrl+K,
//   M-161 sidebar links must announce their label; the palette must expose listbox
//         semantics and a result count.
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

async function stableCorpusId(request: import('@playwright/test').APIRequestContext): Promise<string> {
  const res = await request.get(`${API_BASE}/corpora`);
  expect(res.ok(), `GET ${API_BASE}/corpora must succeed`).toBeTruthy();
  const corpora = (await res.json()) as Array<{ corpus_id: string; internal?: boolean }>;
  const usable =
    corpora.find((c) => c.corpus_id === 'ragweld_code') ??
    corpora.find((c) => !c.internal && !/^ragweld-(exhaustive|registry)-|^pytest_/.test(c.corpus_id)) ??
    corpora.find((c) => !c.internal) ??
    corpora[0];
  expect(usable?.corpus_id, 'the box must have at least one corpus registered').toBeTruthy();
  return usable.corpus_id;
}

async function gotoWeb(page: Page, baseURL: string | undefined, path: string): Promise<void> {
  await page.goto(new URL(path, baseURL).toString(), { waitUntil: 'domcontentloaded' });
}

test.describe('help, search and keyboard access', () => {
  let corpusId = '';

  test.beforeAll(async ({ request }) => {
    corpusId = await stableCorpusId(request);
  });

  test('M-136: focus does not open the palette, and the palette traps focus', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    const trigger = page.locator('#global-search');
    await expect(trigger).toBeVisible();

    // Tabbing across the top bar must not pop a modal open.
    await trigger.focus();
    await expect(page.getByRole('dialog', { name: 'Global search' })).toHaveCount(0);

    // Enter on the trigger opens it (so does Ctrl+K, covered elsewhere).
    await page.keyboard.press('Enter');
    const dialog = page.getByRole('dialog', { name: 'Global search' });
    await expect(dialog).toBeVisible();

    // Focus is trapped: however far Tab is pressed, it never lands outside the dialog.
    for (let i = 0; i < 6; i += 1) {
      await page.keyboard.press('Tab');
      const inside = await page.evaluate(() => {
        const dlg = document.querySelector('[role="dialog"][aria-label="Global search"]');
        return Boolean(dlg && document.activeElement && dlg.contains(document.activeElement));
      });
      expect(inside, `Tab press ${i + 1} moved focus outside the open palette`).toBeTruthy();
    }

    // Escape closes it and hands focus back to the control that opened it.
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test('M-161: the palette exposes listbox semantics and a result count', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.locator('#global-search').click();
    const dialog = page.getByRole('dialog', { name: 'Global search' });
    const input = dialog.getByRole('combobox');
    await expect(input).toBeVisible();
    await input.fill('figures');

    const options = dialog.getByRole('option');
    await expect(options.first()).toBeVisible({ timeout: 30_000 });
    const optionCount = await options.count();
    expect(optionCount, 'result rows must be exposed as options').toBeGreaterThan(0);

    await expect(dialog.getByRole('listbox')).toHaveCount(1);
    // A visible count, so a screen reader user and a sighted user get the same answer.
    await expect(dialog.getByTestId('global-search-count')).toContainText(String(optionCount));

    // The keyboard cursor is published, and it moves with the arrow keys.
    const active1 = await input.getAttribute('aria-activedescendant');
    expect(active1, 'the input must publish aria-activedescendant').toBeTruthy();
    await expect(dialog.locator(`#${active1}`)).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('ArrowDown');
    const active2 = await input.getAttribute('aria-activedescendant');
    expect(active2).not.toBe(active1);
    await expect(dialog.locator(`#${active2}`)).toHaveAttribute('aria-selected', 'true');
  });

  test('M-135: nested config hits are titled with their parent group', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.locator('#global-search').click();
    const dialog = page.getByRole('dialog', { name: 'Global search' });
    await dialog.getByRole('combobox').fill('figures');
    const row = dialog.locator('[data-testid="global-search-result"][data-path="indexing.figures.classify"]');
    await expect(row).toBeVisible({ timeout: 30_000 });
    // "Classify" alone says nothing; the title must name what it classifies.
    const title = await row.getByTestId('global-search-result-title').innerText();
    expect(title.toLowerCase()).toContain('figures');
    expect(title.toLowerCase()).toContain('classify');
  });

  test('M-161: every sidebar link announces its own label', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    const tabBar = page.getByTestId('tab-bar');
    await expect(tabBar).toBeVisible();
    const links = tabBar.getByRole('link');
    await expect(links.first()).toBeVisible();
    const count = await links.count();
    expect(count).toBeGreaterThan(5);
    for (let i = 0; i < count; i += 1) {
      const link = links.nth(i);
      const visible = (await link.innerText()).replace(/\s*📌\s*$/, '').trim();
      const accessible = (await link.getAttribute('aria-label')) ?? '';
      expect(accessible, `sidebar link ${i} must announce "${visible}"`).toBe(visible);
    }
  });

  test('M-137: the dock picker is operable from the keyboard', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.getByTestId('dock-choose').click();
    const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
    await expect(picker).toBeVisible();

    const search = picker.getByRole('combobox');
    await search.fill('glossary');
    const options = picker.getByRole('option');
    await expect(options.first()).toBeVisible();

    // Down-then-Enter must activate the highlighted row, exactly like Ctrl+K.
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    await expect(picker).toHaveCount(0);
    await expect(page.getByTestId('dock-title')).toContainText(/glossary/i);
  });
});
