// Source evidence viewer: a citation opens the actual document in the right rail.
//
// Drives the real stack over a temp corpus made of the Aurora markdown fixture plus the
// deterministic two-page PDF and HTML handbook (tests/fixtures/acceptance_corpus_docs), indexed
// for real (Docling). PDF citations render as thumbnail cards with the cited region boxed;
// text citations are clickable file:line rows; both open the viewer at the cited location.
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { seedAnswerFromSearch } from './chat_seed';
import {
  acceptanceCorpusPath,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(15 * 60 * 1000);

let corpus: ExhaustiveCorpus | null = null;
let corpusDir: string | null = null;

// A document whose evidence line is far wider than the dock column. B-08 found the pane
// clipping such a line at the panel edge, readable only through a horizontal scrollbar at
// the bottom of the whole dock - on the one flow (verifying a citation) this product exists
// for. The phrase is distinctive so retrieval lands on this file.
const WRAP_FILE = 'evidence-wrapping.md';
const WRAP_PHRASE = 'thermohaline drift compensation';
const WRAP_LINE = `The ${WRAP_PHRASE} procedure ${'runs the full descent profile against the reference brine ladder and records every deviation, '.repeat(12)}then signs the record.`;

function docsFixturePath(): string {
  return path.resolve(process.cwd(), 'tests', 'fixtures', 'acceptance_corpus_docs');
}

async function gotoChat(page: Page, corpusId: string): Promise<void> {
  await page.goto(`chat?corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

test.beforeAll(async ({ request }) => {
  const dir = mkdtempSync(path.join(os.tmpdir(), 'ragweld-viewer-'));
  corpusDir = dir;
  cpSync(acceptanceCorpusPath(), dir, { recursive: true });
  cpSync(docsFixturePath(), dir, { recursive: true });
  writeFileSync(path.join(dir, WRAP_FILE), `# Evidence wrapping\n\n${WRAP_LINE}\n`, 'utf8');
  corpus = await provisionExhaustiveCorpus(request, { index: true, corpusPath: dir });
});

test.afterAll(async ({ request }) => {
  if (corpus) await corpus.dispose(request);
  if (corpusDir) rmSync(corpusDir, { recursive: true, force: true });
});

test('PDF citation renders a page thumbnail card and opens the page with the cited region boxed', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const matches = await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?', {
    topK: 8,
    label: 'Source viewer spec',
  });
  expect(matches.some((m) => m.file_path === 'aurora-mission-report.pdf' && m.provenance?.page_start === 1)).toBe(true);
  await gotoChat(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const card = page.getByTestId('chat-citation-open-pdf').first();
  await expect(card).toBeVisible({ timeout: 30_000 });
  const thumb = card.getByTestId('chat-citation-thumb');
  await expect(thumb).toBeVisible();
  await expect
    .poll(async () => thumb.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), {
      timeout: 60_000,
    })
    .toBe(true);
  await expect(card).toContainText('aurora-mission-report.pdf');
  await expect(card).toContainText(/p\. 1/);

  await card.click();
  await expect(page.getByTestId('dock-mode-document')).toHaveAttribute('data-testid', 'dock-mode-document');
  const viewer = page.getByTestId('document-viewer');
  await expect(viewer).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('document-viewer-title')).toHaveText('aurora-mission-report.pdf');
  await expect(page.getByTestId('document-page-indicator')).toHaveText('p. 1 / 2', { timeout: 30_000 });
  const image = page.getByTestId('document-page-image');
  await expect
    .poll(async () => image.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 0), {
      timeout: 60_000,
    })
    .toBe(true);
  const frame = page.getByTestId('document-page-frame');
  expect(await frame.getByTestId('document-region').count()).toBeGreaterThan(0);
  await expect(page.getByTestId('document-cited-text')).toContainText(/salinity array/i);
  await expect(page.getByTestId('document-provenance-not-captured')).toHaveCount(0);

  // The boxes drawn per page equal the seeded provenance regions for that page (the salinity
  // chunk may run onto page 2 depending on chunking; the viewer must follow the data either way).
  const seeded = matches.find((m) => m.file_path === 'aurora-mission-report.pdf' && /salinity array/i.test(m.content));
  expect(seeded).toBeTruthy();
  const regionsOn = (n: number) => (seeded!.provenance?.regions ?? []).filter((r) => r.page === n).length;
  await expect(frame.getByTestId('document-region')).toHaveCount(regionsOn(1));
  await page.getByTestId('document-page-next').click();
  await expect(page.getByTestId('document-page-indicator')).toHaveText('p. 2 / 2');
  await expect(frame.getByTestId('document-region')).toHaveCount(regionsOn(2));
  await page.getByTestId('document-page-chip-1').click();
  await expect(page.getByTestId('document-page-indicator')).toHaveText('p. 1 / 2');
});

test('text citation is a clickable line row that opens the file at the cited lines', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'Which sensor cluster does the incident playbook cover?', {
    topK: 8,
    label: 'Source viewer spec',
  });
  await gotoChat(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const rows = page.getByTestId('chat-citation-open');
  await expect(rows.first()).toBeVisible({ timeout: 30_000 });
  const row = rows.filter({ hasText: '.md:' }).first();
  await expect(row).toBeVisible();
  const label = (await row.innerText()).trim();
  const match = /\[(\d+)\]\s+(\S+\.md):(\d+)-(\d+)/.exec(label);
  expect(match, label).not.toBeNull();
  const startLine = Number(match![3]);

  await row.click();
  await expect(page.getByTestId('document-viewer')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('document-viewer-title')).toHaveText(match![2].split('/').pop()!);
  const highlighted = page.getByTestId('document-highlight-line');
  await expect(highlighted.first()).toBeVisible({ timeout: 30_000 });
  await expect(highlighted.first()).toHaveAttribute('data-line', String(startLine));
  await expect(page.getByTestId('document-stale-badge')).toHaveCount(0);
  await expect(page.getByTestId('document-open-original')).toHaveAttribute('href', /documents\/raw\?path=/);
});

test('a wide evidence line wraps inside the pane instead of running off its edge', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const matches = await seedAnswerFromSearch(page, request, corpus.corpusId, WRAP_PHRASE, {
    topK: 8,
    label: 'Source viewer wrapping spec',
  });
  expect(matches.some((m) => m.file_path === WRAP_FILE), `retrieval never reached ${WRAP_FILE}`).toBe(true);

  await gotoChat(page, corpus.corpusId);
  await expect(page.getByTestId('chat-sources').last()).toBeVisible({ timeout: 60_000 });

  const row = page.getByTestId('chat-citation-open').filter({ hasText: WRAP_FILE }).first();
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.click();

  const view = page.getByTestId('document-text-view');
  await expect(view).toBeVisible({ timeout: 30_000 });
  const highlighted = page.getByTestId('document-highlight-line').first();
  await expect(highlighted).toBeVisible({ timeout: 30_000 });

  // The pane itself does not scroll sideways ...
  const overflow = await view.evaluate((el) => ({
    scrollWidth: el.scrollWidth,
    clientWidth: el.clientWidth,
  }));
  expect(
    overflow.scrollWidth,
    `evidence pane scrolls horizontally (${overflow.scrollWidth} > ${overflow.clientWidth})`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);

  // ... because the wide line occupies several rows' worth of height instead of one, and the
  // virtualizer measured it rather than assuming the single-row height.
  const wideRow = view.locator('[data-line]').filter({ hasText: WRAP_PHRASE }).first();
  await expect(wideRow).toBeVisible({ timeout: 30_000 });
  const box = await wideRow.boundingBox();
  expect(box, 'the wide line must be laid out').not.toBeNull();
  expect(box!.height, 'a line this wide must wrap onto several lines').toBeGreaterThan(40);
  expect(box!.width, 'the wrapped line must fit the pane').toBeLessThanOrEqual(overflow.clientWidth + 1);

  // And the whole page still does not scroll sideways (B-08's dock-wide scrollbar).
  const pageOverflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  expect(pageOverflow.scrollWidth).toBeLessThanOrEqual(pageOverflow.clientWidth + 1);
});
