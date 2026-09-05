// Legibility / layout floor for the app shell (T15 / M-113 X-14, M-114 X-15).
//
// M-113: the shell must be exactly the viewport height (100dvh) with the fixed
// footer at the very bottom -- no dead band under it. The drive measured a
// ~100-180px blank band below the Apply footer at 1366x768 and 1024x768 because
// the layout height was pinned to `calc(100vh - 56px)`, a magic number that is
// wrong wherever the topbar is not 56px tall (52px at <=1024px).
//
// M-114: below ~1200px the chrome must narrow so the centre column keeps a
// readable width and never grows a horizontal scrollbar. Above 1200px nothing
// narrows (the breakpoint boundary is asserted too).
//
// Measured at deviceScaleFactor 1 to match the native-resolution drive. No
// request interception: driven against the real app + API.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { expect, test, type Locator, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';
import { assertPrivateNativeConfig, privateNativeChildEnv, type NativeFixtureConfig } from './native_cost_fixture';

type ShellGeom = {
  innerH: number;
  innerW: number;
  footerBottom: number | null;
  rootH: number;
  docScrollH: number;
  sidebarW: number | null;
  mainW: number | null;
  sidepanelW: number | null;
  scrollCW: number | null;
  scrollSW: number | null;
};

async function measureShell(page: import('@playwright/test').Page, baseURL: string | undefined): Promise<ShellGeom> {
  await page.goto(new URL('dashboard', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.layout', { timeout: 20000 });
  // Let the shell settle (initial config/health fetch, resizable-sidepanel bind).
  await page.waitForTimeout(800);
  return page.evaluate((): ShellGeom => {
    const w = (s: string): number | null => {
      const e = document.querySelector(s) as HTMLElement | null;
      return e ? Math.round(e.getBoundingClientRect().width) : null;
    };
    const footer = document.querySelector('.app-footer-actions') as HTMLElement | null;
    const scroll = document.querySelector('.content-scroll') as HTMLElement | null;
    const root = document.getElementById('root') as HTMLElement;
    return {
      innerH: window.innerHeight,
      innerW: window.innerWidth,
      footerBottom: footer ? Math.round(footer.getBoundingClientRect().bottom) : null,
      rootH: Math.round(root.getBoundingClientRect().height),
      docScrollH: document.documentElement.scrollHeight,
      sidebarW: w('.sidebar'),
      mainW: w('.main-content'),
      sidepanelW: w('.sidepanel'),
      scrollCW: scroll ? scroll.clientWidth : null,
      scrollSW: scroll ? scroll.scrollWidth : null,
    };
  });
}

for (const vp of [
  { w: 1366, h: 768 },
  { w: 1024, h: 768 },
]) {
  test.describe(`app shell at ${vp.w}x${vp.h}`, () => {
    test.use({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: 1 });

    test(`fills the viewport with no dead band under the footer (${vp.w}x${vp.h})`, async ({ page, baseURL }) => {
      const g = await measureShell(page, baseURL);

      // Shell is exactly the viewport tall (100dvh); #root does not overflow it.
      expect(Math.abs(g.rootH - g.innerH), `#root ${g.rootH} != viewport ${g.innerH}`).toBeLessThanOrEqual(1);
      expect(g.docScrollH, `page scrolls vertically (docScrollH ${g.docScrollH} > innerH ${g.innerH})`).toBeLessThanOrEqual(g.innerH + 1);

      // The fixed footer sits at the very bottom -- no dead band below it.
      expect(g.footerBottom).not.toBeNull();
      const deadBand = g.innerH - (g.footerBottom as number);
      expect(deadBand, `dead band of ${deadBand}px below the footer`).toBeLessThanOrEqual(2);
      expect(deadBand, `footer overshoots the viewport by ${-deadBand}px`).toBeGreaterThanOrEqual(-2);

      // The centre column never grows a horizontal scrollbar.
      expect(g.scrollCW).not.toBeNull();
      expect(
        (g.scrollSW as number) - (g.scrollCW as number),
        `content scrolls horizontally (scrollW ${g.scrollSW} > clientW ${g.scrollCW})`,
      ).toBeLessThanOrEqual(1);
    });
  });
}

test.describe('compact chrome breakpoint (<=1200px)', () => {
  test.use({ viewport: { width: 1024, height: 768 }, deviceScaleFactor: 1 });

  test('at 1024px the rail and sidebar narrow so the content keeps its width', async ({ page, baseURL }) => {
    const g = await measureShell(page, baseURL);
    // Sidebar narrowed from 170px, sidepanel track from 360px.
    expect(g.sidebarW, `sidebar ${g.sidebarW} did not narrow`).toBeLessThanOrEqual(155);
    expect(g.sidepanelW, `sidepanel ${g.sidepanelW} did not narrow`).toBeLessThanOrEqual(325);
    // The content column is meaningfully wider than the un-narrowed ~494px.
    expect(g.mainW as number, `content column only ${g.mainW}px wide`).toBeGreaterThanOrEqual(540);
  });
});

test.describe('breakpoint boundary (>1200px)', () => {
  test.use({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 });

  test('above 1200px the full-width chrome is kept', async ({ page, baseURL }) => {
    const g = await measureShell(page, baseURL);
    // Full sidebar (170px) and default sidepanel (360px) -- the breakpoint has
    // not fired, proving it is bounded to <=1200px and not always-on.
    expect(g.sidebarW as number, `sidebar unexpectedly narrowed to ${g.sidebarW}`).toBeGreaterThanOrEqual(165);
    expect(g.sidepanelW as number, `sidepanel unexpectedly narrowed to ${g.sidepanelW}`).toBeGreaterThanOrEqual(350);
  });
});

// These are CSS viewport widths, not a 360px dock inside a desktop viewport.
// The source fixture writes real documents/chunks/mentions to the private stores;
// no indexing, provider calls, request interception, or production corpus reuse.
function mobileSourceFixture(operation: 'create' | 'delete', fixture?: Record<string, string>): Record<string, string> | null {
  const env = privateNativeChildEnv(process.env, process.cwd());
  const configPath = process.env.RAGWELD_TEST_CONFIG_PATH;
  if (!configPath) throw new Error('mobile shell fixtures require RAGWELD_TEST_CONFIG_PATH');
  const config = JSON.parse(readFileSync(configPath, 'utf8')) as NativeFixtureConfig;
  assertPrivateNativeConfig(config);
  const output = execFileSync(process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python', [
    'web/tests/e2e/exhaustive/graph_sources_fixture.py', operation, API_BASE,
    ...(fixture ? [JSON.stringify(fixture)] : []),
  ], {
    cwd: process.cwd(), encoding: 'utf8', timeout: 60_000,
    env: {
      ...env,
      POSTGRES_DSN: config.indexing.postgres_url,
      NEO4J_URI: config.graph_storage.neo4j_uri,
      NEO4J_USER: 'neo4j',
      NEO4J_PASSWORD: 'ci-fixture-only',
    },
  });
  return operation === 'create' ? JSON.parse(output) as Record<string, string> : null;
}

async function expectReachable(target: Locator): Promise<void> {
  // Config/route changes can replace the rendered button between resolving the
  // locator and scrolling it. Re-resolve the whole read-only check; clicks below
  // still occur once, normally, and must receive real pointer events.
  await expect(async () => {
    await target.scrollIntoViewIfNeeded({ timeout: 1000 });
    const receivesPointer = await target.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
      return !!hit && (hit === element || element.contains(hit));
    });
    expect(receivesPointer, 'the control center must receive a real pointer event after ordinary scrolling').toBe(true);
  }).toPass({ timeout: 30_000 });
}

async function expectDrawerBelowHeader(page: Page): Promise<void> {
  await expect.poll(async () => {
    const sidebar = (await page.locator('.sidebar').boundingBox())!;
    const header = (await page.locator('.topbar').boundingBox())!;
    const layout = (await page.locator('.layout').boundingBox())!;
    return sidebar.y >= header.y + header.height - 1 && Math.abs(sidebar.y - layout.y) <= 1;
  }, { message: 'the drawer must begin below the actual wrapped header, at the layout top' }).toBe(true);
}

async function expectPaneBounds(page: Page, stacked: boolean): Promise<void> {
  const geometry = await page.evaluate(() => {
    const box = (selector: string) => {
      const element = document.querySelector(selector)!;
      const { x, y, right, bottom, width, height } = element.getBoundingClientRect();
      return { x, y, right, bottom, width, height };
    };
    return {
      main: box('.main-content'), content: box('.main-content > .content'),
      scroll: box('.main-content .content-scroll'), footer: box('.app-footer-actions'),
      rail: box('.sidepanel'),
      windowHeight: window.innerHeight, documentHeight: document.documentElement.scrollHeight,
      windowWidth: window.innerWidth, documentWidth: document.documentElement.scrollWidth,
    };
  });
  expect(geometry.content.bottom, 'the main content must fit its pane instead of being clipped by the rail').toBeLessThanOrEqual(geometry.main.bottom + 1);
  expect(geometry.footer.bottom, 'the Apply footer must fit inside the main pane').toBeLessThanOrEqual(geometry.main.bottom + 1);
  expect(geometry.scroll.bottom, 'the scrollable content must end above the Apply footer').toBeLessThanOrEqual(geometry.footer.y + 1);
  expect(geometry.scroll.height, 'main content needs a usable scroll viewport').toBeGreaterThanOrEqual(120);
  expect(geometry.rail.height, 'the rail needs room for its header and a usable body').toBeGreaterThanOrEqual(240);
  if (stacked) {
    expect(geometry.main.bottom, 'stacked panes must not overlap').toBeLessThanOrEqual(geometry.rail.y + 1);
  } else {
    expect(geometry.main.right, 'desktop panes must remain side by side').toBeLessThanOrEqual(geometry.rail.x + 1);
  }
  expect(geometry.documentHeight, 'the shell owns vertical scrolling').toBeLessThanOrEqual(geometry.windowHeight + 1);
  expect(geometry.documentWidth, 'the page must not scroll horizontally').toBeLessThanOrEqual(geometry.windowWidth + 1);
}

for (const viewport of [
  { width: 359, height: 800 },
  { width: 390, height: 844 },
  { width: 359, height: 568 },
  { width: 768, height: 800 },
  { width: 769, height: 800 },
]) {
  test.describe(`mobile shell ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport, deviceScaleFactor: 1 });

    test('Graph, Source, Settings and a native dock stay reachable across navigation and reload', async ({ page, baseURL }, testInfo) => {
      const fixture = mobileSourceFixture('create')!;
      try {
        await activateCorpusInBrowser(page, fixture.corpus);
        await page.goto(new URL(`rag?subtab=graph&corpus=${fixture.corpus}`, baseURL).toString());
        const main = page.locator('.main-content');
        await expect(main.getByTestId(`graph-entity-${fixture.entity}`)).toBeAttached();
        await page.screenshot({ path: testInfo.outputPath('graph-initial.png') });
        await expectPaneBounds(page, viewport.width <= 768);

        const navigationToggle = page.getByRole('button', { name: 'Toggle navigation', exact: true });
        await expectReachable(navigationToggle);
        await navigationToggle.click();
        await expect(page.locator('.sidebar')).toHaveClass(/mobile-open/);
        await expectDrawerBelowHeader(page);
        await expectReachable(page.getByTestId('topbar-corpus'));
        const dashboardLink = page.getByTestId('tab-bar').getByRole('link', { name: 'Dashboard', exact: true });
        await expectReachable(dashboardLink);
        await dashboardLink.focus();
        await dashboardLink.press('Enter');
        await expect(page).toHaveURL(/\/dashboard/);
        await expect(page.locator('.sidebar')).not.toHaveClass(/mobile-open/);
        await expectReachable(navigationToggle);
        await navigationToggle.click();
        const ragLink = page.getByTestId('tab-bar').getByRole('link', { name: 'RAG', exact: true });
        await expectReachable(ragLink);
        await ragLink.click();
        await expect(page).toHaveURL(/\/rag/);
        await expect(page.locator('.sidebar')).not.toHaveClass(/mobile-open/);
        await main.locator('.subtab-bar').getByRole('button', { name: 'Graph', exact: true }).click();
        await expect(main.getByTestId(`graph-entity-${fixture.entity}`)).toBeAttached();

        const nav = main.locator('.subtab-bar');
        if (viewport.width <= 768) {
          const row = await nav.locator('button').evaluateAll((buttons) => {
            const boxes = buttons.map((button) => button.getBoundingClientRect());
            return { top: Math.max(...boxes.map((box) => box.top)), bottom: Math.min(...boxes.map((box) => box.bottom)) };
          });
          // Hover/focus animations can move one button by a pixel. Every
          // button must still share a vertical band; wrapped rows cannot.
          expect(row.top, 'mobile subtabs must keep one scrollable row').toBeLessThan(row.bottom);
        }
        // Keyboard focus must expose the last tab rather than leave it clipped
        // beyond the viewport. Return to Graph with an ordinary click.
        await nav.getByRole('button', { name: 'Synthetic Lab', exact: true }).focus();
        await expectReachable(nav.getByRole('button', { name: 'Synthetic Lab', exact: true }));
        await nav.getByRole('button', { name: 'Synthetic Lab', exact: true }).press('Shift+Tab');
        await expect(nav.getByRole('button', { name: 'Indexing', exact: true })).toBeFocused();
        await expectReachable(nav.getByRole('button', { name: 'Graph', exact: true }));
        await nav.getByRole('button', { name: 'Graph', exact: true }).click();

        const table = main.getByTestId('graph-view-table');
        await expectReachable(table);
        await table.focus();
        await table.press('Enter');
        await expect(main.getByTestId('graph-entities-table')).toBeAttached();
        await expectReachable(main.getByTestId('graph-view-visualization'));
        await main.getByTestId('graph-view-visualization').click();
        const search = main.getByTestId('graph-entity-search');
        await expectReachable(search);
        await search.fill('Fuel tank');
        await expectReachable(main.getByTestId('graph-search-btn'));
        await main.getByTestId('graph-search-btn').click();
        const entity = main.getByTestId(`graph-entity-${fixture.entity}`);
        await expectReachable(entity);
        await entity.click();
        const openSource = main.getByTestId('graph-source-open').first();
        await expectReachable(openSource);
        await openSource.click();
        await expect(page.getByTestId('document-viewer-title')).toHaveText('tank.md');
        const evidence = page.getByTestId('document-highlight-line').first();
        await expectReachable(evidence);
        await expect(evidence).toContainText('Fuel tank inspection record');
        await expectPaneBounds(page, viewport.width <= 768);
        await page.screenshot({ path: testInfo.outputPath('graph-source.png') });

        // Settings is a real rail action; returning to Source preserves the
        // current document while the main route changes to model assignments.
        await expectReachable(page.getByTestId('dock-mode-settings'));
        await page.getByTestId('dock-mode-settings').click();
        await expectReachable(page.getByTestId('sidepanel-open-model-assignments'));
        await page.getByTestId('sidepanel-open-model-assignments').click();
        await expect(page).toHaveURL(/subtab=retrieval/);
        await expectReachable(page.getByTestId('dock-mode-document'));
        await page.getByTestId('dock-mode-document').click();
        await expectReachable(evidence);

        // Dock a native page through the chooser and navigate its own subtab.
        await expectReachable(page.getByTestId('dock-choose'));
        await page.getByTestId('dock-choose').click();
        const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
        await picker.getByRole('combobox').fill('Dashboard Glossary');
        await picker.getByRole('option').filter({ hasText: 'Glossary' }).first().click();
        const dock = page.getByTestId('dock-native');
        await expect(page.getByTestId('dock-title')).toContainText('Dashboard — Glossary');
        const system = dock.locator('.subtab-btn[data-subtab="system"]');
        await expectReachable(system);
        await system.click();
        await expect(page.getByTestId('dock-title')).toContainText('System Status');
        await page.reload({ waitUntil: 'domcontentloaded' });
        await expect(page.getByTestId('dock-title')).toContainText('System Status');
        await expectReachable(system);
        await expectPaneBounds(page, viewport.width <= 768);
        await page.screenshot({ path: testInfo.outputPath('native-dock-reloaded.png') });
        if (viewport.width <= 768) {
          // A wide tablet can already show the dock's tab row without moving
          // the stack. Expose the complete pane before checking its scrolled state.
          await page.locator('.sidepanel').scrollIntoViewIfNeeded();
          expect(await page.locator('.layout-panes').evaluate((element) => element.scrollTop),
            'reading the lower dock must exercise a scrolled pane stack').toBeGreaterThan(0);
        }
        await navigationToggle.click();
        await expectDrawerBelowHeader(page);
        const adminLink = page.getByTestId('tab-bar').getByRole('link', { name: 'Admin', exact: true });
        await expectReachable(adminLink);
        await adminLink.focus();
        await expect(adminLink).toBeFocused();
        await expectReachable(page.getByTestId('topbar-corpus'));
        await navigationToggle.click();
      } finally {
        mobileSourceFixture('delete', fixture);
      }
    });

    test('an expanded Apply conflict footer preserves the main body and reload action', async ({ page, baseURL }, testInfo) => {
      const fixture = mobileSourceFixture('create')!;
      try {
        await activateCorpusInBrowser(page, fixture.corpus);
        await page.goto(new URL(`rag?subtab=retrieval&corpus=${fixture.corpus}`, baseURL).toString());
        const main = page.locator('.main-content');
        const bm25 = main.locator('.input-group').filter({ hasText: 'BM25 k1' }).getByRole('spinbutton');
        await expectReachable(bm25);
        const original = await bm25.inputValue();
        await bm25.fill(Number(original) === 1.3 ? '1.4' : '1.3');
        await bm25.press('Tab');
        const apply = page.getByTestId('apply-changes');
        await expect(apply).toBeEnabled();
        // Tab commits NumberField and may focus the following glossary icon;
        // move focus to Apply so its legitimate tooltip no longer covers it.
        await apply.focus();
        await expectReachable(apply);
        const response = page.waitForResponse((res) =>
          new URL(res.url()).pathname === '/api/config' && res.request().method() === 'PUT',
        );
        await apply.click();
        expect((await response).status(), 'real sparse contract changes over stored chunks must conflict').toBe(409);
        await expect(page.getByTestId('apply-error')).toContainText('sparse contract');
        const reload = page.getByTestId('apply-reload-latest');
        await expect(reload).toBeVisible();
        await page.screenshot({ path: testInfo.outputPath('expanded-apply-conflict.png') });
        await expectPaneBounds(page, viewport.width <= 768);

        // The rejected setting remains editable while the error/footer grows.
        await expectReachable(bm25);
        await expectReachable(reload);
        await reload.click();
        await expect(page.getByTestId('apply-error')).toHaveCount(0);
        await expect(page.getByTestId('apply-reload-latest')).toHaveCount(0);
        await expect(bm25).toHaveValue(original);
        await expect(apply).toBeDisabled();
        const graphTab = main.locator('.subtab-bar').getByRole('button', { name: 'Graph', exact: true });
        await expectReachable(graphTab);
        await graphTab.click();
        await expectReachable(main.getByTestId('graph-view-table'));
        await expectPaneBounds(page, viewport.width <= 768);
        await page.screenshot({ path: testInfo.outputPath('after-conflict-recovery.png') });
      } finally {
        mobileSourceFixture('delete', fixture);
      }
    });
  });
}

for (const width of [900, 901, 1024, 1025, 1200, 1201, 1366]) {
  test.describe(`resize handle at ${width}px`, () => {
    test.use({ viewport: { width, height: 800 }, deviceScaleFactor: 1 });

    test('stays below the natural header and resizes the rail at the visible breakpoint', async ({ page, baseURL }) => {
      await page.goto(new URL('dashboard', baseURL).toString());
      await expect(page.locator('.layout')).toBeVisible();
      const handle = page.locator('.resize-handle');
      // Compact chrome fixes the rail width and disables resizing through
      // 1200px, including every width where the header can wrap.
      if (width <= 1200) {
        await expect(handle).toBeHidden();
        return;
      }
      await expect(handle).toBeVisible();
      await expect(handle).toHaveAttribute('data-sidepanel-resize-bound', '1');
      const header = (await page.locator('.topbar').boundingBox())!;
      const bounds = (await handle.boundingBox())!;
      expect(bounds.y, 'the resize hit area must start below the whole rendered header').toBeGreaterThanOrEqual(header.y + header.height - 1);
      expect(bounds.y + bounds.height, 'the resize hit area must end at the viewport').toBeLessThanOrEqual(801);
      await expectReachable(handle);
      const rail = page.locator('.sidepanel');
      const initial = (await rail.boundingBox())!.width;
      const x = bounds.x + bounds.width / 2;
      const y = header.y + header.height + 80;
      await page.mouse.move(x, y);
      await page.mouse.down();
      await page.mouse.move(x - 24, y, { steps: 5 });
      await page.mouse.up();
      await expect.poll(async () => (await rail.boundingBox())!.width).toBeGreaterThan(initial + 15);
    });
  });
}
