// Synthetic Lab promotion gating and failed-run recovery, against the real rendered app
// and a self-provisioned corpus. No request interception, no seeded fixtures: the spec
// registers an UNINDEXED corpus and starts a synthetic run, which fails deterministically
// ("no indexed source chunks") before any gateway call — a real, free, refused run.
//
// Proves the studios-lane fixes on a failed run:
//   M-12  a failed / un-evaluated run cannot be promoted — the four lineage alias buttons
//         are disabled and the block reason is shown (the server also refuses with a typed
//         409; see tests/api/test_synthetic_endpoints.py).
//   M-55  the failed run is not a dead end — it shows the failure reason and a Retry.
//   M-57  the quality-gate block states that the eval set is the run's own self-generated
//         questions (a self-consistency check, not external validation).
import { expect, test } from '@playwright/test';
import { activateCorpusInBrowser, API_BASE, EXHAUSTIVE_CHAT_MODEL, provisionExhaustiveCorpus } from './corpus_fixture';

const ALIASES = ['baseline', 'canary', 'current', 'promoted'];

test('Synthetic Lab: a failed run cannot be promoted and is not a dead end', async ({ page, request, baseURL }) => {
  test.setTimeout(4 * 60 * 1000);
  const pageErrors: string[] = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));

  // Unindexed on purpose: a synthetic run over a corpus with no indexed chunks fails
  // closed before any generation, so this is deterministic and costs nothing.
  const corpus = await provisionExhaustiveCorpus(request, { index: false });
  try {
    const started = await request.post(`${API_BASE}/synthetic/run/start`, {
      data: {
        corpus_id: corpus.corpusId,
        provider: 'grounded_qa',
        recipe: 'eval_dataset',
        generator_model: `litellm:${EXHAUSTIVE_CHAT_MODEL}`,
        judge_model: `litellm:${EXHAUSTIVE_CHAT_MODEL}`,
        max_source_chunks: 10,
        max_pairs: 10,
        pairs_per_source: 1,
      },
    });
    expect(started.ok(), `start synthetic run -> ${started.status()}`).toBeTruthy();
    const runId = String((await started.json()).run_id || '');
    expect(runId).not.toEqual('');

    // Wait for the run to reach its terminal (failed) state.
    await expect
      .poll(
        async () => {
          const r = await request.get(`${API_BASE}/synthetic/run/${encodeURIComponent(runId)}`);
          return r.ok() ? String((await r.json()).status) : 'unknown';
        },
        { timeout: 90_000, intervals: [500] },
      )
      .toBe('failed');

    await activateCorpusInBrowser(page, corpus.corpusId);
    await page.goto(new URL(`rag?subtab=synthetic&corpus=${encodeURIComponent(corpus.corpusId)}`, baseURL).toString());
    await expect(page.getByTestId('synthetic-lab-subtab')).toBeVisible({ timeout: 60_000 });

    // Select the failed run in the runs table.
    const row = page.getByText(runId, { exact: true });
    await expect(row).toBeVisible({ timeout: 30_000 });
    await row.click();

    // M-55: the failed run shows its reason and a Retry — not just status=failed.
    const failure = page.getByTestId('synthetic-run-failure');
    await expect(failure).toBeVisible();
    await expect(failure).toContainText(/no indexed source chunks/i);
    await expect(page.getByTestId('synthetic-retry')).toBeVisible();

    // M-12: the run attached a bundle, so the four alias buttons render — but every one is
    // disabled and the block reason is shown, because a failed run may not be promoted.
    await expect(page.getByTestId('lineage-promotion-blocked')).toBeVisible();
    await expect(page.getByTestId('lineage-promotion-blocked')).toContainText(/failed|completed run/i);
    for (const a of ALIASES) {
      await expect(page.getByTestId(`lineage-set-${a}`), `${a} disabled on a failed run`).toBeDisabled();
    }

    // M-56 (id half): the bundle id is copyable via the shared TruncatedId control
    // (the lane's inline IdValue was reconciled away in favor of legibility's component).
    await expect(page.getByTestId('lineage-copy-current-bundle')).toBeVisible();

    // M-57: the quality-gate block carries the self-generated caveat regardless of verdict.
    const gate = page.locator('.studio-callout', { hasText: 'Quality Gate' });
    await expect(gate).toContainText(/self-generated|self-consistency/i);

    expect(pageErrors, `uncaught page errors: ${pageErrors.join(' | ')}`).toEqual([]);
  } finally {
    await corpus.dispose(request);
  }
});
