// TriBridRAG - what changed between the last server-acknowledged config and the working copy.
//
// The commit model stages field edits locally: `config` is the working copy, `persisted` is the
// last server snapshot, and "Apply" is the single write. The footer needs to say HOW MANY leaf
// values are staged ("Apply 3 changes", X-04) and WHETHER any of them touch the parts of the
// config the current index was built from, so Apply can warn before it invalidates the index
// (M-08). Both come from one diff of the two documents.

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

function walk(a: unknown, b: unknown, prefix: string, out: string[]): void {
  if (isPlainObject(a) && isPlainObject(b)) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const key of keys) {
      walk(a[key], b[key], prefix ? `${prefix}.${key}` : key, out);
    }
    return;
  }
  // Arrays and scalars are leaves: compare by value. JSON.stringify is stable for the
  // JSON-shaped config documents these two always are.
  if (JSON.stringify(a) !== JSON.stringify(b)) out.push(prefix);
}

/** Dotted leaf paths whose value differs between `persisted` and `working`. */
export function changedConfigPaths(persisted: unknown, working: unknown): string[] {
  if (!persisted || !working) return [];
  const out: string[] = [];
  walk(persisted, working, '', out);
  // A top-level whole-section replacement collapses to the bare section name; keep it.
  return out.filter(Boolean);
}

/**
 * Config sections whose change invalidates the stored index: chunking (how documents were
 * split), embedding (the vector space of the dense index), tokenization (token counting that
 * feeds chunking). A staged edit under any of these means the stored index no longer matches
 * the config and a re-index may be needed. Mirrors the server's `_enforce_index_contract_lock`,
 * which refuses embedding/sparse contract changes over a populated index.
 */
export const INDEX_INVALIDATING_SECTIONS = ['chunking', 'embedding', 'tokenization'] as const;

/** The index-invalidating sections that have at least one staged change. */
export function indexInvalidatingChanges(persisted: unknown, working: unknown): string[] {
  const changed = changedConfigPaths(persisted, working);
  const hit = new Set<string>();
  for (const path of changed) {
    const top = path.split('.')[0];
    if ((INDEX_INVALIDATING_SECTIONS as readonly string[]).includes(top)) hit.add(top);
  }
  return Array.from(hit);
}
