// The corpus registry: list, switch, create and delete a corpus from the running app.
//
// M-163/X-18/A-34: the only corpus switch+delete control in the product was a modal mounted
// solely behind the Dashboard "Corpus: ..." Quick Actions tile, and clicking that tile only
// drew a focus ring. A corpus made in the wizard could never be switched to or deleted from
// the GUI.
//
// The tile DOES open the modal. `.tab-content` carries `transform: translateZ(0)` (a "GPU
// acceleration hint", micro-interactions.css:836) AND is the route's scroll container, so an
// identity transform makes it the containing block for `position: fixed` descendants: a modal
// rendered inline anchors `inset: 0` to the top of the scrolled content instead of the
// viewport, and `.content`/`.main-content` (`overflow: hidden`) clip what escapes. Quick
// Actions sits below the fold, so by the time the operator has scrolled to the tile the modal
// opens off-screen. Hence the assertion here is not "a dialog exists" but "the dialog is in
// the viewport", which is what the operator actually needs.
import { randomBytes } from 'node:crypto';
import { expect, test } from '@playwright/test';
import { acceptanceCorpusPath, API_BASE } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });

/** The overlay of a modal must cover the viewport, not a scrolled ancestor's content box. */
async function assertOverlayCoversViewport(dialog: import('@playwright/test').Locator) {
  const geom = await dialog.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { top: r.top, left: r.left, width: r.width, height: r.height, vw: window.innerWidth, vh: window.innerHeight };
  });
  expect(Math.round(geom.top), `overlay top (viewport-anchored) got ${JSON.stringify(geom)}`).toBe(0);
  expect(Math.round(geom.left)).toBe(0);
  expect(Math.round(geom.width)).toBe(geom.vw);
  expect(Math.round(geom.height)).toBe(geom.vh);
}

test('the Dashboard corpus tile opens the corpus registry where the operator can see it', async ({ page }) => {
  await page.goto('dashboard?subtab=system', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });

  const tile = page.locator('#dash-change-repo');
  await expect(tile).toBeVisible({ timeout: 60_000 });
  // System Status is ~4x taller than its scroll window, so the operator reads it scrolled.
  // Scroll a modest amount, keeping the tile itself clickable: that is the ordinary state
  // in which the corpus control gets used.
  await page.evaluate(() => {
    const container = document.querySelector('#tab-dashboard') as HTMLElement | null;
    if (container) container.scrollTop = 150;
  });
  const scrolled = await page.evaluate(() => document.querySelector('#tab-dashboard')?.scrollTop ?? 0);
  expect(scrolled, 'the route scroll container must actually be scrolled for this to be a fair test').toBeGreaterThan(0);

  await tile.click();

  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible({ timeout: 10_000 });
  await expect(dialog).toBeInViewport();
  await assertOverlayCoversViewport(dialog);
});

test('a corpus created in the registry can be switched to and deleted from the registry', async ({ page, request }) => {
  const suffix = randomBytes(4).toString('hex');
  const corpusName = `ragweld registry ${suffix}`;
  const corpusId = `ragweld-registry-${suffix}`;
  const corpusPath = acceptanceCorpusPath();

  try {
    await page.goto('dashboard?subtab=system', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.topbar', { timeout: 90_000 });
    await page.locator('#dash-change-repo').click();
    await expect(page.getByTestId('corpus-registry')).toBeVisible({ timeout: 10_000 });

    // Create: the wizard-created corpus X-18 says can never be reached again.
    await page.getByTestId('corpus-create-name').fill(corpusName);
    await page.getByTestId('corpus-create-path').fill(corpusPath);
    await page.getByTestId('corpus-create-submit').click();
    await expect(page.getByTestId('corpus-registry')).toBeHidden({ timeout: 30_000 });

    // It really exists in the registry the API serves, and it is now the active corpus.
    const listed = await request.get(`${API_BASE}/corpora`);
    expect(listed.ok()).toBe(true);
    const corpora = (await listed.json()) as Array<{ corpus_id: string }>;
    expect(corpora.map((c) => c.corpus_id)).toContain(corpusId);
    await expect(page.locator('#dash-change-repo')).toContainText(corpusName, { timeout: 15_000 });

    // Switch away and back: the registry is the switch control the product lacked.
    await page.locator('#dash-change-repo').click();
    await expect(page.getByTestId('corpus-registry')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId(`corpus-select-${corpusId}`)).toHaveAttribute('aria-current', 'true');
    const other = corpora.map((c) => c.corpus_id).find((id) => id !== corpusId);
    expect(other, 'need a second corpus to prove switching').toBeTruthy();
    await page.getByTestId(`corpus-select-${other}`).click();
    await expect(page.getByTestId('corpus-registry')).toBeHidden({ timeout: 15_000 });
    await expect(page.locator('#dash-change-repo')).not.toContainText(corpusName, { timeout: 15_000 });

    // Delete: the confirm names every store the backend clears, and says what it keeps.
    await page.locator('#dash-change-repo').click();
    await expect(page.getByTestId('corpus-registry')).toBeVisible({ timeout: 10_000 });
    await page.getByTestId(`corpus-delete-${corpusId}`).click();
    const confirmMessage = page.getByTestId('confirm-dialog-message');
    await expect(confirmMessage).toBeVisible({ timeout: 10_000 });
    const text = (await confirmMessage.textContent()) ?? '';
    for (const store of ['Postgres', 'Qdrant', 'Neo4j', 'Lineage', 'registry row']) {
      expect(text, `delete confirm must name ${store}`).toContain(store);
    }
    expect(text, 'delete confirm must say the source files survive').toContain('not touched');
    expect(text, 'delete confirm must not hedge about what the backend removes').not.toContain('may also be removed');
    await page.getByTestId('confirm-dialog-accept').click();

    await expect(page.getByTestId(`corpus-row-${corpusId}`)).toHaveCount(0, { timeout: 30_000 });
    const after = await request.get(`${API_BASE}/corpora`);
    const remaining = ((await after.json()) as Array<{ corpus_id: string }>).map((c) => c.corpus_id);
    expect(remaining).not.toContain(corpusId);
  } finally {
    // A failure mid-test must not leak a corpus into the operator's registry.
    await request.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`).catch(() => undefined);
  }
});

test('the runtime-managed Recall corpus is listed but cannot be deleted here', async ({ page, request }) => {
  const cfg = await request.get(`${API_BASE}/config`);
  expect(cfg.ok()).toBe(true);
  const recallId = String(
    ((await cfg.json()) as { chat?: { recall?: { default_corpus_id?: string } } }).chat?.recall
      ?.default_corpus_id || '',
  ).trim();
  expect(recallId, 'chat.recall.default_corpus_id must be configured').toBeTruthy();

  await page.goto('dashboard?subtab=system', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.locator('#dash-change-repo').click();
  await expect(page.getByTestId('corpus-registry')).toBeVisible({ timeout: 10_000 });

  await expect(page.getByTestId(`corpus-row-${recallId}`)).toBeVisible();
  await expect(page.getByTestId(`corpus-internal-${recallId}`)).toBeVisible();
  await expect(page.getByTestId(`corpus-delete-${recallId}`)).toBeDisabled();
});
