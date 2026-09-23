// In-page instruments for the chat streaming specs: React commits (through the DevTools global
// hook React calls on every commit), the root's actualDuration per commit (React 19 dev builds
// always profile the root), long tasks, the worst gap between animation frames, and, when asked,
// WHICH messages re-rendered in each commit.
//
// Nothing is mocked: the hook is the same seam React DevTools uses, installed before React
// loads, and every number comes from the real app rendering a real stream. The per-message
// attribution walks the committed fiber tree, which costs main-thread time, so it is a separate
// pass from the timing pass (a spec that reads long tasks or frame gaps runs with it off).
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { expect, type Page } from '@playwright/test';

export type StreamProbeMetrics = {
  commits: number;
  commitMs: number;
  maxCommitMs: number;
  longTasks: number;
  longTaskMs: number;
  worstFrameGapMs: number;
  frames: number;
  /** Commits in which some message other than `streamingIndex` re-rendered (attribution pass only). */
  otherMessageRenders: number;
  /** Commits in which the streaming message re-rendered (attribution pass only). */
  streamingMessageRenders: number;
  /** How many messages were in the thread, by index, and how often each re-rendered. */
  rendersByIndex: Record<string, number>;
  windowMs: number;
};

type ProbeWindow = {
  __chatProbe: {
    recording: boolean;
    attribute: boolean;
    commits: number;
    commitMs: number;
    maxCommitMs: number;
    rendersByIndex: Record<string, number>;
    otherRenders: number;
    streamingRenders: number;
    streamingIndex: number;
    longTasks: { start: number; duration: number }[];
    startedAt: number;
    stoppedAt: number;
    worstGap: number;
    frames: number;
  };
};

/**
 * Install the probe before the app loads. `attribute` enables the per-message fiber walk.
 * Must be called before `page.goto`.
 */
export async function installStreamProbe(page: Page, opts: { attribute: boolean }): Promise<void> {
  await page.addInitScript((attribute: boolean) => {
    const probe = {
      recording: false,
      attribute,
      commits: 0,
      commitMs: 0,
      maxCommitMs: 0,
      rendersByIndex: {} as Record<string, number>,
      otherRenders: 0,
      streamingRenders: 0,
      streamingIndex: -1,
      longTasks: [] as { start: number; duration: number }[],
      startedAt: 0,
      stoppedAt: 0,
      worstGap: 0,
      frames: 0,
    };
    (window as unknown as ProbeWindow).__chatProbe = probe;

    // PerformedWork: React sets it on a fiber whose component actually ran in this render.
    const PERFORMED_WORK = 1;
    const COMPONENT_TAGS = new Set([0, 1, 11, 14, 15]);
    let previous = new Set<unknown>();

    type Fiber = {
      tag: number;
      flags: number;
      type: unknown;
      memoizedProps: Record<string, unknown> | null;
      child: Fiber | null;
      sibling: Fiber | null;
    };
    const nameOf = (fiber: Fiber): string => {
      const type = fiber.type as { displayName?: string; name?: string } | null;
      return (type && (type.displayName || type.name)) || '';
    };

    // The walk runs on every commit while attribution is on (recording or not), so the first
    // recorded commit compares against the commit before it rather than an empty set.
    const attributeCommit = (root: { current: Fiber }, count: boolean) => {
      const seen = new Set<unknown>();
      const rendered = new Set<number>();
      const stack: { fiber: Fiber; index: number }[] = [{ fiber: root.current, index: -1 }];
      while (stack.length) {
        const { fiber, index } = stack.pop()!;
        seen.add(fiber);
        let messageIndex = index;
        const props = fiber.memoizedProps;
        if (nameOf(fiber) === 'MessageByIndexProvider' && props && typeof props.index === 'number') {
          messageIndex = props.index;
        }
        if (
          messageIndex >= 0 &&
          COMPONENT_TAGS.has(fiber.tag) &&
          !previous.has(fiber) &&
          (fiber.flags & PERFORMED_WORK) === PERFORMED_WORK
        ) {
          rendered.add(messageIndex);
        }
        if (fiber.sibling) stack.push({ fiber: fiber.sibling, index });
        if (fiber.child) stack.push({ fiber: fiber.child, index: messageIndex });
      }
      previous = seen;
      if (!count) return;
      for (const index of rendered) {
        probe.rendersByIndex[String(index)] = (probe.rendersByIndex[String(index)] || 0) + 1;
        if (index === probe.streamingIndex) probe.streamingRenders += 1;
      }
      if ([...rendered].some((index) => index !== probe.streamingIndex)) probe.otherRenders += 1;
    };

    (window as unknown as { __REACT_DEVTOOLS_GLOBAL_HOOK__: unknown }).__REACT_DEVTOOLS_GLOBAL_HOOK__ = {
      renderers: new Map(),
      supportsFiber: true,
      inject(renderer: unknown) {
        const id = this.renderers.size + 1;
        this.renderers.set(id, renderer);
        return id;
      },
      onScheduleFiberRoot() {},
      onCommitFiberRoot(_id: number, root: { current: Fiber & { actualDuration?: number } }) {
        if (probe.attribute) attributeCommit(root, probe.recording);
        if (!probe.recording) return;
        probe.commits += 1;
        const duration = Number(root.current.actualDuration || 0);
        probe.commitMs += duration;
        if (duration > probe.maxCommitMs) probe.maxCommitMs = duration;
      },
      onCommitFiberUnmount() {},
      onPostCommitFiberRoot() {},
      checkDCE() {},
    };

    try {
      new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          if (probe.recording) probe.longTasks.push({ start: entry.startTime, duration: entry.duration });
        }
      }).observe({ type: 'longtask', buffered: false });
    } catch {
      // longtask is Chromium-only; the specs run in Chromium
    }

    let last = 0;
    const tick = (now: number) => {
      if (probe.recording) {
        if (last) {
          const gap = now - last;
          if (gap > probe.worstGap) probe.worstGap = gap;
        }
        probe.frames += 1;
        last = now;
      } else {
        last = 0;
      }
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, opts.attribute);
}

/** Start recording. `streamingIndex` is the thread index the streaming answer will occupy. */
export async function startStreamProbe(page: Page, streamingIndex: number): Promise<void> {
  await page.evaluate((index) => {
    const probe = (window as unknown as ProbeWindow).__chatProbe;
    Object.assign(probe, {
      recording: true,
      commits: 0,
      commitMs: 0,
      maxCommitMs: 0,
      rendersByIndex: {},
      otherRenders: 0,
      streamingRenders: 0,
      streamingIndex: index,
      longTasks: [],
      startedAt: performance.now(),
      worstGap: 0,
      frames: 0,
    });
  }, streamingIndex);
}

export async function stopStreamProbe(page: Page): Promise<StreamProbeMetrics> {
  return page.evaluate(() => {
    const probe = (window as unknown as ProbeWindow).__chatProbe;
    probe.recording = false;
    probe.stoppedAt = performance.now();
    const longTasks = probe.longTasks.filter((task) => task.duration > 50);
    return {
      commits: probe.commits,
      commitMs: Math.round(probe.commitMs * 10) / 10,
      maxCommitMs: Math.round(probe.maxCommitMs * 10) / 10,
      longTasks: longTasks.length,
      longTaskMs: Math.round(longTasks.reduce((sum, task) => sum + task.duration, 0)),
      worstFrameGapMs: Math.round(probe.worstGap * 10) / 10,
      frames: probe.frames,
      otherMessageRenders: probe.otherRenders,
      streamingMessageRenders: probe.streamingRenders,
      rendersByIndex: probe.rendersByIndex,
      windowMs: Math.round(probe.stoppedAt - probe.startedAt),
    };
  });
}

// ---------------------------------------------------------------------------------------------
// The scripted gateway (chat_stream_fixture.py), spawned per spec on a free port.

export type StreamFixture = {
  baseUrl: string;
  control: (operation: string, data?: unknown) => Promise<void>;
  state: () => Promise<{ received: number; stream_requests: number; completed: number; last_model: string | null }>;
  answer: () => Promise<{ text: string; tokens: number }>;
  stop: () => Promise<void>;
};

// The control plane is driven with Node's own fetch, not a Playwright request context: a
// context from `beforeAll` cannot be reused inside a test.
export async function startStreamFixture(models: string[]): Promise<StreamFixture> {
  const provider: ChildProcessWithoutNullStreams = spawn(
    process.env.RAGWELD_TEST_PYTHON || '.venv/bin/python',
    ['web/tests/e2e/exhaustive/chat_stream_fixture.py', '0', ...models],
    { cwd: process.cwd(), stdio: 'pipe' },
  );
  let startupErrors = '';
  provider.stderr.on('data', (chunk: Buffer) => {
    startupErrors += chunk.toString();
  });
  const baseUrl = await new Promise<string>((resolve, reject) => {
    const timeout = setTimeout(() => reject(new Error('chat stream fixture did not start')), 15_000);
    let output = '';
    provider.stdout.on('data', (chunk: Buffer) => {
      output += chunk.toString();
      if (!output.includes('\n')) return;
      clearTimeout(timeout);
      resolve((JSON.parse(output.split('\n')[0]) as { base_url: string }).base_url);
    });
    provider.once('error', reject);
    provider.once('exit', (code) => reject(new Error(`chat stream fixture exited ${code}: ${startupErrors.slice(-2000)}`)));
  });
  const root = baseUrl.replace(/\/v1$/, '');
  return {
    baseUrl,
    async control(operation, data) {
      const response = await fetch(`${root}/__fixture__/${operation}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(data ?? {}),
      });
      expect(response.ok, await response.text()).toBeTruthy();
    },
    async state() {
      const response = await fetch(`${root}/__fixture__/state`);
      expect(response.ok).toBeTruthy();
      return response.json();
    },
    async answer() {
      const response = await fetch(`${root}/__fixture__/answer`);
      expect(response.ok).toBeTruthy();
      return response.json();
    },
    async stop() {
      if (provider.exitCode !== null) return;
      const exited = new Promise<void>((resolve) => provider.once('exit', () => resolve()));
      provider.kill('SIGTERM');
      await exited;
    },
  };
}
