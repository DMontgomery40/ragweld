import type { UISurface } from './types';

export const UI_SURFACES: UISurface[] = [
  { route: '/start', label: 'Get Started' },
  { route: '/dashboard', subtab: 'system', label: 'Dashboard / System Status' },
  { route: '/dashboard', subtab: 'monitoring', label: 'Dashboard / Monitoring' },
  { route: '/dashboard', subtab: 'storage', label: 'Dashboard / Storage' },
  { route: '/dashboard', subtab: 'help', label: 'Dashboard / Help' },
  { route: '/dashboard', subtab: 'glossary', label: 'Dashboard / Glossary' },
  { route: '/chat', subtab: 'ui', label: 'Chat / UI' },
  { route: '/chat', subtab: 'settings', label: 'Chat / Settings' },
  { route: '/grafana', subtab: 'dashboard', label: 'Grafana / Dashboard' },
  { route: '/grafana', subtab: 'config', label: 'Grafana / Config' },
  { route: '/benchmark', label: 'Benchmark' },
  { route: '/rag', subtab: 'data-quality', label: 'RAG / Data Quality' },
  { route: '/rag', subtab: 'retrieval', label: 'RAG / Retrieval' },
  { route: '/rag', subtab: 'graph', label: 'RAG / Graph' },
  { route: '/rag', subtab: 'reranker-config', label: 'RAG / Reranker' },
  { route: '/rag', subtab: 'learning-ranker', label: 'RAG / Learning Ranker' },
  { route: '/rag', subtab: 'learning-agent', label: 'RAG / Learning Agent Studio' },
  { route: '/rag', subtab: 'indexing', label: 'RAG / Indexing' },
  { route: '/eval', subtab: 'analysis', label: 'Eval / Analysis' },
  { route: '/eval', subtab: 'dataset', label: 'Eval / Dataset' },
  { route: '/eval', subtab: 'prompts', label: 'Eval / Prompts' },
  { route: '/eval', subtab: 'trace', label: 'Eval / Trace' },
  { route: '/infrastructure', subtab: 'services', label: 'Infrastructure / Services' },
  { route: '/infrastructure', subtab: 'docker', label: 'Infrastructure / Docker' },
  { route: '/infrastructure', subtab: 'mcp', label: 'Infrastructure / MCP' },
  { route: '/infrastructure', subtab: 'paths', label: 'Infrastructure / Paths' },
  { route: '/infrastructure', subtab: 'monitoring', label: 'Infrastructure / Monitoring' },
  { route: '/admin', subtab: 'general', label: 'Admin / General' },
  { route: '/admin', subtab: 'secrets', label: 'Admin / Secrets' },
  { route: '/admin', subtab: 'integrations', label: 'Admin / Integrations' },
];

/**
 * Retrieval probes for the isolated corpus (`tests/fixtures/acceptance_corpus`,
 * the Aurora Tidal Observatory). Real domain questions only — every answer is
 * reranker triplet-mining signal (`.claude/rules/testing.md`), so each probe
 * carries the evidence a grounded answer must contain; feedback is thumbs-up
 * only when the answer actually cites it.
 */
export type CorpusProbe = {
  question: string;
  /** Evidence groups: EVERY group must be satisfied by at least one of its alternatives. */
  evidence: string[][];
};

export const ACCEPTANCE_CORPUS_PROBES: CorpusProbe[] = [
  {
    question: 'How often is the salinity sensor array on each buoy calibrated, and against which reference standard?',
    evidence: [['45 days', '45-day'], ['halcyon']],
  },
  {
    question: 'What salinity drift between calibrations marks a sensor as suspect, and what happens to a suspect sensor?',
    evidence: [['0.3'], ['quarantin']],
  },
  {
    question: 'How are the temperature probes verified, and on what cycle?',
    evidence: [['monthly', 'every month', 'each month'], ['platinum']],
  },
  {
    question: 'Where is buoy telemetry stored, and how long is raw telemetry retained before archival?',
    evidence: [['kestreldb'], ['400 days', '400-day']],
  },
  {
    question: 'What does the Pelican gateway do to inbound telemetry frames before they are written to KestrelDB?',
    evidence: [['checksum'], ['arrival', 'timestamp', 'stamps']],
  },
  {
    question: 'When does the nightly KestrelDB compaction run and how long does it typically take?',
    evidence: [['02:15', '2:15'], ['eleven minutes', '11 minutes']],
  },
  {
    question: 'What must the duty technician do if the Pelican gateway stops emitting heartbeats for 90 seconds?',
    evidence: [['osprey'], ['standby', 'fail over', 'failover']],
  },
  {
    question: 'How long do both gateways run in mirrored observation mode after a failover?',
    evidence: [['six hours', '6 hours', 'six-hour', '6-hour']],
  },
  {
    question: 'What happens when a power interruption at the observatory lasts longer than four minutes?',
    evidence: [['generator'], ['station lead']],
  },
  {
    question: 'When was the Aurora Tidal Observatory commissioned, and how many marine technicians staff it?',
    evidence: [['2011'], ['nine', '9 ']],
  },
];

function boundedInt(raw: string | undefined, fallback: number, min: number, max: number): number {
  const value = Number(raw);
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, Math.trunc(value)));
}

/** Probes per retrieval-impacting mutation (each is one gateway chat call). */
export const RETRIEVAL_PROBES_PER_MUTATION = boundedInt(
  process.env.EXHAUSTIVE_PROBES_PER_MUTATION,
  1,
  1,
  ACCEPTANCE_CORPUS_PROBES.length
);

/** Wall-clock budget for the mutation loop; remaining surfaces are reported as skipped:budget. */
export const EXHAUSTIVE_BUDGET_MS = boundedInt(process.env.EXHAUSTIVE_BUDGET_MS, 30 * 60 * 1000, 60 * 1000, 48 * 3600 * 1000);

export const REQUIRED_CLOUD_PROVIDERS = ['openai', 'openrouter', 'cohere'] as const;

export const METRICS_BUDGET_DEFAULT = 'medium' as const;

export const METRICS_MEDIUM_CORE_SET: string[] = [
  'tribrid_search_requests_total',
  'tribrid_search_latency_seconds_count',
  'tribrid_search_stage_latency_seconds_bucket',
  'tribrid_search_stage_errors_total',
  'tribrid_search_leg_results_count_bucket',
  'tribrid_index_runs_total',
  'tribrid_index_duration_seconds_count',
  'tribrid_index_stage_latency_seconds_bucket',
  'tribrid_chunks_indexed_current',
  'tribrid_graph_entities_current',
  'tribrid_graph_relationships_current',
];

export const RETRIEVAL_IMPACT_HINTS = [
  'retrieval',
  'fusion',
  'vector',
  'sparse',
  'graph',
  'rerank',
  'eval',
  'index',
  'embedding',
  'chunk',
  'bm25',
  'top_k',
  'final_k',
];

export const NEVER_TOUCH_HINTS = [
  'api key',
  'apikey',
  'secret',
  'token',
  'webhook',
  'password',
];

/**
 * Whole-word connection/location fields: mutating a host, port, URL or path from
 * a corpus-scoped session rewires the LIVE backend's service endpoints (Neo4j,
 * Postgres, Qdrant, LiteLLM, corpus roots) — not something a UI validator may do.
 */
export const NEVER_TOUCH_PATTERNS: RegExp[] = [
  /\b(url|uri|host|hostname|port|path|paths|endpoint|dsn|database|db)\b/,
  // Search/query boxes are retrieval exercises: filling them with a generated
  // string is a placeholder query (banned) and the topbar #global-search hangs
  // the loop on every surface. Retrieval is probed through Chat with real
  // corpus questions instead.
  /\b(search|query|question)\b/,
];

export const ACTION_BLACKLIST_HINTS = [
  // Keep destructive infra actions out of default mode.
  'delete corpus',
  'remove corpus',
  'factory reset',
  'drop database',
];

/**
 * Whole-word actions the default mode never triggers: host-side training or
 * model lifecycle (MLX training and model loading crashed this machine twice;
 * operator-present only), process/container lifecycle, and paid multi-minute
 * runs (eval, promptfoo, synthetic generation, benchmarks). Chat probes stay
 * the loop's only gateway traffic. `EXHAUSTIVE_DESTRUCTIVE=1` lifts this.
 */
export const ACTION_BLACKLIST_PATTERNS: RegExp[] = [
  /\b(train|training|fine-?tune|finetune|promote|publish)\b/,
  /\b(load|unload|download|pull|warm)\b.*\bmodel\b/,
  /\b(start|launch|run|execute|deploy|trigger|submit|restart|stop|shutdown|kill|reboot|terminate|cancel)\b/,
  /\bdocker\b/,
  /\b(index now|reindex|re-index|generate|mine)\b/,
];

/**
 * Surfaces whose generic buttons reach host processes, training, containers or
 * paid runs. On these surfaces every button/role=button click is blocked in
 * default mode regardless of its label (a "Start Run" or bare "Start" carries no
 * safe-word); input/select/checkbox mutations still run through the config cycle.
 */
export const HOST_ACTION_SURFACE_KEYS = new Set<string>([
  // Onboarding buttons switch the active corpus and launch indexing on operator corpora.
  '/start|',
  '/rag|learning-ranker',
  '/rag|learning-agent',
  '/rag|indexing',
  '/rag|graph',
  '/eval|analysis',
  '/benchmark|',
  '/infrastructure|docker',
  '/infrastructure|mcp',
  '/infrastructure|services',
  '/dashboard|system',
]);
