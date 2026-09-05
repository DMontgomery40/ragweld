// What the Indexing tab says about the run it just replayed.
//
// The drive found the run header printing "500 replayed events" for a corpus whose log held
// more -- 500 being the cap the UI itself asked for -- and found the figure summary
// ("figures_described=124 figures_failed=10 figures_undescribed=6") buried under ~40
// identical "Converting ...: still running" heartbeat lines, with nowhere in the UI to see
// which documents lost figures.
import { expect, test } from '@playwright/test';
import { API_BASE, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(10 * 60 * 1000);

let corpus: ExhaustiveCorpus;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: true });
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

test('the run header reports the events the run recorded, not the cap it asked for', async ({
  page,
  request,
}) => {
  const latest = await request.get(`${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/runs/latest`);
  expect(latest.ok()).toBe(true);
  const runId = String((await latest.json()).run_id || '');

  // The page envelope is what the header reads: a slice plus the run's real total.
  const page10 = await request.get(
    `${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/runs/${encodeURIComponent(runId)}/events?limit=10`
  );
  expect(page10.ok()).toBe(true);
  const capped = (await page10.json()) as { events: unknown[]; total: number; first_index: number };
  expect(capped.events.length).toBeLessThanOrEqual(10);
  expect(capped.total).toBeGreaterThanOrEqual(capped.events.length);
  expect(capped.first_index).toBe(capped.total - capped.events.length);

  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('index-run-details')).toHaveJSProperty('open', false);
  await page.getByTestId('index-run-details').locator('summary').click();
  const count = page.getByTestId('index-run-event-count');
  await expect(count).toBeVisible();
  const text = await count.innerText();
  // Whatever it says, the number in it is the run's own total (the tab asks for 500, and this
  // corpus records fewer), never a bare repetition of the limit.
  const shown = Number(text.replace(/[^0-9]/g, ''));
  const whole = await request.get(
    `${API_BASE}/index/${encodeURIComponent(corpus.corpusId)}/runs/${encodeURIComponent(runId)}/events?limit=500`
  );
  const wholePage = (await whole.json()) as { total: number };
  expect(shown).toBe(wholePage.total);
  expect(text).not.toContain('500');
});

test('repeated conversion heartbeats collapse to one line per document', async ({ page }) => {
  // Drives the shipped function itself, imported from the module the app runs.
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  const result = await page.evaluate(async () => {
    const mod = await import('/web/src/components/RAG/IndexingSubtab.tsx');
    const stamp = new Date().toISOString();
    const ev = (message: string) => ({ run_id: 'r', ts: stamp, type: 'log', message, meta: {} });
    const events = [
      ev('Converting A11_MissionReport.pdf: still running (60s elapsed)'),
      ev('Converting A11_MissionReport.pdf: still running (120s elapsed)'),
      ev('Converting A11_MissionReport.pdf: still running (2400s elapsed)'),
      ev('Figure summary: figures_described=124 figures_failed=10 figures_undescribed=6'),
      ev('Converting other.pdf: still running (60s elapsed)'),
    ];
    return (mod.collapseHeartbeats as (e: unknown[]) => Array<{ message: string }>)(events).map(
      (e) => e.message
    );
  });

  expect(result).toEqual([
    'Converting A11_MissionReport.pdf: still running (2400s elapsed) [3 progress notices]',
    'Figure summary: figures_described=124 figures_failed=10 figures_undescribed=6',
    'Converting other.pdf: still running (60s elapsed)',
  ]);
});
