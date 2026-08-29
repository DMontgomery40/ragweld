import { expect, test } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const GLM_OVERRIDE = 'litellm:z-ai.glm-5.3-flash';

const productionConfig = JSON.parse(
  readFileSync(resolve(process.cwd(), 'tribrid_config.json'), 'utf-8'),
);
productionConfig.chat.litellm.enabled = true;
productionConfig.chat.litellm.default_model = 'openai.gpt-5.6-terra';

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

test('a saved chat model survives startup while the real model catalog is loading', async ({ page }) => {
  const conversationId = `saved-model-${Date.now()}`;
  await page.addInitScript(
    ({ convId, modelOverride }) => {
      const now = Date.now();
      localStorage.setItem(
        'ragweld-chat-threads:v2',
        JSON.stringify({
          version: 2,
          active_conversation_id: convId,
          sessions: [
            {
              conversation_id: convId,
              created_at: now,
              updated_at: now,
              title: 'Saved model regression',
              messages: [],
              model_override: modelOverride,
              sources: { corpus_ids: [] },
            },
          ],
        }),
      );
    },
    { convId: conversationId, modelOverride: GLM_OVERRIDE },
  );

  await page.route(/^https?:\/\/[^/]+\/api(?:\/|\?|$)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/api/config') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(productionConfig) });
      return;
    }
    if (url.pathname === '/api/corpora') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
      return;
    }
    if (url.pathname === '/api/chat/models') {
      await new Promise((resolveDelay) => setTimeout(resolveDelay, 1_500));
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
    if (url.pathname.includes('/stats')) {
      await route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });

  await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });

  const picker = page.getByTestId('model-picker').first();
  await expect(picker).toBeEnabled({ timeout: 60_000 });
  await expect(picker).toHaveValue(GLM_OVERRIDE);
});
