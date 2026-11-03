// Disposable probe policies, not production playback defaults.
export type ProbeKey = { owner: string; reply: string; chunk: string; revision: number };
export type ClockSample = {
  key: ProbeKey; seconds: number; sampledAtMs: number; playing: boolean; buffering: boolean;
};
export type TimedFrame = { index: number; ptsSeconds: number; uri: string; width: number; height: number };
export type ClockPolicy = { maxSampleAgeMs: number; maxExtrapolationMs: number };
export const sameKey = (a: ProbeKey, b: ProbeKey) => a.owner === b.owner && a.reply === b.reply
  && a.chunk === b.chunk && a.revision === b.revision;

export function mediaSeconds(sample: ClockSample, key: ProbeKey, nowMs: number, policy: ClockPolicy): number | null {
  const age = nowMs - sample.sampledAtMs;
  if (!sameKey(sample.key, key) || !Number.isFinite(sample.seconds) || sample.seconds < 0
    || !Number.isFinite(age) || age < 0 || !Number.isFinite(policy.maxSampleAgeMs)
    || !Number.isFinite(policy.maxExtrapolationMs) || policy.maxSampleAgeMs < 0
    || policy.maxExtrapolationMs < 0 || age > policy.maxSampleAgeMs) return null;
  return sample.seconds + (sample.playing && !sample.buffering
    ? Math.min(age, policy.maxExtrapolationMs) / 1000 : 0);
}

export function validateFrames(frames: readonly TimedFrame[]): boolean {
  return frames.length <= 4096 && frames.every((frame, i) => Number.isSafeInteger(frame.index)
    && frame.index >= 0 && Number.isFinite(frame.ptsSeconds) && frame.ptsSeconds >= 0
    && typeof frame.uri === 'string' && frame.uri.length > 0
    && Number.isSafeInteger(frame.width) && frame.width > 0 && frame.width <= 4096
    && Number.isSafeInteger(frame.height) && frame.height > 0 && frame.height <= 4096
    && (i === 0 || (frame.index > frames[i - 1]!.index && frame.ptsSeconds > frames[i - 1]!.ptsSeconds)));
}

export function frameAt(frames: readonly TimedFrame[], seconds: number): TimedFrame | null {
  if (!Number.isFinite(seconds) || seconds < 0 || !validateFrames(frames)) return null;
  let selected: TimedFrame | null = null;
  for (const frame of frames) {
    if (frame.ptsSeconds > seconds) break;
    selected = frame;
  }
  return selected;
}

type Entry = { frame: TimedFrame; ready: boolean; discard: boolean };
export class FrameWindow {
  readonly entries = new Map<number, Entry>();
  private closed = false;
  constructor(private limitBytes: number, private limitInFlight: number) {
    if (!Number.isFinite(limitBytes) || limitBytes <= 0 || !Number.isSafeInteger(limitInFlight)
      || limitInFlight < 1 || limitInFlight > 4) throw new Error('Invalid probe buffer limits');
  }
  get bytes(): number { return [...this.entries.values()].reduce((n, e) => n + e.frame.width * e.frame.height * 4, 0); }
  get inFlight(): number { return [...this.entries.values()].filter(e => !e.ready).length; }
  admit(frame: TimedFrame): boolean {
    if (this.closed || this.entries.has(frame.index) || !validateFrames([frame])
      || this.inFlight >= this.limitInFlight || this.bytes + frame.width * frame.height * 4 > this.limitBytes) return false;
    this.entries.set(frame.index, { frame, ready: false, discard: false });
    return true;
  }
  loaded(index: number): boolean {
    const entry = this.entries.get(index);
    if (this.closed || !entry) return false;
    if (entry.discard) { this.entries.delete(index); return false; }
    entry.ready = true;
    return true;
  }
  failed(index: number): void { this.entries.delete(index); }
  retain(indices: Set<number>): void {
    for (const [index, entry] of this.entries) {
      if (indices.has(index)) continue;
      if (entry.ready) this.entries.delete(index);
      else entry.discard = true; // Keep reservation until the pending loader settles.
    }
  }
  close(): void { this.closed = true; this.entries.clear(); }
}

export type PendingSeek = { target: number; at: number } | null;
export function videoStep(target: number | null, actual: number, pending: PendingSeek,
  nowMs: number, stopped: boolean): { kind: 'pause' | 'wait' | 'seek' | 'play' | 'failed' } {
  if (target === null || stopped) return { kind: 'pause' };
  if (!Number.isFinite(actual) || !Number.isFinite(target)) return { kind: 'failed' };
  // Video advances while seeking; a delayed observation may have passed the
  // original target but already converged with the current audio clock.
  if (pending && Math.abs(actual - pending.target) > 0.08 && Math.abs(actual - target) > 0.12) {
    return { kind: nowMs - pending.at >= 2000 ? 'failed' : 'wait' };
  }
  return { kind: Math.abs(actual - target) > 0.12 ? 'seek' : 'play' };
}
