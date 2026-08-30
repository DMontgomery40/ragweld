// Chat workbench UI defects (wave 2b, lane chat2). Every test here is seeded from
// localStorage and drives only client behaviour — no gateway model is called, so the whole
// file costs nothing to run. The paid Stop proof lives in chat_reliability.spec.ts.
import { expect, test, type Page } from '@playwright/test';

const THREADS_KEY = 'ragweld-chat-threads:v2';

type SeededMessage = {
  id: string;
  role: 'user' | 'assistant';
  createdAt: string;
  content: { type: 'text'; text: string }[];
  status?: { type: string; reason?: string; error?: string };
  metadata?: { custom?: Record<string, unknown> };
};

async function seedThread(
  page: Page,
  opts: { sources: { corpus_ids: string[] }; messages: SeededMessage[]; title?: string },
): Promise<string> {
  const convId = `chat2-seed-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  await page.addInitScript(
    ({ key, convId, sources, messages, title }) => {
      const now = Date.now();
      const session = {
        conversation_id: convId,
        created_at: now,
        updated_at: now,
        title: title || 'Chat2 seed',
        model_override: '',
        sources,
        messages,
      };
      localStorage.setItem(key, JSON.stringify({ version: 2, active_conversation_id: convId, sessions: [session] }));
    },
    { key: THREADS_KEY, convId, sources: opts.sources, messages: opts.messages, title: opts.title },
  );
  return convId;
}

async function gotoChat(page: Page): Promise<void> {
  await page.goto('chat', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#chat-input', { timeout: 90_000 });
}

function completedAssistant(text: string, custom: Record<string, unknown> = {}): SeededMessage {
  const now = Date.now();
  return {
    id: `assistant-${now}`,
    role: 'assistant',
    createdAt: new Date(now).toISOString(),
    content: [{ type: 'text', text }],
    status: { type: 'complete', reason: 'stop' },
    metadata: { custom: { runId: `spec-${now}`, ...custom } },
  };
}

test.describe.serial('chat workbench (seeded, no paid sends)', () => {
  test('M-05: Helpful / Not helpful are legible (>=11.5px, >=4.5:1)', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'hi' }] },
        completedAssistant('An answer with feedback controls.'),
      ],
    });
    await gotoChat(page);

    for (const testId of ['chat-feedback-thumbsup', 'chat-feedback-thumbsdown']) {
      const button = page.getByTestId(testId);
      await expect(button).toBeVisible();
      const metrics = await button.evaluate((el) => {
        const lin = (c: number): number => {
          const s = c / 255;
          return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
        };
        const lum = (rgb: string): number => {
          const m = (rgb.match(/\d+(\.\d+)?/g) || ['0', '0', '0']).map(Number);
          return 0.2126 * lin(m[0]) + 0.7152 * lin(m[1]) + 0.0722 * lin(m[2]);
        };
        const contrast = (fg: string, bg: string): number => {
          const a = lum(fg);
          const b = lum(bg);
          return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
        };
        const bgOf = (node: HTMLElement | null): string => {
          let n: HTMLElement | null = node;
          while (n) {
            const c = getComputedStyle(n).backgroundColor;
            if (c && c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent') return c;
            n = n.parentElement;
          }
          return 'rgb(0, 0, 0)';
        };
        const cs = getComputedStyle(el);
        const bg = bgOf(el.parentElement);
        return {
          fontSizePx: parseFloat(cs.fontSize),
          color: cs.color,
          opacity: parseFloat(cs.opacity),
          contrast: contrast(cs.color, bg),
        };
      });
      expect(metrics.fontSizePx, `${testId} font-size`).toBeGreaterThanOrEqual(11.5);
      expect(metrics.color, `${testId} colour must not be black-on-black`).not.toBe('rgb(0, 0, 0)');
      expect(metrics.opacity, `${testId} opacity floor`).toBeGreaterThanOrEqual(0.8);
      expect(metrics.contrast, `${testId} contrast (measured ${metrics.contrast.toFixed(2)}:1)`).toBeGreaterThanOrEqual(4.5);
    }
  });

  test('M-93: an abandoned running stream reconciles to a retryable error on reload', async ({ page }) => {
    const now = Date.now();
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: 'why did it hang?' }] },
        {
          id: 'a1',
          role: 'assistant',
          createdAt: new Date(now + 1).toISOString(),
          content: [],
          status: { type: 'running' },
          metadata: { custom: {} },
        },
      ],
    });
    await gotoChat(page);

    // The orphan no longer renders "Streaming" forever; it is a terminal, retryable error.
    await expect(page.getByTestId('chat-streaming-elapsed')).toHaveCount(0);
    const errorCard = page.getByTestId('chat-assistant-error');
    await expect(errorCard).toBeVisible();
    await expect(errorCard).toContainText(/interrupted/i);
    await expect(page.getByTestId('chat-retry')).toBeVisible();
  });

  test('M-99: Export downloads a file and confirms', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'export me' }] },
        completedAssistant('Answer to export.'),
      ],
    });
    await gotoChat(page);

    const downloadPromise = page.waitForEvent('download', { timeout: 15_000 });
    await page.getByTestId('chat-export').click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^chat-export-\d+\.json$/);
    await expect(page.getByText(/Exported \d+ message/)).toBeVisible();
  });

  test('M-98: an attached image shows its name, size and type', async ({ page }) => {
    await seedThread(page, { sources: { corpus_ids: ['recall_default'] }, messages: [] });
    await gotoChat(page);

    // A minimal valid 1x1 PNG.
    const pngBase64 =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==';
    await page.getByTestId('chat-image-input').setInputFiles({
      name: 'diagram.png',
      mimeType: 'image/png',
      buffer: Buffer.from(pngBase64, 'base64'),
    });

    const name = page.getByTestId('chat-attachment-name-0');
    await expect(name).toBeVisible();
    await expect(name).toHaveText('diagram.png');
    await expect(page.getByTestId('chat-attachment-0')).toContainText('PNG');
  });

  test('M-96: recall-only selection reads "Recall", never "1 selected"', async ({ page }) => {
    await seedThread(page, {
      sources: { corpus_ids: ['recall_default'] },
      messages: [
        { id: 'u1', role: 'user', createdAt: new Date().toISOString(), content: [{ type: 'text', text: 'memory only' }] },
        completedAssistant('Recall-only answer.'),
      ],
    });
    await gotoChat(page);

    const trigger = page.getByTestId('source-dropdown-trigger');
    await expect(trigger).toContainText('Recall');
    await expect(trigger).not.toContainText(/\bselected\b/);
    await expect(trigger).not.toContainText(/\bcorpus\b|\bcorpora\b/);
  });
});
