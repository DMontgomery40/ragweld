import { expect, test, type Page } from '@playwright/test';
import {
  activateCorpusInBrowser,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';
import { applyRefreshDoubleCheck, gotoSurface } from './harness';
import type { ControlDescriptor } from './types';

let corpus: ExhaustiveCorpus | null = null;
let unindexedCorpus: ExhaustiveCorpus | null = null;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request, { index: true });
  unindexedCorpus = await provisionExhaustiveCorpus(request, { index: false });
});

test.afterAll(async ({ request }) => {
  if (corpus) await corpus.dispose(request);
  if (unindexedCorpus) await unindexedCorpus.dispose(request);
});

test('surface re-anchoring leaves the transient Chat source dropdown closed', async ({ page }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);
  await gotoSurface(page, { route: '/chat', subtab: 'ui', label: 'Chat / UI' });

  const dropdown = page.getByTestId('source-dropdown');
  await expect(dropdown).toBeVisible();
  await expect(dropdown).not.toHaveAttribute('open', '');
});

test('an indexed corpus disables every advanced field that changes the dense contract', async ({ page }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);
  await page.goto(
    `rag?subtab=indexing&component=embedding&corpus=${encodeURIComponent(corpus!.corpusId)}`,
    { waitUntil: 'domcontentloaded' }
  );

  const contractFields = [
    'embedding-input-truncation',
    'embedding-text-prefix',
    'embedding-text-suffix',
    'embedding-contextual-chunk-embeddings',
    'embedding-late-chunking-max-doc-tokens',
    'embedding-max-tokens',
  ];
  for (const testId of contractFields) {
    const field = page.getByTestId(testId);
    await expect(field).toBeVisible({ timeout: 60_000 });
    await expect(field, `${testId} must not stage a contract change against an existing index`).toBeDisabled();
  }
});

test('Apply confirms and persists an index-affecting field before an index exists', async ({ page }) => {
  expect(unindexedCorpus).not.toBeNull();
  await activateCorpusInBrowser(page, unindexedCorpus!.corpusId);
  await page.goto(
    `rag?subtab=indexing&component=embedding&corpus=${encodeURIComponent(unindexedCorpus!.corpusId)}`,
    { waitUntil: 'domcontentloaded' }
  );

  const selector = '[data-testid="embedding-text-suffix"]';
  const field = page.locator(selector).first();
  await expect(field).toBeVisible({ timeout: 60_000 });
  const expected = `exhaustive-confirm-${Date.now()}`;
  await field.fill(expected);

  const control: ControlDescriptor = {
    fingerprint: 'input|text|||Text suffix',
    selector,
    tag: 'input',
    type: 'text',
    role: '',
    id: '',
    name: '',
    label: 'Text suffix',
    value: '',
    checked: null,
    disabled: false,
    visible: true,
    optionValues: [],
  };
  const cycle = await applyRefreshDoubleCheck(page, control, expected);
  expect(cycle).toEqual({
    config_changed: true,
    apply_saved: true,
    persisted_after_refresh: true,
    ui_matches: true,
  });
});

// ---------------------------------------------------------------------------
// Index-contract lock family.
//
// The lock's operator promise (the banner text) is: with an existing index and
// Force reindex off, every control whose value changes what lands in the dense
// or sparse index is non-editable, and everything else stays usable. The 2026-08-31
// public-browser repro typed a new Chunk Size into a locked corpus — only the
// embedding/tokenizer fields were gated, the whole chunking section was live.
// These matrices pin the family on both sides:
//   locked  = controls whose values feed chunk production, text extraction,
//             dense embedding, or the sparse (Qdrant/bm25) contract
//   usable  = operational knobs (batching, timeouts) and graph-leg controls,
//             which the backend index-contract lock does not cover (there is no
//             graph contract-mismatch enforcement; graph writes do not change
//             dense/sparse index contents)
// ---------------------------------------------------------------------------

async function gotoIndexingComponent(page: Page, corpusId: string, component: string): Promise<void> {
  await page.goto(
    `rag?subtab=indexing&component=${component}&corpus=${encodeURIComponent(corpusId)}`,
    { waitUntil: 'domcontentloaded' }
  );
}

async function openAdvancedChunkingControls(page: Page): Promise<void> {
  const summary = page.locator('summary', { hasText: 'Advanced chunking controls' });
  await expect(summary).toBeVisible({ timeout: 60_000 });
  await summary.click();
}

/** Controls rendered for the fixture's default `ast` strategy (chars branch). */
const CHUNKING_AST_BRANCH = [
  'chunking-chunk-size',
  'chunking-chunk-overlap',
  'chunking-max-chunk-tokens',
  'chunking-min-chunk-chars',
  'chunking-max-indexable-file-size',
  'chunking-emit-chunk-ordinal',
  'chunking-emit-parent-doc-id',
  'chunking-preserve-imports',
  'greedy-fallback-target',
];

/** Extra controls rendered when chunking_strategy=recursive (token branch + separators). */
const CHUNKING_RECURSIVE_BRANCH = [
  'chunking-target-tokens',
  'chunking-overlap-tokens',
  'chunking-separators',
  'chunking-separator-keep',
  'chunking-recursive-max-depth',
];

/** Extra controls rendered when chunking_strategy=markdown. */
const CHUNKING_MARKDOWN_BRANCH = [
  'chunking-markdown-max-heading-level',
  'chunking-markdown-include-code-fences',
];

const TOKENIZATION_CONTRACT_CONTROLS = [
  'tokenization-strategy',
  'tokenization-index-max-file-size-mb',
  'large-file-mode',
  // default large_file_mode is 'stream', so this field's only disable input is the lock
  'tokenization-large-file-stream-chunk-chars',
  'parquet-extract-max-rows',
  'parquet-extract-max-chars',
  'parquet-extract-max-cell-chars',
  'parquet-extract-text-columns-only',
  'parquet-extract-include-column-names',
  'sparse-bm25-tokenizer',
  'sparse-bm25-stemmer-lang',
];

async function expectAll(page: Page, testIds: string[], state: 'disabled' | 'enabled'): Promise<void> {
  for (const testId of testIds) {
    const field = page.getByTestId(testId);
    await expect(field, `${testId} should be visible`).toBeVisible({ timeout: 60_000 });
    if (state === 'disabled') {
      await expect(field, `${testId} must not stage an index-content change against an existing index`).toBeDisabled();
    } else {
      await expect(field, `${testId} must stay editable when no index contract is locked`).toBeEnabled();
    }
  }
}

async function expectStrategyRadios(page: Page, state: 'disabled' | 'enabled'): Promise<void> {
  const radios = page.getByTestId('chunking-strategy-group').getByRole('radio');
  await expect(radios.first()).toBeVisible({ timeout: 60_000 });
  const count = await radios.count();
  expect(count, 'the strategy radiogroup must offer real choices').toBeGreaterThanOrEqual(2);
  for (let i = 0; i < count; i += 1) {
    if (state === 'disabled') {
      await expect(radios.nth(i), 'chunking strategy must not change while the index contract is locked').toBeDisabled();
    } else {
      await expect(radios.nth(i), 'chunking strategy must stay selectable without an index').toBeEnabled();
    }
  }
}

test('contract lock disables every index-content control across chunking, tokenization, embedding and graph', async ({ page, request }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);

  // Chunking, default (ast) branch: the exact surface of the public repro.
  await gotoIndexingComponent(page, corpus!.corpusId, 'chunking');
  await expect(page.getByTestId('index-contract-locked-banner')).toBeVisible({ timeout: 60_000 });
  await expectStrategyRadios(page, 'disabled');
  await openAdvancedChunkingControls(page);
  await expectAll(page, CHUNKING_AST_BRANCH, 'disabled');

  // The other chunking branches render behind the strategy value; switch it through
  // the real per-corpus config API (the UI correctly refuses while locked) so the
  // token/separator/markdown controls mount, still under the same locked index.
  try {
    await patchCorpusConfigSection(request, corpus!.corpusId, 'chunking', { chunking_strategy: 'recursive' });
    await gotoIndexingComponent(page, corpus!.corpusId, 'chunking');
    await expectAll(page, CHUNKING_RECURSIVE_BRANCH, 'disabled');

    await patchCorpusConfigSection(request, corpus!.corpusId, 'chunking', { chunking_strategy: 'markdown' });
    await gotoIndexingComponent(page, corpus!.corpusId, 'chunking');
    await expectAll(page, CHUNKING_MARKDOWN_BRANCH, 'disabled');
  } finally {
    await patchCorpusConfigSection(request, corpus!.corpusId, 'chunking', { chunking_strategy: 'ast' });
  }

  // Tokenization: chunk tokenizer, extraction ceilings and the sparse (bm25) contract.
  await gotoIndexingComponent(page, corpus!.corpusId, 'bm25');
  await expectAll(page, TOKENIZATION_CONTRACT_CONTROLS, 'disabled');

  // Embedding: the provider/backend identity is contract; batching is operational.
  await gotoIndexingComponent(page, corpus!.corpusId, 'embedding');
  await expectAll(page, ['embedding-backend'], 'disabled');
  await expectAll(page, ['embedding-batch-size'], 'enabled');

  // Graph: skip-dense removes the dense leg, so it is contract; the graph-leg
  // toggles are not covered by the backend index-contract lock and stay usable.
  await gotoIndexingComponent(page, corpus!.corpusId, 'enrichment');
  await expectAll(page, ['graph-skip-dense'], 'disabled');
  await expectAll(
    page,
    ['graph-indexing-enabled', 'graph-lexical-enabled', 'graph-store-chunk-embeddings', 'graph-build-code'],
    'enabled'
  );
});

test('without an index the same family stays fully editable', async ({ page }) => {
  expect(unindexedCorpus).not.toBeNull();
  await activateCorpusInBrowser(page, unindexedCorpus!.corpusId);

  await gotoIndexingComponent(page, unindexedCorpus!.corpusId, 'chunking');
  await expectStrategyRadios(page, 'enabled');
  await expect(page.getByTestId('index-contract-locked-banner')).toHaveCount(0);
  await openAdvancedChunkingControls(page);
  await expectAll(page, CHUNKING_AST_BRANCH, 'enabled');

  await gotoIndexingComponent(page, unindexedCorpus!.corpusId, 'bm25');
  await expectAll(page, TOKENIZATION_CONTRACT_CONTROLS, 'enabled');

  await gotoIndexingComponent(page, unindexedCorpus!.corpusId, 'embedding');
  await expectAll(page, ['embedding-backend', 'embedding-batch-size'], 'enabled');

  await gotoIndexingComponent(page, unindexedCorpus!.corpusId, 'enrichment');
  await expectAll(page, ['graph-skip-dense'], 'enabled');
});

test('Force reindex is the one honest unlock and re-locking re-disables the field', async ({ page }) => {
  expect(corpus).not.toBeNull();
  await activateCorpusInBrowser(page, corpus!.corpusId);
  await gotoIndexingComponent(page, corpus!.corpusId, 'chunking');

  const chunkSize = page.getByTestId('chunking-chunk-size');
  await expect(chunkSize).toBeVisible({ timeout: 60_000 });
  await expect(chunkSize).toBeDisabled();
  await expect(chunkSize).toHaveValue('1000');

  const forceToggle = page.getByTestId('force-reindex-toggle').locator('input[type="checkbox"]');
  await forceToggle.check();

  // Unlocked: real keyboard input works again (the repro's action, now legitimate).
  await expect(chunkSize).toBeEnabled();
  await expect(page.getByTestId('index-contract-locked-banner')).toHaveCount(0);
  await chunkSize.fill('1234');
  await expect(chunkSize).toHaveValue('1234');
  // Escape restores the committed value so this drive stages nothing.
  await chunkSize.press('Escape');
  await expect(chunkSize).toHaveValue('1000');

  await forceToggle.uncheck();
  await expect(chunkSize).toBeDisabled();
  await expect(page.getByTestId('index-contract-locked-banner')).toBeVisible();
});
