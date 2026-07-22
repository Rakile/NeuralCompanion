import { useCallback, useEffect, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

import { resolveInterfaceStyle } from '../utils/interfaceMode';
import type { InterfaceStyle } from '../utils/interfaceMode';

export type { InterfaceStyle } from '../utils/interfaceMode';

export type SendMode = 'text_only' | 'phone_tts' | 'visual_reply';
export type MicBehavior = 'transcribe_only' | 'send_auto';
export type MuseTalkQuality = 'low_latency' | 'balanced' | 'quality';
export type ChatLayout = 'standard' | 'clean';
export type ChatTextColor = 'white' | 'green' | 'amber' | 'cyan';
export type ChatIndicatorStyle = 'dot' | 'pulse' | 'line' | 'text';

export type PhoneSettings = {
  phoneTtsAutoplay: boolean;
  phoneTtsVolume: number;
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
  interfaceStyle: InterfaceStyle;
};

const SETTINGS_KEY = 'nc-main-chat-remote.phone-settings';
const MIN_POLL_INTERVAL_MS = 900;
const MAX_POLL_INTERVAL_MS = 15000;

export const DEFAULT_PHONE_SETTINGS: PhoneSettings = {
  phoneTtsAutoplay: true,
  phoneTtsVolume: 1,
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
  interfaceStyle: 'classic',
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
  return {
    phoneTtsAutoplay: boolValue(data.phoneTtsAutoplay, DEFAULT_PHONE_SETTINGS.phoneTtsAutoplay),
    phoneTtsVolume: boundedNumber(data.phoneTtsVolume, DEFAULT_PHONE_SETTINGS.phoneTtsVolume, 0, 1),
    playOnBackend: boolValue(data.playOnBackend, DEFAULT_PHONE_SETTINGS.playOnBackend),
    sendMode: enumValue(data.sendMode, ['text_only', 'phone_tts', 'visual_reply'] as const, DEFAULT_PHONE_SETTINGS.sendMode),
    micBehavior: enumValue(data.micBehavior, ['transcribe_only', 'send_auto'] as const, DEFAULT_PHONE_SETTINGS.micBehavior),
    autoReconnect: boolValue(data.autoReconnect, DEFAULT_PHONE_SETTINGS.autoReconnect),
    keepAwake: boolValue(data.keepAwake, DEFAULT_PHONE_SETTINGS.keepAwake),
    pollingIntervalMs: Math.round(boundedNumber(data.pollingIntervalMs, DEFAULT_PHONE_SETTINGS.pollingIntervalMs, MIN_POLL_INTERVAL_MS, MAX_POLL_INTERVAL_MS)),
    museTalkQuality: enumValue(data.museTalkQuality, ['low_latency', 'balanced', 'quality'] as const, DEFAULT_PHONE_SETTINGS.museTalkQuality),
    chatLayout: enumValue(data.chatLayout, ['standard', 'clean'] as const, DEFAULT_PHONE_SETTINGS.chatLayout),
    chatTextColor: enumValue(data.chatTextColor, ['white', 'green', 'amber', 'cyan'] as const, DEFAULT_PHONE_SETTINGS.chatTextColor),
    chatIndicatorStyle: enumValue(data.chatIndicatorStyle, ['dot', 'pulse', 'line', 'text'] as const, DEFAULT_PHONE_SETTINGS.chatIndicatorStyle),
    interfaceStyle: resolveInterfaceStyle(data.interfaceStyle, data.chatLayout),
  };
}

export function usePhoneSettings() {
  const [settings, setSettingsState] = useState<PhoneSettings>(DEFAULT_PHONE_SETTINGS);
  const [loaded, setLoaded] = useState(false);

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
    SecureStore.setItemAsync(SETTINGS_KEY, JSON.stringify(settings)).catch(() => undefined);
  }, [loaded, settings]);

  const setSettings = useCallback((updates: Partial<PhoneSettings>) => {
    setSettingsState((current) => normalizeSettings({ ...current, ...updates }));
  }, []);

  return {
    loaded,
    settings,
    setSettings,
  };
}
