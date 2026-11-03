import { characterRequestError } from './characterErrors';
import { validPersonaRules } from './personaRules';
import type { PeerTransport } from "../relay/peer";
import { awaitReplyReadiness } from '../utils/replyReadiness';
import type { IdleRange } from '../relay/idleLoopTransfer';
import type { IdleManifest } from '../relay/idleLoopCache';
import { StateSyncDecoder, StateSyncResyncRequired } from './stateSync';
import type { LocalAVSession } from '../relay/localAVSession';
import type { AudioSpectrumTimelinePayload, LlmModelSelectionResponse, LlmModelState, TtsProviderState, TtsProviderSelectionResponse, VoiceState, PresenceState, QuickPersonaState, RemoteEnvelope, RemoteHealth, RemoteState } from './types.ts';
import type { AudioMode, PhoneSendEnvelope, PhoneReplyAuth, PhoneReplyReceipt, PhoneReplyAction, PhoneReplyResult, PhoneReplyStatus } from './types.ts';
import type { ConversationActionBody, ConversationActionResult } from './types.ts';
import { recordPhoneDebug, uploadPhoneDebug } from '../utils/phoneDebugBridge.ts';
import { isEmptySttResult } from './envelope.ts';
import {validateProgressivePcmRead} from '../native/progressivePcmPump';

type JsonRecord = Record<string, unknown>;
export type SendTextOptions = {
  audioMode?: AudioMode;
  playOnBackend?: boolean;
  capturePhoneAudio?: boolean;
  visualAfterSend?: boolean;
  debugTraceId?: string;
  imageSource?: 'phone_camera' | 'phone_gallery';
  phoneReplyAuth?: PhoneReplyAuth;
};
export type SttOptions = SendTextOptions & {
  sendToChat?: boolean;
  phoneInterruption?: PhoneReplyReceipt;
  phoneSubmissionId?: string;
};
type RequestOptions = {
  authorize?: boolean;
  timeoutMs?: number;
  privateReply?: boolean;
  signal?: AbortSignal;
};
export type VisualAction = 'show' | 'hide' | 'clear' | 'generate_last';
export type VisualRequestOptions = {
  turnId?: string;
  normalChatTransactionId?: string;
  refinePrompt?: boolean;
};
export type MprcAction = 'play' | 'pause' | 'visual';
export type MprcCastAction = 'status' | 'refresh' | 'install' | 'start' | 'stop';
export type MprcSendOptions = {
  intent?: string;
  speakerId?: string;
};
export type RemoteAuth = { kind: 'lan'; pairingCode: string } | { kind: 'internet'; deviceId: string; deviceToken: string };

const DEFAULT_REQUEST_TIMEOUT_MS = 10000;
const HEALTH_REQUEST_TIMEOUT_MS = 5000;
const STT_REQUEST_TIMEOUT_MS = 120000;
const IMAGE_REQUEST_TIMEOUT_MS = 120000;
const MIN_REQUEST_TIMEOUT_MS = 1000;
const MAX_REQUEST_TIMEOUT_MS = 10 * 60 * 1000;
const STORY_LIBRARY_ERRORS = new Set([
  'Story name must contain 1–120 characters.',
  'A saved story already has this name.',
  'The conversation changed. Refresh and try again.',
  'Wait for the assistant reply to finish before saving.',
  'Story progress is still being checked. Try Save again.',
  'A chat image is missing; this story was not saved.',
  'Saved character media is unavailable.',
  'Saved story file is missing or corrupted.',
  'Saved story version is unavailable or corrupted.',
  'The active saved story was removed. Use Save Story As.',
]);
const DROPPED_MEDIA_QUERY_KEYS = new Set(['code', 'token']);
const PHONE_REPLY_PLAY_ON_BACKEND = false;
const PHONE_REPLY_CAPTURE_AUDIO = true;
let replyDiagnosticSequence = 0;

function recordReplyDiagnostic(event: string, details: Record<string, string | number | boolean>): Promise<void> {
  try { return Promise.resolve(recordPhoneDebug('info', event, details)).catch(() => undefined); }
  catch { return Promise.resolve(); }
}

export class RemoteRequestError extends Error {
  public readonly status: number;
  public readonly payload: unknown;
  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = 'RemoteRequestError';
    this.status = status;
    this.payload = payload;
  }
}

export function isRemoteAuthError(exc: unknown): boolean {
  return exc instanceof RemoteRequestError && !phoneReplyErrorCode(exc) && (exc.status === 401 || exc.status === 429);
}

export function phoneReplyErrorCode(exc: unknown): string {
  if (!(exc instanceof RemoteRequestError) || !exc.payload || typeof exc.payload !== 'object') return '';
  const code = (exc.payload as JsonRecord).error;
  return typeof code === 'string' && /^phone_reply_[a-z_]+$/.test(code) ? code : '';
}

export function phoneReplyRequestId(payload: unknown): string | null {
  const result = (payload as { result?: JsonRecord } | null)?.result;
  if (!result) return null;
  const sent = result.send_result as JsonRecord | undefined;
  const id = result.status === 'accepted' || result.status === 'duplicate' ? result.next_phone_request_id
    : sent?.accepted === true ? sent.phone_request_id : result.accepted === true ? result.phone_request_id : null;
  return typeof id === 'string' && id.length > 0 && [...id].length <= 128 ? id : null;
}

export function isUncertainPhoneReplyError(exc: unknown): boolean {
  return !(exc instanceof RemoteRequestError) || phoneReplyErrorCode(exc) === 'phone_reply_pending';
}

/** Retry only a fixed private operation; caller retains the original body and ownership. */
export async function retryPhoneReply<T>(operation: () => Promise<T>, stillOwned: () => boolean): Promise<T> {
  const deadline = Date.now() + 900_000;
  const operationNumber = ++replyDiagnosticSequence, started = Date.now();
  let attempt = 0;
  const note = (stage: string) => { void recordReplyDiagnostic('phone_reply_retry', {
    operation_number: operationNumber, stage, attempt, elapsed_ms: Math.max(0, Date.now()-started),
  }); };
  while (true) {
    if (!stillOwned()) { note('ownership_ended'); throw new Error('Phone reply ownership ended.'); }
    ++attempt;
    try { const result = await operation(); note('completed'); return result; }
    catch (failure) {
      if (!isUncertainPhoneReplyError(failure)) { note('definitive_failure'); throw failure; }
      if (Date.now() >= deadline) { note('deadline_expired'); throw failure; }
      if (!stillOwned()) { note('ownership_ended'); throw failure; }
      note('retrying');
      await new Promise<void>(resolve => setTimeout(resolve, 1000));
    }
  }
}

function timeoutError(timeoutMs: number): Error {
  return new Error(`Remote request timed out after ${Math.round(timeoutMs / 1000)} seconds.`);
}

function normalizeTimeoutMs(timeoutMs: number | undefined): number {
  const parsed = Number(timeoutMs ?? DEFAULT_REQUEST_TIMEOUT_MS);
  if (!Number.isFinite(parsed)) {
    return DEFAULT_REQUEST_TIMEOUT_MS;
  }
  return Math.max(MIN_REQUEST_TIMEOUT_MS, Math.min(MAX_REQUEST_TIMEOUT_MS, parsed));
}

export class RemoteClient {
  private progressiveModeKey = '';
  private progressiveModeTail: Promise<void> = Promise.resolve();

  async setProgressiveAudioMode(auth: PhoneReplyAuth, enabled: boolean): Promise<void> {
    const key = JSON.stringify([auth.client_key,auth.connection_epoch,enabled]);
    const pending = this.progressiveModeTail.catch(() => undefined).then(async () => {
      if (this.progressiveModeKey === key) return;
      const {result} = await this.request<{result:{version:1;enabled:boolean}}>('POST', '/api/audio/progressive/mode',
        {auth,version:1,enabled}, {privateReply:true});
      if (result?.version !== 1 || result.enabled !== enabled) throw new Error('Progressive audio mode was not confirmed.');
      this.progressiveModeKey = key;
    });
    this.progressiveModeTail = pending;
    return pending;
  }

  async readProgressiveAudio(auth: PhoneReplyAuth, chunk: import('./types').AudioChunk, cursor: number, signal: AbortSignal): Promise<import('./types').ProgressivePcmRead> {
    if (!Number.isSafeInteger(cursor) || cursor < 0 || cursor > 1_440_000
      || !chunk.phone_request_id || !Number.isInteger(chunk.sequence_index) || chunk.sequence_index! < 0)
      throw new Error('Invalid progressive audio cursor.');
    const {result} = await this.request<{result:unknown}>('POST', '/api/audio/progressive/read',
      {auth,phone_request_id:chunk.phone_request_id,chunk_id:chunk.id,sequence_index:chunk.sequence_index,cursor},
      {privateReply:true,timeoutMs:15000,signal});
    return validateProgressivePcmRead(result,cursor);
  }

  private soundscapeInstance = '';
  private priorityRequests = 0;
  get soundscapeCacheScope(): string {
    if (!this.soundscapeInstance) return '';
    if (this.peer) return !this.peer.closed && this.peer.cacheScope ? `sound|${this.peer.cacheScope}|${this.soundscapeInstance}` : '';
    return this.auth.kind === 'lan' ? `sound|${this.baseUrl}|${this.auth.pairingCode}|${this.soundscapeInstance}` : '';
  }
  get soundscapeTransferBusy(): boolean { return this.priorityRequests > 0 || (this.peer?.pendingCount ?? 0) > 0; }
  async soundscapeRequest<T>(method:'GET'|'POST', path:string, body?:JsonRecord, signal?:AbortSignal):Promise<T> {
    if (!path.startsWith('/api/soundscape/')) throw new Error('Invalid sound request.');
    const value = await this.request<T>(method,path,body,{privateReply:true,timeoutMs:15000,signal});
    const instance = (value as {instance_id?:unknown})?.instance_id;
    if(typeof instance==='string' && /^[0-9a-f]{32}$/.test(instance)) this.soundscapeInstance=instance;
    return value;
  }
  async soundscapePart(hash:string,offset:number,length:number,signal:AbortSignal):Promise<Uint8Array> {
    if(!/^[0-9a-f]{64}$/.test(hash) || !Number.isSafeInteger(offset) || !Number.isSafeInteger(length)
      || offset<0 || length<1 || length>256*1024 || offset+length>100*1024*1024) throw new Error('Invalid sound part.');
    const result=await this.idleCacheRead(`/api/soundscape/media/${hash}?offset=${offset}&length=${length}`,
      256*1024,signal,10000,()=>this.soundscapeCacheScope);
    if(result.status!==200 || result.contentType!=='audio/ogg' || result.bytes.byteLength!==length) throw new Error('Sound download failed.');
    return result.bytes;
  }
  private stateDecoder = new StateSyncDecoder();
  private stateEpoch = 0;
  private stateTail: Promise<unknown> = Promise.resolve();
  resetStateSync(): void { this.stateEpoch++; this.stateDecoder.reset(); this.stateTail = Promise.resolve(); }
  private peer?: PeerTransport;
  private localMedia?: LocalAVSession;
  bindLocalMedia(session: LocalAVSession | undefined) { this.localMedia = session; }
  localAVSignal(action: 'offer' | 'candidate' | 'close', body: Record<string, unknown>) {
    return this.request<Record<string, unknown>>('POST', `/api/local-av/${action}`, body, { timeoutMs: 15000 });
  }
  get isRelay(): boolean { return Boolean(this.peer); }
  get bufferedPeer():PeerTransport|null { return this.peer ?? this.localMedia?.peer ?? null; }
  get avHandle(): string { return (this.peer ?? this.localMedia)?.avHandle ?? ''; }
  get avPresentationActive(): boolean { return (this.peer ?? this.localMedia)?.avPresentationActive ?? false; }
  get avTransportClosed(): boolean { return (this.peer ?? this.localMedia)?.avTransportClosed ?? false; }
  requestAVRecovery(): boolean {
    if (this.localMedia) return this.localMedia.requestRecovery();
    if (!this.peer || !this.peer.avHandle || this.peer.closed) return false;
    this.peer.close(); // Existing relay owner reconnects; never issues a playback capability here.
    return true;
  }
  async getAVOutput() {
    if (this.peer) return this.peer.getAVOutput();
    if (this.localMedia) return this.localMedia.getAVOutput();
    throw new Error('Local Opus/H.264 media is not connected.');
  }
  static forPeer(peer: PeerTransport): RemoteClient {
    const client = new RemoteClient("http://nc-peer.invalid", "relay"); client.peer = peer; return client;
  }
  public readonly baseUrl: string;
  public readonly auth: RemoteAuth;
  constructor(baseUrl: string, pairingCode: string);
  constructor(baseUrl: string, auth: RemoteAuth);
  constructor(baseUrl: string, pairingCodeOrAuth: string | RemoteAuth) {
    this.baseUrl = String(baseUrl || '').replace(/\/+$/, '');
    this.auth = typeof pairingCodeOrAuth === 'string' ? { kind: 'lan', pairingCode: pairingCodeOrAuth } : pairingCodeOrAuth;
  }
  static forLan(baseUrl: string, pairingCode: string): RemoteClient { return new RemoteClient(baseUrl, { kind: 'lan', pairingCode }); }
  static forInternet(baseUrl: string, deviceId: string, deviceToken: string): RemoteClient { return new RemoteClient(baseUrl, { kind: 'internet', deviceId, deviceToken }); }
  get pairingCode(): string { return this.auth.kind === 'lan' ? this.auth.pairingCode : ''; }
  get identityKey(): string { if (this.peer) return `relay|${this.peer.id}`; return this.auth.kind === 'lan' ? `lan|${this.baseUrl}` : `internet|${this.baseUrl}|${this.auth.deviceId}`; }

  /** Storage identity only, never a playback capability. Do not log this value. */
  get idleCacheScope(): string {
    if(this.peer) return !this.peer.closed && this.peer.cacheScope ? `relay|${this.peer.cacheScope}` : '';
    if(this.auth.kind!=='lan' || this.localMedia?.state!=='connected' || !this.localMedia.desktopInstance) return '';
    return `lan|${this.baseUrl}|${this.localMedia.desktopInstance}|${this.auth.pairingCode}`;
  }

  async idleCacheManifest(signal:AbortSignal,sourceBinding=false,ordered=false):Promise<IdleManifest|null> {
    const result=await this.idleCacheRead('/api/idle-cache/'+(ordered?'ordered/':'')+'manifest'+(sourceBinding?'?frame_handoff=1':''),128*1024,signal);
    if(result.status===202) return null;
    if(result.status!==200 || !result.contentType.startsWith('application/json')) throw Object.assign(new Error('Idle inventory unavailable.'),{
      idleTransfer:{stage:'manifest',http_status:result.status,received_bytes:result.bytes.byteLength,expected_bytes:0}});
    const {Buffer}=require('buffer') as typeof import('buffer');
    const {parseIdleManifest}=require('../relay/idleLoopCache') as typeof import('../relay/idleLoopCache');
    return parseIdleManifest(JSON.parse(Buffer.from(result.bytes).toString('utf8')));
  }

  async idleCacheSettings(signal:AbortSignal):Promise<{enabled:boolean;preset:string;revision:number;clear_generation:number}>{
    const result=await this.idleCacheRead('/api/idle-cache/settings',2048,signal);
    if(result.status!==200 || !result.contentType.startsWith('application/json'))throw new Error('Idle settings unavailable.');
    const {Buffer}=require('buffer') as typeof import('buffer');
    const value=JSON.parse(Buffer.from(result.bytes).toString('utf8'));
    if(!value || typeof value.enabled!=='boolean' || !['low','balanced','high'].includes(value.preset)
      || !Number.isSafeInteger(value.revision) || value.revision<0
      || !Number.isSafeInteger(value.clear_generation) || value.clear_generation<0)throw new Error('Invalid idle settings.');
    return value;
  }

  async idleCacheRange(range:IdleRange,signal:AbortSignal,ordered=false):Promise<Uint8Array> {
    if(!/^[a-f0-9]{64}$/.test(range.id) || !/^[a-f0-9]{64}$/.test(range.generation)
        || !Number.isSafeInteger(range.offset) || !Number.isSafeInteger(range.length)
        || range.offset<0 || range.length<1 || range.length>16*1024*1024 || range.offset+range.length>16*1024*1024)
      throw new Error('Invalid idle range.');
    const path=`/api/idle-cache/${ordered?'ordered/':''}file/${range.id}?generation=${range.generation}&offset=${range.offset}&length=${range.length}`;
    const result=await this.idleCacheRead(path,range.length,signal,60000);
    if(result.status!==200 || result.contentType!=='video/mp4' || result.bytes.byteLength!==range.length)
      throw Object.assign(new Error('Idle range unavailable.'),{
        idleTransfer:{stage:'range',http_status:result.status,received_bytes:result.bytes.byteLength,expected_bytes:range.length}});
    return result.bytes;
  }

  private async idleCacheRead(path:string,limit:number,signal:AbortSignal,timeoutMs=10000,currentScope=()=>this.idleCacheScope) {
    const scope=currentScope();
    const live=()=>{if(!scope || currentScope()!==scope || signal.aborted) throw new Error('Idle request ownership ended.');};
    live();
    if(this.peer) {
      const response=await this.peer.request('GET',path,undefined,timeoutMs,signal);live();
      const {Buffer}=require('buffer') as typeof import('buffer');
      const bytes=response.bytes ?? Buffer.from(JSON.stringify(response.body ?? {}));
      if(bytes.byteLength>limit) throw new Error('Idle response limit.');
      return {status:response.status,contentType:response.contentType,bytes};
    }
    const controller=new AbortController();
    let rejectAborted:(error:Error)=>void=()=>undefined;
    const cancelled=new Promise<never>((_,reject)=>{rejectAborted=reject;});
    const abort=()=>{controller.abort();rejectAborted(new Error('Idle request cancelled.'));};
    signal.addEventListener('abort',abort,{once:true});
    const timer=setTimeout(abort,timeoutMs);
    try {
      const result=await Promise.race([cancelled,(async()=>{
        const response=await fetch(this.absoluteUrl(path),{method:'GET',redirect:'error',signal:controller.signal,
          headers:{'X-NC-Phone-Code':this.pairingCode}});
        live();
        const length=Number(response.headers.get('Content-Length'));
        if(!Number.isSafeInteger(length) || length<1 || length>limit) throw new Error('Idle response limit.');
        const bytes=new Uint8Array(await response.arrayBuffer());live();
        if(bytes.byteLength!==length) throw new Error('Idle response length mismatch.');
        return {status:response.status,contentType:response.headers.get('Content-Type') || '',bytes};
      })()]);
      live();return result;
    } finally {clearTimeout(timer);signal.removeEventListener('abort',abort);controller.abort();}
  }

  absoluteUrl(path: string): string {
    const base = this.baseUrl.replace(/\/+$/, '');
    const nextPath = path.startsWith('/') ? path : `/${path}`;
    return `${base}${nextPath}`;
  }

  authorizedUrl(path: string, params: JsonRecord = {}): string {
    const target = path.startsWith('/') ? path : `/${path}`;
    const queryStart = target.indexOf('?');
    const targetPath = queryStart >= 0 ? target.slice(0, queryStart) : target;
    const targetQuery = queryStart >= 0 ? target.slice(queryStart + 1) : '';
    const search = new URLSearchParams(targetQuery);
    for (const key of Array.from(search.keys())) {
      if (DROPPED_MEDIA_QUERY_KEYS.has(key.toLowerCase())) {
        search.delete(key);
      }
    }
    for (const [key, value] of Object.entries(params)) {
      if (!DROPPED_MEDIA_QUERY_KEYS.has(key.toLowerCase()) && value !== undefined && value !== null && String(value) !== '') {
        search.set(key, String(value));
      }
    }
    if (this.auth.kind === 'lan' && this.auth.pairingCode) {
      search.set('code', this.auth.pairingCode);
    }
    const suffix = search.toString();
    return this.absoluteUrl(`${targetPath}${suffix ? `?${suffix}` : ''}`);
  }

  apiUrl(path: string): string {
    return this.absoluteUrl(path);
  }

  async websocketUrl(): Promise<string> {
    if (this.peer) throw new Error("WebRTC carries NC state over its peer channel.");
    if (this.auth.kind === 'lan') return this.authorizedUrl('/ws', {state_sync:1}).replace(/^http:/, 'ws:').replace(/^https:/, 'wss:');
    const payload = await this.request<{ ok?: boolean; ticket?: unknown }>('POST', '/internet/ws-ticket', {});
    const ticket = String(payload.ticket || '');
    if (!/^[A-Za-z0-9_-]{8,512}$/.test(ticket)) throw new Error('Internet gateway returned an invalid WebSocket ticket.');
    const url = new URL('/ws', this.baseUrl); url.protocol = 'wss:'; url.searchParams.set('ticket', ticket); url.searchParams.set('state_sync', '1'); return url.toString();
  }

  ownsRelayMediaUrl(url: string): boolean {
    if (!this.peer) return false;
    const { isPeerMediaUrl } = require("../relay/media") as typeof import("../relay/media");
    return isPeerMediaUrl(this.peer, url);
  }

  async requestLiveVisual(method: 'GET' | 'POST', path: string, body?: JsonRecord, signal?: AbortSignal, diagnosticLink?:import('../diagnostics/planTransaction').DiagnosticLink): Promise<unknown> {
    const allowed = method === 'POST'
      ? /^\/api\/dev\/musetalk-live\/(arm|recover|prepare|prefetch|cancel|anticipation-cursor|idle-chunks|idle-chunk-cursor|wait-ready)$/.test(path)
      : /^\/api\/dev\/musetalk-live\/status\/[a-f0-9]{32}$/.test(path);
    const peer=this.bufferedPeer;
    if (!peer || !allowed) throw new Error('Live visual peer route unavailable.');
    const {Buffer} = require('buffer') as typeof import('buffer');
    if (body && Buffer.byteLength(JSON.stringify(body)) > 4096) throw new Error('Live visual payload too large.');
    const response = await peer.request(method, path, body, 2000, signal, diagnosticLink);
    if (response.status !== 200) {
      const {liveControlReason,recordLiveControlRejection}=require('../diagnostics/liveControl') as typeof import('../diagnostics/liveControl');
      const diagnosticReason=liveControlReason(response.body);
      recordLiveControlRejection(diagnosticReason,response.status);
      throw Object.assign(new Error('Live visual request failed.'), {httpStatus: response.status,diagnosticReason});
    }
    if (!response.contentType.includes('json') || response.body === undefined
      || Buffer.byteLength(JSON.stringify(response.body)) > 512 * 1024) throw new Error('Invalid live visual status.');
    return response.body;
  }

  async authorizedMediaUrl(path: string, params: JsonRecord = {}): Promise<{ url: string; expiresAt: number }> {
    if (this.peer) { const { peerMedia } = require("../relay/media") as typeof import("../relay/media"); return peerMedia(this.peer, path, params); }
    if (this.auth.kind === 'lan') return { url: this.authorizedUrl(path, params), expiresAt: 0 };
    const payload = await this.request<{ ok?: boolean; url?: unknown; expires_at?: unknown }>('POST', '/internet/media-ticket', { path, method: 'GET', params });
    const resolved = new URL(String(payload.url || ''), this.baseUrl); const base = new URL(this.baseUrl);
    if (resolved.origin !== base.origin || resolved.protocol !== 'https:' || resolved.pathname !== '/media') throw new Error('Internet gateway returned an invalid media URL.');
    const rawExpiry = Number(payload.expires_at || 0); const expiresAt = rawExpiry > 0 && rawExpiry < 1_000_000_000_000 ? rawExpiry * 1000 : rawExpiry;
    return { url: resolved.toString(), expiresAt };
  }

  async health(expectedGatewayId = ''): Promise<RemoteEnvelope<RemoteHealth>> {
    const payload = await this.request<RemoteEnvelope<RemoteHealth>>('GET', '/health', undefined, { authorize: false, timeoutMs: HEALTH_REQUEST_TIMEOUT_MS });
    if (this.auth.kind === 'internet' && expectedGatewayId && String(payload.gateway_id || '') !== expectedGatewayId) throw new Error('Internet gateway identity does not match the enrolled desktop.');
    return payload;
  }

  async state(options: {forceFull?:boolean} = {}): Promise<RemoteState> {
    const epoch = this.stateEpoch;
    const run = async () => {
      const check = () => { if (epoch !== this.stateEpoch) throw new Error('State connection changed.'); };
      check();
      if (options.forceFull) this.stateDecoder.reset();
      for (let attempt = 0; attempt < 2; ++attempt) {
        check();
        const cursor = this.stateDecoder.cursor();
        const query = new URLSearchParams({sync:'1'});
        if (cursor) for (const [key, value] of Object.entries(cursor)) query.set(key, String(value));
        const payload = await this.request<RemoteEnvelope<{state_sync:unknown}>>('GET', `/api/state?${query}`);
        check();
        if (!payload.ok) throw new Error(payload.error || 'State request failed.');
        try { return this.stateDecoder.apply(payload.state_sync).state; }
        catch (error) {
          this.stateDecoder.reset();
          if (!(error instanceof StateSyncResyncRequired) || attempt) throw error;
        }
      }
      throw new StateSyncResyncRequired();
    };
    const pending = this.stateTail.then(run, run);
    this.stateTail = pending.catch(() => undefined);
    return pending;
  }

  async presence(): Promise<PresenceState> {
    const payload = await this.request<RemoteEnvelope<{ presence: PresenceState }>>('GET', '/api/presence');
    if (!payload.ok || !payload.presence || typeof payload.presence !== 'object') {
      throw new Error(payload.error || 'Presence request failed.');
    }
    return payload.presence;
  }

  async commandDraft(action: 'start' | 'status' | 'cancel', body: { id: string; command?: string; text?: string; options?: import('./types').StoryRefineOptions }) {
    const payload = await this.request<{ok: boolean; result?: import('./types').CommandDraftResult; error?: string}>(
      'POST', `/api/commands/${action}`, body, { privateReply: true });
    if (!payload.ok || !payload.result || payload.result.id !== body.id
      || !['working', 'ready', 'error', 'cancelled'].includes(payload.result.status)
      || (payload.result.status === 'ready' && (body.command === 'story_refine' || body.command === 'story_extend'
        ? !payload.result.plan : typeof payload.result.text !== 'string' || !payload.result.text || payload.result.text.length > 32000)))
      throw new Error(payload.error || 'Invalid draft response.');
    return payload.result;
  }

  async storyPlan(body: import('./types').StoryPlanAction): Promise<import('./types').StoryPlan | null> {
    const payload = await this.request<{ok: boolean; result?: import('./types').StoryPlan | null; error?: string}>(
      'POST', '/api/story-plan', body, { privateReply: true });
    if (!payload.ok || !('result' in payload)) throw new Error(payload.error || 'Story Plan request failed.');
    return payload.result ?? null;
  }

  async visualAuto(body: import('./types').VisualAutoAction): Promise<import('./types').VisualAutoStatus> {
    const payload = await this.request<{ok: boolean; result?: import('./types').VisualAutoStatus; error?: string}>(
      'POST', '/api/visual-auto', body, { privateReply: true });
    if (!payload.ok || !payload.result || !['off', 'user', 'assistant', 'story'].includes(payload.result.mode)
      || !Number.isSafeInteger(payload.result.revision))
      throw new Error(payload.error || 'Visual Reply settings request failed.');
    return payload.result;
  }

  async storyLibrary(body: import('./types').StoryLibraryAction): Promise<import('./types').StoryLibraryResult> {
    const payload = await this.request<{ok: boolean; result?: import('./types').StoryLibraryResult; error?: string}>(
      'POST', '/api/story-library', body, { privateReply: true,
        timeoutMs: ['save', 'save_as', 'open'].includes(body.action) ? 90_000 : 10_000 });
    if (!payload.ok || !payload.result || typeof payload.result !== 'object')
      throw new Error(payload.error || 'Story Library request failed.');
    const result = payload.result;
    if (body.action === 'list' && (!Array.isArray(result.entries)
      || result.entries.some(row => !row || typeof row.entry_id !== 'string' || typeof row.name !== 'string'
        || typeof row.saved_at !== 'string' || !Number.isSafeInteger(row.version)
        || !Array.isArray(row.character_names))))
      throw new Error('Story Library returned an invalid list.');
    if (['save', 'save_as', 'rename'].includes(body.action)
      && (!result.entry_id || !result.name || !result.saved_at || !Number.isSafeInteger(result.version)))
      throw new Error('Story Library did not confirm the saved entry.');
    if (body.action === 'open' && (result.entry_id !== body.entry_id || result.state !== 'paused'))
      throw new Error('Story Library did not confirm the opened story.');
    return result;
  }

  async quickPersonas(): Promise<QuickPersonaState> {
    const payload = await this.request<RemoteEnvelope<{ personas: QuickPersonaState }>>('GET', '/api/personas');
    if (!payload.ok || !payload.personas || !Array.isArray(payload.personas.items)) {
      throw new Error(payload.error || 'Quick Persona list request failed.');
    }
    return payload.personas;
  }

  async chatCharacters(all = false, offset = 0): Promise<import('./types').ChatCharacterSnapshot> {
    return this.characterRequest('GET', `/api/chat-characters?all=${all ? 1 : 0}&limit=100&offset=${offset}`);
  }

  async characterRequest<T>(method: 'GET' | 'POST', path: string, body?: JsonRecord): Promise<T> {
    if (!/^\/api\/chat-characters(?:[/?]|$)/.test(path)) throw new Error('Invalid character route.');
    const payload = await this.request<{ok: boolean; result?: T; error?: string}>(method, path, body, {privateReply: true});
    if (!payload.ok || !payload.result) throw new Error(payload.error || 'Character request failed.');
    return payload.result;
  }

  async selectQuickPersona(slot: number) {
    return this.request('POST', '/api/personas/select', { slot: Math.max(0, Math.trunc(slot)) });
  }

  async personaPrompts(id: string, edit?: { revision: string; system_prompt: string; technical_prompt: string; technical_rules?: import('./types').PersonaTechnicalRules }): Promise<import('./types').PersonaPrompts> {
    const payload = await this.request<RemoteEnvelope<{ result: import('./types').PersonaPrompts }>>(
      'POST', '/api/personas/prompts', { id, action: edit ? 'save' : 'read', ...edit }, { privateReply: true });
    const result = payload.result;
    if (!payload.ok || !result || result.id !== id || typeof result.revision !== 'string'
      || typeof result.system_prompt !== 'string' || typeof result.technical_prompt !== 'string'
      || typeof result.defaults?.system_prompt !== 'string' || typeof result.defaults?.technical_prompt !== 'string'
      || !validPersonaRules(result))
      throw new Error(payload.error || 'Could not load or save persona prompts. Update the desktop if needed.');
    return result;
  }

  async llmModels(): Promise<LlmModelState> {
    const payload = await this.request<{ ok: boolean; models?: LlmModelState; error?: string }>('GET', '/api/llm/models');
    if (!payload.ok || !payload.models) throw new Error(payload.error || 'Language model list request failed.');
    return payload.models;
  }

  async continuousSpeech(auth:PhoneReplyAuth, operationId:string, action:'start'|'status'|'played', chunkCount?:number): Promise<import('./types').ContinuousSpeechState> {
    const payload=await this.request<{ok:boolean;result:import('./types').ContinuousSpeechState}>(
      'POST','/api/continuous/speech',{auth,operation_id:operationId,action,chunk_count:chunkCount},{privateReply:true});
    const result=payload.result;
    if(!result || result.operation_id!==operationId || !Array.isArray(result.chunks) || result.chunks.length>64
      || result.chunks.some((chunk,index)=>chunk.sequence_index!==index || !/^\/api\/audio\/file\/[A-Za-z0-9_-]+$/.test(chunk.url_path))) {
      throw new Error('Invalid desktop user speech response.');
    }
    return result;
  }

  async continuousStatus(auth: PhoneReplyAuth): Promise<import('./types').ContinuousState> {
    const payload = await this.request<{ok:boolean; result:import('./types').ContinuousState}>(
      'POST', '/api/continuous/status', {auth}, {privateReply:true});
    if (!payload.ok || payload.result?.version !== 1 || !Number.isInteger(payload.result.revision))
      throw new Error('Continuous Mode state is unavailable.');
    return payload.result;
  }

  async continuousCommand(auth: PhoneReplyAuth, body: Record<string, unknown>): Promise<import('./types').ContinuousState> {
    const payload = await this.request<{ok:boolean; result:import('./types').ContinuousState; error?:string}>(
      'POST', '/api/continuous/command', {...body,auth}, {privateReply:true});
    if (!payload.ok || payload.result?.version !== 1) throw new Error(payload.error || 'Continuous command was not accepted.');
    return payload.result;
  }

  async claimContinuous(auth: PhoneReplyAuth, operationId: string) {
    type Claim = {ok:boolean; result:{accepted:boolean; status:string; phone_request_id?:string}};
    let payload: Claim;
    try {
      payload = await this.request<Claim>('POST','/api/continuous/claim',{auth,operation_id:operationId},{privateReply:true});
    } catch(failure) {
      const response = failure instanceof RemoteRequestError ? failure.payload as Claim | null : null;
      if (response?.result?.status === 'pending') throw new RemoteRequestError('Automatic reply acknowledgement pending.',409,{error:'phone_reply_pending'});
      if (response?.result?.accepted === false && ['stale','busy','cancelled','unavailable'].includes(response.result.status)) payload=response;
      else throw failure;
    }
    if (payload.result?.status === 'pending') throw new RemoteRequestError('Automatic reply acknowledgement pending.',409,{error:'phone_reply_pending'});
    const result = payload.result;
    if (result?.accepted) return {ok:true,result:{accepted:true,phone_request_id:result.phone_request_id}};
    return {ok:false,error:`Automatic reply ${result?.status || 'unavailable'}. Refresh Continuous Mode.`,result:{accepted:false}};
  }

  async selectLlmModel(providerId: string, modelId: string): Promise<LlmModelSelectionResponse> {
    return this.request('POST', '/api/llm/models/select', { provider_id: providerId, model_id: modelId });
  }

  async ttsProviders(): Promise<TtsProviderState> {
    const payload = await this.request<{ok: boolean; tts?: TtsProviderState; error?: string}>('GET', '/api/tts/providers');
    const state = payload.tts;
    if (!payload.ok || !state || state.schema_version !== 1
      || typeof state.available !== 'boolean' || typeof state.loading !== 'boolean'
      || typeof state.busy !== 'boolean' || typeof state.selected_provider_id !== 'string'
      || typeof state.message !== 'string' || !Array.isArray(state.providers)
      || state.providers.some(provider => !provider || typeof provider.id !== 'string'
        || typeof provider.label !== 'string' || typeof provider.selected !== 'boolean'
        || typeof provider.available !== 'boolean' || typeof provider.story_voices !== 'boolean'
        || typeof provider.progressive_audio !== 'boolean' || typeof provider.message !== 'string')) {
      throw new Error('TTS provider list is unavailable. Update or check the desktop.');
    }
    return state;
  }

  async selectTtsProvider(providerId: string): Promise<TtsProviderSelectionResponse> {
    return this.request('POST', '/api/tts/providers/select', {provider_id: providerId});
  }

  async voices(): Promise<VoiceState> {
    const payload = await this.request<{ ok: boolean; voices?: VoiceState; error?: string }>('GET', '/api/voices');
    if (!payload.ok || !payload.voices || !Array.isArray(payload.voices.items)) {
      throw new Error(payload.error || 'Voice list request failed. Update or check the desktop.');
    }
    return payload.voices;
  }

  async selectVoice(voiceId: string): Promise<RemoteEnvelope<{ result: { accepted: boolean; message: string } }>> {
    return this.request('POST', '/api/voices/select', { voice_id: voiceId });
  }

  async sendText(text: string, options: SendTextOptions = {}) {
    return this.request<PhoneSendEnvelope>('POST', '/api/send', {
      text,
      audio_mode: options.audioMode ?? 'backend_hq',
      play_on_backend: PHONE_REPLY_PLAY_ON_BACKEND,
      capture_phone_audio: options.audioMode === 'phone_native' ? false : PHONE_REPLY_CAPTURE_AUDIO,
      visual_after_send: Boolean(options.visualAfterSend),
      debug_trace_id: String(options.debugTraceId || ''),
      ...(options.phoneReplyAuth ? { phone_reply_auth: options.phoneReplyAuth } : {}),
    }, { privateReply: Boolean(options.phoneReplyAuth) });
  }

  async openPhoneReplySession(sharedQueueVersion?: 1, continuationVersion?: 1): Promise<PhoneReplyAuth> {
    if (continuationVersion === 1 && sharedQueueVersion !== 1) throw new Error('Phone reply session unavailable.');
    const payload = await this.request<{ result: PhoneReplyAuth }>('POST', '/api/phone-reply/session',
      {...(sharedQueueVersion === 1 ? { shared_queue_version: 1 } : {}),
        ...(continuationVersion === 1 ? {reply_continuation_version: 1} : {})}, { privateReply: true });
    if (typeof payload.result?.client_key !== 'string' || !payload.result.client_key
      || typeof payload.result.connection_epoch !== 'string' || !payload.result.connection_epoch
      || (payload.result.shared_queue_version !== undefined && payload.result.shared_queue_version !== 1)
      || payload.result.reply_continuation_version !== continuationVersion
      || (sharedQueueVersion === 1 && payload.result.shared_queue_version !== 1)) throw new Error('Phone reply session unavailable.');
    return Object.freeze({ client_key: payload.result.client_key, connection_epoch: payload.result.connection_epoch,
      ...(payload.result.shared_queue_version === 1 ? { shared_queue_version: 1 as const } : {}),
      ...(continuationVersion === 1 ? {reply_continuation_version: 1 as const} : {}) });
  }

  async sendPhoneReplyAction(auth: PhoneReplyAuth, action: PhoneReplyAction): Promise<PhoneReplyResult> {
    const started = Date.now(), requestNumber = ++replyDiagnosticSequence;
    const kind = ['onset','skip','abandon','playback_finished'].includes(action.kind) ? action.kind : 'unknown';
    const common = {request_number: requestNumber, kind,
      started_chunk_count: action.kind === 'onset' ? action.receipt.started_chunk_ids.length : 0};
    void recordReplyDiagnostic('phone_reply_action', {...common, stage:'requested'});
    let failureKind = 'request', httpStatus: number | undefined;
    const finishDiagnostic = (details: Record<string, string | number | boolean>) => {
      // Wait for the diagnostic write, never for it on the audio/control path.
      void recordReplyDiagnostic('phone_reply_action', {...common, ...details,
        elapsed_ms:Math.max(0,Date.now()-started)}).then(() => uploadPhoneDebug(this,'phone_reply_action')).catch(() => undefined);
    };
    try {
      let result: PhoneReplyResult | undefined;
      try {
        const payload = await this.request<{ result: PhoneReplyResult }>('POST', '/api/phone-reply/action', { auth, action }, { timeoutMs: 140_000, privateReply: true });
        result = payload.result;
      } catch (failure) {
        if (failure instanceof RemoteRequestError) httpStatus = failure.status;
        result = (failure instanceof RemoteRequestError ? failure.payload as { result?: PhoneReplyResult } : null)?.result;
        if (!result || !['stale', 'busy', 'unavailable'].includes(result.status)) throw failure;
      }
      failureKind = 'invalid_ack';
      const requestId = action.kind === 'onset' ? action.receipt.phone_request_id : action.phone_request_id;
      if (result?.phone_request_id !== requestId || !['accepted', 'duplicate', 'stale', 'busy', 'unavailable'].includes(result.status)
        || (result.next_phone_request_id !== null && (typeof result.next_phone_request_id !== 'string'
          || !result.next_phone_request_id || [...result.next_phone_request_id].length > 128))) throw new Error('Phone reply acknowledgement unavailable.');
      finishDiagnostic({stage:'result',status:result.status,...(httpStatus === undefined ? {} : {http_status:httpStatus})});
      return result;
    } catch (failure) {
      finishDiagnostic({stage:'failed',failure_kind:failureKind,...(httpStatus === undefined ? {} : {http_status:httpStatus})});
      throw failure;
    }
  }

  async sendConversationAction(auth: PhoneReplyAuth, body: ConversationActionBody): Promise<ConversationActionResult> {
    let result: ConversationActionResult | undefined;
    try {
      result = (await this.request<{result: ConversationActionResult}>('POST', '/api/phone-reply/conversation-action',
        {auth, ...body}, {privateReply:true, timeoutMs:10_000})).result;
    } catch (failure) {
      result = (failure instanceof RemoteRequestError ? failure.payload as {result?:ConversationActionResult} : null)?.result;
      if (!result || !['stale','busy','unavailable'].includes(result.status)) throw failure;
    }
    if (!result || !['accepted','stale','busy','unavailable'].includes(result.status) || typeof result.reason !== 'string'
      || (result.phone_request_id !== null && (typeof result.phone_request_id !== 'string' || !/^[A-Za-z0-9_-]{1,96}$/.test(result.phone_request_id)))
      || (result.status === 'accepted' && (body.kind === 'retry' ? result.phone_request_id !== null : !result.phone_request_id))) {
      throw new Error('Phone reply acknowledgement unavailable.');
    }
    return result;
  }

  async getPhoneReplyStatus(auth: PhoneReplyAuth, requestId: string): Promise<PhoneReplyStatus> {
    const payload = await this.request<{ result: PhoneReplyStatus }>('POST', '/api/phone-reply/status', { auth, phone_request_id: requestId }, { privateReply: true });
    if (payload.result?.phone_request_id !== requestId || !['pending', 'generating', 'complete', 'cancelled', 'superseded'].includes(payload.result.phase)
      || (payload.result.last_sequence_index !== null && (!Number.isInteger(payload.result.last_sequence_index) || payload.result.last_sequence_index < 0 || payload.result.last_sequence_index >= 2048))
      || (payload.result.playback_stop_requested !== undefined && typeof payload.result.playback_stop_requested !== 'boolean')) {
      throw new Error('Phone reply status unavailable.');
    }
    return payload.result;
  }

  async getPhoneReplyContinuation(auth: PhoneReplyAuth, requestId: string, cursor: number, completedSequence: number): Promise<import('./types').PhoneReplyContinuationStatus> {
    const invalid = () => new Error('Phone reply continuation unavailable.');
    if (auth.reply_continuation_version !== 1 || !Number.isInteger(cursor) || cursor < 0 || cursor > 2048
      || !Number.isInteger(completedSequence) || completedSequence < -1 || completedSequence >= 2048) throw invalid();
    const {result} = await this.request<{result: import('./types').PhoneReplyContinuationStatus}>('POST', '/api/phone-reply/status',
      {auth, phone_request_id: requestId, continuation: {version: 1, cursor, completed_sequence_index: completedSequence}}, {privateReply: true});
    const page = result?.continuation;
    if (result?.phone_request_id !== requestId || !['pending','generating','complete','cancelled','superseded'].includes(result.phase)
      || (result.last_sequence_index !== null && (!Number.isInteger(result.last_sequence_index) || result.last_sequence_index < 0 || result.last_sequence_index >= 2048))
      || (result.playback_stop_requested !== undefined && typeof result.playback_stop_requested !== 'boolean')
      || page?.version !== 1 || typeof page.available !== 'boolean' || !Number.isFinite(page.remaining_seconds)
      || page.remaining_seconds < 0 || page.remaining_seconds > 900 || !Array.isArray(page.items) || page.items.length > 64
      || (page.next_cursor !== null && (page.items.length !== 64 || page.next_cursor !== cursor + 64 || page.next_cursor >= 2048))
      || (!page.available && (!['expired','capacity','media_missing'].includes(page.reason ?? '') || page.items.length !== 0 || page.next_cursor !== null))) throw invalid();
    const ids = new Set<string>();
    for (const [index, item] of page.items.entries()) {
      if (item.phone_request_id !== requestId || item.sequence_index !== cursor + index || item.sequence_index >= 2048
        || typeof item.id !== 'string' || !/^[A-Za-z0-9_.-]{1,128}$/.test(item.id) || ids.has(item.id)
        || item.url_path !== `/api/audio/file/${item.id}` || Object.keys(item).some(key => key.startsWith('_'))) throw invalid();
      ids.add(item.id);
    }
    return result;
  }

  async reportPhonePresentation(auth: PhoneReplyAuth, active: boolean, sequence: number, position?: import('../utils/phonePresentation').PhonePresentationPosition, handoff?:Record<string,unknown>): Promise<unknown> {
    const answer=await this.request<{result:unknown}>('POST', '/api/phone-reply/presentation', {auth,active,sequence,...(position ? {position} : {}),...(handoff?{handoff}:{})},
      {privateReply:true,timeoutMs:4000});
    return answer.result;
  }

  async control(action: string, _options: SendTextOptions = {}) {
    return this.request('POST', '/api/control', { action });
  }

  async engineStart() {
    return this.request('POST', '/api/engine/start', {});
  }

  async engineStop() {
    return this.request('POST', '/api/engine/stop', {});
  }

  async visual(prompt: string, options: VisualRequestOptions = {}) {
    return this.request('POST', '/api/visual', {
      prompt,
      action: 'generate',
      turn_id: options.turnId || '',
      normal_chat_transaction_id: options.normalChatTransactionId || '',
      refine_prompt: options.refinePrompt === true,
    });
  }

  async visualAction(action: VisualAction) {
    return this.request('POST', '/api/visual', { action });
  }

  async mprcState() {
    return this.request('GET', '/api/mprc');
  }

  async mprcSend(text: string, options: MprcSendOptions = {}) {
    return this.request('POST', '/api/mprc/send', {
      text,
      intent: String(options.intent || 'Auto'),
      speaker_id: String(options.speakerId || ''),
    });
  }

  async mprcChoice(choice: string) {
    return this.request('POST', '/api/mprc/choice', { choice });
  }

  async mprcAction(action: MprcAction) {
    return this.request('POST', `/api/mprc/${action}`, {});
  }

  async mprcCast(action: MprcCastAction, deviceName = '') {
    return this.request('POST', '/api/mprc/cast', {
      action,
      device_name: String(deviceName || ''),
    });
  }

  async clearAudio() {
    return this.request('POST', '/api/audio/clear', {});
  }

  async audioSpectrum(path: string): Promise<AudioSpectrumTimelinePayload> {
    return this.request<AudioSpectrumTimelinePayload>('GET', path);
  }

  async stt(audioBase64: string, format = 'm4a', options: SttOptions = {}) {
    if (options.audioMode === 'phone_native') throw new Error('Phone Native uses local recognition; microphone upload is disabled.');
    return this.request('POST', '/api/stt', {
      audio_base64: audioBase64,
      format,
      send_to_chat: options.sendToChat !== false,
      play_on_backend: PHONE_REPLY_PLAY_ON_BACKEND,
      capture_phone_audio: PHONE_REPLY_CAPTURE_AUDIO,
      visual_after_send: Boolean(options.visualAfterSend),
      ...(options.phoneReplyAuth ? { phone_reply_auth: options.phoneReplyAuth,
        ...(options.phoneInterruption ? { phone_interruption: options.phoneInterruption } : { phone_submission_id: options.phoneSubmissionId }) } : {}),
    }, { timeoutMs: options.phoneReplyAuth ? 140_000 : STT_REQUEST_TIMEOUT_MS, privateReply: Boolean(options.phoneReplyAuth) });
  }

  async sendImage(imageBase64: string, format: string, prompt: string, options: SendTextOptions = {}) {
    return this.request<PhoneSendEnvelope>('POST', '/api/image', {
      image_base64: imageBase64,
      visual_after_send: Boolean(options.visualAfterSend),
      audio_mode: options.audioMode ?? 'backend_hq',
      format,
      prompt,
      play_on_backend: PHONE_REPLY_PLAY_ON_BACKEND,
      capture_phone_audio: options.audioMode === 'phone_native' ? false : PHONE_REPLY_CAPTURE_AUDIO,
      debug_trace_id: String(options.debugTraceId || ''),
      source: options.imageSource || 'phone_camera',
      ...(options.phoneReplyAuth ? { phone_reply_auth: options.phoneReplyAuth } : {}),
    }, { timeoutMs: IMAGE_REQUEST_TIMEOUT_MS, privateReply: Boolean(options.phoneReplyAuth) });
  }

  async uploadDebug(reason = 'manual'): Promise<number> {
    return uploadPhoneDebug(this, reason, true);
  }

  async diagnosticPolicy():Promise<{policy:unknown}>{
    return this.request('GET','/api/diagnostics/policy');
  }

  async uploadDebugPayload(payload: JsonRecord): Promise<{ result?: { accepted?: boolean; events_written?: number; desktop_log_path?: string } }> {
    return this.request('POST', '/api/debug', payload);
  }

  private async request<T>(method: 'GET' | 'POST', path: string, body?: JsonRecord, options: RequestOptions = {}): Promise<T> {
    if(method==='POST'&&(path==='/api/send'||path==='/api/image'
      ||path==='/api/stt'&&body?.send_to_chat!==false
      ||path==='/api/phone-reply/conversation-action'&&(body?.kind==='retry'||body?.kind==='regenerate')))
      await awaitReplyReadiness(this);
    const url = this.apiUrl(path);
    const timeoutMs = normalizeTimeoutMs(options.timeoutMs);
    const controller = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
    if(options.signal?.aborted) throw new Error('Request cancelled.');
    const abortExternal=()=>controller?.abort();
    options.signal?.addEventListener('abort',abortExternal,{once:true});
    const init: RequestInit = {
      method,
      headers: {
        'Content-Type': 'application/json',
      },
    };
    if (options.authorize !== false) {
      if (this.auth.kind === 'lan') (init.headers as JsonRecord)['X-NC-Phone-Code'] = this.auth.pairingCode;
      else (init.headers as JsonRecord).Authorization = `Bearer ${this.auth.deviceToken}`;
    }
    if (controller) {
      init.signal = controller.signal;
    }
    if (body) {
      init.body = JSON.stringify(body);
    }
    const performFetch = async (): Promise<Response> => {
      const priority=!path.startsWith('/api/soundscape/');
      if(priority) this.priorityRequests++;
      try {
        if (!this.peer) return await fetch(url, init);
        const value = await this.peer.request(method, path, body, timeoutMs, controller?.signal);
        return new Response(JSON.stringify(value.body ?? {}), { status: value.status, headers: { "Content-Type": "application/json" } });
      } finally { if(priority) this.priorityRequests--; }
    };
    let timeout: ReturnType<typeof setTimeout> | null = null;
    let response: Response;
    let privateBody: string | undefined;
    let privateTimedOut = false;
    try {
      if (options.privateReply) {
        const deadline = new Promise<never>((_resolve, reject) => {
          timeout = setTimeout(() => { privateTimedOut = true; controller?.abort(); reject(timeoutError(timeoutMs)); }, timeoutMs);
        });
        const result = await Promise.race([
          (async () => { const reply = await performFetch(); return { reply, body: await reply.text() }; })(), deadline,
        ]);
        response = result.reply; privateBody = result.body;
      } else if (controller) {
        timeout = setTimeout(() => {
          controller.abort();
        }, timeoutMs);
        response = await performFetch();
      } else {
        response = await Promise.race([
          performFetch(),
          new Promise<Response>((_resolve, reject) => {
            timeout = setTimeout(() => {
              reject(timeoutError(timeoutMs));
            }, timeoutMs);
          }),
        ]);
      }
    } catch (exc) {
      if(options.signal?.aborted) throw new Error('Request cancelled.');
      void recordPhoneDebug('error', 'request_failed', {
        method,
        path: path.split('?')[0],
        error: options.privateReply ? 'Phone reply network request failed.' : exc instanceof Error ? exc.message : String(exc),
      });
      if (privateTimedOut || controller?.signal.aborted) {
        throw timeoutError(timeoutMs);
      }
      if (options.privateReply) throw new Error('Phone reply network request failed.');
      throw exc;
    } finally {
      options.signal?.removeEventListener('abort',abortExternal);
      if (timeout) {
        clearTimeout(timeout);
      }
    }
    const raw = privateBody ?? await response.text();
    let payload: unknown = {};
    if (raw) {
      try {
        payload = JSON.parse(raw);
      } catch {
        payload = { ok: false, error: raw };
      }
    }
    const result = payload && typeof payload === 'object' ? (payload as JsonRecord).result as JsonRecord | undefined : undefined;
    const emptySpeech = path === '/api/stt' && response.ok && isEmptySttResult(payload);
    const privateRejected = options.privateReply && payload && typeof payload === 'object'
      && ((payload as JsonRecord).ok === false || (result?.accepted === false && !emptySpeech) || (result?.send_result as JsonRecord | undefined)?.accepted === false);
    if (path === '/api/stt') {
      // Deliberately exclude transcript, IDs, capabilities and raw error text.
      void recordReplyDiagnostic('stt_outcome', { http_status: response.status,
        outcome: !response.ok || (payload as JsonRecord | null)?.ok === false ? 'request_rejected'
          : emptySpeech ? 'empty_transcript'
          : result?.accepted === false || (result?.send_result as JsonRecord | undefined)?.accepted === false ? 'submission_rejected'
          : phoneReplyRequestId(payload) ? 'reply_admitted' : 'other',
        transcript_present: typeof result?.text === 'string',
        transcript_empty: typeof result?.text === 'string' && result.text.trim() === '',
      });
    }
    if (!response.ok || privateRejected) {
      const rawError = payload && typeof payload === 'object' ? String((payload as JsonRecord).error || `HTTP ${response.status}`) : `HTTP ${response.status}`;
      // Expose only known validation messages, never arbitrary private response
      // bodies (which may contain prompts, credentials, or server details).
      const imageRejection = path === '/api/image' && result?.accepted === false
        && result.error === 'image payload must be PNG, JPEG, or WebP';
      const knownContinuousRejection = path === '/api/continuous/command' && response.status === 400
        && rawError === 'Wait for the desktop to finish stopping, then try Force continuation again.';
      const error = path === '/api/personas/prompts'
        ? (response.status === 400 ? 'These prompts changed or could not be saved. Reopen the editor and try again.'
          : response.status === 404 ? 'Update NC desktop to edit persona prompts.' : 'Persona prompt request failed. Check your connection.')
        : path.startsWith('/api/chat-characters') ? characterRequestError(response.status, rawError)
        : path.startsWith('/api/soundscape/') ? (response.status===409
          ? 'Sound settings changed or this sound is in use. Refresh before trying again.'
          : `Sound request failed (HTTP ${response.status}). Check the connection and your input.`)
        : path === '/api/story-library' ? (STORY_LIBRARY_ERRORS.has(rawError)
          || /^Story Open failed and automatic recovery failed\. Recovery snapshot: [a-f0-9]{32}$/.test(rawError) ? rawError
          : `Story Library request failed (HTTP ${response.status}). Refresh the library and try again.`)
        : imageRejection ? 'Photo format is not supported. Choose a JPEG, PNG, or WebP image.'
        : knownContinuousRejection ? rawError
        : options.privateReply && !/^phone_reply_[a-z_]+$/.test(rawError) ? `Phone reply request failed (HTTP ${response.status}).` : rawError;
      void recordPhoneDebug('error', 'request_rejected', { method, path: path.split('?')[0], status: response.status, error });
      throw new RemoteRequestError(error, response.status, payload);
    }
    if (!payload || typeof payload !== 'object') {
      void recordPhoneDebug('error', 'invalid_response', { method, path: path.split('?')[0], status: response.status });
      throw new Error('Remote backend returned an invalid response.');
    }
    // Reply actions request their upload after validation has recorded the outcome.
    if (options.authorize !== false && path !== '/api/debug' && path !== '/api/phone-reply/action') {
      void uploadPhoneDebug(this, 'connection_recovered').catch(() => undefined);
    }
    return payload as T;
  }
}
