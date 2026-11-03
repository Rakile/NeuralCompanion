import React from 'react';
import {createNativeOrderedIdleCacheIO} from './orderedIdleCacheIO';
import type {OrderedIdleCacheIO} from './orderedIdleCacheIO';
import type {OrderedCachePolicy} from '../dev/orderedChunkStore';
import {OrderedIdleCacheDiagnostics,orderedCacheFailure} from '../diagnostics/orderedIdleCache';

type Storage={io:OrderedIdleCacheIO;scope:string;policy():OrderedCachePolicy;trace:OrderedIdleCacheDiagnostics};
let retained:Storage|undefined;
let status={complete:false,reason:'not_connected',files:0,bytes:0,requiredBytes:0};
export const orderedIdleStatus=()=>retained?{...status,cacheStats:retained.trace.snapshot()}:null;
export async function refreshOrderedIdleStatus(){
  const storage=retained;if(!storage)return;
  try{
    const usage=await storage.io.usage();if(retained!==storage)return;
    status={complete:false,reason:storage.policy().mode==='off'?'disabled':usage.reason,
      files:usage.files,bytes:usage.bytes,requiredBytes:0};
  }catch(error){
    status={...status,reason:orderedCacheFailure(error)};
    storage.trace.record({phase:'usage_failed',reason:status.reason,epoch:storage.policy().epoch,bytes:0});
  }
}
export async function clearOrderedIdleStorage():Promise<boolean>{
  const storage=retained;if(!storage)return false;
  const epoch=storage.policy().epoch;
  try{
    await storage.io.clear(storage.scope,epoch,true);
    storage.trace.record({phase:'clear',reason:'local',epoch,bytes:0});
    await refreshOrderedIdleStatus();return true;
  }catch(error){storage.trace.record({phase:'clear_failed',reason:orderedCacheFailure(error),epoch,bytes:0});throw error;}
}

/** Storage controls do not own playback and remain available while cache is OFF.
 * Keep the last store for a local clear after disconnect; never create output. */
export function useOrderedIdleStorage(scope:string|undefined,owner:object,connected:boolean,policy:OrderedCachePolicy){
  const latest=React.useRef(policy);latest.current=policy;
  const selected=React.useMemo(()=>({io:createNativeOrderedIdleCacheIO(),
    policy:()=>latest.current,trace:new OrderedIdleCacheDiagnostics()}),[owner]);
  React.useEffect(()=>{
    if(!connected||!scope||!selected.io||policy.mode==='unknown')return;
    const storage={...selected,io:selected.io,scope};retained=storage;
    void selected.io.clear(scope,policy.epoch).then(()=>refreshOrderedIdleStatus()).catch(error=>{
      if(retained===storage)status={...status,reason:orderedCacheFailure(error)};
      selected.trace.record({phase:'clear_failed',reason:orderedCacheFailure(error),epoch:policy.epoch,bytes:0});
    });
  },[selected,scope,connected,policy.mode,policy.epoch]);
  return React.useMemo(()=>({io:selected.io,policy:selected.policy,onEvent:selected.trace.record}),[selected]);
}
