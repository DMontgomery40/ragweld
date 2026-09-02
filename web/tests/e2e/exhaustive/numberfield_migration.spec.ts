// NumberField migration (T5/M-25) under the STAGED commit model (T6): one behaviour for
// out-of-range typing across every config-bound numeric input, proven against the real API and
// the real Pydantic bounds -- no route mocking. Before T5 three surfaces disagreed on out-of-range
// typing; T5 unified them on NumberField's clamp-on-blur. T6 then made every config edit STAGE
// (no PATCH-on-blur) -- so the contract these tests pin moved with the commit model, in this
// branch (replacement-only: the tests of the replaced slice move with it). One scenario per
// surface family named by the brief (Data Quality, Chat Settings, Reranker, a Training Studio):
// type a value past the field's Pydantic ge/le, Tab away, and assert (a) the box shows the clamped
// value, (b) blur wrote NOTHING and the change staged (the Apply count goes up by one), (c) Apply
// PUTs the whole config carrying the CLAMPED value and the raw value never reached any request,
// and (d) a fresh GET /api/config confirms the server persisted the clamped value.
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
 * Type `raw` into `field`, Tab away (NumberField clamps in the box to the min/max it advertises,
 * which equal the field's Pydantic ge/le), assert blur STAGED the clamped value without any
 * network write and bumped the Apply count, then click Apply and return the whole-config PUT body
 * plus every PATCH/PUT body seen during the interaction, so the caller can assert the PUT carried
 * the clamped value and the raw value was never in any request.
 */
async function stageAndApplyOutOfRangeValue(
  page: Page,
  field: Locator,
  raw: string,
  clamped: string
): Promise<{ putBody: string; allBodies: string[] }> {
  const allBodies: string[] = [];
  const onRequest = (req: Request) => {
    if (req.method() === 'PATCH' || req.method() === 'PUT') {
      const body = req.postData();
      if (body) allBodies.push(body);
    }
  };
  page.on('request', onRequest);

  const apply = page.getByTestId('apply-changes');
  const countBefore = Number((await apply.getAttribute('data-dirty-count')) ?? '0') || 0;

  // Fill past the bound, Tab away -> NumberField clamps in the box and STAGES the clamped value.
  await field.fill(raw);
  await field.press('Tab');
  await expect(field).toHaveValue(clamped);

  // Staged, not written: no PATCH/PUT on blur, and the footer's dirty count went up by exactly one.
  expect(allBodies, 'blur must write nothing under the staged model').toEqual([]);
  await expect(apply).toBeEnabled();
  await expect
    .poll(async () => Number((await apply.getAttribute('data-dirty-count')) ?? '0') || 0)
    .toBe(countBefore + 1);

  // Apply -> one PUT of the whole config carrying the clamped value.
  const putResponse = page.waitForResponse(
    (res) => res.request().method() === 'PUT' && /\/api\/config(\?|$)/.test(res.url()),
    { timeout: 15_000 }
  );
  await apply.click();
  const response = await putResponse;
  expect(response.status(), 'PUT /api/config failed').toBe(200);
  const putBody = response.request().postData() ?? '';

  page.off('request', onRequest);
  return { putBody, allBodies };
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
  const { putBody, allBodies } = await stageAndApplyOutOfRangeValue(page, field, '999999', '1000');

  expect(putBody).toContain('"chunk_summaries_max":1000');
  for (const body of allBodies) {
    // Field-specific: the whole-config PUT may legitimately hold this number in an unrelated
    // field, so assert the RAW value never reached THIS field, not that the digits never appear.
    expect(body, 'no request ever carried the raw out-of-range value').not.toContain('"chunk_summaries_max":999999');
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
  const { putBody, allBodies } = await stageAndApplyOutOfRangeValue(page, field, '9', '2');

  expect(putBody).toContain('"temperature":2');
  for (const body of allBodies) {
    expect(body, 'no request ever carried the raw out-of-range value').not.toMatch(/"temperature":9(?!\d)/);
  }

  const persisted = await configSection<{ temperature: number }>(request, 'chat');
  expect(persisted.temperature).toBe(2);
});

test('Reranker: an out-of-range input-snippet-chars clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'rag?subtab=reranker');
  // Not tribrid_reranker_alpha: that field only renders when reranker_mode === 'learning'
  // (RerankerConfigSubtab.tsx:252), and `provisionExhaustiveCorpus` deliberately scopes every
  // fixture corpus to reranker_mode: 'none' (cost/determinism isolation) -- picking a
  // mode-gated field would make this test's setup fight the shared fixture. Input snippet
  // chars lives in "Shared reranking behavior", visible regardless of mode, same as the shape
  // of C-32's out-of-range probes (BM25 b clamped and posted the clamped value silently).
  const field = page.getByTestId('reranker-config-snippet-chars');
  await expect(field).toBeVisible();

  const { putBody, allBodies } = await stageAndApplyOutOfRangeValue(page, field, '50000', '2000');

  expect(putBody).toContain('"rerank_input_snippet_chars":2000');
  for (const body of allBodies) {
    // Field-specific: 50000 is a legitimate default elsewhere in the full-config PUT.
    expect(body, 'no request ever carried the raw out-of-range value').not.toContain('"rerank_input_snippet_chars":50000');
  }

  const persisted = await configSection<{ rerank_input_snippet_chars: number }>(request, 'reranking');
  expect(persisted.rerank_input_snippet_chars).toBe(2000);
});

test('Reranker Training Studio: an out-of-range epoch count clamps to the Pydantic bound and never posts the raw value', async ({
  page,
  request,
}) => {
  await gotoScoped(page, 'rag?subtab=learning-reranker');
  // The training-config form (Epochs and its siblings) lives in the Inspector dock panel's
  // "Paths + Config" tab (id: 'config', TrainingStudio.tsx:1095), which is not the Inspector's
  // default active tab.
  await page.getByRole('button', { name: 'Paths + Config' }).click();
  const field = page.getByTestId('training-studio-epochs');
  await expect(field).toBeVisible();

  const { putBody, allBodies } = await stageAndApplyOutOfRangeValue(page, field, '999', '20');

  expect(putBody).toContain('"reranker_train_epochs":20');
  for (const body of allBodies) {
    expect(body, 'no request ever carried the raw out-of-range value').not.toContain('"reranker_train_epochs":999');
  }

  const persisted = await configSection<{ reranker_train_epochs: number }>(request, 'training');
  expect(persisted.reranker_train_epochs).toBe(20);
});

test('Storage Calculator: a typed free-form value survives blur unchanged, no step-snapping', async ({ page }) => {
  // Not config-bound (a local calculator input, requirement 1) -- no corpus scoping needed.
  await page.goto('dashboard?subtab=storage', { waitUntil: 'domcontentloaded' });
  const field = page.getByTestId('storage-calc-hydration');
  await expect(field).toBeVisible();

  // M1: these 16 fields kept their old `step` literals when migrated to NumberField, whose
  // clamp *snaps* to step (origin = min), not just clamps -- so a typed 25 silently committed
  // 30 (step=10) even though the value was already inside [0,100]. `step` is dropped from all
  // 16 free-form calculator inputs; NumberField still clamps to min/max, it just no longer
  // snaps a value that was never out of range.
  await field.fill('25');
  await field.press('Tab');
  await expect(field).toHaveValue('25');

  // min/max clamping itself is unaffected by dropping step: still refuses to exceed the bound.
  await field.fill('150');
  await field.press('Tab');
  await expect(field).toHaveValue('100');
});
