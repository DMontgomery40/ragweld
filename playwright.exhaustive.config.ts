// Exhaustive UI suite config.
// Intentionally avoids importing "@playwright/test" so it can run from `web/node_modules`.
const webBaseURL = process.env.PLAYWRIGHT_WEB_BASE_URL ?? 'http://127.0.0.1:55173/web';

function ensureTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`;
}

export default {
  testDir: './web/tests/e2e/exhaustive',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { outputFolder: 'output/playwright/exhaustive/html-report', open: 'never' }],
  ],
  timeout: Number(process.env.EXHAUSTIVE_TEST_TIMEOUT_MS ?? 10 * 60 * 1000),
  expect: {
    timeout: Number(process.env.EXHAUSTIVE_EXPECT_TIMEOUT_MS ?? 30_000),
  },
  use: {
    baseURL: ensureTrailingSlash(webBaseURL),
    actionTimeout: Number(process.env.EXHAUSTIVE_ACTION_TIMEOUT_MS ?? 30_000),
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'web-exhaustive',
      testMatch: '**/*.spec.ts',
      use: {
        baseURL: ensureTrailingSlash(webBaseURL),
      },
    },
  ],
};
