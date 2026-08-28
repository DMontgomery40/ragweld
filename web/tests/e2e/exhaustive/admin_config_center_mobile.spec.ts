import { expect, test, type Locator, type Page } from '@playwright/test';

const PHONE_VIEWPORT = { width: 390, height: 844 };
const TARGET_FIELD_PATHS = [
  'tracing.langfuse_public_base_url',
  'training.ragweld_agent_mlflow_console_base_url',
] as const;

type RectSnapshot = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
  viewportWidth: number;
  viewportHeight: number;
};

async function centeredRect(locator: Locator): Promise<RectSnapshot> {
  return locator.evaluate((element) => {
    element.scrollIntoView({ block: 'center', inline: 'nearest' });
    const rect = element.getBoundingClientRect();
    return {
      left: rect.left,
      top: rect.top,
      right: rect.right,
      bottom: rect.bottom,
      width: rect.width,
      height: rect.height,
      viewportWidth: window.innerWidth,
      viewportHeight: window.innerHeight,
    };
  });
}

function expectWithinViewport(label: string, rect: RectSnapshot): void {
  expect(rect.left, `${label} left edge escaped viewport`).toBeGreaterThanOrEqual(-1);
  expect(rect.top, `${label} top edge escaped viewport`).toBeGreaterThanOrEqual(-1);
  expect(rect.right, `${label} right edge escaped viewport`).toBeLessThanOrEqual(rect.viewportWidth + 1);
  expect(rect.bottom, `${label} bottom edge escaped viewport`).toBeLessThanOrEqual(rect.viewportHeight + 1);
  expect(rect.width, `${label} width exceeded viewport`).toBeLessThanOrEqual(rect.viewportWidth + 1);
}

async function expectFieldRowWithinPhoneViewport(page: Page, path: string): Promise<void> {
  const card = page.locator(`#tab-admin-basic [data-config-path="${path}"]`);
  await expect(card, `missing field card for ${path}`).toBeVisible();

  const input = card.locator('input, textarea, select').first();
  const saveButton = card.getByRole('button', { name: 'Save' });
  await expect(input, `missing editor control for ${path}`).toBeVisible();
  await expect(saveButton, `missing save button for ${path}`).toBeVisible();

  expectWithinViewport(`card ${path}`, await centeredRect(card));
  expectWithinViewport(`input ${path}`, await centeredRect(input));
  expectWithinViewport(`save ${path}`, await centeredRect(saveButton));
}

test.use({ viewport: PHONE_VIEWPORT });

test('Config Center field cards stay within a phone viewport without horizontal overflow', async ({ page, baseURL }) => {
  await page.goto(new URL('admin?subtab=basic', baseURL).toString());

  await expect(page.getByRole('heading', { name: 'Configuration Center' })).toBeVisible();

  for (const path of TARGET_FIELD_PATHS) {
    await expectFieldRowWithinPhoneViewport(page, path);
  }

  const overflow = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    bodyWidth: document.body.scrollWidth,
  }));
  expect(overflow.documentWidth, 'document overflows horizontally').toBeLessThanOrEqual(overflow.viewportWidth + 1);
  expect(overflow.bodyWidth, 'body overflows horizontally').toBeLessThanOrEqual(overflow.viewportWidth + 1);
});
