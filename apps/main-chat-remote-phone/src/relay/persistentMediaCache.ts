import * as FileSystem from 'expo-file-system/legacy';
import * as Crypto from 'expo-crypto';

export const MEDIA_CACHE_LIMIT = 128 * 1024 * 1024;
const MAX_FILES = 256;
const MAX_FILE_BYTES = 16 * 1024 * 1024;
const MAX_AGE = 30 * 24 * 60 * 60 * 1000;
const folder = `${FileSystem.cacheDirectory || ''}nc-media-v1/`;
type Entry = { file: string; bytes: number; used: number; expires: number };
let entries: Record<string, Entry> = {};
let loaded: Promise<void> | undefined;
let tail: Promise<unknown> = Promise.resolve();
let generation = 0;
const safeFile = /^[a-f0-9]{64}\.(png|jpg|webp)$/;

function serialized<T>(action: () => Promise<T>): Promise<T> {
  const run = tail.then(action, action); tail = run.catch(() => undefined); return run;
}

async function load() {
  if (!FileSystem.cacheDirectory) return;
  if (!loaded) loaded = (async () => {
    await FileSystem.makeDirectoryAsync(folder, { intermediates: true });
    try {
      const parsed: unknown = JSON.parse(await FileSystem.readAsStringAsync(`${folder}index.json`));
      if (!parsed || typeof parsed !== 'object') return;
      for (const [key, value] of Object.entries(parsed)) {
        const e = value as Entry;
        if (/^[a-f0-9]{64}$/.test(key) && e && safeFile.test(e.file)
          && e.file.startsWith(key + '.') && Number.isFinite(e.bytes) && e.bytes > 0 && e.bytes <= MAX_FILE_BYTES
          && Number.isFinite(e.used) && Number.isFinite(e.expires)) entries[key] = e;
      }
    } catch { /* Missing/corrupt index is a cache miss, never a connection failure. */ }
    await trim();
    // Remove interrupted writes/orphans only inside this app-owned cache directory.
    for (const file of await FileSystem.readDirectoryAsync(folder).catch(() => [] as string[])) {
      if (safeFile.test(file) && !Object.values(entries).some(e => e.file === file)) {
        await FileSystem.deleteAsync(folder + file, { idempotent: true }).catch(() => undefined);
      }
    }
  })();
  await loaded;
}

async function trim() {
  let bytes = Object.values(entries).reduce((sum, e) => sum + e.bytes, 0);
  const sorted = Object.entries(entries).sort((a, b) => a[1].used - b[1].used);
  for (const [key, e] of sorted) {
    if (e.expires > Date.now() && bytes <= MEDIA_CACHE_LIMIT && Object.keys(entries).length <= MAX_FILES) continue;
    delete entries[key]; bytes -= e.bytes;
    await FileSystem.deleteAsync(folder + e.file, { idempotent: true }).catch(() => undefined);
  }
}

async function saveIndex() {
  await FileSystem.writeAsStringAsync(`${folder}index.json`, JSON.stringify(entries));
}

export function persistentImageTarget(path: string): boolean {
  const [route = '', query = ''] = path.split('?');
  return /^\/api\/avatar\/file\/[a-f0-9]{20}$/.test(route)
    || (/^\/api\/chat-characters\/media\/[a-f0-9]{64}$/.test(route) && new URLSearchParams(query).get('kind') === 'portrait')
    || (route === '/api/visual/image' && Boolean(new URLSearchParams(query).get('v')));
}

export async function persistentMediaKey(scope: string, target: string): Promise<string> {
  return Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, JSON.stringify([scope, target]));
}

export async function readCachedImage(key: string): Promise<{ url: string; bytes: number } | null> {
  if (!FileSystem.cacheDirectory) return null;
  return serialized(async () => {
    await load(); const e = entries[key];
    if (!e) return null;
    if (e.expires <= Date.now() || !(await FileSystem.getInfoAsync(folder + e.file)).exists) {
      delete entries[key]; await FileSystem.deleteAsync(folder + e.file, { idempotent: true }).catch(() => undefined);
      await saveIndex(); return null;
    }
    e.used = Date.now(); // Saved with the next insertion; avoids a write on every render.
    return { url: folder + e.file, bytes: e.bytes };
  });
}

export async function storeCachedImage(key: string, base64: string, bytes: number, extension: string): Promise<string | null> {
  if (!FileSystem.cacheDirectory || bytes <= 0 || bytes > MAX_FILE_BYTES || !['png', 'jpg', 'webp'].includes(extension)) return null;
  const owner = generation;
  return serialized(async () => {
    await load(); if (owner !== generation) return null;
    const file = `${key}.${extension}`;
    if (!safeFile.test(file)) return null;
    await FileSystem.writeAsStringAsync(folder + file, base64, { encoding: FileSystem.EncodingType.Base64 });
    entries[key] = { file, bytes, used: Date.now(), expires: Date.now() + MAX_AGE };
    await trim(); await saveIndex();
    return folder + file;
  });
}

export async function mediaCacheUsage(): Promise<{ bytes: number; files: number; limit: number }> {
  return serialized(async () => {
    await load(); await trim();
    return { bytes: Object.values(entries).reduce((sum, e) => sum + e.bytes, 0), files: Object.keys(entries).length, limit: MEDIA_CACHE_LIMIT };
  });
}

export async function clearPersistentMediaCache(): Promise<void> {
  if (!FileSystem.cacheDirectory) return;
  ++generation;
  await serialized(async () => {
    await load();
    entries = {};
    await FileSystem.deleteAsync(folder, { idempotent: true });
    await FileSystem.makeDirectoryAsync(folder, { intermediates: true });
    await saveIndex();
  });
}
