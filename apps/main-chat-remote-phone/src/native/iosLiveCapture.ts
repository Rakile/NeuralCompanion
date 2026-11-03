import { requireOptionalNativeModule } from 'expo';
import { Platform } from 'react-native';
import {connectionTrace} from '../utils/connectionTrace';
import type { PhoneReplyReceipt } from '../api/types';
import { continuousCaptureEnabled } from './iosContinuousCapturePolicy';

export type CapturePhase = 'off' | 'listening' | 'speech';
export type CaptureAttachment={ticket:string;sessionId:string;captureId:string};
export type CaptureAttachmentState={attached:boolean;inputReleased:boolean;pendingReplyCount:number};
export type NativeReplyContinuation = {
  recoveryEpoch: number;
  replies: { requestId: string; completedChunkIds: string[]; activeChunkId: string | null; positionSeconds: number | null }[];
};
export type CaptureLifetime = 'capturing' | 'reply-tail' | 'closed';
export type ReplyTailPermit = { requestIds: string[]; pendingUploadIds: string[] };
export type CaptureDuckingLevel = 'default' | 'min' | 'mid' | 'max';
export type CaptureError = 'permission_denied' | 'unsupported_format'
  | 'capture_overflow' | 'backlog_full' | 'route_changed'
  | 'interrupted' | 'start_failed' | 'release_failed' | 'file_failed' | 'background_session_limit' | 'conversation_stopped'
  | 'reply_tail_timeout' | 'reply_tail_unavailable';
export type CaptureCapabilities = {
  available: boolean;
  reason: string;
  voiceProcessingSupported: boolean;
  voiceProcessingActive?: boolean;
  lastRetirementCause?: string;
  inputRoute?: string;
  outputRoute?: string;
  duckingSupported?: boolean;
  backgroundLiveVersion?: 1;
  playbackGuardVersion?: 1;
  stopListeningVersion?: 1;
  foregroundReplyControlsVersion?: 1;
  connectionRecoveryVersion?: 1;
  replyContinuationVersion?: 1;
  independentCaptureVersion?: 1;
  backgroundRoute?: 'wired' | 'bluetooth' | 'ineligible';
};
export type CaptureEvent = {
  captureId?:string;
  sessionId: string;
  sequence: number;
  kind: 'state' | 'onset' | 'utterance' | 'error';
  phase: CapturePhase;
  utteranceId?: string;
  durationMs: number;
  meteringDb?: number;
  error?: CaptureError;
  backgroundAuthorized?: boolean;
  lifetime?: CaptureLifetime;
  phoneReplyReceipt?: PhoneReplyReceipt;
  phoneReplyUnavailable?: boolean;
};
export type OwnedClip = {
  sessionId: string;
  utteranceId: string;
  uri: string;
  byteLength: number;
  durationMs: number;
};
export type OutputState = { ticket: string | null; open: boolean; sessionId: string | null; lastRetirementCause?: string;
  foregroundArmFailure?: Record<string, string | boolean | number> | null };

export interface IosLiveCapture {
  attachCapture?(sessionId:string,ticket:string,foregroundOnly:boolean):Promise<CaptureAttachment>;
  captureAttachmentState?(sessionId:string,ticket:string,captureId:string):Promise<CaptureAttachmentState>;
  detachCapture?(sessionId:string,ticket:string,captureId:string):Promise<boolean>;
  outputState(): Promise<OutputState>;
  beginProtectedOutput(sessionId: string, expectedTicket: string | null): Promise<string>;
  beginForegroundProtectedOutput(sessionId: string, expectedTicket: string | null): Promise<string>;
  beginForegroundOutput(expectedTicket: string | null): Promise<string>;
  retireOutput(ticket: string): Promise<void>;
  setReplyPlaybackActive?(ticket: string, active: boolean): Promise<void>;
  capabilities(): Promise<CaptureCapabilities>;
  start(sessionId: string, duckingLevel?: CaptureDuckingLevel): Promise<void>;
  setSpeechSensitivity?(level: number): Promise<void>;
  stop(sessionId: string): Promise<void>;
  pauseConnection?(sessionId: string, ticket: string, recoveryEpoch: number): Promise<boolean>;
  resumeConnection?(sessionId: string, ticket: string, recoveryEpoch: number): Promise<boolean>;
  pauseReplyContinuation?(sessionId: string, ticket: string, recoveryEpoch: number): Promise<NativeReplyContinuation | null>;
  resumeReplyContinuation?(sessionId: string, ticket: string, recoveryEpoch: number, requestIds: string[]): Promise<boolean>;
  stopListening(sessionId: string, permit: ReplyTailPermit): Promise<void>;
  registerSubmittedUpload(sessionId: string, utteranceId: string, uploadId: string): Promise<boolean>;
  registerSubmittedTurn(sessionId: string, ticket: string, submissionId: string, kind: 'text' | 'image'): Promise<boolean>;
  admitForegroundReply?(ticket:string,requestId:string):boolean;
  admitReplyForUpload(sessionId: string, ticket: string, uploadId: string, requestId: string): Promise<boolean>;
  abandonSubmittedUpload(sessionId: string, ticket: string, uploadId: string): Promise<void>;
  finishReplyOutput(sessionId: string, ticket: string, completedRequestIds: string[]): Promise<void>;
  armBackground(sessionId: string, bluetoothConfirmed: boolean): Promise<boolean>;
  armForeground(sessionId: string): Promise<boolean>;
  disarmBackground(sessionId: string): Promise<void>;
  setPlaybackActive(sessionId: string, active: boolean): Promise<void>;
  acquireUtterance(sessionId: string, utteranceId: string): Promise<OwnedClip>;
  releaseUtterance(sessionId: string, utteranceId: string): Promise<void>;
  subscribe(listener: (event: CaptureEvent) => void): { remove(): void };
}

type OutputMethods = 'outputState' | 'beginProtectedOutput' | 'beginForegroundOutput' | 'retireOutput';
type TailMethods = 'stopListening' | 'registerSubmittedUpload' | 'registerSubmittedTurn'
  | 'admitReplyForUpload' | 'abandonSubmittedUpload' | 'finishReplyOutput';
type ForegroundMethods = 'beginForegroundProtectedOutput' | 'armForeground';
type NativeLiveCapture = Omit<IosLiveCapture, 'subscribe' | 'armBackground' | 'disarmBackground' | OutputMethods | TailMethods | ForegroundMethods>
  & Partial<Pick<IosLiveCapture, OutputMethods | TailMethods | ForegroundMethods>> & {
  armBackground?(sessionId: string, bluetoothConfirmed: boolean): Promise<boolean>;
  disarmBackground?(sessionId: string): Promise<void>;
  startWithDucking?(sessionId: string, duckingLevel: CaptureDuckingLevel): Promise<void>;
  acknowledgeState(sessionId: string, sequence: number): Promise<void>;
  addListener(event: 'captureEvent', listener: (event: CaptureEvent) => void): { remove(): void };
};

const native = (Platform.OS === 'ios' || (Platform.OS === 'android' && continuousCaptureEnabled))
  ? requireOptionalNativeModule<NativeLiveCapture>('NcLiveCapture')
  : null;

const buildRequiredMessage = Platform.OS === 'android'
  ? 'Android Live Mic requires the updated custom app build.'
  : 'iOS Live Mic requires an updated development build.';
const unavailable = () => Promise.reject(new Error(buildRequiredMessage));
const resolved = () => Promise.resolve();
let activeSession: string | null = null;
let activeLifetime: CaptureLifetime = 'closed';
let sessionGeneration = 0;
const attachments=new Map<string,CaptureAttachment>();

function nativeReplyReceiptsSupported(): boolean {
  // Inspect the existing receipt contract without loading a player or adding an
  // audio owner. Foreground capability cannot be inferred from capture alone.
  try {
    const receipt = requireOptionalNativeModule<{
      ncPlaybackGuardVersion?: () => number;
      ncPhoneReplyReceiptVersion?: () => number;
      ncFreezePhoneReplyReceipt?: unknown;
      ncSkipPhoneReplyAudio?: unknown;
      ncFinishPhoneReplyAudio?: unknown;
    }>('ExpoAudio');
    return receipt?.ncPlaybackGuardVersion?.() === 1 && receipt.ncPhoneReplyReceiptVersion?.() === 1
      && typeof receipt.ncFreezePhoneReplyReceipt === 'function' && typeof receipt.ncSkipPhoneReplyAudio === 'function'
      && typeof receipt.ncFinishPhoneReplyAudio === 'function';
  } catch { return false; }
}

async function tailAdmission(sessionId: string, capturingOnly = false): Promise<boolean> {
  if(Platform.OS==='android'&&attachments.has(sessionId)) {
    return !capturingOnly||(activeSession===sessionId&&activeLifetime==='capturing');
  }
  const generation = sessionGeneration;
  if (activeSession !== sessionId || (capturingOnly && activeLifetime !== 'capturing')) return false;
  const supported = (await adapter.capabilities()).stopListeningVersion === 1;
  return supported && generation === sessionGeneration && activeSession === sessionId
    && (!capturingOnly || activeLifetime === 'capturing');
}

const adapter: IosLiveCapture = native ? {
  attachCapture:async(sessionId,ticket,foregroundOnly)=>{
    if(Platform.OS!=='android'||(await adapter.capabilities()).independentCaptureVersion!==1)throw new Error(buildRequiredMessage);
    const output=await native.outputState!();
    if(!output.open||output.ticket!==ticket)throw new Error('Capture output changed.');
    for(const [id,a] of attachments)if(a.ticket!==ticket)attachments.delete(id);
    if(attachments.size>=256)throw new Error('Capture attachment capacity reached.');
    const a=await native.attachCapture!(sessionId,ticket,foregroundOnly);
    if(a.sessionId!==sessionId||a.ticket!==ticket||typeof a.captureId!=='string'||!a.captureId)throw new Error('Invalid capture attachment.');
    attachments.set(sessionId,a);return a;
  },
  captureAttachmentState:(sessionId,ticket,captureId)=>native.captureAttachmentState!(sessionId,ticket,captureId),
  detachCapture:async(sessionId,ticket,captureId)=>{
    const a=attachments.get(sessionId);
    if(!a||a.ticket!==ticket||a.captureId!==captureId)return false;
    const released=await native.detachCapture!(sessionId,ticket,captureId);
    if(released&&activeSession===sessionId){activeSession=null;activeLifetime='closed';sessionGeneration++;}
    return released;
  },
  outputState: async () => {
    if ((await adapter.capabilities()).playbackGuardVersion !== 1) throw new Error(buildRequiredMessage);
    return native.outputState!();
  },
  beginProtectedOutput: async (sessionId, expectedTicket) => {
    if ((await adapter.capabilities()).playbackGuardVersion !== 1) throw new Error(buildRequiredMessage);
    return native.beginProtectedOutput!(sessionId, expectedTicket);
  },
  beginForegroundProtectedOutput: async (sessionId, expectedTicket) => {
    if ((await adapter.capabilities()).foregroundReplyControlsVersion !== 1) throw new Error(buildRequiredMessage);
    return native.beginForegroundProtectedOutput!(sessionId, expectedTicket);
  },
  beginForegroundOutput: async (expectedTicket) => {
    if ((await adapter.capabilities()).playbackGuardVersion !== 1) throw new Error(buildRequiredMessage);
    return native.beginForegroundOutput!(expectedTicket);
  },
  retireOutput: async (ticket) => {
    if ((await adapter.capabilities()).playbackGuardVersion !== 1) throw new Error(buildRequiredMessage);
    await native.retireOutput!(ticket);
    for(const [id,a] of attachments)if(a.ticket===ticket)attachments.delete(id);
  },
  capabilities: async () => {
    const capabilities = await native.capabilities();
    // Older binaries omit this field and the additive start method.
    const guardSupported = capabilities.available === true && capabilities.playbackGuardVersion === 1
      && ['outputState', 'beginProtectedOutput', 'beginForegroundOutput', 'retireOutput']
        .every(method => typeof native[method as OutputMethods] === 'function');
    const backgroundSupported = guardSupported && capabilities.backgroundLiveVersion === 1
      && typeof native.armBackground === 'function' && typeof native.disarmBackground === 'function';
    const tailSupported = guardSupported && capabilities.stopListeningVersion === 1
      && ['stopListening', 'registerSubmittedUpload', 'registerSubmittedTurn', 'admitReplyForUpload', 'abandonSubmittedUpload', 'finishReplyOutput']
        .every(method => typeof native[method as TailMethods] === 'function');
    const foregroundSupported = tailSupported && capabilities.foregroundReplyControlsVersion === 1
      && typeof native.beginForegroundProtectedOutput === 'function' && typeof native.armForeground === 'function'
      && nativeReplyReceiptsSupported();
    return {
      ...capabilities,
      ...(Platform.OS==='android'?{independentCaptureVersion:capabilities.independentCaptureVersion===1&&
        typeof native.attachCapture==='function'&&typeof native.captureAttachmentState==='function'&&typeof native.detachCapture==='function'?1 as const:undefined}:{}),
      ...(capabilities.duckingSupported === undefined ? {} : {
        duckingSupported: capabilities.duckingSupported === true && typeof native.startWithDucking === 'function',
      }),
      backgroundLiveVersion: backgroundSupported ? 1 : undefined,
      playbackGuardVersion: guardSupported ? 1 : undefined,
      stopListeningVersion: tailSupported && (backgroundSupported || foregroundSupported) ? 1 : undefined,
      foregroundReplyControlsVersion: foregroundSupported ? 1 : undefined,
      connectionRecoveryVersion: foregroundSupported && capabilities.connectionRecoveryVersion === 1
        && typeof native.pauseConnection === 'function' && typeof native.resumeConnection === 'function' ? 1 : undefined,
      replyContinuationVersion: foregroundSupported && capabilities.replyContinuationVersion === 1
        && typeof native.pauseReplyContinuation === 'function' && typeof native.resumeReplyContinuation === 'function' ? 1 : undefined,
      backgroundRoute: backgroundSupported && ['wired', 'bluetooth'].includes(capabilities.backgroundRoute ?? '')
        ? capabilities.backgroundRoute : 'ineligible',
    };
  },
  start: async (sessionId, duckingLevel = 'default') => {
    if (!['default', 'min', 'mid', 'max'].includes(duckingLevel)) throw new Error('Invalid Live Mode volume reduction.');
    if (duckingLevel !== 'default' && !native.startWithDucking) throw new Error(buildRequiredMessage);
    // Native rejects a different session while retaining the running one.
    // Keep that owner visible to Stop and terminal events during the request.
    const startingFromIdle = activeSession === null;
    const generation = startingFromIdle ? ++sessionGeneration : sessionGeneration;
    if (startingFromIdle) { activeSession = sessionId; activeLifetime = 'capturing'; }
    try {
      if (duckingLevel === 'default') await native.start(sessionId);
      else await native.startWithDucking!(sessionId, duckingLevel);
      if (sessionGeneration === generation) activeSession = sessionId;
    } catch (error) {
      if (startingFromIdle && sessionGeneration === generation) { activeSession = null; activeLifetime = 'closed'; }
      throw error;
    }
  },
  setSpeechSensitivity: async (level) => {
    if (Platform.OS !== 'android') return;
    if (!native.setSpeechSensitivity) throw new Error(buildRequiredMessage);
    await native.setSpeechSensitivity(level);
  },
  stop: async (sessionId) => {
    const generation = sessionGeneration;
    await native.stop(sessionId);
    if (activeSession === sessionId && sessionGeneration === generation) {
      activeSession = null; sessionGeneration += 1;
      activeLifetime = 'closed';
    }
  },
  pauseConnection: async (sessionId, ticket, recoveryEpoch) => {
    if (activeSession !== sessionId || activeLifetime !== 'capturing' || !native.pauseConnection) return false;
    return native.pauseConnection(sessionId, ticket, recoveryEpoch);
  },
  pauseReplyContinuation: async (sessionId, ticket, recoveryEpoch) => {
    if (activeSession !== sessionId || activeLifetime !== 'capturing' || !native.pauseReplyContinuation) return null;
    return native.pauseReplyContinuation(sessionId, ticket, recoveryEpoch);
  },
  resumeReplyContinuation: async (sessionId, ticket, recoveryEpoch, requestIds) => {
    if (activeSession !== sessionId || activeLifetime !== 'capturing' || !native.resumeReplyContinuation) return false;
    return native.resumeReplyContinuation(sessionId, ticket, recoveryEpoch, requestIds);
  },
  resumeConnection: async (sessionId, ticket, recoveryEpoch) => {
    if (activeSession !== sessionId || activeLifetime !== 'capturing' || !native.resumeConnection) return false;
    return native.resumeConnection(sessionId, ticket, recoveryEpoch);
  },
  stopListening: async (sessionId, permit) => {
    const generation = sessionGeneration;
    if (activeSession !== sessionId && !attachments.has(sessionId)) throw new Error('The Live session is no longer current.');
    // Fence new submissions synchronously, before any asynchronous capability read.
    if(activeSession===sessionId)activeLifetime = 'reply-tail';
    if (!await tailAdmission(sessionId)) throw new Error(buildRequiredMessage);
    await native.stopListening!(sessionId, { requestIds: [...permit.requestIds], pendingUploadIds: [...permit.pendingUploadIds] });
    const attachment=attachments.get(sessionId);
    if(attachment){
      const state=await native.captureAttachmentState!(sessionId,attachment.ticket,attachment.captureId);
      if(!state.attached||!state.inputReleased)throw new Error('Native input release unconfirmed.');
      if(activeSession===sessionId&&generation===sessionGeneration){activeSession=null;activeLifetime='closed';sessionGeneration++;}
      return;
    }
    const state = await native.outputState!();
    if (activeSession === sessionId && generation === sessionGeneration && (!state.open || state.sessionId !== sessionId)) {
      activeSession = null; activeLifetime = 'closed'; sessionGeneration += 1;
    }
  },
  registerSubmittedUpload: async (sessionId, utteranceId, uploadId) => {
    const generation = sessionGeneration;
    if (!await tailAdmission(sessionId, true)) return false;
    const registered = await native.registerSubmittedUpload!(sessionId, utteranceId, uploadId);
    return registered === true && activeSession === sessionId && generation === sessionGeneration && activeLifetime === 'capturing';
  },
  registerSubmittedTurn: async (sessionId, ticket, submissionId, kind) => {
    const generation = sessionGeneration;
    if (!['text', 'image'].includes(kind) || !await tailAdmission(sessionId, true)) return false;
    const registered = await native.registerSubmittedTurn!(sessionId, ticket, submissionId, kind);
    return registered === true && activeSession === sessionId && generation === sessionGeneration && activeLifetime === 'capturing';
  },
  admitForegroundReply: (ticket,requestId) => Platform.OS==='android'&&native.admitForegroundReply?.(ticket,requestId)===true,
  admitReplyForUpload: async (sessionId, ticket, uploadId, requestId) => {
    const attachment=attachments.get(sessionId);
    if(attachment)return attachment.ticket===ticket&&await native.admitReplyForUpload!(sessionId,ticket,uploadId,requestId)===true;
    const generation = sessionGeneration;
    if (!await tailAdmission(sessionId)) return false;
    const admitted = await native.admitReplyForUpload!(sessionId, ticket, uploadId, requestId);
    return admitted === true && activeSession === sessionId && generation === sessionGeneration;
  },
  abandonSubmittedUpload: async (sessionId, ticket, uploadId) => {
    // Exact native identity validates cleanup even after the JS session closed.
    if (typeof native.abandonSubmittedUpload === 'function') await native.abandonSubmittedUpload(sessionId, ticket, uploadId);
  },
  finishReplyOutput: async (sessionId, ticket, completedRequestIds) => {
    const attachment=attachments.get(sessionId);
    if(attachment){
      if(attachment.ticket!==ticket)throw new Error('Capture reply scope changed.');
      await native.finishReplyOutput!(sessionId,ticket,[...completedRequestIds]);
      attachments.delete(sessionId);return;
    }
    const generation = sessionGeneration;
    if (!await tailAdmission(sessionId)) throw new Error('The Live session is no longer current.');
    await native.finishReplyOutput!(sessionId, ticket, [...completedRequestIds]);
    if (activeSession === sessionId && generation === sessionGeneration) {
      activeSession = null; activeLifetime = 'closed'; sessionGeneration += 1;
    }
  },
  armBackground: async (sessionId, bluetoothConfirmed) => {
    const generation = sessionGeneration;
    if (activeSession !== sessionId || activeLifetime !== 'capturing') return false;
    try {
      const capabilities = await adapter.capabilities();
      if (capabilities.backgroundLiveVersion !== 1 || activeSession !== sessionId
          || sessionGeneration !== generation || activeLifetime !== 'capturing') return false;
      const armed = await native.armBackground!(sessionId, bluetoothConfirmed === true);
      return armed === true && activeSession === sessionId && sessionGeneration === generation && activeLifetime === 'capturing';
    } catch { return false; }
  },
  disarmBackground: async (sessionId) => { await native.disarmBackground?.(sessionId); },
  armForeground: async (sessionId) => {
    const generation = sessionGeneration;
    if (activeSession !== sessionId || activeLifetime !== 'capturing') return false;
    try {
      if ((await adapter.capabilities()).foregroundReplyControlsVersion !== 1 || activeSession !== sessionId
          || sessionGeneration !== generation || activeLifetime !== 'capturing') return false;
      const armed = await native.armForeground!(sessionId);
      return armed === true && activeSession === sessionId && sessionGeneration === generation && activeLifetime === 'capturing';
    } catch { return false; }
  },
  setReplyPlaybackActive: (ticket, active) => native.setReplyPlaybackActive?.(ticket, active) ?? Promise.resolve(),
  setPlaybackActive: (sessionId, active) => native.setPlaybackActive(sessionId, active),
  acquireUtterance: (sessionId, utteranceId) => native.acquireUtterance(sessionId, utteranceId),
  releaseUtterance: (sessionId, utteranceId) => native.releaseUtterance(sessionId, utteranceId),
  subscribe: (listener) => {
    let stateEventsEnabled = true;
    return native.addListener('captureEvent', (event) => {
      const attachment=attachments.get(event.sessionId);
      if(attachment&&event.captureId!==attachment.captureId)return;
      if (event.kind === 'error') connectionTrace.event('native_audio_interruption',
        {reason:event.error, phase:event.phase, state:event.lifetime, sequence:event.sequence}, true);
      if (event.sessionId === activeSession && event.lifetime === 'reply-tail') activeLifetime = 'reply-tail';
      if (event.sessionId === activeSession && (event.kind === 'error' || (event.phase === 'off' && event.lifetime !== 'reply-tail'))) {
        activeSession = null;
        activeLifetime = 'closed';
        sessionGeneration += 1;
      }
      if (event.kind === 'state' && !stateEventsEnabled) return;
      try {
        listener(event.backgroundAuthorized === undefined ? event : {
          ...event,
          backgroundAuthorized: event.backgroundAuthorized === true && event.sessionId === activeSession,
        });
      } finally {
        if (event.kind === 'state') {
          void native.acknowledgeState(event.sessionId, event.sequence).catch(() => {
            stateEventsEnabled = false;
          });
        }
      }
    });
  },
} : {
  outputState: unavailable,
  beginProtectedOutput: unavailable,
  beginForegroundProtectedOutput: unavailable,
  beginForegroundOutput: unavailable,
  retireOutput: unavailable,
  capabilities: async () => ({
    available: false,
    reason: buildRequiredMessage,
    voiceProcessingSupported: false,
    backgroundRoute: 'ineligible',
  }),
  start: unavailable,
  stop: resolved,
  stopListening: unavailable,
  registerSubmittedUpload: async () => false,
  registerSubmittedTurn: async () => false,
  admitReplyForUpload: async () => false,
  abandonSubmittedUpload: resolved,
  finishReplyOutput: unavailable,
  armBackground: async () => false,
  armForeground: async () => false,
  disarmBackground: resolved,
  setPlaybackActive: resolved,
  acquireUtterance: unavailable,
  releaseUtterance: resolved,
  subscribe: () => ({ remove() {} }),
};

export function getIosLiveCapture(): IosLiveCapture {
  return adapter;
}
