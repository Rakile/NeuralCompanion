export type VoiceThreadMotion = 'still' | 'breathe' | 'inward' | 'travel' | 'spectrum';

const unit = (value: number): number => Math.max(0, Math.min(1, Number(value) || 0));

/** Read the existing player/microphone analysis; procedural motion never adds voice glow. */
export function silkVoiceLevel(
  energies: readonly number[], inputLevel: number, activity: string, source: string,
): number {
  if (activity === 'listening') return unit(inputLevel);
  if (activity !== 'speaking' || source === 'procedural' || !energies.length) return 0;
  return unit(Math.sqrt(energies.reduce((sum, value) => sum + unit(value) ** 2, 0) / energies.length) * 1.4);
}

export function responsiveSilkLevel(raw: number, settings: { gain: number; quietLift: number }): number {
  return unit(Math.max(0, unit(raw) - .004) * settings.gain) ** settings.quietLift;
}

export function smoothSilkLevel(previous: number, target: number, elapsedMs: number, attack = 60, release = 210): number {
  const timeConstant = Math.max(1, target > previous ? attack : release);
  return unit(previous + (unit(target) - previous) * (1 - Math.exp(-Math.max(0, elapsedMs) / timeConstant)));
}

function silkNoise(position: number, seed: number): number {
  const hash = (n: number) => {
    const value = Math.sin(n * 127.13 + seed * 311.71) * 43758.5453;
    return (value - Math.floor(value)) * 2 - 1;
  };
  const cell = Math.floor(position);
  const fraction = position - cell;
  const blend = fraction * fraction * (3 - 2 * fraction);
  return hash(cell) * (1 - blend) + hash(cell + 1) * blend;
}

/** A continuous signed velocity: seeded currents turn without a repeating sine cycle. */
export function silkFlowVelocity(timeSeconds: number, seed: number, variation: number): number {
  return .22 + silkNoise(timeSeconds * .17, seed + 7) * 1.45 * unit(variation);
}

/** Tangent-continuous cubic filaments, with still ends and a soft central envelope. */
export function buildFineSilkPath({ width, height, phase, level, offset, depthScale,
  timeSeconds = phase, seed = 42, variation = .78, spread = .9, bandLevel = level, transient = 0,
}: {
  width: number; height: number; phase: number; level: number; offset: number; depthScale: number;
  timeSeconds?: number; seed?: number; variation?: number; spread?: number; bandLevel?: number; transient?: number;
}): string {
  const w = Math.max(1, Number(width) || 1);
  const h = Math.max(1, Number(height) || 1);
  const depth = Math.max(0, Math.min(2, Number(depthScale) || 0));
  const p = Number.isFinite(phase) ? phase : 0;
  const o = Number.isFinite(offset) ? offset : 0;
  const seconds = Number.isFinite(timeSeconds) ? timeSeconds : 0;
  const v = unit(variation);
  const bend = silkNoise(seconds * .23, seed + 13);
  const wander = silkNoise(seconds * .19, seed + 33);
  const frequency = 3.1 + silkNoise(seconds * .15, seed + 89) * .42;
  const pulseCenter = .5 + silkNoise(seconds * .7, seed + 19) * .35;
  const points = Array.from({ length: 37 }, (_, index) => {
    const t = index / 36;
    const envelope = Math.sin(Math.PI * t) ** 1.48;
    const independent = silkNoise(t * 2.5 + seconds * .37 + o * .17, seed + 71 + o * 17);
    const shared = Math.sin(t * Math.PI * (2.5 + bend * .5 * v) + p * .61 + wander * .5 * v);
    const flowing = Math.sin(t * Math.PI * frequency - p * .43 + o * .19);
    const pulse = unit(transient) * Math.exp(-(((t - pulseCenter) / .14) ** 2));
    const wave = shared * .56 + flowing * .23 + independent * v * .72 + pulse * v;
    const lift = h * (.018 + unit(level) * .21) * depth;
    const separation = o * h * .011 * spread * (.35 + unit(level) * .9) * Math.sin(t * 6.2 - p * .25 + o * .08);
    const detail = (unit(bandLevel) - unit(level) * .4) * h * .038 * v * Math.sin(t * 11.7 + o * .65 + p * .27);
    const y = h / 2 + Math.max(-h * .4, Math.min(h * .4, (wave * lift + separation + detail) * envelope));
    return { x: t * w, y };
  });
  const first = points[0]!;
  let path = `M ${first.x.toFixed(2)} ${first.y.toFixed(2)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    const a = points[Math.max(0, index - 1)]!;
    const b = points[index]!;
    const c = points[index + 1]!;
    const d = points[Math.min(points.length - 1, index + 2)]!;
    path += ` C ${(b.x + (c.x - a.x) / 6).toFixed(2)} ${(b.y + (c.y - a.y) / 6).toFixed(2)}`
      + ` ${(c.x - (d.x - b.x) / 6).toFixed(2)} ${(c.y - (d.y - b.y) / 6).toFixed(2)}`
      + ` ${c.x.toFixed(2)} ${c.y.toFixed(2)}`;
  }
  return path;
}

export type VoiceThreadProfile = {
  offsets: number[];
  points: number;
};

export function voiceThreadProfile({
  fullscreen,
  lowPower = false,
  reducedMotion,
}: {
  fullscreen: boolean;
  lowPower?: boolean;
  reducedMotion: boolean;
}): VoiceThreadProfile {
  if (reducedMotion) return { offsets: [0], points: 20 };
  if (fullscreen && lowPower) return { offsets: [-1, 0, 1], points: 24 };
  return fullscreen
    ? { offsets: [-2, -1, 0, 1, 2], points: 28 }
    : { offsets: [-1, 0, 1], points: 24 };
}

export function voiceThreadPhase({
  frameTimeMs,
  intensityPct,
  motion,
  reducedMotion,
}: {
  frameTimeMs: number;
  intensityPct: number;
  motion: VoiceThreadMotion;
  reducedMotion: boolean;
}): number {
  if (reducedMotion || motion === 'still') return 0;
  const seconds = Math.max(0, Number(frameTimeMs) || 0) / 1000;
  const intensity = Math.max(0, Math.min(2, Number(intensityPct) / 100));
  const direction = motion === 'inward' ? -1 : 1;
  const speed = motion === 'travel' ? 2.4 : motion === 'spectrum' ? 1.8 : 0.84;
  return (seconds * speed * intensity * direction) % (Math.PI * 8);
}

export function buildVoiceThreadPath({
  amplitude,
  depthScale,
  energies,
  height,
  offset,
  phase,
  points,
  verticalOffset = 0,
  width,
}: {
  amplitude: number;
  depthScale: number;
  energies: readonly number[];
  height: number;
  offset: number;
  phase: number;
  points: number;
  verticalOffset?: number;
  width: number;
}): string {
  const pointCount = Math.max(2, Math.round(Number(points) || 2));
  const safeHeight = Math.max(1, Number(height) || 1);
  const safeWidth = Math.max(1, Number(width) || 1);
  const center = safeHeight / 2;
  const segments: string[] = [];
  for (let index = 0; index < pointCount; index += 1) {
    const progress = index / (pointCount - 1);
    const energyIndex = energies.length
      ? Math.min(energies.length - 1, Math.floor(progress * energies.length))
      : 0;
    const energy = Math.max(0, Math.min(1, Number(energies[energyIndex] || 0)));
    const envelope = Math.sin(progress * Math.PI);
    const wave = Math.sin(progress * Math.PI * 5 + phase + offset);
    const y = center + (
      wave * (amplitude + energy * safeHeight * 0.24) * depthScale
      + verticalOffset
    ) * envelope;
    segments.push(`${index ? 'L' : 'M'} ${(progress * safeWidth).toFixed(1)} ${y.toFixed(1)}`);
  }
  return segments.join(' ');
}
