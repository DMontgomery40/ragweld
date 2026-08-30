// Docked panes must wrap or scroll, never clip content mid-word (T15 / A-44 /
// M-109). The drive found the docked Parameter Glossary clipped every line at
// the pane edge with no wrapping and no horizontal scrollbar, while the docked
// Chat pane scrolled -- an inconsistent overflow treatment. This locks the
// invariant: with the glossary docked (native render mode), no element inside
// the dock may be horizontally larger than its box WITHOUT a scrollable-x
// ancestor -- i.e. everything is reachable by wrapping or by scrolling, nothing
// is silently clipped. Measured at deviceScaleFactor 1. Driven against the real
// app + API, no interception.
import { expect, test } from '@playwright/test';

test.use({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 });

test('the docked glossary wraps or scrolls -- no line is clipped mid-word', async ({ page, baseURL }) => {
  await page.goto(new URL('dashboard?subtab=glossary', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.layout', { timeout: 20000 });
  await page.waitForTimeout(800);

  // Dock the current (glossary) view; DOCK_DEFAULT_MODE_BY_PATH renders
  // /dashboard natively, so this exercises the native docked-pane path.
  const dockCurrent = page.getByTestId('dock-current');
  await expect(dockCurrent).toBeVisible();
  await dockCurrent.click();
  await page.waitForTimeout(800);

  const dockNative = page.getByTestId('dock-native');
  await expect(dockNative, 'the glossary did not dock in native mode').toBeVisible();

  // Scroll into the term-definition rows -- the region the drive saw clipped.
  await page.evaluate(() => {
    const tc = document.querySelector('[data-testid=dock-native] .tab-content') as HTMLElement | null;
    if (tc) tc.scrollTop = 300;
  });
  await page.waitForTimeout(300);

  const clips = await page.evaluate(() => {
    const dockRoot = document.querySelector('[data-testid=dock-panel]') as HTMLElement;
    const scrollableX = (el: HTMLElement): boolean => {
      const o = getComputedStyle(el).overflowX;
      return o === 'auto' || o === 'scroll';
    };
    const offenders: { tag: string; cls: string; cw: number; sw: number; text: string }[] = [];
    dockRoot.querySelectorAll('*').forEach((n) => {
      const el = n as HTMLElement;
      // Content wider than the element's box, i.e. it overflows horizontally.
      if (el.scrollWidth - el.clientWidth <= 4) return;
      // Reachable if any ancestor up to the dock root can scroll horizontally.
      let a: HTMLElement | null = el;
      let reachable = false;
      while (a && a !== dockRoot.parentElement) {
        if (scrollableX(a)) {
          reachable = true;
          break;
        }
        a = a.parentElement;
      }
      if (!reachable) {
        offenders.push({
          tag: el.tagName,
          cls: String(el.className).slice(0, 32),
          cw: el.clientWidth,
          sw: el.scrollWidth,
          text: (el.textContent || '').trim().slice(0, 45),
        });
      }
    });
    return offenders;
  });

  expect(
    clips,
    `docked content clipped horizontally with no scrollable ancestor: ${JSON.stringify(clips)}`,
  ).toEqual([]);
});
