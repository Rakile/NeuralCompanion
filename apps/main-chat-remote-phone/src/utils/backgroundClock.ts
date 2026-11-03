// Connection work normally uses RN timers. A protected Android media service
// can also wake it when an OEM stops Choreographer despite the headless task.
type Timer = { cancel(): void; deadline: number; fire(native: boolean): void };
const pending = new Set<Timer>();

function schedule(callback: () => void, milliseconds: number, repeat: boolean): Timer {
  const delay = Math.max(1, milliseconds);
  let version = 0;
  let handle: ReturnType<typeof globalThis.setTimeout>;
  const clear = () => { if (repeat) globalThis.clearInterval(handle); else globalThis.clearTimeout(handle); };
  const arm = () => {
    const expected = ++version;
    const tick = () => {
      if (version === expected) timer.fire(false);
    };
    handle = repeat ? globalThis.setInterval(tick, delay) : globalThis.setTimeout(tick, delay);
  };
  const timer: Timer = {
    deadline: performance.now() + delay,
    cancel() { pending.delete(timer); version++; clear(); },
    fire(native) {
      if (!pending.has(timer) || (native && performance.now() < timer.deadline)) return;
      if (repeat) {
        timer.deadline = performance.now() + delay;
        if (native) { clear(); arm(); }
      }
      else timer.cancel();
      callback();
    },
  };
  pending.add(timer); arm(); return timer;
}

export const setBackgroundInterval = (callback: () => void, milliseconds: number): Timer => schedule(callback, milliseconds, true);
export const setBackgroundTimeout = (callback: () => void, milliseconds = 0): Timer => schedule(callback, milliseconds, false);
export const clearBackgroundTimer = (timer: Timer | null | undefined): void => timer?.cancel();

export function pulseBackgroundClock(): void {
  // Snapshot prevents callbacks scheduled by a callback from firing this pulse.
  for (const timer of [...pending]) timer.fire(true);
}
