import type { PhoneDebugLevel } from './phoneDebugTypes';

type Recorder = (level: PhoneDebugLevel, event: string, details?: unknown) => Promise<void>;
type Uploader = (baseUrl: string, pairingCode: string, reason?: string, force?: boolean) => Promise<number>;

let recorder: Recorder = async () => undefined;
let uploader: Uploader = async () => 0;

export function configurePhoneDebug(recordHandler: Recorder, uploadHandler: Uploader): void {
  recorder = recordHandler;
  uploader = uploadHandler;
}

export function recordPhoneDebug(level: PhoneDebugLevel, event: string, details: unknown = {}): Promise<void> {
  return recorder(level, event, details);
}

export function uploadPhoneDebug(baseUrl: string, pairingCode: string, reason = 'automatic', force = false): Promise<number> {
  return uploader(baseUrl, pairingCode, reason, force);
}
