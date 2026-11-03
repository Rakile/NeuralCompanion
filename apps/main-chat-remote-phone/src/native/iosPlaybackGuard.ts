import { requireOptionalNativeModule } from 'expo';
import { createAudioPlayer } from 'expo-audio';
import { Platform } from 'react-native';
import type { PhoneReplyReceipt } from '../api/types';
import { androidContinuousCaptureEnabled } from './iosContinuousCapturePolicy';

type GuardModule = {
  ncPlaybackGuardVersion?: () => number;
  ncPhoneReplyReceiptVersion?: () => number;
  ncFreezePhoneReplyReceipt?: (ticket: string, requestId: string, interruptionId: string) => unknown;
  ncSkipPhoneReplyAudio?: (ticket: string, requestId: string) => boolean;
  ncFinishPhoneReplyAudio?: (ticket: string, requestId: string) => boolean;
};
type GuardedPlayer = ReturnType<typeof createAudioPlayer> & {
  ncBindPlaybackTicket?: (ticket: string) => boolean;
  ncBindPhoneReplyChunk?: (ticket: string, requestId: string, chunkId: string) => boolean;
};

function receiptModule(): GuardModule | null {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureEnabled) return null;
  try {
    const module = requireOptionalNativeModule<GuardModule>('ExpoAudio');
    return module?.ncPlaybackGuardVersion?.() === 1 && module.ncPhoneReplyReceiptVersion?.() === 1
      && typeof module.ncFreezePhoneReplyReceipt === 'function' && typeof module.ncSkipPhoneReplyAudio === 'function'
      && typeof module.ncFinishPhoneReplyAudio === 'function'
      ? module : null;
  } catch { return null; }
}

// A primitive capability only. Live listening must also negotiate capture support.
export function phoneReplyReceiptAvailable(): boolean { return receiptModule() !== null; }

const validId = (value: unknown): value is string =>
  typeof value === 'string' && value.length > 0 && Array.from(value).length <= 128;

export function bindPhoneReplyChunk(
  player: ReturnType<typeof createAudioPlayer>, ticket: string, requestId: string, chunkId: string,
): boolean {
  if (!receiptModule() || !validId(ticket) || !validId(requestId) || !validId(chunkId)) return false;
  try { return (player as GuardedPlayer).ncBindPhoneReplyChunk?.(ticket, requestId, chunkId) === true; }
  catch { return false; }
}

export function freezePhoneReplyReceipt(ticket: string, requestId: string, interruptionId: string): PhoneReplyReceipt | null {
  if (!validId(ticket) || !validId(requestId) || !validId(interruptionId)) return null;
  try {
    const raw = receiptModule()?.ncFreezePhoneReplyReceipt?.(ticket, requestId, interruptionId);
    if (!raw || typeof raw !== 'object') return null;
    const receipt = raw as Partial<PhoneReplyReceipt>;
    const ids = receipt.started_chunk_ids;
    if (receipt.phone_request_id !== requestId || receipt.interruption_id !== interruptionId || !Array.isArray(ids)
        || ids.length > 2048 || !ids.every(validId) || new Set(ids).size !== ids.length) return null;
    const copy = [...ids];
    Object.freeze(copy);
    return Object.freeze({ phone_request_id: requestId, interruption_id: interruptionId, started_chunk_ids: copy });
  } catch { return null; }
}

export function skipPhoneReplyAudio(ticket: string, requestId: string): boolean {
  if (!validId(ticket) || !validId(requestId)) return false;
  try { return receiptModule()?.ncSkipPhoneReplyAudio?.(ticket, requestId) === true; }
  catch { return false; }
}

// Only after explicit server producer completion and this request's native queue
// has drained/disposed. Idle audio or a missing snapshot is not completion.
export function finishPhoneReplyAudio(ticket: string, requestId: string): boolean {
  if (!validId(ticket) || !validId(requestId)) return false;
  try { return receiptModule()?.ncFinishPhoneReplyAudio?.(ticket, requestId) === true; }
  catch { return false; }
}

// Only the public additive Expo API is inspected. Explicitly enabled custom
// iOS/Android builds may opt into it; ordinary callers keep legacy playback.
export function playbackGuardAvailable(): boolean {
  if (Platform.OS !== 'ios' && !androidContinuousCaptureEnabled) return false;
  try {
    return requireOptionalNativeModule<GuardModule>('ExpoAudio')?.ncPlaybackGuardVersion?.() === 1;
  } catch { return false; }
}

export function createPhoneAudioPlayer(
  source: Parameters<typeof createAudioPlayer>[0],
  options: Parameters<typeof createAudioPlayer>[1],
  ticket?: string | null,
): ReturnType<typeof createAudioPlayer> {
  if ((Platform.OS !== 'ios' && !androidContinuousCaptureEnabled) || ticket == null) return createAudioPlayer(source, options);
  if (!ticket || !playbackGuardAvailable()) {
    throw new Error('Protected playback requires the updated custom app build.');
  }
  const player = createAudioPlayer(source, options) as GuardedPlayer;
  try {
    if (player.ncBindPlaybackTicket?.(ticket) !== true) throw new Error();
  } catch {
    try { player.pause(); } catch { /* Continue disposal. */ }
    try { player.remove(); } catch { /* Continue disposal. */ }
    try { player.release(); } catch { /* Already disposed. */ }
    throw new Error('Protected playback is no longer available.');
  }
  return player;
}
