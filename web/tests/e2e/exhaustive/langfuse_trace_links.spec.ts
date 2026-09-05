import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { TriBridConfig } from '../../../src/types/generated';
import { API_BASE } from './corpus_fixture';

function emitTrace(traceId: string, baseUrl: string) {
  execFileSync(process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python', [
    'web/tests/e2e/exhaustive/emit_langfuse_trace.py', traceId, baseUrl,
  ], { cwd: process.cwd(), stdio: 'pipe', timeout: 30_000 });
}

async function expectIngested(request: APIRequestContext, traceId: string) {
  await expect.poll(async () => {
    const response = await request.get(`${API_BASE}/observability/langfuse/trace/${traceId}`);
    expect(response.ok()).toBeTruthy();
    return (await response.json()).exists;
  }, { timeout: 30_000 }).toBe(true);
}

async function showTraceLinks(page: Page, request: APIRequestContext, baseURL: string, ids: string[]) {
  const response = await request.get(`${API_BASE}/config`);
  expect(response.ok()).toBeTruthy();
  const config = await response.json() as TriBridConfig;
  expect(config.tracing.langfuse_enabled, 'this acceptance requires the real configured Langfuse').toBe(true);
  const traceBase = `${config.tracing.langfuse_public_base_url}/project/${config.tracing.langfuse_project}/traces`;
  const url = new URL('tests/fixtures/trace-external-links.html', baseURL);
  ids.forEach((id) => url.searchParams.append('trace', id));
  url.searchParams.set('traceBase', traceBase);
  await page.goto(url.toString());
  return config.tracing.langfuse_base_url;
}

test('a mounted trace link becomes available after real Langfuse ingestion', async ({ page, request, baseURL }) => {
  const id = randomBytes(16).toString('hex');
  const ingestionBase = await showTraceLinks(page, request, baseURL!, [id]);
  await expect(page.locator('[data-testid="trace-langfuse-pending"], [data-testid="trace-langfuse-withheld"]')).toBeVisible();
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveCount(0);
  emitTrace(id, ingestionBase);
  await expectIngested(request, id);
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveAttribute('href', new RegExp(`/${id}$`), {
    timeout: 45_000,
  });
  await expect(page.getByTestId('trace-langfuse-pending')).toHaveCount(0);
});

test('changing trace identity cannot inherit a previous trace access result', async ({ page, request, baseURL }) => {
  const ids = [randomBytes(16).toString('hex'), randomBytes(16).toString('hex')];
  const ingestionBase = await showTraceLinks(page, request, baseURL!, ids);
  emitTrace(ids[0], ingestionBase);
  await expectIngested(request, ids[0]);
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveAttribute('href', new RegExp(`/${ids[0]}$`), {
    timeout: 45_000,
  });
  await page.getByRole('button', { name: 'Next trace' }).click();
  await expect(page.getByTestId('fixture-trace-id')).toHaveText(ids[1]);
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveCount(0);
  await expect(page.getByTestId('trace-langfuse-pending')).toBeVisible();
  emitTrace(ids[1], ingestionBase);
  await expectIngested(request, ids[1]);
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveAttribute('href', new RegExp(`/${ids[1]}$`), {
    timeout: 45_000,
  });
});

test('an absent trace stops automatic checks and allows an explicit retry', async ({ page, request, baseURL }) => {
  const id = randomBytes(16).toString('hex');
  let checks = 0;
  page.on('request', (req) => {
    if (new URL(req.url()).pathname.endsWith(`/observability/langfuse/trace/${id}`)) checks += 1;
  });
  const ingestionBase = await showTraceLinks(page, request, baseURL!, [id]);
  const retry = page.getByRole('button', { name: 'Check Langfuse again' });
  await expect(retry).toBeVisible({ timeout: 65_000 });
  expect(checks).toBe(6);
  await page.waitForTimeout(2_000);
  expect(checks).toBe(6);
  emitTrace(id, ingestionBase);
  await expectIngested(request, id);
  await retry.click();
  await expect(page.getByTestId('trace-external-link-langfuse')).toHaveAttribute('href', new RegExp(`/${id}$`), {
    timeout: 45_000,
  });
});
