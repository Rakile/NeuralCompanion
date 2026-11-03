import type {SoundAsset,SoundMedia,SoundscapeState,SoundscapeScope,SoundLayer,SoundscapeCue,SoundscapePatch,SoundChoice,SoundEffectGrant,SoundEffectPlayback} from '../api/soundscape';
import {soundscapeNative} from '../native/soundscape';
import {cuePatchAtOnset,cueEffectAsset} from './soundscapeCue';
import type {CachedSound} from '../relay/soundscapeCache';
import type {SoundscapeTransfer} from '../relay/soundscapeTransfer';

let epoch=Date.now();
type Native=typeof soundscapeNative;
/** Owns only optional background players. Never emits speech completion or admissions. */
export class SoundscapePlayback {
  scope:SoundscapeScope|null=null;
  private current:SoundscapeState|null=null;
  private generation=0;
  private disposed=false;
  private block='';
  private closed=true;
  private applied='';
  private request=new AbortController();
  private previewRequest=new AbortController();
  private loaded=new Map<SoundLayer,{asset:SoundAsset;handle:CachedSound}>();
  private previewHandle:CachedSound|null=null;
  private sourceSession=-1;
  private speechIds=new Set<string>();
  private seenOnsets=new Set<string>();
  private waitingOnset:{replyId:string;at:number}|null=null;
  private stagedCue:{cue:SoundscapeCue;session:number;ready:boolean;cancel:AbortController;handles:CachedSound[];effect?:{asset:SoundAsset;handle:CachedSound}}|null=null;
  private armedEffect:{cue:SoundscapeCue;session:number;asset:SoundAsset;handle:CachedSound;onsetMs:number}|null=null;
  // Admission owns its handle until finally; refresh/Skip must still see its asset.
  private pendingEffect:SoundscapePlayback['armedEffect']=null;
  private effectIntent=0;
  private activeEffectChoice='';
  private choices:SoundChoice[]=[];
  private subscription:{remove():void};
  constructor(private transfer:SoundscapeTransfer,private changed:(status:string,previewId?:string,effect?:SoundEffectPlayback,previewPaused?:boolean)=>void,
    private native:Native=soundscapeNative,private pauses=new Map<string,string>(),private identity=()=> '',private now=()=>Date.now()) {
    this.subscription=native.subscribe(event=>{
      if(this.disposed || !this.scope || event.revision!==this.scope.revision
        || event.conversation_id!==this.scope.conversation_id || event.session_generation!==this.scope.session_generation
        || event.playback_generation!==this.scope.playback_generation)return;
      const reason=String(event.reason||'');
      if(reason==='effect_started'&&typeof event.effect_cue_id==='string') {
        this.activeEffectChoice=event.effect_cue_id;this.changed('',undefined,{choiceId:this.activeEffectChoice,status:'playing'});
      } else if((['effect_ended','effect_stopped','effect_error'].includes(reason)||event.effect_active===false)&&this.activeEffectChoice) {
        this.changed('',undefined,{choiceId:this.activeEffectChoice,status:reason==='effect_ended'?'finished':'stopped'});this.activeEffectChoice='';
      }
      if(['pause:user','pause:route','pause:service','pause:connection'].includes(reason))this.rememberPause(reason.slice(6));
      if(reason==='preview_stopped') { void this.releasePreview(); this.changed('Preview stopped',''); }
      else if(reason==='preview_paused')this.changed('Preview paused',undefined,undefined,true);
      else if(reason==='preview_resumed')this.changed('Previewing',undefined,undefined,false);
      else if(reason.startsWith('pause:'))this.changed(reason==='pause:focus'?'Paused for another audio app':'Paused — tap Resume',reason==='pause:focus'?undefined:'');
      else if(reason==='player_error'||reason==='preview_error')this.changed('Sound playback unavailable','');
      else if(reason==='resume')this.changed('Playing');
    });
  }
  private key(cid=this.scope?.conversation_id) {return `${this.identity()}|${cid??''}`;}
  private rememberPause(reason:string) {
    if(reason==='story'&&this.block)return;
    this.block=reason;this.pauses.set(this.key(),reason);
    if(this.pauses.size>64)this.pauses.delete(this.pauses.keys().next().value!);
  }
  async adopt(state:SoundscapeState,session:number,assets:SoundAsset[],onScopeReady?:()=>Promise<void>):Promise<void> {
    if(this.disposed)return;
    const effectChoice=this.choices.find(c=>c.id===this.activeEffectChoice);
    const effectAsset=this.armedEffect?.asset??this.pendingEffect?.asset??(effectChoice?{id:effectChoice.asset_id,revision:effectChoice.asset_revision}:null);
    if(effectAsset&&!assets.some(a=>a.id===effectAsset.id&&!a.discarded&&a.revision===effectAsset.revision))await this.stopEffects();
    if(this.stagedCue && (this.stagedCue.cue.conversation_id!==state.conversation_id
      ||this.stagedCue.cue.revision!==state.revision||this.stagedCue.session!==session))this.clearCue();
    const fingerprint=JSON.stringify([state,session,...['ambience','music'].map(layer=>{
      const asset=assets.find(a=>a.id===state[layer as SoundLayer].asset_id);return asset?[asset.id,asset.revision,asset.media.sha256,asset.loop,asset.gain]:null;
    })]);
    if(fingerprint===this.applied){await onScopeReady?.();return;}
    const prior=this.scope;
    const newConversation=!prior || state.conversation_id!==prior.conversation_id || session!==this.sourceSession;
    if(newConversation||!state.enabled||state.paused||!state.effects?.enabled||state.effects.muted){this.cancelOnset();await this.stopEffects();}
    this.request.abort();this.request=new AbortController();const signal=this.request.signal;
    const run=++this.generation;
    if(newConversation) {
      if(prior)await this.native.close(prior);
      await this.releaseAll();this.speechIds.clear();this.block=this.pauses.get(this.key(state.conversation_id))||'';
      this.seenOnsets.clear();
      this.waitingOnset=null;
    }
    if(this.disposed||run!==this.generation)return;
    this.current=state;this.sourceSession=session;
    this.scope={conversation_id:state.conversation_id,session_generation:newConversation?++epoch:prior!.session_generation,
      playback_generation:++epoch,revision:state.revision};
    const scope=this.scope;
    if(!state.enabled) { await this.native.begin(scope,'ambience');await this.native.close(scope);this.closed=true;await this.releaseAll();this.applied=fingerprint;this.changed('Off','');return; }
    this.closed=false;
    await this.native.begin(scope,'ambience');await this.native.duck(scope,state.duck_speech);
    if(state.paused||this.block)await this.native.pause(scope,this.block||'story');
    // Optional one-shots have a strict onset deadline. Background preparation
    // must not consume that window after the new native scope is admitted.
    await onScopeReady?.();
    this.changed('Preparing');
    let failed=false;
    for(const layer of ['ambience','music'] as const) {
      if(signal.aborted||this.disposed||run!==this.generation)return;
      try {
      const settings=state[layer],asset=assets.find(a=>a.id===settings.asset_id&&!a.discarded);
      const token=await this.native.begin(scope,layer);
      let loaded=this.loaded.get(layer);
      if(settings.asset_id && !asset) {failed=true;this.changed(`${layer} is missing from the library`);continue;}
      if(asset && (!loaded || loaded.asset.id!==asset.id || loaded.asset.media.sha256!==asset.media.sha256)) {
        const handle=await this.transfer.fetch(asset.media,signal);
        if(signal.aborted||this.disposed||run!==this.generation) {await handle.release();return;}
        const old=loaded;loaded={asset,handle};this.loaded.set(layer,loaded);await old?.handle.release();
      }
      if(signal.aborted||this.disposed||run!==this.generation)return;
      const gain=asset && Number.isFinite(asset.gain) && asset.gain>=0 && asset.gain<=1 ? asset.gain : 1;
      await this.native.apply({scope,layer,load_token:token,file_token:asset?loaded?.handle.fileToken:null,
        volume:settings.volume*gain,muted:settings.muted,loop:asset?.loop??true});
      if(!asset) {await loaded?.handle.release();this.loaded.delete(layer);}
      } catch(error) {if(signal.aborted||run!==this.generation)return;failed=true;this.changed(`${layer} could not load. Retrying shortly.`);}
    }
    if(run!==this.generation || this.disposed)return;
    // Scope changes reset native speech holds; restore only current audible IDs.
    for(const id of this.speechIds)await this.native.speech(scope,id,true,false);
    if(!state.paused&&!this.block) {
      const ok=await this.native.resume(scope);this.changed(ok?'Playing':'Paused — tap Resume');
    } else this.changed('Paused — tap Resume');
    if(!failed)this.applied=fingerprint;
  }
  async resume():Promise<void> {
    if(!this.scope || !this.current?.enabled)return;
    this.prepareResume();
    if(!await this.native.resume(this.scope))this.changed('Paused — audio focus or background permission is unavailable');
  }
  prepareResume(conversationId?:string):void { this.block='';this.pauses.delete(this.key(conversationId));this.applied=''; }
  async pause(reason='user'):Promise<void> {
    this.cancelOnset();
    await this.stopEffects();
    this.rememberPause(reason);
    ++this.generation;this.applied='';this.request.abort();this.previewRequest.abort();
    if(this.scope)await this.native.pause(this.scope,reason);
  }
  async resumeAfterStory():Promise<void> {
    if(this.block==='story'&&!this.current?.paused)await this.resume();
  }
  async speech(id:string,audible:boolean,terminal:boolean):Promise<void> {
    if(audible)this.speechIds.add(id);else this.speechIds.delete(id);
    if(this.scope && this.current?.enabled)await this.native.speech(this.scope,id,audible,terminal);
  }
  clearCue():void {
    const staged=this.stagedCue;this.stagedCue=null;
    if(staged){staged.cancel.abort();for(const handle of staged.handles)void handle.release().catch(()=>undefined);
      if(staged.effect)void staged.effect.handle.release().catch(()=>undefined);}
  }
  async stageCue(cue:SoundscapeCue|null,state:SoundscapeState,session:number,assets:SoundAsset[]):Promise<void> {
    if(this.disposed)return;
    // An older poll may finish after a newer reply was staged. Its consumed
    // cue must not remove that reply's ready background transition.
    if(cue&&this.seenOnsets.has(cue.reply_id))return;
    if(!cue||!cuePatchAtOnset(cue,state,session,assets,cue.reply_id)){this.clearCue();return;}
    if(this.stagedCue?.cue.id===cue.id&&this.stagedCue.session===session)return;
    this.clearCue();
    const staged:NonNullable<SoundscapePlayback['stagedCue']>={cue,session,ready:false,cancel:new AbortController(),handles:[]};
    this.stagedCue=staged;
    // Start optional effects alongside backgrounds. A slow background/cache
    // operation must not postpone acquisition of an already cached one-shot.
    const effectTask=(async()=>{
      try{
        const effect=this.native.effectsAvailable?.()?cueEffectAsset(cue,state,assets):null;
        if(!effect)return;
        const handle=await this.transfer.fetch(effect.media,staged.cancel.signal);
        if(this.stagedCue!==staged||staged.cancel.signal.aborted)await handle.release();
        else staged.effect={asset:effect,handle};
      }catch{/* Effects are optional; a prepared background remains usable. */}
    })();
    try{
      for(const layer of ['ambience','music'] as const){
        const id=cue.actions[layer];if(!id||id==='keep'||id==='clear')continue;
        const asset=assets.find(item=>item.id===id&&item.kind===layer);
        if(!asset)throw new Error('Scene sound is missing.');
        const handle=await this.transfer.fetch(asset.media,staged.cancel.signal);
        if(this.stagedCue!==staged||staged.cancel.signal.aborted){await handle.release();return;}
        staged.handles.push(handle);
      }
      if(this.stagedCue===staged&&!staged.cancel.signal.aborted)staged.ready=true;
    }catch{
      if(this.stagedCue===staged)this.clearCue();
    }
    await effectTask;
  }
  private consumeOnset(replyId:string):void {
    this.seenOnsets.add(replyId);if(this.seenOnsets.size>64)this.seenOnsets.delete(this.seenOnsets.values().next().value!);
  }
  cancelOnset():void {
    if(this.waitingOnset)this.consumeOnset(this.waitingOnset.replyId);
    this.waitingOnset=null;
  }
  canRetryOnset(replyId:string):boolean {
    const onset=this.waitingOnset,elapsed=onset?this.now()-onset.at:-1;
    return !this.disposed&&!this.block&&!!this.current?.enabled&&!this.current.paused
      &&onset?.replyId===replyId&&!this.seenOnsets.has(replyId)&&elapsed>=0&&elapsed<=250;
  }
  assistantOnset(replyId:string,state:SoundscapeState,session:number,assets:SoundAsset[]):SoundscapePatch|null {
    if(this.seenOnsets.has(replyId))return null;
    if(this.waitingOnset&&this.waitingOnset.replyId!==replyId)this.cancelOnset();
    this.waitingOnset??={replyId,at:this.now()};
    const onsetMs=this.waitingOnset.at,elapsed=this.now()-onsetMs;
    if(elapsed<0||elapsed>250){
      this.cancelOnset();
      if(this.stagedCue?.cue.reply_id===replyId&&this.stagedCue.session===session
        &&this.stagedCue.cue.conversation_id===state.conversation_id)this.clearCue();
      return null;
    }
    void this.stopEffects().catch(()=>undefined);
    const staged=this.stagedCue;
    if(!staged||staged.cue.reply_id!==replyId||!staged.ready)return null;
    this.consumeOnset(replyId);this.waitingOnset=null;
    const patch=cuePatchAtOnset(staged.cue,state,session,assets,replyId);
    if(patch&&staged.effect){this.armedEffect={cue:staged.cue,session,asset:staged.effect.asset,handle:staged.effect.handle,onsetMs};staged.effect=undefined;}
    this.clearCue();
    return patch;
  }
  setChoices(choices:SoundChoice[]):void {this.choices=choices;}
  async stopEffects():Promise<void> {
    this.effectIntent++;
    const armed=this.armedEffect;this.armedEffect=null;
    this.pendingEffect=null;
    if(this.activeEffectChoice)this.changed('',undefined,{choiceId:this.activeEffectChoice,status:'stopped'});
    this.activeEffectChoice='';
    const stopped=this.scope?this.native.stopEffect?.(this.scope):undefined;
    await Promise.all([stopped,armed?.handle.release()]);
  }
  async playEffectAtOnset(grant:SoundEffectGrant|null,replyId:string):Promise<boolean> {
    const armed=this.armedEffect;this.armedEffect=null;
    const omitted=(reason:'not_ready'|'late'|'unavailable')=>{
      if(grant)this.changed('',undefined,{choiceId:grant.choice_id,status:'omitted',reason});return false;
    };
    if(!armed)return omitted('not_ready');
    this.pendingEffect=armed;
    const intent=this.effectIntent,scope=this.scope;
    try{
      if(this.now()-armed.onsetMs>250)return omitted('late');
      if(!grant||this.disposed||!scope||this.block||this.current?.paused||!this.current?.enabled
        ||!this.current.effects?.enabled||this.current.effects.muted||this.now()-armed.onsetMs>250
        ||grant.conversation_id!==scope.conversation_id||grant.session_generation!==this.sourceSession
        ||grant.reply_id!==replyId||armed.cue.reply_id!==replyId||armed.session!==this.sourceSession
        ||grant.cue_id!==armed.cue.id||grant.asset_id!==armed.asset.id||grant.asset_revision!==armed.asset.revision||armed.asset.discarded)return false;
      const token=await this.native.begin(scope,'effect');
      if(this.now()-armed.onsetMs>250)return omitted('late');
      if(this.disposed||scope!==this.scope||intent!==this.effectIntent)return false;
      this.activeEffectChoice=grant.choice_id;
      const accepted=await this.native.effect({scope,load_token:token,file_token:armed.handle.fileToken,cue_id:grant.choice_id,
        volume:this.current.effects.volume*(Number.isFinite(armed.asset.gain)?armed.asset.gain:1),deadline_utc_ms:armed.onsetMs+250});
      if(!accepted||this.disposed||scope!==this.scope||intent!==this.effectIntent){
        this.activeEffectChoice='';return omitted(this.now()-armed.onsetMs>250?'late':'unavailable');
      }
      this.changed('',undefined,{choiceId:grant.choice_id,status:'playing'});return true;
    }finally{if(this.pendingEffect===armed)this.pendingEffect=null;await armed.handle.release();}
  }
  async stopChoice(choice:SoundChoice):Promise<void> {
    if(!this.scope||choice.conversation_id!==this.scope.conversation_id||choice.session_generation!==this.sourceSession)return;
    if(choice.layer==='effect'){
      if(this.activeEffectChoice===choice.id||this.armedEffect?.cue.id===choice.cue_id||this.pendingEffect?.cue.id===choice.cue_id)await this.stopEffects();
      return;
    }
    if(!this.choices.some(c=>c.layer===choice.layer&&c.id===choice.id)||this.current?.[choice.layer].asset_id!==choice.asset_id)return;
    const scope=this.scope,token=await this.native.begin(scope,choice.layer);
    if(scope!==this.scope)return;
    await this.native.apply({scope,layer:choice.layer,load_token:token,file_token:null,volume:0,muted:false,loop:true});
  }
  async preview(media:SoundMedia,volume=1,mixBackground=false):Promise<void> {
    if(this.disposed || !this.scope)return;
    await this.stopEffects();await this.stopPreview();this.previewRequest=new AbortController();
    const signal=this.previewRequest.signal,scope=this.scope;
    // Off closes the previous generation. A preview is a separate foreground intent.
    const next=this.closed?{...scope,playback_generation:++epoch}:scope;this.scope=next;this.closed=false;
    const token=await this.native.begin(next,'preview');
    const handle=await this.transfer.fetch(media,signal);
    if(this.disposed || signal.aborted || this.scope!==next) {await handle.release();return;}
    this.previewHandle=handle;
    const started=await this.native.preview({scope:next,load_token:token,file_token:handle.fileToken,volume,mix_background:mixBackground});
    if(signal.aborted||this.disposed||this.scope!==next)return;
    if(!started) {
      if(this.previewHandle===handle)await this.releasePreview();
      throw new Error('Preview could not start. Return to NC and try again.');
    }
    this.changed('Previewing',media.asset_id,undefined,false);
  }
  async previewPlaying(playing:boolean):Promise<void> {
    if(!this.scope||!this.previewHandle||!this.native.previewPlaying)throw new Error('Start a sound review first.');
    const scope=this.scope;
    if(!await this.native.previewPlaying(scope,playing))throw new Error('Sound review could not resume. Return to NC and try Play again.');
    if(!this.disposed&&scope===this.scope)this.changed(playing?'Previewing':'Preview paused',undefined,undefined,!playing);
  }
  private async releasePreview() { const handle=this.previewHandle;this.previewHandle=null;await handle?.release(); }
  async stopPreview():Promise<void> {
    this.previewRequest.abort();if(this.scope)await this.native.stopPreview(this.scope);await this.releasePreview();this.changed('','');
  }
  private async releaseAll() {
    await this.stopPreview();for(const item of this.loaded.values())await item.handle.release();this.loaded.clear();
  }
  async close():Promise<void> {
    if(this.disposed)return;this.cancelOnset();this.disposed=true;await this.stopEffects();++this.generation;this.request.abort();this.previewRequest.abort();this.clearCue();this.subscription.remove();
    if(this.scope)await this.native.close(this.scope);await this.releaseAll();this.scope=null;
  }
}
