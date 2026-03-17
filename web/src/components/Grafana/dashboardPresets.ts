export type GrafanaDashboardPreset = {
  id: string;
  label: string;
  uid: string;
  slug: string;
  description: string;
};

export const GRAFANA_DASHBOARD_PRESETS: GrafanaDashboardPreset[] = [
  {
    id: 'tribrid-overview',
    label: 'TriBrid Overview',
    uid: 'tribrid-overview',
    slug: 'tribrid-overview',
    description: 'Default ragweld platform dashboard.',
  },
  {
    id: 'codex-session-ingest',
    label: 'Codex Session Ingest',
    uid: 'codex-session-ingest',
    slug: 'codex-session-ingest',
    description: 'Codex session ingest progress, retrieval verification, and corpus persistence telemetry.',
  },
  {
    id: 'reranker-training',
    label: 'Reranker Training',
    uid: 'reranker-training',
    slug: 'reranker-training',
    description: 'Learning reranker training, triplet quality, promotion, inference, and diagnostics telemetry.',
  },
];

export function findGrafanaPreset(uid: string, slug: string) {
  const normalizedUid = String(uid || '').trim();
  const normalizedSlug = String(slug || normalizedUid).trim() || normalizedUid;
  return GRAFANA_DASHBOARD_PRESETS.find(
    (preset) => preset.uid === normalizedUid && preset.slug === normalizedSlug,
  ) || null;
}
