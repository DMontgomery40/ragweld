// Source evidence viewer: a citation opens the actual document in the right rail.
//
// Drives the real stack over a temp corpus made of the Aurora markdown fixture plus the
// deterministic two-page PDF and HTML handbook (tests/fixtures/acceptance_corpus_docs), indexed
// for real (Docling). PDF citations render as thumbnail cards with the cited region boxed;
// text citations are clickable file:line rows; both open the viewer at the cited location.
import { cpSync, mkdtempSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import {
  API_BASE,
  acceptanceCorpusPath,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(15 * 60 * 1000);

let corpus: ExhaustiveCorpus | null = null;
let corpusDir: string | null = null;

function docsFixturePath(): string {
  return path.resolve(process.cwd(), 'tests', 'fixtures', 'acceptance_corpus_docs');
}

async function gotoChat(page: Page, corpusId: string): Promise<void> {
  await page.goto(`chat?corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

type SeededMatch = {
  file_path: string;
  content: string;
  provenance?: { page_start?: number | null; regions?: { page: number }[] } | null;
};

/**
 * Seed a chat thread whose assistant message carries the REAL retrieval results for `query`
 * (POST /api/search against the indexed corpus). The viewer is about retrieval evidence, not
 * generation, so the spec does not depend on a paid gateway model being reachable.
 */
async function seedAnswerFromSearch(
  page: Page,
  request: APIRequestContext,
  corpusId: string,
  query: string,
): Promise<SeededMatch[]> {
  const res = await request.post(`${API_BASE}/search`, {
    data: {
      query,
      corpus_id: corpusId,
      top_k: 8,
      include_vector: true,
      include_sparse: true,
      include_graph: true,
      cache_mode: 'bypass',
    },
  });
  if (!res.ok()) throw new Error(`POST /api/search -> ${res.status()} ${(await res.text()).slice(0, 300)}`);
  const matches = ((await res.json()) as { matches: SeededMatch[] }).matches;
  expect(matches.length).toBeGreaterThan(0);
  await page.addInitScript(
    ({ cid, q, sources }) => {
      const now = Date.now();
      const convId = `viewer-spec-${now}`;
      const session = {
        conversation_id: convId,
        created_at: now,
        updated_at: now,
        title: 'Source viewer spec',
        model_override: '',
        sources: { corpus_ids: [cid] },
        messages: [
          { id: `user-${now}`, role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: q }] },
          {
            id: `assistant-${now}`,
            role: 'assistant',
            createdAt: new Date(now + 1).toISOString(),
            content: [{ type: 'text', text: 'Grounded answer seeded from retrieval (see sources).' }],
            status: { type: 'complete', reason: 'stop' },
            metadata: { unstable_state: null, unstable_annotations: [], unstable_data: [], steps: [], custom: { runId: `spec-${now}`, sources } },
          },
        ],
      };
      localStorage.setItem('ragweld-chat-threads:v2', JSON.stringify({ version: 2, active_conversation_id: convId, sessions: [session] }));
      localStorage.setItem('tribrid_active_corpus', cid);
      localStorage.setItem('tribrid_active_repo', cid);
    },
    { cid: corpusId, q: query, sources: matches },
  );
  return matches;
}

test.beforeAll(async ({ request }) => {
  corpusDir = mkdtempSync(path.join(os.tmpdir(), 'ragweld-viewer-'));
  cpSync(acceptanceCorpusPath(), corpusDir, { recursive: true });
  cpSync(docsFixturePath(), corpusDir, { recursive: true });
  corpus = await provisionExhaustiveCorpus(request, { index: true, corpusPath: corpusDir });
});

test.afterAll(async ({ request }) => {
  if (corpus) await corpus.dispose(request);
  if (corpusDir) rmSync(corpusDir, { recursive: true, force: true });
});

test('PDF citation renders a page thumbnail card and opens the page with the cited region boxed', async ({ page, request }) => {
  if (!corpus) throw new Error('corpus not provisioned');
  const matches = await seedAnswerFromSearch(page, request, corpus.corpusId, 'How often is the salinity array calibrated?');
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
  await seedAnswerFromSearch(page, request, corpus.corpusId, 'Which sensor cluster does the incident playbook cover?');
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
