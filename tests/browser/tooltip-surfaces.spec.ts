import { test, expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';

// Real application routes and the configured API, read-only: no settings saves,
// synthetic runs, retrieval queries, training, request interception or mocks.
test('new glossary help renders on Grafana and Synthetic Lab settings', async ({ page }) => {
  const writes: string[] = [];
  page.on('request', request => {
    if (/\/api\/config(?:[/?]|$)/.test(request.url()) && request.method() !== 'GET') writes.push(request.url());
  });
  await page.goto('/web/grafana?subtab=config');
  const grafanaHelp = page.getByLabel('Help: GRAFANA_EMBED_ENABLED', { exact: true });
  await expect(grafanaHelp).toBeVisible();
  await grafanaHelp.click();
  await expect(page.getByRole('tooltip')).toContainText('Grafana');
  await expect(page.getByRole('tooltip').locator('a').first()).toHaveAttribute('href', /^https:\/\/grafana\.com\//);
  await page.screenshot({ path: 'artifacts/tooltip-grafana-settings.png', fullPage: false });
  await page.keyboard.press('Escape');

  await page.goto('/web/rag?subtab=synthetic');
  const recipe = page.getByLabel('Help: SYNTHETIC_RECIPE', { exact: true });
  await expect(recipe).toBeVisible();
  await recipe.click();
  await expect(page.getByRole('tooltip')).toContainText('recipe');
  await expect(page.getByRole('tooltip')).not.toContainText('No tooltip available');
  await page.screenshot({ path: 'artifacts/tooltip-synthetic-settings.png', fullPage: false });
  expect(writes).toEqual([]);
});

test('every real Config Explorer field renders its mapped glossary help', async ({ page }) => {
  const mapping: Record<string, string> = JSON.parse(await readFile('web/src/components/Admin/configGlossaryKeys.json', 'utf8'));
  const writes: string[] = [];
  page.on('request', request => {
    if (/\/api\/config(?:[/?]|$)/.test(request.url()) && request.method() !== 'GET') writes.push(request.url());
  });
  await page.goto('/web/admin?subtab=advanced');
  const explorer = page.locator('#tab-admin-advanced');
  await expect(explorer.locator('[data-config-path]')).toHaveCount(Object.keys(mapping).length);
  const rendered = await explorer.locator('[data-config-path]').evaluateAll(elements => elements.map(element => ({
    path: element.getAttribute('data-config-path'),
    help: element.querySelector('.help-icon')?.getAttribute('aria-label'),
  })));
  for (const field of rendered) expect(field.help).toBe(`Help: ${mapping[field.path!]}`);

  const search = explorer.getByPlaceholder('Search fields, paths, or descriptions');
  for (const path of ['chat.web.enabled', 'training.ragweld_agent_workflow_backend', 'system_prompts.synthetic_generator']) {
    await search.fill(path);
    const field = explorer.locator(`[data-config-path="${path}"]`);
    const help = field.getByRole('button', { name: `Help: ${mapping[path]}`, exact: true });
    await help.focus();
    const bubble = page.getByRole('tooltip');
    await expect(bubble).toBeVisible();
    await expect(bubble).not.toContainText('No tooltip available');
    if (path === 'chat.web.enabled') await page.screenshot({ path: 'artifacts/tooltip-admin-registry.png', fullPage: false });
    await page.keyboard.press('Escape');
  }
  expect(writes).toEqual([]);
});

test('retrieval help preserves generation selections and covers all final labels', async ({ page }) => {
  const writes: string[] = [];
  page.on('request', request => {
    if (/\/api\/config(?:[/?]|$)/.test(request.url()) && request.method() !== 'GET') writes.push(request.url());
  });
  await page.goto('/web/rag?subtab=retrieval');
  await page.getByTestId('retrieval-card-generation').click();
  const model = page.getByTestId('retrieval-generation-answer-alias').locator('select');
  await expect(model).not.toHaveValue('');
  const before = await model.inputValue();
  for (const key of ['GEN_MODEL', 'GEN_MODEL_HTTP', 'GEN_MODEL_MCP', 'GEN_MODEL_CLI', 'ENRICH_MODEL', 'LITELLM_API_KEY']) {
    const help = page.getByLabel(`Help: ${key}`, { exact: true });
    await help.focus();
    await expect(page.getByRole('tooltip')).toBeVisible();
    await expect(page.getByRole('tooltip')).not.toContainText('No tooltip available');
    if (key === 'GEN_MODEL') await page.screenshot({ path: 'artifacts/tooltip-retrieval-generation.png', fullPage: false });
    await page.keyboard.press('Escape');
  }
  await expect(model).toHaveValue(before);
  await page.getByTestId('retrieval-card-ops_tracing').click();
  await page.getByTestId('retrieval-ops-tab-observability').click();
  await page.getByLabel('Help: OTEL_EXPORT_ENABLED', { exact: true }).hover();
  await expect(page.getByRole('tooltip')).toContainText('OpenTelemetry');
  await page.keyboard.press('Escape');
  expect(writes).toEqual([]);
});
