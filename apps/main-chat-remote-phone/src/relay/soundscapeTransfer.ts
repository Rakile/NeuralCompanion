import {Buffer} from 'buffer';
import type {SoundMedia,SoundKind} from '../api/soundscape';
import {SoundscapeCache,type CachedSound} from './soundscapeCache';
import {soundscapeNative} from '../native/soundscape';

const PART=256*1024;
let sequence=0;
export const soundRequestId=()=>`sound-${Date.now()}-${++sequence}-${Math.random().toString(36).slice(2,10)}`;
export interface SoundTransport {
  scope():string;
  busy():boolean;
  part(hash:string,offset:number,length:number,signal:AbortSignal):Promise<Uint8Array>;
  json?<T>(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal?:AbortSignal):Promise<T>;
}
function live(signal:AbortSignal,scope:string,current:string) {
  if(signal.aborted || !scope || scope!==current) throw new Error('Sound transfer cancelled or desktop changed.');
}
function wait(ms:number,signal:AbortSignal):Promise<void> {
  if(signal.aborted)return Promise.reject(new Error('Sound transfer cancelled.'));
  return new Promise((resolve,reject)=>{
    const abort=()=>{clearTimeout(timer);signal.removeEventListener('abort',abort);reject(new Error('Sound transfer cancelled.'));};
    const timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},ms);
    signal.addEventListener('abort',abort,{once:true});
  });
}
/** One low-priority part at a time; existing peer heartbeats/control retain priority. */
export class SoundscapeTransfer {
  private tail:Promise<unknown>=Promise.resolve();
  constructor(private readonly transport:SoundTransport,private readonly cache=new SoundscapeCache()) {}
  private async part<T>(scope:string,signal:AbortSignal,operation:()=>Promise<T>):Promise<T> {
    const execute=async()=>{
      live(signal,scope,this.transport.scope());
      while(this.transport.busy()){await wait(80,signal);live(signal,scope,this.transport.scope());}
      const result=await operation(); live(signal,scope,this.transport.scope());
      await wait(0,signal); return result;
    };
    const task=this.tail.then(execute,execute);this.tail=task.catch(()=>undefined);return task;
  }
  async fetch(descriptor:SoundMedia,signal:AbortSignal,onProgress?:(fraction:number)=>void):Promise<CachedSound> {
    const scope=this.transport.scope();live(signal,scope,this.transport.scope());
    const entry=await this.cache.begin(scope,descriptor);
    try {
      live(signal,scope,this.transport.scope());
      if(!entry.ready){
        for(let offset=0;offset<descriptor.byte_length;offset+=PART){
          const length=Math.min(PART,descriptor.byte_length-offset);
          const bytes=await this.part(scope,signal,()=>this.transport.part(descriptor.sha256,offset,length,signal));
          if(bytes.byteLength!==length)throw new Error('Sound transfer length mismatch.');
          await this.cache.io.fileWrite(entry.handle.fileToken,offset,Buffer.from(bytes).toString('base64'));
          live(signal,scope,this.transport.scope());onProgress?.((offset+length)/descriptor.byte_length);
        }
        if(!await this.cache.io.fileFinish(entry.handle.fileToken))throw new Error('Sound file failed integrity verification.');
      }
      live(signal,scope,this.transport.scope());return entry.handle;
    }catch(error){await entry.handle.release().catch(()=>undefined);throw error;}
  }
  async upload(uri:string,filename:string,metadata:{title:string;kind:SoundKind;category?:string;gain?:number;description?:string;tags?:string[];loop?:boolean},
    signal:AbortSignal,onProgress?:(fraction:number)=>void):Promise<{id:string;state:string;existing?:boolean}> {
    const scope=this.transport.scope(),json=this.transport.json?.bind(this.transport);
    if(!json)throw new Error('Sound importing is unavailable.');
    if(!/\.(mp3|m4a|aac|ogg|opus)$/i.test(filename))throw new Error('Import WAV/FLAC on the desktop. Choose MP3, M4A, AAC or Ogg/Opus here.');
    live(signal,scope,this.transport.scope());
    const info=await soundscapeNative.importInfo(uri);live(signal,scope,this.transport.scope());
    let job:string|undefined;
    try {
      const start=await json<{id:string;state:string}>('POST','/api/soundscape/import/init',
        {client_request_id:soundRequestId(),filename,metadata,...info},signal);
      job=start.id;
      if(start.state==='ready')return start;
      for(let offset=0,index=0;offset<info.byte_length;offset+=PART,index++){
        live(signal,scope,this.transport.scope());
        const bytes=await soundscapeNative.importRead(uri,offset,Math.min(PART,info.byte_length-offset));
        await this.part(scope,signal,()=>json('POST','/api/soundscape/import/chunk',
          {client_request_id:soundRequestId(),id:job,index,...bytes},signal));
        onProgress?.(Math.min(offset+PART,info.byte_length)/info.byte_length);
      }
      return await json('POST','/api/soundscape/import/finalize',{client_request_id:soundRequestId(),id:job},signal);
    }catch(error){
      if(job && scope===this.transport.scope())void json('POST','/api/soundscape/import/abort',
        {client_request_id:soundRequestId(),id:job}).catch(()=>undefined);
      throw error;
    }
  }
}
