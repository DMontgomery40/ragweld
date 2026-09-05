// Second-wave findings on the Indexing and Data Quality subtabs, plus the shared confirmation
// dialog and the Synthetic Lab jump buttons those two subtabs render.
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { API_BASE, patchCorpusConfigSection, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(6 * 60 * 1000);

let corpus: ExhaustiveCorpus;

test.beforeAll(async ({ request }) => {
  corpus = await provisionExhaustiveCorpus(request);
});

test.afterAll(async ({ request }) => {
  await corpus?.dispose(request);
});

test('a dialog whose promise never settles does not block the next one', async ({ page }) => {
  // The confirmation helper used to chain every request onto the previous promise, so one
  // dialog that never settled wedged the chain and every later confirmation hung silently.
  // Driven as the module the app loads, in a real DOM, with no mocking.
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });

  const result = await page.evaluate(async () => {
    const mod = await import('/web/src/components/ui/confirmDialog.tsx');
    const confirmDialog = mod.confirmDialog as (o: Record<string, string>) => Promise<boolean>;

    let firstSettled: boolean | 'pending' = 'pending';
    // Deliberately never answered.
    const first = confirmDialog({ title: 'FIRST', message: 'first message' });
    void first.then((v) => {
      firstSettled = v;
    });
    await new Promise((r) => setTimeout(r, 100));
    const firstRendered = document.querySelectorAll('[data-testid="confirm-dialog"]').length;

    const second = confirmDialog({ title: 'SECOND', message: 'second message' });
    await new Promise((r) => setTimeout(r, 100));

    const dialogs = Array.from(document.querySelectorAll('[data-testid="confirm-dialog"]'));
    const visibleText = dialogs
      .map((d) => d.querySelector('[data-testid="confirm-dialog-message"]')?.textContent || '')
      .join('|');

    // The second dialog is reachable and answerable: this is what used to hang forever.
    (dialogs[dialogs.length - 1]?.querySelector('[data-testid="confirm-dialog-accept"]') as HTMLButtonElement)?.click();
    const secondAnswer = await Promise.race([
      second,
      new Promise<'HUNG'>((r) => setTimeout(() => r('HUNG'), 3000)),
    ]);
    const firstAnswer = await Promise.race([
      first,
      new Promise<'HUNG'>((r) => setTimeout(() => r('HUNG'), 3000)),
    ]);
    return { firstRendered, openDialogs: dialogs.length, visibleText, secondAnswer, firstAnswer, firstSettled };
  });

  expect(result.firstRendered).toBe(1);
  // One dialog at a time is preserved: the unanswered one is closed, not stacked.
  expect(result.openDialogs).toBe(1);
  expect(result.visibleText).toContain('second message');
  expect(result.secondAnswer, 'the second dialog hung behind an unsettled first').toBe(true);
  expect(result.firstAnswer, 'the superseded dialog must answer its caller, not leak').toBe(false);
});

test('the chunking strategies are a radiogroup that arrow keys move', async ({ page }) => {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}&component=chunking`, {
    waitUntil: 'domcontentloaded',
  });
  const group = page.getByTestId('chunking-strategy-group');
  await expect(group).toBeVisible();
  await expect(group).toHaveAttribute('role', 'radiogroup');

  const radios = group.getByRole('radio');
  await expect(radios).toHaveCount(9);
  const checked = group.locator('[aria-checked="true"]');
  await expect(checked).toHaveCount(1);
  const before = await checked.getAttribute('data-strategy');

  await checked.focus();
  await page.keyboard.press('ArrowRight');
  const afterEl = group.locator('[aria-checked="true"]');
  await expect(afterEl).toHaveCount(1);
  expect(await afterEl.getAttribute('data-strategy')).not.toBe(before);

  // Selection is conveyed by more than a border colour.
  await expect(afterEl).toContainText('\u25c9');
});

test('an idle tab stops hammering the index status endpoint', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', (req) => {
    if (/\/api\/index\//.test(req.url())) calls.push(req.url());
  });
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  await expect(page.getByTestId('index-now-button')).toBeVisible();
  await page.waitForTimeout(2000);
  const settled = calls.length;

  // 20 s with nothing running. At the old fixed 3 s cadence that was ~7 more status polls.
  await page.waitForTimeout(20_000);
  const idleCalls = calls.length - settled;
  expect(idleCalls, `idle tab made ${idleCalls} /api/index/* requests in 20s:\n${calls.slice(settled).join('\n')}`).toBeLessThanOrEqual(2);
});

test('the Synthetic Lab jump keeps the corpus and announces the preset on arrival', async ({ page }) => {
  await page.goto(`rag?subtab=data-quality&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });

  const generate = page.getByTestId('synthetic-generator-keywords');
  await expect(generate).toBeVisible();
  // Labelled as what it does, not like a viewer.
  await expect(generate).toContainText(/Generate keywords in Synthetic Lab/i);
  await expect(generate).toHaveAttribute('title', /preselected/i);

  await generate.click();
  await expect(page).toHaveURL(new RegExp(`corpus=${corpus.corpusId}`));
  await expect(page).toHaveURL(/synthetic_recipe=keywords/);

  const notice = page.getByTestId('synthetic-preset-notice');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(/keywords/i);
  await expect(notice).toContainText(/Nothing has run/i);

  // The destination URL is reloadable without losing the corpus.
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page).toHaveURL(new RegExp(`corpus=${corpus.corpusId}`));
});

test('both subtabs offer the same corpus list', async ({ page, request }) => {
  const options = async (subtab: string, testid: string | null) => {
    await page.goto(`rag?subtab=${subtab}&corpus=${encodeURIComponent(corpus.corpusId)}`, {
      waitUntil: 'domcontentloaded',
    });
    // Scoped to the subtab panel: the page header carries its own Theme Mode select.
    const select = testid ? page.getByTestId(testid) : page.locator('.subtab-panel select').first();
    await expect(select).toBeVisible();
    await expect.poll(async () => (await select.locator('option').allTextContents()).length).toBeGreaterThan(0);
    return (await select.locator('option').allInnerTexts()).sort();
  };

  const indexing = await options('indexing', 'target-corpus-select');
  const dataQuality = await options('data-quality', null);
  expect(dataQuality).toEqual(indexing);

  // And a corpus deleted while the tab is open disappears from both, not just one.
  const extra = await provisionExhaustiveCorpus(request);
  try {
    const withExtra = await options('indexing', 'target-corpus-select');
    expect(withExtra).toContain(extra.corpusId);
    expect(await options('data-quality', null)).toEqual(withExtra);
  } finally {
    await extra.dispose(request);
  }
  const afterDelete = await options('indexing', 'target-corpus-select');
  expect(afterDelete).not.toContain(extra.corpusId);
  expect(await options('data-quality', null)).toEqual(afterDelete);
});

test('no consumer can receive a warming estimate, and none opens a dialog on one', async ({ page }) => {
  // Two guarantees, checked against the real modules the app loads.
  //
  // 1. Every caller of the estimate goes through `indexingApi.estimate`, which polls until the
  //    estimator has measured something. The Get Started wizard did NOT guard for this and
  //    opened "Build indexes?" on a payload reading tokens 0 / chunks 0 / $0.0000.
  // 2. A non-ready payload carries `null` for every measured quantity, so a component that
  //    forgot to guard cannot render a zero — it fails to compile instead.
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });

  await page.evaluate(
    ([cid, cpath]) => {
      (window as unknown as { __corpus: string }).__corpus = cid;
      (window as unknown as { __path: string }).__path = cpath;
    },
    [corpus.corpusId, corpus.corpusPath] as const
  );

  const result = await page.evaluate(async () => {
    const api = await import('/web/src/api/indexing.ts');

    // Every payload the API layer hands out is measured. Ask a few times over: if the estimator
    // is cold this waits, and it still must never surface a warming one.
    const statuses: string[] = [];
    for (let i = 0; i < 3; i += 1) {
      const estimate = await (api.indexingApi.estimate as (r: unknown) => Promise<{ status: string }>)({
        corpus_id: (window as unknown as { __corpus: string }).__corpus,
        repo_path: (window as unknown as { __path: string }).__path,
        force_reindex: false,
      });
      statuses.push(estimate.status);
    }
    return { statuses, hasNotReadyError: typeof api.EstimateNotReadyError === 'function' };
  });

  expect(result.hasNotReadyError, 'a typed timeout error must exist for the deadline case').toBe(true);
  expect(result.statuses).toEqual(['ready', 'ready', 'ready']);
  // Nothing rendered a confirmation during any of that.
  await expect(page.getByTestId('confirm-dialog')).toHaveCount(0);
});

test('the api layer is the only place that names the estimate endpoint', () => {
  // A component could bypass every guarantee above by POSTing the endpoint itself, which is how
  // the wizard came to open a confirmation on an unmeasured payload. Naming the two components
  // we know about would not catch a third, so this walks the whole source tree: exactly one
  // file may contain the literal, and it is the one that polls until the estimate is measured.
  const root = path.resolve(process.cwd(), 'web/src');
  const sources: string[] = [];
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.tsx?$/.test(entry.name)) sources.push(full);
    }
  };
  walk(root);
  expect(sources.length, 'the walk found no sources; the path is wrong').toBeGreaterThan(50);

  const offenders = sources
    .filter((file) => readFileSync(file, 'utf-8').includes('/index/estimate'))
    .map((file) => path.relative(root, file))
    .sort();

  expect(offenders).toEqual(['api/indexing.ts']);
});

test('the Get Started wizard opens no dialog until the estimator has measured', async ({ page }) => {
  // The wizard is the surface the guard was missing on: it awaited the estimate and opened
  // "Build indexes?" on a non-ready answer. Driven here through the real wizard, on an API that
  // may still be warming, asserting the dialog appears ONLY with real numbers in it.
  const dialogSnapshots: string[] = [];
  await page.goto('start', { waitUntil: 'domcontentloaded' });

  await page.getByTestId('onboarding-dot-2').click();
  const picker = page.getByTestId('onboarding-existing-corpus');
  await expect(picker).toBeVisible();
  await picker.selectOption(corpus.corpusId);

  await page.getByTestId('onboarding-dot-3').click();
  const build = page.getByTestId('onboarding-index-start');
  await expect(build).toBeVisible();

  // Watch for a dialog appearing at any point during the wait.
  const watcher = setInterval(() => {
    void page
      .locator('[data-testid="confirm-dialog-message"]')
      .innerText()
      .then((text) => dialogSnapshots.push(text))
      .catch(() => undefined);
  }, 250);

  await build.click();
  const dialog = page.getByTestId('confirm-dialog');
  await expect(dialog).toBeVisible({ timeout: 150_000 });
  const message = await page.getByTestId('confirm-dialog-message').innerText();
  await expect(page.getByTestId('confirm-dialog-details')).not.toBeVisible();
  await dialog.getByText('Estimate details', { exact: true }).click();
  const details = await page.getByTestId('confirm-dialog-details').innerText();
  clearInterval(watcher);

  // Cancel: this spec must never start an index run.
  await page.getByTestId('confirm-dialog-cancel').click();
  await expect(dialog).toHaveCount(0);

  // Whatever was on screen, it was never a dialog built from an unmeasured estimate.
  for (const snapshot of [...dialogSnapshots, message]) {
    expect(snapshot, `a dialog showed an unmeasured estimate:\n${snapshot}`).not.toMatch(
      /Estimated tokens: 0\b|Estimated chunks: 0\b|Files: 0\b/
    );
  }
  expect(message).toContain('Index estimate for');
  expect(message).toMatch(/Chunks \(est\): [1-9][\d,]*/);
  expect(details).toMatch(/Estimated tokens: [1-9][\d,]*/);
  expect(details).toMatch(/Estimated chunks: [1-9][\d,]*/);
});

test('estimate consent keeps unknown totals and material uncertainty visible with details collapsed', async ({ page }) => {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`, {
    waitUntil: 'domcontentloaded',
  });
  const assumptions = [
    'Output baseline: 3 successful native requests from run fixture (status=error), with 2 processed chunks and 4 HTTP attempts. Requests are not unique-chunk coverage.',
    '1 dispatched attempts have no usable output sample; delayed native ingestion can change this forecast.',
    'Historical configuration differs; the sampled output baseline may not reflect the current prompt or reasoning settings.',
    'Semantic KG scenario $1.00–$7.00: observed output minimum/maximum. This is not a confidence interval or spending limit.',
    'Forecast assumes one request per chunk at catalog input/output rates; retries can alter charges.',
  ];
  // Exercise the real presentation component with explicit boundary scenarios.
  // The source estimate is measured by the real API; no endpoint is intercepted
  // and the dialog is never connected to an index start or paid request.
  for (const total of [null, 0, 0.000715]) {
    await page.evaluate(async ({ corpusId, corpusPath, total, assumptions }) => {
      const { indexingApi } = await import('/web/src/api/indexing.ts');
      const { indexEstimateConsent } = await import('/web/src/components/RAG/indexEstimateConsent.tsx');
      const { confirmDialog } = await import('/web/src/components/ui/confirmDialog.tsx');
      const measured = await indexingApi.estimate({ corpus_id: corpusId, repo_path: corpusPath });
      const scenario = {
        ...measured, embedding_cost_usd: 0, total_cost_usd: total,
        semantic_kg_cost_usd: total, estimated_seconds_semantic_kg: 1, assumptions,
      };
      void confirmDialog({
        title: 'Measured estimate presentation contract',
        ...indexEstimateConsent(scenario, { corpusName: corpusId }),
      });
    }, { corpusId: corpus.corpusId, corpusPath: corpus.corpusPath, total, assumptions });
    const dialog = page.getByTestId('confirm-dialog');
    await expect(dialog).toBeVisible();
    const message = page.getByTestId('confirm-dialog-message');
    await expect(message).toContainText(`Estimated cost: ${total == null ? 'Unknown' : total === 0 ? '$0.00' : '$0.000715'}`);
    if (total == null) await expect(message).toContainText('Semantic KG cost unknown');
    await expect(message).toContainText('failed or cancelled run');
    await expect(message).toContainText('partial output evidence');
    await expect(message).toContainText('historical settings differ');
    await expect(message).toContainText('not a spending limit');
    const details = page.getByTestId('confirm-dialog-details');
    await expect(details).not.toBeVisible();
    await expect(page.getByTestId('confirm-dialog-accept')).toBeFocused();
    await dialog.getByText('Estimate details', { exact: true }).click();
    await expect(details).toBeVisible();
    for (const assumption of assumptions) await expect(details).toContainText(assumption);
    await expect(details).toContainText('Time range:');
    await expect(details).toContainText('Estimated tokens:');
    await expect(details).toContainText('Embedding:');
    await page.getByTestId('confirm-dialog-cancel').click();
    await expect(dialog).toHaveCount(0);
  }
});

test('quick start reads the wizard corpus graph policy and requires semantic schema review', async ({ page, request }) => {
  const indexPosts: string[] = [];
  page.on('request', (req) => {
    if (req.method() === 'POST' && /\/api\/index(?:\?|$)/.test(req.url())) indexPosts.push(req.url());
  });
  try {
    for (const policy of ['off', 'code', 'semantic'] as const) {
      await patchCorpusConfigSection(request, corpus.corpusId, 'graph_indexing', {
        enabled: policy !== 'off', build_code_graph: policy === 'code',
      });
      await page.goto(`start?corpus=${encodeURIComponent(corpus.corpusId)}`, { waitUntil: 'domcontentloaded' });
      await page.getByTestId('onboarding-dot-2').click();
      await page.getByTestId('onboarding-existing-corpus').selectOption(corpus.corpusId);
      await page.getByTestId('onboarding-dot-3').click();
      const scopedConfig = page.waitForResponse((response) => {
        const url = new URL(response.url());
        return url.pathname.endsWith('/api/config') && url.searchParams.get('corpus_id') === corpus.corpusId;
      });
      await page.getByTestId('onboarding-index-start').click();
      expect((await scopedConfig).ok()).toBe(true);
      if (policy === 'semantic') {
        await expect(page.getByTestId('onboarding-index-error')).toContainText('Review the graph schema');
        await expect(page.getByTestId('confirm-dialog')).toHaveCount(0);
        const review = page.getByTestId('onboarding-review-graph');
        await expect(review).toHaveAttribute('href', `/web/rag?subtab=indexing&component=enrichment&corpus=${encodeURIComponent(corpus.corpusId)}`);
        await review.click();
        await expect(page.getByTestId('generate-graph-schema')).toBeVisible();
      } else {
        await expect(page.getByTestId('confirm-dialog')).toBeVisible({ timeout: 150_000 });
        await expect(page.getByTestId('onboarding-review-graph')).toHaveCount(0);
        await page.getByTestId('confirm-dialog-cancel').click();
      }
    }
    expect(indexPosts).toEqual([]);
  } finally {
    await patchCorpusConfigSection(request, corpus.corpusId, 'graph_indexing', { enabled: false, build_code_graph: false });
  }
});
