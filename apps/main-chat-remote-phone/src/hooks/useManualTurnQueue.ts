import { useEffect, useRef } from 'react';

type Turn = { operation: () => Promise<unknown>; validate: () => void; background?:()=>boolean; resolve: (value: unknown) => void; reject: (error: unknown) => void };

/** Manual input waits for the owned reply, not individual audio-player gaps. */
export function useManualTurnQueue(blocked: (retainedRecording?:boolean) => boolean) {
  const latest = useRef(blocked);
  latest.current = blocked;
  const queue = useRef<Turn[]>([]);
  const running = useRef(false);
  const mounted = useRef(true);
  const pump = useRef<() => void>(() => {});
  pump.current = () => {
    if (!mounted.current) return;
    // Cancel stale waiting work even while an earlier upload is pending.
    queue.current = queue.current.filter(turn => {
      try { turn.validate(); return true; }
      catch (error) { turn.reject(error); return false; }
    });
    if (running.current || !queue.current.length || latest.current(queue.current[0]?.background?.()===true)) return;
    const turn = queue.current.shift()!;
    running.current = true;
    void (async () => {
      try { turn.validate(); turn.resolve(await turn.operation()); }
      catch (error) { turn.reject(error); }
      finally { running.current = false; pump.current(); }
    })();
  };
  useEffect(() => { pump.current(); });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      for (const turn of queue.current.splice(0)) turn.reject(new Error('Queued message cancelled because the screen closed.'));
    };
  }, []);
  return (operation: Turn['operation'], validate: Turn['validate'],background?:Turn['background']): Promise<unknown> => {
    try {
      validate();
      if (!mounted.current) throw new Error('Queued message cancelled because the screen closed.');
      if (queue.current.length >= 4) throw new Error('The manual message queue is full. Wait for the current speech to finish.');
    } catch (error) { return Promise.reject(error); }
    return new Promise((resolve, reject) => {
      queue.current.push({ operation, validate, background, resolve, reject });
      pump.current();
    });
  };
}
