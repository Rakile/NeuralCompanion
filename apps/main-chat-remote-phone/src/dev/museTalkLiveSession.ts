// Development-only owner for successive eligible reply trials. Audio remains owned by useAudioQueue.
import type {RemoteClient} from '../api/client';
import type {AudioChunk} from '../api/types';
import type {OptionalVisualStart} from '../utils/optionalVisualStart';
import {MuseTalkLiveTrial} from './museTalkLiveTrial';

const ARM_RETRY_MS = 1000;

export type MuseTalkEligibilityOptions = {invalidate?: boolean; suspend?: boolean};

export class MuseTalkLiveSession {
  readonly trial: MuseTalkLiveTrial;
  private listeners = new Set<() => void>();
  private eligible = false;
  private closed = false;
  private generation = 0;
  private arming = false;
  private armPromise: Promise<void> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | undefined;
  private activeReply: string | null = null;
  private detachReply: (() => void) | undefined;
  private deferArming: (() => void) | undefined;
  private recovery: AbortController | null = null;

  constructor(private client: RemoteClient, private readonly options: {
    prepareReply?(trial:MuseTalkLiveTrial,chunk:AudioChunk,signal:AbortSignal):Promise<void>;
    idleChunks?():boolean;
  } = {}) {
    this.trial = new MuseTalkLiveTrial(client,{retainIdleOnCancel:true,idleChunks:options.idleChunks});
    this.trial.subscribe(() => {
      this.changed();
      if (this.trial.snapshot.phase === 'off' && !this.activeReply) this.ensureArmed();
    });
  }

  subscribe = (callback: () => void) => {
    this.listeners.add(callback);
    return () => { this.listeners.delete(callback); };
  };

  private changed() { for (const callback of this.listeners) callback(); }

  setEligible(enabled: boolean, options: MuseTalkEligibilityOptions = {}): void {
    if (this.closed) return;
    this.eligible = enabled;
    ++this.generation;
    clearTimeout(this.retryTimer); this.retryTimer = undefined;
    if (!enabled) {
      if (options.suspend && !options.invalidate && this.activeReply && this.trial.snapshot.phase !== 'arming') {
        this.trial.suspendPresentation();
        return;
      }
      this.recovery?.abort();
      // Live-off drains an admitted reply. Disconnect/background/engine changes
      // may request immediate invalidation without changing the public default.
      if (options.invalidate) { this.trial.clearRetainedIdle(); this.releaseReply(true); }
      else if (!this.activeReply) this.trial.cancel();
      return;
    }
    this.ensureArmed();
  }

  private canArm() { return this.eligible && !this.closed && (this.client.auth.kind === 'lan' || Boolean(this.client.bufferedPeer))
    && !(this.options.idleChunks?.()===true&&this.trial.chunkIdleUnsupported) && !this.activeReply && !this.deferArming && !this.recovery; }

  /** Used only by the uncached visual owner before its finite idle epoch ends.
   * Cancel/re-arm excludes old audio; never recover a reply just to renew idle. */
  async renewVisualArm():Promise<boolean>{
    if(this.options.idleChunks?.()!==true||!this.canArm()||this.arming||this.trial.snapshot.phase!=='armed')return false;
    const previous=this.trial.snapshot.trialId;
    this.trial.cancel('Renewing idle video');
    await this.ensureArmed();
    return this.canArm()&&this.trial.snapshot.phase==='armed'&&this.trial.snapshot.trialId!==previous;
  }

  private scheduleRetry() {
    if (!this.canArm() || this.retryTimer) return;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = undefined;
      this.ensureArmed();
    }, ARM_RETRY_MS);
  }

  private ensureArmed(): Promise<void> {
    if (!this.canArm() || this.trial.snapshot.phase === 'armed' || this.trial.busy || this.arming) return this.armPromise ?? Promise.resolve();
    clearTimeout(this.retryTimer); this.retryTimer = undefined;
    const generation = this.generation;
    let reconcileStaleGeneration = false;
    this.arming = true;
    const started = this.trial.arm();
    const pending = Promise.resolve(started).then(() => {
      if (generation !== this.generation || !this.canArm()) {
        if (this.trial.snapshot.phase === 'armed') this.trial.cancel();
        reconcileStaleGeneration = this.canArm();
        return;
      }
      if (this.trial.snapshot.phase !== 'armed') this.scheduleRetry();
    }).finally(() => {
      this.arming = false;
      if (this.armPromise === pending) this.armPromise = null;
      if (reconcileStaleGeneration && this.canArm() && this.trial.snapshot.phase === 'off') this.ensureArmed();
    });
    this.armPromise = pending;
    return pending;
  }

  private releaseReply(cancel: boolean) {
    this.detachReply?.(); this.detachReply = undefined;
    this.activeReply = null;
    if (cancel) this.trial.cancel();
  }

  private deferUntilReplyEnds(signal: AbortSignal) {
    this.deferArming?.();
    if (signal.aborted) return;
    const release = () => {
      if (this.deferArming !== detach) return;
      this.deferArming = undefined;
      this.ensureArmed();
    };
    const detach = () => signal.removeEventListener('abort',release);
    this.deferArming = detach;
    signal.addEventListener('abort',release,{once:true});
  }

  private trackReply(reply: string, signal: AbortSignal) {
    this.releaseReply(false);
    this.activeReply = reply;
    const release = () => {
      if (this.activeReply !== reply) return;
      this.releaseReply(false);
      // The trial's own listener observes the same abort and retires resources.
      // If a backend cancellation completed first, resume idle arming here.
      this.ensureArmed();
    };
    signal.addEventListener('abort',release,{once:true});
    this.detachReply = () => signal.removeEventListener('abort',release);
  }

  private deferPublishedFirst(signal: AbortSignal) {
    this.deferUntilReplyEnds(signal);
    this.trial.cancel();
  }

  private async recoverReply(chunk: AudioChunk, signal: AbortSignal, deadline: number): Promise<void> {
    const recovery = new AbortController();
    this.recovery = recovery;
    clearTimeout(this.retryTimer); this.retryTimer = undefined;
    this.trackReply(chunk.phone_request_id!,signal);
    const cancel = () => recovery.abort();
    signal.addEventListener('abort',cancel,{once:true});
    let admitted = false;
    try {
      // Reconcile any idle arm already on the wire before asking for a specific
      // successor. Its late completion must not cancel the successor's owner.
      await this.armPromise;
      if (signal.aborted || recovery.signal.aborted || this.closed || !this.eligible) return;
      const ready = await this.trial.recover(chunk,recovery.signal);
      if (!ready || signal.aborted || recovery.signal.aborted || this.closed || !this.eligible) return;
      admitted = true;
      await this.options.prepareReply?.(this.trial,chunk,signal);
      if(signal.aborted || recovery.signal.aborted || this.closed)return;
      await this.trial.beforeStart(chunk,signal,deadline);
    } finally {
      signal.removeEventListener('abort',cancel);
      if (this.recovery === recovery) {
        this.recovery = null;
        if (!admitted) {
          this.releaseReply(false);
          if (!signal.aborted && !this.closed) this.deferUntilReplyEnds(signal);
        }
        this.ensureArmed();
      }
    }
  }

  beforeStart: OptionalVisualStart = (chunk, signal, deadline) => {
    const reply = chunk.phone_request_id;
    if (!reply || !Number.isSafeInteger(chunk.sequence_index) || chunk.sequence_index! < 0) {
      if (!this.activeReply) { this.deferUntilReplyEnds(signal); this.trial.cancel(); }
      return;
    }
    if (chunk.playback_recovery_epoch && this.eligible && !this.closed && !signal.aborted
      && performance.now() < deadline && (reply !== this.activeReply || this.trial.snapshot.chunk?.id === chunk.id)) {
      return this.recoverReply(chunk,signal,deadline);
    }
    if (reply === this.activeReply) return this.trial.beforeStart(chunk,signal,deadline);
    if (!this.eligible || this.closed || (this.client.auth.kind !== 'lan' && !this.client.bufferedPeer) || chunk.sequence_index !== 0) return;
    if (signal.aborted || performance.now() >= deadline) {
      // Match the queue's exhausted-deadline contract: an unused arm cannot
      // leak forward and claim a later reply.
      if (!this.activeReply) this.deferPublishedFirst(signal);
      return;
    }
    // A first source can be claimed only by an arm confirmed before it was
    // published and only after the prior reply has fully released ownership.
    if (this.activeReply || this.trial.snapshot.phase !== 'armed') {
      if (!this.activeReply && !this.recovery && deadline === Infinity) {
        return this.recoverReply(chunk,signal,deadline);
      }
      this.deferPublishedFirst(signal);
      return;
    }
    this.trackReply(reply,signal);
    if(this.options.prepareReply)return this.options.prepareReply(this.trial,chunk,signal).then(()=>{
      if(!signal.aborted&&!this.closed&&this.activeReply===reply)return this.trial.beforeStart(chunk,signal,deadline);
    });
    const gate = this.trial.beforeStart(chunk,signal,deadline);
    if (!gate && signal.aborted) this.releaseReply(false);
    return gate;
  };

  prefetch(chunk: AudioChunk | null | undefined): void {
    if (this.activeReply && chunk?.phone_request_id === this.activeReply) this.trial.prefetch(chunk);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true; this.eligible = false; ++this.generation;
    this.recovery?.abort();
    this.trial.clearRetainedIdle();
    clearTimeout(this.retryTimer); this.retryTimer = undefined;
    this.deferArming?.(); this.deferArming = undefined;
    this.releaseReply(true);
    this.listeners.clear();
  }
}
