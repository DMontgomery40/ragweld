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
import { expect, test } from '@playwright/test';

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
