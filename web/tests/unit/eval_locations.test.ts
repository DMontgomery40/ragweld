// Unit rules for eval expected locations (page/line spans per expected path) and the drill-down
// match labels. Runs under `node --test` with Node's built-in type stripping:
// `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  buildExpectedLocations,
  docMatchLabel,
  draftsFromLocations,
  formatDocSpan,
  formatLocation,
  parseExpectedPaths,
  scoredEntries,
} from '../../src/components/Evaluation/evalLocations.ts';

const PDF = 'A11_MissionReport.pdf';

test('expected paths are split, trimmed and de-duplicated', () => {
  assert.deepEqual(parseExpectedPaths(` ${PDF}, docs/a.md ,,${PDF}`), [PDF, 'docs/a.md']);
});

test('a page draft becomes a typed page location; a path without a unit stays file-only', () => {
  const { locations, error } = buildExpectedLocations([PDF, 'docs/a.md'], {
    [PDF]: { unit: 'page', start: '281', end: '282' },
    'docs/a.md': { unit: '', start: '', end: '' },
  });
  assert.equal(error, null);
  assert.deepEqual(locations, [{ path: PDF, unit: 'page', start: 281, end: 282 }]);
});

test('an empty end means a single line', () => {
  const { locations } = buildExpectedLocations(['server/api/eval.py'], {
    'server/api/eval.py': { unit: 'line', start: '120', end: '' },
  });
  assert.deepEqual(locations, [{ path: 'server/api/eval.py', unit: 'line', start: 120, end: 120 }]);
});

test('invalid spans are refused with a reason instead of being sent', () => {
  for (const draft of [
    { unit: 'page' as const, start: '', end: '4' },
    { unit: 'page' as const, start: '0', end: '4' },
    { unit: 'page' as const, start: '9', end: '3' },
    { unit: 'line' as const, start: '2.5', end: '' },
  ]) {
    const result = buildExpectedLocations([PDF], { [PDF]: draft });
    assert.deepEqual(result.locations, []);
    assert.ok(result.error && result.error.startsWith(PDF), JSON.stringify(draft));
  }
});

test('drafts round-trip from stored locations', () => {
  const stored = [{ path: PDF, unit: 'page' as const, start: 176, end: 179 }];
  const drafts = draftsFromLocations(stored);
  assert.deepEqual(buildExpectedLocations([PDF], drafts).locations, stored);
});

test('labels for locations and retrieved chunk spans', () => {
  assert.equal(formatLocation({ unit: 'page', start: 281, end: 282 }), 'pp. 281–282');
  assert.equal(formatLocation({ unit: 'page', start: 5, end: 5 }), 'p. 5');
  assert.equal(formatLocation({ unit: 'line', start: 120, end: 180 }), 'lines 120–180');
  assert.equal(formatDocSpan({ start_line: 3056, end_line: 3092, page_start: 176, page_end: 179 }), 'pp. 176–179');
  assert.equal(formatDocSpan({ start_line: 24, end_line: 30, page_start: null, page_end: null }), 'lines 24–30');
  assert.equal(formatDocSpan({ start_line: 24 }), 'line 24');
});

test('match labels separate a location hit from a right-file miss', () => {
  assert.deepEqual(docMatchLabel('location'), { label: 'location match', tone: 'hit' });
  assert.deepEqual(docMatchLabel('file'), { label: 'file match', tone: 'hit' });
  assert.equal(docMatchLabel('outside_location')?.tone, 'near');
  assert.equal(docMatchLabel('no_page_provenance')?.label, 'right file, no page data');
  assert.equal(docMatchLabel('none'), null);
  assert.equal(docMatchLabel(undefined), null);
});

test('scored entries exclude uninformative ones', () => {
  assert.equal(scoredEntries({ total: 11, uninformative_count: 11 }), 0);
  assert.equal(scoredEntries({ total: 11, uninformative_count: 3 }), 8);
  assert.equal(scoredEntries({ total: 4 }), 4);
  assert.equal(scoredEntries(null), 0);
});
