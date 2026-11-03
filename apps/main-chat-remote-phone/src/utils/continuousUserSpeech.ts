import type { RemoteClient } from '../api/client';
import { setBackgroundTimeout as setTimeout, clearBackgroundTimer as clearTimeout } from './backgroundClock';
import type { AudioChunk, ContinuousSpeechState, PhoneReplyAuth } from '../api/types';
import type { AudioPlayer } from 'expo-audio';
import type { PlaybackClock } from '../hooks/useAudioQueue';
import type { ReadingPlayback } from '../hooks/useReadingAlong';
import { createPhoneAudioPlayer } from '../native/iosPlaybackGuard';
import { configurePhoneAudio } from '../native/phoneCaptureOwnership';
import { nativePlaybackError } from './nativePlaybackError';

let active = false;
const cancelled = () => new Error('User speech cancelled.');

/** Controls the existing player; pausing never cancels or acknowledges a turn. */
export class ContinuousUserPlayback {
  paused = false;
  audible = false;
  setAudible(value:boolean) { if(this.audible!==value){this.audible=value;this.changed();} }
  private pausedAt = 0;
  private pausedMillis = 0;
  private player: AudioPlayer | null = null;
  private operationId: string | null = null;
  private currentChunk: AudioChunk | null = null;
  private sample: PlaybackClock | null = null;
  private completed: {id:string;revision:number} | null = null;
  private completionRevision = 0;
  private volume = 1;
  private waiters = new Set<()=>void>();
  constructor(private changed:()=>void) {}
  get reading(): ReadingPlayback {
    return {readingRole:'user',currentChunk:this.currentChunk,activeReplyId:this.operationId,
      activePlayer:this.player,positionSeconds:this.sample?.seconds ?? 0,sourceClockRequired:true,
      isPlaying:this.audible,paused:this.paused,lastCompletedChunk:this.completed,
      getPlaybackClock:(player,id)=>player===this.player && id===this.currentChunk?.id ? this.sample : null};
  }
  begin(operationId:string) {this.operationId=operationId;this.changed();}
  observeChunk(chunk:ContinuousSpeechState['chunks'][number]) {
    this.currentChunk={...chunk,index:chunk.sequence_index,phone_request_id:this.operationId || undefined};
    this.sample=null;this.changed();
  }
  observePosition(status:{currentTime?:number;playing?:boolean;isBuffering?:boolean}) {
    if(typeof status.currentTime==='number' && Number.isFinite(status.currentTime) && status.currentTime>=0) {
      this.sample={seconds:status.currentTime,sampledAtMs:performance.now(),playing:Boolean(status.playing),
        buffering:Boolean(status.isBuffering)};
    }
  }
  completeChunk() {
    if(this.currentChunk)this.completed={id:this.currentChunk.id,revision:++this.completionRevision};
    this.currentChunk=null;this.sample=null;this.changed();
  }
  get clock() {return Date.now()-this.pausedMillis-(this.paused?Date.now()-this.pausedAt:0);}
  setVolume(value:number) {
    this.volume=Number.isFinite(value)?Math.max(0,Math.min(1,value)):1;
    if(this.player)this.player.volume=this.volume;
  }
  bind(player:typeof this.player) {
    this.player=player;
    if(player)player.volume=this.volume;
    else {this.currentChunk=null;this.sample=null;this.setAudible(false);}
  }
  pause() {
    if(this.paused)return;
    this.player?.pause(); this.paused=true;this.audible=false;this.pausedAt=Date.now();this.changed();
  }
  resume() {
    if(!this.paused)return;
    this.player?.play();this.pausedMillis+=Date.now()-this.pausedAt;this.paused=false;
    this.waiters.forEach(wake=>wake());this.changed();
  }
  reset(preserveReadingOperation=false) {
    this.player=null;this.currentChunk=null;this.sample=null;
    if(!preserveReadingOperation)this.operationId=null;
    this.paused=false;this.audible=false;this.pausedMillis=0;
    this.waiters.forEach(wake=>wake());this.changed();
  }
  async ready(signal:AbortSignal) {
    if(signal.aborted)throw cancelled();
    if(!this.paused)return;
    await new Promise<void>((resolve,reject)=>{
      const wake=()=>{this.waiters.delete(wake);signal.removeEventListener('abort',abort);signal.aborted?reject(cancelled()):resolve();};
      const abort=()=>wake();this.waiters.add(wake);signal.addEventListener('abort',abort,{once:true});
      if(signal.aborted)wake();
    });
  }
}

function bounded<T>(work: Promise<T>, signal: AbortSignal, milliseconds = 120000, playback?:ContinuousUserPlayback): Promise<T> {
  return new Promise((resolve, reject) => {
    const abort = () => finish(cancelled());
    const started=playback?.clock ?? Date.now();
    let timer:ReturnType<typeof setTimeout>;
    const expire=()=>{
      const remaining=milliseconds-((playback?.clock ?? Date.now())-started);
      if(remaining>0 || playback?.paused)timer=setTimeout(expire,playback?.paused?1000:remaining);
      else finish(new Error('User speech timed out.'));
    };
    timer=setTimeout(expire,milliseconds);
    const finish = (error?: Error, value?: T) => {
      clearTimeout(timer); signal.removeEventListener('abort', abort);
      if (error) reject(error); else resolve(value as T);
    };
    signal.addEventListener('abort', abort, {once:true});
    work.then(value => finish(undefined, value), error => finish(error));
    if (signal.aborted) abort();
  });
}

/** A prelude to Continuous admission, never an assistant audio receipt. */
export async function readContinuousUserMessage(client: RemoteClient, auth:()=>Promise<PhoneReplyAuth>, operationId:string, signal: AbortSignal, playbackTicket?: string | null, playback?:ContinuousUserPlayback): Promise<void> {
  if (signal.aborted) throw cancelled();
  if (active) throw new Error('User speech is still stopping. Resume shortly.');
  active = true;
  playback?.begin(operationId);
  try {
    const owner=await bounded(auth(),signal);
    let status=await bounded(client.continuousSpeech(owner,operationId,'start'),signal);
    // The desktop receipt is authoritative if playback completed before a reconnect.
    if (status.played && !status.error) return;
    let completed=0;
    const deadline=(playback?.clock ?? Date.now())+300000;
    await bounded(configurePhoneAudio({playsInSilentMode:true}), signal);
    while(true) {
      await playback?.ready(signal);
      if (signal.aborted) throw cancelled();
      if (status.error) throw new Error(status.error);
      if ((playback?.clock ?? Date.now())>deadline) throw new Error('Desktop user speech timed out.');
      const chunk=status.chunks[completed];
      if(chunk) {
        if(chunk.sequence_index!==completed) throw new Error('User speech stream is incomplete.');
        const media=await bounded(client.authorizedMediaUrl(chunk.url_path),signal);
        if (signal.aborted) throw cancelled();
        const player = createPhoneAudioPlayer({uri:media.url}, {updateInterval:100}, playbackTicket);
        playback?.bind(player);
        playback?.observeChunk(chunk);
        let subscription: {remove():void} | undefined;
        try {
          await bounded(new Promise<void>((resolve,reject) => {
            subscription = player.addListener('playbackStatusUpdate', status => {
              playback?.observePosition(status);
              playback?.setAudible(Boolean(status.playing) && !status.didJustFinish);
              const error = nativePlaybackError(status as typeof status & {nativePlayerErrorCode?: number; error?: string});
              if (error) reject(new Error(error));
              else if (status.didJustFinish) resolve();
            });
            try { if(!playback?.paused)player.play(); } catch (error) { reject(error); }
          }), signal, Math.max(120000, ((chunk.duration_seconds ?? 0) + 30) * 1000), playback);
          playback?.completeChunk();
        } finally {
          playback?.bind(null);
          // remove() unregisters Expo's handle; release() destroys its native engine.
          // Cleanup must continue even if the failed player rejects an operation.
          try { subscription?.remove(); } catch {}
          try { player.pause(); } catch {}
          try { player.remove(); } catch {}
          try { player.release(); } catch {}
        }
        completed++;
      } else if(status.done) {
        if(!completed) throw new Error('Desktop TTS produced no audio.');
        // This receipt follows actual player completion, never synthesis completion.
        await bounded(client.continuousSpeech(owner,operationId,'played',completed),signal);
        return;
      } else {
        await bounded(new Promise<void>(resolve=>setTimeout(resolve,250)),signal);
      }
      status=await bounded(client.continuousSpeech(owner,operationId,'status'),signal);
    }
  // The preview remains owned until Continuous completes its normal submission.
  // Only its display identity survives; the player and clock are always cleared.
  } finally { active = false; playback?.reset(true); }
}
