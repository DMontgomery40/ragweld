// Isolated corpus provisioning for the exhaustive suite.
//
// Every spec here used to create (or reuse) a fixed `ragweld-exhaustive` corpus
// in the LIVE registry and never delete it — twice it leaked into the operator's
// corpus list as the active corpus, pointing at a deleted temp dir. This module
// is the one seam: a uniquely named corpus over the deterministic acceptance
// fixture (`tests/fixtures/acceptance_corpus`), configured so nothing about it
// touches a paid embedding or enrichment lane, with its OWN query log and
// triplets file (the defaults are the operator's shared
// `data/logs/queries.jsonl` / `data/training/triplets.jsonl`, which chat
// feedback and reranker mining would otherwise write into), indexed for real
// when asked, and deleted through the same API the operator uses (which also
// removes the corpus-scoped lineage records since #85's follow-up). The per-run
// files live under data/logs/exhaustive/<id>/ because the reranker log API only
// serves paths under data/logs/.
import { randomBytes } from 'node:crypto';
import { existsSync, rmSync } from 'node:fs';
import path from 'node:path';
import type { APIRequestContext, Page } from '@playwright/test';

export const API_BASE = process.env.EXHAUSTIVE_API_BASE_URL ?? 'http://127.0.0.1:58012/api';

// Test/probe traffic goes to a cheap paid gateway alias, never the host-served
// local model (operator rule after two machine crashes on 2026-08-22).
export const EXHAUSTIVE_CHAT_MODEL = String(process.env.EXHAUSTIVE_CHAT_MODEL || '').trim() || 'openai.gpt-5.6-luna';

const CORPUS_PREFIX = String(process.env.EXHAUSTIVE_CORPUS_PREFIX || '').trim() || 'ragweld-exhaustive';
const INDEX_TIMEOUT_MS = Number(process.env.EXHAUSTIVE_INDEX_TIMEOUT_MS ?? 5 * 60 * 1000);
const DISPOSE_ATTEMPTS = 4;

export type ExhaustiveCorpus = {
  corpusId: string;
  corpusPath: string;
  /** Per-run directory (repo-relative, under data/logs/exhaustive/) holding this corpus's query log and triplets file. */
  runDir: string;
  /**
   * DELETE the corpus (vectors, graph, registry row, lineage) and remove the
   * per-run directory. Safe to call twice; only a 2xx/404 marks it disposed, so a
   * transient failure can be retried instead of silently leaking the corpus.
   * Pass the current hook's `request` when disposing from `afterAll`: Playwright
   * refuses to reuse a `beforeAll` request context there.
   */
  dispose: (context?: APIRequestContext) => Promise<void>;
};

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Absolute path of the Aurora Tidal Observatory acceptance corpus (cwd must be the repo root). */
export function acceptanceCorpusPath(): string {
  const candidate = path.resolve(process.cwd(), 'tests', 'fixtures', 'acceptance_corpus');
  if (!existsSync(path.join(candidate, 'sensor-calibration.md'))) {
    throw new Error(
      `acceptance corpus not found at ${candidate}; run the exhaustive suite from the repo root ` +
        '(npm --prefix web exec -- playwright test --config /abs/path/playwright.exhaustive.config.ts)'
    );
  }
  return candidate;
}

export function uniqueCorpusId(): string {
  return `${CORPUS_PREFIX}-${Date.now().toString(36)}-${randomBytes(2).toString('hex')}`;
}

async function failWithBody(prefix: string, response: { status(): number; text(): Promise<string> }): Promise<never> {
  const body = (await response.text()).slice(0, 400);
  throw new Error(`${prefix} -> ${response.status()} ${body}`);
}

export async function patchCorpusConfigSection(
  request: APIRequestContext,
  corpusId: string,
  section: string,
  updates: Record<string, unknown>
): Promise<void> {
  const response = await request.patch(
    `${API_BASE}/config/${encodeURIComponent(section)}?corpus_id=${encodeURIComponent(corpusId)}`,
    { data: updates }
  );
  if (!response.ok()) await failWithBody(`PATCH /api/config/${section} for ${corpusId}`, response);
}

/**
 * Run a real index over the corpus path and wait for the persisted run to complete.
 *
 * `timeoutMs` overrides the shared deadline (`EXHAUSTIVE_INDEX_TIMEOUT_MS`, default 5 min) for
 * a spec whose run is legitimately longer — a Docling conversion plus per-figure vision calls
 * can take tens of minutes when another figure-enabled index holds the shared converter, and a
 * spec that only passes when the runner remembers an env var is a trap for the next person.
 */
export async function indexCorpus(
  request: APIRequestContext,
  corpusId: string,
  corpusPath: string,
  opts: { timeoutMs?: number; approvedGraphSchemaHash?: string } = {}
): Promise<void> {
  const timeoutMs = opts.timeoutMs ?? INDEX_TIMEOUT_MS;
  // A semantic-policy corpus indexes only against its reviewed schema hash (Task 8);
  // callers that derived a proposal pass it through, everything else stays as before.
  const started = await request.post(`${API_BASE}/index`, {
    data: {
      corpus_id: corpusId,
      repo_path: corpusPath,
      force_reindex: true,
      ...(opts.approvedGraphSchemaHash ? { approved_graph_schema_hash: opts.approvedGraphSchemaHash } : {}),
    },
  });
  if (!started.ok()) await failWithBody(`POST /api/index for ${corpusId}`, started);
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const statusResp = await request.get(`${API_BASE}/index/${encodeURIComponent(corpusId)}/status`);
    if (!statusResp.ok()) await failWithBody(`GET /api/index/${corpusId}/status`, statusResp);
    const status = (await statusResp.json()) as { status?: string; error?: string | null; progress?: number };
    if (status.status === 'complete') return;
    if (status.status === 'error' || status.status === 'cancelled') {
      throw new Error(`indexing ${corpusId} ended with status=${status.status}: ${status.error || 'no error text'}`);
    }
    await sleep(2000);
  }
  throw new Error(`indexing ${corpusId} did not complete within ${timeoutMs} ms`);
}

/**
 * Create a uniquely named corpus over the acceptance fixture, scope its config to
 * cost-free/deterministic lanes, the cheap probe model, and per-run log/triplets
 * files, and optionally index it. The caller owns disposal
 * (`try { ... } finally { await corpus.dispose(); }`).
 */
export async function provisionExhaustiveCorpus(
  request: APIRequestContext,
  opts: { index?: boolean; corpusPath?: string; indexTimeoutMs?: number } = {}
): Promise<ExhaustiveCorpus> {
  const corpusId = uniqueCorpusId();
  // Default: the Aurora acceptance fixture. A spec may point at its own materialized directory
  // (e.g. the source-viewer spec adds the deterministic PDF/HTML fixtures to a temp copy).
  const corpusPath = opts.corpusPath ?? acceptanceCorpusPath();
  // `/api/reranker/logs` only serves log paths under data/logs/ (or the OS temp dir).
  const runDir = path.posix.join('data', 'logs', 'exhaustive', corpusId);
  // Do not pre-create this as the Playwright process: exhaustive runs are often
  // launched by root through pct exec, while the API runs as `ragweld`. The API's
  // first log write must create the directory under its own runtime identity.

  const created = await request.post(`${API_BASE}/corpora`, {
    data: { corpus_id: corpusId, name: corpusId, path: corpusPath },
  });
  if (!created.ok()) await failWithBody(`POST /api/corpora (${corpusId})`, created);

  let disposed = false;
  const dispose = async (context: APIRequestContext = request): Promise<void> => {
    if (disposed) return;
    let lastError: Error | null = null;
    for (let attempt = 1; attempt <= DISPOSE_ATTEMPTS; attempt += 1) {
      // Corpus deletion clears Postgres, Qdrant, Neo4j, lineage, config and
      // per-run artifacts. Under a long headed drive that honest cleanup can
      // exceed Playwright's 30s request default even though the delete commits.
      const response = await context.delete(`${API_BASE}/corpora/${encodeURIComponent(corpusId)}`, {
        timeout: 120_000,
      });
      if (response.ok() || response.status() === 404) {
        disposed = true;
        rmSync(path.resolve(process.cwd(), runDir), { recursive: true, force: true });
        return;
      }
      lastError = new Error(`DELETE /api/corpora/${corpusId} -> ${response.status()} ${(await response.text()).slice(0, 300)}`);
      // 503 is the typed "a store is unreachable, retry" answer; anything else will not heal by waiting.
      if (response.status() !== 503) break;
      await sleep(1500 * attempt);
    }
    throw lastError ?? new Error(`DELETE /api/corpora/${corpusId} failed`);
  };

  try {
    await patchCorpusConfigSection(request, corpusId, 'embedding', { embedding_backend: 'deterministic' });
    await patchCorpusConfigSection(request, corpusId, 'generation', { enrich_disabled: true });
    await patchCorpusConfigSection(request, corpusId, 'graph_indexing', { enabled: false });
    await patchCorpusConfigSection(request, corpusId, 'reranking', { reranker_mode: 'none' });
    await patchCorpusConfigSection(request, corpusId, 'chat', { litellm: { default_model: EXHAUSTIVE_CHAT_MODEL } });
    await patchCorpusConfigSection(request, corpusId, 'ui', { chat_default_model: EXHAUSTIVE_CHAT_MODEL });
    await patchCorpusConfigSection(request, corpusId, 'evaluation', {
      ragas_judge_model: EXHAUSTIVE_CHAT_MODEL,
      promptfoo_grader_model: EXHAUSTIVE_CHAT_MODEL,
    });
    // Reranker-signal isolation: chat feedback and triplet mining for this corpus
    // must never touch the operator's shared query log / triplets file.
    await patchCorpusConfigSection(request, corpusId, 'tracing', {
      tribrid_log_path: path.posix.join(runDir, 'queries.jsonl'),
    });
    await patchCorpusConfigSection(request, corpusId, 'training', {
      tribrid_triplets_path: path.posix.join(runDir, 'triplets.jsonl'),
    });
    if (opts.index) await indexCorpus(request, corpusId, corpusPath, { timeoutMs: opts.indexTimeoutMs });
  } catch (error) {
    try {
      await dispose();
    } catch (cleanupError) {
      throw new Error(
        `provisioning ${corpusId} failed: ${error instanceof Error ? error.message : String(error)}; ` +
          `cleanup also failed, the corpus is LEAKED: ${cleanupError instanceof Error ? cleanupError.message : String(cleanupError)}`
      );
    }
    throw error;
  }
  return { corpusId, corpusPath, runDir, dispose };
}

/** Make `corpusId` the active corpus for every page load of this Playwright page. */
export async function activateCorpusInBrowser(page: Page, corpusId: string): Promise<void> {
  await page.addInitScript((cid: string) => {
    localStorage.setItem('tribrid_active_corpus', cid);
    localStorage.setItem('tribrid_active_repo', cid);
  }, corpusId);
}
