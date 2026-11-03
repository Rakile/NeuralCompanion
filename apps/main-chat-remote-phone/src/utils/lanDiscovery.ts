import { StateSyncDecoder } from '../api/stateSync.ts';

type ProbeResponse = {
  ok: boolean;
  json: () => Promise<unknown>;
};

type FetchLike = (url: string, init?: RequestInit) => Promise<ProbeResponse>;

type DiscoveryOptions = {
  phoneIp: string;
  pairingCode: string;
  preferredBaseUrl: string;
  fetchImpl?: FetchLike;
  port?: number;
  probeTimeoutMs?: number;
  batchSize?: number;
};

const DEFAULT_PORT = 8777;
const DEFAULT_PROBE_TIMEOUT_MS = 650;

function normalizedOrigin(value: string): string {
  try {
    const url = new URL(String(value || '').trim());
    if ((url.protocol !== 'http:' && url.protocol !== 'https:') || !url.hostname) {
      return '';
    }
    return url.origin;
  } catch {
    return '';
  }
}

export function buildLanDiscoveryCandidates(
  _phoneIp: string,
  preferredBaseUrl: string,
  _port = DEFAULT_PORT,
): string[] {
  // Keep the caller interface, but never scan other hosts with pairing credentials.
  // An IP change requires an explicitly entered address or a fresh QR scan.
  const preferred = normalizedOrigin(preferredBaseUrl);
  return preferred ? [preferred] : [];
}

async function probeCandidate(
  baseUrl: string,
  pairingCode: string,
  fetchImpl: FetchLike,
  timeoutMs: number,
): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${baseUrl}/api/state?sync=1`, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        'X-NC-Phone-Code': pairingCode,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      return false;
    }
    const payload = await response.json();
    if (!payload || typeof payload !== 'object' || (payload as { ok?: unknown }).ok !== true) return false;
    return new StateSyncDecoder().apply((payload as { state_sync?: unknown }).state_sync).full;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function discoverRemoteBaseUrl(options: DiscoveryOptions): Promise<string> {
  const pairingCode = String(options.pairingCode || '').trim();
  if (!pairingCode) {
    return '';
  }
  const fetchImpl = options.fetchImpl ?? (fetch as FetchLike);
  const timeoutMs = Math.max(200, Math.min(5000, Math.round(options.probeTimeoutMs ?? DEFAULT_PROBE_TIMEOUT_MS)));
  const [preferred] = buildLanDiscoveryCandidates(options.phoneIp, options.preferredBaseUrl, options.port);

  if (preferred && await probeCandidate(preferred, pairingCode, fetchImpl, timeoutMs)) {
    return preferred;
  }

  return '';
}
