import type {MuseTalkLiveSession} from '../dev/museTalkLiveSession';
import type {IdleChunkStatus,IdleChunkRow,IdleChunkReturn} from '../dev/idleChunkProtocol';
import type {SourceTimeline} from '../relay/frameHandoff';
import type {BufferedPresentation,PresentationChunkReader} from './bufferedPresentation';
import type {IdleChunkRenewal} from './idleChunkNativeReader';
import {IdleChunkQueue} from './idleChunkQueue';
import type {IdleChunkLease} from './idleChunkQueue';
import {IdleChunkContinuation} from './idleChunkContinuation';

type Dependencies={session:Pick<MuseTalkLiveSession,'trial'|'renewVisualArm'>;output:BufferedPresentation;current():boolean;
  now?():number;retryable?(error:unknown):boolean;
  request(method:'GET'|'POST',path:string,body?:Record<string,unknown>,signal?:AbortSignal):Promise<unknown>;
  retain(status:IdleChunkStatus,row:IdleChunkRow,signal:AbortSignal):Promise<IdleChunkLease>;
  diagnose(event:string,fields:Record<string,number|string>):void};
type Epoch={trialId:string;offset:number;queue:IdleChunkQueue;reader:PresentationChunkReader|null;renewal:IdleChunkRenewal|null;source:IdleChunkStatus|null};
type DrainingOwner={offset:number;queue:Pick<IdleChunkQueue,'pump'|'close'|'drained'>;reader:PresentationChunkReader|null};
const sameSource=(a:IdleChunkStatus,b:IdleChunkStatus)=>a.motionId===b.motionId&&a.avatarId===b.avatarId
  &&a.sourceFrameCount===b.sourceFrameCount&&JSON.stringify(a.videoQuality)===JSON.stringify(b.videoQuality);
let requestSequence=0;
// Correlation identity only; requests still use the existing authenticated client.
export function idleChunkRequestId(){return (Date.now().toString(16)+ (++requestSequence).toString(16).padStart(8,'0')
  +Math.floor(Math.random()*0x100000000).toString(16).padStart(8,'0')).padStart(32,'0').slice(-32);}

/** Complete pre-rendered idle files, never full cycles or RTP frames. One
 * visual scope may re-arm fresh finite producers without renewing audio or
 * restarting the observed same-source native clock. */
export class IdleChunkPlayback {
  private closed=false;
  private work:Promise<void>|null=null;
  private closing:Promise<void>|null=null;
  private active:Epoch|null=null;
  private readonly draining=new Set<DrainingOwner>();
  private readonly returns=new Set<IdleChunkContinuation>();
  private root:{reader:PresentationChunkReader;status:IdleChunkStatus}|null=null;
  private boundary=0;
  private armedAt=0;
  private readonly abort=new AbortController();
  constructor(private readonly deps:Dependencies){}
  private live(){return !this.closed&&this.deps.current()&&this.deps.output.presentationActive;}
  private check(){if(!this.live())throw Error('Idle chunk playback owner ended.');}
  private now(){return this.deps.now?.()??performance.now();}
  createReturn(value:{trialId:string;returnSource:IdleChunkReturn;timeline:SourceTimeline;fadeMs:number}):IdleChunkContinuation {
    this.check();
    if(this.deps.session.trial.snapshot.trialId!==value.trialId||this.deps.session.trial.snapshot.chunkedIdle!==true
      ||this.returns.size>=66)throw Error('Idle chunk return owner unavailable.');
    const controller=new IdleChunkContinuation({...value,requestId:idleChunkRequestId(),output:this.deps.output,
      current:()=>this.live(),request:(path,body,signal)=>this.deps.request('POST',path,body,signal),
      retain:this.deps.retain,retryable:this.deps.retryable});
    this.returns.add(controller);return controller;
  }
  async returnConfigured(current:IdleChunkContinuation):Promise<void>{
    this.check();if(!this.returns.has(current))throw Error('Idle chunk return owner ended.');
    for(const previous of this.returns){
      if(previous!==current&&previous.configured&&!previous.displayed){await previous.close();this.returns.delete(previous);}
    }
  }
  async finishReply(controllers:IdleChunkContinuation[],completed:boolean):Promise<void>{
    await this.work?.catch(()=>undefined);
    const selected=completed&&this.live()?controllers.find(controller=>this.returns.has(controller)&&controller.displayed):null;
    if(selected){
      const boundary=await selected.handover();this.check();
      if(this.active){await this.active.queue.close();this.active=null;}
      for(const old of this.draining){await old.queue.close();this.draining.delete(old);}
      const previous=this.root;
      this.root={reader:boundary.reader,status:boundary.source!};this.boundary=boundary.end;
      if(previous&&previous.reader!==boundary.reader&&!await previous.reader.close())throw Error('Old idle chunk reader detachment unavailable.');
      this.draining.add({offset:0,queue:selected,reader:boundary.reader});this.returns.delete(selected);
    }
    for(const controller of controllers){
      if(controller===selected||!this.returns.has(controller))continue;
      await controller.close();this.returns.delete(controller);
    }
  }
  tick():Promise<void>{
    if(this.work)return this.work;
    const work=this.run().finally(()=>{if(this.work===work)this.work=null;});
    this.work=work;return work;
  }
  private async drainActive(){
    const active=this.active;if(!active)return;
    const boundary=await active.queue.drain();this.check();
    this.boundary=active.offset+boundary.end;this.draining.add(active);this.active=null;
  }
  private async settleReplacement(epoch:Epoch){
    if(!epoch.reader||!epoch.source||epoch.renewal||!epoch.reader.position()||this.root?.reader===epoch.reader)return;
    const previous=this.root;
    this.root={reader:epoch.reader,status:epoch.source};
    for(const old of this.draining){await old.queue.close();this.draining.delete(old);}
    if(previous&&!await previous.reader.close())throw Error('Old idle chunk reader detachment unavailable.');
  }
  private async run(){
    this.check();
    const snapshot=this.deps.session.trial.snapshot;
    if(this.active&&snapshot.trialId!==this.active.trialId)await this.drainActive();
    for(const epoch of this.draining){
      await epoch.queue.pump();this.check();
      if(epoch.queue.drained){await epoch.queue.close();this.draining.delete(epoch);}
    }
    if(!this.active&&snapshot.phase==='armed'&&snapshot.chunkedIdle===true&&!this.deps.output.idleBusy){
      const trialId=snapshot.trialId;
      const raw=await this.deps.request('GET',`/api/dev/musetalk-live/status/${trialId}`,undefined,this.abort.signal);
      this.check();
      if(this.deps.session.trial.snapshot.trialId!==trialId||this.deps.session.trial.snapshot.phase!=='armed')return;
      const metadata=raw as {trialId?:string;state?:string;audio?:unknown;segments?:unknown[];motionId?:string;loopFadeMs?:number};
      if(!metadata||metadata.trialId!==trialId||metadata.state!=='armed'||metadata.audio!==null
        ||!Array.isArray(metadata.segments)||metadata.segments.length||metadata.loopFadeMs===undefined
        ||!Number.isSafeInteger(metadata.loopFadeMs)||metadata.loopFadeMs<0||metadata.loopFadeMs>5000)
        throw Error('Invalid armed idle chunk source.');
      if(!metadata.motionId)return; // The optional warmed source is not published yet.
      if(!/^[a-f0-9]{64}$/.test(metadata.motionId))throw Error('Invalid armed idle chunk motion.');
      const root=this.root,quality=this.deps.output.videoQuality;
      const sameMotionQuality=root&&root.status.motionId===metadata.motionId&&JSON.stringify(root.status.videoQuality)===JSON.stringify(quality);
      // The renderer's finite index namespace must eventually roll too. Prepare
      // its replacement ahead, then select only at the old retained boundary.
      const compatible=Boolean(sameMotionQuality&&this.boundary<=9000);
      const clockReset=Boolean(sameMotionQuality&&!compatible);
      const start=sameMotionQuality?(root.status.startFrame+this.boundary*12)%root.status.sourceFrameCount:0;
      const offset=compatible?this.boundary:0,requestId=idleChunkRequestId();
      const epoch:Epoch={trialId,offset,queue:null as unknown as IdleChunkQueue,reader:null,renewal:null,source:null};
      const renew=(status:IdleChunkStatus)=>{
        if(!root||!compatible||!sameSource(root.status,status))throw Error('Idle chunk renewal source changed.');
        if(!epoch.renewal){
          epoch.reader=root.reader;
          epoch.renewal=root.reader.renew(status,offset,()=>this.live()&&this.deps.session.trial.snapshot.trialId===trialId);
        }
        return epoch.renewal;
      };
      epoch.queue=new IdleChunkQueue({trialId,requestId,startFrame:start,current:()=>this.live(),retryable:this.deps.retryable,
        request:(path,body,signal)=>this.deps.request('POST',path,body,signal),retain:this.deps.retain,
        canOffer:(status,row)=>!compatible||renew(status).canOffer(row),
        prepare:async(status,row,file)=>{
          if(compatible)return renew(status).append(status,row,file);
          epoch.source=status;
          const reader=await this.deps.output.createIdleChunkReader(status,metadata.loopFadeMs!,()=>this.live());
          epoch.reader=reader;
          const ready=await reader.prepare(status,row,file);
          if(ready&&!root)this.root={reader,status};
          return ready;
        },append:(status,row,file)=>compatible?renew(status).append(status,row,file):epoch.reader!.append(status,row,file),
        select:async(status)=>{
          if(compatible)return true; // Joining files never reselects the reader.
          if(this.deps.output.idleBusy)return false;
          if(clockReset){
            const deadline=performance.now()+5000;
            for(;;){
              this.check();if(this.deps.output.idleBusy)throw Error('Idle chunk reset interrupted by speech.');
              for(const old of this.draining)await old.queue.pump();
              if(Array.from(this.draining).every(old=>old.queue.drained))break;
              if(performance.now()>=deadline)throw Error('Idle chunk reset boundary unavailable.');
              await new Promise(resolve=>setTimeout(resolve,20));
            }
          }
          const selected=await epoch.reader!.select();
          if(selected)await this.settleReplacement(epoch);
          return selected;
        },position:()=>epoch.renewal?.position()??epoch.reader?.position()??null,
        detach:()=>epoch.reader?.close()??Promise.resolve(true)});
      this.active=epoch;this.armedAt=this.now();
    }
    if(this.active){
      await this.active.queue.pump();this.check();
      await this.settleReplacement(this.active);this.check();
      if(this.active.queue.ready&&snapshot.phase==='armed'&&snapshot.trialId===this.active.trialId
        &&!this.deps.output.qualityBusy&&this.now()-this.armedAt>=90000){
        await this.drainActive();
        await this.deps.session.renewVisualArm();this.check();
      }
    }
  }
  close():Promise<void>{
    if(this.closing)return this.closing;
    this.closed=true;this.abort.abort();
    this.closing=(async()=>{
      await this.work?.catch(()=>undefined);
      const epochs=[...this.draining,...(this.active?[this.active]:[])];
      await Promise.all([...epochs.map(epoch=>epoch.queue.close()),...Array.from(this.returns,controller=>controller.close())]);
      if(this.root&&!await this.root.reader.close())throw Error('Idle chunk reader detachment unavailable.');
      this.draining.clear();this.returns.clear();this.active=null;
    })();
    return this.closing;
  }
}
