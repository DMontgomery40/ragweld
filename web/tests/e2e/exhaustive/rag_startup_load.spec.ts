import { expect, test } from '@playwright/test';

test('RAG default subtab does not trigger reranker startup requests', async ({ page, baseURL }) => {
  const observedApiPaths = new Set<string>();

  page.on('request', (request) => {
    const url = request.url();
    if (!url.includes('/api/')) return;
    try {
      const pathname = new URL(url).pathname;
      observedApiPaths.add(pathname);
    } catch {
      // Ignore malformed URLs in diagnostics.
    }
  });

  await page.goto(new URL('rag', baseURL).toString());
  await page.waitForURL(/\/rag(?:\?|$)/);
  await page.waitForTimeout(1500);

  const rerankerRequests = [...observedApiPaths].filter((path) => path.startsWith('/api/reranker/'));
  expect(rerankerRequests).toEqual([]);
});
