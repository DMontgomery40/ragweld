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
};

/**
 * Seed a chat thread whose assistant message carries the REAL retrieval results for `query`
 * (`POST /api/search` against the indexed corpus), and return those matches so the caller can
 * assert its API-level preconditions before touching the DOM.
 *
 * Applies as an init script, so it must be called before the navigation that should see it.
 */
export async function seedAnswerFromSearch(
  page: Page,
  request: APIRequestContext,
  corpusId: string,
  query: string,
  opts: SeedOptions = {},
): Promise<SeededMatch[]> {
  const topK = opts.topK ?? 8;
  const label = opts.label ?? 'Exhaustive spec';
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
  const matches = ((await res.json()) as { matches: SeededMatch[] }).matches;
  expect(matches.length, `retrieval returned no matches for: ${query}`).toBeGreaterThan(0);
  await page.addInitScript(
    ({ cid, q, sources, title }) => {
      const now = Date.now();
      const convId = `exhaustive-seed-${now}`;
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
            metadata: { unstable_state: null, unstable_annotations: [], unstable_data: [], steps: [], custom: { runId: `spec-${now}`, sources } },
          },
        ],
      };
      localStorage.setItem('ragweld-chat-threads:v2', JSON.stringify({ version: 2, active_conversation_id: convId, sessions: [session] }));
      localStorage.setItem('tribrid_active_corpus', cid);
      localStorage.setItem('tribrid_active_repo', cid);
    },
    { cid: corpusId, q: query, sources: matches, title: label },
  );
  return matches;
}
