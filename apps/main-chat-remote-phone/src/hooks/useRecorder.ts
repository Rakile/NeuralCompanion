import { useCallback, useEffect, useRef, useState } from 'react';
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
import { fileExtensionFromUri } from '../utils/url';

const MAX_RECORDING_MS = 60_000;
const MAX_STT_UPLOAD_BYTES = 18 * 1024 * 1024;
const MAX_STT_UPLOAD_MB = Math.floor(MAX_STT_UPLOAD_BYTES / (1024 * 1024));

type RecorderOptions = {
  sendToChat?: boolean;
  sendOptions?: SendTextOptions;
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
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY!);
  const recorderState = useAudioRecorderState(recorder);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [transcript, setTranscript] = useState('');
  const stopTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectedRef = useRef(connected);
  const voiceAvailableRef = useRef(voiceAvailable);
  const optionsRef = useRef(options);

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

  const stop = useCallback(async (upload: boolean, unavailableMessage = 'Recording stopped. Reconnect before sending voice.') => {
    clearStopTimer();
    setBusy(true);
    setError('');
    let recordedUri = '';
    try {
      await recorder.stop();
      const uri = recorder.uri;
      if (!uri) {
        throw new Error('No recording URI returned.');
      }
      recordedUri = uri;
      if (!upload) {
        setError(unavailableMessage);
        return;
      }
      const info = await FileSystem.getInfoAsync(uri);
      if (info.exists && typeof info.size === 'number' && info.size > MAX_STT_UPLOAD_BYTES) {
        throw new Error(`Recording is too large for phone voice reply. Keep clips under ${MAX_STT_UPLOAD_MB} MB.`);
      }
      const audioBase64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      const sendToChat = optionsRef.current.sendToChat !== false;
      const result = await client.stt(audioBase64, fileExtensionFromUri(uri), {
        ...optionsRef.current.sendOptions,
        sendToChat,
      });
      const errorMessage = remoteActionError(result, 'Voice reply was not accepted.');
      if (errorMessage) {
        throw new Error(errorMessage);
      }
      if (!sendToChat) {
        const text = resultText(result);
        if (text) {
          setTranscript(text);
        }
      }
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : 'Recording upload failed.');
    } finally {
      if (recordedUri) {
        await FileSystem.deleteAsync(recordedUri, { idempotent: true }).catch(() => undefined);
      }
      setBusy(false);
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
    }
  }, [clearStopTimer, client, recorder]);

  const start = useCallback(async () => {
    setError('');
    try {
      const permission = await AudioModule.requestRecordingPermissionsAsync();
      if (!permission.granted) {
        setError('Microphone permission denied.');
        return;
      }
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: true });
      await recorder.prepareToRecordAsync();
      recorder.record();
      clearStopTimer();
      stopTimerRef.current = setTimeout(() => {
        const canUpload = connectedRef.current && voiceAvailableRef.current;
        stop(
          canUpload,
          !connectedRef.current
            ? 'Recording reached 60 seconds. Reconnect before sending voice.'
            : 'Recording reached 60 seconds. Phone voice reply is unavailable with the selected NC STT backend.',
        ).catch(() => undefined);
      }, MAX_RECORDING_MS);
    } catch (exc) {
      clearStopTimer();
      setError(exc instanceof Error ? exc.message : 'Could not start recording.');
      await setAudioModeAsync({ playsInSilentMode: true, allowsRecording: false }).catch(() => undefined);
    }
  }, [clearStopTimer, recorder, stop]);

  useEffect(() => {
    if (!recorderState.isRecording || (connected && voiceAvailable)) {
      return;
    }
    stop(
      false,
      !connected
        ? 'Recording stopped. Reconnect before sending voice.'
        : 'Recording stopped. Phone voice reply is unavailable with the selected NC STT backend.',
    ).catch(() => undefined);
  }, [connected, recorderState.isRecording, stop, voiceAvailable]);

  return {
    recording: recorderState.isRecording,
    busy,
    error,
    transcript,
    clearTranscript: () => setTranscript(''),
    toggleRecording: async () => {
      if (busy) {
        return;
      }
      if (recorderState.isRecording) {
        const canUpload = connected && voiceAvailable;
        await stop(
          canUpload,
          !connected
            ? 'Recording stopped. Reconnect before sending voice.'
            : 'Recording stopped. Phone voice reply is unavailable with the selected NC STT backend.',
        );
      } else {
        if (!connected) {
          setError('Connect before recording voice.');
          return;
        }
        if (!voiceAvailable) {
          setError('Phone voice reply is unavailable with the selected NC STT backend.');
          return;
        }
        await start();
      }
    },
  };
}
