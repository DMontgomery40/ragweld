// App-shell regressions from the 2026-08-29 GUI drive, driven against the real app
// and API with no request interception:
//   M-19  the right rail must not ship a dead credential-upload mock,
//   M-125 an unknown /web/* path must say so instead of rendering a blank page,
//   M-126 an unknown ?subtab= must be corrected visibly, not silently,
//   M-127 an unknown ?corpus= must be named in a toast and dropped from the URL,
//   M-128 subtab changes must be reachable with browser Back,
//   M-129 one request per resource per load,
//   M-136 the top bar must not open the search modal on focus, and must trap focus,
//   M-161 sidebar links must announce their label, not their description.
//
// These need no indexed corpus: every assertion is about the shell, so the spec
// reads the corpus registry and activates whatever corpus the box already has.
import { expect, test, type Page } from '@playwright/test';
import { API_BASE, activateCorpusInBrowser } from './corpus_fixture';

async function firstCorpusId(request: import('@playwright/test').APIRequestContext): Promise<string> {
  const res = await request.get(`${API_BASE}/corpora`);
  expect(res.ok(), `GET ${API_BASE}/corpora must succeed`).toBeTruthy();
  const corpora = (await res.json()) as Array<{ corpus_id: string; internal?: boolean }>;
  // Prefer a long-lived corpus: other suites create and drop transient ones, so
  // "the first non-internal corpus" would make this spec depend on their timing.
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

test.describe('app shell', () => {
  let corpusId = '';

  test.beforeAll(async ({ request }) => {
    corpusId = await firstCorpusId(request);
  });

  test('M-19: the settings rail ships no credential-upload control', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await page.getByTestId('dock-mode-settings').click();

    const rail = page.getByTestId('dock-panel');
    await expect(rail.getByTestId('sidepanel-open-model-assignments')).toBeVisible();

    // The rail promised to ingest .env/.ini/.md files and to persist them to a repo
    // file on disk; nothing behind it existed. It is deleted, not hidden.
    await expect(rail.getByText('Secrets Ingest', { exact: false })).toHaveCount(0);
    await expect(rail.getByText('Drop any .env', { exact: false })).toHaveCount(0);
    await expect(rail.getByText('Persist to defaults.json', { exact: false })).toHaveCount(0);
    await expect(rail.locator('input[type="checkbox"]')).toHaveCount(0);
    await expect(rail.locator('input[type="file"]')).toHaveCount(0);
  });

  test('M-125: an unknown /web path says so instead of rendering a blank page', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'this-route-does-not-exist');
    const notFound = page.getByTestId('route-not-found');
    await expect(notFound).toBeVisible();
    await expect(notFound).toContainText('this-route-does-not-exist');
    // The sidebar stays reachable and there is a way home.
    await expect(page.getByTestId('tab-bar')).toBeVisible();
    await notFound.getByTestId('route-not-found-home').click();
    await expect(page).toHaveURL(/\/dashboard(\?|$)/);
  });

  test('M-126: an unknown ?subtab= is corrected with a visible notice', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'rag?subtab=reranker');
    // It still lands somewhere usable...
    await expect(page).toHaveURL(/subtab=data-quality/);
    // ...but it must not do so silently: the operator is told which slug was wrong.
    const toast = page.locator('.toast, [data-testid="toast"], [role="status"], [role="alert"]').filter({ hasText: 'reranker' });
    await expect(toast.first()).toBeVisible({ timeout: 10_000 });
  });

  test('M-127: an unknown ?corpus= is named in a notice and dropped from the URL', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system&corpus=does-not-exist');
    const toast = page.locator('.toast, [data-testid="toast"], [role="status"], [role="alert"]').filter({ hasText: 'does-not-exist' });
    await expect(toast.first()).toBeVisible({ timeout: 15_000 });
    await expect(page).not.toHaveURL(/corpus=does-not-exist/);
  });

  test('M-128: browser Back walks the dashboard subtabs', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await expect(page).toHaveURL(/subtab=system/);
    await page.locator('#dashboard-subtabs [data-subtab="monitoring"]').click();
    await expect(page).toHaveURL(/subtab=monitoring/);
    await page.locator('#dashboard-subtabs [data-subtab="storage"]').click();
    await expect(page).toHaveURL(/subtab=storage/);
    await page.goBack();
    await expect(page).toHaveURL(/subtab=monitoring/);
    await page.goBack();
    await expect(page).toHaveURL(/subtab=system/);
  });

  test('M-159: the document title names the route, the subtab and the corpus', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'dashboard?subtab=storage');
    await expect(page).toHaveTitle(new RegExp(`^Dashboard . Storage . ${corpusId} . ragweld$`));
    await page.locator('#dashboard-subtabs [data-subtab="glossary"]').click();
    await expect(page).toHaveTitle(new RegExp(`^Dashboard . Glossary . ${corpusId} . ragweld$`));
    await gotoWeb(page, baseURL, 'this-route-does-not-exist');
    await expect(page).toHaveTitle(/^Page not found/);
  });

  test('M-129: one request per resource on a page load', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    const seen: string[] = [];
    const detail: string[] = [];
    const t0 = Date.now();
    page.on('request', (req) => {
      const u = new URL(req.url());
      if (!u.pathname.startsWith('/api/')) return;
      seen.push(u.pathname);
      detail.push(`+${Date.now() - t0}ms ${u.pathname}${u.search}`);
    });
    await gotoWeb(page, baseURL, 'dashboard?subtab=system');
    await expect(page.getByTestId('tab-bar')).toBeVisible();
    await page.waitForTimeout(6000);
    const count = (p: string) => seen.filter((x) => x === p).length;
    const report =
      JSON.stringify(Object.fromEntries([...new Set(seen)].map((p) => [p, count(p)])), null, 2) +
      '\n' +
      detail.filter((d) => d.includes('/api/config') || d.includes('/api/health')).join('\n');
    // Exactly one request per resource for everything the shell owns. These are 1 even
    // on the dev server, where StrictMode mounts every effect twice: the second caller
    // joins the in-flight promise instead of opening its own request.
    expect(count('/api/config'), `duplicate GET /api/config\n${report}`).toBeLessThanOrEqual(1);
    expect(count('/api/corpora'), `duplicate GET /api/corpora\n${report}`).toBeLessThanOrEqual(1);
    expect(count('/api/config/registry'), `duplicate GET /api/config/registry\n${report}`).toBeLessThanOrEqual(1);
    expect(count('/api/models'), `duplicate GET /api/models\n${report}`).toBeLessThanOrEqual(1);
    // Health is probed twice per load and that is the floor without a cache: the top bar
    // probes at App mount, the System Status card probes when it mounts a few hundred ms
    // later, and by then the first probe has already settled so there is no flight to
    // join. Both go through the one store, so genuinely co-timed callers do collapse.
    // A third probe means a new uncoordinated `/health` client was added.
    expect(count('/api/health'), `too many GET /api/health\n${report}`).toBeLessThanOrEqual(2);
  });

  test('a fixed-position modal inside a scrolled route anchors to the viewport', async ({ page, baseURL }) => {
    // `.tab-content` carried `transform: translateZ(0)` as a GPU hint, which makes it a
    // containing block for `position: fixed` descendants. Every inline fixed modal
    // rendered inside a route then anchored to the scrolled content instead of the
    // viewport and opened off-screen -- the reason the Dashboard corpus tile looked like
    // it "did nothing". Seven modals sat on this one fault, so the assertion is about the
    // mechanism, not about any single modal.
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'rag?subtab=retrieval');
    await expect(page.locator('.tab-content').first()).toBeVisible({ timeout: 30_000 });

    const probe = await page.evaluate(() => {
      const route = document.querySelector('.tab-content') as HTMLElement | null;
      if (!route) return { error: 'no .tab-content' } as const;

      // Scroll whatever actually scrolls, then measure a real fixed element in the route.
      const scroller = (document.querySelector('.content-scroll') as HTMLElement | null) ?? route;
      scroller.scrollTop = 400;
      window.scrollTo(0, 400);

      const fixed = document.createElement('div');
      fixed.style.cssText = 'position:fixed;top:0;left:0;width:8px;height:8px;';
      route.appendChild(fixed);
      const rect = fixed.getBoundingClientRect();
      fixed.remove();

      // The transform was doing two jobs. It was the containing block for `absolute`
      // children too, so removing it outright would have re-anchored every absolutely
      // positioned child in every route to whatever ancestor came next. `.tab-content`
      // now carries `position: relative`, which keeps exactly that half.
      const abs = document.createElement('div');
      abs.style.cssText = 'position:absolute;top:0;left:0;width:8px;height:8px;';
      route.appendChild(abs);
      const absRect = abs.getBoundingClientRect();
      const routeRect = route.getBoundingClientRect();
      abs.remove();

      // Anything between the probe and the document that establishes a containing block
      // for fixed descendants is the defect, whichever property produced it.
      const promoted: string[] = [];
      for (let node: HTMLElement | null = route; node; node = node.parentElement) {
        const cs = getComputedStyle(node);
        if (cs.transform !== 'none' || cs.filter !== 'none' || cs.perspective !== 'none' ||
            cs.contain.includes('paint') || cs.willChange.includes('transform')) {
          promoted.push(`${node.className || node.tagName}: transform=${cs.transform} filter=${cs.filter} willChange=${cs.willChange}`);
        }
      }
      return {
        top: rect.top,
        left: rect.left,
        absOffsetTop: Math.round(absRect.top - routeRect.top),
        absOffsetLeft: Math.round(absRect.left - routeRect.left),
        scrolled: scroller.scrollTop,
        promoted,
      } as const;
    });

    expect('error' in probe ? probe.error : '').toBe('');
    if ('promoted' in probe) {
      expect(
        probe.promoted,
        `an ancestor of .tab-content still establishes a containing block for fixed children:\n${probe.promoted.join('\n')}`
      ).toEqual([]);
      // The probe is `position: fixed; top: 0; left: 0`, so on a correct page it sits at
      // the viewport origin no matter how far the route has been scrolled.
      expect(probe.top, 'a fixed element drifted with the route scroll').toBe(0);
      expect(probe.left, 'a fixed element drifted with the route scroll').toBe(0);
      // ...and an absolutely positioned child is still anchored to the route itself.
      expect(probe.absOffsetTop, 'an absolute child is no longer anchored to .tab-content').toBe(0);
      expect(probe.absOffsetLeft, 'an absolute child is no longer anchored to .tab-content').toBe(0);
    }
  });

  test('the palettes still open and centre with the GPU hint gone', async ({ page, baseURL }) => {
    await activateCorpusInBrowser(page, corpusId);
    await gotoWeb(page, baseURL, 'rag?subtab=retrieval');
    await expect(page.locator('.tab-content').first()).toBeVisible({ timeout: 30_000 });
    await page.evaluate(() => {
      const scroller = document.querySelector('.content-scroll') as HTMLElement | null;
      if (scroller) scroller.scrollTop = 600;
    });

    const viewport = page.viewportSize()!;
    const inViewport = async (locator: import('@playwright/test').Locator, what: string) => {
      const box = await locator.boundingBox();
      expect(box, `${what} has no box`).not.toBeNull();
      expect(box!.y, `${what} opened above the viewport`).toBeGreaterThanOrEqual(0);
      expect(box!.x, `${what} opened left of the viewport`).toBeGreaterThanOrEqual(0);
      expect(box!.y, `${what} opened below the viewport`).toBeLessThan(viewport.height);
      expect(box!.x, `${what} opened right of the viewport`).toBeLessThan(viewport.width);
    };

    await page.locator('#global-search').click();
    const searchModal = page.locator('.global-search-modal');
    await expect(searchModal).toBeVisible();
    await inViewport(searchModal, 'the Ctrl+K palette');
    await page.keyboard.press('Escape');

    await page.getByTestId('dock-choose').click();
    const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
    await expect(picker).toBeVisible();
    await inViewport(picker.getByTestId('dock-picker-listbox'), 'the dock picker');
  });
});

