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
import { dragPanelCorner, panelHeight } from './panel_resize';

test.use({ viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 });

for (const route of [
  { label: 'Dashboard', path: 'dashboard', tabs: [{ id: 'glossary', title: 'Glossary' }, { id: 'system', title: 'System Status' }] },
  { label: 'RAG', path: 'rag', tabs: [{ id: 'retrieval', title: 'Retrieval' }, { id: 'reranker', title: 'Reranker' }] },
  { label: 'Eval Analysis', path: 'eval', iframe: true, tabs: [{ id: 'analysis', title: 'Analysis' }, { id: 'trace', title: 'Trace Viewer' }] },
  { label: 'Infrastructure', path: 'infrastructure', iframe: true, tabs: [{ id: 'services', title: 'Services' }, { id: 'paths', title: 'Paths & Stores' }] },
]) {
  test(`dock chooser and subtab navigation stay in sync for ${route.label}`, async ({ page, baseURL }) => {
    await page.goto(new URL('start', baseURL).toString(), { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('dock-choose')).toBeVisible();
    const mainUrl = page.url();
    const dock = route.iframe ? page.frameLocator('[data-testid="dock-iframe"]') : page.getByTestId('dock-native');

    const content = (root: typeof dock | typeof page, id: string) => route.path === 'eval'
      ? (id === 'analysis' ? root.getByRole('heading', { name: '🔬 Eval Analysis' }) : root.getByText('Latest Trace', { exact: true }))
      : root.locator(`#tab-${route.path}-${id}`);

    for (const tab of [...route.tabs, route.tabs[0]]) {
      await page.getByTestId('dock-choose').click();
      const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
      await picker.getByRole('combobox').fill(`/${route.path} ${tab.title}`);
      await picker.getByRole('option').filter({ hasText: tab.title }).first().click();
      await expect(page.getByTestId('dock-title')).toContainText(`${route.label} — ${tab.title}`);
      await expect(content(dock, tab.id)).toBeVisible();
      expect(page.url(), 'choosing a dock target must leave the main pane in place').toBe(mainUrl);
    }

    // A subtab click is also navigation: title, persisted target and visible content must agree.
    const next = route.tabs[1];
    const frameStartedAt = route.iframe ? await dock.locator('body').evaluate(() => performance.timeOrigin) : null;
    const nextButton = route.path === 'eval'
      ? dock.getByRole('button', { name: /Trace Viewer/ })
      : dock.locator(`.subtab-btn[data-subtab="${next.id}"]`);
    await nextButton.click();
    await expect(page.getByTestId('dock-title')).toContainText(`${route.label} — ${next.title}`);
    await expect(content(dock, next.id)).toBeVisible();
    if (route.iframe) {
      expect(await dock.locator('body').evaluate(() => performance.timeOrigin), 'reporting navigation must not reload the frame').toBe(frameStartedAt);
    }
    expect(page.url()).toBe(mainUrl);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('dock-title')).toContainText(`${route.label} — ${next.title}`);
    await expect(content(dock, next.id)).toBeVisible();
    await page.getByTestId('dock-swap').click();
    await expect(page).toHaveURL(new RegExp(`subtab=${next.id}`));
    expect(new URL(page.url()).searchParams.has('embed')).toBe(false);
    expect(new URL(page.url()).searchParams.has('dock')).toBe(false);
    await expect(page.getByTestId('dock-title')).toContainText('Get Started');
    await expect(content(page, next.id)).toBeVisible();
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(content(page, next.id)).toBeVisible();
    await expect(page.getByTestId('dock-title')).toContainText('Get Started');
  });
}

test('an embedded prompt link keeps its workspace and query context through Swap', async ({ page, baseURL }) => {
  await page.goto(new URL('start', baseURL).toString());
  await page.getByTestId('dock-choose').click();
  const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
  await picker.getByRole('combobox').fill('/eval System Prompts');
  await picker.getByRole('option').click();
  const frame = page.frameLocator('[data-testid="dock-iframe"]');
  await frame.locator('summary').filter({ hasText: 'Direct (no context)' }).click();
  const mainUrl = page.url();
  await frame.getByRole('button', { name: 'Open Chat Settings', exact: true }).click();
  await expect(frame.locator('#chat-prompt-system_prompt_direct')).toBeVisible();
  await expect(page.getByTestId('dock-title')).toContainText('Chat — Settings');
  await expect(frame.locator('.topbar')).toHaveCount(0);
  expect(page.url()).toBe(mainUrl);
  await page.reload();
  await expect(frame.locator('#chat-prompt-system_prompt_direct')).toBeVisible();
  await page.getByTestId('dock-swap').click();
  await expect(page).toHaveURL(/\/chat\?.*prompt=system_prompt_direct/);
  expect(new URL(page.url()).searchParams.get('subtab')).toBe('settings');
  expect(new URL(page.url()).searchParams.has('embed')).toBe(false);
  expect(new URL(page.url()).searchParams.has('dock')).toBe(false);
  await expect(page.locator('#chat-prompt-system_prompt_direct')).toBeVisible();
});

test('Undo restores an iframe workspace after its reported navigation and a chooser replacement', async ({ page, baseURL }) => {
  await page.goto(new URL('start', baseURL).toString());
  await page.getByTestId('dock-choose').click();
  const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
  await picker.getByRole('combobox').fill('/eval Analysis');
  await picker.getByRole('option').click();
  const frame = page.frameLocator('[data-testid="dock-iframe"]');
  await frame.getByRole('button', { name: /Trace Viewer/ }).click();
  await expect(page.getByTestId('dock-title')).toContainText('Eval Analysis — Trace Viewer');
  await page.getByTestId('dock-choose').click();
  await picker.getByRole('combobox').fill('/infrastructure Services');
  await picker.getByRole('option').click();
  await expect(frame.locator('#tab-infrastructure-services')).toBeVisible();
  await page.getByTestId('dock-undo-toast').getByRole('button', { name: 'Undo', exact: true }).click();
  await expect(page.getByTestId('dock-title')).toContainText('Eval Analysis — Trace Viewer');
  await expect(frame.getByText('Latest Trace', { exact: true })).toBeVisible();
  await page.getByTestId('dock-swap').click();
  await expect(page).toHaveURL(/\/eval\?.*subtab=trace/);
  await expect(page.getByText('Latest Trace', { exact: true })).toBeVisible();
});

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

  // Reachable is not enough: an un-keyed panel inside the Dock must not BE the sideways
  // scroller either. The global resizable-panel rule (overflow: auto) used to make every
  // docked .settings-section scroll sideways at dock width; only keyed panels resize there.
  const sideways = await page.evaluate(() =>
    Array.from(document.querySelectorAll('[data-testid=dock-native] .settings-section:not([data-resizable])')).map((n) => {
      const el = n as HTMLElement;
      const style = getComputedStyle(el);
      return { resize: style.resize, overflowX: style.overflowX, extra: el.scrollWidth - el.clientWidth, text: (el.textContent || '').trim().slice(0, 40) };
    }),
  );
  expect(sideways.length, 'the docked glossary rendered no panels').toBeGreaterThan(0);
  for (const panel of sideways) {
    expect(panel.resize, JSON.stringify(panel)).toBe('none');
    expect(['auto', 'scroll'].includes(panel.overflowX) && panel.extra > 4, `a docked panel scrolls sideways: ${JSON.stringify(panel)}`).toBe(false);
  }
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

// The docked chat composer keeps its buttons on one line (2026-09-02 drive, S36).
// The dock body inherits `overflow-wrap: anywhere` so long ids wrap instead of
// clipping; the composer's textarea would not shrink below its intrinsic
// 20-column width, so at dock width the Attach/Send column was squeezed and the
// inherited anywhere-wrapping rendered "Send" as S/e/n/d and "Attach" as Att/ach.
// Real Dock Chat click, real chat surface, measured at deviceScaleFactor 1.
test('the docked chat composer keeps Attach and Send on one line', async ({ page, baseURL }) => {
  await page.goto(new URL('dashboard?subtab=glossary', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.layout', { timeout: 20000 });

  await page.getByTestId('dock-chat').click();
  const dockNative = page.getByTestId('dock-native');
  await expect(dockNative, 'Chat did not dock in native mode').toBeVisible();
  await expect(dockNative.locator('#chat-input'), 'the docked chat composer did not render').toBeVisible({
    timeout: 60_000,
  });
  const dockBox = (await dockNative.boundingBox())!;

  const composer = await dockNative.evaluate((root) => {
    const read = (selector: string) => {
      const el = root.querySelector(selector) as HTMLElement;
      const cs = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      // One rect per line box of the label: a letter-per-line button yields one per character.
      const range = document.createRange();
      range.selectNodeContents(el);
      return {
        text: (el.textContent || '').trim(),
        width: box.width,
        height: box.height,
        right: box.right,
        lines: range.getClientRects().length,
        fontSize: parseFloat(cs.fontSize),
        boxY:
          parseFloat(cs.paddingTop) +
          parseFloat(cs.paddingBottom) +
          parseFloat(cs.borderTopWidth) +
          parseFloat(cs.borderBottomWidth),
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
      };
    };
    return { attach: read('[data-testid=chat-attach-button]'), send: read('#chat-send'), input: read('#chat-input') };
  });

  for (const button of [composer.attach, composer.send]) {
    expect(button.lines, `"${button.text}" renders on ${button.lines} lines in the dock`).toBe(1);
    expect(
      button.height - button.boxY,
      `"${button.text}" is ${button.height}px tall in the dock — its label wraps across lines`,
    ).toBeLessThanOrEqual(button.fontSize * 1.6);
    expect(button.scrollWidth, `"${button.text}" overflows its own box`).toBeLessThanOrEqual(button.clientWidth + 1);
    expect(button.right, `"${button.text}" sticks out of the dock pane`).toBeLessThanOrEqual(dockBox.x + dockBox.width + 2);
  }
  // The text column is the one that gives way, and it must still be a usable input.
  expect(composer.input.width, `the docked textarea is ${composer.input.width}px wide`).toBeGreaterThanOrEqual(120);
  expect(composer.input.right, 'the docked textarea sticks out of the dock pane').toBeLessThanOrEqual(
    dockBox.x + dockBox.width + 2,
  );
});

// GUI-050 in the Dock: the docked chat workbench is a resizable panel like the main one. It
// opens at the same comfortable default (not pinned to the dock pane), the operator drags its
// corner to resize it, and it remembers its height under a dock-scoped key, so resizing the
// docked chat never changes the main pane's (and the other way round).
test('the docked chat workbench resizes on its own and remembers a dock-only height', async ({ page, baseURL }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(new URL('dashboard?subtab=glossary', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.layout', { timeout: 20000 });

  await page.getByTestId('dock-chat').click();
  const dockNative = page.getByTestId('dock-native');
  await expect(dockNative.locator('#chat-input'), 'the docked chat composer did not render').toBeVisible({
    timeout: 60_000,
  });
  await page.waitForTimeout(500);

  const docked = dockNative.locator('[data-resizable="chat-workbench"]');
  const geom = () =>
    docked.evaluate((panel) => {
      const chat = panel.querySelector('[data-react-chat="true"]') as HTMLElement;
      const scrollport = panel.closest('.tab-content') as HTMLElement;
      return {
        innerH: window.innerHeight,
        panelH: Math.round(panel.getBoundingClientRect().height),
        panelClientH: panel.clientHeight,
        workbenchH: Math.round(chat.getBoundingClientRect().height),
        dockPaneH: scrollport.clientHeight,
        resize: getComputedStyle(panel).resize,
      };
    });

  const start = await geom();
  const detail = JSON.stringify(start);
  expect(start.resize, detail).toBe('vertical');
  const expected = Math.min(900, Math.max(520, Math.round(0.68 * start.innerH)));
  expect(Math.abs(start.panelH - expected), `docked default height: ${detail}`).toBeLessThanOrEqual(2);
  expect(Math.abs(start.panelClientH - start.workbenchH), `docked workbench does not fill its panel: ${detail}`).toBeLessThanOrEqual(1);

  const shorter = (await dragPanelCorner(page, docked, -150)).to;
  expect(Math.abs(shorter - (start.panelH - 150)), JSON.stringify({ start, shorter })).toBeLessThanOrEqual(4);
  const after = await geom();
  expect(Math.abs(after.panelClientH - after.workbenchH), JSON.stringify(after)).toBeLessThanOrEqual(1);

  // The main pane's workbench is untouched by the docked one, and the docked one keeps its
  // own height when both are mounted at once.
  await page.goto(new URL('chat', baseURL).toString(), { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.main-content #chat-input', { timeout: 90_000 });
  await expect(page.locator('[data-react-chat="true"]')).toHaveCount(2);
  await page.waitForTimeout(500);
  const main = page.locator('.main-content [data-resizable="chat-workbench"]');
  expect(Math.abs((await panelHeight(main)) - expected), 'the docked resize leaked into the main pane').toBeLessThanOrEqual(2);
  expect(Math.abs((await panelHeight(docked)) - shorter), 'the docked height was not remembered').toBeLessThanOrEqual(2);
});
