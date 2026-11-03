import { NativeModules } from 'react-native';
import { setBackgroundInterval as setInterval, setBackgroundTimeout as setTimeout, clearBackgroundTimer as clearInterval, clearBackgroundTimer as clearTimeout } from '../utils/backgroundClock';
import {connectionTrace} from '../utils/connectionTrace';
import {rtcHealthFields} from '../utils/rtcHealth';
import {emitRelayTransition} from './diagnostics';
import { RelayAuth, RelayError, RELAY_SIGNAL, Protocol } from './auth';
import { PeerTransport } from './peer';
import { AVCompatibilityError } from './av';
import type { SignalingMessage } from '@nc-relay/protocol';

type Rtc = typeof import('react-native-webrtc');
const PEER_RECOVERY_MS = 20000;
const AUTH_FAILURES = ['NOT_AUTHENTICATED', 'TOKEN_REUSED', 'LOGIN_REQUIRED', 'INVALID_TOKEN', 'UNAUTHORIZED', 'FORBIDDEN', 'DESKTOP_MISMATCH', 'DESKTOP_REPLACEMENT_REQUIRED'];
function clearPeerMedia(peer: PeerTransport) {
  return (require('./media') as typeof import('./media')).clearPeerMedia(peer);
}
export class RelaySession {
  peer: PeerTransport | null = null; online = false; status = 'disconnected'; error = '';
  onChange: () => void = () => undefined;
  private socket: WebSocket | null = null; private pc: InstanceType<Rtc['RTCPeerConnection']> | null = null;
  private socketToken = '';
  private sid = ''; private generation = 0; private wanted = false; private offering = false; private attempts = 0;
  private retry: ReturnType<typeof setTimeout> | null = null; private refresh: ReturnType<typeof setInterval> | null = null;
  private negotiation: ReturnType<typeof setTimeout> | null = null;
  private authorizationTimer: ReturnType<typeof setTimeout> | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private retryNotBefore = 0;
  private native: Rtc | null = null; private incoming: unknown[] = []; private outgoing: unknown[] = []; private offered = false;
  constructor(readonly auth: RelayAuth) {}
  private desktopId = '';
  private socketCloseOrigin: 'signaling' | 'peer' | 'data_channel' | 'authorization' | 'application' | null = null;
  private causeEventId = '';
  private selectedCandidateType = 'unknown';
  private selectedCandidateProtocol = 'unknown';
  private establishedPeer: PeerTransport | null = null;
  private peerRecoveryTimer: ReturnType<typeof setTimeout> | null = null;
  private peerRecoveryDeadline = 0;
  get wantsConnection(): boolean { return this.wanted; }
  get orderedRecoveryProfile(): string {
    return this.auth.account && this.desktopId
      ? JSON.stringify(['relay', RELAY_SIGNAL, this.auth.account.id, this.desktopId]) : '';
  }
  get commandReady(): boolean { return this.status === 'connected' && this.healthyPeer(); }
  get mediaContinuity(): boolean { return this.recoverablePeer(); }
  // Receipt recovery survives transport replacement, but never account/login or
  // desktop replacement. No capability is sent until a new peer is connected.
  get recoveryKey(): string {
    return this.auth.account && this.desktopId
      ? JSON.stringify([this.auth.account.id, this.auth.credentialGeneration, this.desktopId]) : '';
  }
  private trace(event: string, values: Record<string, unknown> = {}, failure = false) {
    connectionTrace.event(event, {session_id:this.sid, generation:this.generation, state:this.status,
      wanted:Number(this.wanted), online:Number(this.online), socket_state:this.socket?.readyState, ...values}, failure);
  }
  private transition(trigger: string, initiator: 'signaling' | 'peer' | 'data_channel' | 'authorization' | 'application' | 'timer' | 'ice',
    eventRole: 'initiating' | 'cleanup' | 'retry', failure = false): void {
    const socketState = this.socket?.readyState;
    const remaining = this.auth.expiresAt - Date.now();
    const eventId = emitRelayTransition({sessionId:this.sid,trigger,initiator,eventRole,failure,state:{
      peer_state:this.pc?.connectionState ?? 'none',ice_state:this.pc?.iceConnectionState ?? 'none',
      channel_state:this.peer?.channelState ?? (this.pc ? 'connecting' : 'none'),
      signaling_state:socketState === 0 ? 'connecting' : socketState === 1 ? 'open'
        : socketState === 2 ? 'closing' : socketState === 3 ? 'closed' : 'none',
      authorization_valid:Boolean(this.auth.token && remaining > 0),
      authorization_remaining_ms:this.auth.token ? Math.max(0,Math.trunc(remaining)) : null,
      pending_commands:this.peer?.pendingCount ?? 0,
      selected_candidate_type:this.selectedCandidateType,
      candidate_protocol:this.selectedCandidateProtocol,
      ...(eventRole === 'cleanup' && this.causeEventId ? {cause_event_id:this.causeEventId} : {}),
    }});
    if (eventRole === 'initiating' && eventId) this.causeEventId = eventId;
  }
  private update(status?: string, error?: string) {
    if (status && status !== this.status) this.trace('relay_status', {state:status});
    if (status) this.status = status; if (error !== undefined) this.error = error; this.onChange();
  }
  private watchHealth(pc: InstanceType<Rtc['RTCPeerConnection']>) {
    if (this.healthTimer) clearInterval(this.healthTimer);
    let busy = false;
    const sample = async () => {
      if (busy || this.pc !== pc) return;
      busy = true;
      void this.peer?.sampleHeartbeat();
      try {
        const report = await pc.getStats();
        if (this.pc === pc) this.trace('rtc_health', rtcHealthFields(report));
      } catch { if (this.pc === pc) this.trace('rtc_health_unavailable'); }
      finally { busy = false; }
    };
    this.healthTimer = setInterval(() => { void sample(); }, 15000);
    void sample();
  }
  private healthyPeer(): boolean {
    return Boolean(this.peer && !this.peer.closed && this.pc?.connectionState === 'connected'
      && this.peer.channelState === 'open' && this.auth.token && this.auth.expiresAt > Date.now());
  }
  private recoverablePeer(): boolean {
    return Boolean(this.peerRecoveryTimer && this.peerRecoveryDeadline > Date.now()
      && this.peer && this.peer === this.establishedPeer && !this.peer.closed
      && this.peer.channelState === 'open' && this.pc?.connectionState === 'disconnected'
      && this.auth.token && this.auth.expiresAt > Date.now());
  }
  private clearPeerRecovery(): void {
    if (this.peerRecoveryTimer) clearTimeout(this.peerRecoveryTimer);
    this.peerRecoveryTimer = null; this.peerRecoveryDeadline = 0;
  }
  private beginPeerRecovery(pc: InstanceType<Rtc['RTCPeerConnection']>): void {
    if (this.peerRecoveryTimer || !this.wanted || !this.peer || this.peer !== this.establishedPeer
      || this.peer.closed || this.peer.channelState !== 'open') return;
    if (!this.auth.token || this.auth.expiresAt <= Date.now()) { this.peerFailed('authorization_expired'); return; }
    const peer = this.peer, epoch = this.generation;
    this.peerRecoveryDeadline = Date.now() + PEER_RECOVERY_MS;
    this.peerRecoveryTimer = setTimeout(() => {
      this.peerRecoveryTimer = null;
      if (!this.wanted || epoch !== this.generation || pc !== this.pc || peer !== this.peer) return;
      if (!this.auth.token || this.auth.expiresAt <= Date.now()) this.peerFailed('authorization_expired');
      else if (pc.connectionState === 'connected' && peer.channelState === 'open') {
        this.peerRecoveryDeadline = 0; this.update('connected', '');
        this.transition('peer_recovered','peer','retry');
      } else this.peerFailed('recovery_timeout');
    }, PEER_RECOVERY_MS);
    this.update('reconnecting', 'Peer connection interrupted. Waiting for it to recover.');
  }
  private watchAuthorization() {
    if (this.authorizationTimer) clearTimeout(this.authorizationTimer);
    if (!Number.isFinite(this.auth.expiresAt)) return;
    const epoch = this.generation;
    this.authorizationTimer = setTimeout(() => {
      this.authorizationTimer = null;
      if (!this.wanted || epoch !== this.generation) return;
      if (this.auth.token && this.auth.expiresAt > Date.now()) this.watchAuthorization();
      else {
        // Background suspension can delay both timers past access-token expiry.
        // End expired peer authority, but keep Connect intent and try the stored
        // single-use refresh through the normal serialized reconnect path.
        // Confirmed revocation/missing credentials still disconnect in open().
        this.peerFailed('authorization_expired');
      }
    }, Math.max(0, this.auth.expiresAt - Date.now()));
  }
  private peerFailed(reason = 'peer_closed') {
    const initiator = reason === 'authorization_expired' ? 'authorization'
      : reason === 'data_channel_closed' ? 'data_channel' : reason === 'recovery_timeout' ? 'application' : 'peer';
    const trigger = reason === 'authorization_expired' ? 'authorization_expired'
      : reason === 'data_channel_closed' ? 'data_channel_closed'
      : reason === 'recovery_timeout' ? 'recovery_timeout' : 'peer_failed';
    this.transition(trigger,initiator,'initiating',true);
    this.trace('relay_peer_failed', {reason}, true);
    this.closePeer(reason); this.update('reconnecting', 'Internet peer disconnected.');
    if (this.socket) { this.socketCloseOrigin = initiator; this.socket.close(); }
    else this.reconnect();
  }
  async connect(): Promise<void> {
    this.disconnect('connect_reset'); this.wanted = true;
    try {
      if (!NativeModules.WebRTCModule) throw new Error('Internet mode requires an updated native NC Remote build with WebRTC. LAN remains available.');
      this.native = require('react-native-webrtc') as Rtc;
      await this.open();
    } catch (error) { this.wanted = false; this.update('error', error instanceof Error ? error.message : 'Internet connection failed.'); throw error; }
  }
  private async open() {
    const epoch = this.generation;
    this.update(this.healthyPeer() ? 'connected' : this.recoverablePeer() ? 'reconnecting' : 'connecting', '');
    const token = await this.auth.access(); if (!this.wanted || epoch !== this.generation) return;
    this.watchAuthorization();
    const socket = new WebSocket(RELAY_SIGNAL, ['bearer', token]); this.socket = socket;
    this.socketToken = token;
    this.socketCloseOrigin = null;
    this.trace('relay_socket_opening');
    const current = () => epoch === this.generation && socket === this.socket;
    socket.onopen = () => { if (current()) this.trace('relay_socket_open'); };
    socket.onmessage = event => {
      if (!current()) return;
      const parsed = Protocol.parseSignalingMessage(String(event.data));
      if (!parsed.ok) { this.update('error', parsed.error.code); socket.close(1008); return; }
      void this.receive(parsed.message, epoch).catch(error => {
        if (!current()) return;
        this.trace('relay_negotiation_failed', {reason:error instanceof RelayError ? error.code : 'negotiation_error'}, true);
        if (error instanceof AVCompatibilityError) {
          this.disconnect('incompatible_media'); this.update('error', error.message); return;
        }
        if (error instanceof RelayError) {
          this.retryNotBefore = Date.now() + Math.max(error.status === 429 ? 60 : 0, error.retryAfter) * 1000;
          if (AUTH_FAILURES.includes(error.code)) this.wanted = false;
        }
        this.update('error', error instanceof RelayError ? error.code : 'WebRTC negotiation failed.');
        socket.close();
      });
    };
    socket.onerror = () => { if (current()) {
      const closeOrigin = this.socketCloseOrigin;
      this.transition('signaling_error',closeOrigin ?? 'signaling',closeOrigin ? 'cleanup' : 'initiating',true);
      if (!closeOrigin) this.socketCloseOrigin = 'signaling';
      this.trace('relay_socket_error', {}, true);
      this.update(this.healthyPeer() ? 'connected' : this.recoverablePeer() ? 'reconnecting' : 'error', 'Relay connection failed.');
    } };
    socket.onclose = event => {
      if (!current()) return;
      const closeOrigin = this.socketCloseOrigin;
      this.socketCloseOrigin = null;
      this.transition('socket_closed',closeOrigin ?? 'signaling',closeOrigin ? 'cleanup' : 'initiating',true);
      this.trace('relay_socket_closed', {status:event.code, preserved:Number(this.healthyPeer() || this.recoverablePeer())}, true);
      this.socket = null; this.socketToken = '';
      if ([1008, 1009, 4001, 4002].includes(event.code) || !this.wanted) {
        const reason = this.error || `Relay disconnected (${event.code}).`;
        this.disconnect('terminal_signaling_close'); this.update('disconnected', reason); return;
      }
      const active = this.healthyPeer();
      const preserved = this.wanted && (active || this.recoverablePeer());
      if (!preserved) this.closePeer('signaling_closed_without_healthy_peer');
      this.online = false;
      this.update(active ? 'connected' : this.wanted ? 'reconnecting' : 'disconnected',
        preserved ? 'Relay reconnecting; peer identity remains available.' : this.error || `Relay disconnected (${event.code}).`);
      this.reconnect();
    };
    if (!this.refresh) this.refresh = setInterval(() => {
      void this.auth.access().then(() => {
        if (epoch === this.generation && this.wanted) {
          this.watchAuthorization();
          // Signaling keeps its opening JWT even after HTTP authority rotates.
          // Reopen through the existing recovery path before that JWT expires.
          if (this.socket?.readyState === 1 && this.socketToken !== this.auth.token) {
            this.socketCloseOrigin = 'authorization';
            this.socket.close();
          }
        }
      }).catch(error => {
        if (epoch !== this.generation) return;
        this.trace('relay_refresh_failed', {reason:error instanceof RelayError ? error.code : 'refresh_failed'}, true);
        this.disconnect('refresh_failed'); this.update('error', error instanceof RelayError ? error.code : 'Sign in again.');
      });
    }, 60000);
  }
  private send(message: SignalingMessage) {
    const parsed = Protocol.parseSignalingMessage(JSON.stringify(message));
    if (!parsed.ok || this.socket?.readyState !== 1) throw new Error('Signaling unavailable.');
    this.socket.send(JSON.stringify(parsed.message));
  }
  private async receive(message: SignalingMessage, epoch: number) {
    if (message.type === 'hello') { if (message.role !== 'mobile') throw new Error('Unexpected role');
      this.update(this.healthyPeer() ? 'connected' : this.recoverablePeer() ? 'reconnecting' : 'waiting',
        this.healthyPeer() ? '' : this.recoverablePeer() ? 'Peer connection is recovering.' : 'Waiting for desktop presence.'); }
    else if (message.type === 'desktop-presence') {
      this.trace('relay_presence', {online:Number(message.online)});
      if (this.desktopId && this.desktopId !== message.desktopId) this.closePeer('desktop_changed');
      this.desktopId = message.desktopId;
      this.online = message.online; this.onChange();
      if (message.online && !this.pc && !this.offering) await this.offer(epoch);
      else if (!message.online && !this.peer) this.update('waiting', 'Your desktop is offline. Start NC and connect Internet mode there.');
    } else if (message.type === 'answer' && message.sessionId === this.sid && this.pc && !this.peer) {
      await this.pc.setRemoteDescription({ type: 'answer', sdp: message.sdp });
      for (const candidate of this.incoming.splice(0)) await this.pc.addIceCandidate(candidate as never);
    } else if (message.type === 'ice-candidate' && message.sessionId === this.sid && this.pc && !this.peer) {
      if (this.pc.remoteDescription) await this.pc.addIceCandidate(message.candidate as never);
      else if (this.incoming.length < 64) this.incoming.push(message.candidate);
    } else if (message.type === 'hangup' && message.sessionId === this.sid) { this.trace('relay_remote_hangup', {}, true); this.closePeer('desktop_hangup'); this.update('disconnected', 'Desktop ended the peer connection.'); this.socket?.close(); }
    else if (message.type === 'error') {
      this.trace('relay_protocol_error', {reason:message.code}, true);
      if (AUTH_FAILURES.includes(message.code)) { this.transition('authorization_rejected','authorization','initiating',true); this.disconnect('authorization_rejected'); this.update('error', message.code); return; }
      if (message.sessionId && message.sessionId !== this.sid) return;
      this.update('error', message.code);
      if (['SESSION_TAKEN_OVER', 'UNKNOWN_SESSION', 'PEER_OFFLINE'].includes(message.code)) { this.closePeer(message.code); this.socket?.close(); }
    }
  }
  private async offer(epoch: number) {
    this.offering = true;
    const socket = this.socket;
    try {
      const ice = Protocol.IceServersResponseSchema.parse(await this.auth.request('/v1/ice-servers'));
      if (epoch !== this.generation || !this.wanted || socket !== this.socket) return;
      const pc = new this.native!.RTCPeerConnection({ iceServers: ice.iceServers }); this.pc = pc;
      const random = require('expo-crypto') as typeof import('expo-crypto');
      this.sid = random.randomUUID(); this.incoming = []; this.outgoing = []; this.offered = false;
      this.causeEventId = ''; this.selectedCandidateType = 'unknown'; this.selectedCandidateProtocol = 'unknown';
      this.trace('rtc_offer_started');
      const channel = pc.createDataChannel('nc-rpc-v1', { ordered: true });
      channel.onopen = () => {
        if (epoch !== this.generation || pc !== this.pc) { channel.close(); return; }
        this.trace('rtc_channel_open');
        this.watchHealth(pc);
        this.peer = new PeerTransport(this.sid, channel as never, null,
          this.auth.account && this.desktopId ? JSON.stringify([this.auth.account.id, this.desktopId]) : '',
          () => pc === this.pc && (this.establishedPeer !== this.peer || pc.connectionState === 'connected')
            && Boolean(this.auth.token && this.auth.expiresAt > Date.now()) && channel.readyState === 'open');
        const connectedPeer = this.peer;
        this.peer.onClose = () => { void clearPeerMedia(connectedPeer);
          if (epoch === this.generation && this.peer === connectedPeer) {
            if (connectedPeer.mediaError instanceof AVCompatibilityError) {
              const message = connectedPeer.mediaError.message;
              this.disconnect('incompatible_media'); this.update('error', message);
            } else this.peerFailed('data_channel_closed');
          } };
        void connectedPeer.negotiateBuffered().then(()=>{
          if(epoch!==this.generation||this.peer!==connectedPeer||connectedPeer.closed)return;
          if (this.negotiation) clearTimeout(this.negotiation); this.negotiation = null;
          this.attempts = 0; this.update('connected', '');
          this.establishedPeer = connectedPeer;
          this.transition('peer_connected','peer','retry');
          this.trace('relay_media_ready');
        }).catch(error=>{
          if(epoch!==this.generation||this.peer!==connectedPeer)return;
          connectedPeer.mediaError=error instanceof Error?error:new Error('Buffered negotiation failed.');
          connectedPeer.close(connectedPeer.mediaError, 'buffered_negotiation_failed');
        });
      };
      pc.onicecandidate = (event: { candidate?: { toJSON(): Record<string, unknown> } }) => {
        if (epoch !== this.generation || pc !== this.pc || socket !== this.socket || this.peer || !event.candidate) return;
        const candidate = event.candidate.toJSON();
        if (!this.offered) { if (this.outgoing.length < 64) this.outgoing.push(candidate); return; }
        try { this.send({ v: 1, type: 'ice-candidate', sessionId: this.sid, targetRole: 'desktop', candidate }); } catch { this.socket?.close(); }
      };
      pc.onconnectionstatechange = () => {
        if (epoch === this.generation && pc === this.pc) {
          this.trace('rtc_state', {state:pc.connectionState, ice_state:pc.iceConnectionState},
            ['failed', 'disconnected', 'closed'].includes(pc.connectionState));
          if (pc.connectionState === 'connected' && this.peer && (!this.auth.token || this.auth.expiresAt <= Date.now())) {
            this.peerFailed('authorization_expired'); return;
          }
          if (pc.connectionState === 'disconnected') {
            if (!this.peerRecoveryTimer) this.transition('peer_disconnected','peer','initiating',true);
            this.beginPeerRecovery(pc);
            if (pc !== this.pc) return;
          }
          if (pc.connectionState === 'connected' && this.peerRecoveryTimer && this.peer === this.establishedPeer
            && this.peer?.channelState === 'open') {
            this.clearPeerRecovery(); this.update('connected', '');
            this.transition('peer_recovered','peer','retry');
          }
          if (pc.connectionState === 'connected') void pc.getStats().then(report => {
            if (epoch !== this.generation || pc !== this.pc) return;
            report.forEach((stat: any) => {
              if (stat.type !== 'candidate-pair' || !(stat.selected || (stat.nominated && stat.state === 'succeeded'))) return;
              const local = report.get(stat.localCandidateId);
              const remote = report.get(stat.remoteCandidateId);
              this.selectedCandidateType = local?.candidateType === 'relay' || remote?.candidateType === 'relay'
                ? 'relay' : ['host','srflx','prflx'].includes(local?.candidateType) ? local.candidateType : 'unknown';
              this.selectedCandidateProtocol = ['udp','tcp'].includes(local?.protocol) ? local.protocol : 'unknown';
              this.transition('candidate_selected','ice','retry');
              connectionTrace.event('rtc_route', {candidate_type:local?.candidateType === 'relay' || remote?.candidateType === 'relay' ? 'relay' : local?.candidateType, protocol:local?.protocol,
                rtt_ms:Number(stat.currentRoundTripTime || 0)*1000});
            });
          }).catch(() => undefined);
        }
        if (epoch === this.generation && pc === this.pc && ['failed', 'closed'].includes(pc.connectionState)) this.peerFailed('rtc_connection_failed');
      };
      pc.oniceconnectionstatechange = () => {
        if (epoch === this.generation && pc === this.pc)
          this.trace('rtc_ice_state', {ice_state:pc.iceConnectionState},
            ['failed', 'disconnected'].includes(pc.iceConnectionState));
      };
      this.negotiation = setTimeout(() => { if (epoch === this.generation && !this.peer) { this.trace('relay_negotiation_timeout', {}, true); this.socket?.close(); } }, 60000);
      await pc.setLocalDescription(await pc.createOffer({}));
      if (epoch !== this.generation || pc !== this.pc || socket !== this.socket) return;
      this.send({ v: 1, type: 'offer', sessionId: this.sid, targetRole: 'desktop', sdp: pc.localDescription!.sdp }); this.offered = true;
      for (const candidate of this.outgoing.splice(0)) this.send({ v: 1, type: 'ice-candidate', sessionId: this.sid, targetRole: 'desktop', candidate: candidate as Record<string, unknown> });
      this.update('connecting', 'Establishing encrypted peer connection.');
    } finally {
      this.offering = false;
      if (epoch === this.generation && this.wanted && socket !== this.socket && this.socket?.readyState === 1 && this.online && !this.pc) {
        void this.offer(epoch).catch(() => this.socket?.close());
      }
    }
  }
  private reconnect() {
    if (!this.wanted || this.retry) return;
    const epoch = this.generation;
    const delay = Math.max(this.retryNotBefore - Date.now(), Math.min(60000, 1000 * 2 ** Math.min(++this.attempts, 6)) + Math.random() * 1000);
    this.trace('relay_retry_scheduled', {attempt:this.attempts, delay_ms:delay});
    this.transition('reconnect_scheduled','timer','retry');
    this.retry = setTimeout(() => { this.retry = null; void this.openForReconnect(epoch); }, delay);
  }
  async resumeAfterForeground(): Promise<void> {
    if (this.peerRecoveryTimer && (!this.auth.token || this.auth.expiresAt <= Date.now())) {
      this.peerFailed('authorization_expired'); return;
    }
    if (this.peerRecoveryTimer && this.peerRecoveryDeadline <= Date.now()) {
      this.peerFailed('recovery_timeout'); return;
    }
    if (!this.wanted || !this.retry || this.socket || Date.now() < this.retryNotBefore) return;
    clearTimeout(this.retry); this.retry = null;
    this.trace('relay_foreground_retry');
    await this.openForReconnect(this.generation);
  }
  private async openForReconnect(epoch: number): Promise<void> {
    await this.open().catch(error => {
      if (epoch !== this.generation) return;
      this.trace('relay_retry_failed', {reason:error instanceof RelayError ? error.code : 'network_or_validation'}, true);
      if (error instanceof RelayError && AUTH_FAILURES.includes(error.code)) this.disconnect('reconnect_authorization_rejected');
      this.update(this.healthyPeer() ? 'connected' : this.recoverablePeer() ? 'reconnecting' : 'error',
        error instanceof Error ? error.message : 'Reconnect failed.');
      this.reconnect();
    });
  }
  private closePeer(reason = 'session_cleanup') {
    if (this.peer || this.pc) this.transition(reason === 'desktop_changed' ? 'desktop_changed' : 'explicit_cleanup',
      'application','cleanup');
    if (this.peer || this.pc) this.trace('relay_peer_teardown', {reason});
    if (this.healthTimer) clearInterval(this.healthTimer); this.healthTimer = null;
    this.clearPeerRecovery(); this.establishedPeer = null;
    if (this.negotiation) clearTimeout(this.negotiation); this.negotiation = null;
    const peer = this.peer; this.peer = null; if (peer) { peer.onClose = () => undefined; peer.close(undefined, 'session_teardown'); void clearPeerMedia(peer); }
    // Fence the transport before synchronous player invalidation callbacks.
    // Live recovery must see an outage, not a terminal error on a healthy peer.
    const pc = this.pc; this.pc = null; pc?.close(); this.incoming = []; this.outgoing = []; this.offered = false;
    this.selectedCandidateType = 'unknown'; this.selectedCandidateProtocol = 'unknown';
  }
  disconnect(reason = 'user_or_caller') {
    if (this.sid) this.transition('explicit_cleanup','application','initiating');
    this.trace('relay_disconnect', {reason});
    this.wanted = false;
    if (this.sid && this.socket?.readyState === 1) {
      try { this.send({ v: 1, type: 'hangup', sessionId: this.sid, targetRole: 'desktop', reason: 'Disconnected' }); } catch {}
    }
    ++this.generation;
    if (this.retry) clearTimeout(this.retry); if (this.refresh) clearInterval(this.refresh);
    if (this.authorizationTimer) clearTimeout(this.authorizationTimer); this.authorizationTimer = null;
    this.retry = null; this.refresh = null; this.socket?.close(); this.socket = null; this.socketToken = ''; this.closePeer(reason); this.online = false;
    this.update('disconnected', '');
  }
}
