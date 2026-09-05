import { strict as assert } from 'node:assert';
import test from 'node:test';
import { indexRunStatus } from '../../src/components/RAG/indexRunStatus.ts';

for (const saved of ['complete', 'error', 'cancelled', 'indexing', null, undefined] as const) {
  test(`current run stays running while saved history is ${saved}`, () => {
    assert.equal(indexRunStatus(false, 'indexing', saved), 'indexing');
    assert.equal(indexRunStatus(true, 'idle', saved), 'indexing');
  });
}
for (const saved of ['complete', 'error', 'cancelled'] as const) {
  test(`idle or missing current status preserves saved ${saved}`, () => {
    assert.equal(indexRunStatus(false, 'idle', saved), saved);
    assert.equal(indexRunStatus(false, null, saved), saved);
    assert.equal(indexRunStatus(false, undefined, saved), saved);
  });
}
test('without saved history the current result remains visible', () => {
  for (const current of ['idle', 'complete', 'error'] as const) {
    assert.equal(indexRunStatus(false, current, null), current);
  }
  assert.equal(indexRunStatus(false, undefined, undefined), 'idle');
});

for (const current of ['complete', 'error', 'cancelled'] as const) {
  test(`current terminal ${current} wins over delayed saved states`, () => {
    for (const saved of ['indexing', 'complete', 'error', 'cancelled', null, undefined] as const) {
      assert.equal(indexRunStatus(false, current, saved), current);
    }
  });
}
