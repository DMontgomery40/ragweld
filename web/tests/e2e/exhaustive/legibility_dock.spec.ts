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

// Get Started must stay legible when it is the DOCKED pane, not just the main
// page. Repro on 81fb1807: with Grafana docked, navigating to Get Started and
// then clicking the pinned Grafana sidebar item swaps Get Started into the
// ~360px dock; `.ob-container` kept its desktop `1fr 300px` grid (the 300px
// track's help-panel occupant was deleted in the 2026-08-25 wizard rebuild) and
// its single-column collapse only fired on a viewport media query, so at dock
// width the content column went negative and step 4's heading and warning
// rendered one character per line with horizontal overflow. The swap itself is
// intentional; the invariant here is that StartTab lays out by its container's
// width. Real sidebar/dock clicks, no interception.
test('Get Started swapped into the dock lays out readably at dock width', async ({ page, baseURL }) => {
  await page.goto(new URL('grafana', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.layout', { timeout: 20000 });

  // Dock Grafana (main moves to Chat), then set up the repro state: Dashboard main.
  await page.getByTestId('dock-current').click();
  await expect(page.getByTestId('dock-native')).toBeVisible();
  const tabBar = page.getByTestId('tab-bar');
  await tabBar.getByRole('link', { name: 'Dashboard', exact: true }).click();

  // Navigate the main pane to Get Started; it must render full-width there.
  await tabBar.getByRole('link', { name: 'Get Started', exact: true }).click();
  const mainStep = page.locator('#tab-start [data-testid=onboarding-step-1]');
  await expect(mainStep).toBeVisible();
  const mainContainer = page.locator('#tab-start .ob-container');
  const mainMain = page.locator('#tab-start .ob-main');
  const mainContainerBox = (await mainContainer.boundingBox())!;
  const mainMainBox = (await mainMain.boundingBox())!;
  expect(
    mainMainBox.width,
    `main-pane onboarding content is ${mainMainBox.width}px of a ${mainContainerBox.width}px container — the step column must own the container width`,
  ).toBeGreaterThanOrEqual(mainContainerBox.width * 0.7);
  const mainTitleBox = (await page.locator('#tab-start .ob-title').boundingBox())!;
  expect(mainTitleBox.height, 'main-pane onboarding title should fit on one or two lines').toBeLessThanOrEqual(76);

  // Click the pinned Grafana sidebar item: intentional swap — Get Started docks.
  await tabBar.getByRole('link', { name: 'Grafana', exact: true }).click();
  const dockNative = page.getByTestId('dock-native');
  await expect(dockNative).toBeVisible();
  await expect(page.getByTestId('dock-title')).toContainText('Get Started');
  const dockStep1 = dockNative.getByTestId('onboarding-step-1');
  await expect(dockStep1, 'Get Started did not render in the dock').toBeVisible();

  // Step 4 is where the repro was catastrophic: heading + warning in a strip.
  await dockNative.getByTestId('onboarding-dot-4').click();
  const dockStep4 = dockNative.getByTestId('onboarding-step-4');
  await expect(dockStep4).toBeVisible();
  const heading = dockNative.getByRole('heading', { name: 'Ask your first question' });
  await expect(heading).toBeVisible();
  const warning = dockStep4.locator('.ob-warning-box');
  await expect(warning).toContainText('Build the indexes in the previous step first.');

  const dockBox = (await dockNative.boundingBox())!;
  const dockMainBox = (await dockNative.locator('.ob-main').boundingBox())!;
  const headingBox = (await heading.boundingBox())!;
  const warningBox = (await warning.boundingBox())!;

  // The step content must use the dock's width, not a collapsed vertical strip.
  expect(
    dockMainBox.width,
    `docked step content is ${dockMainBox.width}px wide in a ${dockBox.width}px dock`,
  ).toBeGreaterThanOrEqual(dockBox.width * 0.6);
  expect(
    headingBox.width,
    `docked step-4 heading is ${headingBox.width}px wide — a vertical strip, not a heading`,
  ).toBeGreaterThanOrEqual(dockBox.width * 0.4);
  expect(
    headingBox.height,
    `docked step-4 heading is ${headingBox.height}px tall — wrapping one/few characters per line`,
  ).toBeLessThanOrEqual(120);
  expect(
    warningBox.width,
    `docked step-4 warning is ${warningBox.width}px wide in a ${dockBox.width}px dock`,
  ).toBeGreaterThanOrEqual(dockBox.width * 0.6);
  expect(
    warningBox.height,
    `docked step-4 warning is ${warningBox.height}px tall — wrapping one/few characters per line`,
  ).toBeLessThanOrEqual(140);

  // No horizontal overflow at dock width: the onboarding container fits the
  // dock pane, and nothing inside the dock overflows without a scrollable-x
  // ancestor (same invariant as the glossary test above).
  const dockContainerBox = (await dockNative.locator('.ob-container').boundingBox())!;
  expect(
    dockContainerBox.x + dockContainerBox.width,
    'the onboarding container overflows the dock pane to the right',
  ).toBeLessThanOrEqual(dockBox.x + dockBox.width + 2);

  const clips = await page.evaluate(() => {
    const dockRoot = document.querySelector('[data-testid=dock-panel]') as HTMLElement;
    const scrollableX = (el: HTMLElement): boolean => {
      const o = getComputedStyle(el).overflowX;
      return o === 'auto' || o === 'scroll';
    };
    const offenders: { tag: string; cls: string; cw: number; sw: number; text: string }[] = [];
    dockRoot.querySelectorAll('*').forEach((n) => {
      const el = n as HTMLElement;
      if (el.scrollWidth - el.clientWidth <= 4) return;
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
    `docked Get Started clipped horizontally with no scrollable ancestor: ${JSON.stringify(clips)}`,
  ).toEqual([]);
});
