export type RecoveryObservation = Readonly<{
  ownerKey: string; transportRevision: number; connected: boolean;
  freshState: boolean; locked: boolean; enabled: boolean;
}>;
type Phase = 'active' | 'waiting' | 'validating' | 'resuming' | 'terminal';
export type ContinuationAdapter<C> = {
  suspend(epoch: number, signal: AbortSignal): Promise<C>;
  validate(checkpoint: C, epoch: number, signal: AbortSignal): Promise<void>;
  resume(checkpoint: C, epoch: number, signal: AbortSignal): Promise<void>;
  cancel(reason: string): Promise<void>;
  observe(stage: string, epoch: number, outcome: string): void;
  // The caller retains its existing error classification and retry scheduler.
  retryable?(error: unknown, stage: 'suspend' | 'validate' | 'resume'): boolean;
  schedule?(retry: () => void): () => void;
};
type Attempt<C> = { epoch: number; control: AbortController; checkpoint?: C;
  suspended: boolean; busy: boolean; revision: number };

/** Supervises continuation only. Native adapters retain all output authority. */
export class ContinuationRecovery<C> {
  private phase: Phase = 'active';
  private epoch = 0;
  private state?: RecoveryObservation;
  private attempt?: Attempt<C>;
  private clearRetry?: () => void;
  private closing?: Promise<void>;
  constructor(private readonly adapter: ContinuationAdapter<C>) {}
  snapshot(): { phase: Phase; epoch: number } { return { phase: this.phase, epoch: this.epoch }; }
  observe(state: RecoveryObservation): void {
    if (this.phase === 'terminal') return;
    const previous = this.state;
    this.state = { ...state };
    if (!state.enabled || (previous && previous.ownerKey !== state.ownerKey)) {
      void this.cancel(state.enabled ? 'owner_changed' : 'disabled').catch(() => undefined); return;
    }
    const ready = this.ready();
    const changed = previous && previous.transportRevision !== state.transportRevision;
    if (this.phase === 'active') {
      if (!state.connected || !state.freshState || changed) this.suspend();
    } else if (this.attempt?.busy && (!ready || changed)) {
      // A result from an earlier transport must never reopen the new epoch.
      this.suspend();
    }
    this.restore();
  }
  cancel(reason: string): Promise<void> {
    if (this.phase === 'terminal') return this.closing ?? Promise.resolve();
    this.phase = 'terminal';
    this.attempt?.control.abort(); this.clearTimer();
    this.trace('cancelled', reason);
    this.closing = Promise.resolve().then(() => this.adapter.cancel(reason));
    return this.closing;
  }
  private ready(): boolean {
    return Boolean(this.state?.enabled && this.state.connected && this.state.freshState && !this.state.locked);
  }
  private current(attempt: Attempt<C>): boolean {
    return this.attempt === attempt && !attempt.control.signal.aborted && this.phase !== 'terminal';
  }
  private trace(stage: string, outcome: string): void {
    // Diagnostics cannot become output authority or break recovery.
    try { this.adapter.observe(stage, this.epoch, outcome); } catch { /* best effort */ }
  }
  private clearTimer(): void { const clear = this.clearRetry; this.clearRetry = undefined; clear?.(); }
  private suspend(): void {
    this.attempt?.control.abort(); this.clearTimer();
    const attempt: Attempt<C> = { epoch: ++this.epoch, control: new AbortController(),
      suspended: false, busy: false, revision: this.state!.transportRevision };
    this.attempt = attempt; this.phase = 'waiting'; this.trace('suspend', 'requested');
    void Promise.resolve().then(() => {
      if (this.current(attempt)) return this.adapter.suspend(attempt.epoch, attempt.control.signal);
    }).then(checkpoint => {
      if (!this.current(attempt)) return;
      attempt.checkpoint = checkpoint as C; attempt.suspended = true;
      this.trace('suspend', 'completed'); this.restore();
    }).catch(error => this.failed(attempt, 'suspend', error));
  }
  private restore(): void {
    const attempt = this.attempt;
    if (!attempt || !this.current(attempt) || !attempt.suspended || attempt.busy || this.clearRetry || !this.ready()) return;
    attempt.busy = true; attempt.revision = this.state!.transportRevision;
    this.phase = 'validating'; this.trace('validate', 'requested');
    let stage: 'validate' | 'resume' = 'validate';
    void Promise.resolve().then(() => {
      if (this.current(attempt) && this.ready()) return this.adapter.validate(attempt.checkpoint!, attempt.epoch, attempt.control.signal);
    }).then(async () => {
      if (!this.current(attempt) || !this.ready()) return;
      stage = 'resume'; this.phase = 'resuming'; this.trace('resume', 'requested');
      await this.adapter.resume(attempt.checkpoint!, attempt.epoch, attempt.control.signal);
      if (!this.current(attempt) || !this.ready()) return;
      this.phase = 'active'; this.trace('resume', 'completed'); this.attempt = undefined;
    }).catch(error => this.failed(attempt, stage, error)).finally(() => { attempt.busy = false; });
  }
  private failed(attempt: Attempt<C>, stage: 'suspend' | 'validate' | 'resume', error: unknown): void {
    if (!this.current(attempt)) return;
    attempt.busy = false;
    if (stage === 'validate' && this.adapter.retryable?.(error, stage) && this.adapter.schedule) {
      this.phase = 'waiting'; this.trace(stage, 'retry_scheduled');
      this.clearRetry = this.adapter.schedule(() => {
        this.clearRetry = undefined;
        if (this.current(attempt)) this.restore();
      });
    } else {
      this.trace(stage, 'failed'); void this.cancel(`${stage}_failed`).catch(() => undefined);
    }
  }
}
