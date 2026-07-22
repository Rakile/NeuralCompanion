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
const DEFAULT_BATCH_SIZE = 32;

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

function ipv4SubnetPrefix(value: string): string {
  const parts = String(value || '').trim().split('.');
  if (parts.length !== 4) {
    return '';
  }
  const octets = parts.map((part) => Number(part));
  if (octets.some((octet) => !Number.isInteger(octet) || octet < 0 || octet > 255)) {
    return '';
  }
  const first = octets[0];
  if (first === undefined || first === 0 || first === 127 || first >= 224) {
    return '';
  }
  return `${octets[0]}.${octets[1]}.${octets[2]}`;
}

export function buildLanDiscoveryCandidates(
  phoneIp: string,
  preferredBaseUrl: string,
  port = DEFAULT_PORT,
): string[] {
  const candidates: string[] = [];
  const seen = new Set<string>();
  const addCandidate = (value: string) => {
    const normalized = normalizedOrigin(value);
    if (normalized && !seen.has(normalized)) {
      seen.add(normalized);
      candidates.push(normalized);
    }
  };

  addCandidate(preferredBaseUrl);
  const prefix = ipv4SubnetPrefix(phoneIp);
  const phoneHost = Number(String(phoneIp || '').trim().split('.')[3]);
  if (!prefix) {
    return candidates;
  }
  const normalizedPort = Number.isInteger(port) && port > 0 && port <= 65535 ? port : DEFAULT_PORT;
  for (let host = 1; host <= 254; host += 1) {
    if (host !== phoneHost) {
      addCandidate(`http://${prefix}.${host}:${normalizedPort}`);
    }
  }
  return candidates;
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
    const response = await fetchImpl(`${baseUrl}/api/state`, {
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
    return Boolean(
      payload
      && typeof payload === 'object'
      && (payload as { ok?: unknown }).ok === true
      && (payload as { state?: unknown }).state
      && typeof (payload as { state?: unknown }).state === 'object',
    );
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
  const batchSize = Math.max(1, Math.min(64, Math.round(options.batchSize ?? DEFAULT_BATCH_SIZE)));
  const candidates = buildLanDiscoveryCandidates(options.phoneIp, options.preferredBaseUrl, options.port);
  const preferred = normalizedOrigin(options.preferredBaseUrl);

  if (preferred && await probeCandidate(preferred, pairingCode, fetchImpl, timeoutMs)) {
    return preferred;
  }

  const remaining = candidates.filter((candidate) => candidate !== preferred);
  for (let offset = 0; offset < remaining.length; offset += batchSize) {
    const batch = remaining.slice(offset, offset + batchSize);
    const results = await Promise.all(
      batch.map((candidate) => probeCandidate(candidate, pairingCode, fetchImpl, timeoutMs)),
    );
    const foundIndex = results.findIndex(Boolean);
    if (foundIndex >= 0) {
      return batch[foundIndex] ?? '';
    }
  }
  return '';
}
