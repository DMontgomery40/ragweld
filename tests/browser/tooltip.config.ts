// LXC100 only. Start the isolated checkout's Vite server before this suite.
export default {
  testDir: '.',
  testMatch: 'tooltip-*.spec.ts',
  workers: 1,
  use: {
    baseURL: process.env.PLAYWRIGHT_WEB_BASE_URL || 'http://127.0.0.1:55179',
    headless: true,
  },
  reporter: 'list',
};
