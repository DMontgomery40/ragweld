import { expect, test } from '@playwright/test';

import { API_BASE } from './corpus_fixture';

/** The component ids the deck's Integration Matrix actually renders a card for. */
const MATRIX_COMPONENT_IDS = [
  'grafana',
  'alloy',
  'otlp_export',
  'tempo',
  'mimir',
  'pyroscope',
  'faro',
  'opencost',
  'alertmanager',
  'langfuse',
  'litellm',
  'vllm',
  'flyte',
  'mlflow',
  'unsloth',
  'haystack_docling_qdrant',
];

/** The labels the API is naming on its "Operator attention needed across: ..." line. */
function attentionLabels(operatorHint: string): string[] {
  const marker = 'Operator attention needed across:';
  if (!operatorHint.startsWith(marker)) return [];
  return operatorHint
    .slice(marker.length)
    .replace(/\.$/, '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Infrastructure > Monitoring > Observability Operator Deck.
 *
 * The drive found the deck escalating a single failed HTTP probe to
 * `severity=critical` with three phantom incidents, and keeping Grafana on the
 * "Operator attention needed" line forever because its own card admitted the
 * probe could not work through the auth proxy.
 *
 * These run against the live API and the real backends it is configured with.
 */
test.describe('Observability operator deck', () => {
  test('a card\'s evidence stays inside its card, however long the identifier is', async ({ page, baseURL }) => {
    // The Grafana Command Center prints live identifiers (the Qdrant generation name, trace and
    // run ids) as single unbroken tokens. With `overflow-wrap: normal` the retrieval card's
    // generation name ran past its own card and painted over the neighbouring Evals and
    // Benchmark cards on the live deployment (drive finding S43: scrollWidth 568 in a 198px
    // card). Every evidence line must wrap inside its card.
    // The deck scopes to the active corpus from storage, not to a query parameter, and the long
    // identifier only appears for a corpus with a promoted Qdrant generation.
    await page.addInitScript(() => {
      localStorage.setItem('tribrid_active_corpus', 'epstein-files-public');
      localStorage.setItem('tribrid_active_repo', 'epstein-files-public');
    });
    await page.goto(new URL('/web/grafana?subtab=overview', baseURL).toString(), {
      waitUntil: 'domcontentloaded',
    });
    await expect(page.getByTestId('obs-chip-corpus')).toHaveText('corpus=epstein-files-public', { timeout: 60_000 });
    await expect(page.locator('.obs-card-metric').first()).toBeVisible({ timeout: 60_000 });
    await expect(page.locator('.obs-card-metric', { hasText: 'ragweld_chunks_' }).first()).toBeVisible({ timeout: 60_000 });

    const overflowing = await page.evaluate(() => {
      const selectors = ['.obs-card-metric', '.obs-card-detail', '.obs-evidence-mono', '.obs-evidence-copy'];
      const rows: { selector: string; text: string; scrollWidth: number; clientWidth: number }[] = [];
      for (const selector of selectors) {
        for (const el of Array.from(document.querySelectorAll(selector))) {
          const node = el as HTMLElement;
          if (node.scrollWidth > node.clientWidth + 1) {
            rows.push({
              selector,
              text: (node.textContent || '').trim().slice(0, 80),
              scrollWidth: node.scrollWidth,
              clientWidth: node.clientWidth,
            });
          }
        }
      }
      return rows;
    });
    expect(overflowing, 'evidence text must wrap inside its card, not spill across its neighbours').toEqual([]);
  });

  test('shows probe history per component instead of only the latest sample', async ({ page, baseURL, request }) => {
    const status = await request.get(`${API_BASE}/observability/status`);
    expect(status.status(), await status.text()).toBe(200);
    const payload = await status.json();
    const probed = payload.components.filter(
      (item: { id: string; enabled: boolean; configured: boolean }) =>
        item.enabled && item.configured && MATRIX_COMPONENT_IDS.includes(item.id),
    );
    expect(probed.length).toBeGreaterThan(0);

    await page.goto(new URL('infrastructure?subtab=monitoring', baseURL).toString());
    const first = probed[0];
    const history = page.getByTestId(`obs-probe-history-${first.id}`);
    await expect(history).toBeVisible();
    await expect(history).toContainText('last');
    await expect(history).toContainText('probes');
  });

  test('a component that cannot be probed is not an attention item', async ({ page, baseURL, request }) => {
    const status = await request.get(`${API_BASE}/observability/status`);
    const payload = await status.json();
    const unprobeable = payload.components.filter(
      (item: { id: string; probeable: boolean; enabled: boolean }) =>
        item.enabled && item.probeable === false && MATRIX_COMPONENT_IDS.includes(item.id),
    );
    test.skip(unprobeable.length === 0, 'no auth-protected surface on this deployment to assert against');

    const attention = attentionLabels(String(payload.operator_hint));
    for (const component of unprobeable) {
      // The API must not name it on the attention line...
      expect(attention).not.toContain(component.label);
      // ...and it must not read as a fault.
      expect(component.severity).toBe('info');
      expect(component.consecutive_failures).toBe(0);
    }

    await page.goto(new URL('infrastructure?subtab=monitoring', baseURL).toString());
    const card = page.getByTestId(`obs-status-${unprobeable[0].id}`);
    await expect(card).toHaveText('not probeable');
  });

  test('every incident is backed by a confirmed failure streak, never one missed probe', async ({ request }) => {
    const status = await request.get(`${API_BASE}/observability/status`);
    const statusPayload = await status.json();
    const incidents = await request.get(`${API_BASE}/observability/incidents`);
    expect(incidents.status(), await incidents.text()).toBe(200);
    const incidentPayload = await incidents.json();

    const config = await request.get(`${API_BASE}/config`);
    const threshold = Number((await config.json()).tracing.probe_failure_threshold);
    expect(threshold).toBeGreaterThanOrEqual(1);

    const byId = new Map<string, { configured: boolean; consecutive_failures: number }>(
      statusPayload.components.map((item: { id: string }) => [item.id, item]),
    );
    for (const incident of incidentPayload.incidents) {
      if (!String(incident.id).startsWith('component:')) continue;
      const component = byId.get(String(incident.id).slice('component:'.length));
      expect(component, `incident ${incident.id} has no component`).toBeTruthy();
      // Either a configuration fact, or a probe that has failed `threshold` times running.
      const justified = component!.configured === false || component!.consecutive_failures >= threshold;
      expect(justified, `incident ${incident.id} fired below the failure threshold`).toBe(true);
    }
  });

  // S14: the "incidents=" chip read `incidents?.total_count || observability?.incident_count || 0`,
  // so a loaded feed whose total_count was 0 fell through to the status snapshot's own counter
  // (computed for a different scope): "incidents=8" on Grafana Overview while the feed for the
  // same corpus said 0. The feed is the only definition now; the snapshot carries no counter.
  test('the incidents chip is the incidents feed count for the deck scope, never another counter', async ({
    page,
    baseURL,
    request,
  }) => {
    const status = await request.get(`${API_BASE}/observability/status`);
    expect(status.status(), await status.text()).toBe(200);
    const statusPayload = await status.json();
    expect(statusPayload, 'the status snapshot must not carry its own incident counter').not.toHaveProperty(
      'incident_count',
    );

    for (const route of ['grafana', 'infrastructure?subtab=monitoring']) {
      await page.goto(new URL(route, baseURL).toString());
      const chip = page.getByTestId('obs-chip-incidents').first();
      await expect(chip).toBeVisible();
      // Once loaded, the chip is a number, never a placeholder or another source's count.
      await expect(chip).toHaveText(/^incidents=\d+$/, { timeout: 60_000 });

      const scope = (await page.getByTestId('obs-chip-corpus').first().innerText()).replace(/^corpus=/, '').trim();
      const params = scope && scope !== 'global' ? `?corpus_id=${encodeURIComponent(scope)}` : '';
      const feed = await request.get(`${API_BASE}/observability/incidents${params}`);
      expect(feed.status(), await feed.text()).toBe(200);
      const total = Number((await feed.json()).total_count);
      await expect(chip, `${route}: chip must equal the feed count for scope "${scope || 'global'}"`).toHaveText(
        `incidents=${total}`,
      );
    }
  });

  test('external and in-app link rows are labelled, and Grafana says it opens read-only', async ({ page, baseURL }) => {
    await page.goto(new URL('infrastructure?subtab=monitoring', baseURL).toString());

    await expect(page.getByText('External surfaces, open in a new tab')).toBeVisible();
    await expect(page.getByText('In this app', { exact: true })).toBeVisible();
    await expect(page.getByTestId('open-grafana')).toHaveText(/read-only, anonymous/);
  });

  test('every Langfuse link says why it may not open for this account', async ({ page, baseURL, request }) => {
    const status = await request.get(`${API_BASE}/observability/status`);
    const statusPayload = await status.json();
    const langfuse = statusPayload.components.find((item: { id: string }) => item.id === 'langfuse');
    test.skip(!langfuse?.enabled, 'Langfuse is not enabled on this deployment');

    await page.goto(new URL('infrastructure?subtab=monitoring', baseURL).toString());

    // Always true: Langfuse enforces project membership on the signed-in browser
    // identity, and no server-side check can stand in for it. Every Langfuse
    // link carries that, whether or not a run has produced a trace yet.
    const chip = page.getByTestId('obs-external-link-langfuse').first();
    await expect(chip).toBeVisible();
    const tooltip = String(await chip.getAttribute('title'));
    expect(tooltip).toContain('member');
    expect(tooltip).toContain('project');
    expect(tooltip).toContain('do not have access to this trace');

    // And when a run has produced a trace, the deck states it on screen rather
    // than only on hover - either as the requirement, or as the reason the
    // per-trace link was withheld.
    const latest = await request.get(`${API_BASE}/traces/latest`);
    const traceId = String((await latest.json())?.trace?.trace_id || '').trim();
    if (!traceId) return;

    const access = await request.get(`${API_BASE}/observability/langfuse/trace/${traceId}`);
    const payload = await access.json();
    if (payload.exists) {
      const note = page.getByTestId('obs-langfuse-access-note');
      await expect(note).toBeVisible();
      await expect(note).toContainText('member');
      await expect(note).toContainText(String(payload.project));
    } else {
      const withheld = page.getByTestId('obs-langfuse-trace-notice');
      await expect(withheld).toBeVisible();
      await expect(withheld).toContainText('withheld');
    }
  });

  test('every service the defect row names can be opened from its card', async ({ page, baseURL, request }) => {
    // M-77 named ten surfaces. Prometheus and Loki have no observability status
    // component, so they need their own hrefs (tracing.prometheus_base_url and
    // the resolved URL /api/loki/status returns) rather than being left as the
    // plain <strong> the drive found.
    const [statusResponse, lokiResponse, configResponse] = await Promise.all([
      request.get(`${API_BASE}/observability/status`),
      request.get(`${API_BASE}/loki/status`),
      request.get(`${API_BASE}/config`),
    ]);
    const components = new Map<string, string>(
      (await statusResponse.json()).components.map((item: { id: string; url: string | null }) => [
        item.id,
        String(item.url || ''),
      ])
    );
    const lokiUrl = String((await lokiResponse.json())?.url || '').trim();
    const prometheusUrl = String((await configResponse.json())?.tracing?.prometheus_base_url || '').trim();

    await page.goto(new URL('infrastructure?subtab=services', baseURL).toString());

    const expected: Array<[string, string]> = [
      ['mlflow', components.get('mlflow') || ''],
      ['flyte', components.get('flyte') || ''],
      ['tempo', components.get('tempo') || ''],
      ['langfuse', components.get('langfuse') || ''],
      ['qdrant', components.get('haystack_docling_qdrant') || ''],
      ['alertmanager', components.get('alertmanager') || ''],
      ['pyroscope', components.get('pyroscope') || ''],
      ['mimir', components.get('mimir') || ''],
      ['grafana', components.get('grafana') || ''],
      ['prometheus', prometheusUrl],
      ['loki', lokiUrl],
    ];

    for (const [service, url] of expected) {
      if (!url) continue;
      const link = page.getByTestId(`open-service-${service}`);
      await expect(link, `${service} card title must be a link`).toHaveAttribute('href', url);
    }

    // Non-vacuous: the two the review caught must both have resolved a URL.
    expect(prometheusUrl, 'tracing.prometheus_base_url is unset on this deployment').not.toBe('');
    expect(lokiUrl, '/api/loki/status returned no URL').not.toBe('');
  });
});
