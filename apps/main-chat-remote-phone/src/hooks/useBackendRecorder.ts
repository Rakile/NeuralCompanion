import { useCallback, useEffect, useRef, useState } from 'react';
import { Platform } from 'react-native';

import type { RemoteClient } from '../api/client';
import { androidBackgroundLivePlatformEligible, androidContinuousCaptureEnabled, completeAndroidContinuousCaptureCapabilities,
  androidContinuousCaptureRuntimeEnabled, iosContinuousCaptureEnabled,
  setAndroidContinuousCaptureRuntimeReady } from '../native/iosContinuousCapturePolicy';
import { getIosLiveCapture } from '../native/iosLiveCapture';
import type { CaptureCapabilities, CaptureDuckingLevel } from '../native/iosLiveCapture';
import { useIosLiveMic } from './useIosLiveMic';
import type { BackgroundLiveOptions } from './useIosLiveMic';
import { useRecorder } from './useRecorder';
import type { RecorderOptions } from './useRecorder';
import {noteCleanupFailure} from '../utils/cleanupFailureProvenance';

export function useBackendRecorder(
  client: RemoteClient,
  connected: boolean,
  voiceAvailable = true,
  options: RecorderOptions & BackgroundLiveOptions & { liveDuckingLevel?: CaptureDuckingLevel; liveMicSensitivity?: number } = {},
) {
  const manual = useRecorder(client, connected, voiceAvailable, options);
  const [androidValidated, setAndroidValidated] = useState(false);
  const [, reviseAndroidReadiness] = useState(0);
  const manualOwnsCapture = Boolean(manual.recording || manual.busy);
  const manualOwnsCaptureRef = useRef(manualOwnsCapture);
  manualOwnsCaptureRef.current = manualOwnsCapture;
  useEffect(() => {
    if (!androidContinuousCaptureEnabled) return;
    let alive = true;
    getIosLiveCapture().capabilities().then((capabilities: CaptureCapabilities) => {
      if (!alive) return;
      const validated = completeAndroidContinuousCaptureCapabilities(capabilities);
      const ready = validated && !manualOwnsCaptureRef.current;
      setAndroidValidated(validated);
      setAndroidContinuousCaptureRuntimeReady(ready);
      reviseAndroidReadiness(value => value + 1);
    }).catch(() => { if (alive) { setAndroidValidated(false); setAndroidContinuousCaptureRuntimeReady(false); } });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!androidContinuousCaptureEnabled) return;
    if (androidValidated && !manualOwnsCapture && !androidContinuousCaptureRuntimeEnabled()) {
      setAndroidContinuousCaptureRuntimeReady(true);
      reviseAndroidReadiness(value => value + 1);
    }
  }, [androidValidated, manualOwnsCapture]);
  useEffect(() => () => { setAndroidContinuousCaptureRuntimeReady(false); }, []);
  const continuousEnabled = iosContinuousCaptureEnabled
    || (Platform.OS === 'android' && androidContinuousCaptureRuntimeEnabled() && !manualOwnsCapture);
  const continuous = useIosLiveMic(client, connected, voiceAvailable, {
    ...options,
    ...(Platform.OS === 'android' ? { allowBackgroundLive: continuousEnabled
      && androidBackgroundLivePlatformEligible() && options.allowBackgroundLive === true } : {}),
    identityKey: client.identityKey,
    enabled: continuousEnabled,
  });
  const liveStarting = useRef(false);
  const liveStartEpoch = useRef(0);
  const latest = useRef({ client, connected, voiceAvailable, options });
  latest.current = { client, connected, voiceAvailable, options };

  const cancelCapture = useCallback(async () => {
    liveStartEpoch.current += 1;
    let firstError: unknown;
    const drain = async (cancel: () => Promise<void>,operation:string) => {
      try {
        await cancel();
      } catch (error) {
        noteCleanupFailure(error,operation);
        firstError ??= error;
      }
    };
    await Promise.all([
      drain(manual.cancelCapture,'capture.manual.cancel'),
      drain(continuous.cancelCapture,'capture.live.cancel'),
    ]);
    if (firstError !== undefined) throw firstError;
  }, [continuous.cancelCapture, manual.cancelCapture]);

  const toggleLive = useCallback(async () => {
    if(manual.pendingRecording)return;
    if (continuous.liveEnabled) {
      liveStartEpoch.current += 1;
      await continuous.toggleLive();
      return;
    }
    const startEpoch = ++liveStartEpoch.current;
    liveStarting.current = true;
    try {
      await manual.cancelCapture();
      if (liveStartEpoch.current !== startEpoch) return;
      await continuous.toggleLive();
    } finally {
      liveStarting.current = false;
    }
  }, [continuous.liveEnabled, continuous.toggleLive, manual.cancelCapture,manual.pendingRecording]);

  const toggleRecording = useCallback(async () => {
    if(manual.pendingRecording)return;
    if (continuous.liveEnabled || liveStarting.current) return;
    if (!manual.recording) {
      const request = latest.current;
      const startEpoch = ++liveStartEpoch.current;
      await continuous.cancelCapture();
      if (startEpoch !== liveStartEpoch.current || latest.current.client !== request.client) return;
      await request.options.onBeforeLiveStart?.('manual');
      if (startEpoch !== liveStartEpoch.current || latest.current.client !== request.client
        || !latest.current.connected || !latest.current.voiceAvailable) return;
    }
    await manual.toggleRecording();
  }, [continuous.liveEnabled, continuous.cancelCapture, manual.recording, manual.toggleRecording,manual.pendingRecording]);

  if (!continuousEnabled) return manual;

  const metering = continuous.liveEnabled ? continuous : manual;
  return {
    pendingRecording:manual.pendingRecording,sendPendingRecording:manual.sendPendingRecording,
    discardPendingRecording:manual.discardPendingRecording,
    cancelCapture,
    isBackgroundSessionReady: continuous.isBackgroundSessionReady,
    stopListening: continuous.stopListening,
    finishReplyOutput: continuous.finishReplyOutput,
    submitReplyTurn: continuous.submitReplyTurn,
    recording: manual.recording,
    busy: manual.busy || continuous.busy,
    error: continuous.error || manual.error,
    transcript: manual.transcript,
    clearTranscript: manual.clearTranscript,
    liveEnabled: continuous.liveEnabled,
    reconnecting: continuous.reconnecting,
    liveStatus: continuous.liveStatus,
    meteringDb: metering.meteringDb,
    meteringRevision: metering.meteringRevision,
    livePhase: continuous.livePhase,
    pauseLiveForPlayback: continuous.pauseLiveForPlayback,
    toggleLive,
    resumeLiveAfterRouteChange:continuous.resumeLiveAfterRouteChange,
    toggleRecording,
  };
}
