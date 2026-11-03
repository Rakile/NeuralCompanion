/** Allowlisted relay transitions. The adapter observes but never owns recovery. */
import {DiagnosticEmitter} from '../diagnostics/emitter';
import {enqueueDiagnostic, emergencyDiagnostic} from '../diagnostics/bridgeSink';

type State = Record<string, unknown>;
export type RelayTransitionFields = {
  sessionId: string; trigger: string; initiator: string;
  eventRole: 'initiating' | 'cleanup' | 'retry'; state: State; failure?: boolean;
};

const id = /^[A-Za-z0-9_.:/-]{1,128}$/;
const triggers = new Set(['socket_closed','signaling_error','peer_disconnected','peer_failed',
  'data_channel_closed','authorization_expired','authorization_rejected','explicit_cleanup',
  'reconnect_scheduled','peer_recovered','recovery_timeout','desktop_changed',
  'peer_connecting','peer_connected','ice_state_changed','candidate_selected']);
const initiators = new Set(['signaling','peer','data_channel','authorization','application','timer','ice']);
const peerStates = new Set(['none','new','connecting','connected','disconnected','failed','closed','unknown']);
const iceStates = new Set([...peerStates,'checking','completed']);
const channelStates = new Set(['none','connecting','open','closing','closed','unknown']);
const candidateTypes = new Set(['host','srflx','prflx','relay','unknown']);
const protocols = new Set(['udp','tcp','unknown']);
const label = (value: unknown, allowed: Set<string>): string =>
  typeof value === 'string' && allowed.has(value) ? value : 'unknown';
const count = (value: unknown, limit: number): number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? Math.min(value,limit) : 0;

export function buildRelayTransition(fields: Pick<RelayTransitionFields,'trigger'|'initiator'|'eventRole'|'state'>): Record<string, unknown> {
  const state = fields.state || {};
  const remaining = state.authorization_remaining_ms;
  const cause = state.cause_event_id;
  return {
    site:'relay.transition',
    trigger:triggers.has(fields.trigger) ? fields.trigger : 'signaling_error',
    initiator:initiators.has(fields.initiator) ? fields.initiator : 'application',
    event_role:fields.eventRole,
    peer_state:label(state.peer_state,peerStates),
    ice_state:label(state.ice_state,iceStates),
    channel_state:label(state.channel_state,channelStates),
    signaling_state:label(state.signaling_state,channelStates),
    authorization_valid:state.authorization_valid === true,
    authorization_remaining_ms:typeof remaining === 'number' && Number.isSafeInteger(remaining) && remaining >= 0
      ? remaining : null,
    pending_commands:count(state.pending_commands,10000),
    selected_candidate_type:label(state.selected_candidate_type,candidateTypes),
    candidate_protocol:label(state.candidate_protocol,protocols),
    ...(typeof cause === 'string' && id.test(cause) ? {cause_event_id:cause} : {}),
  };
}

const emitter = new DiagnosticEmitter({component:'phone.js',build_id:null,
  build_unavailable_reason:'not_available',clock_id:'phone-js-monotonic',
  enqueue:enqueueDiagnostic,emergency:emergencyDiagnostic});

export function emitRelayTransition(fields: RelayTransitionFields): string | null {
  if (!id.test(fields.sessionId)) return null;
  try {
    const data = buildRelayTransition(fields);
    const cause = data.cause_event_id;
    return emitter.emit({level:fields.failure ? 'warning' : 'info',event_name:'relay.transition',
      trace_id:fields.sessionId,operation_id:`relay-${Date.now()}-${Math.random().toString(36).slice(2)}`,
      parent_operation_id:null,phase:'snapshot',outcome:'observed',basis:'observed',
      links:typeof cause === 'string' && fields.eventRole === 'cleanup'
        ? [{relation:'cleanup_of',event_id:cause,operation_id:null}] : [],
      context:{session_id:fields.sessionId},data});
  } catch { return null; /* Diagnostics must not alter connection decisions. */ }
}
