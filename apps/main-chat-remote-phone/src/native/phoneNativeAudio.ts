import { NativeEventEmitter, NativeModules, Platform } from 'react-native';
import { normalizeNativeMicSensitivity } from '../utils/phoneNativeSpeech';

export type NativeProvider = 'sherpa_onnx' | 'android_offline';
export type NativeRoute = { available: boolean; provider: NativeProvider | null; language: string; reason: string | null };
export type NativeCapabilities = {
  available: boolean;
  reason: string | null;
  deviceLanguage: string;
  stt: NativeRoute;
  tts: NativeRoute;
  models: { sttInstalled: boolean; ttsInstalled: boolean };
  micSensitivitySupported: boolean;
};
export type NativeAudio = { uri: string; provider: NativeProvider; language: string; durationSeconds?: number };
export interface PhoneNativeAudio {
  getCapabilities(language: string): Promise<NativeCapabilities>;
  installModels(): Promise<void>;
  startListening(sessionId: string, language: string, live: boolean, sensitivity?: number): Promise<void>;
  stopListening(commit: boolean): Promise<void>;
  synthesize(text: string, language: string, speakerId?: number): Promise<NativeAudio>;
  cancelSynthesis(): Promise<void>;
  cancel(): Promise<void>;
  deleteAudio(uri: string): Promise<void>;
  addListener(event: string, listener: (event: any) => void): { remove(): void };
}

const native = Platform.OS === 'android' ? NativeModules.NcPhoneNativeAudio : undefined;
const emitter = native ? new NativeEventEmitter(native) : null;
const unavailable = () => Promise.reject(Object.assign(new Error('Phone Native audio requires a custom Android build.'), { code: 'native_build_required' }));
const micSensitivitySupported = () => typeof native?.startListeningWithSensitivity === 'function';
export const phoneNativeAudio: PhoneNativeAudio = native ? {
  getCapabilities: async (language) => ({
    ...await native.getCapabilities(language),
    micSensitivitySupported: micSensitivitySupported(),
  }),
  installModels: () => native.installModels(),
  startListening: (sessionId, language, live, sensitivity = 3) => {
    const level = normalizeNativeMicSensitivity(sensitivity);
    if (micSensitivitySupported()) return native.startListeningWithSensitivity(sessionId, language, live, level);
    if (level !== 3) return unavailable();
    return native.startListening(sessionId, language, live);
  },
  stopListening: (commit) => native.stopListening(commit),
  synthesize: (text, language, speakerId = 0) => native.synthesize(text, language, speakerId),
  cancelSynthesis: () => native.cancelSynthesis(),
  cancel: () => native.cancel(),
  deleteAudio: (uri) => native.deleteAudio(uri),
  addListener: (event, listener) => emitter!.addListener(event, listener),
} : {
  async getCapabilities(language) {
    const resolved = language || Intl.DateTimeFormat().resolvedOptions().locale;
    const route: NativeRoute = { available: false, provider: null, language: resolved, reason: 'native_build_required' };
    return { available: false, reason: 'native_build_required', deviceLanguage: Intl.DateTimeFormat().resolvedOptions().locale,
      stt: route, tts: { ...route }, models: { sttInstalled: false, ttsInstalled: false }, micSensitivitySupported: false };
  },
  installModels: unavailable,
  startListening: unavailable,
  stopListening: unavailable,
  synthesize: unavailable,
  cancelSynthesis: unavailable,
  cancel: unavailable,
  deleteAudio: unavailable,
  addListener: () => ({ remove() {} }),
};
