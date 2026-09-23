// Unit rules for the Chat workbench layout (GUI-050): the per-viewer Expand/height choice is
// read defensively from localStorage, clamped to the pane, and the bottom-edge separator's
// keyboard contract never escapes [floor, pane]. Runs under `node --test` with Node's built-in
// type stripping: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  CHAT_WORKBENCH_KEY_STEP_PX,
  CHAT_WORKBENCH_MIN_PX,
  CHAT_WORKBENCH_PAGE_STEP_PX,
  DEFAULT_CHAT_PANE_LAYOUT,
  chatPaneLayoutKey,
  chatWorkbenchHeightForKey,
  chatWorkbenchMaxHeight,
  readChatPaneLayout,
  resolveChatWorkbenchHeight,
  writeChatPaneLayout,
} from '../../src/components/Chat/chatPaneLayout.ts';

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => (data.has(key) ? data.get(key)! : null),
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  };
}

const throwingStorage = {
  getItem: (): string | null => {
    throw new Error('SecurityError: storage blocked');
  },
  setItem: (): void => {
    throw new Error('QuotaExceededError');
  },
};

test('main and dock keep separate keys', () => {
  assert.notEqual(chatPaneLayoutKey('main'), chatPaneLayoutKey('dock'));
  const storage = memoryStorage();
  writeChatPaneLayout(storage, 'dock', { expanded: true, height: 700 });
  assert.deepEqual(readChatPaneLayout(storage, 'main'), DEFAULT_CHAT_PANE_LAYOUT);
  assert.deepEqual(readChatPaneLayout(storage, 'dock'), { expanded: true, height: 700 });
});

test('stored values are validated, never trusted', () => {
  const cases: Array<[string | null, { expanded: boolean; height: number | null }]> = [
    [null, DEFAULT_CHAT_PANE_LAYOUT],
    ['', DEFAULT_CHAT_PANE_LAYOUT],
    ['not json', DEFAULT_CHAT_PANE_LAYOUT],
    ['null', DEFAULT_CHAT_PANE_LAYOUT],
    ['42', DEFAULT_CHAT_PANE_LAYOUT],
    ['{"expanded":"yes","height":"900"}', { expanded: false, height: null }],
    ['{"expanded":true,"height":120}', { expanded: true, height: null }],
    ['{"expanded":false,"height":1e999}', { expanded: false, height: null }],
    ['{"expanded":false,"height":812.6}', { expanded: false, height: 813 }],
    [`{"expanded":true,"height":${CHAT_WORKBENCH_MIN_PX}}`, { expanded: true, height: CHAT_WORKBENCH_MIN_PX }],
  ];
  for (const [raw, expected] of cases) {
    const storage = memoryStorage(raw === null ? {} : { [chatPaneLayoutKey('main')]: raw });
    assert.deepEqual(readChatPaneLayout(storage, 'main'), expected, `stored ${String(raw)}`);
  }
});

test('blocked storage degrades to the default layout and never throws', () => {
  assert.deepEqual(readChatPaneLayout(throwingStorage, 'main'), DEFAULT_CHAT_PANE_LAYOUT);
  assert.doesNotThrow(() => writeChatPaneLayout(throwingStorage, 'main', { expanded: true, height: null }));
  assert.deepEqual(readChatPaneLayout(null, 'main'), DEFAULT_CHAT_PANE_LAYOUT);
});

test('the resolved height fills the pane unless the operator sized it, and stays within [floor, pane]', () => {
  const pane = 1093;
  const matrix: Array<[{ expanded: boolean; height: number | null }, number | null, number]> = [
    [{ expanded: false, height: null }, pane, pane],
    [{ expanded: true, height: 700 }, pane, pane],
    [{ expanded: false, height: 700 }, pane, 700],
    [{ expanded: false, height: 5000 }, pane, pane],
    // A pane shorter than the floor keeps the floor (the tab scrolls instead).
    [{ expanded: false, height: null }, 300, CHAT_WORKBENCH_MIN_PX],
    [{ expanded: true, height: null }, 300, CHAT_WORKBENCH_MIN_PX],
    [{ expanded: false, height: 700 }, 600, 600],
    // Not measured yet: the floor, never NaN.
    [{ expanded: false, height: null }, null, CHAT_WORKBENCH_MIN_PX],
  ];
  for (const [layout, available, expected] of matrix) {
    const height = resolveChatWorkbenchHeight(layout, available);
    assert.equal(height, expected, `${JSON.stringify(layout)} in ${String(available)}px`);
    assert.ok(height >= CHAT_WORKBENCH_MIN_PX);
    assert.ok(height <= chatWorkbenchMaxHeight(available));
  }
});

test('separator keys move the edge by fixed steps, clamp, and store "fill" at the pane height', () => {
  const pane = 1000;
  assert.deepEqual(chatWorkbenchHeightForKey('ArrowUp', pane, pane), { height: pane - CHAT_WORKBENCH_KEY_STEP_PX });
  assert.deepEqual(chatWorkbenchHeightForKey('PageUp', pane, pane), { height: pane - CHAT_WORKBENCH_PAGE_STEP_PX });
  assert.deepEqual(chatWorkbenchHeightForKey('ArrowDown', 700, pane), { height: 700 + CHAT_WORKBENCH_KEY_STEP_PX });
  // Reaching the pane height means "fill", so the workbench follows a taller window later.
  assert.deepEqual(chatWorkbenchHeightForKey('ArrowDown', pane - 10, pane), { height: null });
  assert.deepEqual(chatWorkbenchHeightForKey('PageDown', pane, pane), { height: null });
  assert.deepEqual(chatWorkbenchHeightForKey('End', 700, pane), { height: null });
  assert.deepEqual(chatWorkbenchHeightForKey('Home', 900, pane), { height: CHAT_WORKBENCH_MIN_PX });
  assert.deepEqual(chatWorkbenchHeightForKey('ArrowUp', CHAT_WORKBENCH_MIN_PX, pane), { height: CHAT_WORKBENCH_MIN_PX });
  assert.equal(chatWorkbenchHeightForKey('Enter', 700, pane), undefined);
  assert.equal(chatWorkbenchHeightForKey('a', 700, pane), undefined);

  // Invariant over every handled key and many starting points: the result is fill or in range.
  for (const key of ['ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End']) {
    for (let current = 0; current <= 2 * pane; current += 37) {
      const next = chatWorkbenchHeightForKey(key, current, pane);
      assert.ok(next, key);
      if (next.height !== null) {
        assert.ok(next.height >= CHAT_WORKBENCH_MIN_PX && next.height < pane, `${key} from ${current}: ${next.height}`);
      }
    }
  }
});
