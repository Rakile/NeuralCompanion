/** Persistent byte pins do not confer playback or microphone ownership. */
export type OrderedIdlePin=Readonly<{pin:string;uri:string;bytes:number}>;
export type OrderedIdleUsage=Readonly<{bytes:number;limit:number;files:number;pins:number;reason:string}>;
export interface OrderedIdleCacheIO {
  acquire(scope:string,digest:string,bytes:number,epoch:number):Promise<OrderedIdlePin|null>;
  importFile(scope:string,digest:string,bytes:number,epoch:number,uri:string):Promise<boolean>;
  release(pin:string):Promise<void>;
  clear(scope:string,epoch:number,force?:boolean):Promise<void>;
  usage():Promise<OrderedIdleUsage>;
}
type Native={
  ncOrderedIdleCacheVersion():number;
  ncOrderedIdleCacheAcquire:OrderedIdleCacheIO['acquire'];
  ncOrderedIdleCacheImport:OrderedIdleCacheIO['importFile'];
  ncOrderedIdleCacheRelease:OrderedIdleCacheIO['release'];
  ncOrderedIdleCacheClear:OrderedIdleCacheIO['clear'];
  ncOrderedIdleCacheUsage:OrderedIdleCacheIO['usage'];
};
export function createNativeOrderedIdleCacheIO():OrderedIdleCacheIO|null {
  let native:Native|null;
  try {
    native=(require('expo') as typeof import('expo')).requireOptionalNativeModule<Native>('ExpoAudio');
    if(native?.ncOrderedIdleCacheVersion()!==1)return null;
  } catch {return null;}
  const module=native;
  return {
    acquire:(scope,digest,bytes,epoch)=>module.ncOrderedIdleCacheAcquire(scope,digest,bytes,epoch),
    importFile:(scope,digest,bytes,epoch,uri)=>module.ncOrderedIdleCacheImport(scope,digest,bytes,epoch,uri),
    release:pin=>module.ncOrderedIdleCacheRelease(pin),
    clear:(scope,epoch,force=false)=>module.ncOrderedIdleCacheClear(scope,epoch,force),
    usage:()=>module.ncOrderedIdleCacheUsage(),
  };
}
