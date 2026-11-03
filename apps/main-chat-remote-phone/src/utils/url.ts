const DEFAULT_LAN_PORT = '8777';

export function normalizeInternetUrl(value: string): string {
  const text = String(value || '').trim().replace(/\s+/g, '');
  if (!text || /^http:\/\//i.test(text) || /^wss?:\/\//i.test(text) || /^[/?#]/.test(text)) return '';
  const candidate = /^https:\/\//i.test(text) ? text : `https://${text}`;
  try {
    const url = new URL(candidate);
    if (url.protocol !== 'https:' || !url.hostname || url.username || url.password) return '';
    url.pathname = ''; url.search = ''; url.hash = '';
    return url.toString().replace(/\/+$/, '');
  } catch { return ''; }
}

export function isPrivateLanHttpOrigin(value: string): boolean {
  try {
    const url = new URL(String(value || '').trim());
    if (url.protocol !== 'http:' || url.username || url.password || !url.hostname) return false;
    const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, '');
    if (host === 'localhost' || host.endsWith('.local') || host === '::1' || /^(?:fe[89ab]|fc|fd)/.test(host)) return true;
    const octets = host.split('.').map(Number);
    if (octets.length !== 4 || octets.some((item) => !Number.isInteger(item) || item < 0 || item > 255)) return false;
    const first = octets[0] ?? -1; const second = octets[1] ?? -1;
    return first === 10 || first === 127 || (first === 169 && second === 254) || (first === 172 && second >= 16 && second <= 31) || (first === 192 && second === 168);
  } catch { return false; }
}

export function normalizeLanUrl(value: string): string {
  const text = value.trim().replace(/\s+/g, '');
  if (!text) {
    return '';
  }
  if (/^[/?#]/.test(text)) {
    return '';
  }
  const withProtocol = /^wss?:\/\//i.test(text)
    ? text.replace(/^ws/i, 'http')
    : /^https?:\/\//i.test(text)
      ? text
      : `http://${text}`;
  try {
    const url = new URL(withProtocol);
    if (!url.port && url.protocol === 'http:') {
      url.port = DEFAULT_LAN_PORT;
    }
    url.pathname = '';
    url.search = '';
    url.hash = '';
    return url.toString().replace(/\/+$/, '');
  } catch {
    return '';
  }
}

export function fileExtensionFromUri(uri: string): string {
  const match = uri.toLowerCase().match(/\.([a-z0-9]+)(?:\?|#|$)/);
  return match?.[1] ?? 'm4a';
}
