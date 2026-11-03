import { PeerTransport } from './peer';
import { AVCompatibilityError } from './av';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';

type Rtc = typeof import('react-native-webrtc');
type Signal = (action: 'offer' | 'candidate' | 'close', body: Record<string, unknown>) => Promise<Record<string, unknown>>;
type Credential = { session: string; credential: string };

async function clearPeerMedia(peer: PeerTransport): Promise<void> {
  await (require('./media') as typeof import('./media')).clearPeerMedia(peer);
}

/** Local pairing owns this media-only peer. HTTP/WS remain the command transport. */
export class LocalAVSession {
  state: 'connecting' | 'connected' | 'reconnecting' | 'error' | 'closed' = 'closed';
  error = '';
  desktopInstance = '';
  peer: PeerTransport | null = null;
  onChange: () => void = () => undefined;
  private pc: InstanceType<Rtc['RTCPeerConnection']> | null = null;
  private credential: Credential | null = null;
  private generation = 0;
  private wanted = false;
  private retry: ReturnType<typeof setTimeout> | null = null;
  private deadline: ReturnType<typeof setTimeout> | null = null;
  private attempts = 0;
  constructor(private signal: Signal,private readonly cacheOwner:string) {}
  get avTransportClosed() { return this.state !== 'connected'; }
  get avHandle() { return this.peer?.avHandle ?? ''; }
  get avPresentationActive() { return this.peer?.avPresentationActive ?? false; }
  async getAVOutput() {
    // The connection hook admits HQ only after readiness, never a file fallback.
    if (this.state !== 'connected' || !this.peer) throw new Error(this.error || 'Local media is connecting.');
    return this.peer.getAVOutput();
  }
  private update(state: typeof this.state, error = '') {
    this.state = state; this.error = error;
    void recordPhoneDebug('info', 'local_av_state', { state }).catch(() => undefined);
    this.onChange();
  }
  start() { if (this.wanted) return; this.wanted = true; void this.open(); }
  private async open() {
    const epoch = ++this.generation;
    this.update(this.attempts ? 'reconnecting' : 'connecting');
    try {
      const { RTCPeerConnection } = require('react-native-webrtc') as Rtc;
      const pc = new RTCPeerConnection({ iceServers: [] }); this.pc = pc;
      const current = () => this.wanted && epoch === this.generation && this.pc === pc;
      const channel = pc.createDataChannel('nc-av-v1', { ordered: true });
      const candidates: Record<string, unknown>[] = [];
      let sent = 0, sending = false;
      const sendCandidates = async () => {
        if (sending || !this.credential) return;
        sending = true;
        try {
          while (current() && this.credential && candidates.length) {
            if (++sent > 64) throw new Error('Local candidate limit.');
            await this.signal('candidate', { ...this.credential, candidate: candidates.shift() });
          }
        } catch (error) { if (current()) this.failed(error); }
        finally { sending = false; }
      };
      pc.onicecandidate = (event: { candidate?: { toJSON(): Record<string, unknown> } }) => {
        if (!current() || !event.candidate) return;
        if (candidates.length + sent >= 64) { this.failed(new Error('Local candidate limit.')); return; }
        candidates.push(event.candidate.toJSON()); void sendCandidates();
      };
      pc.onconnectionstatechange = () => {
        if (current() && ['failed', 'closed'].includes(pc.connectionState)) this.failed(new Error('Local media disconnected.'));
      };
      channel.onopen = () => {
        if (!current() || !this.credential) { channel.close(); return; }
        const peer = new PeerTransport(this.credential.session, channel as never, null,
          JSON.stringify([this.cacheOwner,this.desktopInstance]));
        this.peer = peer;
        peer.onClose = () => { if (current() && this.peer === peer) this.failed(peer.mediaError || new Error('Local media disconnected.')); };
        void peer.negotiateBuffered().then(() => {
          if (!current() || peer.closed) return;
          if (this.deadline) clearTimeout(this.deadline); this.deadline = null;
          this.attempts = 0; this.update('connected');
        }).catch(error => { if (current()) this.failed(error); });
      };
      this.deadline = setTimeout(() => { if (current()) this.failed(new Error('Local media negotiation timed out.')); }, 20000);
      await pc.setLocalDescription(await pc.createOffer({}));
      if (!current()) return;
      const result = await this.signal('offer', { version: 1, sdp: pc.localDescription!.sdp });
      if (result.version !== 1 || typeof result.session !== 'string' || !/^[a-f0-9]{32}$/.test(result.session)
        || typeof result.credential !== 'string' || !/^[a-f0-9]{64}$/.test(result.credential)
        || typeof result.desktop_instance !== 'string' || !/^[a-f0-9]{32}$/.test(result.desktop_instance)
        || typeof result.sdp !== 'string' || result.sdp.length > 65536)
        throw new AVCompatibilityError('Update the NC desktop for local Opus/H.264 media.');
      const credential = { session: result.session, credential: result.credential };
      if (!current()) { void this.signal('close', credential).catch(() => undefined); return; }
      this.credential = credential;
      this.desktopInstance = result.desktop_instance;
      this.onChange();
      await pc.setRemoteDescription({ type: 'answer', sdp: result.sdp });
      await sendCandidates();
    } catch (error) { if (epoch === this.generation && this.wanted) this.failed(error); }
  }
  private failed(error: unknown) {
    if (!this.wanted) return;
    ++this.generation;
    const failure = error as { status?: number; payload?: { error_code?: string } };
    const permanent = error instanceof AVCompatibilityError || failure?.status === 404
      || failure?.payload?.error_code === 'MEDIA_SETUP_REQUIRED';
    // Fence the public state before native callbacks run during disposal.
    this.update(permanent ? 'error' : 'reconnecting', permanent
      ? (error instanceof Error ? error.message : 'Update desktop media setup.') : 'Local media reconnecting.');
    this.dispose();
    if (permanent) { this.wanted = false; return; }
    if (!this.retry) this.retry = setTimeout(() => { this.retry = null; if (this.wanted) void this.open(); }, Math.min(15000, 1000 * 2 ** Math.min(++this.attempts, 4)));
  }
  requestRecovery() { if (!this.wanted || this.state !== 'connected') return false; this.failed(new Error('Media recovery requested.')); return true; }
  private dispose() {
    if (this.deadline) clearTimeout(this.deadline); this.deadline = null;
    const peer = this.peer; this.peer = null;
    if (peer) {
      peer.onClose = () => undefined; peer.close();
      void clearPeerMedia(peer).catch(() => undefined);
    }
    const pc = this.pc; this.pc = null; pc?.close();
    const credential = this.credential; this.credential = null;
    if (credential) void this.signal('close', credential).catch(() => undefined);
  }
  close() {
    this.wanted = false; ++this.generation;
    if (this.retry) clearTimeout(this.retry); this.retry = null;
    this.update('closed'); this.dispose();
  }
}
