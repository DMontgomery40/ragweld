// Unit rules for resizable panels: which storage key a panel's remembered height lives under
// (utils/resizablePanels.ts), which stored or inline heights count as a height at all, and the
// stylesheet ratchets behind the one global CSS rule. Runs under `node --test` with Node's
// built-in type stripping: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import { readdirSync, readFileSync } from 'node:fs';
import test from 'node:test';

import { panelHeightStorageKey, parsePanelHeight } from '../../src/utils/resizablePanels.ts';

const STYLES_DIR = new URL('../../src/styles/', import.meta.url);

test('a panel is remembered per key and per surface, so the Dock never resizes the main pane', () => {
  const main = panelHeightStorageKey('chat-workbench', 'main');
  const dock = panelHeightStorageKey('chat-workbench', 'dock');
  assert.ok(main && dock);
  assert.notEqual(main, dock);
  assert.notEqual(panelHeightStorageKey('chat-routing-trace', 'main'), main);
  // The key is trimmed, so stray whitespace in markup does not fork a panel's memory.
  assert.equal(panelHeightStorageKey('  chat-workbench ', 'main'), main);
});

test('a panel without a key is resizable but not remembered', () => {
  for (const key of ['', '   ', null, undefined]) {
    assert.equal(panelHeightStorageKey(key, 'main'), null, `key ${JSON.stringify(key)}`);
    assert.equal(panelHeightStorageKey(key, 'dock'), null, `key ${JSON.stringify(key)}`);
  }
});

test('stored and inline heights parse to whole px; anything else is no height', () => {
  const cases: Array<[string | null | undefined, number | null]> = [
    ['412px', 412],
    ['412', 412],
    ['412.6px', 413],
    [' 640px ', 640],
    ['', null],
    [null, null],
    [undefined, null],
    ['0px', null],
    ['-20px', null],
    ['50%', null],
    ['auto', null],
    ['12em', null],
    ['NaN', null],
    ['calc(100% - 4px)', null],
  ];
  for (const [raw, expected] of cases) {
    assert.equal(parsePanelHeight(raw), expected, `parsePanelHeight(${JSON.stringify(raw)})`);
  }
});

// A :has() selector is re-matched on every DOM mutation; a streaming chat mutates the DOM on
// every token (claude.ai measured 24 ms per mutation from a single `:root:has()`). Folded
// panels say so with data-collapsed instead.
test('no stylesheet uses :has()', () => {
  const offenders: string[] = [];
  for (const name of readdirSync(STYLES_DIR).filter((n) => n.endsWith('.css'))) {
    readFileSync(new URL(name, STYLES_DIR), 'utf8')
      .split('\n')
      .forEach((line, i) => {
        if (line.includes(':has(')) offenders.push(`${name}:${i + 1}: ${line.trim()}`);
      });
  }
  assert.deepEqual(offenders, []);
});

test('one global rule makes every panel resizable, and a folded panel drops its dragged height', () => {
  const css = readFileSync(new URL('main.css', STYLES_DIR), 'utf8');
  // Every keyed panel everywhere, every un-keyed .settings-section outside the Dock: in the
  // narrow Dock an un-keyed panel keeps its normal flow (overflow: auto made each wide row a
  // sideways-scrolling panel). The Dock is its native pane, or the embed root of its frame.
  const rule =
    /:where\(\.settings-section:not\(:where\(\.dock-native, \.app-embed-root\[data-docked="true"\]\) \*\), \[data-resizable\]\)\s*\{([^}]*)\}/.exec(
      css,
    );
  assert.ok(rule, 'main.css has no resizable-panel rule for keyed panels and un-docked .settings-section');
  assert.match(rule[1], /resize:\s*vertical/);
  assert.match(rule[1], /overflow:\s*auto/);
  // Without it a scroll container in a column-flex pane is squeezed below its content.
  assert.match(rule[1], /flex-shrink:\s*0/);
  const folded = /:where\(\.settings-section, \[data-resizable\]\)\[data-collapsed="true"\]\s*\{([^}]*)\}/.exec(css);
  assert.ok(folded, 'main.css has no data-collapsed rule for folded panels');
  assert.match(folded[1], /height:\s*auto\s*!important/);
  assert.match(folded[1], /resize:\s*none/);
});
