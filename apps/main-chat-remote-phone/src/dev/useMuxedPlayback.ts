import React from 'react';
import {Platform} from 'react-native';
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import {MuxedTrialRuntime} from './muxedTrialRuntime';
import {muxedTrialAvailable,muxedContinuousAvailable,muxedChunkStreamAvailable} from './muxedTrialAudio';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {diagnosticErrorOrigin} from '../utils/diagnosticErrorOrigin';
import {MuxedPlaybackSession} from '../native/muxedPlaybackSession';
import {registerPhonePositionReader,registerPhoneHandoff} from '../utils/phonePresentation';
import {registerReplyReadiness} from '../utils/replyReadiness';

type Options={client:RemoteClient;owner:object;ticket:string|null;enabled:boolean;selected?:boolean;
  chunks?:readonly AudioChunk[];reply(chunk:AudioChunk):BufferedReplyAuthority|null;
  canRetireReply(requestId:string):boolean;retireVisualCarrier():Promise<void>};
// A selected trial that is not ready must fail closed, never open its first MP4
// or original WAV with the ordinary/separate player as an implicit fallback.
export const muxedTrialBlockedAudio={deferNativePreparation:true as const,owns:()=>false,
  acquire:async()=>{throw Error('Current NC Remote/Desktop continuous muxed build required.');},createPlayer:async()=>{throw Error('Current NC Remote/Desktop continuous muxed build required.');}};

export function useMuxedPlayback(options:Options){
  const latest=React.useRef(options);latest.current=options;
  const [,revise]=React.useState(0);
  const previousClose=React.useRef<Promise<void>>(Promise.resolve());
  const openingGates=React.useRef(new WeakMap<MuxedPlaybackSession,{resolve():void;reject(error:unknown):void}>());
  const runtime=React.useMemo(()=>{
    const targetIntent=Platform.OS==='android'&&options.enabled;
    if(targetIntent&&(!muxedContinuousAvailable()||!muxedChunkStreamAvailable()))return undefined;
    if(!options.enabled||!options.ticket||!muxedTrialAvailable())return undefined;
    const identity=options.owner,ticket=options.ticket,client=options.client;
    let resolve!:()=>void,reject!:(error:unknown)=>void;
    const ready=new Promise<void>((a,b)=>{resolve=a;reject=b;});
    const session=new MuxedPlaybackSession({
      ready:()=>ready,
      current:()=>latest.current.enabled&&latest.current.owner===identity&&latest.current.ticket===ticket&&latest.current.client===client,
      canRetireReply:id=>latest.current.canRetireReply(id),
      retireVisualCarrier:()=>latest.current.retireVisualCarrier(),
      createRuntime:epoch=>new MuxedTrialRuntime({client:()=>client,ticket,
        current:epoch.current,claimWaitingPlan:epoch.claimWaitingPlan,reply:chunk=>latest.current.reply(chunk)})});
    openingGates.current.set(session,{resolve,reject});return session;
  },[options.owner,options.ticket,options.enabled,options.client]);
  React.useEffect(()=>{
    if(Platform.OS!=='android'||!options.selected)return;
    return registerReplyReadiness(options.client,()=>{
      if(!runtime)throw Error('Muxed submission output unavailable.');
      return runtime.beforeReply();
    });
  },[runtime,options.client,options.selected]);
  React.useEffect(()=>{
    if(__DEV__&&options.selected&&!runtime)void recordPhoneDebug('warning','muxed_runtime_gate',
      {enabled:options.enabled,output_available:Boolean(options.ticket),native_available:muxedTrialAvailable()}).catch(()=>undefined);
  },[options.selected,options.enabled,options.ticket,runtime]);
  React.useEffect(()=>{
    if(!runtime)return;
    const releasePosition=registerPhonePositionReader(options.client,()=>runtime.readIdlePosition());
    const releaseHandoff=registerPhoneHandoff(options.client,()=>runtime.handoffExchange());
    return()=>{releaseHandoff();releasePosition();};
  },[runtime,options.client]);
  React.useEffect(()=>{
    if(!runtime)return;
    const gate=openingGates.current.get(runtime)!;
    const predecessor=previousClose.current;
    void predecessor.then(gate.resolve,gate.reject);
    const close=()=>{
      // Never replace an inherited failed join with a successor that had no
      // player and therefore closed trivially. The original barrier persists.
      const joined=Promise.all([predecessor,runtime.close()]).then(()=>undefined);
      previousClose.current=joined;return joined;
    };
    let active=true,busy=false,failedOnce=false;
    const unsubscribe=runtime.subscribe(()=>{if(active)revise(value=>value+1);});
    const failed=(error:unknown)=>{if(active&&!failedOnce){
      failedOnce=true;
      const codes:Record<string,string>={'Muxed idle native prune unconfirmed.':'idle_prune',
        'Idle chunk native prepare/append unavailable.':'idle_append','Muxed idle metadata capacity exceeded.':'idle_metadata',
        'Muxed idle owner ended.':'idle_owner','Idle chunk owner ended.':'queue_owner',
        'Muxed runtime owner ended.':'runtime_owner','Invalid idle decoder release cursor.':'idle_cursor',
        'Idle chunk producer unavailable.':'idle_producer','Invalid idle chunk status.':'idle_status',
        'Live visual request failed.':'control_http','Idle chunk source changed within its owner.':'idle_source',
        'Idle chunk producer cursor changed.':'producer_cursor','Invalid idle chunk cursor acknowledgement.':'cursor_ack',
        'Muxed idle descriptor changed.':'idle_descriptor','Invalid muxed idle sample range.':'idle_samples',
        'Muxed idle files unavailable.':'idle_files','Muxed idle admission ended.':'idle_admission',
        'Muxed idle native admission rejected.':'idle_native_rejected',
        'Muxed idle admission cancelled.':'idle_cancelled','Muxed idle mode changed.':'idle_mode',
        'Muxed idle authority unavailable.':'idle_authority','Muxed idle descriptor unavailable.':'idle_descriptor_missing',
        'Muxed idle metadata ended.':'idle_metadata_missing','Muxed session authority ended.':'session_owner',
        'Muxed source admission cancelled.':'source_cancelled','Muxed native owner retired.':'native_owner',
        'Update NC Remote for persistent muxed trial.':'session_unavailable',
        'Update NC Remote for confirmed muxed source retirement.':'source_fence_unavailable',
        'Idle chunk native selection unavailable.':'idle_selection',
        'Buffered media capacity reached; wait for playback release.':'media_capacity',
        'Buffered reply owner authority unavailable or expired.':'media_authority',
        'Buffered media cancelled.':'media_cancelled','Buffered media descriptor identity changed.':'media_descriptor',
        'Peer media unavailable.':'media_unavailable','Phone media cache unavailable.':'media_cache',
        'Peer media cancelled or unavailable before retention.':'media_retention',
        'Buffered media descriptor length or content type mismatch.':'media_mismatch',
        'Peer media cancelled.':'media_cancelled','Phone media cache capacity reached.':'media_capacity'};
      const failure_kind=error instanceof Error&&Object.prototype.hasOwnProperty.call(codes,error.message)?codes[error.message]:'other';
      const status=error instanceof Error?(error as Error&{httpStatus?:unknown}).httpStatus:undefined;
      const http=typeof status==='number'&&Number.isInteger(status)&&status>=100&&status<=599?{http_status:status}:{};
      void recordPhoneDebug('warning','muxed_runtime_failed',{phase:runtime.phase,stage:runtime.runtime?.startupStage??'availability',failure_kind,error_origin:diagnosticErrorOrigin(error),...http}).catch(()=>undefined);
      void close().catch(()=>{void recordPhoneDebug('warning','muxed_runtime_detach_failed',{}).catch(()=>undefined);});
    }};
    const tick=async()=>{if(!active||busy||failedOnce||runtime.phase==='failed')return;busy=true;
      try{await runtime.tick();}catch(error){failed(error);}finally{busy=false;}};
    void runtime.start().catch(failed);
    const timer=setInterval(()=>{if(runtime.phase==='idle'||runtime.phase==='speech'||runtime.phase==='waiting')void tick();},100);
    return()=>{active=false;clearInterval(timer);unsubscribe();void close().catch(()=>undefined);};
  },[runtime]);
  const appendReplyMedia=React.useCallback((requestId:string,chunks:readonly AudioChunk[])=>{
    if(chunks.some(chunk=>chunk.phone_request_id!==requestId)){
      void runtime?.close().catch(()=>undefined);throw Error('Invalid muxed reply manifest.');}
    runtime?.appendReplyMedia(requestId,chunks);
  },[runtime]);
  const restoreReplyMedia=React.useCallback((requestId:string,chunks:readonly AudioChunk[])=>{
    runtime?.restoreReplyMedia(requestId,chunks);
  },[runtime,appendReplyMedia]);
  return {runtime:runtime?.runtime,session:runtime,audio:runtime?.audio,phase:runtime?.phase??'off',appendReplyMedia,restoreReplyMedia};
}
