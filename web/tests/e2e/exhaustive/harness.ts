import { expect, type Locator, type Page } from '@playwright/test';
import type { ControlDescriptor, UISurface } from './types';
import {
  ACTION_BLACKLIST_HINTS,
  METRICS_MEDIUM_CORE_SET,
  NEVER_TOUCH_HINTS,
  REQUIRED_CLOUD_PROVIDERS,
  RETRIEVAL_IMPACT_HINTS,
  UI_SURFACES,
} from './suite_config';

const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:58012/api';
const ALLOW_DESTRUCTIVE = process.env.EXHAUSTIVE_DESTRUCTIVE === '1';
const SELECT_ALL_OPTIONS = process.env.EXHAUSTIVE_SELECT_ALL_OPTIONS === '1';
const ENABLE_PROPAGATION_SCAN = process.env.EXHAUSTIVE_PROPAGATION_SCAN !== '0';
const EXTRA_WAIT_MS = Number(process.env.EXHAUSTIVE_WAIT_MS ?? 500);
const METRICS_BUDGET = String(process.env.EXHAUSTIVE_METRICS_BUDGET || 'medium').toLowerCase();

type ChatModel = {
  id: string;
  provider: string;
  source: string;
};

export type ProviderCoverageResult = {
  provider: string;
  available: boolean;
  tested: boolean;
  feedback?: 'thumbsup' | 'thumbsdown';
  detail: string;
};

function surfacePath(surface: UISurface): string {
  if (!surface.subtab) return surface.route;
  const sep = surface.route.includes('?') ? '&' : '?';
  return `${surface.route}${sep}subtab=${encodeURIComponent(surface.subtab)}`;
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
  return hasAny(text, NEVER_TOUCH_HINTS);
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
      if (!hidden) node.open = true;
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
  const hasLocal = models.some((m: any) => String(m?.source || '').toLowerCase() === 'local');
  const hasCloud = models.some((m: any) => {
    const s = String(m?.source || '').toLowerCase();
    return s === 'cloud_direct' || s === 'openrouter' || s === 'ragweld';
  });
  const providers = Array.from(
    new Set(
      models
        .map((m: any) => String(m?.provider || '').trim().toLowerCase())
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
  }));
}

function normalizeProvider(s: string): string {
  return String(s || '').trim().toLowerCase();
}

function toModelOverrideValue(model: ChatModel): string {
  const source = normalizeProvider(model.source);
  if (source === 'local') return `local:${model.id}`;
  if (source === 'openrouter') return `openrouter:${model.id}`;
  if (source === 'ragweld') return `ragweld:${model.id}`;
  return model.id;
}

function pickProviderCandidate(models: ChatModel[], providerSlug: string): ChatModel | null {
  const p = normalizeProvider(providerSlug);
  if (p === 'openrouter') {
    const match = models.find((m) => normalizeProvider(m.source) === 'openrouter');
    return match || null;
  }
  const exact = models.filter((m) => normalizeProvider(m.provider) === p);
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
): Promise<{ config_changed: boolean; persisted_after_refresh: boolean; ui_matches: boolean }> {
  const before = await fetchConfigSnapshot(page);
  await maybeApply(page);
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

function isActionBlacklisted(c: ControlDescriptor): boolean {
  if (ALLOW_DESTRUCTIVE) return false;
  return hasAny(controlText(c), ACTION_BLACKLIST_HINTS);
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

export async function runChatProbe(
  page: Page,
  question: string
): Promise<{ feedback: 'thumbsup' | 'thumbsdown'; detail: string }> {
  await page.goto('/chat?subtab=ui', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#chat-input', { timeout: 60_000 });

  const assistantMessages = page.locator('#chat-messages [data-role="assistant"]');
  const baseline = await assistantMessages.count();

  await page.fill('#chat-input', question);
  await page.click('#chat-send');

  await expect(assistantMessages).toHaveCount(baseline + 1, { timeout: 10 * 60 * 1000 });
  const latest = assistantMessages.nth(baseline);
  const answerText = normalize(await latest.innerText());

  const badSignals = ['error', 'failed', 'cannot', 'unavailable', 'timeout', 'traceback', 'missing run_id'];
  const down = badSignals.some((s) => answerText.includes(s));
  const feedback: 'thumbsup' | 'thumbsdown' = down ? 'thumbsdown' : 'thumbsup';

  if (feedback === 'thumbsup') {
    await latest.getByRole('button', { name: 'Helpful' }).click();
  } else {
    await latest.getByRole('button', { name: 'Not helpful' }).click();
  }

  return { feedback, detail: `assistant_len=${answerText.length}` };
}

export async function runRequiredProviderCoverage(
  page: Page,
  questionForProvider: (provider: string) => string
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

    await page.goto('/chat?subtab=ui', { waitUntil: 'domcontentloaded' });
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

    const probe = await runChatProbe(page, questionForProvider(provider));
    out.push({
      provider,
      available: true,
      tested: true,
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

  const response = await page.request.get(`${API_BASE}/metrics`);
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
  await page.goto('/eval?subtab=analysis', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(EXTRA_WAIT_MS);
  const evalSettings = page.locator('#eval-run-settings-final-k');
  if ((await safeCount(evalSettings)) > 0) {
    await expect(evalSettings).toBeVisible();
  }

  await page.goto('/infrastructure?subtab=mcp', { waitUntil: 'domcontentloaded' });
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
