export type LiveFullscreenPalette = 'spectrum' | 'electric' | 'state';
export type LiveFullscreenBackgroundKind =
  | 'bundled_still'
  | 'bundled_video'
  | 'custom_image'
  | 'custom_video'
  | 'none';
export type LiveFullscreenResizeMode = 'fill' | 'fit';

export type LiveFullscreenSettings = {
  palette: LiveFullscreenPalette;
  circleSizePct: number;
  circleHorizontalPositionPct: number;
  waveformDepthPct: number;
  glowStrengthPct: number;
  audioSmoothingPct: number;
  spectrumFps: number;
  motionIntensityPct: number;
  rotationSpeedPct: number;
  spectrumBarCount: number;
  verticalPositionPct: number;
  autoRevealVisualReply: boolean;
  portalSpeedPct: number;
  edgeSoftnessPct: number;
  imageSpectrumOpacityPct: number;
  backgroundKind: LiveFullscreenBackgroundKind;
  backgroundUri: string;
  backgroundOpacityPct: number;
  backgroundScalePct: number;
  backgroundOffsetXPct: number;
  backgroundOffsetYPct: number;
  backgroundSoftnessPct: number;
  backgroundResizeMode: LiveFullscreenResizeMode;
  pauseVideoForVisual: boolean;
  longPressSeconds: number;
  vibrationEnabled: boolean;
  plongEnabled: boolean;
};

export const DEFAULT_LIVE_FULLSCREEN_SETTINGS: LiveFullscreenSettings = {
  palette: 'spectrum',
  circleSizePct: 100,
  circleHorizontalPositionPct: 50,
  waveformDepthPct: 100,
  glowStrengthPct: 100,
  audioSmoothingPct: 100,
  spectrumFps: 24,
  motionIntensityPct: 100,
  rotationSpeedPct: 100,
  spectrumBarCount: 48,
  verticalPositionPct: 34,
  autoRevealVisualReply: true,
  portalSpeedPct: 100,
  edgeSoftnessPct: 100,
  imageSpectrumOpacityPct: 35,
  backgroundKind: 'bundled_still',
  backgroundUri: '',
  backgroundOpacityPct: 70,
  backgroundScalePct: 100,
  backgroundOffsetXPct: 0,
  backgroundOffsetYPct: 0,
  backgroundSoftnessPct: 0,
  backgroundResizeMode: 'fill',
  pauseVideoForVisual: true,
  longPressSeconds: 3,
  vibrationEnabled: true,
  plongEnabled: true,
};

function bounded(value: unknown, fallback: number, minimum: number, maximum: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(minimum, Math.min(maximum, parsed));
}

function booleanValue(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

function spectrumBarCount(value: unknown, fallback: number): number {
  return Math.round(bounded(value, fallback, 16, 96) / 4) * 4;
}

function enumValue<T extends string>(value: unknown, values: readonly T[], fallback: T): T {
  return values.includes(value as T) ? value as T : fallback;
}

export function normalizeLiveFullscreenSettings(value: unknown): LiveFullscreenSettings {
  const data = value && typeof value === 'object'
    ? value as Partial<LiveFullscreenSettings>
    : {};
  const defaults = DEFAULT_LIVE_FULLSCREEN_SETTINGS;
  return {
    palette: enumValue(data.palette, ['spectrum', 'electric', 'state'] as const, defaults.palette),
    circleSizePct: bounded(data.circleSizePct, defaults.circleSizePct, 25, 200),
    circleHorizontalPositionPct: bounded(
      data.circleHorizontalPositionPct,
      defaults.circleHorizontalPositionPct,
      10,
      90,
    ),
    waveformDepthPct: bounded(data.waveformDepthPct, defaults.waveformDepthPct, 0, 200),
    glowStrengthPct: bounded(data.glowStrengthPct, defaults.glowStrengthPct, 0, 200),
    audioSmoothingPct: bounded(data.audioSmoothingPct, defaults.audioSmoothingPct, 0, 200),
    spectrumFps: Math.round(bounded(data.spectrumFps, defaults.spectrumFps, 12, 60)),
    motionIntensityPct: bounded(data.motionIntensityPct, defaults.motionIntensityPct, 0, 200),
    rotationSpeedPct: bounded(data.rotationSpeedPct, defaults.rotationSpeedPct, 0, 200),
    spectrumBarCount: spectrumBarCount(data.spectrumBarCount, defaults.spectrumBarCount),
    verticalPositionPct: bounded(data.verticalPositionPct, defaults.verticalPositionPct, 10, 90),
    autoRevealVisualReply: booleanValue(data.autoRevealVisualReply, defaults.autoRevealVisualReply),
    portalSpeedPct: bounded(data.portalSpeedPct, defaults.portalSpeedPct, 25, 200),
    edgeSoftnessPct: bounded(data.edgeSoftnessPct, defaults.edgeSoftnessPct, 0, 200),
    imageSpectrumOpacityPct: bounded(data.imageSpectrumOpacityPct, defaults.imageSpectrumOpacityPct, 0, 200),
    backgroundKind: enumValue(
      data.backgroundKind,
      ['bundled_still', 'bundled_video', 'custom_image', 'custom_video', 'none'] as const,
      defaults.backgroundKind,
    ),
    backgroundUri: typeof data.backgroundUri === 'string' ? data.backgroundUri : defaults.backgroundUri,
    backgroundOpacityPct: bounded(data.backgroundOpacityPct, defaults.backgroundOpacityPct, 0, 200),
    backgroundScalePct: bounded(data.backgroundScalePct, defaults.backgroundScalePct, 25, 200),
    backgroundOffsetXPct: bounded(data.backgroundOffsetXPct, defaults.backgroundOffsetXPct, -100, 100),
    backgroundOffsetYPct: bounded(data.backgroundOffsetYPct, defaults.backgroundOffsetYPct, -100, 100),
    backgroundSoftnessPct: bounded(data.backgroundSoftnessPct, defaults.backgroundSoftnessPct, 0, 200),
    backgroundResizeMode: enumValue(data.backgroundResizeMode, ['fill', 'fit'] as const, defaults.backgroundResizeMode),
    pauseVideoForVisual: booleanValue(data.pauseVideoForVisual, defaults.pauseVideoForVisual),
    longPressSeconds: bounded(data.longPressSeconds, defaults.longPressSeconds, 1, 6),
    vibrationEnabled: booleanValue(data.vibrationEnabled, defaults.vibrationEnabled),
    plongEnabled: booleanValue(data.plongEnabled, defaults.plongEnabled),
  };
}
