export type SilkSettings = {
  gain: number; quietLift: number; attack: number; release: number; depth: number;
  variation: number; speed: number; strands: number; thickness: number; spread: number;
  density: number; radius: number; highlight: number; colorResponse: number; bandHeight: number; seed: number;
};

// The saved Silk Studio design. Preview width, theme and activity are not phone preferences.
export const DEFAULT_SILK_SETTINGS: SilkSettings = {
  gain: 2.1, quietLift: .65, attack: 22, release: 135, depth: 1.1,
  variation: 78, speed: .6, strands: 7, thickness: .66, spread: .9,
  density: 90, radius: 2.1, highlight: 58, colorResponse: 100, bandHeight: 96, seed: 42,
};

type SilkSlider = {
  key: keyof SilkSettings; label: string; group: 'Voice' | 'Motion' | 'Light';
  minimum: number; maximum: number; step: number; suffix: string;
};

export const SILK_SLIDERS: readonly SilkSlider[] = [
  { key: 'gain', label: 'Voice gain', group: 'Voice', minimum: .5, maximum: 4, step: .1, suffix: '×' },
  { key: 'quietLift', label: 'Quiet voice curve', group: 'Voice', minimum: .4, maximum: 1, step: .05, suffix: '' },
  { key: 'attack', label: 'Attack', group: 'Voice', minimum: 8, maximum: 100, step: 1, suffix: ' ms' },
  { key: 'release', label: 'Release', group: 'Voice', minimum: 60, maximum: 400, step: 5, suffix: ' ms' },
  { key: 'depth', label: 'Wave depth', group: 'Voice', minimum: .25, maximum: 1.8, step: .05, suffix: '×' },
  { key: 'variation', label: 'Motion variation', group: 'Motion', minimum: 0, maximum: 100, step: 1, suffix: '%' },
  { key: 'seed', label: 'Motion seed', group: 'Motion', minimum: 0, maximum: 999, step: 1, suffix: '' },
  { key: 'speed', label: 'Flow speed', group: 'Motion', minimum: .1, maximum: 1.5, step: .05, suffix: '×' },
  { key: 'strands', label: 'Strands', group: 'Motion', minimum: 3, maximum: 11, step: 1, suffix: '' },
  { key: 'thickness', label: 'Thread thickness', group: 'Motion', minimum: .3, maximum: 1.4, step: .02, suffix: ' px' },
  { key: 'spread', label: 'Thread spread', group: 'Motion', minimum: .2, maximum: 1.8, step: .05, suffix: '×' },
  { key: 'density', label: 'Glow density', group: 'Light', minimum: 0, maximum: 150, step: 1, suffix: '%' },
  { key: 'radius', label: 'Glow radius', group: 'Light', minimum: .6, maximum: 6, step: .1, suffix: ' px' },
  { key: 'highlight', label: 'Core highlight', group: 'Light', minimum: 0, maximum: 100, step: 1, suffix: '%' },
  { key: 'colorResponse', label: 'Color response', group: 'Light', minimum: 0, maximum: 150, step: 1, suffix: '%' },
  { key: 'bandHeight', label: 'Ribbon height', group: 'Light', minimum: 44, maximum: 120, step: 2, suffix: ' px' },
];

export function normalizeSilkSettings(value: unknown): SilkSettings {
  const data = value && typeof value === 'object' ? value as Partial<SilkSettings> : {};
  const result = { ...DEFAULT_SILK_SETTINGS };
  for (const { key, minimum, maximum, step } of SILK_SLIDERS) {
    const raw = data[key];
    if (typeof raw !== 'number' || !Number.isFinite(raw)) continue;
    const clamped = Math.max(minimum, Math.min(maximum, raw));
    result[key] = Number((minimum + Math.round((clamped - minimum) / step) * step).toFixed(3));
  }
  return result;
}
