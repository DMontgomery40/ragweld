// RAG > Reranker regressions from the 2026-08-29 GUI drive, driven against the real
// app + API with no request interception:
//   M-06  the page must show ONE authoritative configured-vs-active status; it used to
//         say CLOUD in the mode selector while runtime info said disabled, because
//         /reranker/info read the global config and ignored the corpus scope,
//   M-39  the cloud reranker model picker must not print an LLM context window.
//
// Both need a corpus whose reranker config is CLOUD. To avoid mutating a real corpus,
// the spec provisions a throwaway corpus over the acceptance fixture, patches its
// reranking section to cloud, and disposes it. No indexing, no paid lanes.
import { expect, test } from '@playwright/test';
import {
  activateCorpusInBrowser,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe('RAG > Reranker status honesty (wave 2b)', () => {
  let corpus: ExhaustiveCorpus;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request);
    await patchCorpusConfigSection(request, corpus.corpusId, 'reranking', {
      reranker_mode: 'cloud',
      reranker_cloud_provider: 'litellm',
      reranker_cloud_model: 'openai.gpt-5.6-luna',
    });
  });

  test.afterAll(async ({ request }) => {
    await corpus.dispose(request);
  });

  test('M-06: one authoritative configured-vs-active status, scoped to the corpus', async ({ page }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto('rag?subtab=reranker', { waitUntil: 'domcontentloaded' });

    const status = page.getByTestId('reranker-authoritative-status');
    await expect(status).toBeVisible();
    // Runtime info now reflects THIS corpus's cloud config, not the global 'none' -
    // the contradiction the drive caught is gone.
    await expect(status).toContainText('Configured: Cloud');
    await expect(status).toContainText('Active: yes');
    await expect(page.getByTestId('reranker-active-reason')).toContainText('openai.gpt-5.6-luna');
  });

  test('S8: the Reranker tab answers to the slug its label suggests, and to the old one', async ({ page }) => {
    // The tab was labelled "Reranker" but its id was `reranker-config`, so `?subtab=reranker`
    // (what the label suggests, what a runbook would say) bounced to Data Quality with an
    // error toast (2026-09-02 drive, S8). The label's slug is now the id.
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto('rag?subtab=reranker', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#rag-subtabs [data-subtab="reranker"]')).toHaveClass(/active/);
    await expect(page.locator('#tab-rag-reranker')).toHaveClass(/active/);
    await expect(page.getByTestId('reranker-authoritative-status')).toBeVisible();
    await expect(page).toHaveURL(/[?&]subtab=reranker(?:&|$)/);
    await expect(page.getByText(/No "reranker" tab on RAG/)).toHaveCount(0);

    // The old slug still lands on the same tab, silently corrected in the address bar.
    await page.goto('rag?subtab=reranker-config', { waitUntil: 'domcontentloaded' });
    await expect(page.locator('#tab-rag-reranker')).toHaveClass(/active/);
    await expect(page).toHaveURL(/[?&]subtab=reranker(?:&|$)/);
    await expect(page.getByText(/No "reranker-config" tab on RAG/)).toHaveCount(0);
  });

  test('M-39: the cloud reranker model picker shows no chat-context caption', async ({ page }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto('rag?subtab=reranker', { waitUntil: 'domcontentloaded' });

    // Cloud mode is selected (patched above), so the cloud model picker is visible.
    await expect(page.getByTestId('reranker-cloud-provider')).toBeVisible();
    // A reranker scores query/passage pairs; an LLM context window is not its property.
    await expect(page.getByText(/Context:\s*[\d,]+\s*tokens/i)).toHaveCount(0);
  });
});
