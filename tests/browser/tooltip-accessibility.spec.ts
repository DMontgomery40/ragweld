import { test, expect } from '@playwright/test';
import { writeFile, unlink } from 'node:fs/promises';
import path from 'node:path';

const fixturePath = path.resolve('web/.tooltip-acceptance.html');
test.beforeAll(async () => {
  await writeFile(fixturePath, `<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="root"></div><script type="module">
import React from "react";
import {createRoot} from "react-dom/client";
import {TooltipIcon} from "/src/components/ui/TooltipIcon.tsx";
import "/src/styles/style.css";
createRoot(document.getElementById("root")).render(React.createElement("main",{style:{padding:20}},React.createElement("label",null,React.createElement("input",{type:"checkbox","aria-label":"Fixture setting"}),"Chunking strategy",React.createElement(TooltipIcon,{name:"CHUNKING_STRATEGY"})),React.createElement("button",null,"Outside help")));
</script></body></html>`);
});
test.afterAll(async () => { await unlink(fixturePath); });

// Run against the isolated LXC validation UI. The fixture imports the real
// component and fetches the real glossary; no API responses are intercepted.
test('glossary help supports hover, keyboard links, dismissal and touch', async ({ page }) => {
  await page.goto('/web/.tooltip-acceptance.html');
  const help = page.getByLabel('Help: CHUNKING_STRATEGY', { exact: true });
  await help.hover();
  const bubble = page.getByRole('tooltip');
  await expect(bubble).toContainText('Chunking');
  await bubble.locator('a').first().hover();
  await expect(bubble).toBeVisible();
  await page.getByRole('button', { name: 'Outside help' }).hover();
  await expect(bubble).toHaveCount(0);
  await help.hover();
  await page.keyboard.press('Escape');
  await expect(bubble).toHaveCount(0);

  await help.focus();
  await expect(bubble).toBeVisible();
  await page.screenshot({ path: 'artifacts/tooltip-keyboard-links.png', fullPage: true });
  await page.keyboard.press('Enter');
  await expect(bubble).toBeVisible();
  await page.keyboard.press('Tab');
  await expect(bubble.locator('a').first()).toBeFocused();
  await page.waitForTimeout(200); // Exceeds the intentional pointer-exit grace.
  await expect(bubble).toBeVisible();
  const destination = await bubble.locator('a').first().getAttribute('href');
  const [reference] = await Promise.all([page.waitForEvent('popup'), page.keyboard.press('Enter')]);
  await reference.waitForLoadState('domcontentloaded');
  expect(reference.url()).toBe(destination);
  await reference.close();
  await page.bringToFront();
  await page.keyboard.press('Escape');
  await expect(help).toBeFocused();
  await expect(bubble).toHaveCount(0);

  await page.getByRole('button', { name: 'Outside help' }).click();
  await help.click();
  await expect(bubble).toBeVisible();
  await expect(page.getByLabel('Fixture setting')).not.toBeChecked();
  await page.getByRole('button', { name: 'Outside help' }).click();
  await expect(bubble).toHaveCount(0);
});

test('long glossary references stay within a narrow viewport', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 280 });
  await page.goto('/web/.tooltip-acceptance.html');
  await page.getByLabel('Help: CHUNKING_STRATEGY', { exact: true }).click();
  const bubble = page.getByRole('tooltip');
  await expect(bubble).toBeVisible();
  const box = await bubble.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(7);
  expect(box!.x + box!.width).toBeLessThanOrEqual(313);
  expect(box!.y).toBeGreaterThanOrEqual(7);
  expect(box!.y + box!.height).toBeLessThanOrEqual(273);
  await expect(bubble.locator('a').first()).toHaveAttribute('rel', 'noopener noreferrer');
  expect(await bubble.evaluate(el => el.scrollHeight)).toBeGreaterThan(await bubble.evaluate(el => el.clientHeight));
  await page.screenshot({ path: 'artifacts/tooltip-mobile.png', fullPage: true });
});

test('touch opens on the first tap and closes on the second', async ({ browser }) => {
  const context = await browser.newContext({ hasTouch: true, isMobile: true, viewport: { width: 375, height: 667 } });
  const page = await context.newPage();
  await page.goto(`${test.info().project.use.baseURL}/web/.tooltip-acceptance.html`);
  const help = page.getByLabel('Help: CHUNKING_STRATEGY', { exact: true });
  await help.tap();
  await expect(page.getByRole('tooltip')).toContainText('Chunking');
  await expect(page.getByLabel('Fixture setting')).not.toBeChecked();
  await help.tap();
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await context.close();
});
