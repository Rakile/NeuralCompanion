import type {SoundMedia} from '../api/soundscape';
import {soundscapeNative} from '../native/soundscape';

export type CachedSound={fileToken:string;bytes:number;hash:string;release():Promise<void>};
export interface SoundCacheIO {
  fileBegin(scope:string,hash:string,bytes:number):Promise<{token:string;ready:boolean}>;
  fileWrite(token:string,offset:number,data:string):Promise<boolean>;
  fileFinish(token:string):Promise<boolean>;
  fileForget(token:string):Promise<boolean>;
}
export function validateSoundMedia(value:SoundMedia) {
  if(!value || !/^[a-f0-9]{64}$/.test(value.sha256) || !Number.isSafeInteger(value.byte_length)
      || value.byte_length<1 || value.byte_length>100*1024*1024 || value.sample_rate!==48000
      || value.content_type!=='audio/ogg' || ![1,2].includes(value.channels)
      || value.url_path!==`/api/soundscape/media/${value.sha256}`) throw new Error('Invalid sound media descriptor.');
}
/** Native owns scoped disk LRU, integrity checks and decoder pins; JS owns operation handles. */
export class SoundscapeCache {
  constructor(readonly io:SoundCacheIO=soundscapeNative) {}
  async begin(scope:string,descriptor:SoundMedia) {
    validateSoundMedia(descriptor); if(!scope)throw new Error('Sound cache needs a verified desktop identity.');
    const result=await this.io.fileBegin(scope,descriptor.sha256,descriptor.byte_length);
    let released=false;
    const handle:CachedSound={fileToken:result.token,bytes:descriptor.byte_length,hash:descriptor.sha256,
      release:async()=>{if(!released){released=true;await this.io.fileForget(result.token);}}};
    return {ready:result.ready,handle};
  }
}
