import { expect, test } from '@playwright/test';

test('Dashboard default subtab does not trigger storage startup requests', async ({ page, baseURL }) => {
  const observedApiPaths = new Set<string>();

  page.on('request', (request) => {
    const url = request.url();
    if (!url.includes('/api/')) return;
    try {
      observedApiPaths.add(new URL(url).pathname);
    } catch {
      // Ignore malformed URLs in diagnostics.
    }
  });

  await page.goto(new URL('dashboard', baseURL).toString());
  await page.waitForURL(/\/dashboard(?:\?|$)/);
  await page.waitForTimeout(1500);

  const storageRequests = [...observedApiPaths].filter((path) => path.includes('/api/index/stats'));
  expect(storageRequests).toEqual([]);
});
