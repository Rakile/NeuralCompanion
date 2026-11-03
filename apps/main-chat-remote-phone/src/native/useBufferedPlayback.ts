import React from 'react';
import {requireOptionalNativeModule} from 'expo';
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import type {BufferedReplyAuthority} from '../relay/bufferedAudio';
import {BufferedPlaybackRuntime} from './bufferedPlaybackRuntime';
import {BufferedPresentation} from './bufferedPresentation';
import type {NativeBufferedPresentation} from './bufferedPresentation';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import type {VideoQuality} from '../relay/idleLoopCache';
import {phoneIdleCache} from './idleCacheRuntime';

type Options={client:RemoteClient;owner:object;ticket:string|null;enabled:boolean;chunks:AudioChunk[];
  reply(chunk:AudioChunk):BufferedReplyAuthority|null;
  retainHandoff?(chunk:AudioChunk,status:unknown,signal:AbortSignal):Promise<void>};
const diagnose=(event:string,fields:Record<string,string|number>)=>{
  void recordPhoneDebug('info',event,fields).catch(()=>undefined);
};

/** The connection owns cached presentation; the native ticket owns reply files.
 * Changing transports is neither a new account nor permission to replay speech. */
export function useBufferedPlayback(options:Options){
  const latest=React.useRef(options);latest.current=options;
  const [,revise]=React.useState(0);
  const presentationOwner=React.useMemo(()=>{
    const identity=options.owner;
    let closed=false,output:BufferedPresentation|undefined,pending:Promise<BufferedPresentation>|undefined;
    let scope='',quality:VideoQuality|null=null;
    const current=()=>!closed&&latest.current.owner===identity&&latest.current.enabled;
    const get=():Promise<BufferedPresentation>=>{
      if(!current())return Promise.reject(Error('Buffered presentation owner ended.'));
      if(output)return Promise.resolve(output);
      if(!pending){
        const work=(async()=>{
          const peer=latest.current.client.bufferedPeer;
          if(!peer||!peer.cacheScope||peer.closed)throw Error('Buffered media peer reconnecting.');
          if(scope&&scope!==peer.cacheScope)throw Error('Buffered desktop owner changed.');
          scope=peer.cacheScope;
          const capability=await peer.negotiateBuffered();
          if(!current())throw Error('Buffered presentation owner ended.');
          quality=capability.video_quality;
          const native=requireOptionalNativeModule<NativeBufferedPresentation>('ExpoAudio');
          if(!native)throw Error('Update NC Remote for buffered native presentation.');
          const created=BufferedPresentation.open(native,current,()=>quality,async()=>{
            // No idle RTP producer exists to suppress in buffered mode. The
            // decoded selection is local state, not an audio receipt or RPC.
            if(!current())throw Error('Buffered presentation owner ended.');
          },()=>false,async id=>await phoneIdleCache()?.get(id)??null);
          if(!current()){await created.close();throw Error('Buffered presentation owner ended.');}
          output=created;return created;
        })();
        pending=work;
        void work.catch(()=>{if(pending===work)pending=undefined;});
      }
      return pending;
    };
    return {current,get,get output(){return output;},get scope(){return scope;},
      async refreshQuality(){
        const peer=latest.current.client.bufferedPeer;
        if(!current()||!output||output.qualityBusy||!peer||peer.closed||peer.cacheScope!==scope)return;
        const capability=await peer.negotiateBuffered(true);
        // Speech can start while the authenticated settings request is pending.
        // Its prepared media keeps the old generation until a later idle poll.
        if(current()&&!output.qualityBusy&&latest.current.client.bufferedPeer===peer)quality=capability.video_quality;
      },
      async close(){closed=true;const value=output??await pending?.catch(()=>undefined);await value?.close();}};
  },[options.owner,options.enabled]);
  const runtime=React.useMemo(()=>{
    if(!options.enabled)return undefined;
    const identity=options.owner,ticket=options.ticket;
    return new BufferedPlaybackRuntime({client:()=>latest.current.client,
      current:()=>presentationOwner.current()&&latest.current.owner===identity&&latest.current.ticket===ticket,
      replayAuthority:()=>{
        const peer=latest.current.client.bufferedPeer;
        return ticket&&latest.current.ticket===ticket&&presentationOwner.current()&&peer
          &&peer.cacheScope===presentationOwner.scope?{owner:peer.cacheScope,ticket}:null;
      },
      reply:chunk=>{
        const authority=latest.current.reply(chunk);
        if(!authority||authority.ticket!==ticket||!presentationOwner.scope||authority.scope.owner!==presentationOwner.scope)return null;
        return authority;
      },presentation:presentationOwner.get,
      retainHandoff:options.retainHandoff?(chunk,status,signal)=>{
        const retain=latest.current.retainHandoff;
        if(!retain)throw Error('Buffered handoff integration unavailable.');
        return retain(chunk,status,signal);
      }:undefined,diagnose});
  },[presentationOwner,options.owner,options.ticket,options.enabled,Boolean(options.retainHandoff)]);
  React.useEffect(()=>{runtime?.update(options.chunks);},[runtime,options.chunks]);
  React.useEffect(()=>()=>{void runtime?.close().catch(()=>diagnose('buffered_runtime_detach_failed',{}));},[runtime]);
  React.useEffect(()=>{
    if(!options.enabled)return;
    let active=true,busy=false,reported='';
    const tick=async()=>{
      if(!active||busy)return;busy=true;
      try{
        if(presentationOwner.output)await presentationOwner.refreshQuality();
        else {await presentationOwner.get();if(active)revise(value=>value+1);}
      }
      catch(error){if(active){
        // Only a fixed local category crosses diagnostics. Transport/native
        // exception text may contain a private URL or credential.
        const message=error instanceof Error?error.message:'';
        const reason=message==='Update NC Remote for buffered native presentation.'?'native_capability'
          :message==='Buffered native presentation unavailable.'?'native_open'
          :message==='Buffered media peer reconnecting.'?'peer_reconnecting'
          :message==='Buffered desktop owner changed.'?'owner_changed'
          :message==='Buffered presentation owner ended.'?'owner_ended':'transport_or_native';
        if(reported!==reason){reported=reason;diagnose('buffered_presentation_pending',{reason});}
      }}
      finally{busy=false;}
    };
    void tick();const timer=setInterval(tick,2000);
    return()=>{active=false;clearInterval(timer);void presentationOwner.close().catch(()=>diagnose('buffered_presentation_detach_failed',{}));};
  },[presentationOwner,options.enabled]);
  return {runtime,presentation:presentationOwner.output};
}
