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
    id: 'chat',
    label: 'Chat',
    uid: 'ragweld-chat',
    slug: 'chat',
    description: 'Chat outcomes, error ratio, time to first text, duration, cost, tokens, feedback, and Recall gate decisions.',
  },
  {
    id: 'gateway-serving',
    label: 'Gateway & Serving',
    uid: 'ragweld-gateway-serving',
    slug: 'gateway-serving',
    description: 'LiteLLM traffic, failures, time to first token, reasoning share, and deployment health.',
  },
  {
    id: 'retrieval-indexing-graph',
    label: 'Retrieval/Indexing/Graph',
    uid: 'ragweld-retrieval-indexing-graph',
    slug: 'retrieval-indexing-graph',
    description: 'Retrieval latency by leg, graph traversal and rerank, semantic cache, and index size per corpus.',
  },
  {
    id: 'tribrid-overview',
    label: 'TriBrid Overview',
    uid: 'tribrid-overview',
    slug: 'tribrid-overview',
    description: 'Retrieval latency, rate and success, latency by leg with rerank, and index size per corpus.',
  },
  {
    id: 'tribrid-rag-metrics',
    label: 'TriBridRAG Metrics',
    uid: 'tribrid-rag-metrics',
    slug: 'tribridrag-metrics',
    description: 'Every search and indexing stage: latency, errors, throughput, and runs.',
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
    id: 'reranker-training',
    label: 'Reranker Training',
    uid: 'reranker-training',
    slug: 'reranker-training',
    description: 'Learning Reranker training runs, evaluations, promotions, and inference latency.',
  },
];

export function findGrafanaPreset(uid: string, slug: string) {
  const normalizedUid = String(uid || '').trim();
  const normalizedSlug = String(slug || normalizedUid).trim() || normalizedUid;
  return GRAFANA_DASHBOARD_PRESETS.find(
    (preset) => preset.uid === normalizedUid && preset.slug === normalizedSlug,
  ) || null;
}
