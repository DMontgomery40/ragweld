// NOTE:
// This config must be runnable even when the repo root does not have its own Node deps.
// Avoid importing `@playwright/test` here; the Playwright CLI provides the runtime.
const mkdocsBaseURL = process.env.PLAYWRIGHT_MKDOCS_BASE_URL ?? 'http://127.0.0.1:8001';
// Use IPv4 loopback by default; on some machines Vite only binds 127.0.0.1 (not ::1),
// and Node/Playwright will prefer ::1 when resolving "localhost".
const webBaseURL = process.env.PLAYWRIGHT_WEB_BASE_URL ?? 'http://127.0.0.1:5173/web';

function ensureTrailingSlash(url: string): string {
  return url.endsWith('/') ? url : `${url}/`;
}

export default {
  testDir: './.tests',
  webServer: [
    {
      command: 'python -m http.server 8001 --bind 127.0.0.1 --directory site',
      url: ensureTrailingSlash(mkdocsBaseURL),
      reuseExistingServer: true,
      timeout: 120000,
    },
  ],
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: 'list',
  timeout: 30000,
  use: {
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'mkdocs',
      testMatch: '**/mkdocs/**/*.spec.ts',
      use: {
        baseURL: ensureTrailingSlash(mkdocsBaseURL),
      },
    },
    {
      name: 'web',
      testMatch: '**/web/**/*.spec.ts',
      use: {
        baseURL: ensureTrailingSlash(webBaseURL),
      },
    },
  ],
};
