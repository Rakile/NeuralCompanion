import type { PresenceActivity } from '../api/types';
import type { VoiceThreadFrame } from '../hooks/usePresenceSpectrum';
import type { SilkSettings } from './silkSettings';

export type VoiceVisualizerStyle = 'silk' | 'studio_equalizer' | 'centered_pulse' | 'halo_meter';
export type VoiceMeterStyle = Exclude<VoiceVisualizerStyle, 'silk'>;

export const VOICE_VISUALIZER_STYLES: readonly { value: VoiceVisualizerStyle; label: string; detail: string }[] = [
  { value: 'studio_equalizer', label: 'Studio equalizer', detail: 'Rounded frequency bands, from bass to treble.' },
  { value: 'centered_pulse', label: 'Centered pulse', detail: 'Seven centered capsules showing separate frequency ranges.' },
  { value: 'halo_meter', label: 'Halo meter', detail: 'A circular spectrum, from bass to treble clockwise.' },
  { value: 'silk', label: 'Silk threads', detail: 'The original flowing ribbon with your saved tuning.' },
];

export function normalizeVoiceVisualizerStyle(value: unknown): VoiceVisualizerStyle {
  return VOICE_VISUALIZER_STYLES.find(option => option.value === value)?.value || 'silk';
}

export function voiceMeterCount(style: VoiceMeterStyle): number {
  return style === 'centered_pulse' ? 7 : style === 'halo_meter' ? 40 : 25;
}

/** Consume the app's existing PCM/microphone frame; never invent speech from procedural motion. */
export function voiceMeterTargets(frame: VoiceThreadFrame, activity: PresenceActivity, count: number, tuning: SilkSettings): number[] {
  return Array.from({ length: count }, (_, index) => {
    if (frame.enabled === false || (activity !== 'speaking' && activity !== 'listening') || frame.source === 'procedural') return 0;
    const start = Math.floor(index * frame.energies.length / count);
    const end = Math.max(start + 1, Math.ceil((index + 1) * frame.energies.length / count));
    const bands = frame.energies.slice(start, end).map(value => Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0);
    // Microphone metering supplies loudness only; never invent frequency bands.
    const energy = activity === 'listening' ? Math.max(0, Math.min(1, Number(frame.inputLevel) || 0))
      : bands.length ? Math.sqrt(bands.reduce((sum, value) => sum + value ** 2, 0) / bands.length) : 0;
    const audible = Math.max(0, energy - .004);
    const gain = Math.max(.5, Math.min(4, tuning.gain)) / 2.1;
    // Silk's hard-limited gain flattened ordinary spectrum values to 1. This
    // soft response keeps separate bands and stronger syllables distinguishable.
    return (audible * gain / (1 + audible * gain)) ** Math.max(.4, Math.min(1, tuning.quietLift));
  });
}

export type VoiceMeterMark = { x: number; y: number; width: number; height: number; radius: number; opacity: number; rotation: number };

/** Pixel geometry is centered and bounded even inside the compact fullscreen settings preview. */
export function voiceMeterMarks(style: VoiceMeterStyle, width: number, height: number, levels: readonly number[]): VoiceMeterMark[] {
  const w = Math.max(1, Number.isFinite(width) ? width : 1);
  const h = Math.max(1, Number.isFinite(height) ? height : 1);
  const count = voiceMeterCount(style);
  const unit = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));
  return Array.from({ length: count }, (_, index) => {
    const level = unit(levels[index] || 0);
    if (style === 'halo_meter') {
      const ring = Math.min(w, h) * .41;
      const thickness = Math.min(3, ring * .062);
      const length = ring * (.08 + level * .27);
      return { x: w / 2 - thickness / 2, y: h / 2 - ring, width: thickness, height: length,
        radius: thickness / 2, opacity: .25 + level * .7, rotation: index * 360 / count };
    }
    const pulse = style === 'centered_pulse';
    const span = Math.min(w * .88, pulse ? 90 : 224);
    const pitch = span / count;
    const barWidth = Math.min(pulse ? 7 : 5, pitch * .64);
    const focus = pulse ? 1 - Math.abs(index - 3) / 5 : 1;
    const length = Math.min(h * .78, Math.min(pulse ? 7 : 4, h * .1) + level * h * .68 * focus);
    return { x: (w - span) / 2 + index * pitch + (pitch - barWidth) / 2,
      y: pulse ? (h - length) / 2 : h * .88 - length, width: barWidth, height: length,
      radius: barWidth / 2, opacity: .36 + level * .6, rotation: 0 };
  });
}
