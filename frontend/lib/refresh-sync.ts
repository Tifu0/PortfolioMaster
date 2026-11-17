import type { AppConfig, RefreshStreamEvent } from './types';

const HEARTBEAT_TIMEOUT_MS = 15000;
const RECONNECT_DELAY_MS = 5000;

interface RefreshSyncOptions {
  openStream: (signal: AbortSignal) => Promise<Response>;
  getConfig: (signal: AbortSignal) => Promise<AppConfig>;
  onConfig: (config: AppConfig) => void;
  onEvent: (event: RefreshStreamEvent) => void;
}

/** Follow SSE while it delivers heartbeats, with config polling during interruptions. */
export function startRefreshSync({ openStream, getConfig, onConfig, onEvent }: RefreshSyncOptions): () => void {
  let stopped = false;
  let healthy = false;
  let reconnect: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setTimeout> | undefined;
  let heartbeat: ReturnType<typeof setTimeout> | undefined;
  let streamRequest: AbortController | undefined;
  let configRequest: AbortController | undefined;

  async function poll() {
    pollTimer = undefined;
    if (stopped || healthy || configRequest) return;
    const controller = new AbortController();
    configRequest = controller;
    let delay = 30000;
    try {
      const config = await getConfig(controller.signal);
      if (!stopped && !healthy && !controller.signal.aborted) {
        onConfig(config);
        if (config.is_refreshing) delay = 2000;
      }
    } catch {
      // Retry transient failures while the stream is unavailable.
    } finally {
      configRequest = undefined;
      if (!stopped && !healthy) pollTimer = setTimeout(poll, delay);
    }
  }

  async function connect() {
    const controller = new AbortController();
    streamRequest = controller;

    function watchHeartbeat() {
      clearTimeout(heartbeat);
      heartbeat = setTimeout(() => controller.abort(), HEARTBEAT_TIMEOUT_MS);
    }

    function markHealthy() {
      watchHeartbeat();
      if (!healthy) {
        healthy = true;
        clearTimeout(pollTimer);
        pollTimer = undefined;
        configRequest?.abort();
      }
    }

    watchHeartbeat();
    try {
      const response = await openStream(controller.signal);
      if (stopped || !response.ok || !response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
        return;
      }
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
      let buffer = '';
      try {
        while (!stopped) {
          const { done, value } = await reader.read();
          if (done || stopped) break;
          buffer += value;
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? '';
          for (const frame of frames) {
            const lines = frame.split(/\r?\n/);
            if (lines.some((line) => line.startsWith(':'))) markHealthy();
            const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n');
            if (!data) continue;
            let event: RefreshStreamEvent;
            try {
              event = JSON.parse(data);
              if (!event || typeof event.type !== 'string') continue;
            } catch {
              continue;
            }
            markHealthy();
            onEvent(event);
          }
        }
      } finally {
        await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    } catch {
      // A lost or stale stream enters fallback mode until it reconnects.
    } finally {
      controller.abort();
      clearTimeout(heartbeat);
      healthy = false;
      if (!stopped) {
        if (!pollTimer && !configRequest) void poll();
        reconnect = setTimeout(connect, RECONNECT_DELAY_MS);
      }
    }
  }

  void connect();
  return () => {
    stopped = true;
    clearTimeout(reconnect);
    clearTimeout(pollTimer);
    clearTimeout(heartbeat);
    streamRequest?.abort();
    configRequest?.abort();
  };
}
