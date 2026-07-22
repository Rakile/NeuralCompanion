import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import { configurePhoneDebug } from './phoneDebugBridge';
import type { PhoneDebugEvent, PhoneDebugLevel } from './phoneDebugTypes';

export type { PhoneDebugEvent, PhoneDebugLevel } from './phoneDebugTypes';

const DEBUG_FILE = `${FileSystem.documentDirectory || ''}nc-phone-debug.jsonl`;
const MAX_LOCAL_EVENTS = 200;
const MIN_UPLOAD_INTERVAL_MS = 15000;
let uploadInFlight: Promise<number> | null = null;
let lastUploadAt = 0;
let fileQueue: Promise<void> = Promise.resolve();

function withFileLock<T>(operation: () => Promise<T>): Promise<T> {
  const result = fileQueue.then(operation, operation);
  fileQueue = result.then(() => undefined, () => undefined);
  return result;
}

function sanitize(value: unknown, depth = 0): unknown {
  if (depth >= 5) return '[truncated]';
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => sanitize(item, depth + 1));
  if (value && typeof value === 'object') {
    const output: Record<string, unknown> = {};
    Object.entries(value as Record<string, unknown>).slice(0, 50).forEach(([key, child]) => {
      const lowered = key.toLowerCase();
      output[key.slice(0, 80)] = ['code', 'token', 'secret', 'password', 'api_key', 'authorization'].some((marker) => lowered.includes(marker))
        ? '[redacted]'
        : sanitize(child, depth + 1);
    });
    return output;
  }
  if (typeof value === 'string') return value.slice(0, 2000);
  return value;
}

async function readEvents(): Promise<PhoneDebugEvent[]> {
  if (!DEBUG_FILE) return [];
  try {
    const raw = await FileSystem.readAsStringAsync(DEBUG_FILE);
    return raw.split(/\r?\n/).filter(Boolean).slice(-MAX_LOCAL_EVENTS).flatMap((line) => {
      try {
        return [JSON.parse(line) as PhoneDebugEvent];
      } catch {
        return [];
      }
    });
  } catch {
    return [];
  }
}

async function writeEvents(events: PhoneDebugEvent[]): Promise<void> {
  if (!DEBUG_FILE) return;
  const body = events.slice(-MAX_LOCAL_EVENTS).map((event) => JSON.stringify(event)).join('\n');
  await FileSystem.writeAsStringAsync(DEBUG_FILE, body ? `${body}\n` : '');
}

export function phoneDebugFileName(): string {
  return 'nc-phone-debug.jsonl';
}

export async function recordPhoneDebug(level: PhoneDebugLevel, event: string, details: unknown = {}): Promise<void> {
  await withFileLock(async () => {
    const events = await readEvents();
    events.push({
      timestamp: new Date().toISOString(),
      level,
      event: String(event || 'phone_event').slice(0, 100),
      details: sanitize(details),
    });
    await writeEvents(events);
  }).catch(() => undefined);
}

export async function uploadPhoneDebug(baseUrl: string, pairingCode: string, reason = 'automatic', force = false): Promise<number> {
  const now = Date.now();
  if (!force && now - lastUploadAt < MIN_UPLOAD_INTERVAL_MS) return 0;
  if (uploadInFlight) return uploadInFlight;
  const normalizedBase = String(baseUrl || '').replace(/\/+$/, '');
  if (!normalizedBase || !pairingCode) return 0;
  uploadInFlight = (async () => {
    const events = await withFileLock(readEvents);
    if (!events.length) return 0;
    const response = await fetch(`${normalizedBase}/api/debug`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-NC-Phone-Code': pairingCode,
      },
      body: JSON.stringify({
        reason,
        app: { version: '0.1.0', platform: Platform.OS, runtime: String(Platform.Version) },
        events,
      }),
    });
    if (!response.ok) throw new Error(`Debug upload failed with HTTP ${response.status}.`);
    const payload = await response.json() as { result?: { accepted?: boolean; events_written?: number } };
    if (!payload.result?.accepted) throw new Error('Desktop did not accept phone diagnostics.');
    await withFileLock(async () => {
      const current = await readEvents();
      await writeEvents(current.slice(Math.min(events.length, current.length)));
    });
    lastUploadAt = Date.now();
    return Number(payload.result.events_written || events.length);
  })().finally(() => {
    uploadInFlight = null;
  });
  return uploadInFlight;
}

configurePhoneDebug(recordPhoneDebug, uploadPhoneDebug);
