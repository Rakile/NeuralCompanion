import { Buffer } from 'buffer';
import * as FileSystem from 'expo-file-system/legacy';
import type { PeerTransport } from './peer';
import type {DiagnosticLink} from '../diagnostics/planTransaction';
import {mediaAcquisition} from '../diagnostics/planTransaction';
import { persistentImageTarget, persistentMediaKey, readCachedImage, storeCachedImage } from './persistentMediaCache';

export class PeerMediaCapacityError extends Error {}

type MediaEntry = { url: string; bytes: number; contentType?: string; persistent?: boolean; readers?: number;diagnosticLink?:DiagnosticLink };
const caches = new WeakMap<PeerTransport, Map<string, MediaEntry>>();
// Closed-peer readers remain in the same byte/file budget until released.
const detachedReaders = new Set<MediaEntry>();
const pending = new WeakMap<PeerTransport, Map<string, Promise<{ url: string; expiresAt: number }>>>();
const pendingParents=new WeakMap<Promise<{url:string;expiresAt:number}>,DiagnosticLink>();
let counter = 0;
let folderReady: Promise<string> | null = null;

function prepareMediaFolder(): Promise<string> {
  if (!FileSystem.cacheDirectory) return Promise.reject(new Error('Phone media cache unavailable.'));
  if (!folderReady) {
    const folder = `${FileSystem.cacheDirectory}nc-relay/`;
    folderReady = (async () => {
      await FileSystem.makeDirectoryAsync(folder, { intermediates: true });
      let files: string[] = [];
      try { files = await FileSystem.readDirectoryAsync(folder); } catch { /* Cache cleanup is best effort. */ }
      // Run before the first write only: subsequent peers may have active readers.
      // Match only this module's flat, timestamped filenames, never other caches.
      await Promise.all(files.filter(file => /^\d+-\d+\.(ogg|wav|mp3|m4a|aac|mp4|png|jpg|webp|bin)$/.test(file))
        .map(file => FileSystem.deleteAsync(folder + file, { idempotent: true }).catch(() => undefined)));
      return folder;
    })().catch(error => { folderReady = null; throw error; });
  }
  return folderReady;
}

function checkTransfer(peer:PeerTransport,signal?:AbortSignal) {
  if(signal?.aborted)throw new Error('Peer media cancelled.');
  if(peer.closed)throw peer.unavailable();
}
function mediaTarget(path: string, params: Record<string, unknown>) {
  const query = new URLSearchParams(path.split('?')[1] || '');
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null) query.set(key, String(value));
  for (const key of Array.from(query.keys())) if (['code', 'token', 'ticket'].includes(key.toLowerCase())) query.delete(key);
  query.sort();
  return path.split('?')[0] + (query.toString() ? `?${query}` : '');
}
export async function peerMedia(peer: PeerTransport, path: string, params: Record<string, unknown>, signal?: AbortSignal, diagnosticLink?:DiagnosticLink) {
  checkTransfer(peer,signal);
  if (path.split('?')[0] === '/api/musetalk/stream') throw new Error('WebRTC uses MuseTalk frame delivery.');
  const target = mediaTarget(path, params);
  let tasks = pending.get(peer); if (!tasks) { tasks = new Map(); pending.set(peer, tasks); }
  const running = tasks.get(target); if (running) {mediaAcquisition(diagnosticLink,'shared_pending',pendingParents.get(running));return running;}
  const task = resolveMedia(peer, target, signal, diagnosticLink).finally(() => tasks!.delete(target));
  if(diagnosticLink)pendingParents.set(task,diagnosticLink);
  tasks.set(target, task); return task;
}

async function resolveMedia(peer: PeerTransport, target: string, signal?: AbortSignal, diagnosticLink?:DiagnosticLink) {
  const folder = await prepareMediaFolder();
  checkTransfer(peer,signal);
  let cache = caches.get(peer); if (!cache) { cache = new Map(); caches.set(peer, cache); }
  const prior = cache.get(target);
  if (prior && (await FileSystem.getInfoAsync(prior.url)).exists) {
    checkTransfer(peer,signal);
    mediaAcquisition(diagnosticLink,'cache_hit',prior.diagnosticLink);
    cache.delete(target); cache.set(target, prior);
    return { url: prior.url, expiresAt: Date.now() + 120000 };
  }
  cache.delete(target);
  const persistentKey = peer.cacheScope && persistentImageTarget(target) ? await persistentMediaKey(peer.cacheScope, target) : '';
  const stored = persistentKey ? await readCachedImage(persistentKey).catch(() => null) : null;
  checkTransfer(peer,signal);
  if (stored) {
    mediaAcquisition(diagnosticLink,'persistent_hit');
    cache.set(target, { ...stored, persistent: true });
    return { url: stored.url, expiresAt: Date.now() + 120000 };
  }
  const response = await peer.request('GET', target, undefined, 150000, signal, diagnosticLink);
  if (response.status !== 200 || !response.bytes) throw new Error('Peer media unavailable.');
  checkTransfer(peer,signal);
  const extensions: Record<string, string> = { 'audio/ogg':'ogg', 'audio/wav':'wav', 'audio/x-wav':'wav', 'audio/mpeg':'mp3', 'audio/mp4':'m4a', 'audio/aac':'aac', 'video/mp4':'mp4', 'image/png':'png', 'image/jpeg':'jpg', 'image/webp':'webp' };
  const extension = extensions[response.contentType.split(';')[0] || ''] || 'bin';
  const encoded = Buffer.from(response.bytes).toString('base64');
  const persistentUrl = persistentKey ? await storeCachedImage(persistentKey, encoded, response.bytes.length, extension).catch(() => null) : null;
  const url = persistentUrl || `${folder}${Date.now()}-${++counter}.${extension}`;
  try {
    if (!persistentUrl) await FileSystem.writeAsStringAsync(url, encoded, { encoding: FileSystem.EncodingType.Base64 });
    checkTransfer(peer,signal);
  } catch (error) {
    if (!persistentUrl) await FileSystem.deleteAsync(url, {idempotent:true}).catch(() => undefined);
    throw error;
  }
  cache.set(target, { url, bytes: response.bytes.length, contentType: response.contentType.split(';')[0], persistent: Boolean(persistentUrl),diagnosticLink });
  const detachedBytes = Array.from(detachedReaders).reduce((sum, item) => sum + item.bytes, 0);
  let size = detachedBytes + Array.from(cache.values()).reduce((sum, item) => sum + item.bytes, 0);
  while (cache.size + detachedReaders.size > 96 || size > 192 * 1024 * 1024) {
    const first = Array.from(cache.entries()).find(([key, entry]) => key !== target && !entry.readers);
    if (!first) {
      cache.delete(target);
      if (!persistentUrl) await FileSystem.deleteAsync(url, {idempotent:true}).catch(() => undefined);
      throw new PeerMediaCapacityError('Phone media cache capacity reached.');
    }
    cache.delete(first[0]); size -= first[1].bytes;
    if (!first[1].persistent) await FileSystem.deleteAsync(first[1].url, { idempotent: true }).catch(() => undefined);
  }
  // The shared resolver must recheck our bounded cache after an eviction.
  return { url, expiresAt: Date.now() + 120000 };
}

/** A pin in the existing transient cache, not a second on-disk cache. */
export async function retainPeerMedia(peer: PeerTransport, path: string,
    expected: {bytes:number; contentType:string;diagnosticLink?:DiagnosticLink}, signal: AbortSignal) {
  const target = mediaTarget(path, {});
  const resolved = await peerMedia(peer, path, {}, signal, expected.diagnosticLink);
  checkTransfer(peer,signal);
  const cache = caches.get(peer), entry = cache?.get(target);
  if (!entry || entry.url !== resolved.url || entry.persistent || peer.closed || signal.aborted) {
    throw new Error('Peer media cancelled or unavailable before retention.');
  }
  entry.readers = (entry.readers ?? 0) + 1;
  let released = false;
  const release = async () => {
    if (released) return; released = true;
    entry.readers = Math.max(0, (entry.readers ?? 1) - 1);
    if (!entry.readers) {
      detachedReaders.delete(entry);
      if (cache?.get(target) === entry) cache.delete(target);
      await FileSystem.deleteAsync(entry.url, {idempotent:true});
    }
  };
  if (entry.bytes !== expected.bytes || entry.contentType !== expected.contentType) {
    await release(); throw new Error('Buffered media descriptor length or content type mismatch.');
  }
  return {uri:entry.url, bytes:entry.bytes, release};
}
// Only completed downloads owned by this live peer may bypass network-URL
// playback checks. A directory prefix alone would also admit injected paths.
export function isPeerMediaUrl(peer: PeerTransport, url: string): boolean {
  if (peer.closed) return false;
  const cache = caches.get(peer);
  return Boolean(cache && Array.from(cache.values()).some(item => item.url === url));
}

export async function clearPeerMedia(peer: PeerTransport) {
  const cache = caches.get(peer); caches.delete(peer);
  if (cache) for (const entry of cache.values()) if (entry.readers) detachedReaders.add(entry);
  if (cache) await Promise.all(Array.from(cache.values()).filter(item => !item.persistent && !item.readers).map(item => FileSystem.deleteAsync(item.url, { idempotent: true }).catch(() => undefined)));
}
