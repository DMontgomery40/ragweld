// Frontend RUM (Faro) against the real rendered app, the real Alloy
// faro.receiver, and the real Loki behind it. No request interception: the
// assertions are that the live collector ACCEPTED the browser's beacons and
// that the events actually LANDED in Loki with the pinned labels.
import { test, expect } from '@playwright/test';

const LOKI_BASE = process.env.RAGWELD_LOKI_BASE_URL ?? 'http://127.0.0.1:53100';

test('workbench boot ships RUM beacons the Faro collector accepts', async ({ page, request }) => {
  const testStartNs = `${Date.now() - 5_000}000000`;
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });

  const collectorResponse = page.waitForResponse(
    (res) => res.url().includes(':52347/collect') && res.request().method() === 'POST',
    { timeout: 60_000 },
  );

  await page.goto('./');

  // The workbench shell must actually render (RUM from a broken app is noise).
  await expect(page.getByTestId('model-picker').first()).toBeVisible({ timeout: 60_000 });

  const beacon = await collectorResponse;
  expect(beacon.status()).toBeLessThan(300);

  // The accepted beacon must reach Loki through Alloy with the pinned labels;
  // a green collector in front of a broken pipeline is not RUM.
  const query = '{service_name="ragweld-web", ragweld_service="web", deployment_runtime="browser"}';
  let landed = false;
  const deadline = Date.now() + 60_000;
  while (!landed && Date.now() < deadline) {
    const res = await request.get(`${LOKI_BASE}/loki/api/v1/query_range`, {
      params: { query, start: testStartNs, limit: '5' },
    });
    if (res.ok()) {
      const body = await res.json();
      landed = (body?.data?.result?.length ?? 0) > 0;
    }
    if (!landed) await page.waitForTimeout(3_000);
  }
  expect(landed, 'Faro events did not land in Loki within 60s').toBe(true);

  // RUM startup must not degrade the console (rule: clean console after each flow).
  expect(consoleErrors).toEqual([]);
});
