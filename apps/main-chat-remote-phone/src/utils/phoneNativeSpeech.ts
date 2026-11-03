import type { AudioChunk, PhoneSendEnvelope } from '../api/types';

// Names are explicit: ordinary brackets such as [Monday] carry spoken meaning.
const TAGS = new Set(['neutral', 'happy', 'sad', 'angry', 'surprised', 'fearful', 'fear', 'tension', 'focus', 'dark', 'epic', 'energetic', 'disgusted', 'excited', 'calm', 'curious', 'confused', 'shy', 'embarrassed', 'loving', 'playful', 'serious', 'thoughtful', 'whisper', 'whispering', 'clear throat', 'sigh', 'shush', 'groan', 'sniff', 'gasp', 'chuckle', 'laugh']);

export function prepareNativeSpeech(text: string): string {
  let value = String(text || '');
  const directive = /\[(?:visualize|image)\s*:/i;
  let match: RegExpExecArray | null;
  while ((match = directive.exec(value))) {
    let end = match.index + match[0].length, depth = 1;
    for (; end < value.length && depth > 0; end++) {
      if (value[end] === '[') depth++;
      else if (value[end] === ']') depth--;
    }
    value = `${value.slice(0, match.index)} ${value.slice(end)}`;
  }
  return value
    .replace(/!?\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\[([^\]\n]+)\]/g, (full, name: string) => TAGS.has(name.trim().toLowerCase()) ? ' ' : full)
    .replace(/^\s{0,3}(?:#{1,6}\s*|>\s*|[-*+]\s+)/gm, '')
    .replace(/```[^\n]*\n|```/g, '').replace(/`([^`]+)`/g, '$1')
    .replace(/\*\*|__/g, '').replace(/\*([^*\n]+)\*/g, '$1').replace(/_([^_\n]+)_/g, '$1')
    .replace(/\s+/g, ' ').trim();
}

export function splitNativeSpeech(text: string): string[] {
  let remaining = prepareNativeSpeech(text);
  const parts: string[] = [];
  while (remaining.length > 2800) {
    const prefix = remaining.slice(0, 2800);
    const sentence = Math.max(prefix.lastIndexOf('. '), prefix.lastIndexOf('! '), prefix.lastIndexOf('? '));
    let end = sentence > 1400 ? sentence + 1 : prefix.lastIndexOf(' ');
    if (end < 1) end = 2800;
    // Never cut a UTF-16 surrogate pair at a hard word boundary.
    if (/[\uD800-\uDBFF]/.test(remaining.charAt(end - 1))) end--;
    parts.push(remaining.slice(0, end).trim()); remaining = remaining.slice(end).trim();
  }
  if (remaining) parts.push(remaining);
  return parts;
}

export function acceptedNativeRequest(value: unknown): string {
  const envelope = value as PhoneSendEnvelope | undefined;
  const result = envelope?.result;
  return envelope?.ok === true && result?.accepted === true && result.audio_mode === 'phone_native'
    && typeof result.phone_request_id === 'string' ? result.phone_request_id : '';
}

const SAFE_NATIVE_DIAGNOSTIC_CODES = new Set([
  'native_build_required', 'native_operation_failed', 'native_engine_unavailable', 'native_busy',
  'offline_audio_not_ready', 'offline_language_unavailable', 'model_failed_no_offline_fallback',
  'model_failed_using_android_offline', 'microphone_permission_denied', 'hq_microphone_release_failed',
  'invalid_language', 'invalid_session', 'model_install_failed', 'model_install_busy',
  'offline_stt_unavailable', 'offline_tts_unavailable', 'stt_model_failed', 'tts_model_failed',
  'stt_busy_utterance_discarded', 'microphone_capture_failed', 'listening_start_timeout',
  'invalid_synthesis_input', 'local_tts_failed', 'tts_busy', 'queue_full', 'cancelled',
  'audio_delete_failed', 'audio_not_owned', 'app_inactive',
]);

export function safeNativeDiagnosticCode(value: unknown): string {
  const code = typeof value === 'string' ? value.trim() : '';
  if (!code || code.length > 64) return 'unknown';
  if (SAFE_NATIVE_DIAGNOSTIC_CODES.has(code)) return code;
  return /^offline_recognition_(?:[1-9]|1[0-5]|timeout|unavailable)$/.test(code) ? code : 'unknown';
}

export function safeNativeDiagnosticLanguage(value: unknown): string {
  const language = typeof value === 'string' ? value.trim() : '';
  return language.length <= 64 && /^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$/.test(language) ? language : 'unknown';
}

export function normalizeNativeMicSensitivity(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value)
    ? Math.round(Math.max(1, Math.min(5, value))) : 3;
}

/** Aggregate existing ~10 Hz meter events; never retain PCM, text, paths or session IDs.
 * Sherpa reports dBFS; Android's meter is provider-defined, so these are not comparable.
 */
export class NativeCaptureDiagnostics {
  private startedAt: number | null = null;
  private observations = 0;
  private minimum = Infinity;
  private maximum = -Infinity;
  private speechDetected = false;
  private closed = false;
  constructor(private readonly live: boolean, private readonly sensitivity = 3) {}

  observe(state: unknown, db: unknown, now = Date.now()) {
    if (!['listening', 'speech', 'processing', 'off'].includes(String(state))) return null;
    if (state === 'listening' || state === 'speech') this.closed = false;
    else if (this.closed) return null;
    if (this.startedAt === null) this.startedAt = now;
    if (typeof db === 'number' && Number.isFinite(db) && db >= -120 && db <= 30) {
      this.observations = Math.min(6000, this.observations + 1);
      this.minimum = Math.min(this.minimum, db); this.maximum = Math.max(this.maximum, db);
    }
    if (state === 'speech') this.speechDetected = true;
    return state === 'processing' || state === 'off' ? this.finish(state, now) : null;
  }

  finish(reason: 'processing' | 'off' | 'stopped', now = Date.now()) {
    const summary = this.observations || this.speechDetected ? {
      live: this.live, end_reason: reason,
      sensitivity_level: normalizeNativeMicSensitivity(this.sensitivity),
      elapsed_ms: Math.max(0, Math.min(120000, Math.round(now - (this.startedAt ?? now)))),
      meter_observations: this.observations, speech_detected: this.speechDetected,
      ...(this.observations ? { sampled_meter_min: Math.round(this.minimum * 10) / 10,
        sampled_meter_max: Math.round(this.maximum * 10) / 10 } : {}),
    } : null;
    this.startedAt = null; this.observations = 0; this.minimum = Infinity; this.maximum = -Infinity;
    this.speechDetected = false; this.closed = true;
    return summary;
  }
}

export function nativeReason(code: unknown): string {
  const reasons: Record<string, string> = {
    native_build_required: 'Install the custom Android app to use Phone Native. Expo Go, web and iOS use Backend HQ.',
    offline_audio_not_ready: 'Set up local speech below. Install the English packs or matching Android offline speech and voice languages.',
    offline_language_unavailable: 'This language needs installed Android offline recognition and voice data. English can use the downloadable packs.',
    model_failed_no_offline_fallback: 'The local model could not load. In Android app settings, force stop NC Remote, reopen it and check Phone Native setup. Or use a matching installed Android offline language/voice. If it still fails, send diagnostics.',
    model_failed_using_android_offline: 'Using the matching installed Android offline engine because the local model could not load.',
    microphone_permission_denied: 'Allow microphone permission in Android app settings, then try again.',
    hq_microphone_release_failed: 'The previous microphone could not be released. Close other microphone apps and restart the phone app before using Phone Native.',
    invalid_language: 'Use a language tag such as en-US or sv-SE, or leave it empty for the device language.',
    model_install_failed: 'Model installation failed. Check the connection and free storage, then retry the download.',
    model_install_busy: 'A model installation is already running.',
    offline_stt_unavailable: 'No matching offline recognizer is ready. Install English packs or Android offline recognition data.',
    offline_tts_unavailable: 'No matching offline voice is ready. Install English packs or Android offline voice data.',
    stt_model_failed: 'Local recognition failed; that utterance was not sent. If an Android offline fallback is ready, speak again.',
    tts_model_failed: 'The local speech model failed. A matching installed Android offline voice will be used if ready.',
    stt_busy_utterance_discarded: 'Recognition is busy; that utterance was not sent. Please speak again.',
    microphone_capture_failed: 'Microphone capture failed. Check permission and close other microphone apps, then retry.',
    listening_start_timeout: 'The offline microphone did not start. Check installed languages and try again.',
    local_tts_failed: 'Local speech generation failed. In Android app settings, force stop NC Remote, reopen it and check Phone Native setup. Or use a matching installed Android offline language/voice. If it still fails, send diagnostics.',
    app_inactive: 'Return to the app before starting local speech.',
    audio_delete_failed: 'A local audio file could not be removed. Restart the app; temporary files are also cleaned up automatically when stale.',
    native_busy: 'The local speech engine is busy. Try again shortly.',
    tts_busy: 'Local speech is still stopping. Please retry shortly.',
    queue_full: 'The local speech queue is full. Play or clear queued audio before sending more.',
    cancelled: 'Local speech was cancelled.',
  };
  const key = String(code || '');
  const recognitionReasons: Record<string, string> = {
    offline_recognition_8: 'Android offline recognition stayed busy. Wait a moment and try again.',
    offline_recognition_9: 'Android offline recognition lost microphone permission. Allow microphone permission in Android app settings, then try again.',
    offline_recognition_11: 'The Android offline recognition service disconnected. Retry once; if it continues, reopen NC Remote and send diagnostics.',
    offline_recognition_12: 'The requested language is not supported by Android offline recognition. Choose a supported local language or install matching Android offline recognition data.',
    offline_recognition_13: 'The requested Android offline recognition language is unavailable. Install matching offline recognition data, then refresh Phone Native setup.',
    offline_recognition_timeout: 'Android offline recognition did not finish in time. Try again; if it persists, send diagnostics.',
    offline_recognition_unavailable: 'Android offline recognition could not start. Retry once; if it persists, reopen NC Remote and send diagnostics.',
  };
  if (recognitionReasons[key]) return recognitionReasons[key];
  if (key.startsWith('offline_recognition_')) return 'Android offline recognition stopped for an unclassified device error. Try again; if it persists, send diagnostics.';
  if (key.startsWith('android_stt_')) return 'Android offline recognition stopped. Check microphone permission and installed offline languages, then try again.';
  return reasons[key] || 'Local speech stopped for an unknown reason. Try again; if it persists, send diagnostics.';
}

/** Track the last observed backend snapshot separately from the active playback source. */
export class PhonePlaybackBoundary {
  private key = '';
  private source = '';
  private observed = new Set<string>();
  private blocked = new Set<string>();
  select(key: string, source: string, chunks: AudioChunk[]): AudioChunk[] {
    if (key !== this.key) { this.key = key; this.source = source; this.observed.clear(); this.blocked.clear(); }
    if (source !== this.source) {
      // Exclude only items observed BEFORE the transition; retain new items in this snapshot.
      this.blocked = new Set(this.observed); this.source = source;
    }
    this.observed = new Set(chunks.map((chunk) => chunk.id));
    return source === 'native' || source === 'off' ? [] : chunks.filter((chunk) => !this.blocked.has(chunk.id));
  }
}
