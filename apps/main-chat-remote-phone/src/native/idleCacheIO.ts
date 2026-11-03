import type {IdleCacheIO,VerifiedLoop} from '../relay/idleLoopCache';
import {IDLE_WRITE_LIMIT} from '../relay/idleLoopCache';
type NativeIdleIO = {
  ncIdleCacheVersion():number;
  ncIdleCacheSelect(scope:string,avatar:string):Promise<string>;
  ncIdleCacheBegin(generation:string,id:string,bytes:number,sha256:string):Promise<string>;
  ncIdleCacheAppend(handle:string,offset:number,bytes:Uint8Array):Promise<void>;
  ncIdleCacheFinish(handle:string):Promise<VerifiedLoop>;
  ncIdleCacheAbort(handle:string):Promise<void>;
  ncIdleCacheInvalidate(generation:string):Promise<void>;
  ncIdleCacheGet(generation:string,id:string):Promise<VerifiedLoop|null>;
  ncIdleCacheUsage():Promise<{bytes:number;limit:number}>;
};
export function createNativeIdleCacheIO():IdleCacheIO|null {
  let native:NativeIdleIO|null;
  try { native=(require('expo') as typeof import('expo')).requireOptionalNativeModule<NativeIdleIO>('ExpoAudio');
    if(native?.ncIdleCacheVersion()!==2) return null;
  } catch { return null; }
  const module=native;
  return {
    select:(scope,avatar)=>module.ncIdleCacheSelect(scope,avatar),
    begin:(generation,id,bytes,sha256)=>module.ncIdleCacheBegin(generation,id,bytes,sha256),
    async append(handle,offset,chunk) {
      if(!Number.isSafeInteger(offset) || offset<0 || chunk.length<1 || chunk.length>IDLE_WRITE_LIMIT) throw new Error('Invalid idle IO range.');
      // Expo converts Uint8Array directly to Android ByteArray / iOS Data.
      // Never expand every byte into a boxed JavaScript/native number.
      await module.ncIdleCacheAppend(handle,offset,chunk);
    },
    finish:handle=>module.ncIdleCacheFinish(handle),abort:handle=>module.ncIdleCacheAbort(handle),
    invalidate:generation=>module.ncIdleCacheInvalidate(generation),
    get:(generation,id)=>module.ncIdleCacheGet(generation,id),usage:()=>module.ncIdleCacheUsage(),
  };
}
