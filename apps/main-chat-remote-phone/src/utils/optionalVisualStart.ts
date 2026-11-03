import type { AudioChunk } from '../api/types';

export type OptionalVisualStart = (chunk: AudioChunk, signal: AbortSignal, deadlineMs: number) => Promise<void> | void;

// Finite budgets fail open. Infinity explicitly waits for MuseTalk's return
// frame; cancellation and actual visual failures still release the queue.
export function boundedVisualStart(callback: OptionalVisualStart, chunk: AudioChunk,
  signal: AbortSignal, deadlineMs: number): Promise<void> {
  if (signal.aborted) return Promise.resolve();
  if (performance.now() >= deadlineMs) {
    // Notify the visual owner so an armed trial cannot accidentally claim the
    // next reply. Never await visual cleanup after the audio budget expires.
    try { void Promise.resolve(callback(chunk, signal, deadlineMs)).catch(() => {}); }
    catch { /* Optional visuals fail open. */ }
    return Promise.resolve();
  }
  return new Promise(resolve => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true; clearTimeout(timer); signal.removeEventListener('abort', finish); resolve();
    };
    const timer = deadlineMs === Infinity ? undefined
      : setTimeout(finish, Math.max(0, deadlineMs-performance.now()));
    signal.addEventListener('abort', finish, {once: true});
    try { Promise.resolve(callback(chunk, signal, deadlineMs)).then(finish, finish); }
    catch { finish(); }
  });
}
