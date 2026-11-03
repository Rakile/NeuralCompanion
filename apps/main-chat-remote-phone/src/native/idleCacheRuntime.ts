import {IdleLoopCache} from '../relay/idleLoopCache';
import type {IdleLoopSession,IdleSessionStatus} from '../relay/idleLoopSession';
import {createNativeIdleCacheIO} from './idleCacheIO';
import {orderedIdleStatus,refreshOrderedIdleStatus,clearOrderedIdleStorage} from './orderedIdleCacheRuntime';
import {completeIdleCacheStatus,clearCompleteIdleCache} from './completeIdleCacheRuntime';

let cache:IdleLoopCache|null=null,session:IdleLoopSession|null=null;
let status:IdleSessionStatus={complete:false,reason:'not_connected',files:0,bytes:0,requiredBytes:0};
export function phoneIdleCache(){
  if(!cache){const io=createNativeIdleCacheIO();if(io)cache=new IdleLoopCache(io);}
  return cache;
}
export function setIdleSession(value:IdleLoopSession){session?.pause();session=value;}
export function publishIdleStatus(owner:IdleLoopSession,value:IdleSessionStatus){if(session===owner)status={...value};}
export function detachIdleSession(owner:IdleLoopSession){owner.pause();if(session===owner){session=null;status={...status,reason:'paused'};}}
export function idleCacheStatus(){return completeIdleCacheStatus()??orderedIdleStatus()??{...status};}
export async function refreshIdleCacheStatus(){await refreshOrderedIdleStatus();}
export async function clearPhoneIdleCache(){
  if(await clearCompleteIdleCache())return;
  if(await clearOrderedIdleStorage())return;
  if(session)await session.clear();else {
    const selected=phoneIdleCache();if(!selected)throw new Error('Native idle cache unavailable.');
    await selected.clear();
  }
  status={complete:false,reason:'cleared',files:0,bytes:0,requiredBytes:0};
}
