import type { PhoneDebugLevel } from './phoneDebugTypes.ts';

type Recorder = (level: PhoneDebugLevel, event: string, details?: unknown) => Promise<void>;
export type PhoneDebugUploadClient = { uploadDebugPayload: (payload: Record<string, unknown>) => Promise<{ result?: { accepted?: boolean; events_written?: number } }> };
type Uploader = (client: PhoneDebugUploadClient, reason?: string, force?: boolean) => Promise<number>;

let recorder: Recorder = async () => undefined;
let uploader: Uploader = async () => 0;

export function configurePhoneDebug(recordHandler: Recorder, uploadHandler: Uploader): void {
  recorder = recordHandler;
  uploader = uploadHandler;
}

export function recordPhoneDebug(level: PhoneDebugLevel, event: string, details: unknown = {}): Promise<void> {
  return recorder(level, event, details);
}

export function uploadPhoneDebug(client: PhoneDebugUploadClient, reason = 'automatic', force = false): Promise<number> {
  return uploader(client, reason, force);
}
