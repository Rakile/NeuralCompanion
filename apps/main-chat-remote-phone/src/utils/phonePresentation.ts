// Presentation telemetry only: no audio, capture, or visual-player commands.
export type PhonePresentationPosition = {avatarId: string; mediaId: string; sourceFrameCount: number;
  sourceFrame: number; fps: 24; playing: boolean; handoffRange?: {startFrame:number;endFrame:number}};
/** Upcoming one-to-three-second source window, chosen at the display owner.
 * Endpoints follow the cached source cycle; they do not prescribe desktop
 * ping-pong direction. Short source cycles use the largest fitting even span. */
export function declareHandoffRange(position:PhonePresentationPosition):{startFrame:number;endFrame:number}|null {
  const {sourceFrameCount:count,sourceFrame:frame,fps,playing}=position;
  if(!playing || fps!==24 || !Number.isSafeInteger(count) || count<3 || count>1440
    || !Number.isSafeInteger(frame) || frame<0 || frame>=count)return null;
  const span=Math.min(48,Math.floor((count-1)/2)*2);
  const startFrame=(frame+24)%count;
  return {startFrame,endFrame:(startFrame+span)%count};
}
export type PhonePositionReader = () => PhonePresentationPosition | null;
export type HandoffExchange = {payload:Record<string,unknown>;accept:(response:unknown)=>void};
type Request = {id:string;avatarId:string;mediaId:string;sourceFrameCount:number};
export type HandoffClaimObservation={reason:string;expected:boolean|number;actual:boolean|number};
/** Frozen visual agreement only; never an audio capability. */
export class PhoneHandoffSession {
  private serial=0;
  private current:(Request & {startFrame:number;endFrame:number;confirmed:boolean;used:boolean})|null=null;
  private seen=new Set<string>();
  constructor(private read:PhonePositionReader,private observe:(state:'declared'|'confirmed'|'rejected')=>void=()=>{},
    private declare:(position:PhonePresentationPosition)=>{startFrame:number;endFrame:number}|null=declareHandoffRange,
    private abandon:()=>void=()=>{},private diagnoseClaim:(row:HandoffClaimObservation)=>void=()=>{},
    private diagnoseExchange:(row:HandoffClaimObservation)=>void=()=>{}){}
  private trace(reason:string,expected:boolean|number=true,actual:boolean|number=false){
    try{this.diagnoseExchange({reason,expected,actual});}catch{}
  }
  clear(reason:'explicit'|'position_missing'|'position_changed'|'epoch_retired'='explicit'){
    this.trace('clear_'+reason+'_had_agreement',Boolean(this.current),Boolean(this.current));
    ++this.serial;this.current=null;this.trace('agreement_cleared');this.abandon();}
  private matches(value:Request){
    const p=this.read();
    const reason=!p?'position_missing':p.playing!==true?'position_not_playing'
      :p.avatarId!==value.avatarId?'position_avatar_changed':p.mediaId!==value.mediaId?'position_media_changed'
      :p.sourceFrameCount!==value.sourceFrameCount?'position_frame_count_changed':null;
    if(reason)this.trace(reason);return reason===null;
  }
  exchange():HandoffExchange {
    if(this.current && !this.matches(this.current))this.clear('position_changed');
    const current=this.current,serial=++this.serial;
    this.trace(current?'declaration_sent':'request_sent',serial,serial);
    return {payload:{version:1,...(current?{declaration:{id:current.id,startFrame:current.startFrame,endFrame:current.endFrame}}:{})},
      accept:(response:unknown)=>{
        if(serial!==this.serial){this.trace('exchange_superseded',this.serial,serial);return;}
        const value=(response as {handoff?:any})?.handoff;
        if(!value){this.trace('response_missing');return;}
        if(!['requested','confirmed'].includes(value.state)){this.trace('response_state_invalid');return;}
        if(value.version!==1){this.trace('response_version_invalid');return;}
        this.trace(value.state==='confirmed'?'confirmation_received':'request_received',serial,serial);
        const keys=['version','state','id','avatarId','mediaId','sourceFrameCount',...(value.state==='confirmed'?['startFrame','endFrame']:[])];
        if(Object.keys(value).length!==keys.length || keys.some(k=>!(k in value))){this.trace('response_shape_invalid');return;}
        if(typeof value.id!=='string' || !/^[a-f0-9]{32}$/.test(value.id)){this.trace('response_id_invalid');return;}
        if(typeof value.mediaId!=='string' || !/^[a-f0-9]{32}$/.test(value.mediaId)){this.trace('response_media_invalid');return;}
        if(!this.matches(value))return;
        if(value.state==='requested'){
          if(this.current?.id===value.id){this.trace('request_already_current');return;}
          if(this.seen.has(value.id)){this.trace('request_already_seen');return;}
          const position=this.read(),bounds=position && this.declare(position);if(!bounds){this.trace('declaration_unavailable');return;}
          this.seen.add(value.id);if(this.seen.size>32)this.seen.delete(this.seen.values().next().value!);
          this.current={id:value.id,avatarId:value.avatarId,mediaId:value.mediaId,sourceFrameCount:value.sourceFrameCount,
            ...bounds,confirmed:false,used:false};this.trace('declaration_created',true,true);this.observe('declared');
        }else{
          if(!this.current){this.trace('confirmation_without_agreement');return;}
          if(this.current.id!==value.id){this.trace('confirmation_id_changed');return;}
          if(this.current.startFrame!==value.startFrame){this.trace('confirmation_start_changed');return;}
          if(this.current.endFrame!==value.endFrame){this.trace('confirmation_end_changed');return;}
          this.trace(this.current.confirmed?'confirmation_already_accepted':'confirmation_accepted',true,true);
          if(!this.current.confirmed){this.current.confirmed=true;this.observe('confirmed');}
        }
      }};
  }
  claim(plan:{planId:string;avatarId:string;sourceFrameCount:number;speechEntryFrame:number;sourceIndices:number[]}):boolean {
    const c=this.current;
    const reject=(reason:string,expected:boolean|number=true,actual:boolean|number=false)=>{
      try{this.diagnoseClaim({reason,expected,actual});}catch{}return false;
    };
    if(!c)return reject('agreement_missing');
    if(!c.confirmed)return reject('agreement_unconfirmed');
    if(c.used)return reject('agreement_used',false,true);
    // Sample once, at the same point as the previous matches() predicate.
    const p=this.read();
    if(!p)return reject('position_missing');
    if(p.playing!==true)return reject('position_not_playing');
    if(p.avatarId!==c.avatarId)return reject('position_avatar_changed');
    if(p.mediaId!==c.mediaId)return reject('position_media_changed');
    if(p.sourceFrameCount!==c.sourceFrameCount)return reject('position_frame_count_changed',c.sourceFrameCount,p.sourceFrameCount);
    if(plan.planId!==c.id)return reject('plan_id_changed');
    if(plan.avatarId!==c.avatarId)return reject('plan_avatar_changed');
    if(plan.sourceFrameCount!==c.sourceFrameCount)return reject('plan_frame_count_changed',c.sourceFrameCount,plan.sourceFrameCount);
    const count=c.sourceFrameCount,span=(c.endFrame-c.startFrame+count)%count;
    const forward=Array.from({length:span+1},(_,i)=>(c.startFrame+i)%count);
    const cycle=[...forward,...forward.slice(1,-1).reverse()],middle=span/2;
    const ordered=[...cycle.slice(middle),...cycle.slice(0,middle)];
    const reverse=[ordered[0],...ordered.slice(1).reverse()];
    if(plan.speechEntryFrame!==ordered[0]){this.observe('rejected');return reject('entry_frame_changed',ordered[0],plan.speechEntryFrame);}
    if(plan.sourceIndices.length!==ordered.length){this.observe('rejected');return reject('cycle_length_changed',ordered.length,plan.sourceIndices.length);}
    if(![ordered,reverse].some(indices=>indices.every((n,i)=>n===plan.sourceIndices[i]))){this.observe('rejected');return reject('cycle_order_changed');}
    c.used=true;return true;
  }
}
// Scope readers to the exact client object, never to a shared URL/account.
const readers = new WeakMap<object, PhonePositionReader>();
const handoffs = new WeakMap<object,()=>HandoffExchange|null>();
export function registerPhoneHandoff(client:object,exchange:()=>HandoffExchange|null){
  handoffs.set(client,exchange);return()=>{if(handoffs.get(client)===exchange)handoffs.delete(client);};
}
export function exchangePhoneHandoff(client:object){return handoffs.get(client)?.() ?? null;}
export function registerPhonePositionReader(client: object, reader: PhonePositionReader) {
  readers.set(client,reader);
  return () => { if (readers.get(client) === reader) readers.delete(client); };
}
export function hasPhonePositionReader(client: object) { return readers.has(client); }
export function readPhonePosition(client: object) {
  try { return readers.get(client)?.() ?? null; } catch { return null; }
}
let sequence = Date.now() * 1000;
export class PhonePresentationReporter {
  private closed = false;
  private announced = false;
  private pending = false;
  private desired = false;
  constructor(private send: (active: boolean, sequence: number) => Promise<void>) {}
  update(active: boolean) {
    if (this.closed) return;
    this.desired = active;
    if (!active) {
      if (this.announced) { this.announced = false; this.publish(false); }
      return;
    }
    if (this.pending) return;
    this.announced = true; this.pending = true;
    this.publish(true, () => {
      this.pending = false;
      if (this.desired && !this.announced && !this.closed) this.update(true);
    });
  }
  close() {
    if (this.closed) return;
    this.update(false); this.closed = true;
  }
  private publish(active: boolean, settled = () => {}) {
    // Assign before asynchronous auth/network work: a delayed heartbeat may
    // arrive after release, but can never have a newer sequence than release.
    const next = sequence = Math.max(sequence + 1, Date.now() * 1000);
    void Promise.resolve().then(() => this.send(active,next)).catch(() => undefined).finally(settled);
  }
}
