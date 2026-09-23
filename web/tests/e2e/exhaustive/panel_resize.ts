// Driving the global resizable-panel rule (`.settings-section, [data-resizable]` in
// web/src/styles/main.css) the way an operator does: a real pointer drag on the browser's own
// corner resizer. No style is written from the test; the height changes only if Chromium's
// resizer takes the drag.
import { expect, type Locator, type Page } from '@playwright/test';

/** Chromium's resizer is a ~15px square in the bottom-right corner; grab it near its middle. */
const RESIZER_INSET_PX = 6;

export async function panelHeight(panel: Locator): Promise<number> {
  return panel.evaluate((el) => Math.round(el.getBoundingClientRect().height));
}

/**
 * Brings the panel's bottom-right corner on screen when it is not. The corner is on screen
 * when the pointer there lands on the panel, not on the footer, a sticky bar or the far side
 * of its scroll container; a corner already on screen is left where it is.
 */
export async function revealPanelCorner(panel: Locator): Promise<void> {
  const cornerReachable = () =>
    panel.evaluate((el, inset) => {
      const r = el.getBoundingClientRect();
      const hit = document.elementFromPoint(r.right - inset, r.bottom - inset);
      return Boolean(hit && (hit === el || el.contains(hit)));
    }, RESIZER_INSET_PX);
  if (!(await cornerReachable())) {
    await panel.evaluate((el) => el.scrollIntoView({ block: 'end', inline: 'nearest' }));
  }
  expect(await cornerReachable(), "the panel's resizer corner is not on screen").toBe(true);
}

/**
 * Drags the panel's bottom-right corner by `dy` CSS px and returns its height just before the
 * drag (`from`) and after it (`to`). A corner already on screen is left where it is; otherwise
 * the panel's bottom edge is scrolled into view first (after which only a shrink, a negative
 * `dy`, stays on screen).
 */
export async function dragPanelCorner(page: Page, panel: Locator, dy: number): Promise<{ from: number; to: number }> {
  await revealPanelCorner(panel);
  const box = (await panel.boundingBox())!;
  const x = box.x + box.width - RESIZER_INSET_PX;
  const y = box.y + box.height - RESIZER_INSET_PX;
  const viewportH = page.viewportSize()?.height ?? Number.POSITIVE_INFINITY;
  expect(y + dy, `the drag would leave the viewport (y=${y}, dy=${dy})`).toBeLessThan(viewportH);
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x, y + dy / 2, { steps: 5 });
  await page.mouse.move(x, y + dy, { steps: 5 });
  await page.mouse.up();
  return { from: Math.round(box.height), to: await panelHeight(panel) };
}

export type PanelOverflow = {
  panel: string;
  clientW: number;
  scrollW: number;
  clientH: number;
  scrollH: number;
  /** How far the panel's right edge runs past its parent's content box (px). */
  spillX: number;
};

/**
 * Every visible resizable panel whose content no longer fits it at its current size, or that
 * no longer fits its parent. At a panel's default size this must be empty: `overflow: auto`
 * from the global rule must never turn content that used to show into content hidden behind
 * an inner scrollbar, and `flex-shrink: 0` must never push a panel out of a flex row.
 */
export async function overflowingPanels(page: Page, scope = 'body'): Promise<PanelOverflow[]> {
  return page.evaluate((scopeSelector) => {
    const root = document.querySelector(scopeSelector);
    if (!root) return [];
    const out: PanelOverflow[] = [];
    for (const el of Array.from(root.querySelectorAll<HTMLElement>('.settings-section, [data-resizable]'))) {
      if (!el.offsetParent || el.clientHeight === 0) continue;
      const parent = el.parentElement as HTMLElement;
      const parentStyle = getComputedStyle(parent);
      const parentContentRight =
        parent.getBoundingClientRect().right - parseFloat(parentStyle.borderRightWidth) - parseFloat(parentStyle.paddingRight);
      const spillX = Math.round(el.getBoundingClientRect().right - parentContentRight);
      if (el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1 || spillX > 1) {
        const heading = el.querySelector('h1, h2, h3, h4, summary')?.textContent?.trim().slice(0, 60) || '';
        out.push({
          panel: `${el.dataset.resizable || el.id || el.className} ${heading}`.trim(),
          clientW: el.clientWidth,
          scrollW: el.scrollWidth,
          clientH: el.clientHeight,
          scrollH: el.scrollHeight,
          spillX,
        });
      }
    }
    return out;
  }, scope);
}

/**
 * Contrast of the resize grip against the panel right beside it, read from real pixels at the
 * panel's bottom-right corner (dpr 1). The grip is Chromium's 15px resizer painted by
 * `::-webkit-resizer` as two diagonal bars (main.css): bars at 30-42% and 52-64% along the
 * 135deg diagonal, the gap between them at 42-52%. Only pixels well inside the rounded corner
 * are read, so the panel border can never pass for the grip.
 */
export async function resizerGripContrast(page: Page, panel: Locator): Promise<number> {
  const SIZE = 15;
  await revealPanelCorner(panel);
  const corner = await panel.evaluate((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return { right: r.right - parseFloat(cs.borderRightWidth), bottom: r.bottom - parseFloat(cs.borderBottomWidth) };
  });
  const png = await page.screenshot({
    clip: { x: Math.round(corner.right) - SIZE, y: Math.round(corner.bottom) - SIZE, width: SIZE, height: SIZE },
  });
  return page.evaluate(
    async ({ b64, size }) => {
      const img = new Image();
      img.src = `data:image/png;base64,${b64}`;
      await img.decode();
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d')!;
      ctx.drawImage(img, 0, 0);
      const px = (x: number, y: number) => Array.from(ctx.getImageData(x, y, 1, 1).data.slice(0, 3));
      const lin = (c: number) => {
        const s = c / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
      };
      const lum = ([r, g, b]: number[]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
      const contrast = (a: number[], b: number[]) => {
        const [hi, lo] = [lum(a), lum(b)].sort((m, n) => n - m);
        return (hi + 0.05) / (lo + 0.05);
      };
      const gap = px(6, 7); // pixel centre on x + y = 14: between the bars
      let best = 1;
      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          const s = x + y + 1; // pixel centre on the 135deg diagonal
          const onBar = (s >= 10 && s <= 11.8) || (s >= 16.4 && s <= 18.4);
          if (!onBar || Math.hypot(x - 3, y - 3) > 9) continue;
          best = Math.max(best, contrast(px(x, y), gap));
        }
      }
      return Math.round(best * 100) / 100;
    },
    { b64: png.toString('base64'), size: SIZE },
  );
}
