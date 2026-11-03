import schema from './eventSchema';
import {Buffer} from 'buffer';
export type ValidationIssue={path:string;rule:string};
export type DiagnosticEventV1={schema_version:1;event_id:string;producer_id:string;sequence:number;
  component:string;build_id:string|null;build_unavailable_reason:string|null;wall_time_utc:string;
  monotonic_ms:number;clock_id:string;level:'debug'|'info'|'warning'|'error';event_name:string;
  trace_id:string;operation_id:string;parent_operation_id:string|null;phase:string;outcome:string;
  basis:'observed'|'derived'|'hypothesis';links:{relation:string;event_id:string|null;operation_id:string|null}[];
  context:Record<string,string|number>;data:Record<string,unknown>};
// This interpreter supports only keywords used by the pinned v1 contract.
function walk(value:any,s:any,path:string,issues:ValidationIssue[]):void{
  const bad=(rule:string)=>{if(issues.length<32)issues.push({path,rule});};
  if(s.anyOf&&!s.anyOf.some((option:any)=>{const next:ValidationIssue[]=[];walk(value,option,path,next);return !next.length;})){bad('anyOf');return;}
  const matches:Record<string,boolean>={object:value!==null&&typeof value==='object'&&!Array.isArray(value),
    array:Array.isArray(value),string:typeof value==='string',null:value===null,boolean:typeof value==='boolean',
    number:typeof value==='number'&&Number.isFinite(value),integer:typeof value==='number'&&Number.isInteger(value)};
  if(s.type&&!matches[s.type]){bad('type');return;}
  if('const'in s&&value!==s.const)bad('const');
  if(s.enum&&!s.enum.includes(value))bad('enum');
  if(typeof value==='number'&&(value<(s.minimum??-Infinity)||value>(s.maximum??Infinity)))bad('range');
  if(typeof value==='string'){
    const length=Array.from(value).length;
    if(length<(s.minLength??0)||length>(s.maxLength??100000))bad('length');
    if(s.pattern&&!new RegExp(s.pattern).test(value))bad('pattern');
    if(s.format==='date-time'){
      const date=new Date(value);if(!Number.isFinite(date.getTime())||date.toISOString()!==value)bad('format');
    }
  }
  if(matches.object){
    for(const key of s.required??[])if(!Object.prototype.hasOwnProperty.call(value,key))bad('required.'+key);
    for(const [key,child]of Object.entries(value)){
      if(Object.prototype.hasOwnProperty.call(s.properties??{},key))walk(child,s.properties[key],path+'.'+key,issues);
      else if(s.additionalProperties===false)bad('unknown_field');
    }
  }
  if(Array.isArray(value)){
    if(value.length<(s.minItems??0)||value.length>(s.maxItems??100000))bad('items');
    if(s.items)value.forEach((child,i)=>walk(child,s.items,path+'['+i+']',issues));
  }
  for(const constraint of s.allOf??[])walk(value,constraint,path,issues);
  if(s.if){const next:ValidationIssue[]=[];walk(value,s.if,path,next);if(!next.length)walk(value,s.then,path,issues);}
}
export function validateDiagnosticEvent(value:unknown):ValidationIssue[]{
  try{
    const seen=new Set<object>();
    function inspect(node:any,depth=0):void{
      if(depth>12)throw Error();
      if(typeof node==='number'&&!Number.isFinite(node))throw Error();
      if(typeof node==='string'&&node.startsWith('/'))throw Error();
      if(typeof node==='string'&&(/Bearer\s|(?:password|token|secret|authorization|code|api_key)\s*[=:]|[A-Za-z]:[\\/]|file:\/\//i.test(node)||/[\u0000-\u001f]/.test(node)))throw Error();
      if(node===null||['string','number','boolean'].includes(typeof node))return;
      if(typeof node!=='object'||seen.has(node))throw Error();seen.add(node);
      const array=Array.isArray(node),prototype=Object.getPrototypeOf(node);
      const constructor=prototype&&Object.getOwnPropertyDescriptor(prototype,'constructor')?.value;
      // Compare native constructor text to allow plain JSON from another realm.
      if(!(prototype===null&&!array)&&Function.prototype.toString.call(constructor)!==Function.prototype.toString.call(array?Array:Object))throw Error();
      if('toJSON'in node)throw Error();
      // Never run getters or custom JSON hooks on the accepted-payload path.
      for(const key of Reflect.ownKeys(node)){
        if(array&&key==='length')continue;
        const property=Object.getOwnPropertyDescriptor(node,key)!;
        if(typeof key!=='string'||key==='toJSON'||!property.enumerable||!('value'in property))throw Error();
        inspect(property.value,depth+1);
      }
      seen.delete(node);
    }
    inspect(value);
    if(Buffer.byteLength(JSON.stringify(value),'utf8')>16384)return[{path:'$',rule:'size'}];
    const issues:ValidationIssue[]=[];walk(value,schema,'$',issues);
    if(!issues.length){const e=value as DiagnosticEventV1;
      if(e.event_id!==e.producer_id+':'+e.sequence)issues.push({path:'$.event_id',rule:'identity'});
      if(e.phase==='wait'&&Number(e.data.deadline_ms)<Number(e.data.wait_started_ms))issues.push({path:'$.data.deadline_ms',rule:'deadline'});
      if(e.links.some(l=>l.event_id===null&&l.operation_id===null))issues.push({path:'$.links',rule:'target'});
    }return issues;
  }catch{return[{path:'$',rule:'unsafe_or_non_json'}];}
}
