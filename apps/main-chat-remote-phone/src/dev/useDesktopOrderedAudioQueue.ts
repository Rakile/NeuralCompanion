import React from 'react';
import type {AudioChunk,PhoneReplyStatus} from '../api/types';
import type {PlaybackState} from '../hooks/useAudioQueue';
import {useDesktopOrderedPlayback} from './useDesktopOrderedPlayback';
import type {DesktopOrderedPlaybackOptions} from './useDesktopOrderedPlayback';
import type {DesktopOrderedRuntime} from './desktopOrderedRuntime';

type Options=DesktopOrderedPlaybackOptions&{ordinary:PlaybackState;autoplay:boolean;
  onAutoplayChanged(enabled:boolean):void;requestStop(replyId:string):Promise<void>};
type Replay={owner:object;ticket:string|null;opening:boolean;cancelled:boolean};

/** Normal controls over the ordered carrier. The ordinary queue is automatic-OFF
 * in this mode and is used only for explicit Replay. Capture intent is distinct
 * from owner teardown; idle visuals alone never claim speech activity. */
export function useDesktopOrderedAudioQueue(options:Options){
  const latest=React.useRef(options);latest.current=options;
  const [replay,setReplay]=React.useState<Replay|null>(null);
  const replayRef=React.useRef(replay);replayRef.current=replay;
  // A Replay can replace the visual runtime before the App acknowledges an old
  // reply's cancellation. Keep that reply attached to its actual native owner;
  // observing it later must never stop the newly opened idle carrier.
  const replies=React.useMemo(()=>({owners:new Map<string,DesktopOrderedRuntime>(),finished:new Set<string>()}),
    [options.continuationKey||options.owner,options.ticket,options.recoveryEpoch]);
  const ordered=useDesktopOrderedPlayback({...options,enabled:options.enabled&&!replay,
    reply:chunk=>latest.current.autoplay?latest.current.reply(chunk):null});
  const session=ordered.session;
  const current=()=>latest.current.ticket===options.ticket&&latest.current.selected
    &&(options.continuationKey?latest.current.continuationKey===options.continuationKey
      :latest.current.owner===options.owner&&latest.current.client===options.client);
  const replyOwner=(id:string)=>{
    const old=replies.owners.get(id);if(old)return old;
    if(!session||replies.finished.has(id))return undefined;
    if(replies.owners.size>=32)throw Error('ordered.controls_reply_capacity');
    replies.owners.set(id,session);return session;
  };
  const skip=(id:string)=>{
    const target=replyOwner(id);
    if(target&&target.phase!=='off'&&target.phase!=='failed')target.skipReply(id);
  };
  const stopReply=async(id:string)=>{
    if(!current())return;
    skip(id); // Native fencing precedes the network operation.
    await options.requestStop(id);
  };
  const failed=(error:unknown)=>{if(current())options.onFailure(error);};
  const stopExplicit=()=>{
    const active=replayRef.current;if(!active||!current())return;
    active.cancelled=true;options.ordinary.interrupt();
    // A pending opening owns its own settlement; do not reopen idle beneath it.
    if(!active.opening)setReplay(null);
  };
  React.useEffect(()=>{
    if(replay&&!replay.opening&&!options.ordinary.playingId&&!options.ordinary.currentChunk&&!options.ordinary.explicitPlaybackPending)setReplay(null);
  },[replay,options.ordinary.playingId,options.ordinary.currentChunk,options.ordinary.explicitPlaybackPending]);
  React.useEffect(()=>{
    if(options.selected&&!options.autoplay&&session?.activeReplyId)
      void stopReply(session.activeReplyId).catch(failed);
  },[options.selected,options.autoplay,session,session?.activeReplyId]);
  const beforeCapture=async()=>{
    if(!options.selected){options.ordinary.interrupt();return;}
    stopExplicit();
    const id=session?.activeReplyId;if(id)await stopReply(id);
  };
  const beforeConversationAction=async()=>{
    if(!options.selected)return;
    if(!current())throw Error('ordered.controls_owner');
    // Reuse Stop's native fence and authenticated cancellation. Both Retry and
    // Regenerate wait for replacement idle before mutating Desktop history.
    await beforeCapture();
    if(!current())throw Error('ordered.controls_owner');
    await session?.beforeReply();
    if(!current())throw Error('ordered.controls_owner');
  };
  const playExplicit=async(chunks:AudioChunk[])=>{
    if(!chunks.length)throw Error('No retained audio to replay.');
    if(!current())throw Error('ordered.controls_owner');
    if(replayRef.current)throw Error('ordered.replay_pending');
    const attempt:Replay={owner:options.owner,ticket:options.ticket,opening:true,cancelled:false};
    replayRef.current=attempt;setReplay(attempt);
    const allowed=()=>current()&&!attempt.cancelled&&replayRef.current===attempt;
    try{
      const id=session?.activeReplyId;if(id)await stopReply(id);
      await ordered.close();
      if(!allowed())return;
      if(chunks.length===1)await latest.current.ordinary.playNow(chunks[0]!);
      else await latest.current.ordinary.playSequence(chunks);
      if(!allowed())return;
    }finally{
      attempt.opening=false;
      if(replayRef.current===attempt){
        if(!allowed())setReplay(null);
        else setReplay({...attempt});
      }
    }
  };
  const playNow=(chunk:AudioChunk)=>playExplicit([chunk]);
  const close=()=>ordered.close();
  const interrupt=()=>{
    stopExplicit();void close().catch(failed);
  };
  const explicit=Boolean(replay),ordinary=options.ordinary;
  const playback:PlaybackState={...ordinary,
    enabled:options.autoplay,volume:options.volume,
    paused:explicit?ordinary.paused:session?.userPaused===true,
    manualRecovery:explicit?ordinary.manualRecovery:null,
    suspendForPeerInterruption:()=>explicit?ordinary.suspendForPeerInterruption():null,
    pause:async()=>{if(explicit){await ordinary.pause();return;}
      if(!current()||!session)throw Error('Ordered playback is unavailable.');
      await session.setUserPaused(true);},
    resume:async()=>{if(explicit){await ordinary.resume();return;}
      if(!current()||!session)throw Error('Ordered playback is unavailable.');
      await session.setUserPaused(false);},
    playSequence:playExplicit,
    stopCharacterPreview:id=>{if(!explicit||ordinary.currentChunk?.id!==id)return;
      ordinary.stopCharacterPreview(id);setReplay(null);},
    playingId:explicit?ordinary.playingId:session?.currentChunk?.id??'',
    currentChunk:explicit?ordinary.currentChunk:session?.currentChunk??null,
    preparedChunk:explicit?ordinary.preparedChunk:null,
    playedCount:session?.playedCount??0,
    lastCompletedChunk:explicit?ordinary.lastCompletedChunk:session?.lastCompletedChunk??null,
    // Source position is observation from exact native OS-consumed samples;
    // generic player time never substitutes for an unavailable source clock.
    sourceClockRequired:!explicit,
    positionSeconds:explicit?ordinary.positionSeconds:session?.sourcePositionSeconds??0,
    getPlaybackClock:explicit?ordinary.getPlaybackClock:(player,id)=>session?.getPlaybackClock(player,id)??null,
    isPlaying:explicit?ordinary.isPlaying:Boolean(!session?.userPaused&&session?.currentChunk&&session.player?.playing),
    activePlayer:explicit?ordinary.activePlayer:session?.currentChunk?session.player:null,
    activeReplyId:explicit?null:session?.activeReplyId??null,
    hasReplyAudio:!explicit&&Boolean(session?.activeReplyId),
    stopExplicitPlayback:explicit?stopExplicit:null,
    setEnabled:enabled=>{
      if(!current())return;
      options.onAutoplayChanged(enabled);
      if(!enabled&&session?.activeReplyId)void stopReply(session.activeReplyId).catch(failed);
    },
    playNow,interrupt,stop:()=>{void beforeCapture().catch(failed);},reset:interrupt,
    skipReply:id=>{if(current())skip(id);},
    freezeReply:id=>current()?session?.freezeReply(id)??null:null,
    replyDrained:(id,final)=>replies.finished.has(id)||replies.owners.get(id)?.replyDrained(id,final)===true,
    finishReply:id=>{
      if(replies.finished.has(id))return true;
      if(!replies.owners.get(id)?.finishReply(id))return false;
      replies.owners.delete(id);replies.finished.add(id);
      if(replies.finished.size>64)replies.finished.delete(replies.finished.values().next().value!);
      return true;
    },
    replyFinished:id=>replies.finished.has(id),
    completedReplySequence:id=>replies.owners.get(id)?.completedReplySequence(id)??-1,
    appendReplyMedia:(id,chunks)=>{
      if(!current()||!session)throw Error('ordered.controls_unavailable');
      replyOwner(id)?.appendReplyMedia(id,chunks);
      if(!latest.current.autoplay)void stopReply(id).catch(failed);
    },
    retireVisualCarrier:close,recoveryEpoch:options.recoveryEpoch??0,
    // Ordered recovery retires the entire old generation. It must never pass a
    // legacy per-source checkpoint off as a resumed ordered reader.
    suspendReplyPlayback:()=>{interrupt();throw Error('ordered.recovery_requires_generation_retirement');},
    restoreReplyPlayback:async()=>false,cancelReplyContinuation:interrupt,
  };
  const observeReplyStatus=(id:string,status:PhoneReplyStatus,reconciled:boolean)=>{
    if(current()&&!replies.finished.has(id))replyOwner(id)?.observeReplyStatus(id,status,reconciled);
  };
  return {...ordered,selected:options.selected,observeReplyStatus,
    playback:options.selected?playback:ordinary,beforeCapture,beforeConversationAction,close};
}
