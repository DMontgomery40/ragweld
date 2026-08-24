// Observability fabric E2E config (real app, real Alloy Faro collector, no
// request interception). Run from web/node_modules:
//   NODE_PATH=web/node_modules npm --prefix web exec -- playwright test --config ../playwright.observability.config.ts
const webBaseURL = process.env.PLAYWRIGHT_WEB_BASE_URL ?? 'http://127.0.0.1:55173/web';

function ensureTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`;
}

export default {
  testDir: './web/tests/e2e/observability',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'output/playwright/observability/html-report', open: 'never' }]],
  timeout: 3 * 60 * 1000,
  expect: { timeout: 30_000 },
  use: {
    baseURL: ensureTrailingSlash(webBaseURL),
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'web-observability', testMatch: '**/*.spec.ts' }],
};
