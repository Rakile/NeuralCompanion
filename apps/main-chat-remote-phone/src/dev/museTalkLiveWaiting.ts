// Audio availability, not a mobile-specific timeout, determines waiting mode.
export function liveWaitingMode(started: boolean, current: unknown, prepared: unknown): 'hold' | 'idle' {
  return started && !current && !prepared ? 'idle' : 'hold';
}
