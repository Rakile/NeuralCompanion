import { AVRemoteOutput, AVCompatibilityError, admissionReasons } from '../relay/av';
import type { NativeAV, AVObservation } from '../relay/av';
import type { PeerTransport } from '../relay/peer';
import { AppState } from 'react-native';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

type DiagnosticPC = { connectionState?: string; iceConnectionState?: string; signalingState?: string;
  getStats?(): Promise<Map<string, any>> };
/** Read-only snapshots at chunk start/failure, not a keepalive or recovery timer.
 * Log before queue teardown and never include SDP, candidates, IDs or content.
 */
export function createAVDiagnostics(pc: DiagnosticPC) {
  let closed = false, sequence = 0;
  const pending = new Set<() => void>();
  const write = (event: string, details: unknown) => {
    try { void recordPhoneDebug('info', event, details).catch(() => undefined); } catch { /* playback must continue */ }
  };
  const record: AVObservation = (phase, status) => {
    if (closed) return;
    const states = ['active', 'background', 'inactive', 'unknown', 'extension', 'new', 'connecting',
      'connected', 'disconnected', 'failed', 'closed', 'checking', 'completed', 'stable', 'have-local-offer', 'have-remote-offer'];
    const safeState = (value: unknown) => typeof value === 'string' && states.includes(value) ? value : 'unknown';
    const native: Record<string, boolean | number | string> = {};
    if (status) {
      for (const key of ['started', 'completed', 'failed', 'stopped'] as const)
        if (typeof status[key] === 'boolean') native[key] = status[key];
      if (Number.isFinite(status.positionSeconds) && status.positionSeconds >= 0) native.positionSeconds = status.positionSeconds;
      const reasons = ['concealment_limit', 'stream_discontinuity', 'media_stall', 'invalid_frame_size',
        'queue_overflow', 'device_invalidated', 'device_stopped', 'device_prepare_failed', 'invalid_pcm_format', 'unknown'];
      if (status.failureReason && reasons.includes(status.failureReason)) native.failureReason = status.failureReason;
      if (status.admissionReason && admissionReasons.has(status.admissionReason)) native.admissionReason = status.admissionReason;
      for (const key of ['chunkKey', 'offsetSamples'] as const)
        if (Number.isSafeInteger(status[key]) && Number(status[key]) >= 0) native[key] = Number(status[key]);
      if(status.handoffState && ['preparing','retained','speech','stream','returning','returned','ended','degraded'].includes(status.handoffState))
        native.handoffState=status.handoffState;
      if(status.handoffFailure && ['alignment_missed','stream_alignment_missed','return_unavailable','segment_wait_timeout',
        'presentation_timeout','decode_IllegalArgumentException','decode_IllegalStateException'].includes(status.handoffFailure))
        native.handoffFailure=status.handoffFailure;
      if(Number.isInteger(status.sourceFrame) && Number(status.sourceFrame)>=0 && Number(status.sourceFrame)<1440)
        native.sourceFrame=Number(status.sourceFrame);
      if (typeof status.failureAtMs === 'number' && Number.isFinite(status.failureAtMs) && status.failureAtMs > 0)
        native.failureAtMs = status.failureAtMs;
    }
    const context = { observation: ++sequence, phase, observed_at_ms: Date.now(),
      app_state: safeState(AppState?.currentState), connection_state: safeState(pc.connectionState),
      ice_state: safeState(pc.iceConnectionState), signaling_state: safeState(pc.signalingState), native };
    write('av_playback_observation', context);
    if (pending.size >= 2) {
      write('av_playback_network_sample', { ...context, stats_available: false, stats_outcome: 'collector_busy' });
      return;
    }
    let done = false;
    const finish = (stats?: Map<string, any>, outcome = stats instanceof Map ? 'collected' : 'unavailable') => {
      if (done) return; done = true; clearTimeout(timer); pending.delete(cancel);
      if (closed && outcome !== 'peer_closed') return;
      const audio: Record<string, number>[] = [], video: Record<string, number>[] = [];
      if (stats instanceof Map) for (const value of stats.values()) {
        if (!value || value.type !== 'inbound-rtp') continue;
        const kind = value.kind ?? value.mediaType;
        if (kind !== 'audio' && kind !== 'video') continue;
        const rows = kind === 'audio' ? audio : video;
        if (rows.length >= 4) continue;
        const row: Record<string, number> = {};
        const fields = kind === 'audio' ? [
          'concealedSamples', 'silentConcealedSamples', 'concealmentEvents', 'totalSamplesReceived',
          'insertedSamplesForDeceleration', 'removedSamplesForAcceleration'] : [
          'framesReceived', 'framesDecoded', 'framesDropped', 'framesPerSecond', 'keyFramesDecoded',
          'freezeCount', 'totalFreezesDuration', 'totalDecodeTime', 'totalProcessingDelay',
          'frameWidth', 'frameHeight', 'nackCount', 'pliCount', 'firCount'];
        for (const key of ['timestamp', 'packetsReceived', 'packetsLost', 'bytesReceived', 'jitter',
          'jitterBufferDelay', 'jitterBufferEmittedCount', ...fields])
          if (typeof value[key] === 'number' && Number.isFinite(value[key])) row[key] = value[key];
        rows.push(row);
      }
      write('av_playback_network_sample', { ...context, sampled_at_ms: Date.now(), stats_available: stats instanceof Map, stats_outcome: outcome, audio, video });
    };
    const cancel = () => finish(undefined, 'peer_closed');
    const timer = setTimeout(() => finish(undefined, 'timeout'), 2000);
    pending.add(cancel);
    try { void Promise.resolve(pc.getStats?.()).then(finish, () => finish()).catch(() => finish()); }
    catch { finish(); }
  };
  return { record, close() { closed = true; for (const cancel of [...pending]) cancel(); } };
}

type TrackEvent = { track: { id: string; kind: string; remote?: boolean } };
type PC = DiagnosticPC & { _pcId: number; addTransceiver(kind: 'audio' | 'video', options: { direction: 'recvonly' }): unknown };
type Events = {
  addEventListener(name: 'track', listener: (event: TrackEvent) => void): void;
  removeEventListener(name: 'track', listener: (event: TrackEvent) => void): void };
export type AVReceiver = { connect(peer: PeerTransport): Promise<AVRemoteOutput | null>; close(): void };

/** Media is standard, but a codec in SDP is not a protected native output path.
 * Never substitute the file player when the required native guards are missing.
 */
export function createAVReceiver(pc: PC): AVReceiver | null {
  if (process.env.EXPO_PUBLIC_NC_AV_TRACKS === '0') throw new AVCompatibilityError('NC streamed media is explicitly disabled. Remove the diagnostic AV override.');
  // RN 124 inherits these at runtime but omits them from its emitted .d.ts.
  const events = pc as PC & Events;
  if (typeof events.addEventListener !== 'function' || typeof events.removeEventListener !== 'function')
    throw new AVCompatibilityError('Install an updated native NC Remote development build with protected media playback.');
  let native: NativeAV, factory: string;
  try {
    const { NativeModules } = require('react-native') as typeof import('react-native');
    const capability = NativeModules.WebRTCModule?.ncAVFactory;
    const module = (require('expo') as typeof import('expo')).requireOptionalNativeModule<NativeAV & {
      ncAVVersion(): number; ncPlaybackGuardVersion(): number; ncPhoneReplyReceiptVersion(): number;
      ncAVDiagnosticSource?(): string;
    }>('ExpoAudio');
    if (capability?.version !== 1 || capability.defaultOutputMuted !== true || typeof capability.factoryId !== 'string'
      || !capability.factoryId || !module || module.ncAVVersion?.() !== 1 || module.ncPlaybackGuardVersion?.() !== 1
      || module.ncPhoneReplyReceiptVersion?.() !== 1 || !['ncAVOpen', 'ncAVReady', 'ncAVPrepare', 'ncAVPlay', 'ncAVStatus',
        'ncAVSamples', 'ncAVVolume', 'ncAVStop', 'ncAVRetire', 'ncAVClose', 'ncAVVisual', 'ncAVVisible'].every(name => typeof (module as any)[name] === 'function'))
      throw new AVCompatibilityError('Install an updated native NC Remote development build with protected media playback.');
    native = module; factory = capability.factoryId;
    // Optional on older builds. Diagnostics must not gate compatibility.
    try {
      const source = module.ncAVDiagnosticSource?.();
      void recordPhoneDebug('info', 'av_build_identity', { js_revision: 'unified-media-20260929-v1',
        native_source: typeof source === 'string' && /^[a-f0-9]{64}$/.test(source) ? source : 'unavailable',
        admission_diagnostics: typeof module.ncAVDiagnosticSource === 'function' }).catch(() => undefined);
    } catch { /* An optional diagnostic cannot change native availability. */ }
  } catch (error) {
    if (error instanceof AVCompatibilityError) throw error;
    throw new AVCompatibilityError('Install an updated native NC Remote development build with protected media playback.');
  }
  let closed = false, output: AVRemoteOutput | null = null, audio = '', video = '';
  const diagnostics = createAVDiagnostics(pc);
  let waiting: { resolve(): void; reject(error: Error): void } | null = null;
  const track = ({ track }: TrackEvent) => {
    if (closed || !track || track.remote !== true || !['audio', 'video'].includes(track.kind)) return;
    const previous = track.kind === 'audio' ? audio : video;
    if (previous && previous !== track.id) { close(); return; }
    if (track.kind === 'audio') audio = track.id; else video = track.id;
    if (audio && video) waiting?.resolve();
  };
  const close = () => {
    if (closed) return;
    closed = true; diagnostics.close(); output?.close(); output = null;
    waiting?.reject(new Error('NC media peer ended.')); waiting = null;
    events.removeEventListener('track', track);
  };
  events.addEventListener('track', track);
  pc.addTransceiver('audio', { direction: 'recvonly' });
  pc.addTransceiver('video', { direction: 'recvonly' });
  return { close, async connect(peer) {
    try {
      // Load file IO only for a native build that advertises the COMPLETE
      // composition capability, not merely the standalone opening decoder.
      const openingMedia=native.ncAVHandoffVersion?.()===1 ? (()=>{
        const {peerMedia,isPeerMediaUrl}=require('../relay/media') as typeof import('../relay/media');
        const {downloadIdleFile}=require('../dev/museTalkIdleFile') as typeof import('../dev/museTalkIdleFile');
        return {resolve:(path:string)=>peerMedia(peer,path,{}),owns:(url:string)=>isPeerMediaUrl(peer,url),copy:downloadIdleFile};
      })():undefined;
      const candidate = await AVRemoteOutput.connect(peer, native, async () => {
        if (closed) throw new Error('NC media peer ended.');
        if (!audio || !video) {
          let timer: ReturnType<typeof setTimeout> | undefined;
          try {
            await new Promise<void>((resolve, reject) => {
              waiting = { resolve, reject };
              timer = setTimeout(() => reject(new Error('Remote AV tracks unavailable.')), 5000);
            });
          } finally { if (timer) clearTimeout(timer); waiting = null; }
        }
        if (closed) throw new Error('NC media peer ended.');
        return { factory, peer: pc._pcId, audio, video };
      }, diagnostics.record,openingMedia);
      if (closed) { candidate?.close(); throw new Error('NC media peer ended.'); }
      output = candidate; return output;
    } catch (error) { close(); throw error; }
  } };
}
