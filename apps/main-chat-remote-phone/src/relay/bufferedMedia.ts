import type { PeerTransport } from './peer';
import {PeerTransportUnavailableError} from './peer';
import type {DiagnosticLink} from '../diagnostics/planTransaction';
import {mediaAcquisition} from '../diagnostics/planTransaction';
import {MediaScopeTrace} from '../diagnostics/mediaScope';
import { retainPeerMedia, PeerMediaCapacityError } from './media';

export type BufferedMediaScope = Readonly<{owner:string; replyId:string; expiresAt:number}>;
export type BufferedMediaDescriptor = Readonly<{id:string; path:string; bytes:number; contentType:string;diagnosticLink?:DiagnosticLink}>;
export type BufferedMediaLease = {uri:string; bytes:number; release():Promise<void>};
export {PeerMediaCapacityError as BufferedMediaCapacityError} from './media';
export class BufferedMediaCleanupError extends Error {
  constructor(){super('Buffered media cleanup remains unconfirmed.');}
}
type RecordEntry = {
  scope:BufferedMediaScope; descriptor:BufferedMediaDescriptor; controller:AbortController;
  consumers:number; task:Promise<BufferedMediaLease>; pin?:BufferedMediaLease;
};

/** Retains existing cache files, never grants playback authority.
 * isCurrent must consult the existing reply/native ownership guard. Transport
 * reconnect alone must neither revoke that guard nor manufacture a new one.
 */
export class BufferedMediaStore {
  private readonly scopeTrace=new MediaScopeTrace();
  private readonly entries = new Map<string, RecordEntry>();
  private readonly revoked = new Set<string>();
  private running = 0;
  private readonly waiting: Array<() => void> = [];
  private readonly maxFiles:number;
  private readonly maxBytes:number;

  constructor(private readonly peer:() => PeerTransport | null,
      private readonly isCurrent:(scope:BufferedMediaScope) => boolean,
      limits:{maxFiles?:number; maxBytes?:number} = {}) {
    this.maxFiles = Math.min(96, limits.maxFiles ?? 96);
    this.maxBytes = Math.min(192*1024*1024, limits.maxBytes ?? 192*1024*1024);
  }

  private scopeKey(scope:BufferedMediaScope) { return JSON.stringify([scope.owner, scope.replyId]); }
  private check(scope:BufferedMediaScope,phase:'acquire'|'acquire_complete'|'transfer'|'owns') {
    if (this.revoked.has(this.scopeKey(scope))) {
      this.scopeTrace.rejected(phase,'revoked',scope);throw new Error('Buffered reply revoked.');
    }
    let now:number|undefined;
    const reason=!scope.owner?'owner_missing':!scope.replyId?'reply_missing'
      :!Number.isFinite(scope.expiresAt)?'expiry_invalid':scope.expiresAt<=(now=Date.now())?'expired'
      :!this.isCurrent(scope)?'scope_not_current':null;
    if(reason){this.scopeTrace.rejected(phase,reason,scope,now);throw new Error('Buffered reply owner authority unavailable or expired.');}
  }

  async acquire(scope:BufferedMediaScope, descriptor:BufferedMediaDescriptor, signal?:AbortSignal):Promise<BufferedMediaLease> {
    this.check(scope,'acquire');
    if (signal?.aborted) throw new Error('Buffered media cancelled.');
    if (!descriptor.path.startsWith('/api/') || descriptor.path.includes('..') || descriptor.path.includes('#')) {
      throw new Error('Invalid buffered media route.');
    }
    if (!descriptor.id || !Number.isSafeInteger(descriptor.bytes) || descriptor.bytes < 1
        || descriptor.bytes > 16*1024*1024 || !['audio/ogg','video/mp4'].includes(descriptor.contentType)) {
      throw new Error('Invalid buffered media descriptor.');
    }
    const key = JSON.stringify([scope.owner, scope.replyId, descriptor.id]);
    let entry = this.entries.get(key);
    if (entry && (entry.descriptor.path !== descriptor.path || entry.descriptor.bytes !== descriptor.bytes
        || entry.descriptor.contentType !== descriptor.contentType || entry.scope.expiresAt !== scope.expiresAt)) {
      throw new Error('Buffered media descriptor identity changed.');
    }
    if(entry)mediaAcquisition(descriptor.diagnosticLink,entry.pin?'retained':'shared_pending',entry.descriptor.diagnosticLink);
    if (!entry) {
      const bytes = Array.from(this.entries.values()).reduce((sum, row) => sum + row.descriptor.bytes, 0);
      if (this.entries.size >= this.maxFiles || bytes + descriptor.bytes > this.maxBytes) {
        throw new PeerMediaCapacityError('Buffered media capacity reached; wait for playback release.');
      }
      const controller = new AbortController();
      entry = {scope:{...scope}, descriptor:{...descriptor}, controller, consumers:0, task:null!};
      this.entries.set(key, entry);
      const captured = entry;
      entry.task = this.transfer(captured).then(pin => {
        captured.pin = pin; return pin;
      }).catch(error => { if (this.entries.get(key) === captured) this.entries.delete(key); throw error; });
    }
    const captured = entry;
    captured.consumers++;
    let released = false;
    let releaseTask:Promise<void> | undefined;
    const release = ():Promise<void> => {
      if (releaseTask) return releaseTask;
      released = true;
      signal?.removeEventListener('abort', aborted);
      captured.consumers--;
      releaseTask = (async () => {
        if (!captured.consumers) {
          captured.controller.abort();
          const pin = await captured.task.catch(() => null);
          await pin?.release();
          if (this.entries.get(key) === captured) this.entries.delete(key);
        }
      })();
      return releaseTask;
    };
    // acquire's catch awaits the same cleanup and propagates any error.
    const aborted = () => { void release().catch(() => undefined); };
    signal?.addEventListener('abort', aborted, {once:true});
    try {
      const pin = await captured.task;
      this.check(scope,'acquire_complete');
      if (released || signal?.aborted || captured.controller.signal.aborted) throw new Error('Buffered media cancelled.');
      // The acquisition signal owns only pending work. Once handed to a
      // native player, Stop must retire that reader before its lease releases.
      signal?.removeEventListener('abort', aborted);
      return {uri:pin.uri, bytes:pin.bytes, release};
    } catch (error) {
      try { await release(); } catch { throw new BufferedMediaCleanupError(); }
      throw error;
    }
  }

  private async transfer(entry:RecordEntry):Promise<BufferedMediaLease> {
    // Reserve at most two request slots for bulk media; commands retain room.
    await new Promise<void>(resolve => {
      if (this.running < 2) { this.running++; resolve(); }
      else this.waiting.push(resolve);
    });
    try {
      this.check(entry.scope,'transfer');
      if (entry.controller.signal.aborted) throw new Error('Buffered media cancelled.');
      const peer = this.peer();
      if (!peer) throw new PeerTransportUnavailableError('Buffered media peer reconnecting.');
      if (peer.cacheScope !== entry.scope.owner) throw new Error('Buffered media peer owner changed.');
      if (peer.closed) throw peer.unavailable();
      return await retainPeerMedia(peer, entry.descriptor.path, entry.descriptor, entry.controller.signal);
    } finally {
      const next = this.waiting.shift();
      if (next) next(); else this.running--;
    }
  }

  owns(scope:BufferedMediaScope, uri:string):boolean {
    try { this.check(scope,'owns'); } catch { return false; }
    return Array.from(this.entries.values()).some(entry => entry.consumers > 0
      && !entry.controller.signal.aborted && this.scopeKey(entry.scope) === this.scopeKey(scope)
      && entry.scope.expiresAt === scope.expiresAt && entry.pin?.uri === uri);
  }

  async revoke(scope:BufferedMediaScope):Promise<void> {
    this.revoked.add(this.scopeKey(scope));
    for (const entry of this.entries.values()) {
      if (this.scopeKey(entry.scope) === this.scopeKey(scope)) entry.controller.abort();
    }
    // Existing native readers must stop and call release before unlinking.
  }
}
