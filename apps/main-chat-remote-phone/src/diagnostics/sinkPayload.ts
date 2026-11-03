import { validateDiagnosticEvent } from './contract';

export function prepareContractRecord(details: unknown): {event:string; details:unknown} {
  const event = details && typeof details === 'object' ? (details as {contract?:unknown}).contract : undefined;
  const issues = validateDiagnosticEvent(event);
  if (issues.length) return {event:'diagnostics.validation_failed',details:{site:'diagnostic_sink',issues}};
  return {event:'diagnostic_event',details:{contract:JSON.parse(JSON.stringify(event))}};
}
