import type { RemoteEnvelope, RemoteHealth, RemoteState } from './types';

type JsonRecord = Record<string, unknown>;
export type SendTextOptions = {
  playOnBackend?: boolean;
  capturePhoneAudio?: boolean;
  visualAfterSend?: boolean;
};
export type SttOptions = SendTextOptions & {
  sendToChat?: boolean;
};
type RequestOptions = {
  authorize?: boolean;
  timeoutMs?: number;
};
export type VisualAction = 'show' | 'hide' | 'clear' | 'generate_last';
export type MprcAction = 'play' | 'pause' | 'visual';
export type MprcCastAction = 'status' | 'refresh' | 'install' | 'start' | 'stop';
export type MprcSendOptions = {
  intent?: string;
  speakerId?: string;
};

const DEFAULT_REQUEST_TIMEOUT_MS = 10000;
const HEALTH_REQUEST_TIMEOUT_MS = 5000;
const STT_REQUEST_TIMEOUT_MS = 120000;
const MIN_REQUEST_TIMEOUT_MS = 1000;
const MAX_REQUEST_TIMEOUT_MS = 10 * 60 * 1000;
const DROPPED_MEDIA_QUERY_KEYS = new Set(['code', 'token']);

export class RemoteRequestError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly payload: unknown,
  ) {
    super(message);
    this.name = 'RemoteRequestError';
  }
}

export function isRemoteAuthError(exc: unknown): boolean {
  return exc instanceof RemoteRequestError && (exc.status === 401 || exc.status === 429);
}

function timeoutError(timeoutMs: number): Error {
  return new Error(`Remote request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
}

function normalizeTimeoutMs(timeoutMs: number | undefined): number {
  const parsed = Number(timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_REQUEST_TIMEOUT_MS;
  }
  return Math.max(MIN_REQUEST_TIMEOUT_MS, Math.min(MAX_REQUEST_TIMEOUT_MS, parsed));
}

export class RemoteClient {
  constructor(
    public readonly baseUrl: string,
    public readonly pairingCode: string,
  ) {}

  absoluteUrl(path: string): string {
    const base = this.baseUrl.replace(/\/+$/, '');
    const nextPath = path.startsWith('/') ? path : `/${path}`;
    return `${base}${nextPath}`;
  }

  authorizedUrl(path: string, params: JsonRecord = {}): string {
    const target = path.startsWith('/') ? path : `/${path}`;
    const queryStart = target.indexOf('?');
    const targetPath = queryStart >= 0 ? target.slice(0, queryStart) : target;
    const targetQuery = queryStart >= 0 ? target.slice(queryStart + 1) : '';
    const search = new URLSearchParams(targetQuery);
    for (const key of Array.from(search.keys())) {
      if (DROPPED_MEDIA_QUERY_KEYS.has(key.toLowerCase())) {
        search.delete(key);
      }
    }
    for (const [key, value] of Object.entries(params)) {
      if (!DROPPED_MEDIA_QUERY_KEYS.has(key.toLowerCase()) && value !== undefined && value !== null && String(value) !== '') {
        search.set(key, String(value));
      }
    }
    if (this.pairingCode) {
      search.set('code', this.pairingCode);
    }
    const suffix = search.toString();
    return this.absoluteUrl(`${targetPath}${suffix ? `?${suffix}` : ''}`);
  }

  apiUrl(path: string): string {
    return this.absoluteUrl(path);
  }

  websocketUrl(): string {
    const url = this.authorizedUrl('/ws');
    return url.replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
  }

  async health(): Promise<RemoteEnvelope<RemoteHealth>> {
    return this.request('GET', '/health', undefined, { authorize: false, timeoutMs: HEALTH_REQUEST_TIMEOUT_MS });
  }

  async state(): Promise<RemoteState> {
    const payload = await this.request<RemoteEnvelope<{ state: RemoteState }>>('GET', '/api/state');
    if (!payload.ok) {
      throw new Error(payload.error || 'State request failed.');
    }
    if (!payload.state || typeof payload.state !== 'object') {
      throw new Error('Remote backend returned state without a state object.');
    }
    return payload.state;
  }

  async sendText(text: string, options: SendTextOptions = {}) {
    return this.request('POST', '/api/send', {
      text,
      play_on_backend: Boolean(options.playOnBackend),
      capture_phone_audio: options.capturePhoneAudio !== false,
      visual_after_send: Boolean(options.visualAfterSend),
    });
  }

  async control(action: string, options: SendTextOptions = {}) {
    return this.request('POST', '/api/control', {
      action,
      play_on_backend: Boolean(options.playOnBackend),
      capture_phone_audio: options.capturePhoneAudio !== false,
    });
  }

  async engineStart() {
    return this.request('POST', '/api/engine/start', {});
  }

  async engineStop() {
    return this.request('POST', '/api/engine/stop', {});
  }

  async visual(prompt: string) {
    return this.request('POST', '/api/visual', { prompt, action: 'generate' });
  }

  async visualAction(action: VisualAction) {
    return this.request('POST', '/api/visual', { action });
  }

  async mprcState() {
    return this.request('GET', '/api/mprc');
  }

  async mprcSend(text: string, options: MprcSendOptions = {}) {
    return this.request('POST', '/api/mprc/send', {
      text,
      intent: String(options.intent || 'Auto'),
      speaker_id: String(options.speakerId || ''),
    });
  }

  async mprcChoice(choice: string) {
    return this.request('POST', '/api/mprc/choice', { choice });
  }

  async mprcAction(action: MprcAction) {
    return this.request('POST', `/api/mprc/${action}`, {});
  }

  async mprcCast(action: MprcCastAction, deviceName = '') {
    return this.request('POST', '/api/mprc/cast', {
      action,
      device_name: String(deviceName || ''),
    });
  }

  async clearAudio() {
    return this.request('POST', '/api/audio/clear', {});
  }

  async stt(audioBase64: string, format = 'm4a', options: SttOptions = {}) {
    return this.request('POST', '/api/stt', {
      audio_base64: audioBase64,
      format,
      send_to_chat: options.sendToChat !== false,
      play_on_backend: Boolean(options.playOnBackend),
      capture_phone_audio: options.capturePhoneAudio !== false,
      visual_after_send: Boolean(options.visualAfterSend),
    }, { timeoutMs: STT_REQUEST_TIMEOUT_MS });
  }

  private async request<T>(method: 'GET' | 'POST', path: string, body?: JsonRecord, options: RequestOptions = {}): Promise<T> {
    const url = this.apiUrl(path);
    const timeoutMs = normalizeTimeoutMs(options.timeoutMs);
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
    const init: RequestInit = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };
    if (options.authorize !== false) {
      (init.headers as JsonRecord)['X-NC-Phone-Code'] = this.pairingCode;
    }
    if (controller) {
      init.signal = controller.signal;
    }
    if (body) {
      init.body = JSON.stringify(body);
    }
    let timeout: ReturnType<typeof setTimeout> | null = null;
    let response: Response;
    try {
      if (controller) {
        timeout = setTimeout(() => {
          controller.abort();
        }, timeoutMs);
        response = await fetch(url, init);
      } else {
        response = await Promise.race([
          fetch(url, init),
          new Promise<Response>((_resolve, reject) => {
            timeout = setTimeout(() => {
              reject(timeoutError(timeoutMs));
            }, timeoutMs);
          }),
        ]);
      }
    } catch (exc) {
      if (controller?.signal.aborted) {
        throw timeoutError(timeoutMs);
      }
      throw exc;
    } finally {
      if (timeout) {
        clearTimeout(timeout);
      }
    }
    const raw = await response.text();
    let payload: unknown = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = { ok: false, error: raw };
      }
    }
    if (!response.ok) {
      const error = payload && typeof payload === 'object' ? String((payload as JsonRecord).error || `HTTP ${response.status}`) : `HTTP ${response.status}`;
      throw new RemoteRequestError(error, response.status, payload);
    }
    if (!payload || typeof payload !== 'object') {
      throw new Error('Remote backend returned an invalid response.');
    }
    return payload as T;
  }
}
