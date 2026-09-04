import { expect, test } from '@playwright/test';
import {
  API_BASE,
  activateCorpusInBrowser,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe('Model execution policy', () => {
  let corpus: ExhaustiveCorpus;

  test.beforeAll(async ({ request }) => {
    corpus = await provisionExhaustiveCorpus(request);
    await patchCorpusConfigSection(request, corpus.corpusId, 'reranking', {
      reranker_mode: 'cloud', reranker_cloud_provider: 'litellm', reranker_cloud_model: '',
    });
  });

  test.afterAll(async ({ request }) => {
    await corpus.dispose(request);
  });

  test('cloud reranking stays unselected until the operator chooses an allowed model', async ({ page, request }) => {
    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto('rag?subtab=reranker', { waitUntil: 'domcontentloaded' });
    const section = page.locator('#tab-rag-reranker');
    const picker = section.locator('select').filter({ has: page.locator('option[value="openai.gpt-5.6-luna"]') });
    await expect(picker).toBeVisible();
    await expect(picker).toHaveValue('');
    await expect(picker.locator('option:checked')).toHaveText('Select a model');
    expect(await picker.locator('option').allTextContents()).not.toEqual(expect.arrayContaining([expect.stringMatching(/gpt-4(?:o|\.)?/i)]));
    const configUrl = `${API_BASE}/config?corpus_id=${encodeURIComponent(corpus.corpusId)}`;
    expect((await (await request.get(configUrl)).json()).reranking.reranker_cloud_model).toBe('');
    await picker.selectOption('openai.gpt-5.6-luna');
    const apply = page.getByRole('button', { name: /^Apply \d+ changes?$/i });
    await expect(apply).toBeVisible();
    await apply.click();
    await expect.poll(async () => (await (await request.get(configUrl)).json()).reranking.reranker_cloud_model).toBe('openai.gpt-5.6-luna');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(picker).toHaveValue('openai.gpt-5.6-luna');
    await page.screenshot({ path: '/tmp/astra-model-policy-picker.png', fullPage: true });

    await page.getByTestId('reranker-cloud-provider').selectOption('cohere');
    const coherePicker = section.locator('select').nth(1);
    await expect(coherePicker).toHaveValue('');
    await expect(coherePicker.locator('option:checked')).toHaveText('Select a model');
    await page.getByRole('button', { name: /^Apply \d+ changes?$/i }).click();
    await expect.poll(async () => (await (await request.get(configUrl)).json()).reranking.reranker_cloud_model).toBe('');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(coherePicker).toHaveValue('');
  });

  test('config API rejects GPT-4 family choices with a clear error', async ({ request }) => {
    for (const alias of ['openai.gpt-4', 'openai.gpt-4o-mini', 'openai.gpt-4.1-nano']) {
      const response = await request.patch(`${API_BASE}/config/reranking?corpus_id=${encodeURIComponent(corpus.corpusId)}`, {
        data: { reranker_cloud_model: alias },
      });
      expect(response.status()).toBe(422);
      expect(await response.text()).toContain('GPT-4-class models are blocked');
    }
  });
});
