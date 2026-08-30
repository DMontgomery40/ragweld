import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const productionConfig = JSON.parse(
  readFileSync(resolve(process.cwd(), 'tribrid_config.json'), 'utf-8'),
);
productionConfig.ui.runtime_mode = 'production';
productionConfig.generation.gen_model = 'openai.gpt-5.6-terra';
productionConfig.chat.litellm.default_model = 'z-ai.glm-5.3-flash';
productionConfig.ui.chat_default_model = 'z-ai.glm-5.3-flash';

const model = (id: string, displayName: string, catalogProvider: string) => ({
  id,
  override: `litellm:${id}`,
  provider: 'LiteLLM',
  provider_key: 'litellm',
  catalog_model: id.replace('.', '/'),
  components: ['GEN'],
  source: 'litellm',
  provider_type: 'litellm',
  base_url: 'http://127.0.0.1:54000/v1',
  supports_vision: false,
  catalog_provider: catalogProvider,
  display_name: displayName,
  context: 131_072,
  input_per_1k: 0.001,
  output_per_1k: 0.001,
});

test('production retrieval identifies the non-chat generation alias as deployment locked', async ({ page }) => {
  await page.route(/^https?:\/\/[^/]+\/api(?:\/|\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/config') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(productionConfig) });
      return;
    }
    if (url.pathname === '/api/corpora') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ corpus_id: 'nasa-apollo-11', slug: 'nasa-apollo-11', name: 'NASA Apollo 11 Mission Repo' }]),
      });
      return;
    }
    if (url.pathname === '/api/chat/models') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          models: [
            model('openai.gpt-5.6-terra', 'OpenAI: GPT-5.6 Terra', 'openai'),
            model('z-ai.glm-5.3-flash', 'Z.ai: GLM 5.3 Flash', 'z-ai'),
          ],
        }),
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.goto('rag?subtab=retrieval&corpus=nasa-apollo-11', { waitUntil: 'domcontentloaded' });
  await page.getByTestId('retrieval-card-generation').click();

  const control = page.getByTestId('retrieval-generation-answer-alias');
  await expect(control).toBeVisible();
  await expect(control.getByText('Non-chat generation alias')).toBeVisible();
  await expect(control.locator('select')).toBeDisabled();
  await expect(control.locator('select')).toHaveAttribute(
    'aria-describedby',
    'retrieval-generation-answer-alias-lock-note',
  );
  await expect(control.locator('select')).toHaveValue('openai.gpt-5.6-terra');
  await expect(control).toContainText('Chat uses its own model picker');
  await expect(control).toContainText('locked by the production deployment');
});
