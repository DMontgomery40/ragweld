// Second-wave findings on the Indexing and Data Quality subtabs, plus the shared confirmation
// dialog and the Synthetic Lab jump buttons those two subtabs render.
import { readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { API_BASE, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';

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
  await expect(notice).toContainText(/keywords/);
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
  expect(message).toMatch(/Estimated tokens: [1-9][\d,]*/);
  expect(message).toMatch(/Estimated chunks: [1-9][\d,]*/);
});
