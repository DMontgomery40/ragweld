export type GrafanaDashboardPreset = {
  id: string;
  label: string;
  uid: string;
  slug: string;
  description: string;
};

export const GRAFANA_DASHBOARD_PRESETS: GrafanaDashboardPreset[] = [
  {
    id: 'oncall-overview',
    label: 'On-call Overview',
    uid: 'ragweld-oncall-overview',
    slug: 'on-call-overview',
    description: 'Landing dashboard for active incidents, SLO breaches, and recent operational change context.',
  },
  {
    id: 'gateway-serving',
    label: 'Gateway & Serving',
    uid: 'ragweld-gateway-serving',
    slug: 'gateway-serving',
    description: 'LiteLLM routing, vLLM serving, and runtime latency/error signals.',
  },
  {
    id: 'retrieval-indexing-graph',
    label: 'Retrieval/Indexing/Graph',
    uid: 'ragweld-retrieval-indexing-graph',
    slug: 'retrieval-indexing-graph',
    description: 'Qdrant vector-lane health, indexing generation truth, and graph-parity signals.',
  },
  {
    id: 'training-workflow',
    label: 'Training & Workflow',
    uid: 'ragweld-training-workflow',
    slug: 'training-workflow',
    description: 'Flyte, MLflow, Unsloth, and workflow execution telemetry.',
  },
  {
    id: 'eval-benchmark-prompt-regressions',
    label: 'Eval/Benchmark/Prompt Regressions',
    uid: 'ragweld-eval-regressions',
    slug: 'eval-benchmark-prompt-regressions',
    description: 'ML-quality dashboard for eval deltas, benchmark shifts, and prompt-set regressions.',
  },
  {
    id: 'cost-capacity',
    label: 'Cost & Capacity',
    uid: 'ragweld-cost-capacity',
    slug: 'cost-capacity',
    description: 'Cost, capacity pressure, and spend-context landing surface.',
  },
  {
    id: 'frontend-rum',
    label: 'Frontend/RUM',
    uid: 'ragweld-frontend-rum',
    slug: 'frontend-rum',
    description: 'Frontend telemetry and Faro/RUM command surface.',
  },
  {
    id: 'codex-session-ingest',
    label: 'Codex Session Ingest',
    uid: 'codex-session-ingest',
    slug: 'codex-session-ingest',
    description: 'Legacy ingest telemetry retained as a supporting dashboard.',
  },
  {
    id: 'reranker-training',
    label: 'Reranker Training',
    uid: 'reranker-training',
    slug: 'reranker-training',
    description: 'Legacy reranker training board retained during the broader workflow cutover.',
  },
];

export function findGrafanaPreset(uid: string, slug: string) {
  const normalizedUid = String(uid || '').trim();
  const normalizedSlug = String(slug || normalizedUid).trim() || normalizedUid;
  return GRAFANA_DASHBOARD_PRESETS.find(
    (preset) => preset.uid === normalizedUid && preset.slug === normalizedSlug,
  ) || null;
}
