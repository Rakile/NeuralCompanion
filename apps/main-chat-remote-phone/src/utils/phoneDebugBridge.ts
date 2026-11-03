import type { PhoneDebugLevel } from './phoneDebugTypes.ts';
import {siteEnabled} from '../diagnostics/policy';

type Recorder = (level: PhoneDebugLevel, event: string, details?: unknown, requireAcceptance?:boolean) => Promise<void>;
export type PhoneDebugUploadClient = { uploadDebugPayload: (payload: Record<string, unknown>) => Promise<{ result?: { accepted?: boolean; events_written?: number; desktop_log_path?: string } }> };
type Uploader = (client: PhoneDebugUploadClient, reason?: string, force?: boolean) => Promise<number>;

let recorder: Recorder | undefined;
let uploader: Uploader = async () => 0;

export function configurePhoneDebug(recordHandler: Recorder, uploadHandler: Uploader): void {
  recorder = recordHandler;
  uploader = uploadHandler;
}

export function recordPhoneDebug(level: PhoneDebugLevel, event: string, details: unknown = {}, requireAcceptance=false): Promise<void> {
  if(!requireAcceptance&&event!=='diagnostic_event'&&!siteEnabled(event,level,'observed',details&&typeof details==='object'?details as Record<string,unknown>:{}))return Promise.resolve();
  if(!recorder)return requireAcceptance?Promise.reject(Error('Diagnostic recorder unavailable')):Promise.resolve();
  return recorder(level, event, details, requireAcceptance);
}

export function recordPhoneDebugLazy(level:PhoneDebugLevel,event:string,build:()=>unknown):Promise<void>{
  if(!siteEnabled(event,level))return Promise.resolve();
  return recordPhoneDebug(level,event,build());
}

export function uploadPhoneDebug(client: PhoneDebugUploadClient, reason = 'automatic', force = false): Promise<number> {
  return uploader(client, reason, force);
}
