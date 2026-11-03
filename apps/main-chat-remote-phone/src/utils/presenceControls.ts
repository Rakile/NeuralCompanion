export const VOICE_THREAD_PALETTES = ['state', 'spectrum', 'electric'] as const;

export type VoiceThreadPalette = typeof VOICE_THREAD_PALETTES[number];

export function normalizeVoiceThreadPalette(value: unknown): VoiceThreadPalette {
  return VOICE_THREAD_PALETTES.includes(value as VoiceThreadPalette)
    ? value as VoiceThreadPalette
    : 'state';
}

export function presenceHeaderVisibility(showControls: boolean): {
  identity: boolean;
  modes: boolean;
  thread: true;
} {
  return {
    identity: Boolean(showControls),
    modes: Boolean(showControls),
    thread: true,
  };
}

export function primaryNavigationMetrics(bottomInset: number): {
  bottomPadding: number;
  itemMinHeight: 44;
  topPadding: 2;
} {
  const inset = Number.isFinite(bottomInset) ? Math.max(0, bottomInset) : 0;
  return {
    bottomPadding: Math.max(2, inset),
    itemMinHeight: 44,
    topPadding: 2,
  };
}
