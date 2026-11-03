import { recordPhoneDebug } from '../utils/phoneDebug';
import type { DiagnosticEventV1 } from './contract';

/** Acceptance into the existing bounded backlog is not a durable acknowledgement. */
export async function recordDiagnosticEvent(event: DiagnosticEventV1): Promise<void> {
  // Legacy wrapper has no debug level; the envelope retains the exact level.
  await recordPhoneDebug(event.level === 'debug' ? 'info' : event.level, 'diagnostic_event', {contract:event}, true);
}
