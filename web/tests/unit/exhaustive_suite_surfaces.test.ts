// Unit rules for the exhaustive suite's surface list (S28a: the suite drove the Learning
// Reranker subtab through its pre-rename slug, which only worked because the app keeps an
// alias map for old bookmarks). Runs under `node --test` with Node's built-in type stripping:
// `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import { SUBTAB_ALIASES } from '../../src/config/subtabAliases.ts';
import { HOST_ACTION_SURFACE_KEYS, UI_SURFACES } from '../e2e/exhaustive/suite_config.ts';

function surfaceKey(route: string, subtab?: string): string {
  return `${route}|${subtab ?? ''}`;
}

test('no exhaustive surface is addressed by a renamed (aliased) subtab slug', () => {
  const stale = UI_SURFACES.filter(
    (s) => s.subtab && Object.prototype.hasOwnProperty.call(SUBTAB_ALIASES, s.subtab),
  );
  assert.deepEqual(
    stale.map((s) => surfaceKey(s.route, s.subtab)),
    [],
    'surfaces must use the canonical subtab id; the alias map exists for old bookmarks, not for the suite',
  );
});

test('every host-action surface key names a listed surface', () => {
  const listed = new Set(UI_SURFACES.map((s) => surfaceKey(s.route, s.subtab)));
  const orphans = [...HOST_ACTION_SURFACE_KEYS].filter((key) => !listed.has(key));
  assert.deepEqual(orphans, [], 'a host-action key that matches no listed surface protects nothing');
});
