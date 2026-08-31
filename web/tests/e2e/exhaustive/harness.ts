import { expect, type Locator, type Page } from '@playwright/test';
import type { ControlDescriptor, UISurface } from './types';
import {
  ACTION_BLACKLIST_HINTS,
  ACTION_BLACKLIST_PATTERNS,
  HOST_ACTION_SURFACE_KEYS,
  METRICS_MEDIUM_CORE_SET,
  NEVER_TOUCH_HINTS,
  NEVER_TOUCH_PATTERNS,
  REQUIRED_CLOUD_PROVIDERS,
  RETRIEVAL_IMPACT_HINTS,
  UI_SURFACES,
  type CorpusProbe,
} from './suite_config';

const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:58012/api';
// Prometheus exposition lives at the server root (`/metrics`), not under `/api`.
const API_ORIGIN = API_BASE.replace(/\/api\/?$/, '');
const ALLOW_DESTRUCTIVE = process.env.EXHAUSTIVE_DESTRUCTIVE === '1';
const SELECT_ALL_OPTIONS = process.env.EXHAUSTIVE_SELECT_ALL_OPTIONS === '1';
const ENABLE_PROPAGATION_SCAN = process.env.EXHAUSTIVE_PROPAGATION_SCAN !== '0';
const EXTRA_WAIT_MS = Number(process.env.EXHAUSTIVE_WAIT_MS ?? 500);
const METRICS_BUDGET = String(process.env.EXHAUSTIVE_METRICS_BUDGET || 'medium').toLowerCase();

type ChatModel = {
  id: string;
  provider: string;
  source: string;
  override: string;
};

export type ProviderCoverageResult = {
  provider: string;
  available: boolean;
  tested: boolean;
  feedback?: 'thumbsup' | 'thumbsdown';
  detail: string;
};

function surfacePath(surface: UISurface): string {
  // The app is served under /web/, so routes must resolve RELATIVE to the
  // baseURL: an absolute '/dashboard' would hit the origin root and 404.
  const route = surface.route.replace(/^\//, '');
  if (!surface.subtab) return route;
  const sep = route.includes('?') ? '&' : '?';
  return `${route}${sep}subtab=${encodeURIComponent(surface.subtab)}`;
}

function normalize(str: string): string {
  return String(str || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function controlText(c: ControlDescriptor): string {
  return normalize(`${c.tag} ${c.type} ${c.role} ${c.id} ${c.name} ${c.label}`);
}

function hasAny(text: string, hints: string[]): boolean {
  return hints.some((h) => text.includes(h));
}

export function isNeverTouchControl(c: ControlDescriptor): boolean {
  const text = controlText(c);
  return hasAny(text, NEVER_TOUCH_HINTS) || NEVER_TOUCH_PATTERNS.some((pattern) => pattern.test(text));
}

export function isRetrievalImpactControl(c: ControlDescriptor): boolean {
  const text = controlText(c);
  return hasAny(text, RETRIEVAL_IMPACT_HINTS);
}

export async function gotoSurface(page: Page, surface: UISurface): Promise<void> {
  await page.goto(surfacePath(surface), { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(EXTRA_WAIT_MS);
  await page.evaluate(() => {
    const detailsNodes = Array.from(document.querySelectorAll('details'));
    for (const node of detailsNodes) {
      const hidden = !node.offsetParent;
      // Open persistent disclosure panels so their controls are discoverable,
      // but leave transient popovers closed. The Chat source picker is a
      // full-card overlay; auto-opening it covered every later Chat target.
      const transient = node.matches('[data-testid="source-dropdown"]');
      if (!hidden && !transient) node.open = true;
    }
  });
}

export async function ensureAppReady(page: Page): Promise<void> {
  await page.waitForSelector('.topbar', { timeout: 90_000 });
  await page.waitForSelector('#save-btn', { timeout: 90_000 });
}

export async function assertRuntimePreflight(page: Page): Promise<{
  has_local_model: boolean;
  has_cloud_model: boolean;
  model_count: number;
  required_providers: string[];
  available_providers: string[];
}> {
  const health = await page.request.get(`${API_BASE}/health`);
  if (!health.ok()) {
    throw new Error(`Backend health failed: ${health.status()} ${health.statusText()}`);
  }

  const corpus = await getActiveCorpus(page);
  const qs = corpus ? `?corpus_id=${encodeURIComponent(corpus)}` : '';
  const modelsResp = await page.request.get(`${API_BASE}/chat/models${qs}`);
  if (!modelsResp.ok()) {
    throw new Error(`Chat models endpoint failed: ${modelsResp.status()} ${modelsResp.statusText()}`);
  }
  const payload = await modelsResp.json();
  const models = Array.isArray((payload as any)?.models) ? (payload as any).models : [];
  // Post gateway cutover every model is a LiteLLM alias: `ragweld-local` is
  // the host-served local lane and every other alias routes to a cloud
  // upstream. Alias prefixes (`openai.gpt-...`) carry the upstream provider.
  const hasLocal = models.some((m: any) => String(m?.id || '') === 'ragweld-local');
  const hasCloud = models.some(
    (m: any) => String(m?.id || '').length > 0 && String(m?.id || '') !== 'ragweld-local'
  );
  const providers: string[] = Array.from(
    new Set<string>(
      models
        .map((m: any): string => {
          const id = String(m?.id || '');
          return id.includes('.') ? id.split('.')[0].trim().toLowerCase() : '';
        })
        .filter((v: string) => v.length > 0)
    )
  );
  return {
    has_local_model: hasLocal,
    has_cloud_model: hasCloud,
    model_count: models.length,
    required_providers: [...REQUIRED_CLOUD_PROVIDERS],
    available_providers: providers,
  };
}

async function safeCount(locator: Locator): Promise<number> {
  try {
    return await locator.count();
  } catch {
    return 0;
  }
}

async function safeVisible(locator: Locator): Promise<boolean> {
  try {
    return await locator.isVisible();
  } catch {
    return false;
  }
}

async function safeEnabled(locator: Locator): Promise<boolean> {
  try {
    return await locator.isEnabled();
  } catch {
    return false;
  }
}

export async function collectVisibleControls(page: Page): Promise<ControlDescriptor[]> {
  const rows = await page.evaluate(() => {
    const isVisible = (el: Element): boolean => {
      const node = el as HTMLElement;
      const style = window.getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
      if (node.getAttribute('aria-hidden') === 'true') return false;
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    };

    const getLabel = (el: Element): string => {
      const node = el as HTMLElement;
      const id = node.getAttribute('id') || '';
      if (id) {
        const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
        if (explicit) return (explicit.textContent || '').trim();
      }
      const wrapped = node.closest('label');
      if (wrapped) return (wrapped.textContent || '').trim();
      const aria = node.getAttribute('aria-label') || node.getAttribute('title') || '';
      if (aria.trim()) return aria.trim();
      return (node.textContent || '').trim().slice(0, 120);
    };

    const nodes = Array.from(
      document.querySelectorAll(
        [
          'button',
          'select',
          'textarea',
          'input',
          '[role="button"]',
          '[role="combobox"]',
          '[role="switch"]',
          '[contenteditable="true"]',
        ].join(',')
      )
    );

    const results: any[] = [];
    for (const node of nodes) {
      const element = node as HTMLElement;
      const tag = element.tagName.toLowerCase();
      const type = (element.getAttribute('type') || '').toLowerCase();
      if (tag === 'input' && type === 'hidden') continue;
      if (!isVisible(element)) continue;

      const id = element.id || '';
      const name = element.getAttribute('name') || '';
      const role = element.getAttribute('role') || '';
      const label = getLabel(element);
      const value = tag === 'input' || tag === 'textarea' || tag === 'select' ? String((element as any).value ?? '') : '';
      const checked = tag === 'input' && (type === 'checkbox' || type === 'radio') ? Boolean((element as HTMLInputElement).checked) : null;
      const disabled = (element as any).disabled === true || element.getAttribute('aria-disabled') === 'true';
      const dtid = element.getAttribute('data-testid') || '';
      const optionValues =
        tag === 'select'
          ? Array.from((element as HTMLSelectElement).options).map((o) => String(o.value))
          : [];

      const fp = [tag, type, role, id, name, label].join('|').replace(/\s+/g, ' ').trim();
      element.setAttribute('data-exhaustive-fp', fp);

      const selector = id
        ? `#${CSS.escape(id)}`
        : dtid
          ? `[data-testid="${dtid.replace(/"/g, '\\"')}"]`
          : `[data-exhaustive-fp="${fp.replace(/"/g, '\\"')}"]`;

      results.push({
        fingerprint: fp,
        selector,
        tag,
        type,
        role,
        id,
        name,
        label,
        value,
        checked,
        disabled,
        visible: true,
        optionValues,
      });
    }
    return results;
  });

  const dedup = new Map<string, ControlDescriptor>();
  for (const row of rows) {
    dedup.set(String(row.fingerprint), row as ControlDescriptor);
  }
  return Array.from(dedup.values());
}

export async function readControlValue(page: Page, c: ControlDescriptor): Promise<string> {
  const loc = page.locator(c.selector).first();
  await expect(loc).toBeVisible({ timeout: 30_000 });
  if (c.tag === 'input') {
    if (c.type === 'checkbox' || c.type === 'radio') {
      return (await loc.isChecked()) ? 'true' : 'false';
    }
    return await loc.inputValue();
  }
  if (c.tag === 'textarea') return await loc.inputValue();
  if (c.tag === 'select') return await loc.inputValue();
  return normalize(await loc.innerText());
}

async function maybeApply(page: Page): Promise<{ attempted: boolean; saved: boolean }> {
  const saveBtn = page.locator('#save-btn').first();
  const exists = (await safeCount(saveBtn)) > 0;
  if (!exists) return { attempted: false, saved: false };
  if (!(await safeVisible(saveBtn))) return { attempted: false, saved: false };
  if (!(await safeEnabled(saveBtn))) return { attempted: true, saved: false };

  await saveBtn.click();
  const confirm = page.getByTestId('confirm-dialog');
  if ((await safeCount(confirm)) > 0 && (await safeVisible(confirm))) {
    await expect(confirm).toHaveAccessibleName('Apply changes that affect the index');
    const accept = page.getByTestId('confirm-dialog-accept');
    await expect(accept).toBeEnabled();
    await accept.click();
    await expect(confirm).toHaveCount(0);
  }
  await page.waitForTimeout(EXTRA_WAIT_MS);
  await expect(saveBtn).not.toContainText('Saving...', { timeout: 180_000 });
  return { attempted: true, saved: true };
}

async function getActiveCorpus(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    return (
      localStorage.getItem('tribrid_active_corpus') ||
      localStorage.getItem('tribrid_active_repo') ||
      null
    );
  });
}

async function listChatModels(page: Page): Promise<ChatModel[]> {
  const corpus = await getActiveCorpus(page);
  const qs = corpus ? `?corpus_id=${encodeURIComponent(corpus)}` : '';
  const modelsResp = await page.request.get(`${API_BASE}/chat/models${qs}`);
  if (!modelsResp.ok()) return [];
  const payload = await modelsResp.json();
  const models = Array.isArray((payload as any)?.models) ? (payload as any).models : [];
  return models.map((m: any) => ({
    id: String(m?.id || ''),
    provider: String(m?.provider || ''),
    source: String(m?.source || ''),
    override: String(m?.override || ''),
  }));
}

function normalizeProvider(s: string): string {
  return String(s || '').trim().toLowerCase();
}

function toModelOverrideValue(model: ChatModel): string {
  // The picker's option values are the backend's `override` strings
  // (`litellm:<alias>`); selecting the bare id fails.
  return model.override || model.id;
}

/**
 * Known-good, cheap alias per required provider. The catalog is alphabetical, so
 * "first alias for the provider" used to pick retired upstreams
 * (`openai.gpt-3.5-turbo` answers 400 through the gateway) and the whole gate
 * failed on a dead model rather than a dead provider. Override with
 * `EXHAUSTIVE_PROVIDER_MODELS="openai=openai.gpt-5.6-luna,cohere=cohere.command-r7b-12-2024"`.
 */
const PREFERRED_PROVIDER_MODELS: Record<string, string> = {
  openai: 'openai.gpt-5.6-luna',
  // Every non-local alias reaches its upstream via OpenRouter after the cutover.
  openrouter: 'openai.gpt-4.1-nano',
  cohere: 'cohere.command-r7b-12-2024',
  ...Object.fromEntries(
    String(process.env.EXHAUSTIVE_PROVIDER_MODELS || '')
      .split(',')
      .map((pair) => pair.split('=').map((part) => part.trim()))
      .filter((pair) => pair.length === 2 && pair[0] && pair[1])
      .map(([provider, alias]) => [normalizeProvider(provider), alias])
  ),
};

function pickProviderCandidate(models: ChatModel[], providerSlug: string): ChatModel | null {
  const p = normalizeProvider(providerSlug);
  const preferred = PREFERRED_PROVIDER_MODELS[p];
  if (preferred) {
    const match = models.find((m) => String(m.id || '') === preferred);
    if (match) return match;
  }
  // Aliases are `<upstream>.<model>` (all routed through LiteLLM).
  if (p === 'openrouter') {
    const match = models.find((m) => String(m.id || '') !== 'ragweld-local' && String(m.id || '').includes('.'));
    return match || null;
  }
  const exact = models.filter((m) => String(m.id || '').toLowerCase().startsWith(`${p}.`));
  if (exact.length > 0) return exact[0];
  return null;
}

export async function fetchConfigSnapshot(page: Page): Promise<any> {
  const corpus = await getActiveCorpus(page);
  const qs = corpus ? `?corpus_id=${encodeURIComponent(corpus)}` : '';
  const response = await page.request.get(`${API_BASE}/config${qs}`);
  if (!response.ok()) {
    throw new Error(`Config GET failed: ${response.status()} ${response.statusText()}`);
  }
  return await response.json();
}

export async function applyRefreshDoubleCheck(
  page: Page,
  c: ControlDescriptor,
  expectedValue?: string
): Promise<{ config_changed: boolean; persisted_after_refresh: boolean; ui_matches: boolean; apply_saved: boolean }> {
  const before = await fetchConfigSnapshot(page);
  // `saved` is false when Apply never became dirty: the control is UI-local
  // session state (theme, chat sources, model picker), not corpus config.
  const apply = await maybeApply(page);
  const afterApply = await fetchConfigSnapshot(page);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(EXTRA_WAIT_MS);
  const afterRefresh = await fetchConfigSnapshot(page);

  let uiMatches = true;
  if (expectedValue !== undefined) {
    try {
      const actual = await readControlValue(page, c);
      uiMatches = String(actual) === String(expectedValue);
    } catch {
      uiMatches = false;
    }
  }

  return {
    config_changed: JSON.stringify(before) !== JSON.stringify(afterApply),
    persisted_after_refresh: JSON.stringify(afterApply) === JSON.stringify(afterRefresh),
    ui_matches: uiMatches,
    apply_saved: apply.saved,
  };
}

async function mutateInputLike(page: Page, c: ControlDescriptor): Promise<string | null> {
  const loc = page.locator(c.selector).first();
  if (!(await safeVisible(loc)) || !(await safeEnabled(loc))) return null;

  if (c.type === 'checkbox' || c.type === 'radio') {
    await loc.click();
    return (await loc.isChecked()) ? 'true' : 'false';
  }
  if (c.type === 'range' || c.type === 'number') {
    const next = await loc.evaluate((el) => {
      const input = el as HTMLInputElement;
      const min = input.min ? Number(input.min) : 0;
      const max = input.max ? Number(input.max) : min + 100;
      const step = input.step ? Number(input.step) : 1;
      const cur = Number(input.value || min || 0);
      const bump = Number.isFinite(step) && step > 0 ? step : 1;
      const candidate = cur + bump <= max ? cur + bump : Math.max(min, cur - bump);
      input.value = String(candidate);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return String(candidate);
    });
    return String(next);
  }

  const fillValue = `exhaustive-${Date.now()}`;
  await loc.fill(fillValue);
  return fillValue;
}

async function mutateSelect(page: Page, c: ControlDescriptor): Promise<string[]> {
  const loc = page.locator(c.selector).first();
  if (!(await safeVisible(loc)) || !(await safeEnabled(loc))) return [];
  const current = await loc.inputValue();
  const options = (c.optionValues || []).filter((v) => String(v).trim().length > 0);
  const candidates = options.filter((v) => v !== current);
  const toRun = SELECT_ALL_OPTIONS ? candidates : candidates.slice(0, 1);
  const applied: string[] = [];
  for (const value of toRun) {
    await loc.selectOption(value);
    applied.push(value);
  }
  return applied;
}

function isClickLike(c: ControlDescriptor): boolean {
  return c.tag === 'button' || c.role === 'button' || (c.tag === 'input' && (c.type === 'button' || c.type === 'submit'));
}

export function isActionBlacklisted(c: ControlDescriptor, surface?: UISurface): boolean {
  if (ALLOW_DESTRUCTIVE) return false;
  // Welcome prompts are real paid/model actions. The dedicated Chat reliability
  // lane pins a runnable cloud alias and clicks one; the generic crawler must
  // not repeat that generation against whichever session model happens to be
  // persisted (for example an unavailable optional local model).
  if (c.selector.includes('chat-welcome-prompt-')) return true;
  const text = controlText(c);
  if (hasAny(text, ACTION_BLACKLIST_HINTS) || ACTION_BLACKLIST_PATTERNS.some((pattern) => pattern.test(text))) {
    return true;
  }
  // Default-deny clicks on host-action surfaces: their buttons start training,
  // containers, host processes, indexing or paid runs whatever their label says.
  if (surface && isClickLike(c) && HOST_ACTION_SURFACE_KEYS.has(`${surface.route}|${surface.subtab || ''}`)) {
    return true;
  }
  return false;
}

/**
 * Collect failed API responses (>= 400) while an action runs, so a click that
 * hits a nonexistent endpoint or a server error is a failed action rather than
 * an "ok" click. Call `stop()` to detach and read the list.
 */
export function trackFailedApiResponses(page: Page): { failures: string[]; stop: () => string[] } {
  const failures: string[] = [];
  const handler = (response: { status(): number; url(): string; request(): { method(): string } }) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
      failures.push(`${response.status()} ${response.request().method()} ${response.url()}`);
    }
  };
  page.on('response', handler);
  return {
    failures,
    stop: () => {
      page.off('response', handler);
      return failures;
    },
  };
}

export async function executeControlAction(
  page: Page,
  c: ControlDescriptor
): Promise<Array<{ action: string; expected?: string }>> {
  if (c.disabled) return [];
  if (isNeverTouchControl(c)) return [];
  if (isActionBlacklisted(c)) return [];

  const loc = page.locator(c.selector).first();
  if (!(await safeVisible(loc)) || !(await safeEnabled(loc))) return [];

  if (c.tag === 'select') {
    const changed = await mutateSelect(page, c);
    return changed.map((v) => ({ action: `select:${v}`, expected: v }));
  }
  if (c.tag === 'input' || c.tag === 'textarea') {
    const expected = await mutateInputLike(page, c);
    if (expected === null) return [];
    return [{ action: `mutate:${c.tag}:${c.type || 'text'}`, expected }];
  }

  // Generic button-like click.
  await loc.click();
  return [{ action: `click:${c.tag}:${c.role || 'none'}` }];
}

/** Pin the chat model picker to one gateway alias (its option value is the backend `override`). */
export async function selectChatModel(page: Page, alias: string): Promise<ChatModel> {
  const models = await listChatModels(page);
  const model = models.find((m) => m.id === alias);
  if (!model) {
    throw new Error(`chat model alias "${alias}" is not advertised by /api/chat/models for the active corpus`);
  }
  const picker = page.locator('[data-testid="model-picker"]').first();
  await expect(picker).toBeVisible({ timeout: 60_000 });
  await picker.selectOption(toModelOverrideValue(model));
  return model;
}

/**
 * Select the probe corpus (and only it) as the Chat retrieval source through the
 * real source dropdown — the same operator flow `chat_reliability` drives. The
 * chat does not necessarily source the active corpus by default, and an answer
 * without the corpus in its sources is ungrounded by construction.
 */
export async function selectChatSources(page: Page, corpusId: string): Promise<void> {
  const dropdown = page.getByTestId('source-dropdown');
  const summary = dropdown.locator('summary');
  await expect(summary).toBeVisible({ timeout: 60_000 });
  await summary.click();
  const row = dropdown.locator('label').filter({ hasText: corpusId }).first();
  await expect(row, `chat source row for ${corpusId}`).toBeVisible({ timeout: 20_000 });
  const box = row.locator('input[type="checkbox"]').first();
  if (!(await box.isChecked())) await box.check();
  const recall = page.getByTestId('source-recall');
  if ((await recall.count()) > 0 && (await recall.isChecked())) await recall.uncheck();
  await summary.click();
}

/**
 * Ask one real corpus question in the Chat UI and grade the answer against the
 * probe's evidence. Thumbs-up is earned only by a grounded answer (evidence
 * present, no failure signal); anything else is thumbs-down — the feedback is
 * mined into reranker triplets, so it has to mean what it says.
 */
export async function runChatProbe(
  page: Page,
  probe: CorpusProbe,
  opts: { modelAlias?: string; corpusId?: string } = {}
): Promise<{ feedback: 'thumbsup' | 'thumbsdown'; detail: string; grounded: boolean; errorCard: string | null }> {
  await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#chat-input', { timeout: 60_000 });
  if (opts.modelAlias) await selectChatModel(page, opts.modelAlias);
  if (opts.corpusId) await selectChatSources(page, opts.corpusId);

  // assistant-ui renders each message as a `MessagePrimitive.Root` carrying
  // `data-role`; the pre-cutover `#chat-messages` container no longer exists.
  const assistantMessages = page.locator('[data-role="assistant"]');
  const baseline = await assistantMessages.count();

  await page.fill('#chat-input', probe.question);
  await page.click('#chat-send');

  // Stream lifecycle, the same terminal signal chat_reliability relies on: a new
  // assistant message mounts, the Streaming badge shows while tokens arrive and
  // hides on completion, and the composer is re-enabled. Only then is the
  // message final — either an answer with feedback controls or the typed
  // failure boundary's structured error card (which carries no feedback).
  await expect(assistantMessages).toHaveCount(baseline + 1, { timeout: 60_000 });
  const latest = assistantMessages.last();
  const streaming = page.getByText('Streaming').last();
  await expect(streaming).toBeHidden({ timeout: 10 * 60 * 1000 });
  await expect(page.locator('#chat-input')).toBeEnabled({ timeout: 60_000 });
  const errorCard = latest.locator('[data-testid="chat-structured-error-card"]');
  if ((await errorCard.count()) > 0) {
    const errorText = normalize(await errorCard.first().innerText()).slice(0, 900);
    return {
      feedback: 'thumbsdown',
      grounded: false,
      errorCard: errorText,
      detail: `generation failed (structured error card): ${errorText}`,
    };
  }
  const helpful = latest.getByRole('button', { name: 'Helpful', exact: true });
  await expect(helpful).toBeVisible({ timeout: 30_000 });
  const answerText = normalize(await latest.innerText());

  const badSignals = ['error', 'failed', 'cannot', 'unavailable', 'timeout', 'traceback', 'missing run_id'];
  const failureSignal = badSignals.find((s) => answerText.includes(s)) ?? null;
  // Every evidence group must be present (any alternative within a group).
  const groupHits = probe.evidence.map(
    (group) => group.find((term) => answerText.includes(normalize(term))) ?? null
  );
  const missingGroups = probe.evidence.filter((_group, index) => groupHits[index] === null);
  const evidenceHit = missingGroups.length === 0 ? groupHits.filter(Boolean).join('+') : null;
  const grounded = evidenceHit !== null && failureSignal === null;
  const feedback: 'thumbsup' | 'thumbsdown' = grounded ? 'thumbsup' : 'thumbsdown';

  if (feedback === 'thumbsup') {
    await helpful.click();
  } else {
    await latest.getByRole('button', { name: 'Not helpful', exact: true }).click();
  }

  return {
    feedback,
    grounded,
    errorCard: null,
    detail: `assistant_len=${answerText.length} evidence_hit=${evidenceHit ?? 'none'} missing_evidence=${
      missingGroups.length ? missingGroups.map((g) => g.join('/')).join(';') : 'none'
    } failure_signal=${failureSignal ?? 'none'}`,
  };
}

export async function runRequiredProviderCoverage(
  page: Page,
  probeForProvider: (provider: string) => CorpusProbe,
  corpusId?: string
): Promise<ProviderCoverageResult[]> {
  const models = await listChatModels(page);
  const out: ProviderCoverageResult[] = [];
  for (const provider of REQUIRED_CLOUD_PROVIDERS) {
    const candidate = pickProviderCandidate(models, provider);
    if (!candidate) {
      out.push({
        provider,
        available: false,
        tested: false,
        detail: 'No chat model candidate advertised for provider in /api/chat/models.',
      });
      continue;
    }

    await page.goto('chat?subtab=ui', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('[data-testid="model-picker"]', { timeout: 60_000 });
    const picker = page.locator('[data-testid="model-picker"]').first();
    const override = toModelOverrideValue(candidate);
    try {
      await picker.selectOption(override);
    } catch (err) {
      out.push({
        provider,
        available: true,
        tested: false,
        detail: `Failed to select model override "${override}": ${String(err)}`,
      });
      continue;
    }

    const probe = await runChatProbe(page, probeForProvider(provider), { corpusId });
    out.push({
      provider,
      available: true,
      // A structured error card means the provider path did not produce an
      // answer at all: that is a failed probe, not a tested one.
      tested: probe.errorCard === null,
      feedback: probe.feedback,
      detail: `model=${candidate.id} source=${candidate.source} provider=${candidate.provider} ${probe.detail}`,
    });
  }
  return out;
}

export async function runMetricsBudgetCheck(
  page: Page,
  retrievalMutationIndex: number
): Promise<{ checked: boolean; missing: string[]; budget: string; sample_every: number }> {
  const budget = METRICS_BUDGET;
  const sampleEvery = budget === 'high' ? 1 : budget === 'low' ? 10 : 3;
  if (retrievalMutationIndex % sampleEvery !== 0) {
    return { checked: false, missing: [], budget, sample_every: sampleEvery };
  }

  const response = await page.request.get(`${API_ORIGIN}/metrics`);
  if (!response.ok()) {
    return {
      checked: true,
      missing: [`metrics endpoint failed: ${response.status()} ${response.statusText()}`],
      budget,
      sample_every: sampleEvery,
    };
  }
  const text = await response.text();
  const missing = METRICS_MEDIUM_CORE_SET.filter((metric) => !text.includes(metric));
  return { checked: true, missing, budget, sample_every: sampleEvery };
}

export async function runEvalAndMcpSmoke(page: Page): Promise<void> {
  await page.goto('eval?subtab=analysis', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(EXTRA_WAIT_MS);
  // `#eval-run-settings-final-k` exists but lives in a legitimately collapsed
  // settings panel. Open it through the same button an operator uses before
  // checking the field, so the smoke covers both the analysis surface and its
  // run-settings disclosure without treating collapsed content as broken.
  await expect(page.getByRole('heading', { name: 'Eval Analysis' })).toBeVisible();
  const runSettings = page.getByRole('button', { name: /Run Settings/ }).first();
  if ((await safeCount(runSettings)) > 0) {
    await expect(runSettings).toBeVisible();
    if ((await runSettings.getAttribute('aria-expanded')) !== 'true') {
      await runSettings.click();
    }
    await expect(page.locator('#eval-run-settings-final-k')).toBeVisible();
  } else {
    // A freshly provisioned exhaustive corpus has no eval run yet, so the app
    // intentionally omits Run Settings and renders the typed empty state.
    await expect(page.getByRole('heading', { name: 'No Evaluation Runs Yet' })).toBeVisible();
  }

  await page.goto('infrastructure?subtab=mcp', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(EXTRA_WAIT_MS);
  const body = page.locator('#tab-infrastructure-mcp');
  if ((await safeCount(body)) > 0) {
    await expect(body).toBeVisible();
  }
}

export async function scanPropagationMirrors(
  page: Page,
  sourceSurface: UISurface,
  control: ControlDescriptor,
  expected: string
): Promise<{ checked: number; failed: string[] }> {
  if (!ENABLE_PROPAGATION_SCAN) return { checked: 0, failed: [] };
  if (!control.id && !control.name) return { checked: 0, failed: [] };

  const failed: string[] = [];
  let checked = 0;
  for (const target of UI_SURFACES) {
    if (target.route === sourceSurface.route && target.subtab === sourceSurface.subtab) continue;
    await gotoSurface(page, target);
    const controls = await collectVisibleControls(page);
    const mirrors = controls.filter(
      (c) =>
        (control.id && c.id && c.id === control.id) ||
        (control.name && c.name && c.name === control.name)
    );
    for (const mirror of mirrors) {
      checked += 1;
      try {
        const actual = await readControlValue(page, mirror);
        if (String(actual) !== String(expected)) {
          failed.push(`${target.label} -> ${mirror.selector} expected=${expected} actual=${actual}`);
        }
      } catch (err) {
        failed.push(`${target.label} -> ${mirror.selector} read_failed=${String(err)}`);
      }
    }
  }
  return { checked, failed };
}


/** Unscoped (global) config snapshot: what a corpus-scoped session must never mutate. */
export async function fetchGlobalConfigSnapshot(page: Page): Promise<Record<string, unknown>> {
  const response = await page.request.get(`${API_BASE}/config`);
  if (!response.ok()) {
    throw new Error(`Global config GET failed: ${response.status()} ${response.statusText()}`);
  }
  return (await response.json()) as Record<string, unknown>;
}

/** Top-level sections whose JSON differs between two config snapshots. */
export function diffTopLevelSections(before: Record<string, unknown>, after: Record<string, unknown>): string[] {
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  return Array.from(keys)
    .filter((key) => JSON.stringify(before[key]) !== JSON.stringify(after[key]))
    .sort();
}

export async function restoreGlobalConfig(page: Page, snapshot: Record<string, unknown>): Promise<void> {
  const response = await page.request.put(`${API_BASE}/config`, { data: snapshot });
  if (!response.ok()) {
    throw new Error(`Global config restore failed: ${response.status()} ${(await response.text()).slice(0, 300)}`);
  }
}

export class WallClockBudget {
  private readonly startedAt = Date.now();

  constructor(private readonly totalMs: number) {}

  elapsedMs(): number {
    return Date.now() - this.startedAt;
  }

  remainingMs(): number {
    return Math.max(0, this.totalMs - this.elapsedMs());
  }

  exhausted(): boolean {
    return this.remainingMs() <= 0;
  }
}
