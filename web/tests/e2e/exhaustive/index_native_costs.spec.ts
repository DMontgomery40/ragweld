/** Real saved run records, API reconciliation, and HTTP native ledger; no model calls. */
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { IndexRunSummary } from '../../../src/types/generated';
import { API_BASE, patchCorpusConfigSection, provisionExhaustiveCorpus, type ExhaustiveCorpus } from './corpus_fixture';
import { assertPrivateNativeConfig, assertPrivateNativeTargets, type NativeFixtureConfig } from './native_cost_fixture';

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
  const panel = page.getByTestId('index-run-costs').filter({ has: page.getByText('Run accounting', { exact: true }) });
  await expect(panel).toHaveAttribute('data-run-id', run.run_id);
  await expect(panel.getByRole('button', { name: 'Refresh accounting', exact: true })).toBeEnabled();
  return panel;
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
    { rows: [0, 2, 6], count: 3, state: 'complete', native: '$0.01231675', cached: 1, unmeasured: 0 },
    { rows: [6], count: 1, state: 'complete', native: '$0.0000', cached: 1, unmeasured: 0 },
    { rows: [0, 3], count: 3, state: 'incomplete', native: '$0.0123', cached: 0, unmeasured: 1 },
  ];
  for (const [index, variant] of variants.entries()) {
    const run = saveRun(corpus.corpusId, variant.count, index === 2 ? 'cancelled' : 'complete');
    publishRows(run, variant.rows);
    const refreshed = await request.post(`${API_BASE}/index/${corpus.corpusId}/runs/${run.run_id}/costs/reconcile`);
    expect(refreshed.ok()).toBeTruthy();
    const saved = await refreshed.json() as IndexRunSummary;
    expect(saved.accounting?.costs?.state, saved.accounting?.reconciliation_error ?? 'native reconciliation').toBe(variant.state);
    const panel = await openRun(page, run);
    await expect(panel.getByTestId('index-cost-state')).toHaveText(`Accounting ${variant.state}`);
    await expect(panel.getByTestId('index-cost-estimate')).toContainText('Frozen estimate: $0.7500');
    await expect(panel.getByTestId('index-cost-native')).toContainText(variant.native);
    await expect(panel.getByTestId('index-cost-coverage')).toContainText(`${variant.cached} cached · ${variant.unmeasured} unmeasured`);
    await expect(panel.getByTestId('index-cost-denominator')).toContainText('4 chunks processed · 2 files · 72 tokens');
    if (index === 0) {
      await expect(panel.getByTestId('index-cost-provider')).toHaveText('$0.0123');
      await expect(panel.getByTestId('index-cost-calculated')).toHaveText('$0.00001675');
      await expect(panel.getByTestId('index-cost-denominator')).toContainText('$0.0030791875 native logged per processed chunk');
    } else if (index === 2) {
      await expect(panel.getByTestId('index-cost-native')).toContainText('partial accounting');
      await expect(panel.getByTestId('index-cost-denominator')).toContainText('Per-chunk cost unavailable');
      await panel.scrollIntoViewIfNeeded();
      await page.screenshot({ path: test.info().outputPath('incomplete-native-accounting.png') });
    }
  }
  const legacy = saveRun(corpus.corpusId, 0, 'complete', true);
  const panel = await openRun(page, legacy);
  await expect(panel).toContainText('Accounting unavailable');
  await expect(panel).not.toContainText('$0');
});

test('one run settles after native ingestion and incomplete follow-up stops until a manual retry', async ({ page }) => {
  const delayed = saveRun(corpus.corpusId, 1);
  const panel = await openRun(page, delayed);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Accounting pending');
  await expect.poll(() => ledgers.get(delayed.run_id)!.reads).toBe(1);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Accounting incomplete');
  publishRows(delayed, [0]);
  await expect(panel.getByTestId('index-cost-state')).toHaveText('Accounting complete');
  expect(ledgers.get(delayed.run_id)!.reads).toBe(2);

  const absent = saveRun(corpus.corpusId, 1);
  const missing = await openRun(page, absent);
  await expect(missing.getByTestId('index-cost-refresh-paused')).toBeVisible({ timeout: 45_000 });
  expect(ledgers.get(absent.run_id)!.reads).toBe(5);
  // Browser time can advance here: all five actual HTTP reads have settled.
  await page.clock.install();
  await page.clock.fastForward(60_000);
  expect(ledgers.get(absent.run_id)!.reads).toBe(5);
  publishRows(absent, [0]);
  await missing.getByRole('button', { name: 'Refresh accounting', exact: true }).click();
  await expect(missing.getByTestId('index-cost-state')).toHaveText('Accounting complete');
  await expect(missing.getByTestId('index-cost-refresh-paused')).toHaveCount(0);
  expect(ledgers.get(absent.run_id)!.reads).toBe(6);
  expect(ledgers.get(absent.run_id)!.maximumActive).toBe(1);

  const interrupted = saveRun(corpus.corpusId, 1, 'indexing', false, true);
  const interruptedPanel = await openRun(page, interrupted);
  await expect(interruptedPanel.getByTestId('index-cost-state')).toHaveText('Accounting incomplete (run interrupted)');
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
  await expect(panel).toContainText('Accounting unavailable');
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
  const panel = page.getByTestId('index-run-costs').filter({ has: page.getByText('Run accounting', { exact: true }) });
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
  await expect(row).toContainText('Accounting pending');
  expect(ledgers.get(run.run_id)!.reads).toBe(0);
  publishRows(run, [0]);
  const reconciled = await request.post(`${API_BASE}/index/${corpus.corpusId}/runs/${run.run_id}/costs/reconcile`);
  expect(reconciled.ok()).toBeTruthy();
  await page.clock.fastForward(31_000);
  await expect(row).toContainText('Accounting complete · $0.0123 native logged');
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  await row.getByText('Accounting complete · $0.0123 native logged', { exact: true }).click();
  await expect(row.getByTestId('index-cost-estimate')).toContainText('Frozen estimate: $0.7500');
  await row.scrollIntoViewIfNeeded();
  await page.screenshot({ path: test.info().outputPath('dashboard-native-accounting.png') });
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

test('schema accounting follows successful regeneration when latest history fails and preserves a newer failed attempt', async ({ page }) => {
  type HeldLatestLookup = {
    seen: Promise<void>;
    markSeen: () => void;
    released: Promise<void>;
    release: () => void;
    delivered: Promise<void>;
    markDelivered: () => void;
  };
  let latestSchemaLookupMode: number | 'hold' | null = null;
  let heldLatestLookup: HeldLatestLookup | null = null;
  let proposalCreatedAtOverride: string | null = null;
  let proposalAccountingStartedAtOverride: string | null | undefined;
  await page.route('**/api/index/**/graph-schema/proposal', async (route) => {
    if (proposalCreatedAtOverride === null && proposalAccountingStartedAtOverride === undefined) {
      await route.continue();
      return;
    }
    const response = await route.fetch();
    if (response.status() !== 200) {
      await route.fulfill({ response });
      return;
    }
    const payload = await response.json() as Record<string, unknown>;
    if (proposalCreatedAtOverride !== null) payload.created_at = proposalCreatedAtOverride;
    if (proposalAccountingStartedAtOverride !== undefined) {
      payload.accounting_started_at = proposalAccountingStartedAtOverride;
    }
    await route.fulfill({ response, json: payload });
  });
  await page.route('**/api/index/**/runs/latest**', async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get('run_kind') !== 'schema_proposal') {
      await route.continue();
      return;
    }
    if (latestSchemaLookupMode === 'hold') {
      const hold = heldLatestLookup;
      if (!hold) throw new Error('Held latest-schema lookup was not initialized');
      // Fetch now so the response is the historical attempt that existed before the next
      // operator action, then deliver it only after that action has returned a newer attempt.
      const historicalResponse = await route.fetch();
      hold.markSeen();
      await hold.released;
      await route.fulfill({ response: historicalResponse });
      hold.markDelivered();
      return;
    }
    if (latestSchemaLookupMode !== null) {
      await route.fulfill({
        status: latestSchemaLookupMode,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Fixture latest-schema history unavailable' }),
      });
      return;
    }
    await route.continue();
  });
  await patchCorpusConfigSection(page.request, corpus.corpusId, 'graph_indexing', {
    enabled: true,
    build_code_graph: false,
    semantic_kg_llm_model: 'openai.gpt-5.6-sol',
  });
  proposalScenario = 'valid';
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`);
  await page.getByTestId('indexing-component-card-enrichment').click();
  const initialResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && response.request().method() === 'POST'
      && response.status() === 200);
  await page.getByTestId('generate-graph-schema').click();
  const initialProposal = await (await initialResponse).json() as {
    accounting_run_id: string;
    accounting_started_at: string;
  };
  expect(initialProposal.accounting_started_at).toBeTruthy();
  const proposal = page.getByTestId('graph-schema-proposal');
  await expect(proposal).toBeVisible();
  const schemaHash = await page.getByTestId('graph-schema-hash').innerText();
  let successfulRunId = initialProposal.accounting_run_id;
  const attempt = page.getByTestId('index-run-costs').filter({ has: page.getByText('Schema proposal accounting', { exact: true }) });
  await expect(attempt).toHaveAttribute('data-run-id', successfulRunId);

  // A forced regeneration always creates a new attempt. Its returned ID must become visible
  // even when the best-effort historical lookup fails or reports its own timeout.
  for (const status of [503, 504]) {
    latestSchemaLookupMode = status;
    const regeneratedResponse = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
        && response.request().method() === 'POST'
        && response.status() === 200);
    const failedLatestLookup = page.waitForResponse((response) => {
      const url = new URL(response.url());
      return url.pathname === `/api/index/${corpus.corpusId}/runs/latest`
        && url.searchParams.get('run_kind') === 'schema_proposal'
        && response.status() === status;
    });
    await page.getByRole('button', { name: 'Regenerate proposed schema', exact: true }).click();
    const regenerated = await (await regeneratedResponse).json() as {
      accounting_run_id: string;
      accounting_started_at: string;
    };
    expect(regenerated.accounting_run_id).not.toBe(successfulRunId);
    expect(regenerated.accounting_started_at).toBeTruthy();
    await failedLatestLookup;
    await expect(attempt).toHaveAttribute('data-run-id', regenerated.accounting_run_id);
    successfulRunId = regenerated.accounting_run_id;
    latestSchemaLookupMode = null;
  }

  let markHeldLatestSeen!: () => void;
  let releaseHeldLatest!: () => void;
  let markHeldLatestDelivered!: () => void;
  const heldLookup: HeldLatestLookup = {
    seen: new Promise<void>((resolve) => { markHeldLatestSeen = resolve; }),
    markSeen: () => markHeldLatestSeen(),
    released: new Promise<void>((resolve) => { releaseHeldLatest = resolve; }),
    release: () => releaseHeldLatest(),
    delivered: new Promise<void>((resolve) => { markHeldLatestDelivered = resolve; }),
    markDelivered: () => markHeldLatestDelivered(),
  };
  heldLatestLookup = heldLookup;
  latestSchemaLookupMode = 'hold';
  const regeneratedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && response.request().method() === 'POST'
      && response.status() === 200);
  await page.getByRole('button', { name: 'Regenerate proposed schema', exact: true }).click();
  const regenerated = await (await regeneratedResponse).json() as {
    accounting_run_id: string;
    accounting_started_at: string;
  };
  expect(regenerated.accounting_run_id).not.toBe(successfulRunId);
  expect(regenerated.accounting_started_at).toBeTruthy();
  await heldLookup.seen;
  await expect(attempt).toHaveAttribute('data-run-id', regenerated.accounting_run_id);
  successfulRunId = regenerated.accounting_run_id;

  // A response captured before this failed action must not overwrite the failure when it is
  // finally delivered. This covers the same state family as corpus switches and unmounts:
  // async history can populate the panel only while its request generation is still current.
  proposalScenario = 'wrong_shape';
  const failedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && response.request().method() === 'POST'
      && response.status() === 502);
  await page.getByRole('button', { name: 'Regenerate proposed schema', exact: true }).click();
  const response = await failedResponse;
  const failure = await response.json() as {
    detail: { accounting_run_id: string; accounting_started_at: string; message: string };
  };
  expect(failure.detail.accounting_run_id).toMatch(/^[0-9a-f]{32}$/);
  expect(failure.detail.accounting_started_at).toBeTruthy();
  const failedRunResponse = await page.request.get(
    `${API_BASE}/index/${corpus.corpusId}/runs/${failure.detail.accounting_run_id}`
  );
  expect(failedRunResponse.ok()).toBeTruthy();
  const failedRun = await failedRunResponse.json() as IndexRunSummary;
  expect(failure.detail.accounting_started_at).toBe(failedRun.started_at);
  expect(failedRun.accounting?.gateway_base_url).toBe(gatewayUrl);
  await expect(page.getByTestId('graph-schema-error')).toContainText(failure.detail.message);
  await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
  await expect(page.getByTestId('graph-schema-hash')).toHaveText(schemaHash);
  await expect(attempt).toHaveAttribute('data-run-id', failure.detail.accounting_run_id);
  await expect(attempt.getByTestId('index-cost-provider')).toHaveText('$0.0123');
  latestSchemaLookupMode = null;
  heldLookup.release();
  await heldLookup.delivered;
  await page.evaluate(() => new Promise<void>((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
  await expect(attempt).toHaveAttribute('data-run-id', failure.detail.accounting_run_id);

  // Clear the proposal from local UI state, then restore the original configuration so the
  // unforced request returns the cached successful proposal. Its proposal completion time is
  // placed after the failed attempt's start to model overlapping A-start/B-start/A-complete;
  // accounting order must still use A/B attempt starts and keep the newer failure.
  const reasoning = page.getByTestId('schema-proposal-reasoning-effort');
  const originalReasoning = await reasoning.inputValue();
  const alternateReasoning = originalReasoning === 'high' ? 'low' : 'high';
  await reasoning.selectOption(alternateReasoning);
  await expect(proposal).toHaveCount(0);
  await reasoning.selectOption(originalReasoning);
  proposalCreatedAtOverride = new Date(
    Date.parse(failure.detail.accounting_started_at) + 60_000,
  ).toISOString();
  latestSchemaLookupMode = 504;
  const cachedResponse = page.waitForResponse((cachedResponse) =>
    new URL(cachedResponse.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && cachedResponse.request().method() === 'POST'
      && cachedResponse.status() === 200);
  const timedOutCachedLookup = page.waitForResponse((historyResponse) => {
    const url = new URL(historyResponse.url());
    return url.pathname === `/api/index/${corpus.corpusId}/runs/latest`
      && url.searchParams.get('run_kind') === 'schema_proposal'
      && historyResponse.status() === 504;
  });
  await page.getByTestId('generate-graph-schema').click();
  const cachedHttpResponse = await cachedResponse;
  expect(cachedHttpResponse.request().postDataJSON()).toEqual({ force_refresh: false });
  const cached = await cachedHttpResponse.json() as {
    accounting_run_id: string;
    accounting_started_at: string;
  };
  expect(cached.accounting_run_id).toBe(successfulRunId);
  expect(Date.parse(cached.accounting_started_at)).toBeLessThan(
    Date.parse(failure.detail.accounting_started_at),
  );
  await timedOutCachedLookup;
  await expect(page.getByTestId('graph-schema-hash')).toHaveText(schemaHash);
  await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
  await expect(attempt).toHaveAttribute('data-run-id', failure.detail.accounting_run_id);

  latestSchemaLookupMode = null;
  proposalCreatedAtOverride = null;
  await page.reload();
  await page.getByTestId('indexing-component-card-enrichment').click();
  const restoredAttempt = page.getByTestId('index-run-costs').filter({ has: page.getByText('Schema proposal accounting', { exact: true }) });
  await expect(restoredAttempt).toHaveAttribute('data-run-id', failure.detail.accounting_run_id);
  proposalScenario = 'valid';
  const reloadedReasoning = page.getByTestId('schema-proposal-reasoning-effort');
  await reloadedReasoning.selectOption(alternateReasoning);
  latestSchemaLookupMode = 504;
  const freshResponse = page.waitForResponse((freshResponse) =>
    new URL(freshResponse.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && freshResponse.request().method() === 'POST'
      && freshResponse.status() === 200);
  const timedOutLatestLookup = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === `/api/index/${corpus.corpusId}/runs/latest`
      && url.searchParams.get('run_kind') === 'schema_proposal'
      && response.status() === 504;
  });
  await page.getByTestId('generate-graph-schema').click();
  const freshHttpResponse = await freshResponse;
  expect(freshHttpResponse.request().postDataJSON()).toEqual({ force_refresh: false });
  const fresh = await freshHttpResponse.json() as {
    accounting_run_id: string;
    accounting_started_at: string;
  };
  expect(fresh.accounting_run_id).not.toBe(successfulRunId);
  expect(fresh.accounting_run_id).not.toBe(failure.detail.accounting_run_id);
  expect(Date.parse(fresh.accounting_started_at)).toBeGreaterThan(
    Date.parse(failure.detail.accounting_started_at),
  );
  await timedOutLatestLookup;
  await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
  await expect(restoredAttempt).toHaveAttribute('data-run-id', fresh.accounting_run_id);

  // A rolling-upgrade cache may return the same run without the new timestamp. Keep the
  // already known timestamp, or the next fresh unforced proposal becomes incomparable and
  // remains hidden whenever its latest-history follow-up is unavailable.
  await reloadedReasoning.selectOption(originalReasoning);
  await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
  await reloadedReasoning.selectOption(alternateReasoning);
  proposalAccountingStartedAtOverride = null;
  latestSchemaLookupMode = 504;
  const legacyCachedResponse = page.waitForResponse((legacyResponse) =>
    new URL(legacyResponse.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && legacyResponse.request().method() === 'POST'
      && legacyResponse.status() === 200);
  const legacyCachedLatestFailure = page.waitForResponse((historyResponse) => {
    const url = new URL(historyResponse.url());
    return url.pathname === `/api/index/${corpus.corpusId}/runs/latest`
      && url.searchParams.get('run_kind') === 'schema_proposal'
      && historyResponse.status() === 504;
  });
  await page.getByTestId('generate-graph-schema').click();
  const legacyCachedHttpResponse = await legacyCachedResponse;
  expect(legacyCachedHttpResponse.request().postDataJSON()).toEqual({ force_refresh: false });
  const legacyCached = await legacyCachedHttpResponse.json() as { accounting_run_id: string };
  expect(legacyCached.accounting_run_id).toBe(fresh.accounting_run_id);
  await legacyCachedLatestFailure;
  await expect(restoredAttempt).toHaveAttribute('data-run-id', fresh.accounting_run_id);

  proposalAccountingStartedAtOverride = undefined;
  await reloadedReasoning.selectOption(originalReasoning);
  latestSchemaLookupMode = 504;
  const postLegacyFreshResponse = page.waitForResponse((freshResponse) =>
    new URL(freshResponse.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && freshResponse.request().method() === 'POST'
      && freshResponse.status() === 200);
  const postLegacyLatestFailure = page.waitForResponse((historyResponse) => {
    const url = new URL(historyResponse.url());
    return url.pathname === `/api/index/${corpus.corpusId}/runs/latest`
      && url.searchParams.get('run_kind') === 'schema_proposal'
      && historyResponse.status() === 504;
  });
  await page.getByTestId('generate-graph-schema').click();
  const postLegacyFreshHttpResponse = await postLegacyFreshResponse;
  expect(postLegacyFreshHttpResponse.request().postDataJSON()).toEqual({ force_refresh: false });
  const postLegacyFresh = await postLegacyFreshHttpResponse.json() as {
    accounting_run_id: string;
    accounting_started_at: string;
  };
  expect(postLegacyFresh.accounting_run_id).not.toBe(fresh.accounting_run_id);
  expect(Date.parse(postLegacyFresh.accounting_started_at)).toBeGreaterThan(
    Date.parse(fresh.accounting_started_at),
  );
  await postLegacyLatestFailure;
  await expect(restoredAttempt).toHaveAttribute('data-run-id', postLegacyFresh.accounting_run_id);
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
  await expect(panels.nth(0).getByTestId('index-cost-state')).toHaveText('Accounting complete');
  await expect(panels.nth(1).getByTestId('index-cost-state')).toHaveText('Accounting complete');
  expect(ledgers.get(run.run_id)!.reads).toBe(1);
  expect(ledgers.get(run.run_id)!.maximumActive).toBe(1);
  const dock = page.getByTestId('dock-native');
  const dockPanel = dock.getByTestId('index-run-costs');
  const refresh = dockPanel.getByRole('button', { name: 'Refresh accounting', exact: true });
  await refresh.scrollIntoViewIfNeeded();
  await expect(refresh).toBeInViewport();
  await refresh.click();
  await expect.poll(() => ledgers.get(run.run_id)!.reads).toBe(2);
  await expect(refresh).toBeEnabled();
  await page.screenshot({ path: test.info().outputPath('docked-native-accounting.png') });
});
