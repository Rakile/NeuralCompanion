import {policy,validatePolicy} from './policy';
import type {Policy} from './policy';
import {policyContract} from './policyData';
import {DiagnosticEmitter} from './emitter';
import type {DiagnosticEventV1} from './contract';
export type PolicyNative={ncDiagnosticConfigure?:(p:Policy)=>unknown};
export function createPolicyControl(native:PolicyNative|null,sink:(row:DiagnosticEventV1)=>unknown){
  const emitter=new DiagnosticEmitter({component:'phone.js',build_id:null,build_unavailable_reason:'not_available',
    clock_id:'policy-phone',enqueue:sink,emergency:sink});
  let delivered='',jsRevision='',lastNotice='';
  function notice(status:'applied'|'rejected'|'unavailable'|'mismatch',reason?:string){
    const current=policy.snapshot(),key=JSON.stringify([status,reason,current.revision]);
    if(lastNotice===key)return;
    const id=emitter.emit({event_name:'diagnostics.policy',level:status==='applied'?'info':'warning',trace_id:'diagnostics-policy',
      operation_id:'policy-'+current.revision,parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',links:[],context:{},
      data:{site:'diagnostics.policy',status,revision:current.revision,
        effective:Object.fromEntries(policyContract.categories.map(c=>[c,current.categories[c]??current.default_level])),...(reason?{reason}:{})}});
    if(id)lastNotice=key;
  }
  return {
    notice,
    async apply(raw:unknown):Promise<void>{
      let selected:Policy;
      try{selected=validatePolicy(raw);policy.applyPolicy(selected);}catch{notice('rejected','invalid_policy');return;}
      if(delivered===selected.revision){notice('applied');return;}
      if(jsRevision!==selected.revision){notice('applied');jsRevision=selected.revision;}
      if(!native?.ncDiagnosticConfigure){notice('unavailable','native_unavailable');return;}
      try{
        const response=await native.ncDiagnosticConfigure(selected) as {status?:string;policy?:unknown};
        const actual=validatePolicy(response?.policy);
        if(response.status!=='applied'){notice('rejected','native_rejected');return;}
        if(actual.revision!==selected.revision||actual.default_level!==selected.default_level||
          policyContract.categories.some(c=>actual.categories[c]!==selected.categories[c])){notice('mismatch','revision_mismatch');return;}
        delivered=selected.revision;
        notice('applied');
      }catch{notice('unavailable','native_rejected');}
    }
  };
}
