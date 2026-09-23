// Frontend RUM journeys and layout-shift attribution, independent of the Faro SDK: what reaches
// the sink (Faro's pushMeasurement / pushEvent) and in what shape, what is held while Faro is
// still starting, what is dropped when RUM is configured off, and the layout-shift sampling,
// rate-limit and region policy. The sink records the calls the Faro API would receive.
// Runs under `node --test`: `npm --prefix web run test:unit`.
import { strict as assert } from 'node:assert';
import test from 'node:test';

import {
  createRateLimiter,
  createRum,
  layoutShiftEvent,
  LAYOUT_SHIFT_POLICY,
  pickShiftRegion,
  RUM_QUEUE_LIMIT,
  type RumSink,
} from '../../src/observability/rumCore.ts';

type Call =
  | { kind: 'measurement'; type: string; values: Record<string, number>; context?: Record<string, string> }
  | { kind: 'event'; name: string; attributes?: Record<string, string> };

function recordingSink(): { sink: RumSink; calls: Call[] } {
  const calls: Call[] = [];
  return {
    calls,
    sink: {
      pushMeasurement: (payload, options) =>
        calls.push({ kind: 'measurement', type: payload.type, values: payload.values, context: options?.context }),
      pushEvent: (name, attributes) => calls.push({ kind: 'event', name, attributes }),
    },
  };
}

test('with RUM active, journeys go straight to the sink as duration measurements with their context', () => {
  const { sink, calls } = recordingSink();
  const rum = createRum(() => sink);
  rum.measure('chat_send_to_first_text', 1234.6, { model: 'openai.gpt-5.6-luna', outcome: 'ok' });
  rum.event('layout_shift', { region: 'chat-messages', phase: 'stream', value: '0.0123' });
  assert.deepEqual(calls, [
    {
      kind: 'measurement',
      type: 'chat_send_to_first_text',
      values: { duration_ms: 1235 },
      context: { model: 'openai.gpt-5.6-luna', outcome: 'ok' },
    },
    { kind: 'event', name: 'layout_shift', attributes: { region: 'chat-messages', phase: 'stream', value: '0.0123' } },
  ]);
  assert.equal(rum.queued(), 0);
});

test('before Faro starts, reports wait in a bounded queue and drain in order once it is up', () => {
  const { sink, calls } = recordingSink();
  let active: RumSink | null = null;
  const rum = createRum(() => active);
  rum.measure('app_load_to_composer_ready', 900, { surface: 'main', landing_route: 'chat' });
  for (let index = 0; index < RUM_QUEUE_LIMIT + 5; index += 1) rum.measure('conversation_switch', index, { kind: 'select' });
  assert.equal(rum.queued(), RUM_QUEUE_LIMIT, 'the queue is bounded');
  active = sink;
  rum.flush();
  assert.equal(rum.queued(), 0);
  assert.equal(calls.length, RUM_QUEUE_LIMIT);
  // The oldest were dropped: the first thing kept is the 6th switch.
  assert.deepEqual(calls[0], { kind: 'measurement', type: 'conversation_switch', values: { duration_ms: 5 }, context: { kind: 'select' } });
  // A later report also drains anything still queued, ahead of itself.
  active = null;
  rum.measure('chat_send_to_done', 10, { model: 'm', outcome: 'ok' });
  active = sink;
  rum.measure('chat_send_to_done', 20, { model: 'm', outcome: 'ok' });
  assert.deepEqual(calls.slice(-2).map((call) => (call.kind === 'measurement' ? call.values.duration_ms : -1)), [10, 20]);
});

test('RUM configured off drops the queue and ignores everything after', () => {
  const { sink, calls } = recordingSink();
  let active: RumSink | null = null;
  const rum = createRum(() => active);
  rum.measure('chat_send_to_status', 50, { model: 'm', outcome: 'ok' });
  rum.disable();
  assert.equal(rum.queued(), 0);
  active = sink;
  rum.measure('chat_send_to_status', 60, { model: 'm', outcome: 'ok' });
  rum.flush();
  assert.deepEqual(calls, []);
});

test('a sink that throws never breaks the page it measures', () => {
  const rum = createRum(() => ({
    pushMeasurement: () => {
      throw new Error('collector down');
    },
    pushEvent: () => {
      throw new Error('collector down');
    },
  }));
  assert.doesNotThrow(() => rum.measure('chat_send_to_done', 1, { model: 'm', outcome: 'error' }));
  assert.doesNotThrow(() => rum.event('layout_shift', {}));
  assert.doesNotThrow(() => rum.measure('chat_send_to_done', Number.NaN));
});

test('the rate limiter allows max per sliding window', () => {
  let now = 0;
  const limiter = createRateLimiter(3, 60_000, () => now);
  assert.deepEqual([limiter.tryTake(), limiter.tryTake(), limiter.tryTake(), limiter.tryTake()], [true, true, true, false]);
  now = 59_999;
  assert.equal(limiter.tryTake(), false);
  now = 60_000;
  assert.equal(limiter.tryTake(), true, 'the first take left the window');
});

test('a shift is charged to the region of the source that moved the most area', () => {
  assert.deepEqual(
    pickShiftRegion([
      { region: 'chat-composer', surface: 'main', area: 1200 },
      { region: 'chat-messages', surface: 'main', area: 90_000 },
      { region: 'topbar', surface: 'main', area: 40 },
    ]),
    { region: 'chat-messages', surface: 'main' },
  );
  assert.deepEqual(pickShiftRegion([{ region: 'chat-messages', surface: 'dock', area: 10 }]), { region: 'chat-messages', surface: 'dock' });
  assert.deepEqual(pickShiftRegion([]), { region: 'unknown', surface: 'main' });
});

test('layout shifts: input-driven and sub-threshold shifts are ignored, the rest sampled then rate limited', () => {
  const always = () => 0;
  const never = () => 0.99;
  const unlimited = { tryTake: () => true };
  const shift = { value: 0.0421, hadRecentInput: false, sources: [{ region: 'dock', surface: 'dock' as const, area: 5000 }] };

  assert.deepEqual(layoutShiftEvent(shift, 'idle', { random: always, limiter: unlimited }), {
    region: 'dock',
    surface: 'dock',
    phase: 'idle',
    value: '0.0421',
    sample_rate: String(LAYOUT_SHIFT_POLICY.sampleRate),
  });
  assert.equal(layoutShiftEvent({ ...shift, hadRecentInput: true }, 'idle', { random: always, limiter: unlimited }), null);
  assert.equal(layoutShiftEvent({ ...shift, value: 0.0004 }, 'load', { random: always, limiter: unlimited }), null);
  assert.equal(layoutShiftEvent(shift, 'stream', { random: never, limiter: unlimited }), null, 'sampled out');

  let now = 0;
  const limiter = createRateLimiter(LAYOUT_SHIFT_POLICY.maxPerMinute, 60_000, () => now);
  const reported = Array.from({ length: LAYOUT_SHIFT_POLICY.maxPerMinute + 10 }, () =>
    layoutShiftEvent(shift, 'stream', { random: always, limiter }),
  ).filter(Boolean);
  assert.equal(reported.length, LAYOUT_SHIFT_POLICY.maxPerMinute, 'at most maxPerMinute per minute');
  now = 60_001;
  assert.ok(layoutShiftEvent(shift, 'stream', { random: always, limiter }));
});
