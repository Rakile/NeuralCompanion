export type PairingSetup = {
  baseUrl: string;
  pairingCode: string;
};
export type InternetPairingSetup = { mode: 'internet'; hostnameUrl: string; ipUrl: string; enrollmentId: string; secret: string; gatewayId: string };
export type AnyPairingSetup = ({ mode: 'lan' } & PairingSetup) | InternetPairingSetup;

const PAIRING_SCHEME = 'ncchatremote:';
const PAIRING_HOST = 'pair';
const PAIRING_CODE_PATTERN = /^\d{4,9}$/;
const BOUNDED_SECRET_PATTERN = /^[A-Za-z0-9_-]{12,256}$/;

export function parsePairingSetupUri(value: string): PairingSetup | null {
  try {
    const setupUrl = new URL(String(value || '').trim());
    if (setupUrl.protocol.toLowerCase() !== PAIRING_SCHEME || setupUrl.hostname.toLowerCase() !== PAIRING_HOST) {
      return null;
    }
    const pairingCode = String(setupUrl.searchParams.get('code') || '').trim();
    if (!PAIRING_CODE_PATTERN.test(pairingCode)) {
      return null;
    }
    const targetUrl = new URL(String(setupUrl.searchParams.get('url') || '').trim());
    if (
      (targetUrl.protocol !== 'http:' && targetUrl.protocol !== 'https:')
      || !targetUrl.hostname
      || targetUrl.username
      || targetUrl.password
    ) {
      return null;
    }
    return { baseUrl: targetUrl.origin, pairingCode };
  } catch {
    return null;
  }
}

function normalizedHttpsOrigin(value: string): string {
  try {
    const url = new URL(String(value || '').trim());
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password || url.pathname !== '/' || url.search || url.hash) return '';
    return url.origin;
  } catch { return ''; }
}

function effectivePort(origin: string): string { try { return new URL(origin).port || '443'; } catch { return ''; } }

export function parseInternetPairingSetupUri(value: string): InternetPairingSetup | null {
  try {
    const setupUrl = new URL(String(value || '').trim());
    if (setupUrl.protocol.toLowerCase() !== PAIRING_SCHEME || setupUrl.hostname.toLowerCase() !== PAIRING_HOST || setupUrl.searchParams.get('version') !== '2' || setupUrl.searchParams.get('mode') !== 'internet') return null;
    const hostnameUrl = normalizedHttpsOrigin(String(setupUrl.searchParams.get('hostname_url') || ''));
    const ipUrl = normalizedHttpsOrigin(String(setupUrl.searchParams.get('ip_url') || ''));
    const enrollmentId = String(setupUrl.searchParams.get('enrollment_id') || '').trim();
    const secret = String(setupUrl.searchParams.get('secret') || '').trim();
    const gatewayId = String(setupUrl.searchParams.get('gateway_id') || '').trim();
    if (!hostnameUrl || !ipUrl || effectivePort(hostnameUrl) !== effectivePort(ipUrl) || !BOUNDED_SECRET_PATTERN.test(enrollmentId) || !BOUNDED_SECRET_PATTERN.test(secret) || !BOUNDED_SECRET_PATTERN.test(gatewayId)) return null;
    return { mode: 'internet', hostnameUrl, ipUrl, enrollmentId, secret, gatewayId };
  } catch { return null; }
}

export function parseAnyPairingSetupUri(value: string): AnyPairingSetup | null {
  const internet = parseInternetPairingSetupUri(value);
  if (internet) return internet;
  const lan = parsePairingSetupUri(value);
  return lan ? { mode: 'lan', ...lan } : null;
}
