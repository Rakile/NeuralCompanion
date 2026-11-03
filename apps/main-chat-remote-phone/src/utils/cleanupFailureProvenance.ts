/** Failure-only provenance for EXISTING error records. No emitter, polling,
 * exception mutation, retry or successful-path snapshot. Weak keys cannot keep
 * discarded errors/sessions alive; values contain only fixed operation labels.
 */
const operations=new Set(['capture.cancel','capture.manual.cancel','capture.live.cancel',
  'playback.close','output.retire','output.state','output.confirmation']);
const provenance=new WeakMap<object,string[]>();

export function noteCleanupFailure(error:unknown,operation:string):unknown {
  try{
    if(!operations.has(operation)||error===null||typeof error!=='object'&&typeof error!=='function')return error;
    const prior=provenance.get(error)??[];
    if(!prior.includes(operation)&&prior.length<8)provenance.set(error,[...prior,operation]);
  }catch{ /* Diagnostics must preserve the original failure. */ }
  return error;
}

export function cleanupFailureOperations(error:unknown):string[] {
  try{
    return error!==null&&(typeof error==='object'||typeof error==='function')
      ?[...(provenance.get(error)??[])]:[];
  }catch{return [];}
}

/** Catch synchronous throws only; return the exact original value/promise.
 * Promise rejections are annotated at the existing allSettled/catch boundary.
 */
export function invokeCleanup<T>(operation:string,work:()=>T):T {
  try{return work();}catch(error){throw noteCleanupFailure(error,operation);}
}
