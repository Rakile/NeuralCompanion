import React from 'react';
import type {RemoteClient} from '../api/client';

export type MuxedCacheMode='unknown'|'on'|'off';
type Selection={platform:string;connected:boolean;museTalk:boolean;backendHq:boolean;
  demo:boolean;story:boolean;nativeSpeech:boolean;cacheMode:MuxedCacheMode};
export function selectMuxedPlayback(input:Selection):boolean {
  return input.platform==='android'&&input.connected&&input.museTalk&&input.backendHq
    &&!input.demo&&!input.story&&!input.nativeSpeech&&input.cacheMode!=='unknown';
}

export type MuxedCachePolicy={mode:MuxedCacheMode;epoch:number;error:string|null};
type Policy=MuxedCachePolicy;
type Snapshot=Policy&{owner:object;connection:object};
// Mode is pinned per connection; clear generation remains live while ON or OFF.
// Unknown or failed initial reads never mean OFF or select another player.
export function useMuxedCachePolicy(client:RemoteClient,owner:object,connected:boolean):Policy {
  const connection=React.useMemo(()=>({}),[owner,connected]);
  const latest=React.useRef({owner,connection,connected,client});latest.current={owner,connection,connected,client};
  const [snapshot,setSnapshot]=React.useState<Snapshot|null>(null);
  React.useEffect(()=>{
    if(!connected)return;
    const abort=new AbortController();
    const current=()=>!abort.signal.aborted&&latest.current.connected
      &&latest.current.owner===owner&&latest.current.connection===connection;
    let selected:MuxedCacheMode='unknown',epoch=0,busy=false,retryMs=2000;
    let timer:ReturnType<typeof setTimeout>|null=null;
    const read=async()=>{
      if(busy||!current())return;busy=true;
      let succeeded=false;
      try{
        const settings=await latest.current.client.idleCacheSettings(abort.signal);if(!current())return;
        if(typeof settings.enabled!=='boolean'||!Number.isSafeInteger(settings.clear_generation)||settings.clear_generation<0)
          throw Error('Invalid idle-cache policy.');
        if(selected==='unknown')selected=settings.enabled?'on':'off';
        epoch=Math.max(epoch,settings.clear_generation);
        setSnapshot(old=>old?.owner===owner&&old.connection===connection&&old.mode===selected&&old.epoch===epoch&&old.error===null
          ?old:{owner,connection,mode:selected,epoch,error:null});
        succeeded=true;
      }catch{
        if(current())setSnapshot({owner,connection,mode:selected,epoch,error:'Idle-cache policy unavailable.'});
      }finally{
        busy=false;
        if(current()){
          const delay=succeeded?2000:retryMs;
          retryMs=succeeded?2000:Math.min(retryMs*2,30000);
          timer=setTimeout(()=>{timer=null;void read();},delay);
        }
      }
    };
    void read();
    return()=>{abort.abort();if(timer!==null)clearTimeout(timer);};
    // Verified owner/connection pins the mode, not an obsolete peer wrapper.
    // Transport replacement must keep polling current authenticated settings.
  },[owner,connection,connected]);
  return connected&&snapshot?.owner===owner&&snapshot.connection===connection
    ?{mode:snapshot.mode,epoch:snapshot.epoch,error:snapshot.error}:{mode:'unknown',epoch:0,error:null};
}
export function useMuxedCacheMode(client:RemoteClient,owner:object,connected:boolean):MuxedCacheMode {
  return useMuxedCachePolicy(client,owner,connected).mode;
}
