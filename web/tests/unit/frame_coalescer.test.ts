// The streaming renderer's frame coalescer: any number of deltas before a frame share ONE flush,
// a hidden tab (no animation frames) still flushes on the timer, and whichever of frame or timer
// fires first cancels the other. Driven by a scheduler whose frames and timers the test fires
// by hand, plus the real browser-scheduler factory under Node, which has no requestAnimationFrame
// at all: the hidden-tab case with real timers.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  browserFrameScheduler,
  createFrameCoalescer,
  FRAME_FALLBACK_MS,
  type FrameScheduler,
} from '../../src/components/Chat/frameCoalescer.ts';

/** Frames and timers queued until the test runs them, like a browser between two frames. */
function manualScheduler() {
  let nextHandle = 1;
  const frames = new Map<number, () => void>();
  const timers = new Map<number, { callback: () => void; ms: number }>();
  const scheduler: FrameScheduler = {
    requestFrame: (callback) => {
      const handle = nextHandle++;
      frames.set(handle, callback);
      return handle;
    },
    cancelFrame: (handle) => {
      frames.delete(handle);
    },
    setTimer: (callback, ms) => {
      const handle = nextHandle++;
      timers.set(handle, { callback, ms });
      return handle;
    },
    clearTimer: (handle) => {
      timers.delete(handle);
    },
  };
  return {
    scheduler,
    frames,
    timers,
    runFrame() {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback();
    },
    runTimers() {
      const pending = [...timers.values()];
      timers.clear();
      for (const { callback } of pending) callback();
    },
  };
}

test('every schedule before a frame shares one flush, and the next burst gets its own', () => {
  const clock = manualScheduler();
  let flushes = 0;
  const coalescer = createFrameCoalescer(() => (flushes += 1), { scheduler: clock.scheduler });
  for (let delta = 0; delta < 250; delta += 1) coalescer.schedule();
  assert.equal(clock.frames.size, 1, 'one frame requested for the whole burst');
  assert.equal(clock.timers.size, 1, 'one fallback timer armed for the whole burst');
  assert.equal(flushes, 0, 'nothing renders before the frame');

  clock.runFrame();
  assert.equal(flushes, 1);
  assert.equal(clock.timers.size, 0, 'the frame disarmed the fallback timer');
  assert.equal(coalescer.isPending(), false);

  coalescer.schedule();
  coalescer.schedule();
  clock.runFrame();
  assert.equal(flushes, 2);
});

test('a hidden tab gets no frames: the timer flushes instead, and cancels the frame', () => {
  const clock = manualScheduler();
  let flushes = 0;
  const coalescer = createFrameCoalescer(() => (flushes += 1), { scheduler: clock.scheduler, fallbackMs: 250 });
  coalescer.schedule();
  assert.equal([...clock.timers.values()][0].ms, 250);
  clock.runTimers();
  assert.equal(flushes, 1);
  assert.equal(clock.frames.size, 0, 'the timer disarmed the frame');
  // A frame that was already queued and fires late must not flush a second time.
  coalescer.schedule();
  const lateFrame = [...clock.frames.values()][0];
  clock.runTimers();
  lateFrame();
  assert.equal(flushes, 2);
});

test('flushNow runs only a pending flush; cancel drops it', () => {
  const clock = manualScheduler();
  let flushes = 0;
  const coalescer = createFrameCoalescer(() => (flushes += 1), { scheduler: clock.scheduler });
  coalescer.flushNow();
  assert.equal(flushes, 0, 'nothing pending, nothing flushed');
  coalescer.schedule();
  coalescer.flushNow();
  assert.equal(flushes, 1);
  assert.equal(clock.frames.size + clock.timers.size, 0);
  coalescer.schedule();
  coalescer.cancel();
  clock.runFrame();
  clock.runTimers();
  assert.equal(flushes, 1, 'a cancelled flush never runs');
});

test('the browser scheduler with no requestAnimationFrame (Node, like a hidden tab) still flushes on its timer', async () => {
  assert.equal(typeof globalThis.requestAnimationFrame, 'undefined');
  let flushes = 0;
  const coalescer = createFrameCoalescer(() => (flushes += 1), { scheduler: browserFrameScheduler(), fallbackMs: 10 });
  coalescer.schedule();
  coalescer.schedule();
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(flushes, 1);
  assert.ok(FRAME_FALLBACK_MS >= 16, 'the default fallback leaves a visible tab to its frames');
});
