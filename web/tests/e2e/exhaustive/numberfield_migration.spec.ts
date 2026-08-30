// NumberField migration (T5/M-25): one behaviour for out-of-range typing across every
// config-bound numeric input, proven against the real API and the real Pydantic bounds -- no
// route mocking. Before this, three different surfaces disagreed on what happens when the
// operator types past a field's bound: Data Quality kept the rejected value and re-sent it on
// the next Apply (a 422 with no field attribution, C-01/C-02); Retrieval's BM25 b silently
// clamped and posted the clamped value; Retrieval's MMR Lambda silently reverted on blur and
// posted nothing at all (C-32). One scenario per surface family named by the brief (Data
// Quality, Chat Settings, Reranker, a Training Studio): type a value past the field's
// Pydantic ge/le, Tab away, and assert (a) the box shows the clamped value, (b) the PATCH
// that actually reached the server carried the clamped value and the raw value was never sent
// in any request, and (c) a fresh GET /api/config confirms the server persisted the clamped
// value, not the operator's typed one.
import { expect, test, type APIRequestContext, type Locator, type Page, type Request } from '@playwright/test';
import { API_BASE, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(2 * 60 * 1000);

let corpus: ExhaustiveCorpus;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request);
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

async function gotoScoped(page: Page, path: string): Promise<void> {
  await page.goto(`${path}${path.includes('?') ? '&' : '?'}corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await page.waitForSelector('.topbar', { timeout: 90_000 });
}

async function configSection<T>(request: APIRequestContext, section: string): Promise<T> {
  const response = await request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpus.corpusId)}`);
  expect(response.ok(), `GET /api/config for ${corpus.corpusId}`).toBeTruthy();
  const config = (await response.json()) as Record<string, T>;
  return config[section];
}

/**
 * Type `raw` into `field`, Tab away, and assert the box shows `clamped` -- `NumberField`'s
 * commit-on-blur clamp, driven by the min/max it advertises (which now equal the field's
 * Pydantic ge/le; see `test_every_number_field_advertises_its_pydantic_bounds`). Waits for the
 * PATCH to `patchUrlSubstring` (e.g. "/api/config/enrichment") to land, and records every PATCH
 * body sent during the interaction so the caller can assert the raw value was never among them
 * -- not just that the clamped one eventually was.
 */
async function commitOutOfRangeValue(
  page: Page,
  field: Locator,
  raw: string,
  clamped: string,
  patchUrlSubstring: string
): Promise<{ patchedBody: string; allPatchBodies: string[] }> {
  const allPatchBodies: string[] = [];
  const onRequest = (req: Request) => {
    if (req.method() === 'PATCH') {
      const body = req.postData();
      if (body) allPatchBodies.push(body);
    }
  };
  page.on('request', onRequest);

  const patchResponse = page.waitForResponse(
    (res) => res.request().method() === 'PATCH' && res.url().includes(patchUrlSubstring),
    { timeout: 15_000 }
  );
  await field.fill(raw);
  await field.press('Tab');
  await expect(field).toHaveValue(clamped);
  const response = await patchResponse;
  expect(response.status(), `PATCH ${patchUrlSubstring} failed`).toBe(200);
  const patchedBody = response.request().postData() ?? '';

  page.off('request', onRequest);
  return { patchedBody, allPatchBodies };
}

test('Data Quality: an out-of-range chunk-summaries max clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'rag?subtab=data-quality');
  const field = page.getByTestId('data-quality-chunk-summaries-max');
  await expect(field).toBeVisible();

  // The exact probe C-01 used (999999) against enrichment.chunk_summaries_max's Pydantic
  // bound (le=1000) -- C-01 found this reached the server unclamped and came back a 422 whose
  // only signal was a raw axios string; the value stayed in the box and re-sent on Apply.
  const { patchedBody, allPatchBodies } = await commitOutOfRangeValue(
    page,
    field,
    '999999',
    '1000',
    '/api/config/enrichment'
  );

  expect(patchedBody).toContain('"chunk_summaries_max":1000');
  for (const body of allPatchBodies) {
    expect(body, 'no PATCH ever carried the raw out-of-range value').not.toContain('999999');
  }

  const persisted = await configSection<{ chunk_summaries_max: number }>(request, 'enrichment');
  expect(persisted.chunk_summaries_max).toBe(1000);
});

test('Chat Settings: an out-of-range temperature clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'chat?subtab=settings');
  const field = page.getByTestId('chat-settings-temperature');
  await expect(field).toBeVisible();

  // Not chat.max_tokens: that path is a deployment-owned "production-scoped global" setting
  // (`_PRODUCTION_SCOPED_GLOBAL_PATHS`, server/services/config_store.py) -- in production mode
  // a per-corpus GET silently reconciles it back to the operator's global value regardless of
  // what was just PATCHed, which would make the persistence assertion below fail for a reason
  // that has nothing to do with NumberField. chat.temperature carries no such reconciliation.
  const { patchedBody, allPatchBodies } = await commitOutOfRangeValue(
    page,
    field,
    '9',
    '2',
    '/api/config/chat'
  );

  expect(patchedBody).toContain('"temperature":2');
  for (const body of allPatchBodies) {
    expect(body, 'no PATCH ever carried the raw out-of-range value').not.toMatch(/"temperature":9(?!\d)/);
  }

  const persisted = await configSection<{ temperature: number }>(request, 'chat');
  expect(persisted.temperature).toBe(2);
});

test('Reranker: an out-of-range input-snippet-chars clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'rag?subtab=reranker-config');
  // Not tribrid_reranker_alpha: that field only renders when reranker_mode === 'learning'
  // (RerankerConfigSubtab.tsx:252), and `provisionExhaustiveCorpus` deliberately scopes every
  // fixture corpus to reranker_mode: 'none' (cost/determinism isolation) -- picking a
  // mode-gated field would make this test's setup fight the shared fixture. Input snippet
  // chars lives in "Shared reranking behavior", visible regardless of mode, same as the shape
  // of C-32's out-of-range probes (BM25 b clamped and posted the clamped value silently).
  const field = page.getByTestId('reranker-config-snippet-chars');
  await expect(field).toBeVisible();

  const { patchedBody, allPatchBodies } = await commitOutOfRangeValue(
    page,
    field,
    '50000',
    '2000',
    '/api/config/reranking'
  );

  expect(patchedBody).toContain('"rerank_input_snippet_chars":2000');
  for (const body of allPatchBodies) {
    expect(body, 'no PATCH ever carried the raw out-of-range value').not.toContain('50000');
  }

  const persisted = await configSection<{ rerank_input_snippet_chars: number }>(request, 'reranking');
  expect(persisted.rerank_input_snippet_chars).toBe(2000);
});

test('Reranker Training Studio: an out-of-range epoch count clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'rag?subtab=learning-ranker');
  // The training-config form (Epochs and its siblings) lives in the Inspector dock panel's
  // "Paths + Config" tab (id: 'config', TrainingStudio.tsx:1095), which is not the Inspector's
  // default active tab.
  await page.getByRole('button', { name: 'Paths + Config' }).click();
  const field = page.getByTestId('training-studio-epochs');
  await expect(field).toBeVisible();

  const { patchedBody, allPatchBodies } = await commitOutOfRangeValue(
    page,
    field,
    '999',
    '20',
    '/api/config/training'
  );

  expect(patchedBody).toContain('"reranker_train_epochs":20');
  for (const body of allPatchBodies) {
    expect(body, 'no PATCH ever carried the raw out-of-range value').not.toContain('999');
  }

  const persisted = await configSection<{ reranker_train_epochs: number }>(request, 'training');
  expect(persisted.reranker_train_epochs).toBe(20);
});
