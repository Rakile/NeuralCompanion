export const SPECTRUM_FPS = 24;
export const SPECTRUM_BARS = 48;
export const MIC_METER_STALE_AFTER_MS = 350;
const MAX_FRAMES = SPECTRUM_FPS * 60 * 10;
const BASE64_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const PLAYBACK_FALLBACK_RELEASE = 0.92;
const MIC_HISTORY_RELEASE_PER_FRAME = 0.88;

export type SpectrumSource = 'analyzed' | 'live' | 'procedural' | 'idle';
export type SpectrumMotionActivity = 'idle' | 'listening' | 'thinking' | 'speaking';

export type SpectrumTimeline = {
  fps: 24;
  bars: 48;
  frames: number[][];
};

type SpectrumPayload = {
  version?: unknown;
  fps?: unknown;
  bars?: unknown;
  frame_count?: unknown;
  encoding?: unknown;
  data?: unknown;
};

function decodeBase64(value: string): Uint8Array {
  const clean = value.replace(/\s+/g, '').replace(/=+$/, '');
  if (!clean || clean.length % 4 === 1) {
    throw new Error('Spectrum data is invalid.');
  }
  const output: number[] = [];
  let buffer = 0;
  let bits = 0;
  for (const character of clean) {
    const index = BASE64_ALPHABET.indexOf(character);
    if (index < 0) {
      throw new Error('Spectrum data is invalid.');
    }
    buffer = (buffer << 6) | index;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      output.push((buffer >> bits) & 0xff);
    }
  }
  return Uint8Array.from(output);
}

export function decodeSpectrumTimeline(payload: SpectrumPayload): SpectrumTimeline {
  const frameCount = Number(payload?.frame_count);
  if (
    Number(payload?.version) !== 1
    || Number(payload?.fps) !== SPECTRUM_FPS
    || Number(payload?.bars) !== SPECTRUM_BARS
    || payload?.encoding !== 'uint8-base64'
    || !Number.isInteger(frameCount)
    || frameCount < 1
    || frameCount > MAX_FRAMES
    || typeof payload?.data !== 'string'
  ) {
    throw new Error('Spectrum metadata is incompatible.');
  }
  const decoded = decodeBase64(payload.data);
  if (decoded.length !== frameCount * SPECTRUM_BARS) {
    throw new Error('Spectrum data length does not match its metadata.');
  }
  const frames: number[][] = [];
  for (let frameIndex = 0; frameIndex < frameCount; frameIndex += 1) {
    const offset = frameIndex * SPECTRUM_BARS;
    frames.push(Array.from(decoded.slice(offset, offset + SPECTRUM_BARS), (entry) => entry / 255));
  }
  return { fps: SPECTRUM_FPS, bars: SPECTRUM_BARS, frames };
}

export function frameAtPlaybackTime(timeline: SpectrumTimeline, seconds: number): number[] {
  if (!timeline.frames.length) {
    return Array(SPECTRUM_BARS).fill(0);
  }
  const position = Math.max(0, Number(seconds) || 0) * timeline.fps;
  const firstIndex = Math.min(timeline.frames.length - 1, Math.floor(position));
  const secondIndex = Math.min(timeline.frames.length - 1, firstIndex + 1);
  const mix = Math.max(0, Math.min(1, position - firstIndex));
  const firstFrame = timeline.frames[firstIndex]!;
  const secondFrame = timeline.frames[secondIndex]!;
  return firstFrame.map((value, index) => (
    value + ((secondFrame[index] ?? value) - value) * mix
  ));
}

export function hasSpectrumFrameAtTime(timeline: SpectrumTimeline, seconds: number): boolean {
  const framePosition = Math.max(0, Number(seconds) || 0) * timeline.fps;
  return framePosition < timeline.frames.length;
}

export function playbackSpectrumFrame(
  timeline: SpectrumTimeline | undefined,
  seconds: number,
  liveSample: readonly number[] | null | undefined,
  fallbackEnergies?: readonly number[] | null,
): { energies: number[]; source: SpectrumSource } {
  if (timeline && hasSpectrumFrameAtTime(timeline, seconds)) {
    return {
      energies: frameAtPlaybackTime(timeline, seconds),
      source: 'analyzed',
    };
  }
  if (liveSample?.length) {
    return {
      energies: Array.from(liveSample),
      source: 'live',
    };
  }
  return {
    energies: fixedPlaybackFallback(fallbackEnergies),
    source: 'procedural',
  };
}

export function selectSpectrumSource(hasAnalyzed: boolean, hasLive: boolean): Exclude<SpectrumSource, 'idle'> {
  if (hasAnalyzed) {
    return 'analyzed';
  }
  return hasLive ? 'live' : 'procedural';
}

export function normalizeMicLevel(meteringDb: number | null | undefined): number {
  const parsed = Number(meteringDb);
  if (!Number.isFinite(parsed)) {
    return 0;
  }
  return Math.max(0, Math.min(1, (parsed + 60) / 60));
}

export function smoothMicDisplayLevel(
  previous: number,
  meteringDb: number | null | undefined,
): number {
  const prior = Math.max(0, Math.min(1, Number(previous) || 0));
  const target = normalizeMicLevel(meteringDb);
  const blend = target > prior ? 0.72 : 0.12;
  return Math.max(0, Math.min(1, prior + (target - prior) * blend));
}

export function microphoneVuSpectrum(level: number): number[] {
  const normalized = Math.max(0, Math.min(1, Number(level) || 0));
  if (normalized <= 0.04) {
    return Array(SPECTRUM_BARS).fill(0);
  }
  const audible = (normalized - 0.04) / 0.96;
  const halfSpan = (SPECTRUM_BARS - 1) / 2;
  return Array.from({ length: SPECTRUM_BARS }, (_, index) => {
    const mirrored = Math.min(index, SPECTRUM_BARS - 1 - index);
    const envelope = 0.55 + 0.45 * Math.sin((mirrored / halfSpan) * Math.PI / 2);
    return Math.max(0, Math.min(1, audible * envelope));
  });
}

export function previewMicrophoneVuSpectrum(level: number): number[] {
  return microphoneVuSpectrum(level);
}

export type LiveFullscreenEnergyInputs = {
  ttsEnergies: readonly number[] | null | undefined;
  ttsPlaybackActive: boolean;
  microphoneEnergies: readonly number[] | null | undefined;
  barCount?: number;
};

export type LiveFullscreenEnergies = {
  outerEnergies: number[];
  innerEnergies: number[];
};

export function composeLiveFullscreenEnergies({
  ttsEnergies,
  ttsPlaybackActive,
  microphoneEnergies,
  barCount = SPECTRUM_BARS,
}: LiveFullscreenEnergyInputs): LiveFullscreenEnergies {
  const count = Math.max(1, Math.round(Number(barCount) || SPECTRUM_BARS));
  return {
    outerEnergies: ttsPlaybackActive
      ? resampleSpectrum(ttsEnergies || [], count)
      : Array(count).fill(0),
    innerEnergies: resampleSpectrum(microphoneEnergies || [], count),
  };
}

export type MicMeterFreshnessInputs = {
  microphoneActive: boolean;
  meteringDb: unknown;
  sampleUpdatedAtMs: number;
  nowMs: number;
  staleAfterMs?: number;
};

export function freshMicMeteringDb({
  microphoneActive,
  meteringDb,
  sampleUpdatedAtMs,
  nowMs,
  staleAfterMs = MIC_METER_STALE_AFTER_MS,
}: MicMeterFreshnessInputs): number | undefined {
  if (
    !microphoneActive
    || typeof meteringDb !== 'number'
    || !Number.isFinite(meteringDb)
    || !Number.isFinite(sampleUpdatedAtMs)
    || !Number.isFinite(nowMs)
  ) {
    return undefined;
  }
  const boundedTimeoutMs = Math.max(100, Math.min(2_000, Number(staleAfterMs) || 0));
  const ageMs = Math.max(0, nowMs - sampleUpdatedAtMs);
  return ageMs <= boundedTimeoutMs ? meteringDb : undefined;
}

export type MicEnvelopeState = {
  level: number;
  frameTimeMs: number;
  meteringRevision: number | null;
  sampleUpdatedAtMs: number | null;
};

export type MicEnvelopeInputs = {
  frameTimeMs: number;
  microphoneActive: boolean;
  meteringDb: unknown;
  meteringRevision: number;
};

export function createMicEnvelopeState(frameTimeMs = 0): MicEnvelopeState {
  return {
    level: 0,
    frameTimeMs: Math.max(0, Number(frameTimeMs) || 0),
    meteringRevision: null,
    sampleUpdatedAtMs: null,
  };
}

function advanceMicLevel(previous: number, meteringDb: unknown, elapsedMs: number): number {
  const prior = Math.max(0, Math.min(1, Number(previous) || 0));
  const target = normalizeMicLevel(
    typeof meteringDb === 'number' ? meteringDb : undefined,
  );
  const perFrameBlend = target > prior ? 0.72 : 0.12;
  const elapsedFrames = Math.max(0, Number(elapsedMs) || 0) / (1000 / SPECTRUM_FPS);
  const blend = 1 - Math.pow(1 - perFrameBlend, elapsedFrames);
  return Math.max(0, Math.min(1, prior + (target - prior) * blend));
}

export function advanceMicEnvelopeState(
  previous: MicEnvelopeState,
  input: MicEnvelopeInputs,
): MicEnvelopeState {
  const frameTimeMs = Math.max(0, Number(input.frameTimeMs) || 0);
  const timeReset = frameTimeMs < previous.frameTimeMs;
  const elapsedMs = timeReset ? 0 : frameTimeMs - previous.frameTimeMs;
  const parsedRevision = Number(input.meteringRevision);
  const nativeRevision = Number.isFinite(parsedRevision) ? parsedRevision : null;
  let meteringRevision = timeReset ? null : previous.meteringRevision;
  let sampleUpdatedAtMs = timeReset ? null : previous.sampleUpdatedAtMs;

  if (!input.microphoneActive) {
    meteringRevision = null;
    sampleUpdatedAtMs = null;
  } else if (nativeRevision !== null && nativeRevision !== meteringRevision) {
    meteringRevision = nativeRevision;
    sampleUpdatedAtMs = frameTimeMs;
  }

  const freshMeteringDb = freshMicMeteringDb({
    microphoneActive: input.microphoneActive,
    meteringDb: input.meteringDb,
    sampleUpdatedAtMs: sampleUpdatedAtMs ?? Number.NEGATIVE_INFINITY,
    nowMs: frameTimeMs,
  });
  return {
    level: advanceMicLevel(previous.level, freshMeteringDb, elapsedMs),
    frameTimeMs,
    meteringRevision,
    sampleUpdatedAtMs,
  };
}

export type MicSpectrumHistoryState = {
  energies: number[];
  envelope: MicEnvelopeState;
  meteringRevision: number | null;
};

export function createMicSpectrumHistoryState(frameTimeMs = 0): MicSpectrumHistoryState {
  return {
    energies: Array(SPECTRUM_BARS).fill(0),
    envelope: createMicEnvelopeState(frameTimeMs),
    meteringRevision: null,
  };
}

export function advanceMicSpectrumHistoryState(
  previous: MicSpectrumHistoryState,
  input: MicEnvelopeInputs,
): MicSpectrumHistoryState {
  const frameTimeMs = Math.max(0, Number(input.frameTimeMs) || 0);
  const timeReset = frameTimeMs < previous.envelope.frameTimeMs;
  const prior = timeReset ? createMicSpectrumHistoryState(frameTimeMs) : previous;
  const elapsedMs = Math.max(0, frameTimeMs - prior.envelope.frameTimeMs);
  const parsedRevision = Number(input.meteringRevision);
  const nativeRevision = Number.isFinite(parsedRevision) ? parsedRevision : null;
  const acceptedNewSample = Boolean(
    input.microphoneActive
    && nativeRevision !== null
    && nativeRevision !== prior.envelope.meteringRevision
  );
  const envelope = advanceMicEnvelopeState(prior.envelope, input);
  let energies = prior.energies;

  if (acceptedNewSample) {
    energies = [
      ...prior.energies.slice(1),
      Math.max(0, Math.min(1, envelope.level)),
    ];
  } else {
    const sampleAgeMs = envelope.sampleUpdatedAtMs === null
      ? Number.POSITIVE_INFINITY
      : Math.max(0, frameTimeMs - envelope.sampleUpdatedAtMs);
    const staleOrInactive = !input.microphoneActive
      || sampleAgeMs > MIC_METER_STALE_AFTER_MS;
    if (staleOrInactive && prior.energies.some((value) => value > 0)) {
      const elapsedFrames = elapsedMs / (1000 / SPECTRUM_FPS);
      const release = Math.pow(MIC_HISTORY_RELEASE_PER_FRAME, elapsedFrames);
      energies = prior.energies.map((value) => {
        const next = Math.max(0, Math.min(1, Number(value) || 0)) * release;
        return next < 0.001 ? 0 : next;
      });
    }
  }

  return {
    energies,
    envelope,
    meteringRevision: envelope.meteringRevision,
  };
}

export function spectrumFrameIntervalMs(fps: number): number {
  const boundedFps = Math.max(12, Math.min(60, Math.round(Number(fps) || SPECTRUM_FPS)));
  return 1000 / boundedFps;
}

export function shouldPublishSpectrumFrame(
  nowMs: number,
  lastPublishedAtMs: number,
  fps: number,
): boolean {
  return Math.max(0, Number(nowMs) - Number(lastPublishedAtMs))
    >= spectrumFrameIntervalMs(fps);
}

export function spectrumPhaseAtTime(
  elapsedMs: number,
  speed: number,
  intensityPct: number,
): number {
  return advanceSpectrumPhase(0, elapsedMs, speed, intensityPct);
}

export function spectrumRotationPhase(
  activity: SpectrumMotionActivity,
  elapsedMs: number,
  speed: number,
  rotationSpeedPct: number,
): number {
  if (activity === 'speaking' || activity === 'listening') {
    return 0;
  }
  return spectrumPhaseAtTime(elapsedMs, speed, rotationSpeedPct);
}

export function fixedPlaybackFallback(
  previous: readonly number[] | null | undefined,
): number[] {
  if (previous?.length && previous.some((value) => Number(value) > 0.001)) {
    const normalized = previous.length === SPECTRUM_BARS
      ? Array.from(previous, (value) => Math.max(0, Math.min(1, Number(value) || 0)))
      : resampleSpectrum(previous, SPECTRUM_BARS);
    return normalized.map((value) => value * PLAYBACK_FALLBACK_RELEASE);
  }
  return Array(SPECTRUM_BARS).fill(0);
}

export function sampleToSpectrum(
  channels: ReadonlyArray<{ frames?: readonly number[] }> | null | undefined,
): number[] {
  const usable = (channels || []).map((channel) => channel.frames || []).filter((frames) => frames.length);
  if (!usable.length) {
    return Array(SPECTRUM_BARS).fill(0);
  }
  const frameCount = Math.max(...usable.map((frames) => frames.length));
  const mono = Array.from({ length: frameCount }, (_, frameIndex) => {
    let total = 0;
    let count = 0;
    for (const frames of usable) {
      if (frameIndex < frames.length) {
        total += Math.abs(Number(frames[frameIndex] || 0));
        count += 1;
      }
    }
    return count ? total / count : 0;
  });
  return Array.from({ length: SPECTRUM_BARS }, (_, band) => {
    const start = Math.floor((band * mono.length) / SPECTRUM_BARS);
    const end = Math.max(start + 1, Math.floor(((band + 1) * mono.length) / SPECTRUM_BARS));
    let peak = 0;
    for (let index = start; index < Math.min(mono.length, end); index += 1) {
      peak = Math.max(peak, mono[index] || 0);
    }
    return Math.max(0, Math.min(1, peak));
  });
}

export function resampleSpectrum(energies: readonly number[], barCount: number): number[] {
  const count = Math.max(1, Math.round(Number(barCount) || 1));
  if (!energies.length) {
    return Array(count).fill(0);
  }
  const normalized = energies.map((value) => Math.max(0, Math.min(1, Number(value) || 0)));
  if (normalized.length === 1 || count === 1) {
    return Array(count).fill(normalized[0] || 0);
  }
  return Array.from({ length: count }, (_, index) => {
    const sourcePosition = index / (count - 1) * (normalized.length - 1);
    const lowerIndex = Math.floor(sourcePosition);
    const upperIndex = Math.min(normalized.length - 1, lowerIndex + 1);
    const mix = sourcePosition - lowerIndex;
    const lower = normalized[lowerIndex] || 0;
    const upper = normalized[upperIndex] || lower;
    return lower + (upper - lower) * mix;
  });
}

export function smoothSpectrum(previous: readonly number[], next: readonly number[], smoothingPct: number): number[] {
  const smoothing = Math.max(0, Math.min(2, Number(smoothingPct) / 100));
  const retain = smoothing <= 0 ? 0 : Math.min(0.94, 0.35 + smoothing * 0.295);
  return Array.from({ length: SPECTRUM_BARS }, (_, index) => {
    const prior = Number(previous[index] || 0);
    const current = Number(next[index] || 0);
    return Math.max(0, Math.min(1, prior * retain + current * (1 - retain)));
  });
}

export function advanceSpectrumPhase(
  current: number,
  elapsedMs: number,
  speed: number,
  intensityPct: number,
): number {
  const intensity = Math.max(0, Number(intensityPct) / 100);
  return intensity <= 0
    ? current
    : current + Math.max(0, elapsedMs) * Math.max(0, speed) * intensity;
}

export function directionalSpectrumSeconds(seconds: number, rotationSpeedPct: number): number {
  return Number(rotationSpeedPct) <= 0 ? 0 : Math.max(0, Number(seconds) || 0);
}

export function proceduralSpectrum(seconds: number, intensity = 1): number[] {
  const level = Math.max(0, Math.min(1, Number(intensity) || 0));
  return Array.from({ length: SPECTRUM_BARS }, (_, index) => {
    const first = Math.sin(seconds * 8.2 + index * 0.71) * 0.5 + 0.5;
    const second = Math.sin(seconds * 3.7 - index * 0.29) * 0.5 + 0.5;
    return (0.15 + first * 0.55 + second * 0.3) * level;
  });
}
