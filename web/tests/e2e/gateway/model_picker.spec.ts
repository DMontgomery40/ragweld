/**
 * Generation gateway catalog: the Chat model picker must reflect the live
 * LiteLLM alias set joined with data/models.json, and a catalog-backed paid
 * alias must produce a grounded answer on a real corpus with a real question.
 *
 * Real app, real API, real LiteLLM, real OpenRouter spend (one small request).
 * No request interception, no placeholder queries.
 */
import { expect, test, type Page } from '@playwright/test';
import type { ChatModelInfo, ChatModelsResponse } from '../../../src/types/generated';

const API_BASE = process.env.GATEWAY_API_BASE_URL ?? 'http://127.0.0.1:58012/api';
const CORPUS_ID = process.env.GATEWAY_E2E_CORPUS_ID ?? 'epstein-files-1';
const PAID_ALIAS = process.env.GATEWAY_E2E_PAID_ALIAS ?? 'openai.gpt-5.4-mini';
const REAL_QUESTION =
  process.env.GATEWAY_E2E_QUESTION ??
  'Which flights or plane management did Jeffrey Epstein discuss with Barry Cohen in October 2017?';

async function fetchChatModels(page: Page): Promise<ChatModelInfo[]> {
  const response = await page.request.get(`${API_BASE}/chat/models?corpus_id=${encodeURIComponent(CORPUS_ID)}`);
  expect(response.ok(), `GET /api/chat/models -> ${response.status()}`).toBeTruthy();
  const payload = (await response.json()) as ChatModelsResponse;
  return Array.isArray(payload.models) ? payload.models : [];
}

test.describe('generation gateway catalog in the Chat picker', () => {
  test('picker lists every catalog-backed LiteLLM alias grouped by upstream provider', async ({ page }) => {
    const models = await fetchChatModels(page);
    expect(models.length).toBeGreaterThanOrEqual(300);
    const paid = models.find((row) => row.id === PAID_ALIAS);
    expect(paid, `${PAID_ALIAS} must be served by the gateway`).toBeTruthy();
    expect(paid?.catalog_provider).toBe(PAID_ALIAS.split('.', 1)[0]);
    expect(paid?.display_name).toBeTruthy();
    expect(paid?.context).toBeGreaterThan(0);
    expect(paid?.input_per_1k).toBeGreaterThan(0);

    await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
    const picker = page.getByTestId('model-picker').first();
    await expect(picker).toBeVisible({ timeout: 60_000 });
    await expect(picker).toBeEnabled();

    const optionValues = await picker.locator('option').evaluateAll((nodes) =>
      nodes
        .map((node) => (node as HTMLOptionElement).value)
        .filter((value) => value.startsWith('litellm:'))
    );
    expect(new Set(optionValues)).toEqual(new Set(models.map((row) => row.override)));

    const groupLabels = await picker.locator('optgroup').evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLOptGroupElement).label)
    );
    const expectedGroups = new Set(models.map((row) => row.catalog_provider ?? 'LiteLLM'));
    expect(models.every((row) => row.catalog_provider && row.catalog_model)).toBeTruthy();
    expect(groupLabels.length).toBe(expectedGroups.size);
    expect(groupLabels[0]).toMatch(/^ragweld \(/);
    expect(groupLabels.some((label) => label.startsWith(`${paid?.catalog_provider} (`))).toBeTruthy();

    const paidOption = picker.locator(`option[value="litellm:${PAID_ALIAS}"]`);
    await expect(paidOption).toHaveText(String(paid?.display_name));
    await expect(paidOption).toHaveAttribute('title', new RegExp(`alias ${PAID_ALIAS.replace(/\\./g, '\\\\.')}`));
  });

  test('Benchmark and Synthetic Lab pickers group the gateway catalog by provider', async ({ page }) => {
    const models = await fetchChatModels(page);
    const providers = new Set(models.map((row) => row.catalog_provider ?? 'LiteLLM'));
    const paid = models.find((row) => row.id === PAID_ALIAS);
    expect(paid).toBeTruthy();
    const paidGroupLabel = `${paid?.catalog_provider} (${models.filter((row) => row.catalog_provider === paid?.catalog_provider).length})`;

    await page.goto('benchmark', { waitUntil: 'domcontentloaded' });
    const benchmarkGroup = page.getByText(paidGroupLabel, { exact: true });
    await expect(benchmarkGroup).toBeVisible({ timeout: 60_000 });
    const benchmarkHeaders = await page.getByText(/^[a-z0-9.-]+ \(\d+\)$/).allInnerTexts();
    expect(new Set(benchmarkHeaders).size).toBe(providers.size);
    const paidCheckbox = page.getByRole('checkbox', { name: `Select ${paid?.catalog_provider} · ${paid?.display_name}`, exact: true });
    await expect(paidCheckbox).toBeVisible();

    await page.goto('rag?subtab=synthetic', { waitUntil: 'domcontentloaded' });
    const syntheticSelect = page.locator('select').filter({ has: page.locator(`optgroup[label="${paidGroupLabel}"]`) }).first();
    await expect(syntheticSelect).toBeVisible({ timeout: 60_000 });
    const syntheticGroups = await syntheticSelect.locator('optgroup').evaluateAll((nodes) =>
      nodes.map((node) => (node as HTMLOptGroupElement).label)
    );
    expect(syntheticGroups.length).toBe(providers.size);
    expect(syntheticGroups[0]).toMatch(/^ragweld \(/);
    await expect(syntheticSelect.locator(`option[value="litellm:${PAID_ALIAS}"]`)).toHaveText(String(paid?.display_name));
  });

  test('selecting a paid catalog alias yields a grounded, cited answer on the real corpus', async ({ page }) => {
    await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
    const picker = page.getByTestId('model-picker').first();
    await expect(picker).toBeEnabled({ timeout: 60_000 });
    await picker.selectOption(`litellm:${PAID_ALIAS}`);
    await expect(picker).toHaveValue(`litellm:${PAID_ALIAS}`);

    const sources = page.getByTestId('source-dropdown');
    await sources.locator('summary').click();
    const corpusToggle = page.getByTestId(`source-corpus-${CORPUS_ID}`);
    await expect(corpusToggle).toBeVisible();
    if (!(await corpusToggle.isChecked())) await corpusToggle.check();
    await expect(corpusToggle).toBeChecked();
    await sources.locator('summary').click();

    const assistantMessages = page.locator('[data-role="assistant"]');
    const baseline = await assistantMessages.count();
    await page.fill('#chat-input', REAL_QUESTION);
    const chatRequest = page.waitForRequest(
      (request) => request.method() === 'POST' && /\/api\/chat(\/stream)?(\?|$)/.test(request.url()),
      { timeout: 60_000 }
    );
    await page.click('#chat-send');
    const sent = JSON.parse((await chatRequest).postData() ?? '{}') as {
      model_override?: string;
      sources?: { corpus_ids?: string[] };
      message?: string;
    };
    expect(sent.model_override).toBe(`litellm:${PAID_ALIAS}`);
    expect(sent.sources?.corpus_ids ?? []).toContain(CORPUS_ID);
    expect(sent.message).toBe(REAL_QUESTION);
    await expect(assistantMessages).toHaveCount(baseline + 1, { timeout: 4 * 60 * 1000 });
    const latest = assistantMessages.nth(baseline);

    await expect(latest.getByTestId('chat-citation-link').first()).toBeVisible({ timeout: 60_000 });
    const answer = (await latest.innerText()).toLowerCase();
    expect(answer).toContain('cohen');
    expect(answer).toMatch(/plane|aircraft|jet|flight/);
    await expect(page.getByTestId('chat-structured-error-card')).toHaveCount(0);
    await expect(latest).toContainText('LiteLLM');
  });
});
