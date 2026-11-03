import { useCallback, useEffect, useRef, useState } from 'react';
import {observeOrderedControlWait as observeWait} from '../diagnostics/orderedControlWait';
import { AppState, PermissionsAndroid, Platform } from 'react-native';
import {
  AudioModule,
  RecordingPresets,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';

import { RemoteClient, isUncertainPhoneReplyError, phoneReplyErrorCode, phoneReplyRequestId, retryPhoneReply } from '../api/client';
import type { SendTextOptions } from '../api/client';
import type { PhoneReplyAuth, PhoneReplyReceipt } from '../api/types';
import { remoteActionError } from '../api/envelope';
import {
  advanceLiveMicDetector,
  createLiveMicDetector,
} from '../utils/liveMicPolicy';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { rememberCaptureControl } from '../diagnostics/captureControlTrail';
import { fileExtensionFromUri } from '../utils/url';
import { acquireCapture, configurePhoneAudio, releaseCapture } from '../native/phoneCaptureOwnership';
import type { Lease } from '../native/phoneCaptureOwnership';
import { androidContinuousCaptureRuntimeEnabled } from '../native/iosContinuousCapturePolicy';
import {manualDeparture} from '../native/androidManualDeparture';
import type {ManualDeparturePermit} from '../native/androidManualDeparture';
import { ensureRecordingPermission } from '../native/recordingPermission';

const requiresCaptureLease = () => Platform.OS === 'ios' || androidContinuousCaptureRuntimeEnabled();

const MAX_RECORDING_MS = 60_000;
const MAX_STT_UPLOAD_BYTES = 18 * 1024 * 1024;
const MAX_STT_UPLOAD_MB = Math.floor(MAX_STT_UPLOAD_BYTES / (1024 * 1024));
const LIVE_METER_INTERVAL_MS = 100;
const MANUAL_RECORDING_OPTIONS = {
  ...RecordingPresets.HIGH_QUALITY!,
  isMeteringEnabled: true,
};
const LIVE_RECORDING_OPTIONS = {
  ...MANUAL_RECORDING_OPTIONS,
  android: {
    ...MANUAL_RECORDING_OPTIONS.android,
    audioSource: 'voice_communication' as const,
  },
};

// Native disposal must wait for our capture drain. Expo's managed hook releases
// its shared object synchronously, before this hook's async unmount cleanup.
function useNativeAudioRecorder(options: Parameters<typeof useAudioRecorder>[0]) {
  const recorderRef = useRef<ReturnType<typeof useAudioRecorder> | undefined>(undefined);
  if (!recorderRef.current) {
    recorderRef.current = new AudioModule.AudioRecorder({
      extension: options.extension, sampleRate: options.sampleRate,
      numberOfChannels: options.numberOfChannels, bitRate: options.bitRate,
      isMeteringEnabled: options.isMeteringEnabled ?? false,
      ...(Platform.OS === 'ios' ? options.ios : options.android),
    });
  }
  return recorderRef.current!;
}
const usePhoneAudioRecorder = Platform.OS === 'web' ? useAudioRecorder : useNativeAudioRecorder;

type RecorderMode = 'idle' | 'manual' | 'live';
type LivePhase = 'off' | 'listening' | 'speech';

export type RecorderOptions = {
  sendToChat?: boolean;
  // Optional manual-photo turn: transcribe without dispatch, then submit image+text.
  prepareTranscriptSubmission?: (permit?:ManualDeparturePermit) => ((text: string) => Promise<unknown>) | undefined;
  manualScope?:object;
  sendOptions?: SendTextOptions;
  livePauseReason?: string;
  playbackActive?: boolean;
  onLiveSpeechStart?: () => Promise<void> | void;
  phoneReplyControls?: boolean;
  getPhoneReplyAuth?: (renew?: boolean) => Promise<PhoneReplyAuth>;
  onPhoneReplyOnset?: (receipt?: PhoneReplyReceipt) => Promise<void> | void;
  freezePhoneReply?: () => PhoneReplyReceipt | null;
  onPhoneReplySubmitted?: (requestId: string, auth: PhoneReplyAuth) => void;
  beginPhoneReplySubmission?: () => {
    isCurrent: () => boolean;
    settle: (requestId: string | null, auth: PhoneReplyAuth) => void;
    fail: (failure: unknown) => void;
  };
  onPhoneReplyAbandon?: (receipt: PhoneReplyReceipt) => Promise<void> | void;
};

type FinishOptions = {
  upload: boolean;
  sendToChat?: boolean;
  unavailableMessage?: string;
};
type ManualWork={id:string;epoch:number;scope?:object;native:boolean;uri:string;options:RecorderOptions;
  submission?:((text:string)=>Promise<unknown>);receipt?:PhoneReplyReceipt;sendToChat:boolean;
  claimed:boolean;explicit:boolean;uncertain:boolean;retainedRevision:number;permit:ManualDeparturePermit};
class RetainManualRecording extends Error {constructor(){super('Recording not sent. Return to NC to Send or Discard.');}}

function resultText(value: unknown): string {
  if (!value || typeof value !== 'object') {
    return '';
  }
  const payload = value as Record<string, unknown>;
  const direct = String(payload.text || '').trim();
  if (direct) {
    return direct;
  }
  const result = payload.result;
  if (result && typeof result === 'object') {
    return String((result as Record<string, unknown>).text || '').trim();
  }
  return '';
}

export function useRecorder(client: RemoteClient, connected: boolean, voiceAvailable = true, options: RecorderOptions = {}) {
  const recorder = usePhoneAudioRecorder(MANUAL_RECORDING_OPTIONS);
  const recorderDisposedRef = useRef(false);
  const recorderState = useAudioRecorderState(recorder, LIVE_METER_INTERVAL_MS);
  const [mode, setMode] = useState<RecorderMode>('idle');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [transcript, setTranscript] = useState('');
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [livePhase, setLivePhase] = useState<LivePhase>('off');
  const [permissionReady, setPermissionReady] = useState(false);
  const [captureRevision, setCaptureRevision] = useState(0);
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectedRef = useRef(connected);
  const voiceAvailableRef = useRef(voiceAvailable);
  const optionsRef = useRef(options);
  const clientRef = useRef(client);
  clientRef.current = client;
  const modeRef = useRef<RecorderMode>('idle');
  const busyRef = useRef(false);
  const liveEnabledRef = useRef(false);
  const liveSessionRef = useRef(0);
  const mountedRef = useRef(true);
  const foregroundRef = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const activeRecordingUriRef = useRef<string | null>(null);
  const transitionRef = useRef(false);
  const captureEpochRef = useRef(0);
  const captureReleasedRef = useRef(true);
  const captureLeaseRef = useRef<Lease | undefined>(undefined);
  const cancelCaptureRef = useRef<(() => Promise<void>) | undefined>(undefined);
  const transitionWaitersRef = useRef<Array<() => void>>([]);
  const permissionGrantedRef = useRef(false);
  const liveDetectorRef = useRef(createLiveMicDetector());
  const frozenReplyRef = useRef<PhoneReplyReceipt | undefined>(undefined);
  const manualIdRef=useRef<string|null>(null);
  const manualWorkRef=useRef<ManualWork|null>(null);
  const [pendingRecording,setPendingRecording]=useState<{id:string;canSend:boolean}|null>(null);

  const setRecorderMode = useCallback((nextMode: RecorderMode) => {
    modeRef.current = nextMode;
    setMode(nextMode);
  }, []);

  const setRecorderBusy = useCallback((nextBusy: boolean) => {
    busyRef.current = nextBusy;
    setBusy(nextBusy);
  }, []);

  const setLiveSessionEnabled = useCallback((enabled: boolean) => {
    if (enabled !== liveEnabledRef.current) {
      liveSessionRef.current += 1;
    }
    liveEnabledRef.current = enabled;
    setLiveEnabled(enabled);
    if (!enabled) {
      setLivePhase('off');
    }
  }, []);

  useEffect(() => {
    connectedRef.current = connected;
    voiceAvailableRef.current = voiceAvailable;
    setError('');
  }, [connected, voiceAvailable]);

  useEffect(() => {
    optionsRef.current = options;
  }, [options]);

  const clearStopTimer = useCallback(() => {
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      captureEpochRef.current += 1;
      liveEnabledRef.current = false;
      liveSessionRef.current += 1;
      clearStopTimer();
      // A pending acquire can own input before its lease reaches this ref.
      // Failed stops retain their lease, but still dispose the native handle.
      const drain = captureLeaseRef.current || transitionRef.current
        ? cancelCaptureRef.current?.() : Promise.resolve();
      void Promise.resolve(drain).catch(() => undefined).then(() => {
        if (Platform.OS !== 'web' && !mountedRef.current && !recorderDisposedRef.current) {
          recorderDisposedRef.current = true;
          recorder.release();
        }
      }).catch(() => undefined);
    };
  }, [clearStopTimer, recorder]);

  const ensurePermission = useCallback(async (): Promise<boolean> => {
    if (Platform.OS === 'android' && Number(Platform.Version) >= 31 &&
      await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT) !== PermissionsAndroid.RESULTS.GRANTED) {
      setError('Bluetooth permission is required to verify the recording microphone.');
      return false;
    }
    if (Platform.OS !== 'android' && permissionGrantedRef.current) {
      return true;
    }
    const permission = await ensureRecordingPermission();
    permissionGrantedRef.current = permission.granted;
    if (mountedRef.current) {
      setPermissionReady(permission.granted);
      if (!permission.granted) {
        setError('Microphone permission denied.');
      }
    }
    return permission.granted;
  }, []);

  const uploadRecordedUri = useCallback(async (uri: string, sendToChat: boolean, canSubmit: () => boolean, receipt?: PhoneReplyReceipt, work?:ManualWork) => {
    let recordingBytes = 0;
    let sttUploadStartedAtMs = 0;
    let sttUploadCompleted = false;
    const uploadOptions = work?.options??optionsRef.current;
    const transcriptSubmission = work ? work.submission : sendToChat && modeRef.current === 'manual'
      ? uploadOptions.prepareTranscriptSubmission?.() : undefined;
    if (transcriptSubmission) sendToChat = false;
    const optIn = uploadOptions.phoneReplyControls === true && sendToChat;
    const captureEpoch = captureEpochRef.current;
    let pending: ReturnType<NonNullable<RecorderOptions['beginPhoneReplySubmission']>> | undefined;
    let pendingSettled = false;
    const ownsUpload = () => mountedRef.current && connectedRef.current && captureEpoch === captureEpochRef.current
      && clientRef.current === client && (!pending || pending.isCurrent());
    try {
      if (!canSubmit()) {
        return;
      }
      const info = await FileSystem.getInfoAsync(uri);
      recordingBytes = info.exists && typeof info.size === 'number' ? info.size : 0;
      if (info.exists && typeof info.size === 'number' && info.size > MAX_STT_UPLOAD_BYTES) {
        throw new Error(`Recording is too large for phone voice reply. Keep clips under ${MAX_STT_UPLOAD_MB} MB.`);
      }
      const audioBase64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      // A stop/disconnect can happen while the native file is being read. Once
      // client.stt starts, the request belongs to NC and cannot be recalled here.
      if (!canSubmit()) {
        return;
      }
      sttUploadStartedAtMs = Date.now();
      void recordPhoneDebug('info', 'stt_upload_started', {
        started_at_ms: sttUploadStartedAtMs,
        recording_bytes: recordingBytes,
        send_to_chat: sendToChat,
        live_mic: liveEnabledRef.current,
      });
      const auth = optIn ? await uploadOptions.getPhoneReplyAuth?.() : undefined;
      if (!canSubmit() || (optIn && !ownsUpload())) return;
      if (optIn && !auth) throw new Error('Phone reply authorization unavailable.');
      const submissionId = `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      const fixedOptions = {
        ...uploadOptions.sendOptions,
        sendToChat,
        ...(auth ? { phoneReplyAuth: auth, phoneInterruption: receipt, phoneSubmissionId: receipt ? undefined : submissionId } : {}),
      };
      const operation = () => {
        work?.permit.assertSend();if(work&&sendToChat)work.uncertain=true;
        return client.stt(audioBase64, fileExtensionFromUri(uri), fixedOptions);
      };
      work?.permit.assertSend(); // Local departure denial is not a lost network ACK.
      const retryOwned=()=>{
        if(!ownsUpload())return false;
        try{work?.permit.assertSend();return true;}catch{return false;}
      };
      if (auth) pending = uploadOptions.beginPhoneReplySubmission?.();
      const result = await (auth ? retryPhoneReply(operation, retryOwned) : operation());
      if (auth && !ownsUpload()) return;
      const requestId = phoneReplyRequestId(result);
      if (auth) {
        if (pending) { pending.settle(requestId, auth); pendingSettled = true; }
        else if (requestId) uploadOptions.onPhoneReplySubmitted?.(requestId, auth);
      }
      const errorMessage = remoteActionError(result, 'Voice reply was not accepted.');
      const completedAtMs = Date.now();
      const transcriptText = resultText(result);
      sttUploadCompleted = true;
      void recordPhoneDebug(errorMessage ? 'error' : 'info', 'stt_upload_completed', {
        completed_at_ms: completedAtMs,
        upload_and_stt_ms: Math.max(0, completedAtMs - sttUploadStartedAtMs),
        recording_bytes: recordingBytes,
        send_to_chat: sendToChat,
        accepted: !errorMessage,
        transcript_chars: transcriptText.length,
        live_mic: liveEnabledRef.current,
        error: errorMessage,
      });
      if (errorMessage) {
        if(work)work.uncertain=false; // A received rejection is not a lost acknowledgement.
        throw new Error(errorMessage);
      }
      if (transcriptSubmission && transcriptText && canSubmit() && ownsUpload()) {
        work?.permit.assertSend();
        await transcriptSubmission(transcriptText);
      } else if (!transcriptSubmission && !sendToChat && transcriptText && mountedRef.current) {
        setTranscript(transcriptText);
      }
    } catch (exc) {
      if(work&&!isUncertainPhoneReplyError(exc))work.uncertain=false;
      if (ownsUpload() && phoneReplyErrorCode(exc) === 'phone_reply_authentication') void uploadOptions.getPhoneReplyAuth?.(true).catch(() => undefined);
      pending?.fail(exc); pendingSettled = true;
      if (sttUploadStartedAtMs && !sttUploadCompleted) {
        void recordPhoneDebug('error', 'stt_upload_completed', {
          completed_at_ms: Date.now(),
          upload_and_stt_ms: Math.max(0, Date.now() - sttUploadStartedAtMs),
          recording_bytes: recordingBytes,
          send_to_chat: sendToChat,
          accepted: false,
          transcript_chars: 0,
          live_mic: liveEnabledRef.current,
          error: exc instanceof Error ? exc.message : 'Recording upload failed.',
        });
      }
      throw exc;
    } finally {
      // A cancelled/stale upload can finish without throwing or adopting its
      // ACK. The App still bounds any uncertain dispatch under its old scope.
      if (!pendingSettled) pending?.fail(new Error('Phone reply acknowledgement ownership ended.'));
    }
  }, [client]);

  const clearManualWork=useCallback(async(work:ManualWork,sent=false)=>{
    void recordPhoneDebug('info','manual_recording_settled',{sent,uncertain:work.uncertain});
    if(manualWorkRef.current===work){manualWorkRef.current=null;manualIdRef.current=null;setPendingRecording(null);}
    if(!sent&&work.receipt)void Promise.resolve(work.options.onPhoneReplyAbandon?.(work.receipt)).catch(()=>undefined);
    manualDeparture.release(work.id);
    if(work.uri)await FileSystem.deleteAsync(work.uri,{idempotent:true}).catch(()=>undefined);
  },[]);
  const makeManualWork=useCallback((uri:string,sendToChat:boolean,receipt?:PhoneReplyReceipt):ManualWork=>{
    const id=manualIdRef.current!,epoch=captureEpochRef.current,scope=optionsRef.current.manualScope;
    const work:ManualWork={id,epoch,scope,native:true,uri,sendToChat,receipt,claimed:false,explicit:false,uncertain:false,retainedRevision:-1,
      options:optionsRef.current,permit:{isCurrent:()=>mountedRef.current&&connectedRef.current&&clientRef.current===client
        &&captureEpochRef.current===epoch&&optionsRef.current.manualScope===scope,
        assertSend:()=>{
          if(!work.permit.isCurrent())throw Error('The recording conversation changed.');
          const state=manualDeparture.state(id);
          if(state?.error)throw new RetainManualRecording();
          if(work.explicit){if(!foregroundRef.current||!manualDeparture.canSend(id))throw new RetainManualRecording();return;}
          if(state?.departed){
            if(state.reason!=='app_switch'||!manualDeparture.canSend(id))throw new RetainManualRecording();
            if(!work.claimed){if(!manualDeparture.claim(id,state.revision))throw new RetainManualRecording();work.claimed=true;}
          }else if(!foregroundRef.current)throw new RetainManualRecording();
        },markDispatched:()=>{work.uncertain=true;}}};
    work.submission=sendToChat?work.options.prepareTranscriptSubmission?.(work.permit):undefined;
    return work;
  },[client]);
  const retainManualWork=useCallback((work:ManualWork)=>{
    work.retainedRevision=manualDeparture.state(work.id)?.revision??-1;
    manualWorkRef.current=work;setPendingRecording({id:work.id,canSend:!work.uncertain});
    void recordPhoneDebug('info','manual_recording_retained',{reason:manualDeparture.state(work.id)?.reason??'unknown',uncertain:work.uncertain});
  },[]);
  const sendPendingRecording=useCallback(async(automatic=false)=>{
    const work=manualWorkRef.current;if(!work||busyRef.current||transitionRef.current||work.uncertain)return;
    if(!work.permit.isCurrent()){await clearManualWork(work);return;}
    if(!automatic&&!foregroundRef.current)return;
    work.explicit=!automatic;setRecorderBusy(true);transitionRef.current=true;
    try{await uploadRecordedUri(work.uri,work.sendToChat,work.permit.isCurrent,work.receipt,work);await clearManualWork(work,true);setError('');}
    catch(error){retainManualWork(work);setError(error instanceof Error?error.message:'Recording could not be sent.');}
    finally{setRecorderBusy(false);transitionRef.current=false;transitionWaitersRef.current.splice(0).forEach(resolve=>resolve());}
  },[clearManualWork,retainManualWork,setRecorderBusy,uploadRecordedUri]);
  const discardPendingRecording=useCallback(async()=>{
    const work=manualWorkRef.current;if(work&&!busyRef.current){await clearManualWork(work);setError('');}
  },[clearManualWork]);

  const releaseRecording = useCallback(async () => {
    const lease = captureLeaseRef.current;
    // An idle/stale recorder must never stop a different input owner.
    if (requiresCaptureLease() && !lease) return;
    await recorder.stop();
    if (lease) {
      // Configure while still owning input, outside release's serialized callback.
      await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: false }, lease);
      await releaseCapture(lease, async () => undefined);
      captureLeaseRef.current = undefined;
    }
    captureReleasedRef.current = true;
  }, [recorder]);

  const finishCurrentRecording = useCallback(async ({
    upload,
    sendToChat,
    unavailableMessage = '',
  }: FinishOptions) => {
    if (transitionRef.current || modeRef.current === 'idle') {
      return;
    }
    transitionRef.current = true;
    const finishedMode = modeRef.current;
    const frozenReply = frozenReplyRef.current;
    frozenReplyRef.current = undefined;
    if (!upload && frozenReply) void Promise.resolve(optionsRef.current.onPhoneReplyAbandon?.(frozenReply)).catch(() => undefined);
    const captureEpoch = captureEpochRef.current;
    const liveSession = liveSessionRef.current;
    const canSubmit = () => mountedRef.current && captureEpochRef.current === captureEpoch && clientRef.current === client && connectedRef.current && voiceAvailableRef.current
      && (finishedMode !== 'live' || (liveEnabledRef.current && liveSessionRef.current === liveSession
        && foregroundRef.current && !optionsRef.current.livePauseReason));
    clearStopTimer();
    if (upload) {
      setRecorderBusy(true);
      if (finishedMode === 'live') {
        setLivePhase('listening');
      }
    }
    let recordedUri = '';
    let work:ManualWork|undefined,retained=false;
    try {
      // Capture conversation/photo before releasing hardware or yielding.
      if(finishedMode==='manual'&&manualIdRef.current&&upload)work=makeManualWork('',
        typeof sendToChat==='boolean'?sendToChat:optionsRef.current.sendToChat!==false,frozenReply);
      await observeWait('capture.release',releaseRecording());
      const uri = (manualIdRef.current?manualDeparture.state(manualIdRef.current)?.uri:null)??recorder.uri;
      if (!uri) {
        if (upload) {
          throw new Error('No recording URI returned.');
        }
        return;
      }
      recordedUri = uri;
      if(work)work.uri=uri;
      if (!upload) {
        if (unavailableMessage) {
          setError(unavailableMessage);
        }
        return;
      }
      await observeWait('capture.upload',uploadRecordedUri(
        uri,
        typeof sendToChat === 'boolean' ? sendToChat : optionsRef.current.sendToChat !== false,
        canSubmit,
        frozenReply,
        work,
      ));
    } catch (exc) {
      if(work?.uri&&work.permit.isCurrent()){retainManualWork(work);retained=true;}
      const message = exc instanceof Error ? exc.message : 'Recording upload failed.';
      if (mountedRef.current && (finishedMode !== 'live' || liveSessionRef.current === liveSession)) {
        setError(message);
      }
      if (finishedMode === 'live' && liveSessionRef.current === liveSession) {
        setLiveSessionEnabled(false);
      }
    } finally {
      if (recordedUri&&!retained) {
        await FileSystem.deleteAsync(recordedUri, { idempotent: true }).catch(() => undefined);
      }
      if(!retained&&manualIdRef.current){manualDeparture.release(manualIdRef.current);manualIdRef.current=null;}
      if (upload) {
        setRecorderBusy(false);
      }
      if (!requiresCaptureLease()) {
        await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: liveEnabledRef.current }).catch(() => undefined);
      }
      activeRecordingUriRef.current = null;
      transitionRef.current = false;
      setRecorderMode('idle');
      setCaptureRevision((revision) => revision + 1);
      transitionWaitersRef.current.splice(0).forEach((resolve) => resolve());
    }
  }, [
    client,
    clearStopTimer,
    recorder,
    releaseRecording,
    setLiveSessionEnabled,
    setRecorderBusy,
    setRecorderMode,
    uploadRecordedUri,
    makeManualWork,retainManualWork,
  ]);

  const beginRecording = useCallback(async (nextMode: Exclude<RecorderMode, 'idle'>) => {
    if (transitionRef.current || modeRef.current !== 'idle' || busyRef.current || manualWorkRef.current) {
      return;
    }
    if (captureLeaseRef.current) {
      setError('The previous microphone could not be released. Restart the phone app before retrying.');
      if (nextMode === 'live') setLiveSessionEnabled(false);
      return;
    }
    transitionRef.current = true;
    const liveSession = liveSessionRef.current;
    const captureEpoch = captureEpochRef.current;
    setError('');
    let started = false;
    let prepared = false;
    let prepareAttempted = false;
    const requiresLease = Platform.OS === 'ios' || androidContinuousCaptureRuntimeEnabled();
    try {
      if (requiresCaptureLease()) {
        captureLeaseRef.current = await acquireCapture('manual');
        captureReleasedRef.current = false;
        if (!mountedRef.current || captureEpochRef.current !== captureEpoch || !foregroundRef.current || !connectedRef.current || !voiceAvailableRef.current) return;
      }
      await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: true }, captureLeaseRef.current);
      if (requiresCaptureLease() && (!mountedRef.current || captureEpochRef.current !== captureEpoch
        || !foregroundRef.current || !connectedRef.current || !voiceAvailableRef.current)) return;
      prepareAttempted = true;
      await recorder.prepareToRecordAsync(
        nextMode === 'live' ? LIVE_RECORDING_OPTIONS : MANUAL_RECORDING_OPTIONS,
      );
      prepared = true;
      captureReleasedRef.current = false;
      if (!mountedRef.current || captureEpochRef.current !== captureEpoch || !foregroundRef.current || !connectedRef.current || !voiceAvailableRef.current) {
        return;
      }
      if (nextMode === 'live') {
        if (!liveEnabledRef.current || liveSessionRef.current !== liveSession || optionsRef.current.livePauseReason) {
          return;
        }
        liveDetectorRef.current = createLiveMicDetector(liveDetectorRef.current.noiseFloorDb);
        setLivePhase('listening');
      }
      if(nextMode==='manual'){
        const id=`manual-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        if(manualDeparture.begin(recorder,id))manualIdRef.current=id;
      }
      if (Platform.OS === 'android') {
        await (recorder as unknown as {ncRecordPrepared():Promise<void>}).ncRecordPrepared();
        if (!mountedRef.current || captureEpochRef.current !== captureEpoch || !foregroundRef.current || !connectedRef.current || !voiceAvailableRef.current) return;
      } else recorder.record();
      activeRecordingUriRef.current = recorder.uri;
      started = true;
      if (nextMode === 'manual') {
        clearStopTimer();
        stopTimerRef.current = setTimeout(() => {
          const canUpload = connectedRef.current && voiceAvailableRef.current;
          void finishCurrentRecording({
            upload: canUpload,
            unavailableMessage: !connectedRef.current
              ? 'Recording reached 60 seconds. Reconnect before sending voice.'
              : 'Recording reached 60 seconds. Phone voice reply is unavailable with the selected NC STT backend.',
          });
        }, MAX_RECORDING_MS);
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Could not start recording.');
      if (nextMode === 'live' && liveSessionRef.current === liveSession) {
        setLiveSessionEnabled(false);
      }
    } finally {
      if (!started) {
        if (prepared || (requiresCaptureLease() && prepareAttempted)) {
          // Android retains a prepared MediaRecorder until stop releases it,
          // even if Live Mode was cancelled before record() could be called.
          await releaseRecording().catch(() => undefined);
          if (recorder.uri) {
            await FileSystem.deleteAsync(recorder.uri, { idempotent: true }).catch(() => undefined);
          }
        }
        if (!prepareAttempted && captureLeaseRef.current) {
          const lease = captureLeaseRef.current;
          try {
            await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: false }, lease);
            await releaseCapture(lease, async () => undefined);
            captureLeaseRef.current = undefined;
            captureReleasedRef.current = true;
          } catch {
            if (mountedRef.current) setError('Could not restore the playback audio session. Restart the phone app before retrying.');
          }
        }
        if (!requiresCaptureLease()) {
          await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: liveEnabledRef.current }).catch(() => undefined);
        }
        if(manualIdRef.current){manualDeparture.release(manualIdRef.current);manualIdRef.current=null;}
      }
      transitionRef.current = false;
      setRecorderMode(started ? nextMode : 'idle');
      setCaptureRevision((revision) => revision + 1);
      transitionWaitersRef.current.splice(0).forEach((resolve) => resolve());
    }
  }, [
    clearStopTimer,
    finishCurrentRecording,
    recorder,
    releaseRecording,
    setLiveSessionEnabled,
    setRecorderMode,
  ]);

  const stopLiveSession = useCallback(async (message = '') => {
    setLiveSessionEnabled(false);
    if (message) {
      setError(message);
    }
    if (modeRef.current === 'live') {
      await finishCurrentRecording({ upload: false });
    } else if (!transitionRef.current && !requiresCaptureLease()) {
      await configurePhoneAudio({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
    }
  }, [finishCurrentRecording, setLiveSessionEnabled]);

  const cancelCapture = useCallback(async () => {
    captureEpochRef.current++;
    setLiveSessionEnabled(false);
    const waitForTransition = () => transitionRef.current
      ? new Promise<void>((resolve) => { transitionWaitersRef.current.push(resolve); })
      : Promise.resolve();
    await waitForTransition();
    if(manualWorkRef.current)await clearManualWork(manualWorkRef.current);
    await finishCurrentRecording({ upload: false });
    await waitForTransition();
    if (!captureReleasedRef.current) {
      throw new Error('The previous microphone could not be released. Close other microphone apps and restart the phone app.');
    }
  }, [finishCurrentRecording, setLiveSessionEnabled,clearManualWork]);

  useEffect(()=>{
    if(Platform.OS!=='android')return;
    if(!connected)void cancelCapture().catch(()=>undefined);
    return()=>{void cancelCapture().catch(()=>undefined);};
  },[client,connected,options.manualScope]);
  cancelCaptureRef.current = cancelCapture;

  useEffect(() => {
    if (!liveEnabled) {
      return;
    }
    if (!connected || !voiceAvailable) {
      void stopLiveSession(
        !connected
          ? 'Live Mic stopped because the phone disconnected.'
          : 'Live Mic stopped because phone voice input became unavailable.',
      );
    }
  }, [connected, liveEnabled, stopLiveSession, voiceAvailable]);

  useEffect(() => {
    if (!liveEnabled || !permissionReady) {
      return;
    }
    if (options.livePauseReason || busy) {
      if (modeRef.current === 'live') {
        void finishCurrentRecording({ upload: false });
      }
      return;
    }
    if (mode === 'idle' && !transitionRef.current) {
      void beginRecording('live');
    }
  }, [beginRecording, busy, captureRevision, finishCurrentRecording, liveEnabled, mode, options.livePauseReason, permissionReady]);

  useEffect(() => {
    if (
      !liveEnabled
      || mode !== 'live'
      || !recorderState.isRecording
      || transitionRef.current
      || options.livePauseReason
      || (recorderState.url && activeRecordingUriRef.current && recorderState.url !== activeRecordingUriRef.current)
    ) {
      return;
    }
    const previousPhase = liveDetectorRef.current.phase;
    const result = advanceLiveMicDetector(liveDetectorRef.current, {
      elapsedMs: recorderState.durationMillis,
      meteringDb: recorderState.metering,
      playbackActive: optionsRef.current.playbackActive,
    });
    liveDetectorRef.current = result.state;
    setLivePhase(result.state.phase);
    if (previousPhase === 'listening' && result.state.phase === 'speech') {
      try {
        if (optionsRef.current.phoneReplyControls) {
          frozenReplyRef.current = optionsRef.current.freezePhoneReply?.() ?? undefined;
          void Promise.resolve(optionsRef.current.onPhoneReplyOnset?.(frozenReplyRef.current)).catch(() =>
            setError('Phone interruption acknowledgement is pending.'));
        } else {
        const interruption = optionsRef.current.onLiveSpeechStart?.();
        if (interruption) {
          void Promise.resolve(interruption).catch((exc) => {
            const message = exc instanceof Error ? exc.message : 'Could not interrupt the current NC response.';
            setError(message);
            void recordPhoneDebug('error', 'live_mic_interrupt_failed', { error: message });
          });
        }
        }
      } catch (exc) {
        const message = exc instanceof Error ? exc.message : 'Could not interrupt the current NC response.';
        setError(message);
        void recordPhoneDebug('error', 'live_mic_interrupt_failed', { error: message });
      }
    }
    if (result.decision === 'rotate') {
      void finishCurrentRecording({ upload: false });
    } else if (result.decision === 'upload') {
      void finishCurrentRecording({ upload: true, sendToChat: true });
    }
  }, [
    finishCurrentRecording,
    liveEnabled,
    mode,
    options.livePauseReason,
    options.playbackActive,
    recorderState.durationMillis,
    recorderState.isRecording,
    recorderState.metering,
    recorderState.url,
  ]);

  useEffect(() => {
    let lastDeparture='';
    const observe=()=>{
      const id=manualIdRef.current;if(!id)return;
      const state=manualDeparture.state(id);if(!state?.departed)return;
      const signature=`${id}:${state.revision}`;
      if(signature!==lastDeparture){lastDeparture=signature;
        void recordPhoneDebug('info','manual_recording_departure',{revision:state.revision,reason:state.reason,
          stopped:state.stopped,has_file:Boolean(state.uri),stop_failed:Boolean(state.error)});
      }
      if(modeRef.current==='manual')void finishCurrentRecording({upload:true});
      else if(manualWorkRef.current&&state.reason==='app_switch'
        &&state.revision>manualWorkRef.current.retainedRevision)
        void sendPendingRecording(true);
    };
    const native=manualDeparture.subscribe(observe);
    observe(); // Replay native classification that arrived during finalization.
    const subscription = AppState.addEventListener('change', (nextState) => {
      foregroundRef.current = nextState === 'active';
      observe();
      if (nextState !== 'active' && liveEnabledRef.current) {
        void stopLiveSession('Live Mic stopped when the app left the foreground.');
      }
    });
    return () => {subscription.remove();native.remove();};
  }, [stopLiveSession,finishCurrentRecording,sendPendingRecording,captureRevision]);

  const liveStatus = !liveEnabled
    ? 'Off'
    : error
      ? error
      : options.livePauseReason
        ? options.livePauseReason
        : busy
          ? 'Transcribing and sending...'
          : !permissionReady
            ? 'Waiting for microphone permission...'
            : mode === 'idle'
              ? 'Starting microphone...'
              : livePhase === 'speech'
                ? 'Hearing you...'
                : 'Listening...';

  return {
    pendingRecording,sendPendingRecording:()=>sendPendingRecording(),discardPendingRecording,
    cancelCapture,
    recording: mode === 'manual' && recorderState.isRecording,
    busy,
    error,
    transcript,
    clearTranscript: () => setTranscript(''),
    liveEnabled,
    liveStatus,
    meteringDb: recorderState.metering,
    meteringRevision: recorderState.durationMillis,
    livePhase,
    pauseLiveForPlayback: async () => undefined,
    toggleLive: async () => {
      if(manualWorkRef.current){setError('Send or discard the retained recording first.');return;}
      if (liveEnabledRef.current) {
        await stopLiveSession();
        return;
      }
      if (modeRef.current === 'manual' || busyRef.current) {
        setError('Finish the current voice recording before starting Live Mic.');
        return;
      }
      if (!connected) {
        setError('Connect before starting Live Mic.');
        return;
      }
      if (!voiceAvailable) {
        setError('Phone voice reply is unavailable with the selected NC STT backend.');
        return;
      }
      try {
        setError('');
        // Arm before requesting permission so a second tap or background event
        // can cancel a permission dialog that has not resolved yet.
        setLiveSessionEnabled(true);
        const liveSession = liveSessionRef.current;
        if (!await ensurePermission()) {
          if (liveSessionRef.current === liveSession) {
            setLiveSessionEnabled(false);
          }
          return;
        }
        if (!mountedRef.current || !liveEnabledRef.current || liveSessionRef.current !== liveSession) {
          return;
        }
        if (!foregroundRef.current || !connectedRef.current || !voiceAvailableRef.current) {
          await stopLiveSession();
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Could not start Live Mic.');
        setLiveSessionEnabled(false);
      }
    },
    toggleRecording: async () => {
      rememberCaptureControl(busyRef.current || liveEnabledRef.current ? 'manual_blocked'
        : modeRef.current === 'manual' ? 'manual_send' : 'manual_start');
      if (busyRef.current) {
        return;
      }
      if (liveEnabledRef.current) {
        setError('Stop Live Mic before using the manual Mic button.');
        return;
      }
      if (modeRef.current === 'manual') {
        const canUpload = connected && voiceAvailable;
        await finishCurrentRecording({
          upload: canUpload,
          unavailableMessage: !connected
            ? 'Recording stopped. Reconnect before sending voice.'
            : 'Recording stopped. Phone voice reply is unavailable with the selected NC STT backend.',
        });
        return;
      }
      if (!connected) {
        setError('Connect before recording voice.');
        return;
      }
      if (!voiceAvailable) {
        setError('Phone voice reply is unavailable with the selected NC STT backend.');
        return;
      }
      try {
        const captureEpoch = captureEpochRef.current;
        if (await ensurePermission() && captureEpochRef.current === captureEpoch) {
          await beginRecording('manual');
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Could not start recording.');
      }
    },
  };
}
