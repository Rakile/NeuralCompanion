export const INTERFACE_STYLES = ['classic', 'adaptive', 'flat', 'immersive'] as const;

export type InterfaceStyle = typeof INTERFACE_STYLES[number];

export type InterfaceModePolicy = {
  cards: boolean;
  primaryFirst: boolean;
  immersive: boolean;
  persistentNavigation: boolean;
};

export type ChromeVisibilityState = {
  disconnected?: boolean;
  authorizationError?: boolean;
  recording?: boolean;
  sttBusy?: boolean;
  playing?: boolean;
  playbackError?: boolean;
  visualError?: boolean;
  buddyProviderError?: boolean;
  castError?: boolean;
};

export function normalizeInterfaceStyle(value: unknown): InterfaceStyle {
  return INTERFACE_STYLES.includes(value as InterfaceStyle) ? value as InterfaceStyle : 'classic';
}

export function resolveInterfaceStyle(value: unknown, legacyChatLayout: unknown): InterfaceStyle {
  if (value === undefined || value === null || value === '') {
    return legacyChatLayout === 'clean' ? 'adaptive' : 'classic';
  }
  return normalizeInterfaceStyle(value);
}

export function modePolicy(mode: InterfaceStyle): InterfaceModePolicy {
  if (mode === 'classic') {
    return { cards: true, primaryFirst: false, immersive: false, persistentNavigation: true };
  }
  if (mode === 'flat') {
    return { cards: false, primaryFirst: false, immersive: false, persistentNavigation: true };
  }
  if (mode === 'immersive') {
    return { cards: false, primaryFirst: true, immersive: true, persistentNavigation: false };
  }
  return { cards: false, primaryFirst: true, immersive: false, persistentNavigation: true };
}

export function shouldForceChromeVisible(state: ChromeVisibilityState): boolean {
  return Object.values(state).some(Boolean);
}
