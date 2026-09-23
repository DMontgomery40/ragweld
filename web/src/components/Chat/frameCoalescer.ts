/**
 * Coalesce bursts of work into at most one flush per animation frame.
 *
 * A streamed answer arrives as hundreds of small deltas a second; rendering each one was the
 * dominant cost of the chat page. The stream keeps accumulating text synchronously (so nothing is
 * ever lost) and asks this coalescer for a flush; every request made before the next frame shares
 * that one flush.
 *
 * A hidden tab gets no animation frames at all, so every request also arms a timer: whichever of
 * the frame or the timer comes first runs the flush and cancels the other. Terminal events never
 * wait for either: the stream publishes its final state directly.
 */

/** The browser's frame and timer functions, injectable so the policy is testable. */
export type FrameScheduler = {
  requestFrame: (callback: () => void) => number;
  cancelFrame: (handle: number) => void;
  setTimer: (callback: () => void, ms: number) => number;
  clearTimer: (handle: number) => void;
};

export type FrameCoalescer = {
  /** Ask for a flush. Calls made before it runs share it. */
  schedule: () => void;
  /** Run the pending flush now, if there is one. */
  flushNow: () => void;
  /** Drop the pending flush without running it. */
  cancel: () => void;
  /** Whether a flush is waiting for its frame (or its timer). */
  isPending: () => boolean;
};

/** How long a flush may wait when no frame comes (a hidden tab); browsers clamp hidden-tab timers to >= 1 s anyway. */
export const FRAME_FALLBACK_MS = 100;

export function browserFrameScheduler(): FrameScheduler {
  const raf = typeof globalThis.requestAnimationFrame === 'function' ? globalThis.requestAnimationFrame.bind(globalThis) : null;
  const caf = typeof globalThis.cancelAnimationFrame === 'function' ? globalThis.cancelAnimationFrame.bind(globalThis) : null;
  return {
    requestFrame: (callback) => (raf ? raf(() => callback()) : -1),
    cancelFrame: (handle) => {
      if (caf && handle >= 0) caf(handle);
    },
    setTimer: (callback, ms) => globalThis.setTimeout(callback, ms) as unknown as number,
    clearTimer: (handle) => globalThis.clearTimeout(handle),
  };
}

export function createFrameCoalescer(
  flush: () => void,
  options: { scheduler: FrameScheduler; fallbackMs?: number },
): FrameCoalescer {
  const { scheduler } = options;
  const fallbackMs = options.fallbackMs ?? FRAME_FALLBACK_MS;
  let pending = false;
  let frame: number | null = null;
  let timer: number | null = null;

  const disarm = () => {
    if (frame !== null) scheduler.cancelFrame(frame);
    if (timer !== null) scheduler.clearTimer(timer);
    frame = null;
    timer = null;
  };

  const run = () => {
    if (!pending) return;
    pending = false;
    disarm();
    flush();
  };

  return {
    schedule() {
      if (pending) return;
      pending = true;
      frame = scheduler.requestFrame(run);
      timer = scheduler.setTimer(run, fallbackMs);
    },
    flushNow: run,
    cancel() {
      pending = false;
      disarm();
    },
    isPending: () => pending,
  };
}
