import type { IosLiveCapture } from '../native/iosLiveCapture';

export function continuousActivityAllowed(foreground: boolean, protectedAndroid: boolean, ticket: string | null): boolean {
  return foreground || (protectedAndroid && Boolean(ticket));
}

/** Reuse the existing output lifetime; never open an owner from the background. */
export async function retainContinuousOutput(options: {
  capture: Pick<IosLiveCapture, 'outputState' | 'setReplyPlaybackActive'>;
  foreground: () => boolean;
  ticket: () => string | null;
  current: () => boolean;
  ensureForeground: () => Promise<void>;
}): Promise<string> {
  if (options.foreground()) await options.ensureForeground();
  const ticket = options.ticket();
  const valid = () => Boolean(ticket && options.current() && options.ticket() === ticket);
  if (!valid()) throw new Error('Continuous playback ownership changed.');
  const state = await options.capture.outputState();
  if (!valid() || !state.open || state.ticket !== ticket || state.sessionId !== null
      || !options.capture.setReplyPlaybackActive) {
    throw new Error('Continuous playback ownership is unavailable.');
  }
  // Native starts the service only from a visible Activity. In the background
  // this succeeds solely for the same service owner already started there.
  await options.capture.setReplyPlaybackActive(ticket!, true);
  if (!valid()) throw new Error('Continuous playback ownership changed.');
  return ticket!;
}
