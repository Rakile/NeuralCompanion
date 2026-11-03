import {validateDiagnosticEvent} from './contract';
import type {DiagnosticEventV1} from './contract';

export type NativeDiagnostics={ncDiagnosticVersion():number;ncDiagnosticPeek(limit:number):unknown;
  ncDiagnosticAck(ids:string[]):unknown};
type Schedule=(tick:()=>Promise<void>)=>()=>void;
const schedule:Schedule=tick=>{const timer=setInterval(()=>{void tick();},250);return()=>clearInterval(timer);};

/** Ack transfers custody into JS backlog, never claims disk durability. */
export function startNativeDiagnostics(native:NativeDiagnostics|null,sink:(event:DiagnosticEventV1)=>Promise<void>,
  emergency:(reason:string)=>void,scheduler:Schedule=schedule):()=>void{
  let stopped=false,busy=false;
  const report=(reason:string)=>{try{emergency(reason);}catch{}};
  try{if(!native||native.ncDiagnosticVersion()!==1){report('native_unavailable');return()=>{};}}
  catch{report('native_unavailable');return()=>{};}
  const tick=async()=>{
    if(stopped||busy)return;busy=true;
    const accepted:string[]=[];
    try{
      const rows=await native.ncDiagnosticPeek(64);
      if(stopped)return;
      if(!Array.isArray(rows)||rows.length>64){report('invalid_batch');return;}
      for(const row of rows){
        if(stopped)return;
        if(validateDiagnosticEvent(row).length||row.component!=='phone.native'){report('validation_failed');return;}
        const eventId=row.event_id;
        try{await sink(row as DiagnosticEventV1);}catch{report('sink_failed');return;}
        if(stopped)return;
        accepted.push(eventId);
      }
    }catch{report('native_transport_failed');}
    finally{
      // Transfer only accepted custody, including a prefix before a sink error.
      // One bounded ACK avoids a synchronous native backlog scan per record.
      try{if(!stopped&&accepted.length)await native.ncDiagnosticAck(accepted);}
      catch{report('native_transport_failed');}
      finally{busy=false;}
    }
  };
  const cancel=scheduler(tick);
  return()=>{stopped=true;cancel();};
}
