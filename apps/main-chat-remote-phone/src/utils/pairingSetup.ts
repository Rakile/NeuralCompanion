export type PairingSetup = {
  baseUrl: string;
  pairingCode: string;
};

const PAIRING_SCHEME = 'ncchatremote:';
const PAIRING_HOST = 'pair';
const PAIRING_CODE_PATTERN = /^\d{4,9}$/;

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
