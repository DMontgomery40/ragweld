// A Chat page nobody is looking at must be quiet.
//
// M-130 (B-35): a Chat tab left alone was logged making hundreds of requests - health
// probes, each one shipping a Faro event with it. Measured on this branch's base, an idle
// Chat tab made 3 requests per 30 s (`/api/health` x1, `/faro/collect` x2) and a HIDDEN one
// made exactly the same: visibility changed nothing.
//
// The health probe is the app's own poller and is the half this lane fixes. `/faro/collect`
// is the Faro SDK shipping on its own cadence; it is counted and printed here but not
// asserted on, because `web/src/observability/faro.ts` belongs to the observability lane and
// pausing telemetry is their call, not a passing test's.
//
// The hidden-tab half of the fix is NOT asserted here on purpose. In this headless
// Chromium `document.visibilityState` stays "visible" whatever you do to the page -
// `bringToFront()` on another tab and CDP `Page.setWebLifecycleState: frozen` both leave it
// visible (measured) - so a passing hidden-tab test here could only be bought by stubbing
// `document.visibilityState`, i.e. by faking the very input the code branches on. The
// wiring is covered instead by the source invariant in
// `tests/unit/test_chat_health_polling.py`.
import { expect, test, type Page, type Request } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

/** Long enough to catch the 30 s health interval at least once. */
const IDLE_MS = 35_000;

type Counts = Record<string, number>;

function summarize(urls: string[]): Counts {
  const counts: Counts = {};
  for (const raw of urls) {
    const path = new URL(raw).pathname;
    counts[path] = (counts[path] ?? 0) + 1;
  }
  return counts;
}

async function openChat(page: Page): Promise<void> {
  await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
  // Let the page's startup fetches finish before any measurement window opens.
  await page.waitForTimeout(3_000);
}

/** Collect API and Faro requests over `ms`, returning them split by origin. */
async function record(page: Page, ms: number): Promise<{ api: string[]; faro: string[] }> {
  const api: string[] = [];
  const faro: string[] = [];
  const onRequest = (req: Request) => {
    const url = req.url();
    if (url.includes('/faro/')) faro.push(url);
    else if (url.includes('/api/')) api.push(url);
  };
  page.on('request', onRequest);
  await page.waitForTimeout(ms);
  page.off('request', onRequest);
  return { api, faro };
}

test('a visible idle Chat page polls health at its configured interval and nothing else', async ({
  page,
}) => {
  await openChat(page);
  const { api, faro } = await record(page, IDLE_MS);
  console.log(`VISIBLE ${IDLE_MS / 1000}s -> api ${JSON.stringify(summarize(api))} faro ${faro.length}`);

  const counts = summarize(api);
  const health = counts['/api/health'] ?? 0;
  // One probe per 30 s interval, and nothing else: an idle page asks no other questions.
  expect(health, `/api/health ${health}x in ${IDLE_MS / 1000}s`).toBeLessThanOrEqual(2);
  expect(api.length, `idle Chat made ${api.length} API requests: ${JSON.stringify(counts)}`).toBe(health);
});
