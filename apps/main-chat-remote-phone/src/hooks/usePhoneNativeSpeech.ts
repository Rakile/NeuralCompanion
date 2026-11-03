import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { AudioModule } from 'expo-audio';
import type { AudioChunk, AudioMode, ChatMessage, PhoneSendEnvelope } from '../api/types';
import { phoneNativeAudio } from '../native/phoneNativeAudio';
import type { NativeCapabilities } from '../native/phoneNativeAudio';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import { acceptedNativeRequest, NativeCaptureDiagnostics, nativeReason, normalizeNativeMicSensitivity, safeNativeDiagnosticCode, safeNativeDiagnosticLanguage, splitNativeSpeech } from '../utils/phoneNativeSpeech';

type Options = {
  mode: AudioMode; identityKey: string; connected: boolean; storyActive: boolean;
  backendSupported: boolean; backendReason: string; language: string; speakerId: number;
  sensitivity?: number;
  conversationGeneration?: number;
  sendToChat: boolean; messages: ChatMessage[];
  onSendText: (text: string) => Promise<unknown>;
  releasePlayback: () => void;
  onLiveSpeechStart?: () => Promise<void>;
  onBeforeListening?: () => Promise<void>;
};
type Listening = 'off' | 'listening' | 'speech';
type Progress = { model: string; phase: string; bytes: number; totalBytes: number };
type PendingSpeech = { id: string; text: string };
const MAX_LOCAL_FILES = 8;
const MAX_PENDING_PARTS = 128;

export function usePhoneNativeSpeech(options: Options) {
  const latest = useRef(options); latest.current = options;
  const [capabilities, setCapabilities] = useState<NativeCapabilities | null>(null);
  const [probing, setProbing] = useState(false);
  const [setupOpen, setSetupOpen] = useState(false);
  const [installing, setInstalling] = useState(false);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState('');
  const [probeError, setProbeError] = useState('');
  const [chunks, setChunks] = useState<AudioChunk[]>([]);
  const [recording, setRecording] = useState(false);
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [livePhase, setLivePhase] = useState<Listening>('off');
  const [busy, setBusy] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [meteringDb, setMeteringDb] = useState<number | undefined>();
  const [meteringRevision, setMeteringRevision] = useState(0);
  const capabilitiesRef = useRef<NativeCapabilities | null>(capabilities); capabilitiesRef.current = capabilities;
  const mounted = useRef(true);
  const foreground = useRef(AppState.currentState !== 'background' && AppState.currentState !== 'inactive');
  const epoch = useRef(0), probeEpoch = useRef(0), micEpoch = useRef(0);
  const accepted = useRef(new Set<string>()), spoken = useRef(new Set<string>()), utterances = useRef(new Set<string>());
  const pending = useRef<PendingSpeech[]>([]), files = useRef<AudioChunk[]>([]);
  const owned = useRef(new Map<string, string>());
  const finished = useRef(new Set<string>());
  const synthesizing = useRef(false), installingRef = useRef(false), setupWanted = useRef(false);
  const synthesisContext = useRef<{ epoch: number; key: string } | null>(null);
  const session = useRef(''), live = useRef(false), starting = useRef(false);
  const phase = useRef<Listening>('off');
  const captureDiagnostics = useRef<NativeCaptureDiagnostics | null>(null);
  const pumpRef = useRef<() => void>(() => {});
  const collectRef = useRef<(messages: ChatMessage[]) => void>(() => {});
  const context = () => `${latest.current.identityKey}|${latest.current.mode}|${latest.current.connected}|${latest.current.storyActive}|${latest.current.language}|${latest.current.speakerId}|${latest.current.conversationGeneration}`;
  const active = () => mounted.current && foreground.current && latest.current.mode === 'phone_native'
    && latest.current.connected && !latest.current.storyActive;
  const diagnosticDetails = (kind: 'stt' | 'tts', code: unknown, stage: string,
    sessionPresent?: boolean, includeErrorCode = true) => {
    const route = capabilitiesRef.current?.[kind];
    const safeCode = safeNativeDiagnosticCode(code);
    const provider = safeCode.startsWith('offline_recognition_') ? 'android_offline'
      : route?.provider === 'android_offline' || route?.provider === 'sherpa_onnx' ? route.provider : 'unknown';
    return {
      ...(includeErrorCode ? { error_code: safeCode } : {}),
      ...(sessionPresent === undefined ? {} : { session_present: sessionPresent }),
      provider,
      language: safeNativeDiagnosticLanguage(latest.current.language || route?.language),
      stage,
    };
  };
  const recordCaptureSummary = (summary: ReturnType<NativeCaptureDiagnostics['finish']> | undefined) => {
    if (!summary) return;
    // State events lack provider identity; fallback may differ from the last probe.
    const { provider, ...details } = diagnosticDetails('stt', undefined, 'capture', undefined, false);
    void recordPhoneDebug('info', 'native_capture_summary', {
      ...details, configured_provider: provider, meter_scale: 'provider_reported', ...summary,
    });
  };
  const safeDelete = (uri: string) => { void phoneNativeAudio.deleteAudio(uri).catch(() => { if (mounted.current) setError(nativeReason('audio_delete_failed')); }); };
  const publish = () => { if (mounted.current) setChunks([...files.current]); };

  const stopSpeech = useCallback((keepLatest: boolean) => {
    epoch.current++;
    accepted.current.clear(); spoken.current.clear(); pending.current = [];
    // Only local playback belongs to this hook; HQ setup must not stop an HQ player.
    if (owned.current.size) latest.current.releasePlayback();
    const retained = keepLatest ? files.current[files.current.length - 1] : undefined;
    for (const [id, uri] of owned.current) if (id !== retained?.id) safeDelete(uri);
    owned.current.clear(); files.current = retained ? [retained] : []; finished.current.clear();
    if (retained) { owned.current.set(retained.id, retained.url_path); finished.current.add(retained.id); }
    publish();
    void phoneNativeAudio.cancelSynthesis().catch(() => undefined);
  }, []);
  const interrupt = useCallback(() => stopSpeech(false), [stopSpeech]);

  const cancel = useCallback(() => {
    captureDiagnostics.current = null;
    interrupt(); micEpoch.current++; session.current = ''; live.current = false; starting.current = false;
    utterances.current.clear(); phase.current = 'off';
    void phoneNativeAudio.cancel().catch(() => undefined);
    if (mounted.current) {
      setRecording(false); setLiveEnabled(false); setLivePhase('off'); setBusy(false);
      setMeteringDb(undefined); setTranscript(''); setProbing(false);
    }
  }, [interrupt]);

  const refreshCapabilities = useCallback(async () => {
    const current = ++probeEpoch.current, language = latest.current.language;
    if (!foreground.current || !mounted.current) return;
    setProbing(true);
    try {
      const result = await phoneNativeAudio.getCapabilities(language);
      if (current === probeEpoch.current && mounted.current && foreground.current && language === latest.current.language) {
        setCapabilities(result); setProbeError('');
      }
    } catch (exc) {
      if (current === probeEpoch.current && mounted.current) { setCapabilities(null); setProbeError(nativeReason((exc as { code?: string })?.code)); }
    } finally { if (current === probeEpoch.current && mounted.current) setProbing(false); }
  }, []);

  const collect = useCallback((messages: ChatMessage[]) => {
    if (!active()) return;
    for (const message of messages) {
      if (message.role !== 'assistant' || message.phone_audio_mode !== 'phone_native'
        || !accepted.current.has(message.phone_request_id || '') || !message.id || spoken.current.has(message.id)) continue;
      spoken.current.add(message.id);
      const parts = splitNativeSpeech(message.content);
      if (parts.length + pending.current.length > MAX_PENDING_PARTS) { setError(nativeReason('queue_full')); continue; }
      pending.current.push(...parts.map((text, index) => ({ id: `local-${message.id}-${index}`, text })));
    }
    pumpRef.current();
  }, []);
  collectRef.current = collect;

  pumpRef.current = () => {
    if (!active() || synthesizing.current || !pending.current.length || files.current.length >= MAX_LOCAL_FILES) return;
    const part = pending.current.shift()!;
    const current = epoch.current, key = context();
    synthesizing.current = true;
    synthesisContext.current = { epoch: current, key };
    void recordPhoneDebug('info', 'native_synthesis_started', diagnosticDetails('tts', undefined, 'request', undefined, false));
    void phoneNativeAudio.synthesize(part.text, latest.current.language, latest.current.speakerId).then((audio) => {
      if (current !== epoch.current || key !== context() || !active()) { safeDelete(audio.uri); return; }
      if (!audio.uri.startsWith('file://')) {
        void recordPhoneDebug('error', 'native_synthesis_failed',
          diagnosticDetails('tts', 'local_tts_failed', 'native_result'));
        setError(nativeReason('local_tts_failed')); return;
      }
      void recordPhoneDebug('info', 'native_synthesis_succeeded', {
        provider: audio.provider === 'android_offline' || audio.provider === 'sherpa_onnx' ? audio.provider : 'unknown',
        language: safeNativeDiagnosticLanguage(audio.language), stage: 'native_result',
      });
      setCapabilities((previous) => previous ? { ...previous,
        available: previous.stt.available,
        tts: { available: true, provider: audio.provider, language: audio.language,
          reason: audio.provider === 'android_offline' && previous.tts.provider === 'sherpa_onnx'
            ? 'model_failed_using_android_offline' : previous.tts.reason },
      } : previous);
      const duration = Number(audio.durationSeconds);
      const item: AudioChunk = { id: part.id, index: files.current.length, url_path: audio.uri, text: part.text,
        speaker: 'Phone voice', content_type: 'audio/wav', created_at: Date.now() / 1000,
        ...(Number.isFinite(duration) && duration > 0 ? { duration_seconds: duration } : {}) };
      owned.current.set(item.id, audio.uri); files.current.push(item); publish();
    }).catch((exc) => {
      if (current === epoch.current && active()) {
        const code = (exc as { code?: string })?.code;
        void recordPhoneDebug('error', 'native_synthesis_failed', diagnosticDetails('tts', code, 'promise_reject'));
        setError(nativeReason(code));
      }
    }).finally(() => { synthesizing.current = false; synthesisContext.current = null; pumpRef.current(); });
  };

  const submit = useCallback(async (operation: () => Promise<unknown>): Promise<unknown> => {
    if (!active() || !latest.current.backendSupported) throw new Error(latest.current.backendReason || 'Connect to an updated desktop with Phone Native support. Story uses Backend HQ.');
    // Typed native chat needs local TTS; microphone readiness is checked independently on start.
    if (!capabilities?.tts.available || probing) throw new Error(nativeReason(capabilities?.tts.reason || 'offline_tts_unavailable'));
    if (accepted.current.size >= 512 || pending.current.length >= MAX_PENDING_PARTS) throw new Error(nativeReason('queue_full'));
    const current = epoch.current, key = context();
    const result = await operation();
    if (current !== epoch.current || key !== context() || !active()) return result;
    const id = acceptedNativeRequest(result);
    if (!id) throw new Error('The desktop did not confirm Phone Native routing. Update the desktop and try again.');
    accepted.current.add(id);
    collectRef.current(latest.current.messages);
    collectRef.current((result as PhoneSendEnvelope)?.result?.state?.chat?.messages || []);
    return result;
  }, [capabilities, probing]);

  const playbackFinished = useCallback((chunk: AudioChunk) => {
    if (!owned.current.has(chunk.id)) return;
    finished.current.add(chunk.id);
    files.current = files.current.filter((item) => {
      if (item.id === chunk.id || !finished.current.has(item.id)) return true;
      const uri = owned.current.get(item.id); owned.current.delete(item.id); finished.current.delete(item.id);
      if (uri) safeDelete(uri); return false;
    });
    publish(); pumpRef.current();
  }, []);

  useEffect(() => { cancel(); }, [options.mode, options.identityKey, options.connected, options.storyActive, options.language, options.speakerId, options.conversationGeneration, cancel]);
  useEffect(() => {
    if (options.mode === 'phone_native' || setupOpen) { setCapabilities(null); void refreshCapabilities(); }
  }, [options.mode, options.language, setupOpen, refreshCapabilities]);
  useEffect(() => { collect(options.messages); }, [options.messages, collect]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (state) => {
      foreground.current = state === 'active';
      if (!foreground.current) { probeEpoch.current++; cancel(); }
      else if (latest.current.mode === 'phone_native' || setupWanted.current) void refreshCapabilities();
    });
    return () => subscription.remove();
  }, [cancel, refreshCapabilities]);
  useEffect(() => {
    const valid = (event: { sessionId?: string }) => active() && Boolean(session.current) && event.sessionId === session.current;
    const subscriptions = [
      phoneNativeAudio.addListener('onTranscript', (event) => {
        if (!valid(event) || event.isFinal !== true || !event.utteranceId || utterances.current.has(event.utteranceId)) return;
        utterances.current.add(event.utteranceId);
        if (utterances.current.size > 256) utterances.current.delete(utterances.current.values().next().value!);
        const text = typeof event.text === 'string' ? event.text.trim() : '';
        if (!text) return;
        void recordPhoneDebug('info', 'native_recognition_succeeded', {
          provider: event.provider === 'sherpa_onnx' || event.provider === 'android_offline' ? event.provider : 'unknown',
          language: safeNativeDiagnosticLanguage(event.language), stage: 'final_result',
        });
        if (event.provider === 'sherpa_onnx' || event.provider === 'android_offline') {
          setCapabilities((previous) => previous ? { ...previous, available: previous.tts.available,
            stt: { available: true, provider: event.provider, language: String(event.language || previous.stt.language),
              reason: event.provider === 'android_offline' && previous.stt.provider === 'sherpa_onnx'
                ? 'model_failed_using_android_offline' : previous.stt.reason },
          } : previous);
        }
        if (!live.current) { setRecording(false); setBusy(false); }
        if (!latest.current.sendToChat) { setTranscript(text); return; }
        const current = micEpoch.current;
        setBusy(true);
        void latest.current.onSendText(text).catch(() => {
          if (current === micEpoch.current && active()) setError('The local transcript could not be sent. Check the desktop connection and try again.');
        }).finally(() => { if (current === micEpoch.current && mounted.current) setBusy(false); });
      }),
      phoneNativeAudio.addListener('onListeningState', (event) => {
        if (!valid(event)) return;
        recordCaptureSummary(captureDiagnostics.current?.observe(event.state, event.meteringDb));
        if (event.state === 'speech' && phase.current !== 'speech') {
          interrupt(); // Synthesis-only cancellation keeps this utterance's PCM alive.
          void latest.current.onLiveSpeechStart?.().catch(() => undefined);
        }
        phase.current = event.state === 'speech' ? 'speech' : event.state === 'off' ? 'off' : 'listening';
        setLivePhase(phase.current);
        if (typeof event.meteringDb === 'number' && Number.isFinite(event.meteringDb)) { setMeteringDb(event.meteringDb); setMeteringRevision((v) => v + 1); }
        if (event.state === 'off') { live.current = false; setLiveEnabled(false); setRecording(false); setBusy(false); }
      }),
      phoneNativeAudio.addListener('onError', (event) => {
        const synthesis = synthesisContext.current;
        if (valid(event)) {
          void recordPhoneDebug('error', 'native_recognition_failed',
            diagnosticDetails('stt', event.code, 'native_event', Boolean(event.sessionId)));
          setError(nativeReason(event.code));
        } else if (!event.sessionId && synthesis && synthesis.epoch === epoch.current && synthesis.key === context() && active()) {
          void recordPhoneDebug('error', 'native_synthesis_failed', diagnosticDetails('tts', event.code, 'native_event'));
          setError(nativeReason(event.code));
        }
      }),
      phoneNativeAudio.addListener('onModelProgress', (event) => {
        if (mounted.current && installingRef.current) setProgress({ model: String(event.model), phase: String(event.phase), bytes: Number(event.bytes) || 0, totalBytes: Number(event.totalBytes) || 0 });
      }),
    ];
    return () => subscriptions.forEach((subscription) => subscription.remove());
  }, [interrupt]);
  useEffect(() => () => { mounted.current = false; cancel(); }, [cancel]);

  const start = async (wantLive: boolean) => {
    if (starting.current || phase.current !== 'off') return;
    if (!active() || !latest.current.backendSupported) { setError('Connect to an updated desktop before using native voice chat. Story uses Backend HQ.'); return; }
    if (!capabilities?.stt.available || !capabilities?.tts.available || probing) { setError(nativeReason(capabilities?.stt.reason || 'offline_audio_not_ready')); return; }
    const current = ++micEpoch.current, key = context();
    const sensitivity = normalizeNativeMicSensitivity(latest.current.sensitivity);
    starting.current = true; setError('');
    let failureStage = 'permission';
    try {
      let permission = await AudioModule.getRecordingPermissionsAsync();
      if (current !== micEpoch.current || key !== context() || !active()) return;
      if (!permission.granted) {
        // Android's request can pause/resume even with a previous grant. Avoid
        // that roundtrip when ready, and never revive a lifecycle-cancelled start.
        permission = await AudioModule.requestRecordingPermissionsAsync();
        if (current !== micEpoch.current || key !== context() || !active()) {
          if (key === context() && active()) setError(permission.granted
            ? 'Microphone permission is allowed. Tap Mic or Live Mode again to start.'
            : nativeReason('microphone_permission_denied'));
          return;
        }
      }
      if (!permission.granted) { setError(nativeReason('microphone_permission_denied')); return; }
      failureStage = 'microphone_release';
      try { await latest.current.onBeforeListening?.(); }
      catch { throw Object.assign(new Error('Microphone release failed.'), { code: 'hq_microphone_release_failed' }); }
      if (current !== micEpoch.current || key !== context() || !active()) return;
      session.current = `phone-${Date.now()}-${current}`; live.current = wantLive;
      captureDiagnostics.current = new NativeCaptureDiagnostics(wantLive, sensitivity);
      phase.current = 'listening';
      utterances.current.clear(); setLiveEnabled(wantLive); setRecording(!wantLive); setLivePhase('listening');
      failureStage = 'native_start';
      await phoneNativeAudio.startListening(session.current, latest.current.language, wantLive, sensitivity);
    } catch (exc) {
      if (current === micEpoch.current && active()) {
        const code = (exc as { code?: string })?.code;
        void recordPhoneDebug('error', 'native_recognition_failed',
          diagnosticDetails('stt', code, failureStage, Boolean(session.current)));
        session.current = ''; live.current = false; phase.current = 'off'; setRecording(false); setLiveEnabled(false); setLivePhase('off');
        setError(nativeReason(code));
      }
    } finally { if (current === micEpoch.current) starting.current = false; }
  };
  const stopListening = async (commit: boolean) => {
    if (!commit) {
      recordCaptureSummary(captureDiagnostics.current?.finish('stopped'));
      captureDiagnostics.current = null;
    }
    if (!commit) { micEpoch.current++; session.current = ''; live.current = false; starting.current = false; phase.current = 'off'; setLiveEnabled(false); setRecording(false); setLivePhase('off'); }
    try { await phoneNativeAudio.stopListening(commit); }
    catch (exc) { if (mounted.current) setError(nativeReason((exc as { code?: string })?.code)); }
  };

  return {
    capabilities, probing, setupOpen, installing, progress, error: error || probeError, chunks,
    openSetup: () => { setupWanted.current = true; setSetupOpen(true); },
    closeSetup: () => { setupWanted.current = false; setSetupOpen(false); },
    refreshCapabilities,
    reportCaptureReleaseError: () => setError(nativeReason('hq_microphone_release_failed')),
    requestMicrophonePermission: async () => {
      try {
        const permission = await AudioModule.requestRecordingPermissionsAsync();
        if (mounted.current) setError(permission.granted ? '' : nativeReason('microphone_permission_denied'));
      } catch { if (mounted.current) setError(nativeReason('microphone_permission_denied')); }
    },
    installModels: async () => {
      if (installingRef.current) return;
      installingRef.current = true; setInstalling(true); setProgress(null); setError('');
      try { await phoneNativeAudio.installModels(); if (mounted.current && foreground.current) await refreshCapabilities(); }
      catch (exc) { if (mounted.current) setError(nativeReason((exc as { code?: string })?.code)); }
      finally { installingRef.current = false; if (mounted.current) setInstalling(false); }
    },
    submit, interrupt, stop: () => stopSpeech(true), clear: interrupt, cancel, playbackFinished,
    resolveOwnedAudio: (chunk: AudioChunk): string | null => owned.current.get(chunk.id) === chunk.url_path ? chunk.url_path : null,
    recording, busy, transcript, clearTranscript: () => setTranscript(''), liveEnabled, livePhase,
    liveStatus: !liveEnabled ? 'Off' : busy ? 'Sending local transcript...' : livePhase === 'speech' ? 'Hearing you...' : 'Listening offline...',
    meteringDb, meteringRevision, pauseLiveForPlayback: async () => undefined,
    toggleLive: async () => { if (live.current || starting.current) await stopListening(false); else await start(true); },
    toggleRecording: async () => { if (live.current) return; if (phase.current !== 'off') { setBusy(true); await stopListening(true); } else await start(false); },
  };
}
