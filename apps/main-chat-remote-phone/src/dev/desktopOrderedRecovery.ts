import type {PhoneReplyAuth} from '../api/types';

/** Reconnects recover the same authority; desktop restarts begin a new one.
 * Keep legacy servers compatible and leave previous journal entries intact. */
export function scopeOrderedRecoveryProfile(profile:string,instance:unknown):string{
  return profile&&typeof instance==='string'&&/^[a-f0-9]{32}$/.test(instance)
    ?JSON.stringify(['ordered-authority-v1',profile,instance]):profile;
}

type Auth=Readonly<Pick<PhoneReplyAuth,'client_key'|'connection_epoch'>>;
type Custody=Readonly<{streamId:string;capability:string}>;
export type RecoveryBody=Readonly<{version:1;operationId:string;previousStreamId:string;previousCapability:string;capability:string}>;
export type RecoveryIntent=Readonly<({kind:'open';capability:string}|{kind:'recover';recovery:RecoveryBody})&{streamId:string;auth:Auth}>;
type RecordV1={version:1;current:Custody|null;pending:RecoveryIntent|null};
type Storage={read(scope:string):Promise<string|null>;write(scope:string,value:string):Promise<void>;random(bytes:number):Promise<string>};
const hex=(value:unknown,length:number)=>typeof value==='string'&&new RegExp(`^[a-f0-9]{${length}}$`).test(value);
function fields(value:unknown,keys:string[]):asserts value is Record<string,unknown>{
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==keys.length
    ||keys.some(k=>!(k in value)))throw Error('ordered.recovery_journal');
}
function auth(value:unknown):Auth{
  fields(value,['client_key','connection_epoch']);
  if(Object.values(value).some(v=>typeof v!=='string'||!v.length||v.length>256))throw Error('ordered.recovery_journal');
  return Object.freeze({client_key:value.client_key as string,connection_epoch:value.connection_epoch as string});
}
function custody(value:unknown):Custody{
  fields(value,['streamId','capability']);
  if(!hex(value.streamId,32)||!hex(value.capability,64))throw Error('ordered.recovery_journal');
  return Object.freeze({streamId:value.streamId as string,capability:value.capability as string});
}
function intent(value:unknown):RecoveryIntent{
  const kind=(value as {kind?:unknown})?.kind;
  if(kind==='open'){
    fields(value,['kind','streamId','capability','auth']);
    return Object.freeze({kind,...custody({streamId:value.streamId,capability:value.capability}),auth:auth(value.auth)});
  }
  fields(value,['kind','streamId','recovery','auth']);
  const r=value.recovery;fields(r,['version','operationId','previousStreamId','previousCapability','capability']);
  if(kind!=='recover'||r.version!==1||!hex(value.streamId,32)||!hex(r.operationId,32)||!hex(r.previousStreamId,32)
    ||!hex(r.previousCapability,64)||!hex(r.capability,64)||r.previousStreamId===value.streamId)throw Error('ordered.recovery_journal');
  return Object.freeze({kind,streamId:value.streamId as string,auth:auth(value.auth),recovery:Object.freeze({version:1,
    operationId:r.operationId as string,previousStreamId:r.previousStreamId as string,
    previousCapability:r.previousCapability as string,capability:r.capability as string})});
}
/** Only the OS storage boundary sees secrets. No status/diagnostic snapshot of
 * this journal is exposed. Failed persistence always prevents admission. */
export class OrderedRecoveryJournal {
  private readonly serial=new Map<string,Promise<unknown>>();
  private readonly beginning=new Map<string,Promise<RecoveryIntent>>();
  constructor(private readonly storage:Storage){}
  private transaction<T>(scope:string,work:()=>Promise<T>):Promise<T>{
    if(!hex(scope,64))return Promise.reject(Error('ordered.recovery_scope'));
    const task=(this.serial.get(scope)??Promise.resolve()).catch(()=>undefined).then(work);
    this.serial.set(scope,task);void task.finally(()=>{if(this.serial.get(scope)===task)this.serial.delete(scope);}).catch(()=>undefined);
    return task;
  }
  private async read(scope:string):Promise<RecordV1>{
    let raw:string|null;try{raw=await this.storage.read(scope);}catch{throw Error('ordered.recovery_storage');}
    if(raw===null)return {version:1,current:null,pending:null};
    let value:unknown;try{if(raw.length>4096)throw Error();value=JSON.parse(raw);}catch{throw Error('ordered.recovery_journal');}
    fields(value,['version','current','pending']);if(value.version!==1)throw Error('ordered.recovery_journal');
    const current=value.current===null?null:custody(value.current),pending=value.pending===null?null:intent(value.pending);
    if(pending?.kind==='recover'&&(!current||current.streamId!==pending.recovery.previousStreamId
      ||current.capability!==pending.recovery.previousCapability))throw Error('ordered.recovery_journal');
    if(pending?.kind==='open'&&current)throw Error('ordered.recovery_journal');
    return {version:1,current,pending};
  }
  private async write(scope:string,value:RecordV1){
    try{await this.storage.write(scope,JSON.stringify(value));}catch{throw Error('ordered.recovery_storage');}
  }
  begin(scope:string,authentication:Auth):Promise<RecoveryIntent>{
    const previous=this.beginning.get(scope);if(previous)return previous;
    const task=this.transaction(scope,async()=>{
      const record=await this.read(scope);if(record.pending)return record.pending;
      const streamId=await this.storage.random(16),capability=await this.storage.random(32),
        owner=auth({client_key:authentication.client_key,connection_epoch:authentication.connection_epoch});
      const next=intent(record.current?{kind:'recover',streamId,auth:owner,recovery:{version:1,
        operationId:await this.storage.random(16),previousStreamId:record.current.streamId,
        previousCapability:record.current.capability,capability}}:{kind:'open',streamId,capability,auth:owner});
      await this.write(scope,{...record,pending:next});return next;
    });
    this.beginning.set(scope,task);void task.finally(()=>{if(this.beginning.get(scope)===task)this.beginning.delete(scope);}).catch(()=>undefined);
    return task;
  }
  async prepare(scope:string,authentication:Auth,
    send:(intent:RecoveryIntent,authentication:Auth)=>Promise<unknown>,current:()=>boolean):Promise<RecoveryIntent>{
    const unresolved=await this.transaction(scope,async()=>Boolean((await this.read(scope)).pending));
    const pending=await this.begin(scope,authentication);
    const check=()=>{if(!current())throw Error('ordered.recovery_owner');};check();
    if(!unresolved&&pending.auth.client_key===authentication.client_key&&pending.auth.connection_epoch===authentication.connection_epoch)return pending;
    // A prior process may have lost admission's reply. Settle that exact
    // operation first; fresh credentials cannot silently own its running player.
    let result:unknown;
    try{result=await send(pending,pending.auth);}
    catch(error){
      check();if((error as Error)?.message!=='phone_reply_authentication')throw error;
      if(pending.kind==='open'){
        // We cannot prove whether the old open arrived. Preserve its capability
        // and ask Desktop to prove exact predecessor ownership via recovery.
        // Unknown Desktop state is a precise failure, never a force-open.
        await this.transaction(scope,async()=>{
          const record=await this.read(scope);
          if(JSON.stringify(record.pending)!==JSON.stringify(pending))throw Error('ordered.recovery_stale_confirmation');
          await this.write(scope,{version:1,current:{streamId:pending.streamId,capability:pending.capability},pending:null});
        });
        check();return this.begin(scope,authentication);
      }
      result=await send(pending,authentication);
    }
    // Persist exact remote evidence even if the UI owner ended in flight.
    // This grants no local playback; the owner check still gates the successor.
    await this.confirm(scope,pending,result);check();
    return this.begin(scope,authentication);
  }
  confirm(scope:string,expected:RecoveryIntent,result:unknown):Promise<void>{
    return this.transaction(scope,async()=>{
      const next=intent(expected),record=await this.read(scope);
      if(JSON.stringify(record.pending)!==JSON.stringify(next))throw Error('ordered.recovery_stale_confirmation');
      const state=(result as {state?:unknown}|null)?.state;
      const wanted=next.kind==='open'?{version:1,streamId:next.streamId,generation:0}
        :{version:1,state:state==='closed'?'closed':'recovered',streamId:next.streamId,generation:0,operationId:next.recovery.operationId};
      if(!result||typeof result!=='object'||Object.keys(result).length!==Object.keys(wanted).length
        ||Object.entries(wanted).some(([k,v])=>(result as Record<string,unknown>)[k]!==v))throw Error('ordered.recovery_response');
      await this.write(scope,{version:1,current:{streamId:next.streamId,
        capability:next.kind==='open'?next.capability:next.recovery.capability},pending:null});
    });
  }
}
