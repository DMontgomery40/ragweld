import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import type { GraphSchemaProposal, GraphSchemaProposalFailureResponse, GraphSchemaProposalState, TriBridConfig } from '../../../src/types/generated';
import {
  API_BASE,
  patchCorpusConfigSection,
  provisionExhaustiveCorpus,
  type ExhaustiveCorpus,
} from './corpus_fixture';

test.describe.configure({ mode: 'serial' });
test.setTimeout(90_000);

let provider: ChildProcessWithoutNullStreams;
let providerBase: string;
let corpus: ExhaustiveCorpus;
let otherCorpus: ExhaustiveCorpus | undefined;
let pageErrors: string[];

async function control(request: APIRequestContext, operation: string, data?: unknown) {
  const response = await request.post(`${providerBase.replace(/\/v1$/, '')}/__fixture__/${operation}`, { data: data ?? {} });
  expect(response.ok(), await response.text()).toBeTruthy();
}

async function providerState(request: APIRequestContext): Promise<{
  received: number;
  completed: number;
  last_reasoning_effort: string | null;
  last_model: string | null;
}> {
  const response = await request.get(`${providerBase.replace(/\/v1$/, '')}/__fixture__/state`);
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function configureCorpus(request: APIRequestContext, target: ExhaustiveCorpus): Promise<void> {
  await patchCorpusConfigSection(request, target.corpusId, 'chat', {
    litellm: { base_url: providerBase, default_model: 'openai.gpt-5.6-sol' },
  });
  await patchCorpusConfigSection(request, target.corpusId, 'graph_indexing', {
    enabled: true,
    build_code_graph: false,
    semantic_kg_llm_model: 'openai.gpt-5.6-sol',
  });
  const models = await request.get(`${API_BASE}/chat/models?corpus_id=${encodeURIComponent(target.corpusId)}`);
  expect(models.ok(), await models.text()).toBeTruthy();
  expect(await models.text()).toContain('openai.gpt-5.6-sol');
}

async function openSettings(page: Page): Promise<void> {
  await page.goto(`rag?subtab=indexing&corpus=${encodeURIComponent(corpus.corpusId)}`);
  await expect(page.getByTestId('target-corpus-select')).toHaveValue(corpus.corpusId);
  await page.getByTestId('indexing-component-card-enrichment').click();
  await expect(page.getByTestId('schema-proposal-timeout')).toBeVisible();
}

async function graphConfig(request: APIRequestContext) {
  const response = await request.get(`${API_BASE}/config?corpus_id=${encodeURIComponent(corpus.corpusId)}`);
  expect(response.ok()).toBeTruthy();
  return ((await response.json()) as TriBridConfig).graph_indexing;
}

async function setBudgets(page: Page, request: APIRequestContext, timeout: number, tokens: number): Promise<void> {
  await page.getByTestId('schema-proposal-timeout').fill(String(timeout));
  await page.getByTestId('schema-proposal-timeout').press('Enter');
  await page.getByTestId('schema-proposal-max-output-tokens').fill(String(tokens));
  await page.getByTestId('schema-proposal-max-output-tokens').press('Enter');
  await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
  await expect.poll(async () => {
    const config = await graphConfig(request);
    return [config.schema_proposal_timeout_s, config.schema_proposal_max_output_tokens];
  }).toEqual([timeout, tokens]);
}

test.beforeAll(async () => {
  provider = spawn(process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python', [
    'web/tests/e2e/exhaustive/graph_schema_fixture.py',
  ], { cwd: process.cwd(), env: { ...process.env, PYTHONPATH: process.cwd() }, stdio: 'pipe' });
  let startupErrors = '';
  provider.stderr.on('data', (chunk: Buffer) => { startupErrors += chunk.toString(); });
  providerBase = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('Local schema transport fixture did not start')), 15_000);
    let output = '';
    provider.stdout.on('data', (chunk: Buffer) => {
      output += chunk.toString();
      if (!output.includes('\n')) return;
      clearTimeout(timeout);
      resolve((JSON.parse(output.split('\n')[0]) as { base_url: string }).base_url);
    });
    provider.once('error', reject);
    provider.once('exit', (code) => reject(new Error(`Local schema transport fixture exited: ${code}: ${startupErrors.slice(-2000)}`)));
  });
});

test.beforeEach(async ({ request, page }) => {
  pageErrors = [];
  page.on('pageerror', (error) => pageErrors.push(error.message));
  await control(request, 'scenario', { scenario: 'valid' });
  corpus = await provisionExhaustiveCorpus(request);
  await configureCorpus(request, corpus);
});

test.afterEach(async ({ request, page }) => {
  await control(request, 'release');
  await otherCorpus?.dispose(request);
  otherCorpus = undefined;
  await corpus?.dispose(request);
  await expect(page.locator('vite-error-overlay')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});

test.afterAll(async () => {
  if (provider && provider.exitCode === null) {
    const exited = new Promise<void>((resolve) => provider.once('exit', () => resolve()));
    provider.kill('SIGTERM');
    await exited;
  }
});

test('reload restores the persisted proposal read-only with review details closed', async ({ page, request }) => {
  await openSettings(page);
  await page.getByTestId('generate-graph-schema').click();
  await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
  const before = await providerState(request);
  let posted = 0;
  page.on('request', (req) => {
    if (req.method() === 'POST' && new URL(req.url()).pathname.endsWith('/graph-schema/proposal')) posted += 1;
  });
  await page.reload();
  await page.getByTestId('indexing-component-card-enrichment').click();
  await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
  await expect(page.getByTestId('graph-schema-review')).not.toHaveAttribute('open');
  await expect(page.getByTestId('graph-schema-technical')).not.toHaveAttribute('open');
  expect((await providerState(request)).received).toBe(before.received);
  expect(posted).toBe(0);
});

for (const change of ['regenerate', 'corpus', 'config'] as const) {
  test(`an actual stale proposal response cannot overwrite a later ${change}`, async ({ page, request }) => {
    if (change === 'corpus') {
      otherCorpus = await provisionExhaustiveCorpus(request);
      await configureCorpus(request, otherCorpus);
    }
    await openSettings(page);
    await page.getByTestId('generate-graph-schema').click();
    await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
    const before = await providerState(request);
    let release!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    let captured!: (saved: GraphSchemaProposalState) => void;
    const capture = new Promise<GraphSchemaProposalState>((resolve) => { captured = resolve; });
    let handlerFinished!: () => void;
    const handlerCompletion = new Promise<void>((resolve) => { handlerFinished = resolve; });
    let forwarding: 'forwarded' | 'aborted' | 'failed' | null = null;
    let forwardingError = '';
    let claimed = false;
    await page.route('**/graph-schema/proposal', async (route) => {
      if (route.request().method() !== 'GET' || claimed) {
        await route.continue();
        return;
      }
      claimed = true;
      // Response scheduling, not API mocking: fetch the actual completed API
      // response now, then forward that same response without replacing its
      // status, headers or bytes after the newer operator action has completed.
      try {
        const original = await route.fetch();
        expect(original.status()).toBe(200);
        captured(await original.json() as GraphSchemaProposalState);
        await held;
        // New actions deliberately abort the obsolete mount request. Preserve
        // that outcome instead of injecting a response into a cancelled route.
        const failure = route.request().failure()?.errorText ?? '';
        if (/ERR_ABORTED|NS_BINDING_ABORTED|cancell?ed/i.test(failure)) {
          forwarding = 'aborted';
        } else {
          await route.fulfill({ response: original });
          forwarding = 'forwarded';
        }
      } catch (error) {
        const failure = route.request().failure()?.errorText ?? '';
        forwarding = /ERR_ABORTED|NS_BINDING_ABORTED|cancell?ed/i.test(failure) ? 'aborted' : 'failed';
        forwardingError = String(error);
      } finally {
        handlerFinished();
      }
    });
    try {
      await page.reload();
      await page.getByTestId('indexing-component-card-enrichment').click();
      const stale = await capture;
      expect(stale.status).toBe('current');
      expect(stale.proposal?.accounting_run_id).toBeTruthy();
      let newAttempt: string | null = null;
      if (change === 'regenerate') {
        // The held mount read leaves local state empty. First retrieve the
        // existing proposal manually, then prove the next click is forced and
        // sends an actual new provider request with a distinct accounting owner.
        // A second legitimate context-ready GET may have restored the proposal
        // while the earlier response is held. Only retrieve manually if it has
        // not already arrived; every click labeled Regenerate is actual work.
        if ((await page.getByTestId('generate-graph-schema').innerText()).trim() === 'Generate proposed schema') {
          await page.getByTestId('generate-graph-schema').click();
        }
        await expect(page.getByTestId('generate-graph-schema')).toHaveText('Regenerate proposed schema');
        const beforeForced = await providerState(request);
        const regeneratedResponse = page.waitForResponse((response) =>
          new URL(response.url()).pathname.endsWith('/graph-schema/proposal')
          && response.request().method() === 'POST'
          && response.request().postDataJSON().force_refresh === true);
        await page.getByTestId('generate-graph-schema').click();
        const regenerated = await (await regeneratedResponse).json() as GraphSchemaProposal;
        newAttempt = regenerated.accounting_run_id ?? null;
        expect(newAttempt).toBeTruthy();
        expect(newAttempt).not.toBe(stale.proposal?.accounting_run_id);
        await expect.poll(async () => (await providerState(request)).received).toBe(beforeForced.received + 1);
      } else if (change === 'corpus') {
        await page.getByTestId('target-corpus-select').selectOption(otherCorpus!.corpusId);
        await expect(page.getByTestId('graph-schema-restore-state')).toContainText('No saved schema');
      } else {
        await page.getByTestId('schema-proposal-reasoning-effort').selectOption('high');
        await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
        await expect.poll(async () => (await graphConfig(request)).schema_proposal_reasoning_effort).toBe('high');
        await expect(page.getByTestId('graph-schema-restore-state')).toContainText('out of date');
      }
      release();
      await handlerCompletion;
      expect(forwarding, forwardingError).not.toBe('failed');
      expect(['forwarded', 'aborted']).toContain(forwarding);
      await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
      if (change === 'regenerate') {
        await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
        const costs = page.getByTestId('index-run-costs').filter({ has: page.getByText('Schema proposal cost', { exact: true }) });
        await expect(costs).toHaveAttribute('data-run-id', newAttempt!);
      } else {
        await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
        expect((await providerState(request)).received).toBe(before.received);
      }
    } finally {
      release();
      if (claimed) await handlerCompletion;
      await page.unroute('**/graph-schema/proposal');
    }
  });
}

for (const setting of [
  { name: 'reasoning', testId: 'schema-proposal-reasoning-effort', field: 'schema_proposal_reasoning_effort', initial: 'low', next: 'high', select: true },
  { name: 'output limit', testId: 'schema-proposal-max-output-tokens', field: 'schema_proposal_max_output_tokens', initial: '16384', next: '8192', select: false },
] as const) {
  for (const action of ['apply', 'discard', 'generate'] as const) {
    test(`a staged ${setting.name} edit pauses saved review until ${action}`, async ({ page, request }) => {
      await openSettings(page);
      await page.getByTestId('generate-graph-schema').click();
      await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
      const before = await providerState(request);
      const field = page.getByTestId(setting.testId);
      if (setting.select) {
        await field.selectOption(setting.next);
      } else {
        await field.fill(setting.next);
        await field.press('Enter');
      }
      await expect(page.getByTestId('graph-schema-restore-state')).toContainText('unapplied changes');
      await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
      expect(String((await graphConfig(request))[setting.field])).toBe(setting.initial);
      expect((await providerState(request)).received).toBe(before.received);

      if (action === 'apply') {
        await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
        await expect.poll(async () => String((await graphConfig(request))[setting.field])).toBe(setting.next);
        await expect(page.getByTestId('graph-schema-restore-state')).toContainText('out of date');
        await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
      } else if (action === 'discard') {
        // Restore the original value through the real field, discarding the
        // staged edit without a server write or a page remount.
        if (setting.select) {
          await field.selectOption(setting.initial);
        } else {
          await field.fill(setting.initial);
          await field.press('Enter');
        }
        await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
        await expect(page.getByTestId('graph-schema-review')).not.toHaveAttribute('open');
        await expect(page.getByTestId('graph-schema-technical')).not.toHaveAttribute('open');
        expect(String((await graphConfig(request))[setting.field])).toBe(setting.initial);
      } else {
        // Generate already owns a safe config flush. Its own acknowledgment
        // must not let the read-only restore effect cancel the operator action.
        await page.getByTestId('generate-graph-schema').click();
        await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
        await expect.poll(async () => String((await graphConfig(request))[setting.field])).toBe(setting.next);
      }
      await expect.poll(async () => (await providerState(request)).received)
        .toBe(before.received + (action === 'generate' ? 1 : 0));
      await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
    });
  }
}

test('proposal budgets persist their defaults and both supported boundaries', async ({ page, request }) => {
  const before = await providerState(request);
  await openSettings(page);
  const timeout = page.getByTestId('schema-proposal-timeout');
  const tokens = page.getByTestId('schema-proposal-max-output-tokens');
  await expect(timeout).toHaveValue('60');
  await expect(timeout).toHaveAttribute('min', '5');
  await expect(timeout).toHaveAttribute('max', '80');
  await expect(tokens).toHaveValue('16384');
  await expect(tokens).toHaveAttribute('min', '256');
  await expect(tokens).toHaveAttribute('max', '32768');
  for (const [seconds, output] of [[5, 256], [80, 32768], [60, 16384]]) {
    await setBudgets(page, request, seconds, output);
    await page.reload();
    await page.getByTestId('indexing-component-card-enrichment').click();
    await expect(timeout).toHaveValue(String(seconds));
    await expect(tokens).toHaveValue(String(output));
  }
  expect((await providerState(request)).received).toBe(before.received);
});

test('proposal reasoning persists every supported choice and reaches the provider independently of KG effort', async ({ page, request }, testInfo) => {
  await openSettings(page);
  const effort = page.getByTestId('schema-proposal-reasoning-effort');
  const kgEffort = page.getByTestId('semantic-kg-reasoning-effort');
  await expect(effort).toHaveValue('low');
  await expect(kgEffort).toHaveValue('medium');
  await expect(effort.locator('option')).toHaveText(['minimal', 'low', 'medium', 'high', 'xhigh']);

  for (const choice of ['minimal', 'low', 'medium', 'high', 'xhigh'] as const) {
    await effort.selectOption(choice);
    await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
    await expect.poll(async () => {
      const config = await graphConfig(request);
      return [config.schema_proposal_reasoning_effort, config.semantic_kg_reasoning_effort];
    }).toEqual([choice, 'medium']);
    await page.reload();
    await page.getByTestId('indexing-component-card-enrichment').click();
    await expect(effort).toHaveValue(choice);
    await expect(kgEffort).toHaveValue('medium');

    const before = await providerState(request);
    await page.getByTestId('generate-graph-schema').click();
    await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
    const after = await providerState(request);
    expect(after.received).toBe(before.received + 1);
    expect(after.last_reasoning_effort).toBe(choice);
    expect(after.last_model).toBe('openai.gpt-5.6-sol');
    await expect(kgEffort).toHaveValue('medium');
  }
  await effort.scrollIntoViewIfNeeded();
  await page.screenshot({ path: testInfo.outputPath('schema-proposal-reasoning.png') });
});

for (const failure of [{ scenario: 'wrong_shape', status: 502 }, { scenario: 'slow', status: 504 }]) {
  test(`proposal ${failure.status} is readable and a successful retry resets loading`, async ({ page, request }, testInfo) => {
    await openSettings(page);
    await setBudgets(page, request, 5, 16384);
    await control(request, 'scenario', { scenario: failure.scenario });
    const responsePromise = page.waitForResponse((response) =>
      new URL(response.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && response.request().method() === 'POST');
    const generate = page.getByTestId('generate-graph-schema');
    await generate.click();
    const response = await responsePromise;
    expect(response.status()).toBe(failure.status);
    const { detail } = await response.json() as GraphSchemaProposalFailureResponse;
    const error = page.getByTestId('graph-schema-error');
    await expect(error).toContainText(detail.message!);
    await expect(error).toContainText(detail.operator_hint!);
    expect(await error.innerText()).not.toMatch(/PRIVATE PROVIDER DETAIL|\{"|\[object Object\]/);
    await expect(generate).toHaveAttribute('aria-busy', 'false');
    await expect(generate).toBeEnabled();
    await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
    await error.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`schema-proposal-${failure.status}.png`) });

    await control(request, 'scenario', { scenario: 'valid' });
    await generate.click();
    await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
    await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
    await expect(generate).toHaveAttribute('aria-busy', 'false');
    await expect(generate).toBeEnabled();
  });
}

for (const changed of ['corpus', 'settings', 'reasoning'] as const) {
  test(`a ${changed} change discards a proposal already executing at the provider`, async ({ page, request }) => {
    if (changed === 'corpus') {
      otherCorpus = await provisionExhaustiveCorpus(request);
      await configureCorpus(request, otherCorpus);
    }
    await openSettings(page);
    await setBudgets(page, request, 5, 16384);
    await control(request, 'scenario', { scenario: 'held_valid' });
    const before = await providerState(request);
    const generate = page.getByTestId('generate-graph-schema');
    const proposalRequest = page.waitForRequest((request) =>
      new URL(request.url()).pathname === `/api/index/${corpus.corpusId}/graph-schema/proposal`
      && request.method() === 'POST');
    await generate.click();
    const inFlight = await proposalRequest;
    const settled = new Promise<void>((resolve) => {
      const finish = (request: import('@playwright/test').Request) => {
        if (request !== inFlight) return;
        page.off('requestfinished', finish);
        page.off('requestfailed', finish);
        resolve();
      };
      page.on('requestfinished', finish);
      page.on('requestfailed', finish);
    });
    await expect.poll(async () => (await providerState(request)).received).toBe(before.received + 1);
    await expect(generate).toHaveAttribute('aria-busy', 'true');
    if (changed === 'corpus') {
      await page.getByTestId('target-corpus-select').selectOption(otherCorpus!.corpusId);
      await expect(page.getByTestId('target-corpus-select')).toHaveValue(otherCorpus!.corpusId);
    } else if (changed === 'settings') {
      await page.getByTestId('schema-proposal-max-output-tokens').fill('8192');
      await page.getByTestId('schema-proposal-max-output-tokens').press('Enter');
      await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
      await expect.poll(async () => (await graphConfig(request)).schema_proposal_max_output_tokens).toBe(8192);
    } else {
      await page.getByTestId('schema-proposal-reasoning-effort').selectOption('high');
      await page.getByRole('button', { name: /^Apply \d+ changes?$/ }).click();
      await expect.poll(async () => (await graphConfig(request)).schema_proposal_reasoning_effort).toBe('high');
      await expect(page.getByTestId('semantic-kg-reasoning-effort')).toHaveValue('medium');
    }
    await expect(generate).toHaveAttribute('aria-busy', 'false');
    await control(request, 'release');
    await expect.poll(async () => (await providerState(request)).completed).toBeGreaterThan(before.completed);
    await settled;
    await expect(page.getByTestId('graph-schema-proposal')).toHaveCount(0);
    await expect(page.getByTestId('graph-schema-error')).toHaveCount(0);
    await expect(generate).toBeEnabled();

    // A fresh request must still work after the obsolete one completes.
    await control(request, 'scenario', { scenario: 'valid' });
    await generate.click();
    await expect(page.getByTestId('graph-schema-proposal')).toBeVisible();
    await expect(generate).toHaveAttribute('aria-busy', 'false');
  });
}
