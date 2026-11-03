import { Buffer } from 'buffer';
import {connectionTrace, diagnosticRoute} from '../utils/connectionTrace';
import type { AVRemoteOutput } from './av';
import type { AVReceiver } from '../native/avTracks';
import {AVCompatibilityError} from './av';
import {parseVideoQuality} from './idleLoopCache';
import type {VideoQuality} from './idleLoopCache';
import {PlanTransactionTrace,preparationDiagnosticLink} from '../diagnostics/planTransaction';
import type {DiagnosticLink} from '../diagnostics/planTransaction';
export type BufferedCapability=Readonly<{buffered_media:1;audio_format:'ogg-opus';video_format:'h264-segments';local_video:1;video_quality:VideoQuality}>;
export type PeerResponse = { status: number; contentType: string; body?: unknown; bytes?: Uint8Array };
// Only transport failures may be retried by buffered delivery. Protocol,
// authorization, media validation and cancellation remain terminal to callers.
export class PeerTransportUnavailableError extends Error {}
type Channel = { readyState: string; bufferedAmount: number; send(value: string): void; close(): void; onmessage: ((event: { data: unknown }) => void) | null; onclose: (() => void) | null };
type Pending = { resolve(value: PeerResponse): void; reject(error: Error): void; timer: ReturnType<typeof setTimeout>; cleanup(): void; diagnostic:PlanTransactionTrace; idleRange?: {offset:number;length:number}; idleBytes?:Uint8Array; size?: number; chunks?: Uint8Array[]; received: number; status: number; contentType: string };
export class PeerTransport {
  private sequence = 0; private pending = new Map<string, Pending>(); closed = false;
  get channelState(): string { return this.channel.readyState; }
  get pendingCount(): number { return this.pending.size; }
  onClose: () => void = () => undefined;
  private closeReason:Error = new PeerTransportUnavailableError('Internet peer disconnected.');
  unavailable():Error { return this.closeReason; }
  private av: AVRemoteOutput | null = null;
  mediaError: Error | null = null;
  private avReady: Promise<void>;
  private bufferedReady:Promise<BufferedCapability>|null=null;
  private bufferedNegotiating=false;
  private heartbeatEnabled=false;
  private heartbeatBusy=false;
  private missedHeartbeats=0;
  private lastReceived=performance.now();
  private lastSent=performance.now();
  async sampleHeartbeat():Promise<void> {
    if (!this.heartbeatEnabled || this.closed || this.heartbeatBusy || !this.canRequest()) return;
    const fields=()=>({session_id:this.id,pending:this.pending.size,buffered_bytes:this.channel.bufferedAmount,
      last_receive_age_ms:Math.max(0,performance.now()-this.lastReceived),last_send_age_ms:Math.max(0,performance.now()-this.lastSent)});
    if(this.pending.size>=4 || this.channel.bufferedAmount>65536) {
      connectionTrace.event('peer_heartbeat_skipped',{...fields(),reason:'busy'});return;
    }
    this.heartbeatBusy=true;
    const started=performance.now();
    try {
      const response=await this.request('GET','/api/peer-health',undefined,8000);
      if(response.status!==200 || (response.body as {pong?:number})?.pong!==1) {
        this.heartbeatEnabled=false;
        connectionTrace.event('peer_heartbeat_unavailable',fields());return;
      }
      connectionTrace.event('peer_heartbeat_ok',{...fields(),elapsed_ms:performance.now()-started,missed:this.missedHeartbeats});
      this.missedHeartbeats=0;
    } catch {
      if(!this.closed) connectionTrace.event('peer_heartbeat_missed',{...fields(),elapsed_ms:performance.now()-started,missed:++this.missedHeartbeats},true);
    } finally {this.heartbeatBusy=false;}
  }
  async negotiateBuffered(refresh=false):Promise<BufferedCapability>{
    if(this.closed)throw this.closeReason;
    if(this.media)throw new AVCompatibilityError('Incompatible live-track and buffered media owners.');
    if(refresh&&!this.bufferedNegotiating)this.bufferedReady=null;
    if(!this.bufferedReady){
      this.bufferedNegotiating=true;
      const pending=this.request('POST','/api/buffered/negotiate',
        {version:1,audio_formats:['ogg-opus'],local_video:1},15000).then(response=>{
        const value=response.body as Partial<BufferedCapability>|undefined;
        if(response.status!==200||!response.contentType.startsWith('application/json')||!value
          ||value.buffered_media!==1||value.audio_format!=='ogg-opus'||value.video_format!=='h264-segments'||value.local_video!==1)
          throw new AVCompatibilityError('Update NC desktop for buffered Opus/H.264 playback.');
        if(this.closed)throw this.closeReason;
        this.heartbeatEnabled=(value as {peer_heartbeat?:number}).peer_heartbeat===1;
        return Object.freeze({...value,video_quality:parseVideoQuality(value.video_quality)}) as BufferedCapability;
      });
      this.bufferedReady=pending;
      void pending.then(()=>{this.bufferedNegotiating=false;},()=>{
        this.bufferedNegotiating=false;if(this.bufferedReady===pending)this.bufferedReady=null;
      });
    }
    return this.bufferedReady;
  }
  get avTransportClosed(): boolean { return this.closed && Boolean(this.media); }
  get avHandle(): string { return this.av?.nativeHandle ?? ''; }
  get avPresentationActive(): boolean { return this.av?.presentationActive ?? false; }
  async getAVOutput(): Promise<AVRemoteOutput | null> {
    await this.avReady;
    if (this.mediaError) throw this.mediaError;
    if (this.closed) throw new Error('NC media peer unavailable.');
    return this.av;
  }
  constructor(readonly id: string, private channel: Channel, private media: AVReceiver | null = null,
    readonly cacheScope = '', private canRequest: () => boolean = () => true) {
    channel.onmessage = event => { try { this.receive(event.data); } catch { this.close(new Error('Invalid NC peer response.'), 'invalid_peer_response'); } };
    channel.onclose = () => this.close(undefined, 'data_channel_closed');
    this.avReady = media ? media.connect(this).then(value => {
      if (this.closed) value?.close(); else this.av = value;
    }).catch(error => { this.mediaError = error instanceof Error ? error : new Error('NC media negotiation failed.'); this.close(this.mediaError, 'media_negotiation_failed'); }) : Promise.resolve();
  }
  private async send(frame: Record<string, unknown>, active = () => true) {
    const deadline = Date.now() + 30000;
    while (this.channel.bufferedAmount > 512 * 1024) {
      if (!active()) throw new Error('NC peer request cancelled.');
      if (this.closed) throw this.closeReason;
      if (Date.now() > deadline) throw new PeerTransportUnavailableError('Peer transfer stalled.');
      await new Promise<void>(resolve => setTimeout(resolve, 20));
    }
    if (!active()) throw new Error('NC peer request cancelled.');
    if (this.closed) throw this.closeReason;
    if (this.channel.readyState !== 'open') throw new PeerTransportUnavailableError('Internet peer disconnected.');
    const encoded = JSON.stringify({ v: 1, ...frame });
    if (Buffer.byteLength(encoded) > 65536) throw new Error('Peer frame limit.');
    this.channel.send(encoded);
    this.lastSent=performance.now();
  }
  async request(method: 'GET' | 'POST', path: string, body?: Record<string, unknown>, timeoutMs = 150000, signal?: AbortSignal, diagnosticLink?:DiagnosticLink): Promise<PeerResponse> {
    if (signal?.aborted) throw new Error('NC peer request cancelled.');
    if (this.closed) throw this.closeReason;
    if (!this.canRequest()) throw new PeerTransportUnavailableError('Internet peer disconnected.');
    if (this.pending.size >= 8) throw new Error('Internet peer is busy or disconnected.');
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('..')) throw new Error('Invalid NC peer route.');
    let idleRange: {offset:number;length:number} | undefined;
    if (path.startsWith('/api/idle-cache/file/') || path.startsWith('/api/idle-cache/ordered/file/')) {
      const match = /^\/api\/idle-cache\/(?:ordered\/)?file\/[a-f0-9]{64}\?generation=[a-f0-9]{64}&offset=([0-9]{1,8})&length=([0-9]{1,8})$/.exec(path);
      if (method !== 'GET' || !match || body) throw new Error('Invalid idle range.');
      idleRange = {offset:Number(match[1]), length:Number(match[2])};
      if (idleRange.length < 1 || idleRange.length > 16*1024*1024 || idleRange.offset+idleRange.length > 16*1024*1024) throw new Error('Idle range limit.');
      // One bounded file buffer, leaving the other pending slots for control.
      if([...this.pending.values()].some(item=>item.idleRange))throw new Error('Idle transfer already running.');
    }
    const id = `${this.id}_${++this.sequence}`;
    const started = Date.now();
    const trace = (outcome: string, status = 0) => {
      if (path.split('?')[0] === '/api/debug') return; // Do not recursively log diagnostic uploads.
      connectionTrace.event('peer_request', {request_id:id, route:diagnosticRoute(path), method, outcome,
        elapsed_ms:Date.now()-started, status, pending:this.pending.size, buffered_bytes:this.channel.bufferedAmount},
        outcome === 'timeout' || outcome === 'failed' || status >= 400);
    };
    trace('started');
    const bytes = Buffer.from(JSON.stringify({ v: 1, type: 'request', id, method, path, ...(idleRange ? {accept:'NCI1'} : {}), ...(body ? { body } : {}) }));
    if (bytes.length > 16 * 1024 * 1024) throw new Error('NC request exceeds the transfer limit.');
    const diagnostic=new PlanTransactionTrace(id);
    return diagnostic.observeCall('phone.peer.request',()=>new Promise<PeerResponse>((resolve, reject) => {
      const cleanup = () => signal?.removeEventListener('abort', cancel);
      const cancel = () => {
        clearTimeout(timer); cleanup(); this.pending.delete(id);
        void this.send({type: 'cancel', id}).catch(() => undefined);
        reject(new Error('NC peer request cancelled.'));
      };
      const timer = setTimeout(() => { trace('timeout'); cleanup(); this.pending.delete(id); void this.send({ type: 'cancel', id }).catch(() => undefined); reject(new Error('NC peer request timed out.')); }, timeoutMs);
      this.pending.set(id, { resolve: response => { trace('completed', response.status); resolve(response); },
        reject: error => { trace('failed'); reject(error); }, timer, cleanup, diagnostic, idleRange, received: 0, status: 0, contentType: '' });
      signal?.addEventListener('abort', cancel, {once: true});
      const active = () => this.pending.has(id);
      void (async () => {
        if (bytes.length < 45000) await this.send(JSON.parse(bytes.toString()), active);
        else {
          await this.send({ type: 'request-start', id, bytes: bytes.length }, active);
          for (let offset = 0; offset < bytes.length; offset += 24576) {
            if (!this.pending.has(id)) return;
            // Hermes can return Uint8Array from subarray; explicitly restore
            // Buffer before base64 encoding, or it becomes comma-separated text.
            await this.send({ type: 'request-chunk', id, data: Buffer.from(bytes.subarray(offset, offset + 24576)).toString('base64') }, active);
          }
          await this.send({ type: 'request-end', id }, active);
        }
      })().catch(error => { trace('failed'); clearTimeout(timer); cleanup(); this.pending.delete(id); reject(error); });
    }),preparationDiagnosticLink(body)??preparationDiagnosticLink({trialId:diagnosticLink?.trace_id,diagnosticLink}));
  }
  private receive(raw: unknown) {
    this.lastReceived=performance.now();
    if (typeof raw !== 'string') { this.receiveIdleRange(raw); return; }
    if (typeof raw !== 'string' || Buffer.byteLength(raw) > 65536) throw new Error('Peer frame limit.');
    const message = JSON.parse(raw); if (message.v !== 1) throw new Error('Peer version.');
    if (['response', 'file-start'].includes(message.type) && (!Number.isInteger(message.status) || message.status < 100 || message.status > 599 || typeof message.contentType !== 'string' || message.contentType.length > 256)) throw new Error('Invalid peer response metadata.');
    const item = this.pending.get(message.id); if (!item) return;
    const finish = (response: PeerResponse) => { clearTimeout(item.timer); item.cleanup(); this.pending.delete(message.id);
      item.diagnostic.decision('phone.peer.response','response_status',null,response.status,response.status>=400?'warning':'debug');
      if (item.chunks) item.diagnostic.decision('phone.peer.response','received_bytes',null,item.received);
      item.resolve(response); };
    if (item.idleRange && (message.type !== 'response' || message.status === 200)) {
      clearTimeout(item.timer); item.cleanup(); this.pending.delete(message.id);
      item.reject(new Error('Binary idle transfer required.')); return;
    }
    if (message.type === 'response') finish({ status: message.status, contentType: message.contentType, body: message.body });
    else if (message.type === 'file-start') {
      if (item.chunks || !Number.isInteger(message.bytes) || message.bytes < 0 || message.bytes > 64 * 1024 * 1024) throw new Error('Media transfer limit.');
      item.size = message.bytes; item.chunks = []; item.status = message.status; item.contentType = message.contentType;
    } else if (message.type === 'file-chunk') {
      if (!item.chunks || typeof message.data !== 'string' || message.data.length > 32768) throw new Error('Media chunk limit.');
      const data = Buffer.from(message.data, 'base64'); item.received += data.length;
      if (data.length > 24576 || item.received > item.size!) throw new Error('Media overflow.');
      item.diagnostic.decision('phone.peer.file','received_bytes',null,item.received);
      item.chunks.push(data);
    } else if (message.type === 'file-end') {
      if (!item.chunks || item.received !== item.size) throw new Error('Incomplete media.');
      const bytes = Buffer.concat(item.chunks); finish(item.contentType.includes('json') ? { status: item.status, contentType: item.contentType, body: JSON.parse(bytes.toString()) } : { status: item.status, contentType: item.contentType, bytes });
    } else throw new Error('Invalid peer response.');
  }
  private receiveIdleRange(raw: unknown) {
    // Invalid/cache-only packets cannot terminate Live or grant audio ownership.
    let id = '';
    try {
      const bytes = raw instanceof ArrayBuffer ? Buffer.from(raw)
        : ArrayBuffer.isView(raw) ? Buffer.from(raw.buffer,raw.byteOffset,raw.byteLength) : null;
      if (!bytes || bytes.length < 8 || bytes.length > 8+1024+24576 || bytes.toString('ascii',0,4) !== 'NCI1') throw new Error('Idle frame limit.');
      const count = bytes.readUInt32BE(4);
      if (count < 1 || count > 1024 || 8+count > bytes.length) throw new Error('Idle header limit.');
      const header = JSON.parse(bytes.toString('utf8',8,8+count));
      if (typeof header.id !== 'string') throw new Error('Invalid idle request.');
      id = header.id;
      const item = this.pending.get(id);
      if (!item) return; // Cancelled/duplicate data is discarded, never reused.
      if (!item.idleRange || Object.keys(header).sort().join(',') !== 'id,length,offset'
          || !Number.isSafeInteger(header.length) || header.length<1 || header.length>24576
          || header.offset !== item.idleRange.offset+item.received || item.received+header.length>item.idleRange.length
          || bytes.length !== 8+count+header.length) throw new Error('Idle range mismatch.');
      item.idleBytes??=new Uint8Array(item.idleRange.length);
      item.idleBytes.set(bytes.subarray(8+count),item.received);item.received+=header.length;
      if(item.received!==item.idleRange.length)return;
      clearTimeout(item.timer); item.cleanup(); this.pending.delete(id);
      item.resolve({status:200, contentType:'video/mp4', bytes:item.idleBytes});
    } catch {
      const item = this.pending.get(id);
      if (item?.idleRange) {
        clearTimeout(item.timer); item.cleanup(); this.pending.delete(id);
        item.reject(new Error('Invalid idle transfer.'));
      }
    }
  }
  close(reason:Error = new PeerTransportUnavailableError('Internet peer disconnected.'), origin = 'caller') {
    if (this.closed) return; this.closed = true; this.closeReason = reason;
    connectionTrace.event('peer_close_origin', {session_id:this.id, reason:origin,
      state:this.channel.readyState, pending:this.pending.size, buffered_bytes:this.channel.bufferedAmount,
      last_receive_age_ms:Math.max(0,performance.now()-this.lastReceived),last_send_age_ms:Math.max(0,performance.now()-this.lastSent)},
    origin !== 'session_teardown');
    this.media?.close(); this.av?.close(); this.av = null;
    for (const pending of this.pending.values()) { clearTimeout(pending.timer); pending.cleanup(); pending.reject(this.closeReason); }
    this.pending.clear(); this.channel.close(); this.onClose();
  }
}
import { setBackgroundTimeout as setTimeout, clearBackgroundTimer as clearTimeout } from '../utils/backgroundClock';
