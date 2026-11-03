import { Platform } from 'react-native';
import { setAudioModeAsync } from 'expo-audio';
import { androidContinuousCaptureRuntimeEnabled } from './iosContinuousCapturePolicy';

export type Owner = 'manual' | 'ios-live';
export type Lease = { id: number; owner: Owner };

let nextId = 0;
let owner: Lease | undefined;
let chain: Promise<unknown> = Promise.resolve();
type AudioMode = Parameters<typeof setAudioModeAsync>[0];
// Expo's pinned AudioRecords defaults: each partial write replaces, not merges.
const defaultMode = {
  allowsRecording: false, interruptionMode: 'mixWithOthers' as const,
  playsInSilentMode: false, shouldPlayInBackground: false, allowsBackgroundRecording: false,
};
const liveBackgroundMode = {
  playsInSilentMode: true, allowsRecording: true, shouldPlayInBackground: true,
  allowsBackgroundRecording: false, interruptionMode: 'doNotMix' as const,
};
let lastMode: AudioMode = { ...defaultMode };
let livePhase: 'acquired' | 'starting' | 'running' | 'reply-tail' | 'stopped' = 'acquired';
let previousLiveMode: AudioMode | undefined;

async function writeMode(mode: AudioMode): Promise<void> {
  await setAudioModeAsync(mode);
  if (Platform.OS !== 'ios') return;
  lastMode = Object.fromEntries(Object.entries({ ...defaultMode, ...mode })
    .map(([key, value]) => [key, value ?? defaultMode[key as keyof typeof defaultMode]])) as AudioMode;
}

function requireLive(lease: Lease): void {
  if (!owns(lease) || lease.owner !== 'ios-live') throw new Error('The Live microphone lease is no longer current.');
}

// Internal only: caller already owns the serialization boundary and confirmed drain.
async function restorePreparedMode(): Promise<void> {
  if (!previousLiveMode) return;
  await writeMode(previousLiveMode);
  previousLiveMode = undefined;
}

export function prepareLiveBackgroundAudio(lease: Lease): Promise<void> {
  if (Platform.OS !== 'ios') return Promise.resolve();
  return serialize(async () => {
    requireLive(lease);
    if (livePhase !== 'acquired') throw new Error('Background audio must be prepared before native Start.');
    if (previousLiveMode) return;
    previousLiveMode = { ...lastMode };
    try { await writeMode(liveBackgroundMode); }
    catch (error) {
      // A failed preparation ends this attempt, even if restoration succeeds.
      livePhase = 'stopped';
      await restorePreparedMode();
      throw error;
    }
  });
}

export function restoreLiveBackgroundAudio(lease: Lease): Promise<void> {
  if (Platform.OS !== 'ios') return Promise.resolve();
  return serialize(async () => {
    requireLive(lease);
    if (livePhase !== 'acquired' && livePhase !== 'stopped') {
      throw new Error('Stop the native Live microphone before restoring audio.');
    }
    await restorePreparedMode();
  });
}

// Wrap native Start only. Route confirmation, arm, UI and network work stay outside.
// A rejected Start may have partially acquired hardware: retain phase until drain.
export function startLiveCapture(lease: Lease, start: () => Promise<void>): Promise<void> {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled()) return start();
  return serialize(async () => {
    requireLive(lease);
    if (livePhase !== 'acquired') throw new Error('The native Live microphone has already started.');
    livePhase = 'starting';
    await start();
    livePhase = 'running';
  });
}

function serialize<T>(operation: () => Promise<T> | T): Promise<T> {
  const result = chain.then(operation);
  chain = result.catch(() => undefined);
  return result;
}

function owns(lease: Lease): boolean {
  return owner?.id === lease.id && owner.owner === lease.owner;
}

export function acquireCapture(kind: Owner): Promise<Lease> {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled() && !owner) return Promise.resolve({ id: ++nextId, owner: kind });
  return serialize(() => {
    if (owner) throw new Error('Stop the current microphone before starting another capture.');
    owner = { id: ++nextId, owner: kind };
    livePhase = 'acquired';
    return { ...owner };
  });
}

// The stop callback must not call this coordinator recursively. Its promise is
// the native drain boundary; rejection deliberately keeps the owner in place.
export function releaseCapture(lease: Lease, stop: () => Promise<void>): Promise<void> {
  // Capability teardown must not strand an already acquired Android lease or
  // let a stale release bypass its owner. Legacy capture has no stored owner.
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled() && !owner) return stop();
  return serialize(async () => {
    if (!owns(lease)) throw new Error('The microphone lease is no longer current.');
    await stop();
    if (lease.owner === 'ios-live') {
      livePhase = 'stopped';
      if (Platform.OS === 'ios') await restorePreparedMode();
    }
    owner = undefined;
  });
}

// The callback stops native input and checks exact native output ownership.
// true retains the lease; false proves this lifetime has closed. A rejection
// keeps ownership fenced, including when hardware teardown only partly succeeded.
export function stopLiveListening(lease: Lease, stop: () => Promise<boolean>): Promise<void> {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled()) return stop().then(() => undefined);
  return serialize(async () => {
    requireLive(lease);
    if (livePhase !== 'running') throw new Error('The Live microphone is not capturing.');
    const retained = await stop();
    if (retained !== true && retained !== false) throw new Error('Native output ownership is unavailable.');
    livePhase = retained ? 'reply-tail' : 'stopped';
    if (!retained) {
      if (Platform.OS === 'ios') await restorePreparedMode();
      owner = undefined;
    }
  });
}

export function finishLiveReplyOutput(lease: Lease, finish: () => Promise<void>): Promise<void> {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled()) return finish();
  return serialize(async () => {
    requireLive(lease);
    if (livePhase !== 'reply-tail' && livePhase !== 'stopped') throw new Error('There is no retained Live reply.');
    await finish();
    livePhase = 'stopped';
    if (Platform.OS === 'ios') await restorePreparedMode();
    owner = undefined;
  });
}

export function configurePhoneAudio(mode: Parameters<typeof setAudioModeAsync>[0], lease?: Lease): Promise<void> {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureRuntimeEnabled() && !owner) return setAudioModeAsync(mode);
  return serialize(async () => {
    if (lease && !owns(lease)) throw new Error('The microphone lease is no longer current.');
    if (owner?.owner === 'ios-live') {
      if (!lease && Object.keys(mode).every((key) => key === 'playsInSilentMode') && mode.playsInSilentMode === true) return;
      throw new Error('The native Live microphone owns the audio session.');
    }
    if (owner && !lease) {
      if (Object.keys(mode).every((key) => key === 'playsInSilentMode') && mode.playsInSilentMode === true) return;
      throw new Error('The recording microphone owns the audio session.');
    }
    if (mode.allowsRecording && !lease) throw new Error('Recording requires a microphone lease.');
    await writeMode(mode);
  });
}
