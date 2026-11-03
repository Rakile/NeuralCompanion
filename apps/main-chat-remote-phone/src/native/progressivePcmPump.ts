import type {ProgressivePcmRead} from '../api/types';

const MAX_FRAMES = 1_440_000;
const MAX_READ_FRAMES = 12_000;

export function validateProgressivePcmRead(raw: unknown, cursor: number): ProgressivePcmRead {
  const value = raw as Partial<ProgressivePcmRead> | null;
  const invalid = () => new Error('Invalid progressive audio response.');
  if (!value || value.version !== 1 || value.sample_rate !== 24000 || value.channels !== 1
      || value.cursor !== cursor || !Number.isSafeInteger(value.next_cursor)
      || value.next_cursor! < cursor || value.next_cursor! > MAX_FRAMES
      || value.next_cursor! - cursor > MAX_READ_FRAMES || typeof value.finished !== 'boolean'
      || typeof value.pcm_base64 !== 'string' || value.pcm_base64.length > 32_000
      || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value.pcm_base64)) throw invalid();
  const padding = value.pcm_base64.endsWith('==') ? 2 : value.pcm_base64.endsWith('=') ? 1 : 0;
  const bytes = value.pcm_base64.length / 4 * 3 - padding;
  if (bytes !== (value.next_cursor! - cursor) * 2
      || (value.total_frames !== null && (!Number.isSafeInteger(value.total_frames)
        || value.total_frames! < value.next_cursor! || value.total_frames! > MAX_FRAMES))
      || (value.finished && value.total_frames !== value.next_cursor)) throw invalid();
  return value as ProgressivePcmRead;
}

function waitForPcm(signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    if (signal.aborted) { resolve(); return; }
    const done = () => { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); };
    const timer = setTimeout(done, 40);
    signal.addEventListener('abort', done, {once:true});
  });
}

/** One reader/append in flight. Keep at most 2.5 seconds ahead of the native clock. */
export async function pumpProgressivePcm(options: {
  signal: AbortSignal;
  read(cursor: number): Promise<ProgressivePcmRead>;
  append(cursor: number, base64: string): number | Promise<number>;
  finish(totalFrames: number): boolean | Promise<boolean>;
  positionSeconds(): number;
}): Promise<void> {
  let cursor = 0;
  while (!options.signal.aborted) {
    const position = options.positionSeconds();
    if (cursor / 24000 - (Number.isFinite(position) ? Math.max(0,position) : 0) > 2) {
      await waitForPcm(options.signal); continue;
    }
    const page = validateProgressivePcmRead(await options.read(cursor), cursor);
    if (options.signal.aborted) return;
    if (page.next_cursor > cursor) {
      const next = await options.append(cursor, page.pcm_base64);
      if (options.signal.aborted) return;
      if (next !== page.next_cursor) throw new Error('Progressive audio append was not confirmed.');
      cursor = next;
    }
    if (page.finished) {
      if (await options.finish(cursor) !== true && !options.signal.aborted) throw new Error('Progressive audio completion was not confirmed.');
      return;
    }
    if (page.cursor === page.next_cursor) await waitForPcm(options.signal);
  }
}
