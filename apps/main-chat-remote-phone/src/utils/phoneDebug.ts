import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import { configurePhoneDebug } from './phoneDebugBridge';
import type { PhoneDebugUploadClient } from './phoneDebugBridge';
import { sanitizePhoneDebugValue } from './phoneDebugSanitize';
import type { PhoneDebugEvent, PhoneDebugLevel } from './phoneDebugTypes';
import { prepareContractRecord } from '../diagnostics/sinkPayload';
import {siteEnabled} from '../diagnostics/policy';

export type { PhoneDebugEvent, PhoneDebugLevel } from './phoneDebugTypes';

const DEBUG_FILE = `${FileSystem.documentDirectory || ''}nc-phone-debug.jsonl`;
const MAX_LOCAL_EVENTS = 2000;
// Reserve incident evidence when normal request traffic fills the backlog.
const MAX_CONNECTION_EVENTS = 256;
const connectionEvidence = (event: StoredEvent) => /^(connection_|continuous_phone_stage|relay_|rtc_|peer_close|peer_heartbeat|phone_network|phone_lifecycle|phone_power|js_timer|diagnostics_started|audio_(focus_|timeout|playback_failed|waiting_)|manual_reply_suspended)/.test(event.event)
  || (event.event === 'diagnostic_event' && String((event.details as {contract?: {data?: {site?: string}}})?.contract?.data?.site || '').startsWith('native.playback.'));
// UTF-16 code units: at most 3 MiB of UTF-8 JSON on disk.
const MAX_LOCAL_CHARS = 1024 * 1024;
const MAX_EVENT_CHARS = 16000;
const MAX_UPLOAD_EVENTS = 200;
const MAX_UPLOAD_BATCHES = 10;
const MIN_UPLOAD_INTERVAL_MS = 15000;
const PRESSURE_UPLOAD_INTERVAL_MS = 1000;
let uploadInFlight: Promise<number> | null = null;
let lastUploadAt = 0;
let lastPressureUploadAt = 0;
let fileQueue: Promise<void> = Promise.resolve();
type StoredEvent = PhoneDebugEvent & {localId: string};
let cachedEvents: StoredEvent[] | null = null;
let cachedChars = 0;
const serializedEvents = new WeakMap<StoredEvent,string>();
let dirty = false;
let persistTimer: ReturnType<typeof setTimeout> | null = null;
const diagnosticSession = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
let nextEvent = 0;
let writeFailureReported = false;
let readUnavailable = false;

function serializedEvent(event: StoredEvent): string {
  let body = serializedEvents.get(event);
  if (body === undefined) {
    body = JSON.stringify(event); serializedEvents.set(event,body);
  }
  return body;
}

function identified(event: PhoneDebugEvent): StoredEvent {
  const localId = `${diagnosticSession}-${++nextEvent}`;
  const details = event.details && typeof event.details === 'object' && !Array.isArray(event.details)
    ? event.details : {value:event.details};
  return {...event,localId,details:{...details,diagnosticRecordId:localId, diagnosticRevision:'peer-incidents-20261012-v4'}};
}

function withFileLock<T>(operation: () => Promise<T>): Promise<T> {
  const result = fileQueue.then(operation, operation);
  fileQueue = result.then(() => undefined, () => undefined);
  return result;
}

async function readEvents(): Promise<StoredEvent[]> {
  if (cachedEvents) return cachedEvents;
  if (!DEBUG_FILE) return [];
  try {
    if (typeof FileSystem.getInfoAsync === 'function' && !(await FileSystem.getInfoAsync(DEBUG_FILE)).exists) {
      cachedEvents = []; return cachedEvents;
    }
    let malformed = 0;
    const raw = await FileSystem.readAsStringAsync(DEBUG_FILE);
    cachedEvents = raw.split(/\r?\n/).filter(Boolean).flatMap((line) => {
      try {
        const event = JSON.parse(line) as StoredEvent;
        if (!event || typeof event.event !== 'string') { malformed++; return []; }
        return [typeof event.localId === 'string' ? event : identified(event)];
      } catch {
        malformed++;
        return [];
      }
    });
    if (malformed) cachedEvents.push(identified({ timestamp: new Date().toISOString(), level: 'warning',
      event: 'phone_debug_storage_failure', details: { operation: 'parse', dropped_events: malformed } }));
  } catch {
    // Do not overwrite an unreadable existing backlog. Fresh events can still
    // be uploaded from bounded memory; a later app launch can retry the file.
    readUnavailable = true;
    cachedEvents = [identified({ timestamp: new Date().toISOString(), level: 'warning',
      event: 'phone_debug_storage_failure', details: { operation: 'read', durable: false } })];
  }
  cachedChars = cachedEvents.reduce((n,event) => n+serializedEvent(event).length+1,0);
  return cachedEvents;
}

async function persistEvents(): Promise<void> {
  if (!dirty || !cachedEvents) return;
  if (!DEBUG_FILE) return;
  if (readUnavailable) throw new Error('Phone diagnostics backlog could not be read; preserving existing file.');
  const body = cachedEvents.map(serializedEvent).join('\n');
  try {
    await FileSystem.writeAsStringAsync(DEBUG_FILE, body ? `${body}\n` : '');
  } catch {
    // Keep the in-memory evidence, and report loss of durability once per
    // failure period. Do not recurse into this logger or expose OS path/errors.
    if (!writeFailureReported) {
      writeFailureReported = true;
      const marker = identified({ timestamp: new Date().toISOString(), level: 'warning',
        event: 'phone_debug_storage_failure', details: { operation: 'write', durable: false } });
      cachedEvents.push(marker); cachedChars += serializedEvent(marker).length + 1;
      boundEvents(cachedEvents);
    }
    throw new Error('Phone diagnostics persistence unavailable.');
  }
  writeFailureReported = false;
  dirty = false;
}

function persistSoon(): void {
  if (persistTimer) return;
  persistTimer = setTimeout(() => {
    persistTimer = null;
    void withFileLock(persistEvents).catch(() => undefined);
  },250);
}

function boundEvents(events: StoredEvent[]): void {
  if (events.length <= MAX_LOCAL_EVENTS && cachedChars <= MAX_LOCAL_CHARS) return;
  // Preserve an explicit local-eviction count across repeated overflows. Events
  // already in flight may still arrive; this is not a claimed server-loss count.
  let droppedEvents = 0;
  for (let i=events.length-1;i>=0;i--) {
    const event = events[i];
    if (!event || event.event !== 'phone_debug_overflow') continue;
    droppedEvents += Number((event.details as {droppedEvents?: number})?.droppedEvents || 0);
    cachedChars -= serializedEvent(event).length+1; events.splice(i,1);
  }
  let protectedCount = events.filter(connectionEvidence).length;
  while (events.length >= MAX_LOCAL_EVENTS || cachedChars > MAX_LOCAL_CHARS-1024) {
    const ordinary = protectedCount <= MAX_CONNECTION_EVENTS ? events.findIndex(event => !connectionEvidence(event)) : -1;
    const removed = events.splice(ordinary < 0 ? 0 : ordinary,1)[0]; if (!removed) break;
    if (connectionEvidence(removed)) protectedCount--;
    cachedChars -= serializedEvent(removed).length+1; droppedEvents++;
  }
  const marker = identified({timestamp:new Date().toISOString(),level:'warning',event:'phone_debug_overflow',
    details:{droppedEvents,scope:'local_backlog',maxEvents:MAX_LOCAL_EVENTS}});
  events.push(marker); cachedChars += serializedEvent(marker).length+1;
}

export function phoneDebugFileName(): string {
  return 'nc-phone-debug.jsonl';
}

export async function recordPhoneDebug(level: PhoneDebugLevel, event: string, details: unknown = {}, requireAcceptance = false): Promise<void> {
  try {
    if(!requireAcceptance&&event!=='diagnostic_event'&&!siteEnabled(event,level,'observed',details&&typeof details==='object'?details as Record<string,unknown>:{}))return;
    // Capture occurrence time before queued disk work; atMs in playback events
    // remains the monotonic authority for duration calculations.
    const prepared = event === 'diagnostic_event' ? prepareContractRecord(details) :
      {event:String(event || 'phone_event').slice(0,100),details:sanitizePhoneDebugValue(details)};
    const row = identified({timestamp:new Date().toISOString(),level,...prepared});
    // Contract payloads already have a strict 16 KiB UTF-8 limit. Leave room for
    // the existing wrapper; never silently truncate a validated envelope.
    if (prepared.event !== 'diagnostic_event' && JSON.stringify(row).length > MAX_EVENT_CHARS)
      row.details = {diagnosticDetailsTruncated:true,diagnosticRecordId:row.localId};
    await withFileLock(async () => {
      const events = await readEvents();
      events.push(row); cachedChars += serializedEvent(row).length+1;
      boundEvents(events); dirty = true;
      if (/^(connection_failure_snapshot|peer_close_origin|relay_peer_teardown|phone_lifecycle)/.test(row.event)) {
        await persistEvents().catch(() => undefined);
      } else persistSoon();
    });
  } catch {
    // Native custody transfer must retry when the bounded JS backlog rejects it.
    if (requireAcceptance) throw new Error('Diagnostic backlog acceptance failed.');
  }
}

export async function uploadPhoneDebug(client: PhoneDebugUploadClient, reason = 'automatic', force = false): Promise<number> {
  const now = Date.now();
  if (uploadInFlight) return uploadInFlight;
  if (!client) return 0;
  const pressure = cachedChars >= MAX_LOCAL_CHARS / 2 || (cachedEvents?.length ?? 0) >= MAX_LOCAL_EVENTS / 2;
  if (!force) {
    if (pressure && now - lastPressureUploadAt < PRESSURE_UPLOAD_INTERVAL_MS) return 0;
    if (!pressure && now - lastUploadAt < MIN_UPLOAD_INTERVAL_MS) return 0;
    // Keep the existing bounded batches and single in-flight upload. A failed
    // pressure drain cannot cause an unbounded retry on every control response.
    if (pressure) lastPressureUploadAt = now;
  }
  uploadInFlight = (async () => {
    let total = 0;
    for (let batch=0;batch<MAX_UPLOAD_BATCHES;batch++) {
      const events = await withFileLock(async () => {
        const current = await readEvents();
        await persistEvents().catch(() => undefined);
        return current.slice(0,MAX_UPLOAD_EVENTS);
      });
      if (!events.length) break;
      const payload = await client.uploadDebugPayload({reason,
        app:{version:'0.3.0',platform:Platform.OS,runtime:String(Platform.Version),diagnosticRevision:'peer-incidents-20261012-v4'},events});
      const accepted = payload.result?.events_written;
      if (!payload.result?.accepted || (accepted !== undefined &&
          (!Number.isInteger(accepted) || accepted <= 0 || accepted > events.length))) {
        throw new Error('Desktop did not accept phone diagnostics.');
      }
      const count = accepted ?? events.length;
      const acknowledged = new Set(events.slice(0,count).map(event => event.localId));
      await withFileLock(async () => {
        const current = await readEvents();
        cachedEvents = current.filter(event => {
          if (!acknowledged.has(event.localId)) return true;
          cachedChars -= serializedEvent(event).length+1; return false;
        });
        dirty = true; await persistEvents().catch(() => undefined);
      });
      total += count;
    }
    lastUploadAt = Date.now();
    return total;
  })().finally(() => {
    uploadInFlight = null;
  });
  return uploadInFlight;
}

configurePhoneDebug(recordPhoneDebug, uploadPhoneDebug);
