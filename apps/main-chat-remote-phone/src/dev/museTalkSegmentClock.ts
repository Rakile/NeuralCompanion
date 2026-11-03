import type { ProbeVideoSegment } from './museTalkMatchedSample';

export function segmentAt(segments: readonly ProbeVideoSegment[], seconds: number | null,
  duration: number, liveReply = false): { index: number; localSeconds: number } | null {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0 || !Number.isFinite(duration)
    || duration <= 0 || (!liveReply && duration > 60) || seconds >= duration
    || !segments.length || (!liveReply && segments.length > 120)) return null;
  let end = 0;
  for (const [index, segment] of segments.entries()) {
    if (segment.index !== index || segment.startFrame !== end || !Number.isSafeInteger(segment.frameCount)
      || segment.frameCount <= 0 || segment.frameCount > 24) return null;
    end += segment.frameCount;
    if (!Number.isSafeInteger(end)) return null;
  }
  if (Math.abs(duration - end/24) > 1/24 + .00001) return null;
  const segment = segments.find(s => seconds < (s.startFrame + s.frameCount)/24) ?? segments[segments.length-1]!;
  return { index: segment.index, localSeconds: Math.min(seconds - segment.startFrame/24, (segment.frameCount-1)/24) };
}
