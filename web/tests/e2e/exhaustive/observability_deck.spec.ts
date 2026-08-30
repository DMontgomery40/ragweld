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
});
