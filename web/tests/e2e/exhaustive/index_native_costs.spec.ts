/** Real saved run records, API reconciliation, and HTTP native ledger; no model calls. */
import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page, type Request } from '@playwright/test';
import type { GraphSchemaProposal, GraphSchemaProposalFailureResponse, GraphSchemaProposalState, IndexRunSummary } from '../../../src/types/generated';
import { API_BASE, patchCorpusConfigSection, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';
import { assertPrivateNativeConfig, assertPrivateNativeTargets, privateNativeChildEnv, type NativeFixtureConfig } from './native_cost_fixture';

// Private suites use different API/store instances. Normal exhaustive collection
// can list this suite without running it against the operator's runtime.
const nativeFixtureEnabled = process.env.NATIVE_COST_FIXTURE === '1';
if (nativeFixtureEnabled) assertPrivateNativeTargets(process.env, process.cwd());
if (!nativeFixtureEnabled && /^(1|true|yes|on)$/i.test(process.env.RAGWELD_STRICT_INTEGRATION || '')) {
  throw new Error('Strict native cost acceptance requires NATIVE_COST_FIXTURE=1');
}
test.skip(!nativeFixtureEnabled, 'Requires the dedicated private native cost API/store fixture');

const evidence = JSON.parse(fs.readFileSync(path.resolve('tests/fixtures/native_spend_rows.json'), 'utf8'));
const ledgers = new Map<string, { rows: unknown[]; reads: number; delayMs: number; active: number; maximumActive: number }>();
let gateway: http.Server;
let gatewayUrl: string;
let proposalScenario: 'valid' | 'wrong_shape' = 'valid';
let corpus: ExhaustiveCorpus;
let neighbor: ExhaustiveCorpus;
let ordinal = 0;
const runDirs: string[] = [];

function saveGraphOutcomeRun(historical: boolean): IndexRunSummary {
  expect(process.cwd().startsWith('/var/tmp/')).toBeTruthy();
  const runId = `${Date.now().toString(16)}${(++ordinal).toString(16)}`.padStart(32, '0');
  const started = new Date(Date.now() - 60_000 + ordinal).toISOString();
  const run: IndexRunSummary = {
    run_id: runId, corpus_id: corpus.corpusId, status: 'error', started_at: started,
    completed_at: started, graph_promotable: false,
    error: 'Replacement extraction failed; the previous generation remains active.',
    graph_metadata: {
      policy: 'semantic',
      extraction: {
        outcome_version: historical ? 'whole_file_v0' : 'checkpoint_v1',
        progress_owner_run_id: historical ? null : runId, progress_sequence: historical ? 0 : 14,
        selected_chunks: historical ? 1002 : 5, attempted_chunks: historical ? 1002 : 3,
        succeeded_chunks: historical ? 0 : 2, failed_chunks: historical ? 1002 : 1,
        reused_chunks: historical ? null : 1, cancelled_chunks: historical ? null : 1,
        unfinished_chunks: historical ? null : 1, truncated_chunks: 0,
        extracted_entities: 4, semantic_relationships: 2, from_chunk_relationships: 4,
        worker_seconds: historical ? 0 : 12,
      },
      resolution: { candidate_nodes: 0, resolved_nodes: 0, merged_nodes: 0, unresolved_duplicate_groups: 0 },
    },
  };
  const dir = path.resolve('data/index_runs', corpus.corpusId, run.run_id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(run));
  runDirs.push(dir);
  return run;
}

for (const historical of [false, true]) {
  test(`graph outcomes retain ${historical ? 'historical uncertainty' : 'durable reuse and unfinished work'} after reload with details closed`, async ({ page }) => {
    const run = saveGraphOutcomeRun(historical);
    for (let visit = 0; visit < 2; visit += 1) {
      if (visit === 0) await openRun(page, run);
      else await page.reload();
      const details = page.getByTestId('graph-generation-details');
      await expect(details).toBeAttached();
      await expect(details).toHaveJSProperty('open', false);
      await expect(page.getByText('Not published', { exact: true })).toBeVisible();
      await expect(page.getByTestId('graph-selected-chunks')).not.toBeVisible();
      await details.locator('> summary').click();
      if (historical) {
        await expect(page.getByTestId('graph-selected-chunks')).toContainText('1,002');
        await expect(page.getByTestId('graph-historical-outcomes')).toContainText('Detailed chunk outcomes unavailable');
        await expect(page.getByTestId('graph-historical-outcomes')).toContainText('not measured dispatches');
        await expect(page.getByTestId('graph-reused-chunks')).toHaveCount(0);
      } else {
        for (const [id, text] of [
          ['graph-selected-chunks', 'Selected chunks: 5'], ['graph-attempted-chunks', 'Attempted (admitted): 3'],
          ['graph-reusable-chunks', 'Reusable successes: 2'], ['graph-reused-chunks', 'Reused: 1'],
          ['graph-failed-chunks', 'Failed: 1'], ['graph-cancelled-chunks', 'Cancelled: 1'],
          ['graph-unfinished-chunks', 'Unfinished: 1'],
        ]) await expect(page.getByTestId(id)).toHaveText(text);
      }
    }
  });
}

function saveRun(
  corpusId: string,
  count: number,
  status: IndexRunSummary['status'] = 'complete',
  legacy = false,
  ownerInterrupted = false,
): IndexRunSummary {
  expect(process.cwd().startsWith('/var/tmp/'), 'saved fixtures require a private remote overlay').toBeTruthy();
  const started = new Date(Date.now() - 60_000 + ordinal++).toISOString();
  const run: IndexRunSummary = {
    run_id: `native-ui-${Date.now()}-${ordinal}`, corpus_id: corpusId, status,
    started_at: started, completed_at: new Date().toISOString(), progress: status === 'complete' ? 1 : 0.5,
    total_files: status === 'complete' ? 2 : 0, total_chunks: status === 'complete' ? 4 : 0,
    accounting: legacy ? null : {
      session_id: '', corpus_id: corpusId, started_at: started, ended_at: new Date().toISOString(),
      gateway_base_url: gatewayUrl,
      config_fingerprint: 'a'.repeat(64), models: { semantic_kg: 'fixture-native' },
      census: {}, owner_interrupted: ownerInterrupted,
      coverage_complete: !ownerInterrupted, gateway_attempt_policy_verified: true,
      processed_files: 2, processed_chunks: 4, processed_tokens: 72,
      estimate: { captured_at: started, total_usd: 0.75, embedding_usd: 0, semantic_kg_usd: 0.75, figure_description_usd: 0, estimated_chunks: 10, detail: 'Saved before this attempt; actual work can differ.' },
    },
  };
  if (run.accounting) {
    run.accounting.session_id = run.run_id;
    run.accounting.census = { semantic_kg: {
      identity: { session_id: run.run_id, corpus_id: corpusId, lane: 'semantic_kg' },
      revision: 2 * count + 1, started_requests: count, completed_requests: count,
      failed_requests: 0, uncertain_requests: 0, inflight: 0, active_producers: 0,
      owner_finished: !ownerInterrupted, dispatch_enabled: false,
      state: ownerInterrupted ? 'interrupted' : 'closed',
    } };
  }
  const dir = path.resolve('data/index_runs', corpusId, run.run_id);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify(run));
  runDirs.push(dir);
  ledgers.set(run.run_id, { rows: [], reads: 0, delayMs: 0, active: 0, maximumActive: 0 });
  return run;
}

function publishRows(run: IndexRunSummary, indexes: number[]) {
  ledgers.get(run.run_id)!.rows = indexes.map((index) => {
    const row = structuredClone(evidence.listing.data[index]);
    row.session_id = run.run_id;
    row.startTime = run.started_at;
    row.endTime = run.completed_at;
    row.metadata.spend_logs_metadata = { run_id: run.run_id, corpus_id: run.corpus_id, lane: 'semantic_kg' };
    return row;
  });
}

async function openRun(page: Page, run: IndexRunSummary) {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(run.corpus_id)}`);
  const panel = page.getByTestId('index-run-costs').filter({ has: page.getByText('Run cost', { exact: true }) });
  await expect(panel).toHaveAttribute('data-run-id', run.run_id);
  await expect(panel.getByRole('button', { name: 'Refresh cost', exact: true })).toBeEnabled();
  await expectCostsCollapsed(panel);
  return panel;
}

async function expectCostsCollapsed(panel: Locator) {
  await expect(panel.getByTestId('index-cost-details')).toHaveJSProperty('open', false);
  await expect(panel.getByTestId('index-cost-estimate')).not.toBeVisible();
  await expect(panel.getByTestId('index-cost-coverage')).not.toBeVisible();
  await expect(panel.getByTestId('index-cost-denominator')).not.toBeVisible();
  expect(await panel.innerText()).not.toMatch(/Frozen estimate|admitted requests|Automatic checks finished/);
}

async function expandCosts(panel: Locator) {
  await panel.getByTestId('index-cost-details').locator('> summary').click();
  await expect(panel.getByTestId('index-cost-details')).toHaveJSProperty('open', true);
}

async function assertFixtureIsolation(request: APIRequestContext, corpusId: string): Promise<void> {
  const response = await request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpusId)}`);
  expect(response.ok(), 'fixture config must resolve before browser work').toBeTruthy();
  assertPrivateNativeConfig(await response.json() as NativeFixtureConfig, gatewayUrl);
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async ({ request }) => {
  // Resolve the application's global config before provisioning changes its state.
  const browserApi = `${new URL(process.env.PLAYWRIGHT_WEB_BASE_URL!).origin}/api`;
  for (const endpoint of [API_BASE, browserApi]) {
    const config = await request.get(`${endpoint}/config`);
    expect(config.ok(), 'private API and browser proxy config must resolve before setup').toBeTruthy();
    assertPrivateNativeConfig(await config.json() as NativeFixtureConfig);
  }
  gateway = http.createServer((req, res) => {
    const url = new URL(req.url!, 'http://127.0.0.1');
    if (req.method === 'GET' && url.pathname === '/spend/logs/v2') {
      const ledger = ledgers.get(url.searchParams.get('session_id')!);
      if (!ledger) { res.writeHead(404).end(); return; }
      ledger.reads += 1;
      ledger.active += 1;
      ledger.maximumActive = Math.max(ledger.maximumActive, ledger.active);
      const rows = structuredClone(ledger.rows);
      setTimeout(() => {
        res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({ data: rows, total: rows.length, page: 1, page_size: 100, total_pages: rows.length ? 1 : 0, total_is_capped: false }));
        ledger.active -= 1;
      }, ledger.delayMs);
      return;
    }
    if (req.method === 'GET' && url.pathname === '/v1/models') {
      res.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify({
        object: 'list',
        data: [{ id: 'openai.gpt-5.6-sol', object: 'model', created: 1, owned_by: 'native-cost-fixture' }],
      }));
      return;
    }
    if (req.method === 'POST' && url.pathname === '/v1/chat/completions') {
      let requestBody = '';
      req.setEncoding('utf8');
      req.on('data', (chunk) => { requestBody += chunk; });
      req.on('end', () => {
        JSON.parse(requestBody);
        const runId = String(req.headers['x-litellm-session-id'] || '');
        const attribution = JSON.parse(String(req.headers['x-litellm-spend-logs-metadata'] || '{}'));
        const row = structuredClone(evidence.listing.data[0]);
        const now = new Date().toISOString();
        const requestId = `schema-proposal-${runId}-${Date.now()}`;
        row.request_id = requestId;
        row.session_id = runId;
        row.startTime = now;
        row.endTime = now;
        row.metadata.litellm_call_id = requestId;
        row.metadata.spend_logs_metadata = attribution;
        ledgers.set(runId, { rows: [row], reads: 0, delayMs: 0, active: 0, maximumActive: 0 });
        const schema = proposalScenario === 'valid'
          ? {
              node_types: [
                { label: 'Mission', description: 'A named domain entity', properties: [{ name: 'name', type: 'STRING', description: 'Entity name' }] },
                { label: 'Instrument', description: 'Equipment used by a mission', properties: [{ name: 'name', type: 'STRING', description: 'Equipment name' }] },
              ],
              relationship_types: [{ label: 'USES', description: 'Operates equipment', properties: [] }],
              patterns: [{ source: 'Mission', relationship: 'USES', target: 'Instrument' }],
              constraints: [],
            }
          : { node_types: 'PRIVATE PROVIDER DETAIL' };
        res.writeHead(200, { 'Content-Type': 'application/json', 'x-litellm-response-cost': '0.0123' }).end(JSON.stringify({
          id: requestId,
          object: 'chat.completion',
          created: 1,
          model: 'openai.gpt-5.6-sol',
          choices: [{ index: 0, finish_reason: 'stop', message: { role: 'assistant', content: JSON.stringify(schema), refusal: null } }],
          usage: { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18 },
        }));
      });
      return;
    }
    // Any request outside the spend ledger, catalog, or proposal endpoint fails.
    res.writeHead(405).end();
  });
  await new Promise<void>((resolve) => gateway.listen(0, '127.0.0.1', resolve));
  gatewayUrl = `http://127.0.0.1:${(gateway.address() as { port: number }).port}`;
  corpus = await provisionExhaustiveCorpus(request);
  neighbor = await provisionExhaustiveCorpus(request);
  for (const item of [corpus, neighbor]) {
    await patchCorpusConfigSection(request, item.corpusId, 'chat', { litellm: { base_url: `${gatewayUrl}/v1` } });
  }
  await assertFixtureIsolation(request, corpus.corpusId);
  await assertFixtureIsolation(request, neighbor.corpusId);
});

test.afterAll(async ({ request }) => {
  for (const dir of runDirs) fs.rmSync(dir, { recursive: true, force: true });
  await corpus?.dispose(request);
  await neighbor?.dispose(request);
  gateway?.closeAllConnections();
  await new Promise<void>((resolve) => gateway ? gateway.close(() => resolve()) : resolve());
});

test('saved estimates, native evidence, cache zero, missing prices, and legacy absence stay distinct', async ({ page, request }) => {
  const variants = [
    { rows: [0, 2, 6], count: 3, state: 'complete', native: '$0.01231675', readable: '$0.01 recorded', cached: 1, unmeasured: 0 },
    { rows: [6], count: 1, state: 'complete', native: '$0.0000', readable: '$0.00 recorded', cached: 1, unmeasured: 0 },
    { rows: [0, 3], count: 3, state: 'incomplete', native: '$0.0123', readable: '$0.01 recorded', cached: 0, unmeasured: 1 },
    { rows: [2], count: 1, state: 'complete', native: '$0.00001675', readable: '<$0.01 recorded', cached: 0, unmeasured: 0 },
  ];
  for (const [index, variant] of variants.entries()) {
    const run = saveRun(corpus.corpusId, variant.count, index === 2 ? 'cancelled' : index === 3 ? 'error' : 'complete');
    publishRows(run, variant.rows);
    const refreshed = await request.post(`${API_BASE}/index/${corpus.corpusId}/runs/${run.run_id}/costs/reconcile`);
    expect(refreshed.ok()).toBeTruthy();
    const saved = await refreshed.json() as IndexRunSummary;
    expect(saved.accounting?.costs?.state, saved.accounting?.reconciliation_error ?? 'native reconciliation').toBe(variant.state);
    const panel = await openRun(page, run);
    await expect(page.getByTestId('index-run-status-pill')).toHaveText(index === 2 ? 'Cancelled' : index === 3 ? 'Failed' : 'Complete');
    await expect(panel.getByRole('status')).toBeVisible();
    await expect(panel.getByTestId('index-cost-state')).toHaveText(variant.state === 'complete' ? 'Complete' : 'Incomplete');
    await expect(panel.getByTestId('index-cost-amount')).toHaveText(variant.readable);
    if (index === 0 || index === 2) {
      await panel.screenshot({ path: test.info().outputPath(index === 0 ? 'main-cost-collapsed.png' : 'incomplete-cost-collapsed.png') });
    }
    await expandCosts(panel);
    await expect(panel.getByTestId('index-cost-estimate')).toBeVisible();
    await expect(panel.getByTestId('index-cost-estimate')).toContainText('Frozen estimate: $0.7500');
    await expect(panel.getByTestId('index-cost-native')).toContainText(variant.native);
    await expect(panel.getByTestId('index-cost-coverage')).toContainText(`${variant.cached} cached · ${variant.unmeasured} unmeasured`);
    await expect(panel.getByTestId('index-cost-denominator')).toContainText('4 chunks processed · 2 files · 72 tokens');
    if (index === 0) {
      await expect(panel.getByTestId('index-cost-provider')).toHaveText('$0.0123');
      await expect(panel.getByTestId('index-cost-calculated')).toHaveText('$0.00001675');
      await expect(panel.getByTestId('index-cost-denominator')).toContainText('$0.0030791875 native logged per processed chunk');
      await panel.screenshot({ path: test.info().outputPath('main-cost-details.png') });
    } else if (index === 2) {
      await expect(panel.getByTestId('index-cost-native')).toContainText('partial accounting');
      await expect(panel.getByTestId('index-cost-denominator')).toContainText('Per-chunk cost unavailable');
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: test.info().outputPath('incomplete-native-accounting.png') });
    }
  }
  const legacy = saveRun(corpus.corpusId, 0, 'complete', true);
  const panel = await openRun(page, legacy);
  await expect(panel).toContainText('Unavailable');
  await expect(panel.getByTestId('index-cost-amount')).toHaveCount(0);
  await expect(panel).not.toContainText('$0');
});

test('one run settles after native ingestion and incomplete follow-up stops until a manual retry', async ({ page }) => {
  const delayed = saveRun(corpus.corpusId, 1);
  const panel = await openRun(page, delayed);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Pending');
  await expect.poll(() => ledgers.get(delayed.run_id)!.reads).toBe(1);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Incomplete');
  publishRows(delayed, [0]);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Complete');
  expect(ledgers.get(delayed.run_id)!.reads).toBe(2);

  const absent = saveRun(corpus.corpusId, 1);
  const missing = await openRun(page, absent);
  await expect(missing.getByTestId('index-cost-refresh-paused')).toHaveCount(1, { timeout: 45_000 });
  await expectCostsCollapsed(missing);
  await expandCosts(missing);
  await expect(missing.getByTestId('index-cost-refresh-paused')).toBeVisible();
  expect(ledgers.get(absent.run_id)!.reads).toBe(5);
  // Browser time can advance here: all five actual HTTP reads have settled.
  await page.clock.install();
  await page.clock.fastForward(60_000);
  expect(ledgers.get(absent.run_id)!.reads).toBe(5);
  publishRows(absent, [0]);
  await missing.getByRole('button', { name: 'Refresh cost', exact: true }).click();
  await expect(missing.getByTestId('index-cost-state')).toHaveText('Complete');
  await expect(missing.getByTestId('index-cost-refresh-paused')).toHaveCount(0);
  expect(ledgers.get(absent.run_id)!.reads).toBe(6);
  expect(ledgers.get(absent.run_id)!.maximumActive).toBe(1);

  const interrupted = saveRun(corpus.corpusId, 1, 'indexing', false, true);
  const interruptedPanel = await openRun(page, interrupted);
  await expect(interruptedPanel.getByTestId('index-cost-state')).toHaveText('Incomplete · Interrupted');
  await expect(interruptedPanel.getByTestId('index-cost-owner-interrupted')).not.toBeVisible();
  await expandCosts(interruptedPanel);
  await expect(interruptedPanel.getByTestId('index-cost-owner-interrupted')).toBeVisible();
  for (const [attempt, delay] of [1000, 2000, 4000, 8000, 16000].entries()) {
    await page.clock.fastForward(delay);
    await expect.poll(() => ledgers.get(interrupted.run_id)!.reads).toBe(attempt + 1);
  }
  await expect(interruptedPanel.getByTestId('index-cost-refresh-paused')).toBeVisible();
  await page.clock.fastForward(60_000);
  expect(ledgers.get(interrupted.run_id)!.reads).toBe(5);
});

test('a held reconciliation cannot publish its amounts after a corpus change', async ({ page }) => {
  const held = saveRun(corpus.corpusId, 1);
  publishRows(held, [0]);
  ledgers.get(held.run_id)!.delayMs = 1800;
  await openRun(page, held);
  await expect.poll(() => ledgers.get(held.run_id)!.active).toBe(1);
  const other = saveRun(neighbor.corpusId, 0, 'complete', true);
  const panel = await openRun(page, other);
  await expect.poll(() => ledgers.get(held.run_id)!.active).toBe(0);
  await expect(panel).toHaveAttribute('data-run-id', other.run_id);
  await expect(panel).toContainText('Unavailable');
  await expect(panel).not.toContainText('$0.0123');
});

test('a delayed latest-run response cannot replace the newly selected corpus', async ({ page }) => {
  const first = saveRun(corpus.corpusId, 0, 'complete', true);
  const second = saveRun(neighbor.corpusId, 0, 'complete', true);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let intercepted!: () => void;
  const requestSeen = new Promise<void>((resolve) => { intercepted = resolve; });
  let held = false;
  await page.route('**/api/index/**/runs/latest**', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!held && pathname === `/api/index/${first.corpus_id}/runs/latest`) {
      held = true;
      intercepted();
      await gate;
    }
    await route.continue();
  });
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(first.corpus_id)}`);
  await requestSeen;
  await page.getByTestId('target-corpus-select').selectOption(second.corpus_id);
  const panel = page.getByTestId('index-run-costs').filter({ has: page.getByText('Run cost', { exact: true }) });
  await expect(panel).toHaveAttribute('data-run-id', second.run_id);
  const delayedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `/api/index/${first.corpus_id}/runs/latest`);
  release();
  await delayedResponse;
  await page.waitForTimeout(250);
  await expect(panel).toHaveAttribute('data-run-id', second.run_id);
});

test('Dashboard refreshes accounting for the same saved run without causing ledger reads', async ({ page, request }) => {
  const run = saveRun(corpus.corpusId, 1);
  await page.clock.install();
  await page.goto(`dashboard?subtab=system&corpus=${encodeURIComponent(corpus.corpusId)}`);
  const row = page.getByTestId(`dash-recent-run-${corpus.corpusId}`);
  await expect(row).toContainText('Pending');
  await expectCostsCollapsed(row);
  expect(ledgers.get(run.run_id)!.reads).toBe(0);
  publishRows(run, [0]);
  const reconciled = await request.post(`${API_BASE}/index/${corpus.corpusId}/runs/${run.run_id}/costs/reconcile`);
  expect(reconciled.ok()).toBeTruthy();
  await page.clock.fastForward(31_000);
  await expect(row).toContainText('$0.01 recorded · Complete');
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  await expectCostsCollapsed(row);
  await expandCosts(row);
  await expect(row.getByTestId('index-cost-estimate')).toContainText('Frozen estimate: $0.7500');
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('dashboard-native-accounting.png') });
  await page.reload();
  await expect(row).toContainText('$0.01 recorded · Complete');
  await expectCostsCollapsed(row);
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
});

for (const reverse of [false, true]) {
  test(`Dashboard ignores a delayed status response across corpus switch ${reverse ? 'B to A' : 'A to B'}`, async ({ page }) => {
  const first = reverse ? neighbor : corpus;
  const second = reverse ? corpus : neighbor;
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let intercepted!: () => void;
  const requestSeen = new Promise<void>((resolve) => { intercepted = resolve; });
  let held = false;
  await page.route('**/api/index/status**', async (route) => {
    const url = new URL(route.request().url());
    if (!held && url.searchParams.get('corpus_id') === first.corpusId) {
      held = true;
      intercepted();
      await gate;
    }
    await route.continue();
  });
  await page.goto(`dashboard?subtab=system&corpus=${encodeURIComponent(first.corpusId)}`);
  await requestSeen;
  await page.locator('#dash-change-repo').click();
  await page.getByTestId(`corpus-select-${second.corpusId}`).click();
  const panel = page.locator('[data-tooltip="DASHBOARD_INDEX_PANEL"]');
  await expect(panel).toContainText(second.corpusId);
  const delayedResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/index/status' && url.searchParams.get('corpus_id') === first.corpusId;
  });
  release();
  await delayedResponse;
  await page.waitForTimeout(250);
  await expect(panel).toContainText(second.corpusId);
  await expect(panel).not.toContainText(first.corpusId);
});

}

test('schema accounting survives actual missing history, read-only restore, and delayed older attempts', async ({ page }) => {
  const proposalPath = `/api/index/${corpus.corpusId}/graph-schema/proposal`;
  const historyPath = `/api/index/${corpus.corpusId}/runs/latest`;
  const runRoot = path.resolve('data/index_runs', corpus.corpusId);
  expect(runRoot.startsWith('/var/tmp/')).toBeTruthy();
  let schemaPosts = 0;
  const activeCostReads = new Set<Request>();
  page.on('request', (request) => {
    if (new URL(request.url()).pathname === proposalPath && request.method() === 'POST') schemaPosts += 1;
    if (new URL(request.url()).pathname.startsWith(`/api/index/${corpus.corpusId}/runs/`)
      && new URL(request.url()).pathname !== historyPath) activeCostReads.add(request);
  });
  page.on('requestfinished', (request) => { activeCostReads.delete(request); });
  page.on('requestfailed', (request) => { activeCostReads.delete(request); });

  // Mutate only this private corpus's persisted, typed proposal. API responses
  // continue to come from the actual backend, including optional old timestamps.
  function updateSavedProposalTiming(fields: { created_at?: string; accounting_started_at?: null }): void {
    expect(process.env.RAGWELD_TEST_CONFIG_PATH, 'set this to the private API configuration file').toBeTruthy();
    execFileSync(process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python', ['-c', `
import asyncio, json, os, sys
from pathlib import Path
from urllib.parse import urlparse
from server.db.postgres import PostgresClient
from server.models.index import GraphSchemaProposal

async def main():
    assert Path.cwd().resolve().is_relative_to(Path('/var/tmp'))
    raw = json.loads(Path(os.environ['RAGWELD_TEST_CONFIG_PATH']).read_text())
    dsn = raw['indexing']['postgres_url']
    target = urlparse(dsn)
    assert target.hostname == '127.0.0.1' and target.port == 55439
    assert target.path == '/tribrid_test'
    fields = json.loads(sys.argv[2])
    assert set(fields) <= {'created_at', 'accounting_started_at'}
    pg = PostgresClient(dsn, schema_mode='control')
    assert pg._resolve_dsn(dsn) == dsn, 'Private fixture database overrides are forbidden'
    await pg.connect()
    try:
        saved = await pg.get_graph_schema_proposal(sys.argv[1])
        assert saved is not None and saved.corpus_id == sys.argv[1]
        payload = saved.model_dump(mode='json', by_alias=True)
        payload.update(fields)
        await pg.set_graph_schema_proposal(sys.argv[1], GraphSchemaProposal.model_validate(payload))
    finally:
        await pg.disconnect()

asyncio.run(main())
`, corpus.corpusId, JSON.stringify(fields)], {
      cwd: process.cwd(), env: privateNativeChildEnv(process.env, process.cwd()), stdio: 'pipe',
    });
  }

  let historyBarrier: Promise<void> | null = null;
  let holdNextHistory = false;
  let releaseHistory!: () => void;
  const historyRelease = new Promise<void>((resolve) => { releaseHistory = resolve; });
  let captureHistory!: (run: IndexRunSummary) => void;
  const historicalRun = new Promise<IndexRunSummary>((resolve) => { captureHistory = resolve; });
  let historyFinished!: () => void;
  const historyCompletion = new Promise<void>((resolve) => { historyFinished = resolve; });
  let heldHistoryClaimed = false;
  await page.route('**/api/index/**/runs/**', async (route) => {
    const url = new URL(route.request().url());
    const isSchemaHistory = url.pathname === historyPath && url.searchParams.get('run_kind') === 'schema_proposal';
    if (!isSchemaHistory) {
      // Keep browser cost reads from starting writers while this fixture moves
      // settled summaries. Restore every file before letting those reads proceed.
      if (historyBarrier) await historyBarrier;
      await route.continue();
      return;
    }
    if (historyBarrier) {
      const moved: Array<{ original: string; held: string }> = [];
      try {
        for (const entry of fs.readdirSync(runRoot, { withFileTypes: true })) {
          if (!entry.isDirectory()) continue;
          const original = path.join(runRoot, entry.name, 'summary.json');
          if (!fs.existsSync(original)) continue;
          const summary = JSON.parse(fs.readFileSync(original, 'utf8')) as IndexRunSummary;
          if (summary.run_kind !== 'schema_proposal') continue;
          expect(summary.corpus_id).toBe(corpus.corpusId);
          expect(summary.run_id).toBe(entry.name);
          expect(['complete', 'error', 'cancelled']).toContain(summary.status);
          for (const census of Object.values(summary.accounting?.census ?? {})) {
            expect(census.inflight).toBe(0);
            expect(census.active_producers).toBe(0);
            expect(census.owner_finished).toBe(true);
          }
          const held = path.join(runRoot, entry.name, 'summary.held-by-browser-fixture');
          expect(fs.existsSync(held)).toBe(false);
          fs.renameSync(original, held);
          moved.push({ original, held });
        }
        expect(moved.length).toBeGreaterThan(0);
        const absent = await route.fetch();
        expect(absent.status()).toBe(404);
        // Forward this authentic absence only after every saved run is back.
        while (moved.length) {
          const { original, held } = moved[0];
          expect(fs.existsSync(original), 'no writer may replace a held settled summary').toBe(false);
          fs.renameSync(held, original);
          moved.shift();
        }
        await route.fulfill({ response: absent });
      } finally {
        for (const { original, held } of moved) {
          if (fs.existsSync(original)) throw new Error(`Unexpected writer; preserved held fixture summary at ${held}`);
          fs.renameSync(held, original);
        }
      }
      return;
    }
    if (holdNextHistory) {
      holdNextHistory = false;
      heldHistoryClaimed = true;
      try {
        const original = await route.fetch();
        expect(original.status()).toBe(200);
        captureHistory(await original.json() as IndexRunSummary);
        await historyRelease;
        await route.fulfill({ response: original });
      } finally {
        historyFinished();
      }
      return;
    }
    await route.continue();
  });

  async function withMissingHistory(action: () => Promise<GraphSchemaProposal>): Promise<GraphSchemaProposal> {
    await expect.poll(() => activeCostReads.size, { message: 'prior native reconciliation must drain before holding summaries' }).toBe(0);
    let unblock!: () => void;
    historyBarrier = new Promise<void>((resolve) => { unblock = resolve; });
    const absent = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === historyPath && url.searchParams.get('run_kind') === 'schema_proposal'
        && response.status() === 404;
    });
    try {
      const [result] = await Promise.all([action(), absent]);
      return result;
    } finally {
      historyBarrier = null;
      unblock();
    }
  }

  async function generateProposal(force: boolean): Promise<GraphSchemaProposal> {
    const response = page.waitForResponse((response) => new URL(response.url()).pathname === proposalPath
      && response.request().method() === 'POST' && response.status() === 200);
    await page.getByTestId('generate-graph-schema').click();
    const actual = await response;
    expect(actual.request().postDataJSON()).toEqual({ force_refresh: force });
    return await actual.json() as GraphSchemaProposal;
  }

  await patchCorpusConfigSection(page.request, corpus.corpusId, 'graph_indexing', {
    enabled: true, build_code_graph: false, semantic_kg_llm_model: 'openai.gpt-5.6-sol',
  });
  proposalScenario = 'valid';
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`);
  await page.getByTestId('indexing-component-card-enrichment').click();
  const initialProposal = await generateProposal(false);
  expect(initialProposal.accounting_started_at).toBeTruthy();
  const proposal = page.getByTestId('graph-schema-proposal');
  await expect(proposal).toBeVisible();
  const schemaHash = initialProposal.schema_hash;
  const attempt = page.getByTestId('index-run-costs').filter({ has: page.getByText('Schema proposal cost', { exact: true }) });
  await expect(attempt).toHaveAttribute('data-run-id', initialProposal.accounting_run_id!);
  await expectCostsCollapsed(attempt);
  const review = proposal.getByTestId('graph-schema-review');
  await expect(review).toHaveJSProperty('open', false);
  await expect(proposal.getByTestId('graph-schema-technical')).toHaveJSProperty('open', false);
  await expect(proposal.getByTestId('graph-schema-hash')).not.toBeVisible();
  await proposal.screenshot({ path: test.info().outputPath('schema-collapsed.png') });
  await proposal.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('schema-and-cost-collapsed.png') });
  await review.locator('> summary').click();
  await proposal.getByTestId('graph-schema-node-types').locator('> summary').click();
  await proposal.getByTestId('graph-schema-relationship-types').locator('> summary').click();
  await proposal.getByTestId('graph-schema-patterns').locator('> summary').click();
  await expect(proposal.getByTestId('graph-schema-node-types').locator('ul')).toBeVisible();
  await expect(proposal.getByTestId('graph-schema-json')).not.toBeVisible();
  await proposal.screenshot({ path: test.info().outputPath('schema-human-review.png') });
  await review.locator('> summary').click();
  await expect(review).toHaveJSProperty('open', false);

  // A real missing-history 404 cannot erase the successful action's returned owner.
  // Actual provider 502/504 coverage belongs to graph_schema_reliability.spec.ts.
  const forced = await withMissingHistory(() => generateProposal(true));
  expect(forced.accounting_run_id).not.toBe(initialProposal.accounting_run_id);
  expect(forced.accounting_started_at).toBeTruthy();
  await expect(attempt).toHaveAttribute('data-run-id', forced.accounting_run_id!);

  try {
    holdNextHistory = true;
    const successful = await generateProposal(true);
    const captured = await historicalRun;
    expect(captured.run_id).toBe(successful.accounting_run_id);
    await expect(attempt).toHaveAttribute('data-run-id', successful.accounting_run_id!);

    // The gateway really returns an invalid schema; the API creates a failed
    // accounting attempt while retaining the previous successful proposal.
    proposalScenario = 'wrong_shape';
    const failedResponse = page.waitForResponse((response) => new URL(response.url()).pathname === proposalPath
      && response.request().method() === 'POST' && response.status() === 502);
    await page.getByRole('button', { name: 'Regenerate proposed schema', exact: true }).click();
    const failure = await (await failedResponse).json() as GraphSchemaProposalFailureResponse;
    const failedId = failure.detail.accounting_run_id!;
    expect(failedId).toMatch(/^[0-9a-f]{32}$/);
    const failedRunResponse = await page.request.get(`${API_BASE}/index/${corpus.corpusId}/runs/${failedId}`);
    expect(failedRunResponse.ok()).toBeTruthy();
    const failedRun = await failedRunResponse.json() as IndexRunSummary;
    expect(failure.detail.accounting_started_at).toBe(failedRun.started_at);
    expect(failedRun.accounting?.gateway_base_url).toBe(gatewayUrl);
    await expect(page.getByTestId('graph-schema-error')).toContainText(failure.detail.message);
    await expect(proposal).toBeVisible();
    await expect(page.getByTestId('graph-schema-hash')).toHaveText(schemaHash);
    await expect(attempt).toHaveAttribute('data-run-id', failedId);
    await expectCostsCollapsed(attempt);
    await expandCosts(attempt);
    await expect(attempt.getByTestId('index-cost-provider')).toHaveText('$0.0123');
    releaseHistory();
    await historyCompletion;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(attempt).toHaveAttribute('data-run-id', failedId);

    // Persist overlapping completion order (A-start, B-start, A-complete).
    // Returning a draft to its saved values now restores through GET, with no
    // Generate click, and must leave B's newer failed accounting owner intact.
    updateSavedProposalTiming({ created_at: new Date(Date.parse(failedRun.started_at) + 60_000).toISOString() });
    const reasoning = page.getByTestId('schema-proposal-reasoning-effort');
    const originalReasoning = await reasoning.inputValue();
    const alternateReasoning = originalReasoning === 'high' ? 'low' : 'high';
    await reasoning.selectOption(alternateReasoning);
    await expect(proposal).toHaveCount(0);
    const postsBeforeRestore = schemaPosts;
    const providersBeforeRestore = ledgers.size;
    const restoredResponse = page.waitForResponse((response) => new URL(response.url()).pathname === proposalPath
      && response.request().method() === 'GET' && response.status() === 200);
    await reasoning.selectOption(originalReasoning);
    const restored = await (await restoredResponse).json() as GraphSchemaProposalState;
    expect(restored.status).toBe('current');
    expect(restored.proposal?.accounting_run_id).toBe(successful.accounting_run_id);
    expect(Date.parse(restored.proposal!.accounting_started_at!)).toBeLessThan(Date.parse(failedRun.started_at));
    expect(Date.parse(restored.proposal!.created_at)).toBeGreaterThan(Date.parse(failedRun.started_at));
    await expect(proposal).toBeVisible();
    await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
    await expect(attempt).toHaveAttribute('data-run-id', failedId);
    expect(schemaPosts).toBe(postsBeforeRestore);
    expect(ledgers.size).toBe(providersBeforeRestore);

    await page.reload();
    await page.getByTestId('indexing-component-card-enrichment').click();
    await expect(proposal).toBeVisible();
    await expect(attempt).toHaveAttribute('data-run-id', failedId);
    await expectCostsCollapsed(attempt);
    await expect(review).toHaveJSProperty('open', false);
    expect(schemaPosts).toBe(postsBeforeRestore);
    expect(ledgers.size).toBe(providersBeforeRestore);

    proposalScenario = 'valid';
    await reasoning.selectOption(alternateReasoning);
    const fresh = await withMissingHistory(() => generateProposal(false));
    expect(fresh.accounting_run_id).not.toBe(successful.accounting_run_id);
    expect(fresh.accounting_run_id).not.toBe(failedId);
    expect(Date.parse(fresh.accounting_started_at!)).toBeGreaterThan(Date.parse(failedRun.started_at));
    await expect(attempt).toHaveAttribute('data-run-id', fresh.accounting_run_id!);

    // An existing persisted proposal may omit its optional attempt timestamp.
    // Hold authentic GET responses so an unforced manual cache lookup remains
    // possible; its null must not erase the same owner's already-known start.
    updateSavedProposalTiming({ accounting_started_at: null });
    await reasoning.selectOption(originalReasoning);
    await expect(proposal).toHaveCount(0);
    let releaseRestore!: () => void;
    const restoreRelease = new Promise<void>((resolve) => { releaseRestore = resolve; });
    let captureRestore!: (state: GraphSchemaProposalState) => void;
    const restoredLegacy = new Promise<GraphSchemaProposalState>((resolve) => { captureRestore = resolve; });
    const pendingRestores: Promise<void>[] = [];
    let holdRestore = true;
    await page.route('**/graph-schema/proposal', async (route) => {
      if (route.request().method() !== 'GET' || !holdRestore) {
        await route.continue();
        return;
      }
      let finished!: () => void;
      pendingRestores.push(new Promise<void>((resolve) => { finished = resolve; }));
      try {
        const original = await route.fetch();
        expect(original.status()).toBe(200);
        captureRestore(await original.json() as GraphSchemaProposalState);
        await restoreRelease;
        if (!/ERR_ABORTED|NS_BINDING_ABORTED|cancell?ed/i.test(route.request().failure()?.errorText ?? '')) {
          await route.fulfill({ response: original });
        }
      } catch (error) {
        if (!/ERR_ABORTED|NS_BINDING_ABORTED|cancell?ed/i.test(route.request().failure()?.errorText ?? '')) throw error;
      } finally {
        finished();
      }
    });
    try {
      await reasoning.selectOption(alternateReasoning);
      const legacyState = await restoredLegacy;
      expect(legacyState.status).toBe('current');
      expect(legacyState.proposal?.accounting_run_id).toBe(fresh.accounting_run_id);
      expect(legacyState.proposal?.accounting_started_at).toBeNull();
      const providersBeforeCache = ledgers.size;
      const cached = await withMissingHistory(() => generateProposal(false));
      expect(cached.accounting_run_id).toBe(fresh.accounting_run_id);
      expect(cached.accounting_started_at).toBeNull();
      expect(ledgers.size).toBe(providersBeforeCache);
      await expect(attempt).toHaveAttribute('data-run-id', fresh.accounting_run_id!);
    } finally {
      holdRestore = false;
      releaseRestore();
      await Promise.all(pendingRestores);
      await page.unroute('**/graph-schema/proposal');
    }

    await reasoning.selectOption(originalReasoning);
    const postLegacyFresh = await withMissingHistory(() => generateProposal(false));
    expect(postLegacyFresh.accounting_run_id).not.toBe(fresh.accounting_run_id);
    expect(Date.parse(postLegacyFresh.accounting_started_at!)).toBeGreaterThan(Date.parse(fresh.accounting_started_at!));
    await expect(attempt).toHaveAttribute('data-run-id', postLegacyFresh.accounting_run_id!);
  } finally {
    releaseHistory();
    if (heldHistoryClaimed) await historyCompletion;
    await page.unroute('**/api/index/**/runs/**');
  }
});

test('main and default-width dock share a single in-flight native read for the same run', async ({ page }) => {
  const run = saveRun(corpus.corpusId, 1);
  publishRows(run, [0]);
  ledgers.get(run.run_id)!.delayMs = 2400;
  await openRun(page, run);
  await page.getByTestId('dock-choose').click();
  const picker = page.getByRole('dialog', { name: 'Choose something to dock' });
  await picker.getByRole('combobox').fill('RAG Indexing');
  await picker.getByRole('option').filter({ hasText: 'Indexing' }).first().click();
  const panels = page.getByTestId('index-run-costs');
  await expect(panels).toHaveCount(2);
  await expect(panels.nth(0).getByTestId('index-cost-state')).toHaveText('Complete');
  await expect(panels.nth(1).getByTestId('index-cost-state')).toHaveText('Complete');
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  expect(ledgers.get(run.run_id)!.maximumActive).toBe(1);
  let runReads = 0;
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname === `/api/index/${run.corpus_id}/runs/${run.run_id}`
      || pathname === `/api/index/${run.corpus_id}/runs/${run.run_id}/costs/reconcile`) runReads += 1;
  });
  for (const panel of await panels.all()) {
    await expectCostsCollapsed(panel);
    const details = panel.getByTestId('index-cost-details');
    const toggle = details.locator('> summary');
    await toggle.focus();
    await toggle.press('Enter');
    await expect(details).toHaveJSProperty('open', true);
    await expect(panel.getByTestId('index-cost-native')).toBeVisible();
    expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
    await toggle.press('Space');
    await expectCostsCollapsed(panel);
  }
  expect(runReads).toBe(0);
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  const dock = page.getByTestId('dock-native');
  const dockPanel = dock.getByTestId('index-run-costs');
  const dockBounds = await dock.boundingBox();
  const costBounds = await dockPanel.boundingBox();
  expect(dockBounds).not.toBeNull();
  expect(costBounds).not.toBeNull();
  expect(costBounds!.x + costBounds!.width).toBeLessThanOrEqual(dockBounds!.x + dockBounds!.width + 1);
  const refresh = dockPanel.getByRole('button', { name: 'Refresh cost', exact: true });
  await refresh.scrollIntoViewIfNeeded();
  await expect(refresh).toBeInViewport();
  await refresh.click();
  await expect.poll(() => ledgers.get(run.run_id)!.reads).toBe(2);
  await expect(refresh).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('docked-native-accounting.png') });
  await page.reload();
  await expect(panels).toHaveCount(2);
  for (const panel of await panels.all()) {
    await expect(panel.getByTestId('index-cost-state')).toHaveText('Complete');
    await expectCostsCollapsed(panel);
  }
  expect(ledgers.get(run.run_id)!.reads).toBe(2);
});

test('run cost stays concise at a narrow viewport and resets its disclosure after reload', async ({ page, request }) => {
  const run = saveRun(corpus.corpusId, 1);
  publishRows(run, [0]);
  const response = await request.post(`${API_BASE}/index/${corpus.corpusId}/runs/${run.run_id}/costs/reconcile`);
  expect(response.ok()).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  const panel = await openRun(page, run);
  await expect(panel.getByTestId('index-cost-headline')).toHaveText('$0.01 recorded · Complete');
  expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await expandCosts(panel);
  await expect(panel.getByTestId('index-cost-provider')).toBeVisible();
  expect(await panel.evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  await page.reload();
  await expect(panel).toHaveAttribute('data-run-id', run.run_id);
  await expectCostsCollapsed(panel);
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  await panel.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('narrow-run-cost-collapsed.png') });
});
