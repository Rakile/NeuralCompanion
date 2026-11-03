import React from 'react';
import {Platform} from 'react-native';
import {requireOptionalNativeModule} from 'expo';
import type {RemoteClient} from '../api/client';
import type {AudioChunk,PhoneReplyAuth} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import {createPhoneAudioPlayer,finishPhoneReplyAudio,freezePhoneReplyReceipt,skipPhoneReplyAudio} from '../native/iosPlaybackGuard';
import {configurePhoneAudio} from '../native/phoneCaptureOwnership';
import {prepareAndroidPlaybackRoute} from '../native/androidPlaybackRoute';
import {registerReplyReadiness} from '../utils/replyReadiness';
import {DesktopOrderedRuntime} from './desktopOrderedRuntime';
import type {OrderedPlayer} from './desktopOrderedRuntime';
import {beginAndroidPlaybackBackground} from '../native/androidPlaybackBackground';
import type {PlaybackBackgroundLease} from '../native/androidPlaybackBackground';
import {orderedRecoveryJournal,orderedRecoveryScope} from '../native/orderedRecoveryStorage';
import {DesktopOrderedTransport} from './desktopOrderedTransport';
import {OrderedIdleInventory} from './orderedIdleInventory';
import type {OrderedIdleInventoryStatus} from './orderedIdleInventory';
import {OrderedIdleInventoryConnection} from './orderedIdleInventoryConnection';
import {phoneIdleCache} from '../native/idleCacheRuntime';
import {attachCompleteIdleInventory,publishCompleteIdleStatus,detachCompleteIdleInventory} from '../native/completeIdleCacheRuntime';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {reportOrderedIdleFailure,reportOrderedIdleRecovery} from '../utils/orderedIdleDiagnostics';
import {readOrderedPlaybackClock} from '../native/orderedPlaybackClock';
import {setOrderedUserPaused} from '../native/orderedUserPause';
import {orderedInventoryTransport} from './orderedContinuation';
import {recordOrderedContinuation} from '../diagnostics/orderedControlWait';

export type DesktopOrderedPlaybackOptions={client:RemoteClient;owner:object;ticket:string|null;selected:boolean;enabled:boolean;
  continuationKey?:string;transportReady?:boolean;freshState?:boolean;transportRevision?:number;locked?:boolean;
  recoveryProfile:string;
  idleCache?:ConstructorParameters<typeof DesktopOrderedRuntime>[0]['idleCache'];
  getAuth(renew?:boolean):Promise<PhoneReplyAuth>;reply(chunk:AudioChunk):BufferedReplyAuthority|null;volume:number;
  recoveryEpoch?:number;
  nativeAdmitted(replyId:string):boolean;
  onBackgroundReady?(ready:boolean):void;
  onAssistantPlaybackStarted?(replyId:string):void;
  onInterruption?:ConstructorParameters<typeof DesktopOrderedRuntime>[0]['onInterruption'];
  beforeSpeech():Promise<void>;onRecovering?(error:unknown):void;onFailure(error:unknown):void};
type Opening={runtime?:DesktopOrderedRuntime;failure?:unknown;ready:Promise<DesktopOrderedRuntime>;
  idleStatus?:OrderedIdleInventoryStatus;
  backgroundReady?:boolean;
  retired?:boolean;close?():Promise<void>;resolve(runtime:DesktopOrderedRuntime):void;reject(error:unknown):void};
function opening():Opening{
  let resolve!:(runtime:DesktopOrderedRuntime)=>void,reject!:(error:unknown)=>void;
  const ready=new Promise<DesktopOrderedRuntime>((a,b)=>{resolve=a;reject=b;});void ready.catch(()=>undefined);
  return {ready,resolve,reject};
}

export function desktopOrderedAvailable():boolean{
  if(Platform.OS!=='android')return false;
  try{return requireOptionalNativeModule<{ncOrderedMuxedQueueVersion?():number}>('ExpoAudio')?.ncOrderedMuxedQueueVersion?.()===1;}
  catch{return false;}
}
export function desktopOrderedContinuationAvailable():boolean{
  try{return requireOptionalNativeModule<{ncOrderedContinuationVersion?():number}>('ExpoAudio')?.ncOrderedContinuationVersion?.()===1;}
  catch{return false;}
}

/** Lifecycle adapter for the normal uncached owner. Construction has no native
 * or network effects; a successor cannot run before its predecessor joins.
 * Deliberately registers no phone position or transition-planning callbacks. */
export function useDesktopOrderedPlayback(options:DesktopOrderedPlaybackOptions){
  const latest=React.useRef(options);latest.current=options;
  const [,revise]=React.useState(0);
  const previousClose=React.useRef<()=>Promise<void>>(()=>Promise.resolve());
  // Local reader joins gate admission; remote deletion has a separate lifetime.
  // Keep failed exact cleanup obligations across a gap with no media peer.
  const pendingCleanup=React.useRef(new Map<Opening,{peer:unknown;retry():Promise<void>}>());
  const available=desktopOrderedAvailable(),peer=options.client.bufferedPeer;
  const unsupportedContinuation=React.useRef<{peer:unknown;key:string}|null>(null);
  const retaining=available&&desktopOrderedContinuationAvailable()&&!!options.continuationKey
    &&!(unsupportedContinuation.current?.peer===peer&&unsupportedContinuation.current?.key===options.continuationKey);
  const retainedPeer=React.useRef<{key:string;profile:string;scope:string}|null>(null);
  if(!retaining||!options.selected||!options.enabled||!options.ticket)retainedPeer.current=null;
  else {
    if(retainedPeer.current?.key!==options.continuationKey||retainedPeer.current?.profile!==options.recoveryProfile)
      retainedPeer.current=null;
    if(peer?.cacheScope)retainedPeer.current={key:options.continuationKey!,profile:options.recoveryProfile,scope:peer.cacheScope};
  }
  const peerScope=retaining?retainedPeer.current?.scope:peer?.cacheScope;
  const lifecycleOwner=retaining?options.continuationKey:options.owner;
  const [authenticationRevision,retryAuthentication]=React.useState(0);
  // One renewal per externally admitted owner, not an unbounded error loop.
  // Ordinary volume/Live changes neither reset this budget nor replace playback.
  const authenticationRecovery=React.useMemo(()=>({attempted:false,coldAttempted:false}),[options.selected,options.enabled,
    lifecycleOwner,options.ticket,retaining?null:options.client,retaining?peerScope:peer,
    retaining?null:options.getAuth,options.recoveryEpoch,options.recoveryProfile]);
  const entry=React.useMemo(()=>available&&options.selected&&options.enabled&&options.ticket&&peerScope
    ?opening():undefined,[available,options.selected,options.enabled,lifecycleOwner,options.ticket,
      retaining?null:options.client,retaining?peerScope:peer,retaining?null:options.getAuth,
      options.recoveryEpoch,options.recoveryProfile,authenticationRevision]);
  React.useEffect(()=>{
    if(Platform.OS!=='android'||!options.selected)return;
    return registerReplyReadiness(options.client,()=>{
      if(!entry)throw Error('ordered.hook_unavailable');
      return entry.ready.then(session=>session.beforeReply());
    },()=>({selected:latest.current.selected,enabled:latest.current.enabled,
      owner_changed:latest.current.owner!==options.owner,ticket_changed:latest.current.ticket!==options.ticket,
      client_changed:latest.current.client!==options.client,peer_changed:latest.current.client.bufferedPeer!==peer,
      auth_changed:latest.current.getAuth!==options.getAuth,
      recovery_changed:(latest.current.recoveryEpoch??0)!==(options.recoveryEpoch??0),
      entry_retired:entry?.retired===true,entry_failed:!!entry?.failure}));
  },[options.selected,options.client,entry]);
  React.useEffect(()=>{
    if(!entry)return;
    let predecessor:(()=>Promise<void>)|undefined=previousClose.current;
    const joinPredecessor=async()=>{await predecessor?.();predecessor=undefined;};
    const {owner,ticket,client,getAuth,recoveryEpoch=0,recoveryProfile,continuationKey}=options;
    const current=()=>active&&!entry.retired&&latest.current.selected&&latest.current.enabled
      &&latest.current.ticket===ticket&&(retaining?latest.current.continuationKey===continuationKey
        &&(!latest.current.client.bufferedPeer||latest.current.client.bufferedPeer.cacheScope===peerScope)
        :latest.current.owner===owner&&latest.current.client===client&&client.bufferedPeer===peer&&latest.current.getAuth===getAuth)
      &&(latest.current.recoveryEpoch??0)===recoveryEpoch
      &&latest.current.recoveryProfile===recoveryProfile;
    let active=true,busy=false;
    let background:Promise<PlaybackBackgroundLease|undefined>|undefined;
    const backgroundChanged=(ready:boolean)=>{
      entry.backgroundReady=ready&&current();
      if(active){latest.current.onBackgroundReady?.(entry.backgroundReady);revise(n=>n+1);}
    };
    let unsubscribe:(()=>void)|undefined;
    let inventory:OrderedIdleInventory|undefined,inventoryConnection:OrderedIdleInventoryConnection|undefined;
    const failed=(error:unknown)=>{
      entry.reject(error);if(!current()||entry.failure)return;
      entry.failure=error;revise(n=>n+1);
      const reason=(error as Error)?.message;
      if(retaining&&!authenticationRecovery.coldAttempted
        &&(reason==='ordered.continuation_unsupported'||reason==='ordered_reattach_media_unavailable')){
        authenticationRecovery.coldAttempted=true;
        if(reason==='ordered.continuation_unsupported')unsupportedContinuation.current={
          peer:latest.current.client.bufferedPeer,key:continuationKey!};
        // Existing journal/reader barriers own cold retirement and fresh idle.
        // Do not renew credentials or silently replay unfinished speech.
        try{latest.current.onRecovering?.(error);}catch{}
        retryAuthentication(n=>n+1);return;
      }
      if((error as Error)?.message==='phone_reply_authentication'&&!authenticationRecovery.attempted){
        authenticationRecovery.attempted=true;
        try{latest.current.onRecovering?.(error);}catch{} // Observation cannot replace recovery.
        retryAuthentication(n=>n+1);return;
      }
      try{latest.current.onFailure(error);}catch{}
    };
    const starting=(async()=>{
      await joinPredecessor();if(!current())throw Error('ordered.hook_owner');
      const cleanupAttempts:Promise<void>[]=[];
      for(const cleanup of pendingCleanup.current.values())if(cleanup.peer!==peer){
        cleanup.peer=peer;
        // Retry once per replacement peer, never block successor admission on
        // remote reachability or infer closure from successful reconnection.
        cleanupAttempts.push(cleanup.retry().catch(()=>undefined));
      }
      if(pendingCleanup.current.size>=64)await Promise.all(cleanupAttempts);
      if(!current())throw Error('ordered.hook_owner');
      if(pendingCleanup.current.size>=64)throw Error('ordered_recovery_retention_capacity');
      // Preserve the credential shared with capture on ordinary admission.
      // Only a confirmed authentication rejection renews it, after local join;
      // the journal still settles uncertain admission with its exact old proof.
      const auth=await getAuth(authenticationRecovery.attempted);if(!current())throw Error('ordered.hook_owner');
      if(!auth?.client_key||!auth.connection_epoch)throw Error('ordered.hook_auth');
      if(!recoveryProfile)throw Error('ordered.recovery_profile');
      const scope=await orderedRecoveryScope(recoveryProfile);if(!current())throw Error('ordered.hook_owner');
      const intent=await orderedRecoveryJournal.prepare(scope,auth,async(intent,authentication)=>{
        if(!current())throw Error('ordered.hook_owner');
        await peer!.negotiateBuffered();if(!current())throw Error('ordered.hook_owner');
        const transport=new DesktopOrderedTransport({peer:()=>latest.current.client.bufferedPeer,
          owner:peer!.cacheScope,auth:authentication,streamId:intent.streamId,generation:0,current,
          onAvailable:()=>false,onFailure:()=>{}});
        return transport.admitRecovery(intent);
      },current);if(!current())throw Error('ordered.hook_owner');
      if(options.idleCache?.policy().mode==='on'&&!options.idleCache.io)throw Error('ordered.cache_native_required');
      await configurePhoneAudio({playsInSilentMode:true});if(!current())throw Error('ordered.hook_owner');
      await prepareAndroidPlaybackRoute(ticket!,current);if(!current())throw Error('ordered.hook_owner');
      if(options.idleCache?.policy().mode==='on'){
        const cache=phoneIdleCache();if(!cache)throw Error('ordered.cached_storage_unavailable');
        // Predecessor native readers are joined above. Do not spend a second
        // reusable-cache budget on the obsolete occurrence cache in this mode.
        await options.idleCache.io!.clear(peer!.cacheScope,options.idleCache.policy().epoch,true);
        if(!current())throw Error('ordered.hook_owner');
        const inventoryClient=retaining?orderedInventoryTransport(()=>latest.current.client,current):client;
        inventory=new OrderedIdleInventory({client:inventoryClient,cache,
          beforeStorageChange:()=>entry.runtime?.pauseCachedIdle()??Promise.resolve(),
          onChange:value=>{publishCompleteIdleStatus(entry,value);if(current()){entry.idleStatus=value;revise(n=>n+1);}},
          onFailure:error=>{if(current())reportOrderedIdleFailure('acquisition',error);}});
        attachCompleteIdleInventory(entry,inventory);
        inventoryConnection=new OrderedIdleInventoryConnection({client:inventoryClient,inventory,current,
          policy:()=>latest.current.idleCache?.policy()??{mode:'off',epoch:0},
          onFailure:error=>{if(current())reportOrderedIdleFailure('manifest',error);},
          onState:reason=>{if(current()){entry.idleStatus={complete:false,reason,files:0,totalFiles:0,bytes:0,requiredBytes:0};
            publishCompleteIdleStatus(entry,entry.idleStatus);revise(n=>n+1);}}});
      }
      const runtime=entry.runtime=new DesktopOrderedRuntime({onSpeechStarted:id=>latest.current.onAssistantPlaybackStarted?.(id),setUserPaused:setOrderedUserPaused,readPlaybackClock:readOrderedPlaybackClock,
        continuation:retaining?{ownerKey:continuationKey!,
          operationId:()=> (require('expo-crypto') as typeof import('expo-crypto')).randomUUID().replace(/-/g,'').toLowerCase(),
          schedule:retry=>{const timer=setTimeout(retry,5000);return()=>clearTimeout(timer);},
          observe:recordOrderedContinuation}:undefined,
        session:{ticket:ticket!,owner:peer!.cacheScope,connectionEpoch:auth.connection_epoch,recoveryEpoch,
          streamId:intent.streamId,expiresAtMs:Date.now()+6000000},
        recovery:{intent,confirm:async result=>{
          await orderedRecoveryJournal.confirm(scope,intent,result);
        }},
        // Only cleanup can outlive `current`. Its transport still validates the
        // exact original cache scope and private auth on a reconnected peer.
        auth,peer:()=>latest.current.client.bufferedPeer,current,idleCache:options.idleCache,
        fullIdle:inventory?{inventory,policy:()=>latest.current.idleCache?.policy()??{mode:'off',epoch:0},
          onDiagnostic:value=>{void recordPhoneDebug('warning','ordered_cached_idle_stalled',value).catch(()=>undefined);},
          onRecovery:reportOrderedIdleRecovery}:undefined,
        // Ordered RPC, not a generic bind, owns visual and per-reply grants.
        createPlayer:()=>createPhoneAudioPlayer(null,{updateInterval:100,keepAudioSessionActive:true},null) as OrderedPlayer,
        authority:chunk=>latest.current.reply(chunk),
        finish:(id,admitted)=>admitted||latest.current.nativeAdmitted(id)?finishPhoneReplyAudio(ticket!,id):true,
        freeze:(id,interruption)=>freezePhoneReplyReceipt(ticket!,id,interruption),
        onInterruption:receipt=>{if(current())latest.current.onInterruption?.(receipt);},
        skip:(id,admitted)=>admitted||latest.current.nativeAdmitted(id)?skipPhoneReplyAudio(ticket!,id):true,
        beforeSpeech:async()=>{
          await latest.current.beforeSpeech();if(!current())throw Error('ordered.hook_owner');
          await prepareAndroidPlaybackRoute(ticket!,current);if(!current())throw Error('ordered.hook_owner');
        },volume:()=>latest.current.volume,onFailure:failed});
      unsubscribe=runtime.subscribe(()=>{
        if(active)revise(n=>n+1);
        // A registered player alone is insufficient; ordered open must have
        // installed its actual native binding before service admission.
        if(current()&&!background&&runtime.player&&runtime.startupStage==='idle'){
          authenticationRecovery.coldAttempted=false;
          background=beginAndroidPlaybackBackground(ticket!,String(runtime.player.id),backgroundChanged)
            .catch(()=>{backgroundChanged(false);return undefined;});
        }
      });
      entry.resolve(runtime);revise(n=>n+1);
      // Acquisition is parallel with streamed startup and every later reply.
      void inventoryConnection?.start().catch(failed);
      await runtime.start();
    })();void starting.catch(failed);
    let joined:Promise<void>|undefined,localJoined:Promise<void>|undefined;
    const settleLocal=()=>{
      if(localJoined)return localJoined;
      entry.retired=true;entry.reject(Error('ordered.hook_owner'));
      entry.backgroundReady=false;
      if(latest.current.owner===owner&&latest.current.ticket===ticket)latest.current.onBackgroundReady?.(false);
      const closing=entry.runtime?.close();void closing?.catch(()=>undefined);
      // Preserve failed predecessor settlement even if no new player opened.
      localJoined=Promise.all([joinPredecessor(),starting.catch(()=>undefined)])
        .then(async()=>{await entry.runtime?.settleLocalForRecovery();await inventoryConnection?.close();
          detachCompleteIdleInventory(entry);await (await background)?.close();});
      previousClose.current=settleLocal;void localJoined.catch(()=>undefined);
      return localJoined;
    };
    entry.close=()=>{
      if(joined)return joined;
      if(!pendingCleanup.current.has(entry))pendingCleanup.current.set(entry,{peer,retry:async()=>{
        // An old transport call can still be settling when the new peer opens.
        // Join that attempt before retrying; entry.close preserves native proof.
        await joined?.catch(()=>undefined);await entry.close!();
      }});
      joined=settleLocal().then(()=>entry.runtime?.close()).then(()=>{
        pendingCleanup.current.delete(entry);
      }).catch(error=>{joined=undefined;throw error;});
      void joined.catch(()=>undefined);
      return joined;
    };
    const timer=setInterval(()=>{
      const session=entry.runtime;if(!session)return;
      if(!active||busy||session.phase==='off'||session.phase==='failed')return;
      busy=true;void session.tick().catch(()=>undefined).finally(()=>{busy=false;});
    },100);
    return()=>{
      active=false;clearInterval(timer);unsubscribe?.();void entry.close!().catch(()=>undefined);
    };
  },[entry]);
  const session=entry?.runtime;
  React.useEffect(()=>{
    if(!retaining||!session)return;
    session.observeConnection({ownerKey:options.continuationKey!,transportRevision:options.transportRevision??0,
      connected:options.transportReady!==false&&!!peer&&!peer.closed&&peer.cacheScope===peerScope,
      freshState:options.freshState!==false,locked:options.locked===true,enabled:options.selected&&options.enabled});
  },[retaining,session,peer,peerScope,options.continuationKey,options.transportRevision,options.transportReady,
    options.freshState,options.locked,options.selected,options.enabled]);
  return {session,runtime:session,idleStatus:entry?.idleStatus??null,backgroundReady:entry?.backgroundReady===true&&!entry.retired,phase:entry?.failure?'failed' as const:session?.phase??(entry&&!entry.retired?'arming' as const:'off' as const),available,
    close:()=>entry?.close?.()??Promise.resolve()};
}
