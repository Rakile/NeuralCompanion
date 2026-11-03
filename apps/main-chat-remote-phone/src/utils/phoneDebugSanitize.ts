const SENSITIVE_KEY_PARTS = [
  'api_key',
  'apikey',
  'authorization',
  'code',
  'password',
  'secret',
  'signature',
  'ticket',
  'token',
];

const CONTENT_KEYS = new Set([
  'audio_base64',
  'content',
  'image_base64',
  'message',
  'prompt',
  'response_text',
  'source_text',
  'stack',
  'text',
  'transcript',
]);

function normalizedKey(value: string): string {
  return value.trim().toLowerCase().replace(/[ -]+/g, '_');
}

function scrubString(value: string): string {
  return value
    .replace(/([?&](?:api_?key|authorization|code|password|secret|signature|ticket|token)=)[^&\s"'#]+/gi, '$1[redacted]')
    .replace(/\bBearer\s+[A-Za-z0-9._~+/=-]+/gi, 'Bearer [redacted]')
    .replace(/\b(pairing(?:[_ -]?code)?\s*[:=]\s*)\d{4,9}\b/gi, '$1[redacted]')
    .slice(0, 2000);
}

export function sanitizePhoneDebugValue(value: unknown, depth = 0): unknown {
  if (depth >= 5) return '[truncated]';
  if (Array.isArray(value)) {
    return value.slice(0, 50).map((item) => sanitizePhoneDebugValue(item, depth + 1));
  }
  if (value && typeof value === 'object') {
    const output: Record<string, unknown> = {};
    Object.entries(value as Record<string, unknown>).slice(0, 50).forEach(([rawKey, child]) => {
      const key = rawKey.slice(0, 80);
      const lowered = normalizedKey(key);
      // Exact numeric RTC counters, not arbitrary keys containing "code".
      if (['framesdecoded', 'keyframesdecoded', 'totaldecodetime', 'native_error_code'].includes(lowered)
          && typeof child === 'number' && Number.isFinite(child) && child >= 0 && child <= Number.MAX_SAFE_INTEGER) {
        output[key] = child;
        return;
      }
      const sensitive = CONTENT_KEYS.has(lowered)
        || SENSITIVE_KEY_PARTS.some((marker) => lowered.includes(marker));
      output[key] = sensitive ? '[redacted]' : sanitizePhoneDebugValue(child, depth + 1);
    });
    return output;
  }
  if (typeof value === 'string') return scrubString(value);
  return value;
}
