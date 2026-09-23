/**
 * Split markdown into finished top-level blocks plus the tail that is still being written.
 *
 * A streamed answer used to be re-parsed and re-highlighted from its first character on every
 * delta. Rendered block by block, only the tail changes from frame to frame: every earlier block
 * is a string that will never change again, so its rendered element can be memoized forever.
 *
 * A block is finished once a line that starts a NEW top-level block has fully arrived (its newline
 * included) after a blank line or a closed code fence, and that line cannot continue the block
 * before it:
 * - lines inside a fenced code block never end one (``` and ~~~, the closing fence at least as
 *   long as the opening one);
 * - an indented line continues the block (list-item continuation, indented code);
 * - a list marker after a list continues the list (a loose list is one list, not two);
 * - a partial last line never decides anything.
 * Once finished, a block never changes as more text arrives, which is what makes memoizing it
 * safe (tests/unit/markdown_blocks.test.ts checks this over every prefix of a real answer).
 *
 * Link-reference and footnote definitions are document-scoped (a `[1]: url` line at the end
 * changes how a `[text][1]` link far above it renders), so a document that contains one is
 * rendered as a single block.
 */

export type MarkdownBlockSplit = {
  /** Finished segments, in order. `blocks.join('') + tail` is always the input. */
  blocks: string[];
  /** The segment still being written; may be empty. */
  tail: string;
  /** The tail ends inside a code fence that has not been closed yet. */
  tailOpenFence: boolean;
  /** A definition was seen, so the whole text is one segment (the tail). */
  documentScoped: boolean;
};

const FENCE_OPEN = /^ {0,3}(`{3,}|~{3,})(.*)$/;
const FENCE_CLOSE = /^ {0,3}(`+|~+)[ \t]*$/;
const LIST_ITEM = /^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)/;
const DEFINITION = /^ {0,3}\[[^\]\n]+\]:/;
const BLANK = /^[ \t]*$/;
const INDENTED = /^[ \t]/;

type Fence = { char: string; length: number };

export function splitMarkdownBlocks(text: string): MarkdownBlockSplit {
  const blocks: string[] = [];
  let blockStart = 0;
  let blockHasContent = false;
  let blockHasList = false;
  let pendingBoundary = false;
  let fence: Fence | null = null;
  let documentScoped = false;
  let offset = 0;

  while (offset < text.length) {
    const newline = text.indexOf('\n', offset);
    const line = text.slice(offset, newline === -1 ? text.length : newline);
    if (!fence && DEFINITION.test(line)) documentScoped = true;
    // A partial line is still arriving: it belongs to the tail and decides nothing.
    if (newline === -1) break;
    const next = newline + 1;

    if (fence) {
      const close = FENCE_CLOSE.exec(line);
      if (close && close[1][0] === fence.char && close[1].length >= fence.length) {
        fence = null;
        pendingBoundary = true;
      }
      offset = next;
      continue;
    }

    if (BLANK.test(line)) {
      if (blockHasContent) pendingBoundary = true;
      offset = next;
      continue;
    }

    if (pendingBoundary) {
      const continues = INDENTED.test(line) || (blockHasList && LIST_ITEM.test(line));
      if (!continues) {
        blocks.push(text.slice(blockStart, offset));
        blockStart = offset;
        blockHasList = false;
      }
      pendingBoundary = false;
    }

    blockHasContent = true;
    if (LIST_ITEM.test(line)) blockHasList = true;
    const open = FENCE_OPEN.exec(line);
    // A backtick fence's info string may not contain a backtick (CommonMark 4.5).
    if (open && !(open[1][0] === '`' && open[2].includes('`'))) {
      fence = { char: open[1][0], length: open[1].length };
    }
    offset = next;
  }

  if (documentScoped) {
    return { blocks: [], tail: text, tailOpenFence: fence !== null, documentScoped: true };
  }
  return { blocks, tail: text.slice(blockStart), tailOpenFence: fence !== null, documentScoped: false };
}

/** A split plus what it was computed from, so the next call can resume at the tail. */
export type IncrementalMarkdownSplit = {
  text: string;
  tailStart: number;
  split: MarkdownBlockSplit;
};

/**
 * The same result as `splitMarkdownBlocks(text)`, computed by re-scanning only the previous tail
 * when `text` extends the previous text (the streaming case). Finished blocks keep their string
 * identity across calls, so a memoized renderer compares them by reference.
 */
export function advanceMarkdownSplit(previous: IncrementalMarkdownSplit | null, text: string): IncrementalMarkdownSplit {
  if (previous && previous.text === text) return previous;
  if (previous && !previous.split.documentScoped && text.startsWith(previous.text)) {
    const rest = splitMarkdownBlocks(text.slice(previous.tailStart));
    if (!rest.documentScoped) {
      const consumed = rest.blocks.reduce((sum, block) => sum + block.length, 0);
      return {
        text,
        tailStart: previous.tailStart + consumed,
        split: {
          blocks: rest.blocks.length ? previous.split.blocks.concat(rest.blocks) : previous.split.blocks,
          tail: rest.tail,
          tailOpenFence: rest.tailOpenFence,
          documentScoped: false,
        },
      };
    }
  }
  const split = splitMarkdownBlocks(text);
  return { text, tailStart: text.length - split.tail.length, split };
}
