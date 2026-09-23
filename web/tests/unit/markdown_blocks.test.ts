// The streaming renderer's block splitter. A finished block is memoized forever, so the one
// property that matters is that a block, once reported finished, never changes as more text
// arrives. Checked over EVERY prefix of a realistic answer (fences with blank lines, a loose list,
// a list item with a nested fence, a table, a ~~~ fence holding ```), plus the incremental path
// the renderer actually uses, which must agree with a full re-split at every step.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  advanceMarkdownSplit,
  splitMarkdownBlocks,
  type IncrementalMarkdownSplit,
} from '../../src/components/ui/markdownBlocks.ts';

const ANSWER = [
  '# Salinity sensor calibration',
  '',
  'Each buoy array is calibrated against the observatory reference standard.',
  'The interval depends on the drift the last cycle measured.',
  '',
  '## Findings',
  '- Drift stays within 0.02 PSU on most sensors.',
  '- Two sensors needed a manual review.',
  '',
  '1. Record the reference reading.',
  '',
  '2. Soak the probe for ten minutes.',
  '',
  '   Keep the probe submerged the whole time.',
  '',
  '3. Log the result:',
  '',
  '   ```bash',
  '   kestrelctl log --sensor PS-105',
  '',
  '   kestrelctl verify --sensor PS-105',
  '   ```',
  '',
  'The drift estimate:',
  '',
  '```python',
  'def drift(readings):',
  '',
  '    return sum(readings) / len(readings)',
  '',
  '',
  'print(drift([0.1, 0.2]))',
  '```',
  'Directly after the fence, a paragraph.',
  '',
  '| Sensor | Interval |',
  '|---|---:|',
  '| PS-101 | 90 |',
  '| PS-105 | 30 |',
  '',
  '> Quoted from the runbook.',
  '',
  '~~~markdown',
  '```',
  'a fence inside a tilde fence',
  '',
  '```',
  '~~~',
  '',
  '````text',
  '```',
  'still inside the four-backtick fence',
  '```',
  '````',
  '',
  'End of the answer.',
].join('\n') + '\n';

function isPrefix(shorter: string[], longer: string[]): boolean {
  return shorter.length <= longer.length && shorter.every((block, index) => longer[index] === block);
}

test('over every prefix: lossless, finished blocks never change, incremental equals a full split', () => {
  let previous: ReturnType<typeof splitMarkdownBlocks> | null = null;
  let incremental: IncrementalMarkdownSplit | null = null;
  for (let length = 0; length <= ANSWER.length; length += 1) {
    const prefix = ANSWER.slice(0, length);
    const split = splitMarkdownBlocks(prefix);
    assert.equal(split.blocks.join('') + split.tail, prefix, `lossless at ${length}`);
    assert.equal(split.documentScoped, false);
    for (const block of split.blocks) assert.ok(block.length > 0, `an empty block at ${length}`);
    if (previous) {
      assert.ok(isPrefix(previous.blocks, split.blocks), `a finished block changed between ${length - 1} and ${length}`);
    }
    const before: IncrementalMarkdownSplit | null = incremental;
    incremental = advanceMarkdownSplit(incremental, prefix);
    assert.deepEqual(incremental.split, split, `incremental split diverged at ${length}`);
    assert.equal(incremental.tailStart, length - split.tail.length);
    if (before) {
      // Finished blocks keep their identity, so a memoized renderer never re-renders them.
      before.split.blocks.forEach((block, index) => assert.equal(incremental!.split.blocks[index], block));
    }
    previous = split;
  }
});

test('the finished answer splits at real block boundaries and never inside a fence or a list', () => {
  const { blocks, tail, tailOpenFence } = splitMarkdownBlocks(ANSWER);
  assert.equal(tailOpenFence, false);
  assert.equal(tail, 'End of the answer.\n');
  const containing = (text: string) => blocks.filter((block) => block.includes(text));
  // The loose ordered list, its continuation paragraph and its nested fence are one block.
  const list = containing('1. Record the reference reading.');
  assert.equal(list.length, 1);
  for (const part of ['2. Soak the probe', 'Keep the probe submerged', 'kestrelctl log', 'kestrelctl verify']) {
    assert.ok(list[0].includes(part), `the list lost "${part}"`);
  }
  // A fence with blank lines inside is one block, ended by its closing fence; the paragraph that
  // follows the fence without a blank line starts the next block.
  const python = containing('def drift(readings):');
  assert.equal(python.length, 1);
  assert.ok(python[0].includes("print(drift([0.1, 0.2]))\n```\n"));
  assert.ok(!python[0].includes('Directly after the fence'));
  assert.equal(containing('Directly after the fence').length, 1);
  // A ``` line inside a ~~~ fence, and inside a longer backtick fence, does not close it.
  const tilde = containing('a fence inside a tilde fence');
  assert.equal(tilde.length, 1);
  assert.ok(tilde[0].startsWith('~~~markdown') && tilde[0].includes('~~~\n'));
  const four = containing('still inside the four-backtick fence');
  assert.equal(four.length, 1);
  assert.ok(four[0].startsWith('````text') && four[0].includes('````\n'));
  // The table is one block.
  assert.equal(containing('| PS-101 | 90 |').length, 1);
  assert.ok(containing('| PS-101 | 90 |')[0].includes('| PS-105 | 30 |'));
});

test('while a fence is open the tail says so, and nothing inside it is finished', () => {
  const cut = ANSWER.indexOf('    return sum');
  const split = splitMarkdownBlocks(ANSWER.slice(0, cut));
  assert.equal(split.tailOpenFence, true);
  assert.ok(split.tail.startsWith('```python'), JSON.stringify(split.tail.slice(0, 40)));
  assert.ok(split.blocks.every((block) => !block.includes('def drift')));
});

test('a partial line decides nothing', () => {
  assert.deepEqual(splitMarkdownBlocks('First paragraph.\n\nSecond').blocks, []);
  assert.deepEqual(splitMarkdownBlocks('First paragraph.\n\nSecond\n').blocks, ['First paragraph.\n\n']);
  // A list marker still arriving could continue a list: only the complete line decides.
  assert.deepEqual(splitMarkdownBlocks('1. one\n\n2').blocks, []);
  assert.deepEqual(splitMarkdownBlocks('1. one\n\n2. two\n').blocks, []);
  assert.deepEqual(splitMarkdownBlocks('1. one\n\nAfter the list.\n').blocks, ['1. one\n\n']);
});

test('a closing fence must match the opener; a backtick info string may not hold a backtick', () => {
  const short = splitMarkdownBlocks('````js\nconst a = 1;\n```\n\nstill code\n');
  assert.deepEqual(short.blocks, []);
  assert.equal(short.tailOpenFence, true);
  const notFence = splitMarkdownBlocks('``` not`a fence\n\nNext paragraph.\n');
  assert.equal(notFence.tailOpenFence, false);
  assert.deepEqual(notFence.blocks, ['``` not`a fence\n\n']);
});

test('link-reference and footnote definitions make the document one block', () => {
  for (const definition of ['[1]: https://example.org/runbook', '[^note]: The runbook, section 4.']) {
    const text = `See the [runbook][1] and the note[^note].\n\nMore text.\n\n${definition}\n`;
    const split = splitMarkdownBlocks(text);
    assert.equal(split.documentScoped, true, definition);
    assert.deepEqual(split.blocks, []);
    assert.equal(split.tail, text);
    // The incremental path reaches the same answer when the definition arrives last.
    let incremental: IncrementalMarkdownSplit | null = null;
    for (let length = 0; length <= text.length; length += 1) incremental = advanceMarkdownSplit(incremental, text.slice(0, length));
    assert.deepEqual(incremental!.split, split);
  }
});

test('text that does not extend the previous text is split from scratch', () => {
  const first = advanceMarkdownSplit(null, 'Alpha.\n\nBeta.\n\nGamma');
  const replaced = advanceMarkdownSplit(first, 'Other.\n\nText\n');
  assert.deepEqual(replaced.split, splitMarkdownBlocks('Other.\n\nText\n'));
});
