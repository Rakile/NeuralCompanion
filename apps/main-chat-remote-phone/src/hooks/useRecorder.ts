import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import {
  AudioModule,
  RecordingPresets,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import * as FileSystem from 'expo-file-system/legacy';

import { RemoteClient } from '../api/client';
import type { SendTextOptions } from '../api/client';
import { remoteActionError } from '../api/envelope';
import {
  advanceLiveMicDetector,
  createLiveMicDetector,
} from '../utils/liveMicPolicy';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { fileExtensionFromUri } from '../utils/url';

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

type RecorderMode = 'idle' | 'manual' | 'live';
type LivePhase = 'off' | 'listening' | 'speech';

type RecorderOptions = {
  sendToChat?: boolean;
  sendOptions?: SendTextOptions;
  livePauseReason?: string;
  playbackActive?: boolean;
  onLiveSpeechStart?: () => Promise<void> | void;
};

type FinishOptions = {
  upload: boolean;
  sendToChat?: boolean;
  unavailableMessage?: string;
};

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
  const recorder = useAudioRecorder(MANUAL_RECORDING_OPTIONS);
  const recorderState = useAudioRecorderState(recorder, LIVE_METER_INTERVAL_MS);
  const [mode, setMode] = useState<RecorderMode>('idle');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [transcript, setTranscript] = useState('');
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [livePhase, setLivePhase] = useState<LivePhase>('off');
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectedRef = useRef(connected);
  const voiceAvailableRef = useRef(voiceAvailable);
  const optionsRef = useRef(options);
  const modeRef = useRef<RecorderMode>('idle');
  const busyRef = useRef(false);
  const liveEnabledRef = useRef(false);
  const transitionRef = useRef(false);
  const permissionGrantedRef = useRef(false);
  const liveDetectorRef = useRef(createLiveMicDetector());

  const setRecorderMode = useCallback((nextMode: RecorderMode) => {
    modeRef.current = nextMode;
    setMode(nextMode);
  }, []);

  const setRecorderBusy = useCallback((nextBusy: boolean) => {
    busyRef.current = nextBusy;
    setBusy(nextBusy);
  }, []);

  const setLiveSessionEnabled = useCallback((enabled: boolean) => {
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

  useEffect(() => () => clearStopTimer(), [clearStopTimer]);

  const ensurePermission = useCallback(async (): Promise<boolean> => {
    if (permissionGrantedRef.current) {
      return true;
    }
    const permission = await AudioModule.requestRecordingPermissionsAsync();
    permissionGrantedRef.current = permission.granted;
    if (!permission.granted) {
      setError('Microphone permission denied.');
    }
    return permission.granted;
  }, []);

  const uploadRecordedUri = useCallback(async (uri: string, sendToChat: boolean) => {
    let recordingBytes = 0;
    let sttUploadStartedAtMs = 0;
    let sttUploadCompleted = false;
    try {
      const info = await FileSystem.getInfoAsync(uri);
      recordingBytes = info.exists && typeof info.size === 'number' ? info.size : 0;
      if (info.exists && typeof info.size === 'number' && info.size > MAX_STT_UPLOAD_BYTES) {
        throw new Error(`Recording is too large for phone voice reply. Keep clips under ${MAX_STT_UPLOAD_MB} MB.`);
      }
      const audioBase64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      sttUploadStartedAtMs = Date.now();
      void recordPhoneDebug('info', 'stt_upload_started', {
        started_at_ms: sttUploadStartedAtMs,
        recording_bytes: recordingBytes,
        send_to_chat: sendToChat,
        live_mic: liveEnabledRef.current,
      });
      const result = await client.stt(audioBase64, fileExtensionFromUri(uri), {
        ...optionsRef.current.sendOptions,
        sendToChat,
      });
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
        throw new Error(errorMessage);
      }
      if (!sendToChat && transcriptText) {
        setTranscript(transcriptText);
      }
    } catch (exc) {
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
    }
  }, [client]);

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
    clearStopTimer();
    if (upload) {
      setRecorderBusy(true);
      if (finishedMode === 'live') {
        setLivePhase('listening');
      }
    }
    let recordedUri = '';
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) {
        if (upload) {
          throw new Error('No recording URI returned.');
        }
        return;
      }
      recordedUri = uri;
      if (!upload) {
        if (unavailableMessage) {
          setError(unavailableMessage);
        }
        return;
      }
      await uploadRecordedUri(
        uri,
        typeof sendToChat === 'boolean' ? sendToChat : optionsRef.current.sendToChat !== false,
      );
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : 'Recording upload failed.';
      setError(message);
      if (finishedMode === 'live') {
        setLiveSessionEnabled(false);
      }
    } finally {
      if (recordedUri) {
        await FileSystem.deleteAsync(recordedUri, { idempotent: true }).catch(() => undefined);
      }
      if (upload) {
        setRecorderBusy(false);
      }
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
      transitionRef.current = false;
      setRecorderMode('idle');
    }
  }, [
    clearStopTimer,
    recorder,
    setLiveSessionEnabled,
    setRecorderBusy,
    setRecorderMode,
    uploadRecordedUri,
  ]);

  const beginRecording = useCallback(async (nextMode: Exclude<RecorderMode, 'idle'>) => {
    if (transitionRef.current || modeRef.current !== 'idle' || busyRef.current) {
      return;
    }
    transitionRef.current = true;
    setError('');
    let started = false;
    try {
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
      await recorder.prepareToRecordAsync(
        nextMode === 'live' ? LIVE_RECORDING_OPTIONS : MANUAL_RECORDING_OPTIONS,
      );
      if (nextMode === 'live') {
        liveDetectorRef.current = createLiveMicDetector(liveDetectorRef.current.noiseFloorDb);
        setLivePhase('listening');
        if (!liveEnabledRef.current || optionsRef.current.livePauseReason) {
          return;
        }
      }
      recorder.record();
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
      if (nextMode === 'live') {
        setLiveSessionEnabled(false);
      }
    } finally {
      if (!started) {
        await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
      }
      transitionRef.current = false;
      setRecorderMode(started ? nextMode : 'idle');
    }
  }, [
    clearStopTimer,
    finishCurrentRecording,
    recorder,
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
    } else {
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
    }
  }, [finishCurrentRecording, setLiveSessionEnabled]);

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
    if (!liveEnabled) {
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
  }, [beginRecording, busy, finishCurrentRecording, liveEnabled, mode, options.livePauseReason]);

  useEffect(() => {
    if (
      !liveEnabled
      || mode !== 'live'
      || !recorderState.isRecording
      || transitionRef.current
      || options.livePauseReason
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
        const interruption = optionsRef.current.onLiveSpeechStart?.();
        if (interruption) {
          void Promise.resolve(interruption).catch((exc) => {
            const message = exc instanceof Error ? exc.message : 'Could not interrupt the current NC response.';
            setError(message);
            void recordPhoneDebug('error', 'live_mic_interrupt_failed', { error: message });
          });
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
  ]);

  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      if (nextState !== 'active' && liveEnabledRef.current) {
        void stopLiveSession('Live Mic stopped when the app left the foreground.');
      }
    });
    return () => subscription.remove();
  }, [stopLiveSession]);

  const liveStatus = !liveEnabled
    ? 'Off'
    : error
      ? error
      : options.livePauseReason
        ? options.livePauseReason
        : busy
          ? 'Transcribing and sending...'
          : livePhase === 'speech'
            ? 'Hearing you...'
            : 'Listening...';

  return {
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
        if (!await ensurePermission()) {
          return;
        }
        setError('');
        setLiveSessionEnabled(true);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Could not start Live Mic.');
        setLiveSessionEnabled(false);
      }
    },
    toggleRecording: async () => {
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
        if (await ensurePermission()) {
          await beginRecording('manual');
        }
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : 'Could not start recording.');
      }
    },
  };
}
