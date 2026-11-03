import {IdleChunkQueue} from '../native/idleChunkQueue';
import {parseIdleChunkStatus} from './idleChunkProtocol';
import type {IdleChunkStatus,IdleChunkRow,IdleChunkReturn,IdleChunkWaitingAuthority} from './idleChunkProtocol';
import type {BufferedMediaStore,BufferedMediaScope,BufferedMediaLease} from '../relay/bufferedMedia';
import type {MuxedTrialAudioSession} from './muxedTrialAudio';
import type {MuxedTrialFile,MuxedTrialPlan} from './muxedTrialDelivery';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';
import {IdleDiagnosticTrace} from '../diagnostics/idleTrace';
import {siteEnabled} from '../diagnostics/policy';
import {reportMuxedReturn} from '../utils/muxedReturnDiagnostics';
import {reportMuxedIdleFailure} from '../utils/muxedIdleDiagnostics';
import type {MuxedIdleOperation} from '../utils/muxedIdleDiagnostics';
import type {AudioPlayer} from 'expo-audio';
import type {PhonePresentationPosition} from '../utils/phonePresentation';
type Reader=Awaited<ReturnType<MuxedTrialAudioSession['openIdle']>>;
export type QueuedIdleReader={player:AudioPlayer;append(rows:MuxedTrialFile[],first:number):Promise<boolean>;
  position():{index:number;seconds:number}|null;prune(index:number):Promise<number|null>};
export type QueuedIdleBinding={open(status:IdleChunkStatus,files:MuxedTrialFile[],signal:AbortSignal,owns:()=>boolean):Promise<QueuedIdleReader|null>;
  detach():Promise<void>};
type Metadata=Omit<MuxedTrialFile,'uri'>&{path:string;sha256:string;sourceIndices:number[]};
type Dependencies={trialId:string;requestId:string;startFrame:number;ticket:string;scope:BufferedMediaScope;
  settings:Parameters<MuxedTrialAudioSession['openIdle']>[1];current():boolean;
  store:Pick<BufferedMediaStore,'acquire'|'owns'>;audio:Pick<MuxedTrialAudioSession,'openIdle'>;
  returnSource?:IdleChunkReturn;returnPrefetch?:boolean;returnPrefill?:2|6;retryable?(error:unknown):boolean;
  request(path:string,body:Record<string,unknown>,signal:AbortSignal):Promise<unknown>};

/** Scoped complete-file idle on the muxed session's embedded native clock.
 * The legacy video-only reader and separate-audio handoff are not involved. */
export class MuxedTrialIdle {
  private readonly diagnosticTrace=new IdleDiagnosticTrace();
  private readonly abort=new AbortController();
  private readonly queue:IdleChunkQueue;
  private readonly metadata=new Map<number,Metadata>();
  private readonly leases=new Map<number,BufferedMediaLease>();
  private source:IdleChunkStatus|null=null;
  private reader?:Reader;
  private queuedReader?:QueuedIdleReader;
  private queuedBinding?:QueuedIdleBinding;
  private releasedThrough=0;
  private closed=false;
  private work?:Promise<void>;
  private closing?:Promise<void>;
  private sealing=false;
  private finishing?:Promise<void>;
  private waitingAuthority?:IdleChunkWaitingAuthority;
  private waitingOpening?:Promise<boolean>;
  private waitingFinishing?:Promise<boolean>;
  private negotiating=false;
  private waitingProposal?:{index:number;frames:12;startFrame:number;endFrame:number};
  private boundaryGeneration=0;
  private boundaryLastChange='never_proposed';
  private positionRejection='not_sampled';
  private boundaryTrace(reason:string,position?:number):void{
    try{
      if(!siteEnabled('muxed_idle.handoff'))return;
      const fields={generation:this.boundaryGeneration,proposal_present:Boolean(this.waitingProposal),
        index:this.waitingProposal?.index??-1,position:position??-1,
        authority_present:Boolean(this.waitingAuthority),opening:Boolean(this.waitingOpening),negotiating:this.negotiating};
      for(const [key,actual] of Object.entries(fields))this.diagnosticTrace.handoffObserved({
        reason:`boundary.${reason}.${key}`,expected:actual,actual});
      this.diagnosticTrace.handoffObserved({reason:`boundary.${reason}.last_change.${this.boundaryLastChange}`,expected:true,actual:true});
    }catch{} // Observation must never change boundary ownership.
  }
  private operation:MuxedIdleOperation='queue';
  constructor(private readonly deps:Dependencies){
    if(!deps.ticket||!deps.scope.owner||!deps.scope.replyId||deps.scope.expiresAt<=Date.now())throw Error('Muxed idle authority unavailable.');
    this.queue=new IdleChunkQueue({trialId:deps.trialId,requestId:deps.requestId,startFrame:deps.startFrame,
      returnSource:deps.returnSource,returnPrefetch:deps.returnPrefetch,returnPrefill:deps.returnPrefill,current:()=>this.live(),retryable:deps.retryable,
      request:(path,body,signal)=>this.request(path,body,signal),
      waitingAuthority:()=>this.waitingAuthority,
      retain:async(status,row,signal)=>{
        const metadata=this.metadata.get(row.index);if(!metadata||metadata.path!==row.uri)throw Error('Muxed idle descriptor unavailable.');
        this.operation='retain';
        this.trace('retain_start',{chunk_index:row.index,bytes:metadata.bytes});
        const file=await deps.store.acquire(deps.scope,{id:`muxed-idle-${status.mediaId}-${row.index}`,
          path:metadata.path,bytes:metadata.bytes,contentType:'video/mp4'},signal);
        this.leases.set(row.index,file);
        this.trace('retain_done',{chunk_index:row.index});
        return {uri:file.uri,release:async()=>{this.operation='release';await file.release();this.leases.delete(row.index);this.metadata.delete(row.index);}};
      },
      prepare:async(status,row,file)=>{
        this.source=status;
        this.operation='append';
        this.trace('native_open_start',{chunk_index:row.index});
        this.reader=await deps.audio.openIdle([this.file(row,file.uri)],deps.settings,deps.ticket,this.abort.signal,()=>this.owns());
        this.trace('native_open_done',{chunk_index:row.index});return true;
      },
      append:async(status,row,file)=>{
        this.operation='append';const rows=[this.file(row,file.uri)];
        this.trace('append_start',{chunk_index:row.index,queued:Boolean(this.queuedReader)});
        const result=this.queuedReader?(await this.queuedReader.append(rows,row.index)?true:'blocked'):
          await (this.reader?.append(rows,row.index)??false);
        this.trace('append_done',{chunk_index:row.index,result});return result;
      },
      select:async()=>{if(!this.reader||!this.owns()){this.trace('play_rejected');return false;}
        this.trace('play_start');this.reader.play();this.trace('play_issued');return true;},
      position:()=>this.source?{mediaId:this.source.mediaId,releasedThrough:this.releasedThrough}:null,
      detach:async()=>{if(this.queuedBinding)await this.queuedBinding.detach();else await this.reader?.detach();return true;}});
  }
  private trace(step:string,details:Record<string,unknown>={}):void{
    try{if(siteEnabled('muxed_idle.'+step))this.diagnosticTrace.observe(step,{trial_id:this.deps.trialId,player_id:this.player?.id,
      retained_files:this.leases.size,released_through:this.releasedThrough,...details});}catch{}
    try{if(siteEnabled('muxed_idle_transaction','info'))void recordPhoneDebug('info','muxed_idle_transaction',{
      step,monotonic_ms:performance.now(),trial_id:this.deps.trialId,request_id:this.deps.requestId,
      media_id:this.source?.mediaId??null,retained_files:this.leases.size,released_through:this.releasedThrough,
      closed:this.closed,sealing:this.sealing,negotiating:this.negotiating,...details,
    }).catch(()=>undefined);}catch{}
  }
  private live(){return !this.closed&&!this.abort.signal.aborted&&this.deps.current()&&this.deps.scope.expiresAt>Date.now();}
  private owns(){
    // releasedThrough advances only after native prune certifies reader closure.
    // Those consumed leases stay tracked until asynchronous unlink completes,
    // but their revoked storage pins no longer own current/future playback.
    return this.live()&&Array.from(this.leases.entries()).every(([index,file])=>
      index<this.releasedThrough||this.deps.store.owns(this.deps.scope,file.uri));
  }
  private file(row:IdleChunkRow,uri:string):MuxedTrialFile{
    const value=this.metadata.get(row.index);if(!value)throw Error('Muxed idle metadata ended.');
    const {path,sha256,sourceIndices,...file}=value;return {...file,uri};
  }
  private async request(path:string,body:Record<string,unknown>,signal:AbortSignal){
    this.operation=path.endsWith('/idle-chunk-cursor')?'cursor_ack':'status';
    const operation=this.operation;
    this.trace('request_start',{operation});
    let raw:unknown;
    try{raw=await this.deps.request(path,body,signal);}
    catch(error){this.trace('request_failed',{operation,aborted:signal.aborted});throw error;}
    this.trace('request_done',{operation});
    if(!path.endsWith('/idle-chunks'))return raw;
    const status=parseIdleChunkStatus(raw,this.deps.trialId,this.deps.requestId,this.waitingAuthority);if(!status)return raw;
    const value=raw as {muxedAudio?:unknown;segments:Array<Record<string,unknown>>};
    if(value.muxedAudio!==true)throw Error('Muxed idle mode changed.');
    for(const row of status.segments){
      if(row.state!=='ready')continue;
      const samples=value.segments.find(item=>item.index===row.index)!;
      const delay=samples.delaySamples,padding=samples.paddingSamples,rawSamples=samples.rawSamples;
      if(samples.sampleRate!==48000||samples.validSamples!==24000||!Number.isSafeInteger(delay)||Number(delay)<0||Number(delay)>2048
        ||!Number.isSafeInteger(padding)||Number(padding)<0||Number(padding)>1023
        ||!Number.isSafeInteger(rawSamples)||Number(rawSamples)%1024!==0||Number(rawSamples)>28672
        ||Number(rawSamples)-Number(delay)-Number(padding)!==24000)throw Error('Invalid muxed idle sample range.');
      const metadata:Metadata={index:row.index,startFrame:row.startFrame,frameCount:12,bytes:row.bytes!,path:row.uri!,sha256:row.sha256!,sourceIndices:[...row.sourceIndices],
        sampleRate:48000,fps:24,validSamples:24000,delaySamples:Number(delay),paddingSamples:Number(padding),rawSamples:Number(rawSamples)};
      const previous=this.metadata.get(row.index);
      if(previous&&JSON.stringify(previous)!==JSON.stringify(metadata))throw Error('Muxed idle descriptor changed.');
      this.metadata.set(row.index,metadata);
    }
    if(this.metadata.size>12)throw Error('Muxed idle metadata capacity exceeded.');
    this.source=status;return raw;
  }
  get ready(){return this.queue.ready;}
  get retainedReady(){return this.owns()&&this.queue.retainedWindow()!==null;}
  get player(){return this.queuedReader?.player??this.reader?.player??null;}
  readIdlePosition():PhonePresentationPosition|null{
    const reject=(reason:string)=>{
      if(this.positionRejection!==reason){this.positionRejection=reason;this.boundaryTrace('position_unavailable_'+reason);}
      this.trace('position_unavailable',{reason});return null;};
    if(!this.owns())return reject('ownership_unavailable');
    if(this.sealing)return reject('sealing');
    try{
      const position=this.queuedReader?.position()??this.reader?.position(),source=this.source;
      if(!source)return reject('source_missing');
      if(!position)return reject('native_position_missing');
      const playing=this.player?.currentStatus.playing;
      this.trace('position_observed',{chunk_index:position.index,seconds:position.seconds,
        playing:playing??null,reader_present:Boolean(this.reader||this.queuedReader)});
      if(playing!==true)return reject('native_not_playing');
      if(!Number.isSafeInteger(position.index)||!Number.isFinite(position.seconds)
        ||position.seconds<0||position.seconds>=0.5)return reject('native_position_invalid');
      if(!this.leases.has(position.index))return reject('chunk_not_retained');
      const row=this.metadata.get(position.index),frame=row?.sourceIndices[Math.floor(position.seconds*24)];
      if(frame===undefined)return reject('frame_metadata_missing');
      if(this.positionRejection!=='none'){this.positionRejection='none';this.boundaryTrace('position_available');}
      this.trace('position_available',{chunk_index:position.index,seconds:position.seconds,source_frame:frame});
      return {avatarId:source.avatarId,mediaId:source.mediaId,sourceFrameCount:source.sourceFrameCount,
        sourceFrame:frame,fps:24,playing:true};
    }catch{return reject('native_position_read_threw');}
  }
  sourceFrame():number|null{
    return this.readIdlePosition()?.sourceFrame??null;
  }
  proposeWaitingBoundary(){
    if(!this.readIdlePosition()){this.boundaryTrace('rejected_position_'+this.positionRejection);return null;}
    if(!this.source||this.sealing||this.waitingAuthority){
      this.boundaryTrace(!this.source?'rejected_source_missing':this.sealing?'rejected_sealing':'rejected_authority');return null;}
    const count=this.source.sourceFrameCount,span=Math.min(48,Math.floor((count-1)/2)*2);
    const index=this.queue.reserveWaitingBoundary();
    if(span<2||index>10000){this.boundaryTrace(span<2?'rejected_span':'rejected_index');return null;}
    const entry=(this.source.startFrame+index*12)%count,startFrame=(entry-span/2+count)%count;
    this.waitingProposal={index,frames:12,startFrame,endFrame:(startFrame+span)%count};
    this.boundaryGeneration++;this.boundaryLastChange='created';this.boundaryTrace('created');
    return this.waitingProposal;
  }
  waitingBoundary(){const owned=this.owns();this.boundaryTrace(owned?'lookup':'lookup_ownership_unavailable');
    return owned&&this.waitingProposal?{...this.waitingProposal}:null;}
  abandonWaitingBoundary(reason='agreement_clear',position?:number){
    // An issued activation may already have committed on the producer. Only
    // a declaration with no request in flight can safely release its pin.
    if(this.waitingAuthority||this.waitingOpening||this.negotiating){this.boundaryTrace('retained_'+reason,position);return;}
    if(this.waitingProposal){this.boundaryLastChange=reason;this.boundaryTrace(reason,position);}
    this.waitingProposal=undefined;
    if(this.live())this.queue.releaseWaitingBoundary();
  }
  motionMatches(plan:MuxedTrialPlan){return this.source?.motionId===plan.timeline.motionId;}
  private async waitingPause(signal:AbortSignal){
    // Native prune has already joined the consumed row's reader. Its lease
    // release revokes storage ownership before asynchronous cleanup finishes;
    // join the tick before validating the remaining retained window.
    await this.work;
    if(!this.owns()||signal.aborted)throw Error('Muxed waiting owner ended.');
    await new Promise<void>(resolve=>{
      const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',done);this.abort.signal.removeEventListener('abort',done);resolve();};
      const timer=setTimeout(done,40);signal.addEventListener('abort',done,{once:true});this.abort.signal.addEventListener('abort',done,{once:true});
    });
    await this.work;
    if(!this.owns()||signal.aborted)throw Error('Muxed waiting owner ended.');
  }
  beginWaitingPlan(plan:NonNullable<MuxedTrialPlan['anticipation']>,boundary:{index:number;frames:number},files:MuxedTrialFile[],signal:AbortSignal):Promise<boolean>{
    if(this.waitingOpening)return this.waitingAuthority?.planId===plan.planId
      &&this.waitingAuthority.firstIndex===boundary.index&&boundary.frames===12
      &&JSON.stringify(this.waitingAuthority.sourceIndices)===JSON.stringify(plan.sourceIndices)
      ?this.waitingOpening:Promise.resolve(false);
    const proposal=this.waitingProposal,source=this.source,position=this.reader?.position();
    if(!this.owns()||signal.aborted||!proposal||!source||!position||this.queuedReader||this.sealing||files.length
      ||boundary.index!==proposal.index||boundary.frames!==proposal.frames||boundary.index<position.index+2
      ||plan.avatarId!==source.avatarId||plan.sourceFrameCount!==source.sourceFrameCount||plan.repeat!==true
      ||plan.speechEntryFrame!==(source.startFrame+boundary.index*12)%source.sourceFrameCount
      ||plan.sourceIndices[0]!==plan.speechEntryFrame||plan.exitAfterFrame!==plan.sourceIndices.length-1)
      return Promise.resolve(false);
    const authority:IdleChunkWaitingAuthority={planId:plan.planId,firstIndex:boundary.index,avatarId:plan.avatarId,
      sourceFrameCount:plan.sourceFrameCount,sourceIndices:[...plan.sourceIndices]};
    this.negotiating=true;
    return this.waitingOpening=(async()=>{
      try{
        await this.work;
        if(!this.owns()||signal.aborted)throw Error('Muxed waiting owner ended.');
        const current=this.reader?.position();if(!current||boundary.index<current.index+2)return false;
        this.waitingAuthority=authority;
          for(;;){
            const actual=this.reader?.position();
            if(!this.owns()||signal.aborted||!actual||boundary.index<actual.index+2)
              throw Error('Muxed desktop waiting boundary missed.');
            try{
              await this.request('/api/dev/musetalk-live/idle-chunks',{trialId:this.deps.trialId,requestId:this.deps.requestId,
                startFrame:this.deps.startFrame,waitingPlanId:authority.planId,waitingFirstIndex:authority.firstIndex},signal);
              break;
            }catch(error){if(!this.deps.retryable?.(error))throw error;await this.waitingPause(signal);}
          }
        if(!this.owns()||signal.aborted)throw Error('Muxed waiting owner ended.');
          this.queue.releaseWaitingBoundary();
      }finally{this.negotiating=false;}
      // Producer publication is not native admission. Both prefix rows must
      // have completed append ACKs before the speech coordinator may proceed.
      while(this.queue.retainedThrough<authority.firstIndex+2){await this.tick();await this.waitingPause(signal);}
      if(!this.owns()||signal.aborted)throw Error('Muxed waiting owner ended.');
      return true;
    })();
  }
  finishWaitingPlan(planId:string,files:MuxedTrialFile[],signal:AbortSignal,ownsPlan:()=>boolean=()=>true):Promise<boolean>{
    if(this.waitingAuthority?.planId!==planId||files.length)return Promise.resolve(false);
    return this.waitingFinishing??=this.finishWaiting(planId,signal,ownsPlan);
  }
  private async finishWaiting(planId:string,signal:AbortSignal,ownsPlan:()=>boolean):Promise<boolean>{
    const waiting=this.waitingAuthority;
    if(!waiting||waiting.planId!==planId||!await this.waitingOpening)return false;
    let target:number|undefined,frames=0;
    while(target===undefined){
      await this.work;
      if(!this.owns()||signal.aborted||!ownsPlan())throw Error('Muxed waiting owner ended.');
      await this.tick();const position=this.reader?.position();
      if(!position)throw Error('Muxed waiting position unavailable.');
      // The desktop prescribed exitAfterFrame at the end of each repetition.
      // Choose its next native-stageable occurrence, never a full idle scan.
      const earliest=(position.index+2)*12;
      const end=waiting.firstIndex*12+Math.max(1,Math.ceil((earliest-waiting.firstIndex*12+1)/waiting.sourceIndices.length))*waiting.sourceIndices.length-1;
      const index=Math.floor(end/12),count=end%12+1;
      if(index>10000)throw Error('Muxed waiting boundary capacity ended.');
      if(index>=position.index+2&&this.leases.has(index)){
        const row=this.metadata.get(index);
        if(row?.sourceIndices[count-1]!==waiting.sourceIndices.at(-1))throw Error('Muxed waiting exit changed.');
        target=index;frames=count;
      }else await this.waitingPause(signal);
    }
    this.sealing=true;await this.work;await this.queue.drain();
    const owns=()=>this.owns()&&!signal.aborted&&ownsPlan();
    if(!owns()||!this.reader||!await this.reader.seal([],target,frames,owns))throw Error('Muxed native planned boundary rejected.');
    while(!this.reader.silentEnded())await this.waitingPause(signal);
    if(!owns())throw Error('Muxed waiting owner ended.');return true;
  }
  tick():Promise<void>{
    if(this.work)return this.work;
    if(this.sealing||this.negotiating)return Promise.resolve();
    const work=(async()=>{
      try{
        if(!this.live())throw Error('Muxed idle owner ended.');
        this.operation='position';
        const position=this.queuedReader?.position()??this.reader?.position();
        this.trace('tick_position',{chunk_index:position?.index??null,seconds:position?.seconds??null});
          if(position&&this.waitingProposal&&!this.waitingAuthority&&!this.waitingOpening
            &&position.index>=this.waitingProposal.index-2)this.abandonWaitingBoundary('playhead_approaching',position.index);
        if(position&&position.index>this.releasedThrough){
          this.operation='prune';
          if(this.queuedReader){
            const through=await this.queuedReader.prune(position.index);
            if(!this.live())throw Error('Muxed idle owner ended.');
            if(through!==null){
              if(!Number.isSafeInteger(through)||through<this.releasedThrough||through>this.queue.retainedThrough)
                throw Error('Muxed queued idle closure changed.');
              this.releasedThrough=through;
            }
          }else{
            if(!await this.reader!.prune(position.index))throw Error('Muxed idle native prune unconfirmed.');
            if(!this.live())throw Error('Muxed idle owner ended.');
            this.releasedThrough=position.index;
          }
        }
        this.operation='queue';
        await this.queue.pump();
      }catch(error){
        reportMuxedIdleFailure(this.operation,error,this.leases.size,this.releasedThrough);throw error;
      }
    })().finally(()=>{if(this.work===work)this.work=undefined;});this.work=work;return work;
  }
  /** Install a native, future-only splice. Within one motion, locate the
   * desktop plan's predecessor. A validated source change ends a complete
   * outgoing clip; frame indices from different motions are not comparable.
   * The decoder plays the supplied anticipation before speech admission. */
  finishPlan(plan:MuxedTrialPlan,files:MuxedTrialFile[],signal:AbortSignal,ownsPlan:()=>boolean):Promise<void>{
    return this.finishing??=(async()=>{
      const started=Date.now(),deadline=started+60000;
      let stage:'search'|'selected'|'seal'|'await_end'|'ended'='search';
      let target:number|undefined,frames=0,lastReport=started;
      const report=(reason?:'idle_owner'|'signal'|'plan_owner'|'deadline')=>{
        let position:ReturnType<Reader['position']>|undefined,status:Reader['player']['currentStatus']|undefined;
        // Diagnostic reads must not replace the original authority failure if
        // native retirement has already invalidated its SharedObject handle.
        try{position=this.reader?.position();status=this.reader?.player.currentStatus;}catch{}
        const indices=[...this.leases.keys()].sort((a,b)=>a-b);
        void recordPhoneDebug(reason?'warning':'info','muxed_handoff',{stage,...(reason?{reason}:{}),
          elapsed_ms:Date.now()-started,scope_remaining_ms:this.deps.scope.expiresAt-Date.now(),
          cycle_frames:this.source?.sourceFrameCount??-1,entry_frame:plan.anticipation?.sourceIndices[0]??plan.timeline.sourceIndices[0]??-1,
          target_cycle_frames:plan.timeline.sourceFrameCount,motion_matches:this.source?.motionId===plan.timeline.motionId,
          count_matches:this.source?.sourceFrameCount===plan.timeline.sourceFrameCount,
          avatar_matches:this.source?.avatarId===plan.idleReturn.avatarId,
          anticipation_frames:plan.anticipation?.sourceIndices.length??0,position_index:position?.index??-1,
          position_seconds:position?.seconds??-1,retained_first:indices[0]??-1,retained_count:indices.length,
          target:target??-1,frames,ready:this.ready,playing:status?.playing===true,did_just_finish:status?.didJustFinish===true,
          native_error:Boolean((status as {error?:unknown}|undefined)?.error)}).catch(()=>undefined);
        lastReport=Date.now();
      };
      const check=()=>{
        const reason=!this.live()?'idle_owner':signal.aborted?'signal':!ownsPlan()?'plan_owner':Date.now()>deadline?'deadline':undefined;
        if(reason){report(reason);throw Error('Muxed planned handoff ended.');}
      };
      const wait=async()=>{check();await new Promise<void>(resolve=>{
        const done=()=>{clearTimeout(timer);signal.removeEventListener('abort',done);this.abort.signal.removeEventListener('abort',done);resolve();};
        const timer=setTimeout(done,40);signal.addEventListener('abort',done,{once:true});this.abort.signal.addEventListener('abort',done,{once:true});
      });check();};
      const anticipated=plan.anticipation;
      const entry=anticipated?.sourceIndices[0]??plan.timeline.sourceIndices[0];
      if(entry===undefined||plan.timeline.sourceFps!==24||files.reduce((n,file)=>n+file.frameCount,0)!==(anticipated?.sourceIndices.length??0)
        ||(anticipated&&(anticipated.speechEntryFrame!==plan.timeline.sourceIndices[0]||anticipated.exitAfterFrame!==anticipated.sourceIndices.length-1)))
        throw Error('Muxed desktop entry unavailable.');
      report();
      while(target===undefined){
        check();await this.tick();const source=this.source,position=this.reader?.position();
        const changing=source&&source.motionId!==plan.timeline.motionId;
        if(plan.idleReturn.motionId!==plan.timeline.motionId||plan.idleReturn.sourceFrameCount!==plan.timeline.sourceFrameCount
          ||anticipated&&(anticipated.avatarId!==plan.idleReturn.avatarId||anticipated.sourceFrameCount!==plan.timeline.sourceFrameCount)
          ||source&&!changing&&(source.sourceFrameCount!==plan.timeline.sourceFrameCount||source.avatarId!==plan.idleReturn.avatarId))
          throw Error('Muxed idle and desktop plan differ.');
        if(source&&position&&this.ready){
          const predecessor=(entry+source.sourceFrameCount-1)%source.sourceFrameCount;
          for(const index of [...this.leases.keys()].sort((a,b)=>a-b)){
            if(index<position.index+2)continue;
            // The incoming source was independently authenticated and its
            // timeline/return still agree. Keep the native future-only margin
            // and actual END proof, without searching the outgoing mood for
            // an unrelated incoming frame number or remapping that number.
            if(changing){target=index;frames=12;break;}
            const first=(source.startFrame+index*12)%source.sourceFrameCount;
            const offset=(predecessor-first+source.sourceFrameCount)%source.sourceFrameCount;
            if(offset<12){target=index;frames=offset+1;break;}
          }
        }
        if(target===undefined){if(Date.now()-lastReport>=5000)report();await wait();}
      }
      stage='selected';report();
      this.sealing=true;await this.work;await this.queue.drain();check();
      stage='seal';report();
      if(!this.reader||!await this.reader.seal(files,target,frames,ownsPlan))throw Error('Muxed native planned boundary rejected.');
      stage='await_end';report();
      while(!this.reader.silentEnded()){if(Date.now()-lastReport>=5000)report();await wait();}
      check(); // Silent END is not a speech receipt; native source epoch stays
      // alive until the staged speech install explicitly retires it.
      stage='ended';report();
    })();
  }
  async activateReturn():Promise<void>{
    if(this.queuedBinding)throw Error('Muxed queued RETURN cannot replace its source.');
    await this.queue.admitReturn(async window=>{
      this.source=window.status;
      reportMuxedReturn('idle_open_start');
      this.reader=await this.deps.audio.openIdle(window.files.map(file=>this.file(file.row,file.uri)),
        this.deps.settings,this.deps.ticket,this.abort.signal,()=>this.owns());
      reportMuxedReturn('idle_open_done');
      if(!this.owns())return false;this.reader.play();reportMuxedReturn('idle_play_issued');return true;
    });await this.tick();
    reportMuxedReturn('idle_tick_done');
  }
  /** Admission ACK enables independent refill; it is not onset or a play call. */
  activateQueuedReturn(binding:QueuedIdleBinding):Promise<boolean>{
    if(!this.live())throw Error('Muxed queued RETURN owner ended.');
    if(this.reader||this.queuedBinding&&this.queuedBinding!==binding)throw Error('Muxed queued RETURN owner changed.');
    this.queuedBinding=binding;
    return this.queue.tryAdmitReturn(async window=>{
      this.source=window.status;
      const reader=await binding.open(window.status,window.files.map(file=>this.file(file.row,file.uri)),
        this.abort.signal,()=>this.owns());
      if(!reader)return 'blocked';
      this.queuedReader=reader;
      if(!this.owns())throw Error('Muxed queued RETURN owner ended.');
      return true;
    });
  }
  /** Failed whole-session retirement still has to cancel/ join the queue's
   * transport work. This deliberately does not release its retained files. */
  async quiesce():Promise<void>{
    this.sealing=true;this.abort.abort();
    await Promise.allSettled([this.queue.quiesce(),this.work,this.waitingOpening,this.waitingFinishing]);
  }
  close():Promise<void>{
    return this.closing??=(async()=>{
      this.closed=true;this.abort.abort();
      // Stop output before waiting for an in-flight transfer/validation tick.
      const detached=this.queuedBinding?this.queuedBinding.detach():this.reader?.detach();
      // Queue.close synchronously aborts its own issued control/transfer
      // signal. Start it before joining tick, otherwise a retain-only return
      // can wait forever on the very request closing is supposed to cancel.
      const queued=this.queue.close();
      const results=await Promise.allSettled([detached,queued,this.work,this.waitingOpening,this.waitingFinishing]);
      const failed=results.slice(0,2).find(result=>result.status==='rejected');
      if(failed?.status==='rejected')throw failed.reason;
      this.metadata.clear();
    })();
  }
}
