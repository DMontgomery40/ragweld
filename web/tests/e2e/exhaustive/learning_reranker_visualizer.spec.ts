// Learning Reranker Neural Visualizer, against the real rendered app and the real
// run registry. No request interception: assertions observe the live page.
//
// M-54 (drive D-26): with points=0 the 3D scene (cyan point lights, bloom, terrain
// grid) still painted a large saturated cyan mass that read as data, with "Awaiting
// telemetry" in dim grey sitting on top of the bright cyan. The visualizer must not
// mount any renderer until there is a trajectory to draw: the neutral canvas ground
// shows through and a legible empty-state explains the next action.
//
// This also carries the 2026-08-22 offline guard (the visualizer used to suspend the
// R3F tree forever fetching a drei HDR from a CDN): at zero points that tree is not
// mounted at all, so no external 3D asset may be fetched. epstein-files-1 has no
// reranker training runs, so it is the deterministic zero-telemetry case.
import { expect, test } from '@playwright/test';

const STUDIO_PATH = 'rag?subtab=learning-ranker&corpus=epstein-files-1';

test('Neural Visualizer shows a neutral empty state at zero points, not a painted mass', async ({
  page,
  baseURL,
}) => {
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const host = new URL(request.url()).hostname;
    if (host !== '127.0.0.1' && host !== 'localhost') externalRequests.push(request.url());
  });

  // Uncaught exceptions are real regressions (the 2026-08-22 defect crashed the R3F
  // tree). Console resource/CORS/telemetry noise is environmental when the dev app is
  // driven against a cross-origin API (Faro collect, backend auth 403s, a corpus with
  // no eval dataset) and is not what this spec guards, so it is filtered out.
  const pageErrors: string[] = [];
  page.on('pageerror', (err) => pageErrors.push(String(err)));
  const ENV_NOISE = /Failed to load resource|CORS policy|faro|ERR_FAILED|Failed to fetch|\[API Error\]|status code 40\d|status of 40\d/i;
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !ENV_NOISE.test(msg.text())) consoleErrors.push(msg.text());
  });

  await page.goto(new URL(STUDIO_PATH, baseURL).toString());

  // The visualizer panel renders (not blank-forever): the panel and its header exist.
  const panel = page.getByTestId('neural-visualizer');
  await expect(panel).toBeVisible({ timeout: 60_000 });

  // No telemetry for this corpus -> the empty state, and it names the next action.
  const empty = page.getByTestId('neural-awaiting-telemetry');
  await expect(empty).toBeVisible({ timeout: 30_000 });
  await expect(empty).toContainText('No training telemetry yet');
  await expect(empty).toContainText(/start a run/i);

  // The defect was a WebGL canvas painting a cyan mass at zero points. No renderer
  // (webgl2/webgpu/canvas2d) may be mounted while there is nothing to draw.
  await expect(page.locator('.neural-canvas canvas')).toHaveCount(0);
  await expect(page.locator('.neural-canvas')).toHaveCount(0);

  // The empty-state heading is legible against the fixed dark canvas ground: a real
  // (non-transparent) colour and at least the body-text floor size.
  const heading = empty.getByText('No training telemetry yet');
  const headingStyle = await heading.evaluate((el) => {
    const cs = getComputedStyle(el);
    return { size: parseFloat(cs.fontSize), color: cs.color };
  });
  expect(headingStyle.size, 'empty-state heading >= 14px').toBeGreaterThanOrEqual(14);
  expect(headingStyle.color, 'empty-state heading has a real colour').not.toEqual('rgba(0, 0, 0, 0)');

  // The live renderer/quality/color chips stay — they mirror real operator controls,
  // not debug internals, so hiding them would be a regression.
  await expect(panel.locator('.studio-chip', { hasText: 'points=0' })).toBeVisible();

  // Offline: with no renderer mounted, no external 3D asset fetch is even attempted.
  const assetFetches = externalRequests.filter(
    (url) =>
      /\.(hdr|exr|glb|gltf|ktx2|basis)(\?|$)/i.test(url) ||
      /githack|githubusercontent|market-assets|pmndrs/i.test(url),
  );
  expect(assetFetches, 'visualizer pulled external 3D assets').toEqual([]);
  expect(pageErrors, `uncaught page errors: ${pageErrors.join(' | ')}`).toEqual([]);
  expect(consoleErrors, `app console errors: ${consoleErrors.join(' | ')}`).toEqual([]);
});
