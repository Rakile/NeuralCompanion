import {requireOptionalNativeModule} from 'expo';
import {Platform} from 'react-native';
import type {AudioChunk, PhoneReplyAuth} from '../api/types';
import type {RemoteClient} from '../api/client';
import {pumpProgressivePcm} from './progressivePcmPump';

type ProgressiveModule = {
  ncProgressivePcmVersion(): number;
  ncProgressivePcmOpen(): string | Promise<string>;
  ncProgressivePcmAppend(id:string,cursor:number,base64:string): number | Promise<number>;
  ncProgressivePcmFinish(id:string,totalFrames:number): boolean | Promise<boolean>;
  ncProgressivePcmClose(id:string): boolean | Promise<boolean>;
};

function progressiveModule(): ProgressiveModule | null {
  if (Platform.OS !== 'android') return null;
  try {
    const module = requireOptionalNativeModule<ProgressiveModule>('ExpoAudio');
    return module?.ncProgressivePcmVersion?.() === 1
      && ['ncProgressivePcmOpen','ncProgressivePcmAppend','ncProgressivePcmFinish','ncProgressivePcmClose']
        .every(key => typeof (module as unknown as Record<string,unknown>)[key] === 'function') ? module : null;
  } catch { return null; }
}

export function progressivePcmAvailable(): boolean { return progressiveModule() !== null; }

export type ProgressivePcmSource = {
  uri: string;
  start(positionSeconds: () => number, onFailure: (error: unknown) => void): void;
  close(): void;
};

export async function openProgressivePcmSource(client: RemoteClient, auth: PhoneReplyAuth,
  chunk: AudioChunk, signal: AbortSignal): Promise<ProgressivePcmSource> {
  const native = progressiveModule();
  if (!native || chunk.progressive_audio?.version !== 1 || chunk.progressive_audio.sample_rate !== 24000
    || chunk.progressive_audio.channels !== 1 || !chunk.phone_request_id || !Number.isInteger(chunk.sequence_index)
    || chunk.sequence_index! < 0 || signal.aborted) throw new Error('Progressive audio is unavailable.');
  const id = await native.ncProgressivePcmOpen();
  if (typeof id !== 'string' || !/^[A-Za-z0-9_-]{1,128}$/.test(id)) throw new Error('Progressive audio source was not opened.');
  const abort = new AbortController();
  let closed = false, started = false;
  const close = () => {
    if (closed) return;
    closed = true; abort.abort(); signal.removeEventListener('abort',close);
    try { void Promise.resolve(native.ncProgressivePcmClose(id)).catch(() => undefined); }
    catch { /* Stop still releases the guarded player. */ }
  };
  signal.addEventListener('abort',close,{once:true});
  if (signal.aborted) { close(); throw new Error('Progressive audio cancelled.'); }
  return {
    uri: `nc-progressive-pcm://${id}`,
    close,
    start(positionSeconds,onFailure) {
      if (started || closed) return;
      started = true;
      void pumpProgressivePcm({signal:abort.signal,positionSeconds,
        read:cursor=>client.readProgressiveAudio(auth,chunk,cursor,abort.signal),
        append:(cursor,base64)=>native.ncProgressivePcmAppend(id,cursor,base64),
        finish:total=>native.ncProgressivePcmFinish(id,total),
      }).catch(error=>{ if (!closed) { close(); onFailure(error); } });
    },
  };
}
