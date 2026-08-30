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

    // Every top-bar tab stop shows a real focus ring. `--ring` is a 20%-alpha slate and a
    // blanket `input:focus-visible { outline: none }` removed the global outline, so the
    // first tab stops of the page had no visible indicator at all.
    await page.locator('.topbar button').first().focus();
    for (let i = 0; i < 4; i += 1) {
      const ring = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el) return null;
        const cs = getComputedStyle(el);
        // A ring counts if it is a >=2px outline OR a >=2px box-shadow in a fully opaque
        // colour. `rgba(...)` in a shadow means a translucent ring, which is exactly the
        // 20%-alpha `--ring` that made these stops look unfocused.
        const shadow = cs.boxShadow || 'none';
        const opaqueSpread = /rgb\(\d+,\s*\d+,\s*\d+\)[^,]*?\b([2-9]|\d{2,})px\b/.test(shadow);
        return {
          id: el.id || el.tagName,
          inTopbar: Boolean(el.closest('.topbar')),
          outline: `${cs.outlineStyle} ${cs.outlineWidth}`,
          shadow,
          visible:
            (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth || '0') >= 2) || opaqueSpread,
        };
      });
      if (!ring?.inTopbar) break;
      expect(
        ring.visible,
        `${ring.id} has no visible focus ring (outline: ${ring.outline}, box-shadow: ${ring.shadow})`
      ).toBe(true);
      await page.keyboard.press('Tab');
    }
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

  test('M-133 / M-160: glossary chips come from the data and count the current search', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=glossary');

    const all = page.getByTestId('glossary-count-all');
    await expect(all).toBeVisible({ timeout: 30_000 });
    const readCount = async (testId: string) =>
      Number(((await page.getByTestId(testId).innerText()) || '').replace(/[^0-9]/g, ''));

    // Every term is reachable through some chip: the chips sum to the All total.
    const chips = page.locator('[data-testid^="glossary-chip-"]');
    await expect(chips.first()).toBeVisible();
    const chipIds = await chips.evaluateAll((els) =>
      els.map((el) => (el.getAttribute('data-testid') || '').replace('glossary-chip-', ''))
    );
    expect(chipIds.length).toBeGreaterThan(6);
    // One badge per category: two chips sharing a code is a badge that identifies nothing.
    const badges = await chips.evaluateAll((els) =>
      els.map((el) => (el.querySelector('[aria-hidden="true"]')?.textContent || '').trim())
    );
    expect(new Set(badges).size, `duplicate category badges: ${badges.join(', ')}`).toBe(badges.length);
    let summed = 0;
    for (const id of chipIds) summed += await readCount(`glossary-count-${id}`);
    expect(summed, 'the category chips must account for every term').toBe(await readCount('glossary-count-all'));

    // The counts describe the search result, not the unfiltered totals.
    const unfiltered = await readCount('glossary-count-all');
    await page.locator('input.glossary-search').fill('figure');
    await expect(all).not.toHaveText(`(${unfiltered})`);
    const searched = await readCount('glossary-count-all');
    expect(searched).toBeGreaterThan(0);
    expect(searched).toBeLessThan(unfiltered);
    const searchedChips = await page.locator('[data-testid^="glossary-chip-"]').evaluateAll((els) =>
      els.map((el) => Number((el.textContent || '').match(/\((\d+)\)/)?.[1] ?? '0'))
    );
    expect(searchedChips.reduce((a, b) => a + b, 0)).toBe(searched);
  });

  test('M-134: glossary search matches on word boundaries, names first', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=glossary');
    await expect(page.getByTestId('glossary-count-all')).toBeVisible({ timeout: 30_000 });
    await page.locator('input.glossary-search').fill('figure');

    const titles = await page.locator('.glossary-card .glossary-card-title strong').allInnerTexts();
    expect(titles.length).toBeGreaterThan(0);
    // "Enrichment Model" and friends only matched through *con-figure-d*.
    expect(titles).not.toContain('Enrichment Model');
    // The genuine hits lead, rather than sitting at positions 2 and 8.
    expect(titles[0].toLowerCase()).toContain('figure');
    expect(titles[1].toLowerCase()).toContain('figure');
  });

  test('M-132: TOTAL CORPORA has help of its own', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');

    const total = page.locator('text=Total corpora').first();
    await expect(total).toBeVisible({ timeout: 30_000 });
    const activeHelp = page.locator('[aria-label="Help: SYS_STATUS_CORPUS"], [title="Help: SYS_STATUS_CORPUS"]');
    const totalHelp = page.locator(
      '[aria-label="Help: SYS_STATUS_CORPORA_TOTAL"], [title="Help: SYS_STATUS_CORPORA_TOTAL"]'
    );
    // The count and the selection are different questions and must not share one entry.
    await expect(totalHelp).toHaveCount(1);
    await expect(activeHelp).toHaveCount(1);
  });

  test('M-28: Admin Basic names the corpus it is editing and tags each field scope', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'admin?subtab=basic');

    const banner = page.getByTestId('admin-basic-scope');
    await expect(banner).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('admin-basic-scope-corpus')).toHaveText(corpusId);

    // Every field says whether a save lands on this corpus or on the deployment.
    const scopeChips = page.locator('[data-testid^="config-field-scope-"]');
    await expect(scopeChips.first()).toBeVisible();
    const labels = await scopeChips.allInnerTexts();
    expect(labels.length).toBeGreaterThan(3);
    for (const label of labels) expect(['corpus', 'global']).toContain(label.trim());
  });

  test('M-131: every Ops & Tracing and Semantic Cache control carries help', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'rag?subtab=retrieval');

    const opsPill = page.getByRole('button', { name: /Ops & Tracing/i }).first();
    await expect(opsPill).toBeVisible({ timeout: 30_000 });
    await opsPill.click();

    // Tooltip coverage stopped at this tab: ~24 controls with no "?" at all, precisely the
    // settings whose defaults an operator can least reason about. Both inner pills.
    const cacheHelp = page.locator('[aria-label^="Help: SEMANTIC_CACHE_"]');
    await expect(cacheHelp).toHaveCount(13);

    await page.getByRole('button', { name: /Observability/i }).first().click();
    await expect(page.getByTestId('retrieval-section-ops-integrations')).toBeVisible();
    for (const key of [
      'OTLP_ENDPOINT',
      'OTEL_SERVICE_NAME',
      'OTLP_HEADERS',
      'COST_TRACKING_ENABLED',
      'LANGFUSE_ENABLED',
      'LANGFUSE_BASE_URL',
      'LANGFUSE_PUBLIC_BASE_URL',
      'LANGFUSE_PROJECT',
      'LANGFUSE_PUBLIC_KEY',
      'TEMPO_BASE_URL',
      'ALLOY_BASE_URL',
    ]) {
      await expect(
        page.locator(`[aria-label="Help: ${key}"]`),
        `${key} must carry a help icon`
      ).toHaveCount(1);
    }

    // Every one of those keys resolves to real glossary copy, not the fallback.
    const glossary = await page.evaluate(async () => {
      const res = await fetch('/web/glossary.json', { cache: 'no-store' });
      const data = await res.json();
      return (data.terms || []).map((t: { key: string; definition: string }) => [t.key, t.definition.length]);
    });
    const byKey = new Map<string, number>(glossary as Array<[string, number]>);
    for (const key of [
      'SEMANTIC_CACHE_ENABLED',
      'SEMANTIC_CACHE_MODE',
      'SEMANTIC_CACHE_MAX_TEMPERATURE_FOR_WRITE',
      'OTLP_HEADERS',
      'ALLOY_BASE_URL',
    ]) {
      expect(byKey.get(key) ?? 0, `${key} needs a substantial definition`).toBeGreaterThan(120);
    }
  });

  test('M-91: the MCP endpoint advertised is the configured public origin', async ({ page, baseURL, request }) => {
    const status = await (await request.get(`${API_BASE}/mcp/status`)).json();
    const http = status.python_http;
    test.skip(!http, 'the MCP HTTP transport is not enabled on this deployment');

    const config = await (await request.get(`${API_BASE}/config`)).json();
    const expected = `${String(config.mcp.public_base_url).replace(/\/+$/, '')}${http.path}`;
    // The server owns the string; the workbench must render exactly it. The old client-side
    // build produced `http://<request host>:80/mcp/` -- plain HTTP on an HTTPS-only box.
    expect(http.url).toBe(expected);

    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'infrastructure?subtab=mcp');
    const link = page.getByTestId('mcp-http-url');
    await expect(link).toBeVisible({ timeout: 30_000 });
    await expect(link).toHaveText(http.url);
    await expect(link).toHaveAttribute('href', http.url);
    // Nothing on the page reconstructs a scheme/host of its own any more.
    expect(await link.innerText()).not.toMatch(/:80\//);
  });

  test('M-88: the DSN field says the password is withheld, and keeps it on save', async ({ page, baseURL, request }) => {
    const config = await (await request.get(`${API_BASE}/config`)).json();
    const dsn = String(config.indexing.postgres_url);
    expect(dsn, 'the API must already be withholding the password').toContain('[redacted]');

    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'infrastructure?subtab=paths');
    const field = page.getByTestId('postgres-url');
    await expect(field).toBeVisible({ timeout: 30_000 });
    await expect(field).toHaveValue(dsn);
    // The marker is explained rather than left looking like a corrupted value.
    await expect(page.getByTestId('postgres-url-configured')).toBeVisible();
    await expect(page.getByTestId('postgres-url-secret-note')).toContainText('[redacted]');
    // And the field never shows a credential pair, not even as a placeholder.
    expect(await field.getAttribute('placeholder')).not.toMatch(/:[^@/]+@/);
  });

  test('M-80: the Frontend row reports how the frontend is actually served', async ({ page, baseURL, request }) => {
    const dev = await (await request.get(`${API_BASE}/dev/status`)).json();
    expect(['dev_server', 'built_bundle', 'absent']).toContain(dev.frontend_mode);

    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    const row = page.getByTestId('dash-frontend-status');
    await expect(row).toBeVisible({ timeout: 30_000 });

    // A red "stopped" must mean something is wrong. A built bundle behind a proxy is a
    // healthy deployment and had been reported as a permanent failure (M-80).
    if (dev.frontend_mode === 'absent') {
      await expect(row).toContainText('not built');
    } else {
      await expect(row).not.toContainText('stopped');
      await expect(row).toContainText(dev.frontend_mode === 'dev_server' ? 'dev server' : 'built bundle');
    }
  });
});

