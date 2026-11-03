type ThreadPalette = { accent: string; glow: string };
const unit = (value: number) => Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));

function tint(hex: string, shift: number, amount: number, peakLightness: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const [r, g, b] = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const high = Math.max(r!, g!, b!), low = Math.min(r!, g!, b!);
  const delta = high - low;
  const lightness = (high + low) / 2;
  let hue = 0;
  if (delta) {
    hue = high === r ? ((g! - b!) / delta) % 6
      : high === g ? (b! - r!) / delta + 2 : (r! - g!) / delta + 4;
    hue *= 60;
  }
  const saturation = delta ? delta / (1 - Math.abs(2 * lightness - 1)) : 0;
  const s = saturation + (.96 - saturation) * amount;
  const l = lightness + (peakLightness - lightness) * amount;
  const h = ((hue + shift) % 360 + 360) % 360 / 60;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs(h % 2 - 1));
  const rgb = h < 1 ? [c, x, 0] : h < 2 ? [x, c, 0] : h < 3 ? [0, c, x]
    : h < 4 ? [0, x, c] : h < 5 ? [x, 0, c] : [c, 0, x];
  return '#' + rgb.map(value => Math.round(unit(value + l - c / 2) * 255).toString(16).padStart(2, '0')).join('');
}

/** Color follows the same smoothed PCM envelope and syllable attack as motion.
 * No wall clock/random hue cycle: silence returns the selected state palette.
 */
export function silkAudioColors(palette: ThreadPalette, level: number, transient: number, response: number) {
  const strength = unit(response / 150) * 1.5;
  const energy = unit(level), attack = unit(transient);
  const amount = unit((energy * .85 + attack * .5) * strength);
  if (!amount) return { ...palette, highlight: '#ffffff' };
  const shift = Math.min(90, (energy * 54 + attack * 28) * strength);
  const accent = tint(palette.accent, -shift, amount, .66);
  const glow = tint(palette.glow, shift * .7, amount, .58);
  const highlight = /^#[0-9a-f]{6}$/i.test(accent)
    ? '#' + [1, 3, 5].map(offset => Math.round(255 + (parseInt(accent.slice(offset, offset + 2), 16) - 255)
      * amount * .6).toString(16).padStart(2, '0')).join('')
    : '#ffffff';
  return { accent, glow, highlight };
}
