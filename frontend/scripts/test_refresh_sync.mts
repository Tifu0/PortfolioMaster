import assert from 'node:assert/strict';
import { startRefreshSync } from '../lib/refresh-sync';

const encoder = new TextEncoder();
const events: string[] = [];
let polls = 0;
let stream!: ReadableStreamDefaultController<Uint8Array>;
let endPoll!: () => void;
let connected!: () => void;
const sawConnected = new Promise<void>((resolve) => {
  connected = resolve;
});
const sawPoll = new Promise<void>((resolve) => {
  endPoll = resolve;
});

const stop = startRefreshSync({
  openStream: async () =>
    new Response(
      new ReadableStream({
        start(controller) {
          stream = controller;
        },
      }),
      {
        headers: { 'Content-Type': 'text/event-stream' },
      }
    ),
  getConfig: async () => {
    polls += 1;
    endPoll();
    return { status: 'ok', refresh_interval_seconds: 0, batch_size: 50 };
  },
  onConfig() {},
  onEvent(event) {
    events.push(event.type);
    if (event.type === 'connected') connected();
  },
});

try {
  stream.enqueue(encoder.encode('data: {"type":"connec'));
  stream.enqueue(encoder.encode('ted"}\r\n\r\n: keepalive\r\n\r\n'));
  await sawConnected;
  assert.deepEqual(events, ['connected']);
  assert.equal(polls, 0, 'A healthy SSE feed does not poll config');
  stream.close();
  await sawPoll;
  assert.equal(polls, 1, 'An ended stream starts config fallback');
} finally {
  stop();
}

console.log('✓ Refresh sync SSE and fallback polling tests passed');
