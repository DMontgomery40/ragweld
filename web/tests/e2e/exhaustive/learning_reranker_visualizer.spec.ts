// Learning Reranker Neural Visualizer against the real rendered app and the
// real run registry. No request interception: assertions observe the live
// page. Regression for the 2026-08-22 defect where the visualizer rendered
// blank forever (dead frameloop, OrbitControls `connect(null)`) because
// drei's <Environment preset> fetched an HDR from an external CDN and
// suspended the R3F tree; the environment is now procedural and offline.
import { expect, test } from '@playwright/test';

const STUDIO_PATH = 'rag?subtab=learning-ranker&corpus=epstein-files-1';

test('Neural Visualizer paints a live scene with connected controls and no external assets', async ({
  page,
  baseURL,
}) => {
  const externalRequests: string[] = [];
  page.on('request', (request) => {
    const host = new URL(request.url()).hostname;
    if (host !== '127.0.0.1' && host !== 'localhost') externalRequests.push(request.url());
  });

  const consoleErrors: string[] = [];
  const contextLost: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
    if (msg.text().includes('Context Lost')) contextLost.push(msg.text());
  });

  await page.goto(new URL(STUDIO_PATH, baseURL).toString());

  const canvas = page.locator('.neural-canvas canvas');
  await expect(canvas).toBeVisible({ timeout: 60_000 });

  // R3F sizes the canvas from its measured container a beat after mount; a
  // canvas stuck at the default 300x150 (or 0x0) is the defect, so poll for
  // the settled layout instead of sampling one mid-layout frame.
  await page.waitForFunction(
    () => {
      const el = document.querySelector('.neural-canvas canvas');
      return !!el && el.clientWidth > 200 && el.clientHeight > 200;
    },
    undefined,
    { timeout: 30_000 },
  );
  const box = await canvas.boundingBox();
  expect(box, 'visualizer canvas must have layout').not.toBeNull();

  // The R3F frameloop must actually tick; a mounted-but-dead canvas was the bug.
  const rafTicks = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        let count = 0;
        const orig = window.requestAnimationFrame.bind(window);
        window.requestAnimationFrame = (cb) => orig((t) => ((count += 1), cb(t)));
        setTimeout(() => {
          window.requestAnimationFrame = orig;
          resolve(count);
        }, 1_000);
      }),
  );
  expect(rafTicks, 'render loop is not ticking').toBeGreaterThan(10);

  // The scene must paint real content, not just the clear color (#050712,
  // channel sum 30). Probe inside the same frame task as the render so the
  // drawing buffer is still valid.
  const readCenterStrip = () =>
    page.evaluate(
      () =>
        new Promise<{ maxSum: number; strip: number[] }>((resolve) => {
          const el = document.querySelector('.neural-canvas canvas') as HTMLCanvasElement;
          const gl = el.getContext('webgl2')!;
          let tries = 0;
          const probe = () => {
            requestAnimationFrame(() => {
              const px = new Uint8Array(4 * 64);
              gl.readPixels(
                Math.max(0, Math.floor(gl.drawingBufferWidth / 2) - 32),
                Math.floor(gl.drawingBufferHeight / 2),
                64,
                1,
                gl.RGBA,
                gl.UNSIGNED_BYTE,
                px,
              );
              let maxSum = 0;
              for (let i = 0; i < px.length; i += 4) {
                maxSum = Math.max(maxSum, px[i] + px[i + 1] + px[i + 2]);
              }
              tries += 1;
              if (maxSum > 90 || tries > 300) resolve({ maxSum, strip: Array.from(px.slice(0, 64)) });
              else probe();
            });
          };
          probe();
        }),
    );

  const before = await readCenterStrip();
  expect(before.maxSum, 'canvas never painted above the clear color').toBeGreaterThan(90);

  // OrbitControls must be connected to the canvas: a real drag has to change
  // the rendered view (the original defect logged `connect(null)` and left a
  // dead camera).
  const cx = box!.x + box!.width / 2;
  const cy = box!.y + box!.height / 2;
  await page.mouse.move(cx, cy);
  await page.mouse.down();
  await page.mouse.move(cx + 160, cy + 60, { steps: 8 });
  await page.mouse.up();

  const after = await readCenterStrip();
  expect(
    after.strip.join(','),
    'dragging on the canvas did not change the rendered view (controls disconnected)',
  ).not.toEqual(before.strip.join(','));

  // The visualizer must be fully offline. The regression fetched an HDR
  // environment preset from a drei asset CDN; guard against any 3D-asset
  // fetch leaving the machine. (The app shell's font loads are a separate,
  // pre-existing surface and are not blessed here.)
  const assetFetches = externalRequests.filter(
    (url) =>
      /\.(hdr|exr|glb|gltf|ktx2|basis)(\?|$)/i.test(url) ||
      /githack|githubusercontent|market-assets|pmndrs/i.test(url),
  );
  expect(assetFetches, 'visualizer pulled external 3D assets').toEqual([]);

  expect(contextLost, 'WebGL context was lost during the drive').toEqual([]);
  expect(consoleErrors).toEqual([]);
});
