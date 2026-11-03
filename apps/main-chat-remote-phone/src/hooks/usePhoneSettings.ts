import { useCallback, useEffect, useRef, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import type { AudioMode } from '../api/types';
import { normalizeNativeMicSensitivity } from '../utils/phoneNativeSpeech';

import { resolveInterfaceStyle } from '../utils/interfaceMode';
import type { InterfaceStyle } from '../utils/interfaceMode';
import {
  DEFAULT_LIVE_FULLSCREEN_SETTINGS,
  normalizeLiveFullscreenSettings,
} from '../utils/liveFullscreenSettings';
import type { LiveFullscreenSettings } from '../utils/liveFullscreenSettings';
import { normalizeCompanionDisplayMode } from '../utils/companionDisplayMode';
import type { CompanionDisplayMode } from '../utils/companionDisplayMode';
import { normalizeVoiceThreadPalette } from '../utils/presenceControls';
import type { VoiceThreadPalette } from '../utils/presenceControls';
import { normalizeThemeId } from '../styles/theme';
import type { PhoneThemeId } from '../styles/theme';
import {normalizePresentationStyle} from '../styles/presentation';
import type {PresentationStyle} from '../styles/presentation';
import { DEFAULT_SILK_SETTINGS, normalizeSilkSettings } from '../utils/silkSettings';
import type { SilkSettings } from '../utils/silkSettings';
import { normalizeVoiceVisualizerStyle } from '../utils/voiceVisualizer';
import type { VoiceVisualizerStyle } from '../utils/voiceVisualizer';
import { normalizeNarrationPace } from '../utils/narrationPace';
import type { NarrationPace } from '../utils/narrationPace';
import { DEFAULT_RESPONSE_CARD_ORDER, normalizeResponseCardOrder } from '../utils/responseCardOrder';
import type { ResponseCardId } from '../utils/responseCardOrder';
import { DEFAULT_QUICK_MENU_ACTIONS, normalizeQuickMenuActions } from '../utils/quickMenuActions';
import type { QuickMenuAction } from '../utils/quickMenuActions';
import { DEFAULT_VISUAL_DISPLAY, normalizeVisualDisplay } from '../utils/visualDisplay';
import type { VisualDisplay } from '../utils/visualDisplay';

export type { InterfaceStyle } from '../utils/interfaceMode';
export type { CompanionDisplayMode } from '../utils/companionDisplayMode';
export type { VoiceThreadPalette } from '../utils/presenceControls';

export type SendMode = 'text_only' | 'phone_tts' | 'visual_reply';
export type MicBehavior = 'transcribe_only' | 'send_auto';
export type MuseTalkQuality = 'low_latency' | 'balanced' | 'quality';
export type ChatLayout = 'standard' | 'clean';
export type ChatTextColor = 'white' | 'green' | 'amber' | 'cyan';
export type ChatIndicatorStyle = 'dot' | 'pulse' | 'line' | 'text';
export type ChatReadingStyle = 'quiet_underline' | 'soft_focus' | 'reading_rail';

export type PhoneSettings = {
  presentationStyle: PresentationStyle;
  colorTheme: PhoneThemeId;
  conversationAvatarSize: number;
  showTopVoiceThread: boolean;
  voiceVisualizerStyle: VoiceVisualizerStyle;
  silk: SilkSettings;
  audioMode: AudioMode;
  nativeLanguage: string;
  nativeSpeakerId: number;
  nativeMicSensitivity: number;
  liveMicSensitivity: number;
  phoneTtsAutoplay: boolean;
  progressiveLiquidAudio: boolean;
  headphoneNextTogglesPlayback: boolean;
  phoneTtsVolume: number;
  automatedUserTtsVolume: number;
  phoneNarrationPace: NarrationPace;
  allowBackgroundLive: boolean;
  liveDuckingUseSystemDefault: boolean;
  liveDuckingLevel: 'min' | 'mid' | 'max';
  playOnBackend: boolean;
  sendMode: SendMode;
  micBehavior: MicBehavior;
  autoReconnect: boolean;
  keepAwake: boolean;
  pollingIntervalMs: number;
  museTalkQuality: MuseTalkQuality;
  chatLayout: ChatLayout;
  chatTextColor: ChatTextColor;
  chatIndicatorStyle: ChatIndicatorStyle;
  chatReadAlong: boolean;
  chatBionicReading: boolean;
  chatReadingAutoScroll: boolean;
  chatReadingStyle: ChatReadingStyle;
  chatFontSize: number;
  retainedChatMessages: number;
  interfaceStyle: InterfaceStyle;
  companionDisplayMode: CompanionDisplayMode;
  showPresenceControls: boolean;
  showConversationControls: boolean;
  showPlaybackRail: boolean;
  showVisualButton: boolean;
  showStoryShortcuts: boolean;
  showContinuousBar: boolean;
  showCompanionHeader: boolean;
  showSoundsMenu: boolean;
  autoCloseResponseMenu: boolean;
  responseCardOrder: ResponseCardId[];
  quickMenuActions: QuickMenuAction[];
  showResetChat: boolean;
  voiceThreadPalette: VoiceThreadPalette;
  liveFullscreen: LiveFullscreenSettings;
  visualDisplay: VisualDisplay;
};

const SETTINGS_KEY = 'nc-main-chat-remote.phone-settings';
const MIN_POLL_INTERVAL_MS = 900;
const MAX_POLL_INTERVAL_MS = 15000;

export const DEFAULT_PHONE_SETTINGS: PhoneSettings = {
  presentationStyle: 'classic',
  colorTheme: 'midnight',
  conversationAvatarSize: 72,
  showTopVoiceThread: true,
  voiceVisualizerStyle: 'silk',
  silk: DEFAULT_SILK_SETTINGS,
  audioMode: 'backend_hq',
  nativeLanguage: '',
  nativeSpeakerId: 0,
  nativeMicSensitivity: 3,
  liveMicSensitivity: 4,
  phoneTtsAutoplay: true,
  progressiveLiquidAudio: false,
  headphoneNextTogglesPlayback: true,
  phoneTtsVolume: 1,
  automatedUserTtsVolume: 1,
  phoneNarrationPace: 'original',
  allowBackgroundLive: false,
  liveDuckingUseSystemDefault: true,
  liveDuckingLevel: 'min',
  playOnBackend: false,
  sendMode: 'phone_tts',
  micBehavior: 'send_auto',
  autoReconnect: true,
  keepAwake: true,
  pollingIntervalMs: 1800,
  museTalkQuality: 'balanced',
  chatLayout: 'standard',
  chatTextColor: 'white',
  chatIndicatorStyle: 'dot',
  chatReadAlong: true,
  chatBionicReading: false,
  chatReadingAutoScroll: true,
  chatReadingStyle: 'quiet_underline',
  chatFontSize: 20,
  retainedChatMessages: 20,
  interfaceStyle: 'adaptive',
  companionDisplayMode: 'conversation',
  showPresenceControls: false,
  showConversationControls: true,
  showPlaybackRail: true,
  showVisualButton: true,
  showStoryShortcuts: true,
  showContinuousBar: true,
  showCompanionHeader: true,
  showSoundsMenu: false,
  autoCloseResponseMenu: true,
  responseCardOrder: [...DEFAULT_RESPONSE_CARD_ORDER],
  quickMenuActions: [...DEFAULT_QUICK_MENU_ACTIONS],
  showResetChat: true,
  voiceThreadPalette: 'state',
  liveFullscreen: DEFAULT_LIVE_FULLSCREEN_SETTINGS,
  visualDisplay: DEFAULT_VISUAL_DISPLAY,
};

function boolValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function boundedNumber(value: unknown, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, Math.min(maximum, parsed));
}

function enumValue<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return options.includes(value as T) ? value as T : fallback;
}

function normalizeSettings(value: unknown): PhoneSettings {
  const data = value && typeof value === 'object' ? value as Partial<PhoneSettings> : {};
  const storedSendMode = enumValue(data.sendMode, ['text_only', 'phone_tts', 'visual_reply'] as const, DEFAULT_PHONE_SETTINGS.sendMode);
  return {
    colorTheme: normalizeThemeId(data.colorTheme),
    presentationStyle: normalizePresentationStyle(data.presentationStyle),
    conversationAvatarSize: Math.round(boundedNumber(data.conversationAvatarSize, 72, 48, 128)),
    showTopVoiceThread: boolValue(data.showTopVoiceThread, true),
    voiceVisualizerStyle: normalizeVoiceVisualizerStyle(data.voiceVisualizerStyle),
    silk: normalizeSilkSettings(data.silk),
    audioMode: enumValue(data.audioMode, ['backend_hq', 'phone_native'] as const, 'backend_hq'),
    nativeLanguage: typeof data.nativeLanguage === 'string' ? data.nativeLanguage.trim().slice(0, 64) : '',
    nativeSpeakerId: Math.round(boundedNumber(data.nativeSpeakerId ?? 0, 0, 0, 7)),
    nativeMicSensitivity: normalizeNativeMicSensitivity(data.nativeMicSensitivity),
    liveMicSensitivity: Math.round(boundedNumber(data.liveMicSensitivity, DEFAULT_PHONE_SETTINGS.liveMicSensitivity, 1, 5)),
    phoneTtsAutoplay: boolValue(data.phoneTtsAutoplay, DEFAULT_PHONE_SETTINGS.phoneTtsAutoplay),
    headphoneNextTogglesPlayback: boolValue(data.headphoneNextTogglesPlayback, DEFAULT_PHONE_SETTINGS.headphoneNextTogglesPlayback),
    phoneTtsVolume: boundedNumber(data.phoneTtsVolume, DEFAULT_PHONE_SETTINGS.phoneTtsVolume, 0, 1),
    automatedUserTtsVolume: boundedNumber(data.automatedUserTtsVolume, DEFAULT_PHONE_SETTINGS.automatedUserTtsVolume, 0, 1),
    phoneNarrationPace: normalizeNarrationPace(data.phoneNarrationPace),
    allowBackgroundLive: boolValue(data.allowBackgroundLive, DEFAULT_PHONE_SETTINGS.allowBackgroundLive),
    liveDuckingUseSystemDefault: boolValue(data.liveDuckingUseSystemDefault, true),
    liveDuckingLevel: enumValue(data.liveDuckingLevel, ['min', 'mid', 'max'] as const, 'min'),
    progressiveLiquidAudio: boolValue(data.progressiveLiquidAudio, false),
    playOnBackend: false,
    sendMode: storedSendMode === 'text_only' ? 'phone_tts' : storedSendMode,
    micBehavior: enumValue(data.micBehavior, ['transcribe_only', 'send_auto'] as const, DEFAULT_PHONE_SETTINGS.micBehavior),
    autoReconnect: boolValue(data.autoReconnect, DEFAULT_PHONE_SETTINGS.autoReconnect),
    keepAwake: boolValue(data.keepAwake, DEFAULT_PHONE_SETTINGS.keepAwake),
    pollingIntervalMs: Math.round(boundedNumber(data.pollingIntervalMs, DEFAULT_PHONE_SETTINGS.pollingIntervalMs, MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS)),
    museTalkQuality: enumValue(data.museTalkQuality, ['low_latency', 'balanced', 'quality'] as const, DEFAULT_PHONE_SETTINGS.museTalkQuality),
    chatLayout: enumValue(data.chatLayout, ['standard', 'clean'] as const, DEFAULT_PHONE_SETTINGS.chatLayout),
    chatTextColor: enumValue(data.chatTextColor, ['white', 'green', 'amber', 'cyan'] as const, DEFAULT_PHONE_SETTINGS.chatTextColor),
    chatIndicatorStyle: enumValue(data.chatIndicatorStyle, ['dot', 'pulse', 'line', 'text'] as const, DEFAULT_PHONE_SETTINGS.chatIndicatorStyle),
    chatReadAlong: boolValue(data.chatReadAlong, DEFAULT_PHONE_SETTINGS.chatReadAlong),
    chatBionicReading: boolValue(data.chatBionicReading, DEFAULT_PHONE_SETTINGS.chatBionicReading),
    chatReadingAutoScroll: boolValue(data.chatReadingAutoScroll, DEFAULT_PHONE_SETTINGS.chatReadingAutoScroll),
    chatReadingStyle: enumValue(data.chatReadingStyle, ['quiet_underline', 'soft_focus', 'reading_rail'] as const, DEFAULT_PHONE_SETTINGS.chatReadingStyle),
    chatFontSize: Math.round(boundedNumber(data.chatFontSize, DEFAULT_PHONE_SETTINGS.chatFontSize, 14, 28)),
    retainedChatMessages: Math.round(boundedNumber(data.retainedChatMessages, DEFAULT_PHONE_SETTINGS.retainedChatMessages, 10, 100)),
    interfaceStyle: resolveInterfaceStyle(data.interfaceStyle, data.chatLayout),
    companionDisplayMode: normalizeCompanionDisplayMode(data.companionDisplayMode),
    showPresenceControls: boolValue(data.showPresenceControls, DEFAULT_PHONE_SETTINGS.showPresenceControls),
    showConversationControls: boolValue(data.showConversationControls, DEFAULT_PHONE_SETTINGS.showConversationControls),
    showPlaybackRail: boolValue(data.showPlaybackRail, DEFAULT_PHONE_SETTINGS.showPlaybackRail),
    showVisualButton: boolValue(data.showVisualButton, DEFAULT_PHONE_SETTINGS.showVisualButton),
    showStoryShortcuts: boolValue(data.showStoryShortcuts, DEFAULT_PHONE_SETTINGS.showStoryShortcuts),
    showContinuousBar: boolValue(data.showContinuousBar, DEFAULT_PHONE_SETTINGS.showContinuousBar),
    showCompanionHeader: boolValue(data.showCompanionHeader, DEFAULT_PHONE_SETTINGS.showCompanionHeader),
    showSoundsMenu: boolValue(data.showSoundsMenu, DEFAULT_PHONE_SETTINGS.showSoundsMenu),
    autoCloseResponseMenu: boolValue(data.autoCloseResponseMenu, DEFAULT_PHONE_SETTINGS.autoCloseResponseMenu),
    responseCardOrder: normalizeResponseCardOrder(data.responseCardOrder),
    quickMenuActions: normalizeQuickMenuActions(data.quickMenuActions),
    showResetChat: boolValue(data.showResetChat, DEFAULT_PHONE_SETTINGS.showResetChat),
    voiceThreadPalette: normalizeVoiceThreadPalette(data.voiceThreadPalette),
    liveFullscreen: normalizeLiveFullscreenSettings(data.liveFullscreen),
    visualDisplay: normalizeVisualDisplay(data.visualDisplay),
  };
}

export function usePhoneSettings() {
  const [settings, setSettingsState] = useState<PhoneSettings>(DEFAULT_PHONE_SETTINGS);
  const [loaded, setLoaded] = useState(false);
  const pendingSave = useRef<Promise<void>>(Promise.resolve());

  useEffect(() => {
    let alive = true;
    SecureStore.getItemAsync(SETTINGS_KEY)
      .then((raw) => {
        if (!alive || !raw) {
          return;
        }
        setSettingsState(normalizeSettings(JSON.parse(raw)));
      })
      .catch(() => undefined)
      .finally(() => {
        if (alive) {
          setLoaded(true);
        }
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!loaded) {
      return;
    }
    const snapshot = JSON.stringify(settings);
    pendingSave.current = pendingSave.current
      .then(() => SecureStore.setItemAsync(SETTINGS_KEY, snapshot))
      .catch(() => undefined);
  }, [loaded, settings]);

  const setSettings = useCallback((updates: Partial<PhoneSettings>) => {
    setSettingsState((current) => normalizeSettings({ ...current, ...updates }));
  }, []);

  const setLiveFullscreenSettings = useCallback((updates: Partial<LiveFullscreenSettings>) => {
    setSettingsState((current) => normalizeSettings({
      ...current,
      liveFullscreen: {
        ...current.liveFullscreen,
        ...updates,
      },
    }));
  }, []);

  return {
    loaded,
    settings,
    setLiveFullscreenSettings,
    setSettings,
  };
}
