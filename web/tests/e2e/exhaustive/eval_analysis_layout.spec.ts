// Eval Analysis must stay scrollable no matter how large the latest Promptfoo
// run is. Regression for the 2026-08-24 finding where the Promptfoo panel
// (200 fully-expanded result cards, ~30k px) was mounted in the fixed header
// region above the scroll container: the overflow:hidden tab root clipped the
// header at viewport height and the whole screen became unreachable —
// selectors, Run Settings, and the drill-down could not be scrolled to.
// No request interception: driven against the real app and API.
import { expect, test } from '@playwright/test';

const API_BASE = process.env.RAGWELD_API_BASE_URL ?? 'http://127.0.0.1:58012';

test('Promptfoo panel lives in the scroll container and the header fits the viewport', async ({ page, baseURL }) => {
  const consoleErrors: string[] = [];
  page.on('console', (msg) => {
    if (msg.type() === 'error') consoleErrors.push(msg.text());
  });
  page.on('pageerror', (err) => consoleErrors.push(String(err)));

  await page.goto(new URL('eval?subtab=analysis', baseURL).toString());

  const panel = page.getByTestId('promptfoo-regression-panel');
  await expect(panel).toBeAttached();

  // The bug class: an overflow:hidden ancestor (the tab root) clipping tens of
  // thousands of pixels it can never show. No hidden ancestor of the panel may
  // hold overflowing content — scrollable ancestors must sit between the panel
  // and any clipping boundary.
  const clipping = await panel.evaluate((el) => {
    const offenders: {
      tag: string;
      cls: string;
      clientHeight: number;
      scrollHeight: number;
      children: { tag: string; cls: string; h: number }[];
    }[] = [];
    let sawScrollContainer = false;
    let node: HTMLElement | null = (el as HTMLElement).parentElement;
    while (node && node !== document.body) {
      const oy = getComputedStyle(node).overflowY;
      if (oy === 'auto' || oy === 'scroll') sawScrollContainer = true;
      if (oy === 'hidden' && node.scrollHeight > node.clientHeight + 8) {
        offenders.push({
          tag: node.tagName,
          cls: String(node.className).slice(0, 80),
          clientHeight: node.clientHeight,
          scrollHeight: node.scrollHeight,
          children: Array.from(node.children).map((c) => ({
            tag: c.tagName,
            cls: String((c as HTMLElement).className).slice(0, 40),
            h: Math.round(c.getBoundingClientRect().height),
          })),
        });
      }
      node = node.parentElement;
    }
    return { offenders, sawScrollContainer };
  });
  expect(clipping.sawScrollContainer, 'Promptfoo panel has no scrollable ancestor').toBe(true);
  expect(
    clipping.offenders,
    `overflow:hidden ancestors are clipping content: ${JSON.stringify(clipping.offenders)}`,
  ).toHaveLength(0);

  // The primary controls stay truly reachable: after scrolling, Run Eval must
  // land inside the viewport and be hit-testable (not clipped away).
  const runEval = page.getByRole('button', { name: /Run Eval/ }).first();
  await runEval.scrollIntoViewIfNeeded();
  const reachable = await runEval.evaluate((el) => {
    const rect = el.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    if (cy < 0 || cy > window.innerHeight || cx < 0 || cx > window.innerWidth) {
      return { ok: false, reason: `center off-viewport at (${Math.round(cx)}, ${Math.round(cy)})` };
    }
    const hit = document.elementFromPoint(cx, cy);
    return hit && (hit === el || el.contains(hit) || hit.contains(el))
      ? { ok: true, reason: '' }
      : { ok: false, reason: `elementFromPoint hit ${hit?.tagName ?? 'nothing'}` };
  });
  expect(reachable.ok, `Run Eval button unreachable: ${reachable.reason}`).toBe(true);

  const appErrors = consoleErrors.filter((e) => !e.includes('favicon'));
  expect(appErrors, `console errors: ${appErrors.join('\n')}`).toHaveLength(0);
});

test('Promptfoo results are collapsed by default; sample-size control is present', async ({ page, baseURL, request }) => {
  await page.goto(new URL('eval?subtab=analysis', baseURL).toString());

  const panel = page.getByTestId('promptfoo-regression-panel');
  await expect(panel).toBeAttached();

  // Sample-size dropdown: bounded default so one click cannot silently launch
  // a full-dataset (~30 min, several-hundred-LLM-call) regression.
  const sampleSelect = page.getByTestId('promptfoo-sample-size');
  await expect(sampleSelect).toBeVisible();
  await expect(sampleSelect).toHaveValue('25');
  const optionValues = await sampleSelect.locator('option').evaluateAll((opts) =>
    opts.map((o) => (o as HTMLOptionElement).value),
  );
  expect(optionValues).toContain('');
  expect(optionValues).toContain('10');
  expect(optionValues).toContain('50');

  // Resolve the active corpus the panel is rendering for, then check whether
  // it has a recorded run with results. The probe is a hard assertion: a
  // broken endpoint must fail the test, not skip it silently.
  const activeCorpus = await page.evaluate(() => window.localStorage.getItem('tribrid_active_corpus'));
  test.skip(!activeCorpus, 'no active corpus resolved — collapse assertions need a corpus with a recorded Promptfoo run');
  const runsResp = await request.get(`${API_BASE}/api/eval/promptfoo/runs?corpus_id=${activeCorpus}`);
  expect(runsResp.ok(), `promptfoo runs probe failed: ${runsResp.status()}`).toBeTruthy();
  const runs = (await runsResp.json())?.runs ?? [];
  const latest = runs[0];
  test.skip(
    !latest || !(latest.results?.length > 0),
    `corpus ${activeCorpus} has no recorded Promptfoo run with results — collapse assertions cannot execute (visible skip, not a silent pass)`,
  );

  // With a recorded run present, the per-entry cards must be hidden behind a
  // collapsed section until the operator expands it.
  const resultsSection = panel.getByRole('button', { name: /Run results/ });
  await expect(resultsSection).toBeVisible();
  await expect(resultsSection).toHaveAttribute('aria-expanded', 'false');
  const firstCard = panel.getByTestId('promptfoo-result-card').first();
  await expect(firstCard).toBeHidden();

  await resultsSection.click();
  await expect(resultsSection).toHaveAttribute('aria-expanded', 'true');
  await expect(firstCard).toBeVisible();

  // Cards keep the verdict scannable but tuck the full response/grader prose
  // behind a per-card disclosure: the card itself is a <details> that starts
  // closed.
  const cardState = await firstCard.evaluate((el) => ({
    tag: el.tagName,
    open: (el as HTMLDetailsElement).open,
  }));
  expect(cardState.tag).toBe('DETAILS');
  expect(cardState.open).toBe(false);

  // Results group failures-first: the failed group (when failures exist) is
  // open, the passed group starts collapsed.
  if (latest.failed > 0) {
    const failedGroup = panel.getByTestId('promptfoo-failed-group');
    await expect(failedGroup).toBeAttached();
    expect(await failedGroup.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(true);
  }
  const passedGroup = panel.getByTestId('promptfoo-passed-group');
  await expect(passedGroup).toBeAttached();
  expect(await passedGroup.evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
});

test('System Prompts render as collapsed disclosures that expand per card', async ({ page, baseURL }) => {
  await page.goto(new URL('eval?subtab=prompts', baseURL).toString());

  const cards = page.getByTestId('system-prompt-card');
  await expect(cards.first(), 'no system prompt cards rendered').toBeAttached();
  const count = await cards.count();

  // Every card is a <details> and starts closed — the subtab must scan as a
  // compact list, not a wall of expanded prompt bodies (2026-08-24 finding).
  for (let i = 0; i < count; i++) {
    const state = await cards.nth(i).evaluate((el) => ({
      tag: el.tagName,
      open: (el as HTMLDetailsElement).open,
    }));
    expect(state.tag).toBe('DETAILS');
    expect(state.open, `prompt card ${i} started expanded`).toBe(false);
  }

  // A real click on the first summary opens exactly that card.
  await cards.first().locator('summary').click();
  expect(await cards.first().evaluate((d) => (d as HTMLDetailsElement).open)).toBe(true);
  if (count > 1) {
    expect(await cards.nth(1).evaluate((d) => (d as HTMLDetailsElement).open)).toBe(false);
  }
});

test('Run Configuration groups keys into response and operational tiers', async ({ page, baseURL, request }) => {
  await page.goto(new URL('eval?subtab=analysis', baseURL).toString());

  // The corpus store writes this key once corpora resolve; the panel renders
  // at the same point, so wait for it before reading.
  await expect(page.getByTestId('promptfoo-regression-panel')).toBeAttached();
  const activeCorpus = await page.evaluate(() => window.localStorage.getItem('tribrid_active_corpus'));
  test.skip(!activeCorpus, 'no active corpus resolved — config-tier assertions need a corpus with eval runs');
  const runsResp = await request.get(`${API_BASE}/api/eval/runs?corpus_id=${activeCorpus}`);
  expect(runsResp.ok(), `eval runs probe failed: ${runsResp.status()}`).toBeTruthy();
  const runs = (await runsResp.json())?.runs ?? [];
  test.skip(runs.length === 0, `corpus ${activeCorpus} has no eval runs — config-tier assertions cannot execute`);

  // Expand the Run Configuration section and assert the two-tier layout: the
  // response-affecting tier renders its category cards, the operational tier
  // exists, is labeled honestly, and starts collapsed.
  const configToggle = page.getByRole('button', { name: /Run Configuration/ });
  await expect(configToggle).toBeVisible();
  await expect(configToggle).toContainText('config keys');
  await expect(configToggle).not.toContainText('retrieval keys');
  await configToggle.click();

  const responseTier = page.getByTestId('config-tier-response');
  await expect(responseTier).toBeVisible();
  await expect(responseTier).toContainText('Affects retrieval & answers');
  // Real retrieval knobs land in the response tier…
  await expect(responseTier).toContainText('FUSION_SPARSE_WEIGHT');
  await expect(responseTier).toContainText('VECTOR_WEIGHT');
  // …and no Grafana/observability key may leak into it.
  const responseText = await responseTier.innerText();
  expect(responseText).not.toContain('GRAFANA_');
  expect(responseText).not.toContain('ALERTMANAGER_');

  const operationalTier = page.getByTestId('config-tier-operational');
  await expect(operationalTier).toBeVisible();
  const tierToggle = operationalTier.getByRole('button', { name: /Operational \/ UI/ });
  await expect(tierToggle).toHaveAttribute('aria-expanded', 'false');
  await tierToggle.click();
  await expect(tierToggle).toHaveAttribute('aria-expanded', 'true');
  // Observability keys must land in the operational tier, not "Other".
  await expect(operationalTier).toContainText('Observability & Alerts');
  await expect(operationalTier).toContainText('GRAFANA_DASHBOARD_SLUG');
  // Data-store wiring is operational but must not be filed as ignorable noise:
  // it renders under Infra & Data Stores, outside the result-safe categories.
  await expect(operationalTier).toContainText('Infra & Data Stores');
  await expect(operationalTier).toContainText('POSTGRES_URL');
});
