// Local stdin/stdout validation only. No network and no diagnostic payload logging.
import * as protocol from './index.js';
import { readFileSync } from 'node:fs';
try {
  const input = readFileSync(0, 'utf8');
  if (Buffer.byteLength(input) > 131072) throw new Error('limit');
  const request = JSON.parse(input);
  let value: unknown;
  if (request.op === 'signal') {
    const parsed = protocol.parseSignalingMessage(typeof request.payload === 'string' ? request.payload : JSON.stringify(request.payload));
    if (!parsed.ok) throw new Error(parsed.error.code);
    value = parsed.message;
  } else if (request.op === 'constants') {
    value = { version: protocol.SIGNALING_PROTOCOL_VERSION, apiErrors: protocol.ApiErrorCode,
      signalingErrors: protocol.SignalingErrorCode, httpStatuses: protocol.HTTP_STATUS_BY_ERROR_CODE };
  } else {
    const schema = (protocol as Record<string, unknown>)[request.schema] as { parse?: (v: unknown) => unknown };
    if (!request.schema?.endsWith('Schema') || typeof schema?.parse !== 'function') throw new Error('schema');
    value = schema.parse(request.payload);
  }
  process.stdout.write(JSON.stringify({ ok: true, value }));
} catch {
  process.stdout.write(JSON.stringify({ ok: false, code: 'VALIDATION_FAILED' }));
}
