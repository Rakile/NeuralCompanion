import type {DiagnosticEventV1} from './contract';
import {recordPhoneDebug} from '../utils/phoneDebugBridge';

export const enqueueDiagnostic=(event:DiagnosticEventV1)=>recordPhoneDebug(
  event.level==='debug'?'info':event.level,'diagnostic_event',{contract:event},true);

/** Independent last resort: never retry a failed backlog through itself. */
export function emergencyDiagnostic(event:DiagnosticEventV1):void{
  console.error(JSON.stringify({event:'diagnostic_event',details:{contract:event}}));
}
