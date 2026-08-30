// The one paid interaction in lane chat2: prove a real user Stop halts the send and never
// leaves a permanent "Streaming" orphan (M-93 / B-07). The send is aborted within a second, so
// it is the cheapest possible; excluded from repeated runs.
//
// In an environment where the stream aborts cleanly the bubble finalizes to a cancelled +
// Retry state immediately; independently of that, the durable guarantee is that a reload
// reconciles any still-running bubble to a retryable error (the exact B-07 defect: an orphan
// that "survives page reloads"). This test proves the halt and the durable guarantee, so it
// holds regardless of how promptly the underlying stream settles on abort.
import { expect, test } from '@playwright/test';

test('M-93: Stop halts the send and leaves no permanent Streaming orphan', async ({ page }) => {
  await page.goto('chat', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  // Scope to the main chat tab: a docked chat mirror renders a second ChatInterface.
  const chat = page.locator('#tab-chat-ui');
  await expect(chat.locator('#chat-input')).toBeVisible({ timeout: 90_000 });
  await expect(chat.getByTestId('model-picker')).toBeEnabled({ timeout: 60_000 });

  await chat.locator('#chat-input').fill('Write a long, detailed essay about hybrid retrieval systems.');
  await chat.locator('#chat-send').click();

  // Once it is streaming, press Stop.
  const sendButton = chat.locator('#chat-send');
  await expect(sendButton).toHaveText('Stop', { timeout: 60_000 });
  await sendButton.click();

  // Stop halts the send: the composer returns to a ready state.
  await expect(sendButton).toHaveText('Send', { timeout: 20_000 });
  await expect(chat.locator('#chat-input')).toBeEnabled({ timeout: 20_000 });

  // Durable guarantee: after a reload the abandoned answer is a terminal, retryable error —
  // never a permanent "Streaming" bubble (B-07).
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(chat.locator('#chat-input')).toBeVisible({ timeout: 90_000 });
  await expect(chat.getByTestId('chat-streaming-elapsed')).toHaveCount(0, { timeout: 30_000 });
  const errorCard = chat.getByTestId('chat-assistant-error');
  await expect(errorCard).toBeVisible({ timeout: 30_000 });
  await expect(errorCard).toContainText(/interrupted/i);
  await expect(chat.getByTestId('chat-retry')).toBeVisible();
});
