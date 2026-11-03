import type { AudioChunk } from '../api/types';
import type { TimedFrame } from './museTalkProbeClock';

export type ProbeVideoSegment = {
  index: number; startFrame: number; frameCount: number; uri: string; bytes: number;
};
export type ProbeSegmentSet = { framesPerSegment: 12 | 24; segments: ProbeVideoSegment[] };

export type MatchedSample = {
  version: 1;
  audio: { id: string; url_path: string; phone_request_id: string };
  durationSeconds: number;
  frames: TimedFrame[];
  video?: { uri: string };
  segmentSets?: ProbeSegmentSet[];
};

const INVALID_SAMPLE = 'Invalid matched MuseTalk sample';
const ID_PATTERN = /^[A-Za-z0-9_-]{1,160}$/;
const SOURCE_FPS = 24;
const TIMESTAMP_TOLERANCE_SECONDS = 0.00001;

function invalid(): never {
  throw new Error(INVALID_SAMPLE);
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}

export function parseMatchedSample(value: unknown): MatchedSample {
  const input = record(value);
  if (input.version !== 1 || !Number.isFinite(input.durationSeconds)
    || typeof input.durationSeconds !== 'number' || input.durationSeconds <= 0
    || input.durationSeconds > 60 || !Array.isArray(input.frames)
    || input.frames.length < 1 || input.frames.length > 1440) invalid();

  const audioInput = record(input.audio);
  const id = audioInput.id;
  const phoneRequestId = audioInput.phone_request_id;
  if (typeof id !== 'string' || !ID_PATTERN.test(id)
    || typeof phoneRequestId !== 'string' || !ID_PATTERN.test(phoneRequestId)
    || audioInput.url_path !== `/api/audio/file/${id}`) invalid();

  const frames: TimedFrame[] = [];
  const paths = new Set<string>();
  let width: number | null = null;
  let height: number | null = null;
  for (let index = 0; index < input.frames.length; index += 1) {
    const frameInput = record(input.frames[index]);
    const ptsSeconds = frameInput.ptsSeconds;
    const uri = frameInput.uri;
    const frameWidth = frameInput.width;
    const frameHeight = frameInput.height;
    const expectedPts = index / SOURCE_FPS;
    const expectedUri = `/api/dev/musetalk-probe/frame/${index.toString().padStart(8, '0')}.png`;
    if (frameInput.index !== index || typeof ptsSeconds !== 'number'
      || !Number.isFinite(ptsSeconds) || ptsSeconds < 0 || ptsSeconds >= input.durationSeconds
      || Math.abs(ptsSeconds - expectedPts) > TIMESTAMP_TOLERANCE_SECONDS
      || uri !== expectedUri || paths.has(uri)
      || !Number.isSafeInteger(frameWidth) || (frameWidth as number) < 1 || (frameWidth as number) > 4096
      || !Number.isSafeInteger(frameHeight) || (frameHeight as number) < 1 || (frameHeight as number) > 4096
      || (width !== null && frameWidth !== width) || (height !== null && frameHeight !== height)) invalid();
    paths.add(uri);
    width = frameWidth as number;
    height = frameHeight as number;
    frames.push({ index, ptsSeconds, uri, width, height });
  }

  if (Math.abs(input.durationSeconds - (frames.length / SOURCE_FPS))
    > (1 / SOURCE_FPS) + TIMESTAMP_TOLERANCE_SECONDS) invalid();

  let video: { uri: string } | undefined;
  let segmentSets: ProbeSegmentSet[] | undefined;
  if (input.segmentSets !== undefined) {
    if (!Array.isArray(input.segmentSets) || input.segmentSets.length < 1 || input.segmentSets.length > 2) invalid();
    const sizes = new Set<number>();
    let totalBytes = 0;
    segmentSets = input.segmentSets.map(raw => {
      const set = record(raw);
      const size = set.framesPerSegment;
      if ((size !== 12 && size !== 24) || sizes.has(size) || !Array.isArray(set.segments)
        || set.segments.length !== Math.ceil(frames.length / size)) invalid();
      sizes.add(size);
      const segments = set.segments.map((rawSegment, index): ProbeVideoSegment => {
        const item = record(rawSegment);
        const startFrame = index * size;
        const frameCount = Math.min(size, frames.length - startFrame);
        const uri = `/api/dev/musetalk-probe/segment/${size}/${String(index).padStart(8, '0')}.mp4`;
        if (item.index !== index || item.startFrame !== startFrame || item.frameCount !== frameCount
          || item.uri !== uri || !Number.isSafeInteger(item.bytes) || (item.bytes as number) <= 0
          || (item.bytes as number) > 16 * 1024 * 1024) invalid();
        totalBytes += item.bytes as number;
        if (totalBytes > 128 * 1024 * 1024) invalid();
        return { index, startFrame, frameCount, uri, bytes: item.bytes as number };
      });
      return { framesPerSegment: size, segments };
    });
  }
  if (input.video !== undefined) {
    const value = record(input.video);
    if (value.uri !== '/api/dev/musetalk-probe/visual-only.mp4') invalid();
    video = { uri: value.uri };
  }
  return {
    version: 1,
    audio: { id, url_path: `/api/audio/file/${id}`, phone_request_id: phoneRequestId },
    durationSeconds: input.durationSeconds,
    frames,
    ...(video ? { video } : {}),
    ...(segmentSets ? { segmentSets } : {}),
  };
}

export function matchedAudio(sample: MatchedSample, items: readonly AudioChunk[]): AudioChunk | null {
  let match: AudioChunk | null = null;
  for (const item of items) {
    if (item.id !== sample.audio.id || item.url_path !== sample.audio.url_path
      || item.phone_request_id !== sample.audio.phone_request_id) continue;
    if (match !== null) return null;
    match = item;
  }
  return match;
}

export function sampleFrames(sample: MatchedSample, fps: 12 | 24): TimedFrame[] {
  if (fps !== 12 && fps !== 24) invalid();
  return fps === 24 ? [...sample.frames] : sample.frames.filter(frame => frame.index % 2 === 0);
}
