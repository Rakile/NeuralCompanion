import {recordPhoneDebug} from './phoneDebugBridge';

// Deliberate allowlist: never spread auth, request bodies, errors, SDP or stats.
const strings = new Set(['request_id','reply_id','previous_id','operation','route','method','outcome',
  'phase','state','ice_state','candidate_type','protocol','reason','session_id','chunk_id','network_type']);
const numbers = new Set(['elapsed_ms','status','pending','buffered_bytes','received_bytes','sequence',
  'position_seconds','rtt_ms','replies','retired','done','foreground','connected','started',
  'attempt','delay_ms','generation','wanted','online','preserved','socket_state','packets_received',
  'packets_lost','jitter_ms','sent_bytes','loaded','playing','paused','queued','retained','automatic',
  'status_age_ms','reachable','duration_ms','last_receive_age_ms','last_send_age_ms','missed',
  'timer_delay_ms','power_save','device_idle','interactive','native_error_code','play_when_ready','focus_interrupted']);
type Fields = Record<string, unknown>;
export function diagnosticRoute(path: string): string {
  const route = path.split('?')[0] ?? '';
  return /^\/(health|api\/(state|send|debug|control|continuous\/(status|speech|claim|command)|phone-reply\/(status|action|presentation|session)|buffered\/(audio|release|negotiate)))$/.test(route)
    ? route : 'media_or_other';
}
export class ConnectionTrace {
  private recent: Fields[] = [];
  private lastSnapshot = -Infinity;
  private transitions: Fields[] = [];
  private followupAt = 0;
  private session = '';
  constructor(private emit = (event: string, details: Fields) => {
    void recordPhoneDebug('info', event, details).catch(() => undefined);
  }) {}
  event(event: string, values: Fields = {}, failure = false): void {
    try {
      const fields: Fields = {};
      for (const [key, value] of Object.entries(values)) {
        if (strings.has(key) && typeof value === 'string' && /^[A-Za-z0-9_/-]{1,128}$/.test(value)) fields[key] = value;
        if (numbers.has(key) && typeof value === 'number' && Number.isFinite(value) && value >= 0) fields[key] = value;
      }
      if (typeof fields.session_id === 'string' && fields.session_id) this.session = fields.session_id;
      if (!fields.session_id && this.session) fields.session_id = this.session;
      const now = Date.now();
      const row = {event, at_ms:now, ...fields};
      this.recent.push(row); if (this.recent.length > 32) this.recent.shift();
      if (event !== 'peer_request') {
        this.transitions.push(row); if (this.transitions.length > 24) this.transitions.shift();
      }
      this.emit(event, fields);
      if (this.followupAt && now >= this.followupAt) {
        this.followupAt = 0;
        this.emit('connection_followup_snapshot', {recent:[...this.recent], transitions:[...this.transitions]});
      }
      if (failure && now-this.lastSnapshot >= 10000) {
        this.lastSnapshot = now;
        this.followupAt = now + 10000;
        this.emit('connection_failure_snapshot', {recent:[...this.recent], transitions:[...this.transitions]});
      }
    } catch { /* No diagnostic failure may escape into playback. */ }
  }
}
export const connectionTrace = new ConnectionTrace();
