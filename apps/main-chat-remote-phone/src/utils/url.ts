const DEFAULT_LAN_PORT = '8777';

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
