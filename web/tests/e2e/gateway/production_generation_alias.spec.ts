import { expect, test } from '@playwright/test';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { ChatModelsResponse, TriBridConfig } from '../../../src/types/generated';

const API_BASE = process.env.GATEWAY_API_BASE_URL?.trim() ?? '';
const LUNA = 'openai.gpt-6-luna';
const SOL = 'openai.gpt-6-sol';

test('production generation aliases survive Apply and reload on a disposable corpus', async ({ page }) => {
  if (!API_BASE) {
    throw new Error('Set GATEWAY_API_BASE_URL to the isolated settings-test API.');
  }
  const corpusId = `pytest_generation_picker_${Date.now().toString(36)}`;
  const corpusDir = mkdtempSync(join(tmpdir(), 'ragweld-generation-picker-'));
  const scope = `?corpus_id=${encodeURIComponent(corpusId)}`;
  let created = false;
  try {
    const response = await page.request.post(`${API_BASE}/corpora`, {
      data: { corpus_id: corpusId, name: 'Generation settings acceptance', path: corpusDir },
    });
    expect(response.ok(), await response.text()).toBeTruthy();
    created = true;
    const baseline = await page.request.get(`${API_BASE}/config${scope}`);
    expect(baseline.ok(), await baseline.text()).toBeTruthy();
    const initial = await baseline.json() as TriBridConfig;
    expect(initial.ui.runtime_mode).toBe('production');
    expect(initial.generation.gen_model).toBe(LUNA);
    const catalogResponse = await page.request.get(`${API_BASE}/chat/models${scope}`);
    expect(catalogResponse.ok(), await catalogResponse.text()).toBeTruthy();
    const catalog = await catalogResponse.json() as ChatModelsResponse;
    for (const alias of [LUNA, SOL]) {
      expect(catalog.models?.some((model) => model.id === alias && model.source === 'litellm')).toBeTruthy();
    }
    // Begin from a distinct supported choice so selecting Luna must stage a real edit.
    const seed = await page.request.patch(`${API_BASE}/config/generation${scope}`, {
      data: { gen_model: SOL, gen_model_http: '' },
    });
    expect(seed.ok(), await seed.text()).toBeTruthy();
    expect((await seed.json() as TriBridConfig).generation.gen_model).toBe(SOL);

    await page.goto(`rag?subtab=retrieval&corpus=${encodeURIComponent(corpusId)}`, { waitUntil: 'domcontentloaded' });
    await page.getByTestId('retrieval-card-generation').click();
    const primary = page.getByTestId('retrieval-generation-answer-alias').locator('select');
    const http = page.locator('.input-group').filter({ has: page.getByText('HTTP Alias Override', { exact: true }) }).locator('select');
    await expect(primary).toBeEnabled();
    await expect(primary.locator('option[value=""]:not([disabled])')).toHaveCount(0);
    await expect(primary).toHaveValue(SOL);
    await expect(http).toBeEnabled();
    for (const alias of [LUNA, SOL]) {
      await primary.selectOption(alias);
      await http.selectOption(LUNA);
      await expect(page.getByTestId('apply-changes')).toBeEnabled();
      const appliedResponse = page.waitForResponse((res) => {
        const url = new URL(res.url());
        return res.request().method() === 'PUT' && url.pathname === '/api/config'
          && url.searchParams.get('corpus_id') === corpusId;
      });
      await page.getByTestId('apply-changes').click();
      const applied = await appliedResponse;
      expect(applied.ok(), await applied.text()).toBeTruthy();
      const sent = applied.request().postDataJSON() as TriBridConfig;
      expect(sent.generation.gen_model).toBe(alias);
      expect(sent.generation.gen_model_http).toBe(LUNA);
      const saved = await applied.json() as TriBridConfig;
      expect(saved.generation).toEqual(sent.generation);
      await expect(primary).toHaveValue(alias);
      await expect(http).toHaveValue(LUNA);
      await expect(page.getByTestId('apply-changes')).toBeDisabled();
      const readback = await page.request.get(`${API_BASE}/config${scope}`);
      expect(readback.ok(), await readback.text()).toBeTruthy();
      expect((await readback.json() as TriBridConfig).generation).toEqual(saved.generation);
      await page.reload({ waitUntil: 'domcontentloaded' });
      await page.getByTestId('retrieval-card-generation').click();
      await expect(primary).toHaveValue(alias);
      await expect(http).toHaveValue(LUNA);
      await expect(page.getByTestId('apply-changes')).toBeDisabled();
      if (alias === LUNA) {
        await primary.scrollIntoViewIfNeeded();
        await page.screenshot({ path: test.info().outputPath('luna-reloaded.png'), fullPage: false });
      }
    }
  } finally {
    try {
      if (created) {
        const removed = await page.request.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`);
        expect.soft(removed.ok(), await removed.text()).toBeTruthy();
      }
    } finally {
      rmSync(corpusDir, { recursive: true, force: true });
    }
  }
});
