export type EngineIndicatorStatus = 'stopped' | 'starting' | 'running';

type EngineIndicatorInput = {
  connected: boolean;
  running: boolean;
  lifecycleState?: string;
  startPending: boolean;
};

export function engineIndicatorStatus({ connected, running, lifecycleState, startPending }: EngineIndicatorInput): EngineIndicatorStatus {
  if (!connected) return 'stopped';
  const phase = String(lifecycleState || '').trim().toLowerCase();
  if (startPending || phase === 'starting' || phase === 'initializing' || phase === 'loading') return 'starting';
  if (phase) return phase === 'running' ? 'running' : 'stopped';
  return running ? 'running' : 'stopped';
}
