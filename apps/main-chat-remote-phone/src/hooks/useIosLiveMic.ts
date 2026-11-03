import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, PermissionsAndroid, Platform } from 'react-native';
import { ensureRecordingPermission } from '../native/recordingPermission';
import * as FileSystem from 'expo-file-system/legacy';

import type { RemoteClient, SendTextOptions } from '../api/client';
import { phoneReplyErrorCode, phoneReplyRequestId, retryPhoneReply, isUncertainPhoneReplyError, RemoteRequestError } from '../api/client';
import type { PhoneReplyAuth, PhoneReplyReceipt } from '../api/types';
import { isRecord, isEmptySttResult, remoteActionError } from '../api/envelope';
import { getIosLiveCapture } from '../native/iosLiveCapture';
import type { CaptureAttachment, CaptureDuckingLevel, CaptureEvent, CapturePhase, ReplyTailPermit, NativeReplyContinuation } from '../native/iosLiveCapture';
import { acquireCapture, releaseCapture, prepareLiveBackgroundAudio, startLiveCapture, stopLiveListening, finishLiveReplyOutput } from '../native/phoneCaptureOwnership';
import type { Lease } from '../native/phoneCaptureOwnership';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { rememberCaptureControl } from '../diagnostics/captureControlTrail';

function captureTiming(stage: 'speech_start' | 'speech_end' | 'upload_start' | 'upload_end', epoch: number, durationMs: number): void {
  try {
    void recordPhoneDebug('info', 'phone.mic.timing', { stage, capture_epoch: epoch,
      duration_ms: Number.isFinite(durationMs) ? Math.max(0, Math.round(durationMs)) : null }).catch(() => undefined);
  } catch { /* Timing observations must never affect capture or submission. */ }
}
import type { RecorderOptions } from './useRecorder';
import { ContinuationRecovery } from '../utils/continuationRecovery';

// Only finite state labels, booleans and counts belong here, never IDs or errors' text.
function recordLiveStop(details: Record<string, string | boolean | number>): void {
  // Low-rate ownership/stop evidence must survive optional microphone logging OFF.
  try { void recordPhoneDebug('warning', 'ios_live_stop', details).catch(() => undefined); }
  catch { /* A diagnostic sink must not change microphone or reply ownership. */ }
}

export type BackgroundLiveOptions = {
  getPlaybackTicketForCapture?:()=>Promise<string>;
  onAudioRouteFailure?: (ticket:string) => Promise<boolean>;
  allowBackgroundLive?: boolean;
  confirmBluetoothHeadphones?: () => Promise<boolean>;
  transportFailureRevision?: number;
  connectionRecoveryKey?: string;
  connectionRecoveryReady?: boolean;
  // Exact surviving ordered media peer, not command reachability or a grant.
  orderedPlaybackPeer?:object|null;
  orderedContinuationKey?:string;
  onConnectionPaused?: (sessionId: string, ticket: string) => void;
  onConnectionRestored?: (sessionId: string, ticket: string, recoveryEpoch?:number) => void;
  onReplyContinuationPaused?: (checkpoint: NativeReplyContinuation, pendingAdmissions?: ReadonlyMap<string, { auth: PhoneReplyAuth; uploadId: string }>) => void;
  onReplyContinuationValidate?: (checkpoint: NativeReplyContinuation) => Promise<string[]>;
  onReplyContinuationRestored?: (checkpoint: NativeReplyContinuation) => Promise<void>;
  onConnectionReplyRetired?: (sessionId: string, ticket: string, requestId: string, auth: PhoneReplyAuth) => void;
  onBeforeLiveStart?: (kind?:'manual'|'live') => Promise<void>;
  onBackgroundUpload?: (sessionId: string, uploadId: string) => void;
  getPhoneReplyReceiptAuth?: (sessionId: string, ticket: string, receipt: PhoneReplyReceipt) => PhoneReplyAuth | undefined;
  onBackgroundUploadSettled?: (sessionId: string, uploadId: string, requestId: string | null, auth?: PhoneReplyAuth) => void;
  onBackgroundSessionStart?: (sessionId: string) => void;
  onBackgroundSessionStop?: (sessionId: string) => void;
  onBackgroundOutputTicket?: (sessionId: string, ticket: string) => void;
  getReplyTailPermit?: (sessionId: string) => ReplyTailPermit;
  onBackgroundListeningStopped?: (sessionId: string) => void;
  onBeforeReplyOutputFinish?: (sessionId: string, ticket: string) => Promise<void>;
  onBackgroundOutputFinished?: (sessionId: string) => void;
  onBackgroundUploadAbandoned?: (sessionId: string, uploadId: string) => void;
};
export type IosLiveMicOptions = RecorderOptions & BackgroundLiveOptions & { identityKey: string; enabled: boolean; liveDuckingLevel?: CaptureDuckingLevel; liveMicSensitivity?: number };
type Session = {
  independentCapture?:boolean; attachment?:CaptureAttachment;
  orderedPlaybackPeer?:object|null;
  orderedContinuationKey?:string;
  id: string; epoch: number; identity: string; client: RemoteClient;
  cancelled: boolean; sequence: number; onsets: string[]; completions: string[]; ignoredOnsets: string[];
  registeringTurns: number;
  lease?: Lease; attemptedStart: boolean; subscription?: { remove(): void };
  setup?: Promise<void>; stopping?: Promise<void>;
  backgroundRequested: boolean; backgroundAuthorized: boolean; protected: boolean;
  protectedReady: boolean; foregroundProtected: boolean;
  transportRevision: number; callbacks: BackgroundLiveOptions & RecorderOptions;
  outputTicket?: string; retirement?: Promise<void>;
  cancelledSignal: Promise<void>; cancelSignal: () => void;
  listeningStopped: boolean; replyControls: boolean; auth?: PhoneReplyAuth;
  finishingReplyOutput?: boolean;
  stoppingListening?: boolean;
  inputRelease?:Promise<void>;
  submitted: Set<string>; receiptByUtterance: Map<string, PhoneReplyReceipt>;
  pendingAdmissions: Map<string, { auth: PhoneReplyAuth; uploadId: string; checkpointed: boolean }>;
  pendingTimers: Set<ReturnType<typeof setTimeout>>;
  issuedSubmissions: number;
  recoveryKey?: string;
  recoverySupported?: boolean;
  continuationSupported?: boolean;
  continuationCheckpoint?: NativeReplyContinuation;
  recoveryEpoch?: number;
  recovering?: boolean;
  recovery?: ContinuationRecovery<LegacyRecovery>;
  recoveryTransport?: { client: RemoteClient; revision: number; serial: number };
  // Native suppression evidence also gates late-ACK retirement; not supervision.
  recoveryPause?: Promise<boolean>;
};
type LegacyRecovery = { checkpoint?: NativeReplyContinuation; auth?: PhoneReplyAuth; ids: string[];
  target?: { client: RemoteClient; connected: boolean; voiceAvailable: boolean; options: IosLiveMicOptions } };
type Upload = { session: Session; id: string; client: RemoteClient; options: SendTextOptions; receipt?: PhoneReplyReceipt };
function recordRecovery(session: Session, stage: string, details: Record<string, string | number | boolean> = {}): void {
  try { void recordPhoneDebug('info', 'live_recovery', { capture_epoch: session.epoch,
    recovery_attempt: session.recoveryEpoch ?? 0, stage, monotonic_ms: performance.now(),
    ...details }).catch(() => undefined); } catch { /* Diagnostics cannot change ownership. */ }
}
const MAX_WAV_BYTES = 1_920_044;
let nextSession = 0;
const GATEWAY_REQUIRED = 'Background Live stopped because speech could not be correlated. Connect to an updated gateway before retrying.';
const SESSION_LIMIT = 'Restart the phone app to begin more background sessions. Ordinary foreground Live remains available.';

async function requestAndroidBackgroundPermissions(): Promise<{ bluetoothGranted: boolean; notificationGranted: boolean }> {
  if (Platform.OS !== 'android') return { bluetoothGranted: false, notificationGranted: true };
  const version = Number(Platform.Version);
  let bluetoothGranted = false;
  if (version >= 31) {
    bluetoothGranted = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT)
      === PermissionsAndroid.RESULTS.GRANTED;
  }
  const notifications = version >= 33
    ? await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS)
    : PermissionsAndroid.RESULTS.GRANTED;
  return { bluetoothGranted, notificationGranted: notifications === PermissionsAndroid.RESULTS.GRANTED };
}

function sttRequestId(payload: unknown): string | null {
  if (!isRecord(payload) || !isRecord(payload.result)) return null;
  const sent = payload.result.send_result;
  return isRecord(sent) && sent.accepted === true
    && typeof sent.phone_request_id === 'string' && sent.phone_request_id.length > 0
    && sent.phone_request_id.length <= 256 ? sent.phone_request_id : null;
}

export function useIosLiveMic(client: RemoteClient, connected: boolean, voiceAvailable = true, options: IosLiveMicOptions) {
  const capture = useRef(getIosLiveCapture()).current;
  const latest = useRef({ client, connected, voiceAvailable, options });
  latest.current = { client, connected, voiceAvailable, options };
  const mounted = useRef(true);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const current = useRef<Session | null>(null);
  const replyScopes=useRef(new Map<string,Session>());
  const releaseInput=useRef<(session:Session)=>Promise<void>>(async()=>{});
  const inputRouteRecovery=useRef<{session:Session;cancelled:boolean}|null>(null);
  const restartInputRoute=useRef<(session:Session)=>Promise<void>>(async()=>{});
  const stopListeningRef = useRef<(session: Session) => void>(() => {});
  const preparingPermissions = useRef(false);
  const permissionEpoch = useRef(0);
  const retiring = useRef<Session | null>(null);
  const epoch = useRef(0);
  const queue = useRef<Upload[]>([]);
  const active = useRef<Upload | null>(null);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [livePhase, setLivePhase] = useState<CapturePhase>('off');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [meteringDb, setMeteringDb] = useState<number | undefined>(undefined);
  const [meteringRevision, setMeteringRevision] = useState(0);
  const [starting, setStarting] = useState(false);
  const [foregroundOnly, setForegroundOnly] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);

  const ownsSession = useCallback((session: Session, recordInvalidation = false,receiptSettlement=false) => {
    const retained=session.independentCapture===true&&replyScopes.current.get(session.id)===session;
    const orderedScope=session.independentCapture===true&&!!session.orderedContinuationKey
      &&session.orderedContinuationKey===latest.current.options.orderedContinuationKey;
    const survivingOutput=receiptSettlement&&session.independentCapture===true&&(orderedScope||!!session.orderedPlaybackPeer
      &&session.orderedPlaybackPeer===latest.current.options.orderedPlaybackPeer);
    // One predicate set supplies both admission and the pre-cleanup diagnostic.
    // Values are booleans only; never publish identities, clients or native IDs.
    const checks = {
      mounted: mounted.current,
      foreground_eligible: foreground.current || session.backgroundAuthorized || (Platform.OS === 'android' && session.listeningStopped && session.protectedReady) || (session.independentCapture===true&&replyScopes.current.get(session.id)===session),
      current_session: current.current === session || replyScopes.current.get(session.id)===session,
      uncancelled: !session.cancelled,
      enabled: retained||latest.current.options.enabled,
      identity_matches: latest.current.options.identityKey === session.identity||orderedScope,
      client_matches: latest.current.client === session.client||orderedScope,
      connected: latest.current.connected||survivingOutput,
      voice_available: retained||latest.current.voiceAvailable,
      background_allowed: retained||!session.backgroundRequested || latest.current.options.allowBackgroundLive === true,
      transport_revision_matches: !session.backgroundRequested
        || (latest.current.options.transportFailureRevision ?? 0) === session.transportRevision||survivingOutput,
    };
    const allowed = Object.values(checks).every(Boolean);
    if (!allowed && recordInvalidation) {
      try {
        void recordPhoneDebug('warning', 'ios_live_capture_invalidated', checks).catch(() => undefined);
      } catch { /* A diagnostic failure must never prevent immediate teardown. */ }
    }
    return allowed;
  }, []);
  const canSubmit = useCallback((session: Session, recordInvalidation = false) =>
    !session.listeningStopped && !session.recovering
      &&(!session.orderedContinuationKey||latest.current.options.connectionRecoveryReady!==false)
      && ownsSession(session, recordInvalidation), [ownsSession]);

  const waitingForReply = useCallback((session: Session) => {
    if (!session.replyControls) return false;
    const permit = latest.current.options.getReplyTailPermit?.(session.id);
    return session.registeringTurns > 0 || session.submitted.size > 0
      || active.current?.session === session || queue.current.some(item => item.session === session)
      || Boolean(permit?.requestIds.length || permit?.pendingUploadIds.length);
  }, []);

  const showError = useCallback((session: Session, message: string) => {
    if (mounted.current && epoch.current === session.epoch) setError(message);
  }, []);

  const diagnose = useCallback(async (session: Session, transition: 'start' | 'stop' | 'error') => {
    try {
      const capabilities = await capture.capabilities();
      if (!mounted.current || epoch.current !== session.epoch) return;
      const retirementCauses = ['none', 'other', 'explicit', 'interruption', 'media_reset', 'foreground_left',
        'permission_revoked', 'route_setup_same', 'route_setup_different', 'route_other_same', 'route_other_different',
        'audio_focus_loss', 'route_change', 'audio_disabled'];
      await recordPhoneDebug(transition === 'error' ? 'error' : 'info', 'ios_live_capture', {
        transition, voice_processing_supported: capabilities.voiceProcessingSupported,
        voice_processing_active: capabilities.voiceProcessingActive,
        input_route: capabilities.inputRoute, output_route: capabilities.outputRoute,
        retirement_cause: capabilities.lastRetirementCause === undefined ? 'unavailable'
          : retirementCauses.includes(capabilities.lastRetirementCause) ? capabilities.lastRetirementCause : 'unknown',
      });
    } catch { /* Diagnostics never affect capture ownership. */ }
  }, [capture]);

  const discard = useCallback(async (item: Upload) => {
    try { await capture.releaseUtterance(item.session.id, item.id); }
    catch { showError(item.session, 'Could not release a Live Mic audio file. Restart the phone app before retrying.'); }
  }, [capture, showError]);

  const stopSession = useCallback((session: Session, message = '', initiator = 'safety_failure'): Promise<void> => {
    if (message) showError(session, message);
    if (session.stopping) return session.stopping;
    if(initiator==='safety_failure'&&session.attachment&&session.protectedReady&&ownsSession(session)&&
      (message==='Live Mic stopped because the audio input changed or capture failed. Restart Live Mic when ready.'||
       message==='Live Mic stopped: too many completed clips are waiting to send (backpressure).'))return releaseInput.current(session);
    // Fixed categories only: never emit exception text, utterance IDs or tickets.
    const reasons: Record<string, string> = {
      'Live Mic stopped because the connection or conversation changed.': 'connection_changed',
      'Reply admission ended. Stop Live and restart when ready.': 'reply_admission_ended',
      'Reply receipt unavailable. Stop Live and restart when ready.': 'receipt_unavailable',
      'Background Live authorization ended. Restart Live Mic when ready.': 'background_authorization_ended',
      'Live Mic stopped because the audio input changed or capture failed. Restart Live Mic when ready.': 'native_capture_failed',
      'Live Mic stopped: too many completed clips are waiting to send (backpressure).': 'upload_backpressure',
      'Reply admission capacity reached. Restart the phone app when ready.': 'admission_capacity',
      'Reply acknowledgement could not be recovered. Stop Live and restart when ready.': 'acknowledgement_expired',
      'Phone reply authorization expired. Start Live again when ready.': 'reply_authorization_expired',
      'Live Mic stopped when the app left the foreground.': 'foreground_left',
      'Live Mic could not update its playback state.': 'playback_state_failed',
    };
    recordLiveStop({stage:'session_stop',reason:message ? reasons[message] ?? 'other' : 'explicit_or_cleanup',
      initiator,
      capture_epoch: session.epoch, recovery_attempt: session.recoveryEpoch ?? 0, recovering: session.recovering === true,
      listening_stopped:session.listeningStopped === true,receipt_count:session.receiptByUtterance.size,
      submitted_count:session.submitted.size,pending_timer_count:session.pendingTimers.size});
    session.cancelled = true;
    session.recoveryEpoch = (session.recoveryEpoch ?? 0) + 1;
    void session.recovery?.cancel('session_stopped').catch(() => undefined);
    session.backgroundAuthorized = false;
    session.cancelSignal();
    session.receiptByUtterance.clear(); if(!session.independentCapture)session.submitted.clear(); session.pendingAdmissions.clear(); session.ignoredOnsets = [];
    for (const timer of session.pendingTimers) clearTimeout(timer);
    session.pendingTimers.clear();
    if (session.protected) session.callbacks.onBackgroundSessionStop?.(session.id);
    // Close native output immediately, even while confirmation or Start drains.
    if (session.outputTicket&&!session.independentCapture) session.retirement = capture.retireOutput(session.outputTicket);
    void session.retirement?.catch(() => undefined);
    retiring.current = session;
    session.subscription?.remove();
    if (current.current === session) {
      current.current = null;
      if (mounted.current) { setLiveEnabled(false); setLivePhase('off'); setStarting(false); setBusy(false); setReconnecting(false); }
    }
    const dropped = queue.current.filter((item) => item.session === session);
    queue.current = queue.current.filter((item) => item.session !== session);
    // Diagnostics only: keep cleanup ordering and failed-ownership fencing intact.
    let teardownOperation = 'setup';
    session.stopping = (async () => {
      // Setup owns acquisition/start until it settles. Never hold the serialized
      // ownership chain while awaiting setup or an upload worker.
      await session.setup;
      await session.inputRelease?.catch(()=>undefined);
      if (session.outputTicket && !session.retirement&&!session.independentCapture) session.retirement = capture.retireOutput(session.outputTicket);
      // Native Stop also drains a protected Begin which never reached Start.
      if (session.lease) {
        teardownOperation = 'release_capture';
        await releaseCapture(session.lease, async () => {
          teardownOperation = 'native_stop';
          if (session.attemptedStart || session.outputTicket) await capture.stop(session.id);
          if(session.independentCapture&&session.outputTicket)for(const upload of [...session.submitted]){
            await capture.abandonSubmittedUpload(session.id,session.outputTicket,upload);
            session.submitted.delete(upload);
          }
          if(session.attachment){
            const a=session.attachment;
            if(!await capture.detachCapture!(a.sessionId,a.ticket,a.captureId))throw new Error('Capture detach unconfirmed.');
          }
          teardownOperation = 'output_retirement';
          await session.retirement;
          teardownOperation = 'restore_audio';
        });
        session.lease = undefined;
      }
      teardownOperation = 'discard_uploads';
      await Promise.all(dropped.map(discard));
      if (retiring.current === session) retiring.current = null;
      replyScopes.current.delete(session.id);
      void diagnose(session, message ? 'error' : 'stop');
    })().catch((error: unknown) => {
      const knownErrors = ['permission_denied', 'unsupported_format', 'capture_overflow', 'backlog_full',
        'route_changed', 'interrupted', 'start_failed', 'release_failed', 'file_failed',
        'background_session_limit', 'conversation_stopped', 'reply_tail_timeout', 'reply_tail_unavailable'];
      // Never record native messages, paths, tickets or other arbitrary payloads.
      let nativeError = 'unknown';
      try {
        if (isRecord(error) && typeof error.code === 'string' && knownErrors.includes(error.code)) nativeError = error.code;
      } catch { /* Even a hostile error accessor must not change cleanup. */ }
      recordLiveStop({ stage: 'teardown_failed', operation: teardownOperation, native_error: nativeError });
      if (session.replyControls) session.stopping = undefined;
      showError(session, 'Could not stop the Live microphone. Restart the phone app before retrying.');
      void diagnose(session, 'error');
      throw new Error('The previous Live microphone could not be released.');
    });
    return session.stopping;
  }, [capture, diagnose, discard, showError, ownsSession]);

  const stopSafely = useCallback((session: Session, message: string) => {
    // Player and capture callbacks can race. The App coalesces recovery using
    // exact native ticket/cause evidence, before either callback tears it down.
    if(Platform.OS==='android'&&message&&session.protectedReady&&session.outputTicket&&latest.current.options.onAudioRouteFailure){
      void latest.current.options.onAudioRouteFailure(session.outputTicket).catch(()=>false).then(handled=>{
        if(!handled&&current.current===session&&!session.cancelled)void stopSession(session,message).catch(()=>undefined);
      });return;
    }
    void stopSession(session, message).catch(() => undefined);
  }, [stopSession]);

  const settleSubmission = useCallback(async (session: Session, uploadId: string, requestId: string | null, auth = session.auth) => {
    if (!session.replyControls) { session.callbacks.onBackgroundUploadSettled?.(session.id, uploadId, requestId); return; }
    if (!ownsSession(session,false,true) || session.recovering || !session.outputTicket) return;
    const recoveryEpoch = session.recoveryEpoch;
    const stillOwned = () => ownsSession(session,false,true) && !session.recovering && session.recoveryEpoch === recoveryEpoch;
    if (requestId) {
      if (auth) session.pendingAdmissions.set(requestId, { auth, uploadId, checkpointed: false });
      if (!await capture.admitReplyForUpload(session.id, session.outputTicket, uploadId, requestId)) {
        if (stillOwned()) stopSafely(session, 'Reply admission ended. Stop Live and restart when ready.');
        return;
      }
      if (!stillOwned()) return;
      session.callbacks.onBackgroundUploadSettled?.(session.id, uploadId, requestId, auth);
      session.pendingAdmissions.delete(requestId);
    } else {
      await capture.abandonSubmittedUpload(session.id, session.outputTicket, uploadId);
      if (stillOwned()) session.callbacks.onBackgroundUploadAbandoned?.(session.id, uploadId);
    }
    session.submitted.delete(uploadId);
  }, [capture, ownsSession, stopSafely]);

  const retireRecoveredReply = useCallback(async (session: Session, recoveryEpoch: number | undefined,
    result: unknown, auth: PhoneReplyAuth | undefined, submissionId: string) => {
    const requestId = phoneReplyRequestId(result);
    const sameScope = () => (current.current === session
      ||session.independentCapture===true&&replyScopes.current.get(session.id)===session)
      && !session.cancelled && Boolean(session.recoveryKey)
      && latest.current.options.connectionRecoveryKey === session.recoveryKey && session.recoveryEpoch !== recoveryEpoch;
    if (!requestId || auth?.shared_queue_version !== 1 || !session.outputTicket || !sameScope()) return;
    if (session.continuationSupported && auth.reply_continuation_version === 1) {
      // The request was sent before the outage, but its receipt arrived after
      // the native checkpoint. Reconcile that exact receipt, not a new turn.
      const deadline = Date.now() + 900_000;
      while (sameScope() && !session.listeningStopped && Date.now() < deadline) {
        // A subsequent native checkpoint can publish admission before the
        // bridge resolves its promise. That checkpoint already restores it.
        if (session.pendingAdmissions.get(requestId)?.checkpointed) {
          session.pendingAdmissions.delete(requestId); return;
        }
        if (session.recovering || !latest.current.connected || latest.current.options.connectionRecoveryReady === false) {
          await Promise.race([session.cancelledSignal, new Promise<void>(resolve => setTimeout(resolve, 100))]);
          continue;
        }
        const epoch = session.recoveryEpoch;
        const currentAdmission = () => sameScope() && !session.recovering
          && session.recoveryEpoch === epoch && latest.current.connected;
        const currentReceipt = () => currentAdmission() && !session.listeningStopped;
        let status;
        try { status = await session.client.getPhoneReplyContinuation(auth, requestId, 0, -1); }
        catch (failure) {
          if (!currentReceipt()) continue;
          if (!isUncertainPhoneReplyError(failure)) throw failure;
          await Promise.race([session.cancelledSignal, new Promise<void>(resolve => setTimeout(resolve, 1000))]);
          continue;
        }
        if (!currentReceipt()) continue;
        if (status.phase === 'cancelled' || status.phase === 'superseded' || status.playback_stop_requested
          || !status.continuation.available) throw new Error('The pending reply is no longer available.');
        const admissionId = `${submissionId}-recovery-${epoch}`;
        if (session.issuedSubmissions >= 256) throw new Error('Reply admission capacity reached.');
        const registered = await capture.registerSubmittedTurn(session.id, session.outputTicket, admissionId, 'text');
        if (!currentAdmission()) continue;
        if (!registered) throw new Error('Pending reply recovery admission unavailable.');
        session.issuedSubmissions++;
        session.callbacks.onBackgroundUpload?.(session.id, admissionId);
        session.pendingAdmissions.set(requestId, { auth, uploadId: admissionId, checkpointed: false });
        const admitted = await capture.admitReplyForUpload(session.id, session.outputTicket, admissionId, requestId);
        // Live off retains already submitted replies; Stop speech/cancel and
        // a changed connection still fence this native admission.
        if (!currentAdmission()) continue;
        if (!admitted) throw new Error('Pending reply recovery admission ended.');
        session.callbacks.onBackgroundUploadSettled?.(session.id, admissionId, requestId, auth);
        session.pendingAdmissions.delete(requestId);
        return;
      }
      if (sameScope() && !session.listeningStopped) throw new Error('Reply acknowledgement recovery expired.');
      return;
    }
    // Releasing the backend queue requires confirmed native suppression. A
    // second outage may replace the pause while this old receipt is waiting.
    while (sameScope()) {
      const pause = session.recoveryPause;
      if (!pause) return;
      const paused = await pause;
      if (pause !== session.recoveryPause) continue;
      if (paused && sameScope()) latest.current.options.onConnectionReplyRetired?.(session.id, session.outputTicket, requestId, auth);
      return;
    }
  }, [capture]);

  const pump = useCallback(async () => {
    if (active.current) return;
    while (queue.current.length && !active.current) {
      const item = queue.current.shift()!;
      const session = item.session;
      const recoveryEpoch = session.recoveryEpoch;
      // A resumed reply retains its original owner even when reconnect has
      // issued fresh authorization for new turns. Pin that receipt's owner
      // through upload retries and admission of the interruption's successor.
      const receiptAuth = latest.current.options.getPhoneReplyReceiptAuth;
      let submissionAuth = item.receipt && receiptAuth
        ? receiptAuth(session.id, session.outputTicket ?? '', item.receipt) : session.auth;
      const currentUpload = () => canSubmit(session) && session.recoveryEpoch === recoveryEpoch;
      const ownedUpload = () => ownsSession(session,false,true) && !session.recovering && session.recoveryEpoch === recoveryEpoch;
      const recoverableUpload = () => session.continuationSupported && submissionAuth?.reply_continuation_version === 1
        && current.current === session && !session.cancelled && !session.listeningStopped
        && Boolean(session.recoveryKey) && latest.current.options.connectionRecoveryKey === session.recoveryKey;
      active.current = item;
      if (canSubmit(session)) setBusy(true);
      let failure = '';
      let uploadPending = false;
      let dispatched = false;
      try {
        if (!currentUpload()) continue;
        if(session.independentCapture&&session.replyControls&&!item.receipt){
          // New turns share the current playback credential; old interruption
          // receipts and already-dispatched uploads keep their immutable auth.
          submissionAuth=await latest.current.options.getPhoneReplyAuth?.();
          if(!currentUpload())continue;
          if(!submissionAuth)throw Error('Phone reply ownership ended.');
          session.auth=submissionAuth;
        }
        if (session.replyControls && item.receipt && !submissionAuth) throw new Error('Phone reply ownership ended.');
        const clip = await capture.acquireUtterance(session.id, item.id);
        if (!currentUpload()) continue;
        if (clip.sessionId !== session.id || clip.utteranceId !== item.id
          || !Number.isInteger(clip.byteLength) || clip.byteLength < 44 || clip.byteLength > MAX_WAV_BYTES) {
          throw new Error('Invalid audio file');
        }
        const base64 = await FileSystem.readAsStringAsync(clip.uri, { encoding: FileSystem.EncodingType.Base64 });
        if (!currentUpload()) continue;
        if (!base64.length || base64.length > 4 * Math.ceil(clip.byteLength / 3)) throw new Error('Invalid audio length');
        if (session.protected) {
          if (session.replyControls) {
            if (session.issuedSubmissions >= 256) { failure = 'Reply admission capacity reached. Stop Live and restart the phone app when ready.'; continue; }
            const registered = await capture.registerSubmittedUpload(session.id, item.id, item.id);
            if (!currentUpload()) {
              await capture.abandonSubmittedUpload(session.id, session.outputTicket!, item.id); continue;
            }
            if (!registered) { showError(session, 'Reply submission capacity reached. Stop Live and restart when ready.'); continue; }
            session.issuedSubmissions++;
          }
          session.callbacks.onBackgroundUpload?.(session.id, item.id);
          uploadPending = true;
        }
        if (!currentUpload()) continue;
        if (session.replyControls) session.submitted.add(item.id);
        dispatched = true;
        const sttOptions = { ...item.options, sendToChat: true, ...(session.replyControls ? {
          phoneReplyAuth: submissionAuth, phoneInterruption: item.receipt,
          phoneSubmissionId: item.receipt ? undefined : item.id,
        } : {}) };
        const recoveryDeadline = Date.now() + 900_000;
        const operation = async () => {
          // Retry an uncertain ACK using the immutable submission/auth on the
          // recovered transport. Server deduplication returns the existing turn.
          while (recoverableUpload() && (session.recovering || !latest.current.connected
            || latest.current.options.connectionRecoveryReady === false)) {
            if (Date.now() >= recoveryDeadline) throw new Error('Reply acknowledgement recovery expired.');
            await Promise.race([session.cancelledSignal, new Promise<void>(resolve => setTimeout(resolve, 100))]);
          }
          if (session.replyControls && !ownedUpload() && !recoverableUpload()) throw new Error('Phone reply ownership ended.');
          return (recoverableUpload() ? session.client : item.client).stt(base64, 'wav', sttOptions);
        };
        const uploadStarted = Date.now();
        captureTiming('upload_start', session.epoch, clip.durationMs);
        const result = await (session.replyControls ? retryPhoneReply(operation, () => ownedUpload() || Boolean(recoverableUpload())) : operation())
          .finally(() => captureTiming('upload_end', session.epoch, Date.now() - uploadStarted));
        // Legacy protected uploads still reconcile their ACK after Stop. Only
        // recovery-capable reply admissions must be fenced by capture epoch.
        if (session.replyControls && !ownedUpload()) {
          await retireRecoveredReply(session, recoveryEpoch, result, submissionAuth, item.id); continue;
        }
        const requestId = session.replyControls ? phoneReplyRequestId(result) : sttRequestId(result);
        if (uploadPending) {
          uploadPending = false;
          await settleSubmission(session, item.id, requestId, submissionAuth);
          if (session.replyControls && !ownedUpload()) await retireRecoveredReply(session, recoveryEpoch, result, submissionAuth, item.id);
        }
        if (!canSubmit(session)) continue;
        if (session.protected && !session.replyControls && !requestId) { failure = GATEWAY_REQUIRED; continue; }
        if (session.replyControls && isRecord(result) && isRecord(result.result) && ['stale', 'busy', 'unavailable'].includes(String(result.result.status))) {
          failure = 'Phone reply could not be resolved. Stop Live and restart when ready.'; continue;
        }
        if (!isEmptySttResult(result) && remoteActionError(result, 'Voice reply was not accepted.')) throw new Error('Voice reply rejected');
      } catch (cause) {
        if (ownsSession(session) && phoneReplyErrorCode(cause) === 'phone_reply_authentication') void session.callbacks.getPhoneReplyAuth?.(true).catch(() => undefined);
        failure = 'Live Mic stopped because reading or sending audio failed. Queued audio was discarded.';
      } finally {
        if (!dispatched && item.receipt && session.receiptByUtterance.has(item.id)) {
          void Promise.resolve(latest.current.options.onPhoneReplyAbandon?.(item.receipt)).catch(() => undefined);
        }
        if (uploadPending && ownedUpload()) await settleSubmission(session, item.id, null);
        session.receiptByUtterance.delete(item.id);
        // Includes failed acquire: the module accepts release as an idempotent
        // discard of this owned ID. Stop never releases the active reader here.
        try { await capture.releaseUtterance(session.id, item.id); }
        catch {
          failure = 'Could not release a Live Mic audio file. Restart the phone app before retrying.';
          // Reader cleanup outlives Stop. Report its failure in this epoch even
          // when submission is fenced, but never into a newer capture session.
          showError(session, failure);
        }
        if (active.current === item) {
          active.current = null;
          // Live off can retain an upload after submission closes. Its busy
          // state ends with the reader, without changing a newer session.
          if (mounted.current && epoch.current === session.epoch) setBusy(false);
        }
        if (failure && (currentUpload() || recoverableUpload())) stopSafely(session, failure);
      }
    }
  }, [canSubmit, ownsSession, capture, showError, stopSafely, settleSubmission, retireRecoveredReply]);

  const receive = useCallback((session: Session, event: CaptureEvent) => {
    if(session.attachment&&event.captureId!==session.attachment.captureId)return;
    // Terminal native events revoke output even when JS has just lost background permission.
    if (current.current !== session || session.cancelled || event.sessionId !== session.id || !Number.isSafeInteger(event.sequence)
      || event.sequence <= session.sequence) return;
    session.sequence = event.sequence;
    if (event.kind === 'onset' || event.kind === 'utterance') {
      captureTiming(event.kind === 'onset' ? 'speech_start' : 'speech_end', session.epoch, event.durationMs);
    }
    if (event.kind === 'error' || event.phase === 'off') {
      const knownErrors = ['permission_denied', 'unsupported_format', 'capture_overflow', 'backlog_full',
        'route_changed', 'interrupted', 'start_failed', 'release_failed', 'file_failed',
        'background_session_limit', 'conversation_stopped', 'reply_tail_timeout', 'reply_tail_unavailable'];
      recordLiveStop({ stage: 'native_event', listening_stopped: session.listeningStopped === true,
        reply_controls: session.replyControls, native_kind: event.kind === 'error' ? 'error' : 'state',
        lifetime: event.lifetime === 'reply-tail' ? 'reply-tail' : event.lifetime === 'closed' ? 'closed' : 'other',
        native_error: event.error === undefined ? 'none' : knownErrors.includes(event.error) ? event.error : 'unknown' });
    }
    if (event.phase === 'off' && event.lifetime === 'reply-tail' && session.replyControls) {
      // Native Activity.onPause may drain the microphone before AppState arrives.
      // Adopt its tail through the same coordinator/callbacks as a user Live-off.
      if (Platform.OS === 'android' && !session.listeningStopped) stopListeningRef.current(session);
      else { session.listeningStopped = true; setLiveEnabled(false); setLivePhase('off'); }
      return;
    }
    // Native stop/finish publishes a normal closed event before resolving its promise.
    // That operation still owns exact ticket/closure verification and lease release.
    if ((session.finishingReplyOutput || session.stoppingListening) && event.kind === 'state' && event.phase === 'off'
      && event.lifetime === 'closed' && event.error === undefined) return;
    if (event.kind === 'error' || event.phase === 'off') {
      if(event.error==='route_changed'&&inputRouteRecovery.current?.session===session)return;
      if(Platform.OS==='android'&&event.error==='route_changed'&&session.independentCapture&&session.protectedReady
        &&!session.listeningStopped&&foreground.current&&!inputRouteRecovery.current){
        void restartInputRoute.current(session);return;
      }
      stopSafely(session, event.error === 'backlog_full'
        ? 'Live Mic stopped: too many completed clips are waiting to send (backpressure).'
        : 'Live Mic stopped because the audio input changed or capture failed. Restart Live Mic when ready.');
      return;
    }
    if (session.backgroundAuthorized && event.backgroundAuthorized === false) {
      stopSafely(session, 'Background Live authorization ended. Restart Live Mic when ready.');
      return;
    }
    if (!canSubmit(session)) {
      if (event.kind === 'utterance' && event.utteranceId && !session.completions.includes(event.utteranceId)) {
        session.completions.push(event.utteranceId); if (session.completions.length > 4) session.completions.shift();
        void discard({ session, id: event.utteranceId, client: session.client, options: {} });
      }
      return;
    }
    setLivePhase(event.phase);
    if (typeof event.meteringDb === 'number' && Number.isFinite(event.meteringDb)) {
      setMeteringDb(event.meteringDb); setMeteringRevision(event.sequence);
    }
    if (event.kind === 'onset' && event.utteranceId && !session.onsets.includes(event.utteranceId)) {
      if (session.protected && !session.protectedReady) return;
      session.onsets.push(event.utteranceId); if (session.onsets.length > 4) session.onsets.shift();
      if (session.replyControls) {
        if (event.phoneReplyUnavailable) { stopSafely(session, 'Reply receipt unavailable. Stop Live and restart when ready.'); return; }
        // Native receipts require an acknowledged playback start (including chunk
        // gaps). No receipt while a turn is owned means waiting, not a new turn.
        if (!event.phoneReplyReceipt && waitingForReply(session)) {
          session.ignoredOnsets.push(event.utteranceId);
          // Keep each rejection until its completion; a delayed native event
          // must never become new input merely because newer onsets arrived.
          try { void recordPhoneDebug('info', 'live_input_discarded', {reason:'reply_waiting',stage:'onset'}).catch(() => undefined); }
          catch { /* Diagnostics must not admit blocked input. */ }
          return;
        }
        if (event.phoneReplyReceipt) session.receiptByUtterance.set(event.utteranceId, event.phoneReplyReceipt);
        try { void Promise.resolve(latest.current.options.onPhoneReplyOnset?.(event.phoneReplyReceipt)).catch(() =>
          showError(session, 'Phone interruption acknowledgement is pending; the same receipt will be retried with speech.')); }
        catch { showError(session, 'Phone interruption could not be acknowledged.'); }
        return;
      }
      try {
        const result = latest.current.options.onLiveSpeechStart?.();
        if (result) void Promise.resolve(result).catch(() => {
          if (canSubmit(session)) showError(session, 'Could not interrupt the current NC response.');
        });
      } catch { showError(session, 'Could not interrupt the current NC response.'); }
    } else if (event.kind === 'utterance' && event.utteranceId && !session.completions.includes(event.utteranceId)) {
      session.completions.push(event.utteranceId); if (session.completions.length > 4) session.completions.shift();
      const item = { session, id: event.utteranceId, client: latest.current.client, options: { ...latest.current.options.sendOptions },
        receipt: session.receiptByUtterance.get(event.utteranceId) ?? event.phoneReplyReceipt };
      if (session.replyControls && event.phoneReplyUnavailable) { void discard(item); stopSafely(session, 'Reply receipt unavailable. Stop Live and restart when ready.'); return; }
      // A protected Start is still negotiating/confirming until arm returns.
      // Discard completed setup speech instead of queuing an output-denied reply.
      if (session.protected && !session.protectedReady) { void discard(item); return; }
      // Decide at onset, not completion: playback may have started in between.
      // Also fail closed if a completion arrives without its onset while busy.
      if (session.ignoredOnsets.includes(item.id)
        || (!session.onsets.includes(item.id) && !item.receipt && waitingForReply(session))) {
        session.ignoredOnsets = session.ignoredOnsets.filter(id => id !== item.id);
        void discard(item); return;
      }
      if (queue.current.length + (active.current ? 1 : 0) >= 2) {
        void discard(item);
        stopSafely(session, 'Live Mic stopped: too many completed clips are waiting to send (backpressure).');
        return;
      }
      queue.current.push(item);
      void pump();
    }
  }, [canSubmit, discard, pump, showError, stopSafely, waitingForReply]);

  const cancelCapture = useCallback(async () => {
    rememberCaptureControl('capture_cancel');
    if(inputRouteRecovery.current){inputRouteRecovery.current.cancelled=true;if(mounted.current){setLiveEnabled(false);setLivePhase('off');setReconnecting(false);}}
    permissionEpoch.current += 1;
    if (preparingPermissions.current && mounted.current) setStarting(false);
    const session = current.current ?? retiring.current;
    if (session) await stopSession(session, '', 'cancel_capture');
  }, [stopSession]);

  const stopListening = useCallback(async (session:Session|null=current.current,routeRecovery=false) => {
    if(!routeRecovery&&inputRouteRecovery.current)inputRouteRecovery.current.cancelled=true;
    rememberCaptureControl('live_tail_stop');
    if (!session) return;
    if (session.recovering) { await stopSession(session, '', 'live_off_during_recovery'); return; }
    if (!session.replyControls || !session.protectedReady || !session.lease || !session.outputTicket) { await stopSession(session, '', 'live_off_without_reply_tail'); return; }
    if (session.listeningStopped) return;
    const ticket = session.outputTicket;
    const permit = session.callbacks.getReplyTailPermit?.(session.id) ?? { requestIds: [], pendingUploadIds: [...session.submitted] };
    recordLiveStop({ stage: 'requested', request_count: permit.requestIds.length,
      pending_upload_count: permit.pendingUploadIds.length, submitted_count: session.submitted.size,
      reply_controls: session.replyControls, protected_ready: session.protectedReady });
    // Fence completion observers before publishing Live off or yielding to the
    // shared audio queue. Stop owns the lease until it confirms closure/tail.
    session.stoppingListening = true;
    session.listeningStopped = true;
    if(!routeRecovery)setLiveEnabled(false);
    setLivePhase(routeRecovery?'listening':'off'); setStarting(false);
    session.callbacks.onBackgroundListeningStopped?.(session.id);
    for (const [id, receipt] of session.receiptByUtterance) if (!session.submitted.has(id)) {
      session.receiptByUtterance.delete(id);
      void Promise.resolve(latest.current.options.onPhoneReplyAbandon?.(receipt)).catch(() => undefined);
    }
    const dropped = queue.current.filter(item => item.session === session);
    queue.current = queue.current.filter(item => item.session !== session);
    void Promise.all(dropped.map(discard));
    try {
      if(session.attachment){
        const a=session.attachment;
        const lease=session.lease;
        const release=releaseCapture(lease,async()=>{
          await capture.stopListening(session.id,permit);
          const state=await capture.captureAttachmentState!(a.sessionId,a.ticket,a.captureId);
          if(!state.attached||!state.inputReleased)throw new Error('Native input release unconfirmed.');
        }).then(()=>{if(session.lease===lease)session.lease=undefined;});
        session.inputRelease=release;await release;
        if(session.cancelled)return;
        session.lease=undefined;session.subscription?.remove();
        if(current.current===session)current.current=null;
        replyScopes.current.set(session.id,session);
        recordLiveStop({stage:'input_detached',capture_epoch:session.epoch,output_preserved:true});
        if(!permit.requestIds.length&&!permit.pendingUploadIds.length){
          await capture.finishReplyOutput(session.id,ticket,[]);
          replyScopes.current.delete(session.id);session.cancelled=true;session.cancelSignal();
          session.callbacks.onBackgroundOutputFinished?.(session.id);
        }
        return;
      }
      await stopLiveListening(session.lease, async () => {
        // An ordered carrier can still be showing idle. Join its readers before
        // native empty-tail retirement, rather than reporting that expected
        // retirement as an unexpected playback failure.
        if (!permit.requestIds.length && !permit.pendingUploadIds.length)
          await session.callbacks.onBeforeReplyOutputFinish?.(session.id, ticket);
        if (!ownsSession(session)) throw new Error('Listening stop was cancelled.');
        await capture.stopListening(session.id, permit);
        const state = await capture.outputState();
        recordLiveStop({ stage: 'returned', output_open: state.open, output_owner_matches: state.ticket === ticket,
          session_matches: state.sessionId === session.id, cancelled: session.cancelled });
        // Real errors still queue terminal cleanup; leave its lease owned until it drains.
        if (session.cancelled || current.current !== session) throw new Error('Listening stop was cancelled.');
        if (state.ticket !== ticket || (state.open && state.sessionId !== session.id)) throw new Error('Native output ownership changed.');
        return state.open && state.ticket === ticket && state.sessionId === session.id;
      });
      if (!ownsSession(session)) return;
      const state = await capture.outputState();
      if (state.ticket !== ticket || (state.open && state.sessionId !== session.id)) throw new Error('Native output ownership changed.');
      if (!state.open) {
        session.lease = undefined;
        session.cancelled = true; session.cancelSignal(); session.subscription?.remove();
        session.receiptByUtterance.clear(); current.current = null;
        session.callbacks.onBackgroundOutputFinished?.(session.id);
      }
    } catch { showError(session, 'Microphone stop could not be confirmed. Stop Live and restart when ready.'); }
    finally { session.stoppingListening = false; }
  }, [capture, discard, ownsSession, showError, stopSession]);
  releaseInput.current=stopListening;

  stopListeningRef.current = session => {
    if (current.current === session) void stopListening();
  };

  const finishReplyOutput = useCallback(async (sessionId: string, ticket: string, completed: string[]) => {
    const retained=replyScopes.current.get(sessionId);
    if(retained?.attachment&&retained.outputTicket===ticket){
      if(retained.stoppingListening||retained.finishingReplyOutput||retained.submitted.size||!ownsSession(retained))return false;
      retained.finishingReplyOutput=true;
      try{
        await capture.finishReplyOutput(sessionId,ticket,completed);
        replyScopes.current.delete(sessionId);retained.cancelled=true;retained.cancelSignal();
        for(const timer of retained.pendingTimers)clearTimeout(timer);retained.pendingTimers.clear();
        retained.callbacks.onBackgroundOutputFinished?.(sessionId);return true;
      }catch{return false;}finally{retained.finishingReplyOutput=false;}
    }
    const session = current.current;
    if (!session || session.id !== sessionId || session.outputTicket !== ticket || !session.listeningStopped || !session.lease
      || session.stoppingListening || session.finishingReplyOutput || session.submitted.size || !ownsSession(session)) return false;
    try {
      await finishLiveReplyOutput(session.lease, async () => {
        session.finishingReplyOutput = true;
        await session.callbacks.onBeforeReplyOutputFinish?.(sessionId, ticket);
        if (!ownsSession(session)) throw new Error('Reply completion was cancelled.');
        await capture.finishReplyOutput(sessionId, ticket, completed);
        const state = await capture.outputState();
        // A real error/cancellation may have queued terminal cleanup while the
        // native promise was pending. Leave the lease for that cleanup to drain.
        if (session.cancelled || current.current !== session) throw new Error('Reply completion was cancelled.');
        if (state.open || state.ticket !== ticket) throw new Error('Native output closure could not be confirmed.');
      });
      if (current.current !== session || session.cancelled) return false;
      session.lease = undefined; session.cancelled = true; session.subscription?.remove(); current.current = null;
      session.callbacks.onBackgroundOutputFinished?.(session.id);
      return true;
    } catch { showError(session, 'Reply output is still owned. Stop Live before trying again.'); return false; }
    finally { session.finishingReplyOutput = false; }
  }, [capture, ownsSession, showError]);

  const submitReplyTurn = useCallback(async (sessionId: string, submissionId: string, kind: 'text' | 'image', operation: () => Promise<unknown>,authentication?:PhoneReplyAuth) => {
    const session = current.current;
    if (!session || session.id !== sessionId || !session.replyControls || !session.outputTicket || !canSubmit(session)) throw new Error('Live reply admission ended.');
    const ticket = session.outputTicket;
    const recoveryEpoch = session.recoveryEpoch;
    const submissionAuth = authentication??session.auth;
    const currentTurn = () => ownsSession(session,false,true) && !session.recovering && session.recoveryEpoch === recoveryEpoch;
    if (session.issuedSubmissions >= 256) { stopSafely(session, 'Reply admission capacity reached. Restart the phone app when ready.'); throw new Error('Reply admission capacity reached.'); }
    session.registeringTurns++;
    let registered: boolean;
    try { registered = await capture.registerSubmittedTurn(sessionId, ticket, submissionId, kind); }
    finally { if (session.recoveryEpoch === recoveryEpoch) session.registeringTurns--; }
    if (!registered || !canSubmit(session) || !currentTurn()) {
      await capture.abandonSubmittedUpload(sessionId, ticket, submissionId);
      throw new Error('Live reply submission unavailable. Stop Live and restart when ready.');
    }
    session.submitted.add(submissionId);
    session.issuedSubmissions++;
    session.callbacks.onBackgroundUpload?.(sessionId, submissionId);
    try {
      const result = await operation();
      if (currentTurn()) await settleSubmission(session, submissionId, phoneReplyRequestId(result), submissionAuth);
      if (!currentTurn()) await retireRecoveredReply(session, recoveryEpoch, result, submissionAuth, submissionId);
      return result;
    } catch (failure) {
      if (!isUncertainPhoneReplyError(failure) && currentTurn()) await settleSubmission(session, submissionId, null);
      else if (currentTurn()) {
        const timer = setTimeout(() => { session.pendingTimers.delete(timer);
          if (currentTurn()) stopSafely(session, 'Reply acknowledgement could not be recovered. Stop Live and restart when ready.'); }, 900_000);
        session.pendingTimers.add(timer);
      }
      if (currentTurn() && phoneReplyErrorCode(failure) === 'phone_reply_authentication') {
        void session.callbacks.getPhoneReplyAuth?.(true).catch(() => undefined);
        stopSafely(session, 'Phone reply authorization expired. Start Live again when ready.');
        throw new Error('Phone reply authorization expired. The message was not accepted.');
      }
      if (!isUncertainPhoneReplyError(failure)) throw failure;
      throw new Error('Phone reply acknowledgement unavailable. The message may have been accepted.');
    }
  }, [capture, canSubmit, ownsSession, settleSubmission, stopSafely, retireRecoveredReply]);

  useEffect(() => {
    mounted.current = true;
    const subscription = AppState.addEventListener('change', (state) => {
      foreground.current = state === 'active';
      if(!foreground.current&&inputRouteRecovery.current)inputRouteRecovery.current.cancelled=true;
      if (!foreground.current && current.current && !current.current.backgroundAuthorized) {
        const session = current.current;
        if (Platform.OS === 'android' && session.replyControls && session.protectedReady) {
          stopListeningRef.current(session);
        } else stopSafely(session, 'Live Mic stopped when the app left the foreground.');
      }
    });
    return () => {
      mounted.current = false;
      if(inputRouteRecovery.current)inputRouteRecovery.current.cancelled=true;
      permissionEpoch.current += 1;
      subscription.remove();
      if (current.current) stopSafely(current.current, '');
      for(const session of replyScopes.current.values())void stopSession(session,'','unmount').catch(()=>undefined);
    };
  }, [stopSafely]);

  useEffect(() => {
    for(const retained of replyScopes.current.values())if(!ownsSession(retained)
      &&!(retained.independentCapture&&!retained.cancelled&&retained.orderedContinuationKey
        &&retained.orderedContinuationKey===options.orderedContinuationKey))
      void stopSession(retained,'','reply_scope_changed').catch(()=>undefined);
    const session = current.current;
    if (!session) return;
    if(session.orderedContinuationKey&&session.orderedContinuationKey!==options.orderedContinuationKey){
      stopSafely(session,'Live Mic stopped because the connection or conversation changed.');return;
    }
    const recoverable = session.recoverySupported && session.protectedReady && !session.listeningStopped
      && session.recoveryKey && session.recoveryKey === options.connectionRecoveryKey && options.enabled
      && (foreground.current || session.backgroundAuthorized)
      && (!session.backgroundRequested || options.allowBackgroundLive === true);
    if (!recoverable) {
      if (session.recovering || (session.recoverySupported && session.recoveryKey && session.recoveryKey !== options.connectionRecoveryKey)
        || !ownsSession(session, true)) stopSafely(session, 'Live Mic stopped because the connection or conversation changed.');
      return;
    }
    const changed = session.client !== client || session.identity !== options.identityKey
      || session.transportRevision !== (options.transportFailureRevision ?? 0);
    if(!session.recovering&&session.independentCapture&&(
      session.orderedContinuationKey&&session.orderedContinuationKey===options.orderedContinuationKey
      ||session.orderedPlaybackPeer&&session.orderedPlaybackPeer===options.orderedPlaybackPeer&&session.client===client&&session.identity===options.identityKey)){
      // The command lane may be unavailable while the exact buffered media
      // lifetime survives. canSubmit still blocks disconnected uploads; do not
      // pause native output, clear reply receipts or renew its shared credential.
      const waiting=!connected||options.connectionRecoveryReady===false;
      setReconnecting(waiting);
      if(!waiting){
        session.client=client;session.identity=options.identityKey;
        session.orderedPlaybackPeer=options.orderedPlaybackPeer;
        session.callbacks={...options};
        session.transportRevision=options.transportFailureRevision??0;
        if(!voiceAvailable)stopSafely(session,'Live Mic stopped because the connection or conversation changed.');
      }
      return;
    }
    if (!session.recovering && connected && !changed) {
      if (!voiceAvailable) stopSafely(session, 'Live Mic stopped because the connection or conversation changed.');
      return;
    }
    if (!session.recovery) {
      session.recoveryTransport = { client: session.client, revision: session.transportRevision, serial: 0 };
      const trace = (stage: string, details: Record<string, string | number | boolean> = {}) => recordRecovery(session, stage, details);
      const valid = (epoch: number, signal: AbortSignal, target?: LegacyRecovery['target']) => {
        const owned = !signal.aborted && current.current === session && !session.cancelled
          && session.recoveryEpoch === epoch && latest.current.options.connectionRecoveryKey === session.recoveryKey;
        return owned && (!target || (latest.current.client === target.client && latest.current.connected
          && latest.current.voiceAvailable && latest.current.options.connectionRecoveryReady !== false));
      };
      session.recovery = new ContinuationRecovery<LegacyRecovery>({
        suspend: async (epoch, signal) => {
          session.recoveryEpoch = epoch; session.recovering = true;
          trace('pause_requested', { connected: latest.current.connected, transport_changed: changed,
            foreground: foreground.current, continuation_supported: session.continuationSupported === true });
          setReconnecting(true); setBusy(false); setLivePhase('listening'); setError('');
          for (const timer of session.pendingTimers) clearTimeout(timer);
          session.pendingTimers.clear(); session.receiptByUtterance.clear(); session.submitted.clear();
          if (active.current?.session === session) active.current = null;
          session.registeringTurns = 0;
          const dropped = queue.current.filter(item => item.session === session);
          queue.current = queue.current.filter(item => item.session !== session);
          void Promise.all(dropped.map(discard));
          const continuationEnabled = session.continuationSupported && session.auth?.reply_continuation_version === 1
            && latest.current.options.onReplyContinuationValidate && latest.current.options.onReplyContinuationRestored;
          const pause = Promise.resolve(continuationEnabled
            ? capture.pauseReplyContinuation?.(session.id, session.outputTicket!, epoch)
            : capture.pauseConnection?.(session.id, session.outputTicket!, epoch) ?? false);
          session.recoveryPause = pause.then(paused => Boolean(paused) && valid(epoch, signal), () => false);
          const paused = await pause;
          if (!valid(epoch, signal)) { trace('superseded', { operation: 'native_pause' }); return { ids: [] }; }
          if (!paused) throw new Error('Native connection pause rejected');
          const checkpoint = continuationEnabled && typeof paused === 'object' ? paused : undefined;
          session.continuationCheckpoint = checkpoint;
          if (checkpoint) {
            trace('checkpoint_ready', { reply_count: checkpoint.replies.length,
              completed_chunk_count: checkpoint.replies.reduce((n, r) => n + r.completedChunkIds.length, 0),
              active_chunk_count: checkpoint.replies.filter(r => r.activeChunkId).length,
              known_position_count: checkpoint.replies.filter(r => r.positionSeconds !== null).length });
            latest.current.options.onReplyContinuationPaused?.(checkpoint, session.pendingAdmissions);
            for (const reply of checkpoint.replies) {
              const admission = session.pendingAdmissions.get(reply.requestId);
              if (admission) admission.checkpointed = true;
            }
          } else { trace('checkpoint_not_supported'); latest.current.options.onConnectionPaused?.(session.id, session.outputTicket!); }
          return { checkpoint, ids: [] };
        },
        validate: async (state, epoch, signal) => {
          const target = state.target = latest.current;
          trace('authorization_requested');
          const auth = await target.options.getPhoneReplyAuth?.(true);
          if (!valid(epoch, signal, target)) return;
          if (!auth) throw new Error('Reply authorization unavailable');
          trace('manifest_requested', { checkpoint_present: Boolean(state.checkpoint) });
          const ids = state.checkpoint ? await target.options.onReplyContinuationValidate!(state.checkpoint) : [];
          if (!valid(epoch, signal, target)) return;
          state.auth = auth; state.ids = ids;
        },
        resume: async (state, epoch, signal) => {
          const target = state.target!;
          if (!valid(epoch, signal, target)) return;
          trace('native_resume_requested', { retained_reply_count: state.ids.length });
          const resumed = state.checkpoint
            ? await capture.resumeReplyContinuation?.(session.id, session.outputTicket!, epoch, state.ids)
            : await capture.resumeConnection?.(session.id, session.outputTicket!, epoch);
          if (!valid(epoch, signal, target)) return;
          if (!resumed) throw new Error('Native connection resume rejected');
          session.auth = state.auth; session.client = target.client; session.identity = target.options.identityKey;
          session.orderedPlaybackPeer = target.options.orderedPlaybackPeer;
          session.transportRevision = target.options.transportFailureRevision ?? 0;
          session.callbacks = { ...latest.current.options };
          session.onsets = []; session.completions = []; session.ignoredOnsets = [];
          trace('playback_restore_requested');
          if (state.checkpoint) await session.callbacks.onReplyContinuationRestored!(state.checkpoint);
          else session.callbacks.onConnectionRestored?.(session.id, session.outputTicket!, epoch);
          if (!valid(epoch, signal, target)) return;
          session.continuationCheckpoint = undefined; session.recovering = false;
          trace('resumed'); setReconnecting(false); setError('');
        },
        cancel: async reason => {
          if (session.cancelled) return;
          trace('failed', { operation: reason, reason: 'rejected_or_exception' });
          stopSafely(session, reason === 'suspend_failed'
            ? 'Live connection recovery could not pause safely. Start Live again when ready.'
            : 'Live connection recovery could not authorize replies. Start Live again when ready.');
        },
        observe: () => {}, // The existing catalogued producer above owns stage diagnostics.
        retryable: failure => isUncertainPhoneReplyError(failure) || (failure instanceof RemoteRequestError && failure.status >= 500),
        schedule: retry => {
          trace('retry_scheduled', { operation: 'authorization', delay_ms: 5000 });
          const timer = setTimeout(() => { session.pendingTimers.delete(timer); retry(); }, 5000);
          session.pendingTimers.add(timer);
          return () => { clearTimeout(timer); session.pendingTimers.delete(timer); };
        },
      });
      session.recovery.observe({ ownerKey: session.recoveryKey!, transportRevision: 0,
        connected: true, freshState: true, locked: false, enabled: true });
    }
    const transport = session.recoveryTransport!;
    const revision = options.transportFailureRevision ?? 0;
    if (transport.client !== client || transport.revision !== revision) {
      transport.client = client; transport.revision = revision; transport.serial++;
    }
    session.recovery.observe({ ownerKey: options.connectionRecoveryKey!, transportRevision: transport.serial,
      connected, freshState: voiceAvailable && options.connectionRecoveryReady !== false,
      locked: !foreground.current && !session.backgroundAuthorized, enabled: options.enabled });
  }, [client, connected, voiceAvailable, options.identityKey, options.enabled, options.allowBackgroundLive,
    options.transportFailureRevision, options.connectionRecoveryKey, options.connectionRecoveryReady, options.orderedPlaybackPeer,options.orderedContinuationKey,
    reconnecting, ownsSession, stopSafely, capture, discard]);

  useEffect(() => {
    const session = current.current;
    if (!session) return;
    void (async () => {
      await session.setup;
      if (!canSubmit(session)) return;
      await capture.setPlaybackActive(session.id, Boolean(latest.current.options.playbackActive));
    })().catch(() => { if (canSubmit(session)) stopSafely(session, 'Live Mic could not update its playback state.'); });
  }, [options.playbackActive, capture, canSubmit, stopSafely]);

  const toggleLive = useCallback(async (recoverForegroundRoute = false) => {
    if(!recoverForegroundRoute&&inputRouteRecovery.current){
      inputRouteRecovery.current.cancelled=true;permissionEpoch.current++;
      if(current.current)await stopListening();
      setLiveEnabled(false);setLivePhase('off');setStarting(false);setReconnecting(false);
      return;
    }
    rememberCaptureControl(current.current ? 'live_toggle_stop' : 'live_toggle_start');
    if (preparingPermissions.current) return;
    if (current.current) {
      if (current.current.listeningStopped) { setError('The previous reply is still finishing. Stop speech or wait before starting Live.'); return; }
      await stopListening(); return;
    }
    if (retiring.current) {
      await stopSession(retiring.current, '', 'drain_previous_session').catch(() => undefined);
      // A failed drain keeps ownership and blocks a new capture.
      if (retiring.current || current.current) return;
    }
    const now = latest.current;
    const duckingLevel = Platform.OS === 'android' ? 'default' : now.options.liveDuckingLevel ?? 'default';
    if (!mounted.current || !foreground.current || !now.options.enabled) return;
    if (!now.connected || !now.voiceAvailable) { setError('Connect with phone voice input available before starting Live Mic.'); return; }
    // Android permission activities temporarily background the app. No Live session
    // may own the microphone until those activities have returned to the foreground.
    preparingPermissions.current = true;
    const permissionAttempt = ++permissionEpoch.current;
    setError(''); setStarting(true);
    let androidBluetoothPermission = false;
    let backgroundAllowed = now.options.allowBackgroundLive === true && recoverForegroundRoute !== true;
    try {
      const permission = await ensureRecordingPermission();
      if (!permission.granted) throw new Error('Microphone permission denied.');
      if (backgroundAllowed) {
        const permissions = await requestAndroidBackgroundPermissions();
        androidBluetoothPermission = permissions.bluetoothGranted;
        backgroundAllowed = permissions.notificationGranted;
      } else if (Platform.OS==='android'&&Number(Platform.Version)>=31) {
        // Ask before any native session exists: the permission activity itself
        // may background NC. Foreground Bluetooth duplex needs this too.
        androidBluetoothPermission=await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT)
          ===PermissionsAndroid.RESULTS.GRANTED;
      }
      if (!foreground.current) {
        await new Promise<void>((resolve, reject) => {
          const subscription = AppState.addEventListener('change', (state) => {
            if (state === 'active') { clearTimeout(timeout); subscription.remove(); resolve(); }
          });
          const timeout = setTimeout(() => { subscription.remove(); reject(new Error('Return to the app and start Live Mic again.')); }, 5000);
          if (foreground.current) { clearTimeout(timeout); subscription.remove(); resolve(); }
        });
      }
    } catch (failure) {
      if (mounted.current && permissionAttempt === permissionEpoch.current) {
        setError(failure instanceof Error ? failure.message : 'Live Mic permission was unavailable.'); setStarting(false);
      }
      return;
    } finally {
      preparingPermissions.current = false;
    }
    if (!mounted.current || permissionAttempt !== permissionEpoch.current || !foreground.current || current.current || !latest.current.connected
      || !latest.current.options.enabled || latest.current.options.identityKey !== now.options.identityKey) {
      setStarting(false); return;
    }
    let cancelSignal!: () => void;
    const cancelledSignal = new Promise<void>((resolve) => { cancelSignal = resolve; });
    const session: Session = { id: `ios-live-${Date.now()}-${++nextSession}`, epoch: ++epoch.current,
      identity: now.options.identityKey, client: now.client, cancelled: false,
      sequence: 0, onsets: [], completions: [], ignoredOnsets: [], registeringTurns: 0, attemptedStart: false,
      backgroundRequested: backgroundAllowed, backgroundAuthorized: false, protected: false, protectedReady: false, foregroundProtected: false,
      callbacks: { ...now.options }, transportRevision: now.options.transportFailureRevision ?? 0, cancelledSignal, cancelSignal,
      listeningStopped: false, replyControls: false, submitted: new Set(), receiptByUtterance: new Map(), pendingAdmissions: new Map(), pendingTimers: new Set(), issuedSubmissions: 0,
      recoveryKey: now.options.connectionRecoveryKey, recoveryEpoch: 0,orderedPlaybackPeer:now.options.orderedPlaybackPeer,
      orderedContinuationKey:now.options.orderedContinuationKey };
    current.current = session;
    setError(''); setForegroundOnly(now.options.allowBackgroundLive === true && !backgroundAllowed);
    setLiveEnabled(true); setStarting(true); setLivePhase('listening');
    session.setup = (async () => {
      try {
        const capabilities = await capture.capabilities();
        session.recoverySupported = capabilities.connectionRecoveryVersion === 1;
        session.continuationSupported = capabilities.replyContinuationVersion === 1
          && typeof capture.pauseReplyContinuation === 'function' && typeof capture.resumeReplyContinuation === 'function';
        if (!canSubmit(session)) return;
        if (!capabilities.available) { showError(session, Platform.OS === 'android'
          ? 'Android Live Mic requires the updated custom app build.'
          : 'iOS Live Mic requires an updated development build.'); return; }
        if(Platform.OS==='android'){
          if(capabilities.independentCaptureVersion!==1||!capture.attachCapture||!capture.captureAttachmentState||!capture.detachCapture||!session.callbacks.getPlaybackTicketForCapture){
            showError(session,'Android Live Mic requires the independent capture app build.');return;
          }
          session.independentCapture=true;
        }
        const replySupported = now.options.phoneReplyControls && capabilities.stopListeningVersion === 1 && capabilities.foregroundReplyControlsVersion === 1;
        if (now.options.phoneReplyControls && !replySupported) {
          showError(session, 'Separate Live off and Stop speech require an updated phone app. Legacy Live stop remains available.');
        }
        if (duckingLevel !== 'default' && capabilities.duckingSupported !== true) {
          showError(session, 'This Live Mode volume reduction requires iOS 17 or later and an updated app build. Use system default to continue.');
          return;
        }
        await Promise.race([session.callbacks.onBeforeLiveStart?.('live'), session.cancelledSignal]);
        if (!canSubmit(session)) return;
        session.lease = await acquireCapture('ios-live');
        if (!canSubmit(session)) return;
        if (session.backgroundRequested && capabilities.backgroundLiveVersion !== 1) {
          showError(session, Platform.OS === 'android'
            ? 'Android Background Live requires the updated custom app build.'
            : 'Background Live requires an updated development build.'); return;
        }
        // Speaker capture preserves foreground startup and never changes Expo mode.
        if(session.independentCapture){
          if(!replySupported)throw new Error('Phone reply admission unavailable.');
          session.protected=true;session.foregroundProtected=!session.backgroundRequested;
          session.outputTicket=await session.callbacks.getPlaybackTicketForCapture!();
          if(!canSubmit(session))return;
          session.attachment=await capture.attachCapture!(session.id,session.outputTicket,session.foregroundProtected);
          if(!canSubmit(session))return;
          session.callbacks.onBackgroundSessionStart?.(session.id);
          session.callbacks.onBackgroundOutputTicket?.(session.id,session.outputTicket);
          recordLiveStop({stage:'capture_attached',capture_epoch:session.epoch,output_preserved:true});
        } else if (session.backgroundRequested && (Platform.OS === 'android' || capabilities.backgroundRoute !== 'ineligible')) {
          session.protected = true;
          session.callbacks.onBackgroundSessionStart?.(session.id);
          await prepareLiveBackgroundAudio(session.lease);
          if (!canSubmit(session)) return;
          const output = await capture.outputState();
          if (!canSubmit(session)) return;
          if (output.open && output.sessionId === null && output.ticket) {
            await capture.retireOutput(output.ticket);
            if (!canSubmit(session)) return;
          }
          session.outputTicket = await capture.beginProtectedOutput(session.id, output.ticket);
          if (!canSubmit(session)) return;
          session.callbacks.onBackgroundOutputTicket?.(session.id, session.outputTicket);
        } else if (replySupported) {
          session.protected = true; session.foregroundProtected = true;
          session.callbacks.onBackgroundSessionStart?.(session.id);
          const output = await capture.outputState();
          if (!canSubmit(session)) return;
          if (output.open && output.sessionId === null && output.ticket) {
            await capture.retireOutput(output.ticket);
            if (!canSubmit(session)) return;
          }
          session.outputTicket = await capture.beginForegroundProtectedOutput(session.id, output.ticket);
          if (!canSubmit(session)) return;
          session.callbacks.onBackgroundOutputTicket?.(session.id, session.outputTicket);
          if (session.backgroundRequested) setForegroundOnly(true);
        } else if (session.backgroundRequested) setForegroundOnly(true);
        session.subscription = capture.subscribe((event) => receive(session, event));
        session.attemptedStart = true;
        if (Platform.OS === 'android') await capture.setSpeechSensitivity?.(now.options.liveMicSensitivity ?? 4);
        await startLiveCapture(session.lease, () => capture.start(session.id, duckingLevel));
        if (!canSubmit(session)) return;
        if (session.foregroundProtected) {
          const armed = await capture.armForeground(session.id);
          if (!armed) {
            try {
              const state = await capture.outputState();
              recordLiveStop({stage:'foreground_arm_rejected',...(state.foregroundArmFailure ?? {reason:'native_evidence_unavailable'})});
            } catch {recordLiveStop({stage:'foreground_arm_rejected',reason:'evidence_read_failed'});}
          }
          if (!canSubmit(session)) return;
          if (!armed) { showError(session, Platform.OS === 'android'
            ? 'Live microphone audio setup was not accepted. Let the audio device settle, then tap Start Live to retry.'
            : 'Foreground Live could not be armed. Restart Live when ready.'); session.cancelled = true; return; }
          session.protectedReady = !replySupported;
        } else if (session.protected && Platform.OS === 'android') {
          const confirmed = await Promise.race([
            session.callbacks.confirmBluetoothHeadphones?.() ?? Promise.resolve(false),
            session.cancelledSignal.then(() => false),
          ]);
          if (!canSubmit(session)) return;
          if (confirmed && Number(Platform.Version) >= 31 && !androidBluetoothPermission) {
            showError(session, 'Android Background Live needs Nearby devices permission for Bluetooth headphones.');
            session.cancelled = true; return;
          }
          const armed = await capture.armBackground(session.id, confirmed);
          if (!canSubmit(session)) return;
          const admittedRoute = (await capture.capabilities()).backgroundRoute;
          if (!canSubmit(session)) return;
          if (!armed || !['wired', 'bluetooth'].includes(admittedRoute ?? '')
            || (admittedRoute === 'bluetooth' && !confirmed)) {
            showError(session, 'Android Background Live could not verify an active headphone microphone and output route. Restart Live when ready.');
            session.cancelled = true; return;
          }
          session.backgroundAuthorized = true;
          session.protectedReady = !replySupported;
        } else if (session.protected) {
          const route = (await capture.capabilities()).backgroundRoute;
          if (!canSubmit(session)) return;
          let confirmed = false;
          if (route === 'bluetooth') {
            confirmed = await Promise.race([
              session.callbacks.confirmBluetoothHeadphones?.() ?? Promise.resolve(false),
              session.cancelledSignal.then(() => false),
            ]);
          }
          if (!canSubmit(session)) return;
          const settledRoute = (await capture.capabilities()).backgroundRoute;
          if (!canSubmit(session)) return;
          if (route !== settledRoute || route === 'ineligible' || (route === 'bluetooth' && !confirmed)) {
            showError(session, 'Background Live needs confirmed headphones. Restart Live Mic when ready.');
            session.cancelled = true; return;
          }
          const armed = await capture.armBackground(session.id, confirmed);
          if (!canSubmit(session)) return;
          if (!armed) { showError(session, 'Background Live could not be armed. Restart Live Mic when ready.'); session.cancelled = true; return; }
          session.backgroundAuthorized = true;
          session.protectedReady = !replySupported;
        }
        if (session.protected && replySupported) {
          session.auth = await now.options.getPhoneReplyAuth?.();
          if (!canSubmit(session)) return;
          if (!session.auth) throw new Error('Phone reply capability unavailable.');
          session.replyControls = true;
          session.protectedReady = true;
        }
        await capture.setPlaybackActive(session.id, Boolean(latest.current.options.playbackActive));
        if (!canSubmit(session)) return;
        setStarting(false);
        void diagnose(session, 'start');
        return;
      } catch (failure) {
        if (canSubmit(session)) {
          const message = failure instanceof Error ? failure.message : '';
          showError(session, message.startsWith('Android Background Live needs ') ? message
            : String((failure as { code?: unknown })?.code ?? '').includes('background_session_limit')
              || String(failure).includes('background_session_limit') ? SESSION_LIMIT
              : Platform.OS === 'android'
                ? 'Could not start Android Live Mic. Audio setup did not complete; tap Start Live to retry.'
                : 'Could not start iOS Live Mic. Stop other microphone capture before retrying.');
        }
      }
      // Cleanup is scheduled by the caller after setup resolves, avoiding a
      // cycle between stop's drain and this setup promise.
      session.cancelled = true;
    })();
    await session.setup;
    if (!canSubmit(session) || !session.attemptedStart || session.cancelled) {
      await stopSession(session, '', 'start_cleanup').catch(() => undefined);
    }
  }, [stopListening, canSubmit, capture, diagnose, receive, showError, stopSession]);

  restartInputRoute.current=async(session:Session)=>{
    if(inputRouteRecovery.current||current.current!==session||!ownsSession(session))return;
    const attempt={session,cancelled:false};inputRouteRecovery.current=attempt;
    const eligible=()=>inputRouteRecovery.current===attempt&&!attempt.cancelled&&mounted.current&&foreground.current
      &&latest.current.connected&&latest.current.voiceAvailable&&latest.current.options.enabled
      &&latest.current.client===session.client&&latest.current.options.identityKey===session.identity;
    recordLiveStop({stage:'input_route_recovery_begin',capture_epoch:session.epoch,output_preserved:true});
    setReconnecting(true);setError('');
    let operation='input_release';
    try{
      // The existing exact attachment release preserves admitted reply tails.
      // Never use whole-output retirement or the player-replacement recovery.
      await stopListening(session,true);
      if(session.lease)throw Error('Input release unconfirmed');
      if(!eligible())return;
      operation='route_settle';
      // Device removals/additions arrive in a burst; one restart, not a loop.
      await new Promise(resolve=>setTimeout(resolve,350));
      if(!eligible()||current.current)return;
      operation='input_restart';
      await toggleLive(true);
      if(!eligible())return;
      operation='restart_confirmation';
      const resumed=current.current as Session|null;
      if(!resumed?.protectedReady||!resumed.independentCapture||resumed.outputTicket!==session.outputTicket)
        throw Error('Input restart unconfirmed');
      recordLiveStop({stage:'input_route_recovery_restored',capture_epoch:resumed.epoch,output_preserved:true});
    }catch{
      if(eligible()){
        recordLiveStop({stage:'input_route_recovery_failed',operation,capture_epoch:session.epoch,output_preserved:true});
        setError(`Microphone route recovery failed at ${operation}. Tap Start Live to retry.`);
      }
    }finally{
      if(inputRouteRecovery.current===attempt){
        inputRouteRecovery.current=null;
        if(mounted.current){
          setReconnecting(false);
          if(!current.current||current.current===session){setLiveEnabled(false);setLivePhase('off');}
        }
      }
    }
  };

  const isBackgroundSessionReady = useCallback((sessionId: string): boolean => {
    const session = current.current;
    return Boolean(session && session.id === sessionId && session.protected
      && session.protectedReady && canSubmit(session));
  }, [canSubmit]);

  return { cancelCapture, stopListening, finishReplyOutput, submitReplyTurn, isBackgroundSessionReady, busy, error, transcript: '', clearTranscript: () => undefined,
    resumeLiveAfterRouteChange:async()=>{
      await toggleLive(true);
      const resumed=current.current;
      if(!resumed||!resumed.protectedReady||!canSubmit(resumed))throw Error('Audio route microphone restart unavailable');
    },
    liveEnabled, livePhase, meteringDb, meteringRevision, toggleLive, reconnecting,
    liveStatus: error || (reconnecting ? 'Live paused — reconnecting…' : !liveEnabled ? 'Off' : starting ? 'Starting microphone...' : foregroundOnly ? 'Listening (foreground only)' : busy
      ? 'Listening while sending...' : livePhase === 'speech' ? 'Hearing you...' : current.current?.backgroundAuthorized
        ? 'Background Live ready — headphones required' : 'Listening...'),
    pauseLiveForPlayback: async () => undefined };
}
