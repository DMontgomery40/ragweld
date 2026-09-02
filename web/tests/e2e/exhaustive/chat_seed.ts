// Seeding a chat thread from REAL retrieval, for specs that assert on citation rendering.
//
// Citations are a view over retrieval evidence, not over generation, so a spec about how a
// citation renders should not depend on a paid gateway model being reachable — nor should it
// pay for one on every run. `seedAnswerFromSearch` runs the real `POST /api/search` the chat
// pipeline would run, then writes a thread into localStorage whose assistant message carries
// exactly those matches as its sources. Nothing is mocked or stubbed: the sources rendered in
// the browser are the bytes the retrieval API returned.
import { expect, type APIRequestContext, type Page } from '@playwright/test';
import { API_BASE } from './corpus_fixture';

/**
 * The subset of `ChunkMatch` these specs read. Deliberately a local read shape rather than the
 * generated wire type: `metadata` is `Record<string, unknown>` on the wire, and a spec asserting
 * on `metadata.chunk_kind` is reading indexer output, not a registered contract.
 */
export type SeededMatch = {
  file_path: string;
  content: string;
  metadata?: Record<string, unknown> | null;
  provenance?: { extraction?: string | null; page_start?: number | null; regions?: { page: number }[] } | null;
};

export type SeedOptions = {
  /** Retrieval breadth. Shapes the citation list the spec then asserts on. */
  topK?: number;
  /** Names the seeded conversation, so a failure screenshot says which spec wrote it. */
  label?: string;
  /**
   * Keep the threads already seeded on this page and add this one as the active conversation.
   * Init scripts stack in registration order, so a later call reads what an earlier one wrote:
   * that is how a spec seeds two real conversations and switches between them.
   */
  append?: boolean;
};

/** One real retrieval run: the matches it returned and the run id the API recorded for it. */
export type SeededRun = {
  matches: SeededMatch[];
  /** `debug.observability_run_id` -- the run `/api/traces/latest` will serve for this corpus. */
  runId: string;
};

/**
 * Run the retrieval the chat pipeline runs, and report the run it was recorded under.
 *
 * Exported because a spec about the Routing Trace needs a run on the corpus that no
 * conversation produced, which is the same call without the seeding.
 */
export async function runSeedSearch(
  request: APIRequestContext,
  corpusId: string,
  query: string,
  topK = 8,
): Promise<SeededRun> {
  const res = await request.post(`${API_BASE}/search`, {
    data: {
      query,
      corpus_id: corpusId,
      top_k: topK,
      include_vector: true,
      include_sparse: true,
      include_graph: true,
      cache_mode: 'bypass',
    },
  });
  if (!res.ok()) throw new Error(`POST /api/search -> ${res.status()} ${(await res.text()).slice(0, 300)}`);
  const body = (await res.json()) as { matches: SeededMatch[]; debug?: Record<string, unknown> | null };
  const runId = String(body.debug?.observability_run_id || '').trim();
  expect(runId, `POST /api/search recorded no run id for: ${query}`).not.toBe('');
  return { matches: body.matches, runId };
}

/**
 * Write a thread into localStorage whose assistant message carries the results of `run` -- and
 * the run id the API recorded for it, which is what the Routing Trace panel matches a
 * conversation against.
 *
 * Applies as an init script, so it must be called before the navigation that should see it.
 * Init scripts run on EVERY navigation of the page, a `page.reload()` included, so the script
 * marks itself applied in sessionStorage (per tab; survives a reload, dies with the context)
 * and is a no-op afterwards. A spec that reloads to check persistence therefore checks the
 * app's persistence, not a re-seed.
 */
export async function seedConversationFromRun(
  page: Page,
  corpusId: string,
  query: string,
  run: SeededRun,
  opts: SeedOptions = {},
): Promise<void> {
  const label = opts.label ?? 'Exhaustive spec';
  const append = opts.append ?? false;
  const seedId = `exhaustive-seed-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  await page.addInitScript(
    ({ cid, q, sources, title, seedId, runId, append }) => {
      const appliedKey = `ragweld-exhaustive-seed-applied:${seedId}`;
      if (sessionStorage.getItem(appliedKey)) return;
      sessionStorage.setItem(appliedKey, '1');
      const now = Date.now();
      const convId = seedId;
      const session = {
        conversation_id: convId,
        created_at: now,
        updated_at: now,
        title,
        model_override: '',
        sources: { corpus_ids: [cid] },
        messages: [
          { id: `user-${now}`, role: 'user', createdAt: new Date(now).toISOString(), content: [{ type: 'text', text: q }] },
          {
            id: `assistant-${now}`,
            role: 'assistant',
            createdAt: new Date(now + 1).toISOString(),
            content: [{ type: 'text', text: 'Grounded answer seeded from retrieval (see sources).' }],
            status: { type: 'complete', reason: 'stop' },
            metadata: { unstable_state: null, unstable_annotations: [], unstable_data: [], steps: [], custom: { runId, sources } },
          },
        ],
      };
      let sessions: unknown[] = [session];
      if (append) {
        try {
          const stored = JSON.parse(localStorage.getItem('ragweld-chat-threads:v2') || 'null');
          if (stored && Array.isArray(stored.sessions)) sessions = [session, ...stored.sessions];
        } catch {
          // a corrupt store is replaced, not appended to
        }
      }
      localStorage.setItem('ragweld-chat-threads:v2', JSON.stringify({ version: 2, active_conversation_id: convId, sessions }));
      localStorage.setItem('tribrid_active_corpus', cid);
      localStorage.setItem('tribrid_active_repo', cid);
    },
    { cid: corpusId, q: query, sources: run.matches, title: label, seedId, runId: run.runId, append },
  );
}

/**
 * Seed a chat thread whose assistant message carries the REAL retrieval results for `query`
 * (`POST /api/search` against the indexed corpus), and return those matches so the caller can
 * assert its API-level preconditions before touching the DOM.
 */
export async function seedAnswerFromSearch(
  page: Page,
  request: APIRequestContext,
  corpusId: string,
  query: string,
  opts: SeedOptions = {},
): Promise<SeededMatch[]> {
  const run = await runSeedSearch(request, corpusId, query, opts.topK ?? 8);
  expect(run.matches.length, `retrieval returned no matches for: ${query}`).toBeGreaterThan(0);
  await seedConversationFromRun(page, corpusId, query, run, opts);
  return run.matches;
}
