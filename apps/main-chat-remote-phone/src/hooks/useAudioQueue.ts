import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {connectionTrace} from '../utils/connectionTrace';
import { createPhoneAudioPlayer, bindPhoneReplyChunk, freezePhoneReplyReceipt, skipPhoneReplyAudio, finishPhoneReplyAudio } from '../native/iosPlaybackGuard';
import type { AudioPlayer } from 'expo-audio';
import type { NativeReplyContinuation } from '../native/iosLiveCapture';

import { RemoteClient } from '../api/client';
import type { AudioChunk, PhoneReplyReceipt, PhoneReplyAuth } from '../api/types';
import {
  audioHistoryAfterBoundary,
  createLatestAudioSampleBuffer,
  nextUnseenAudioChunk,
  refreshAudioChunkMetadata,
} from '../utils/audioFastStart';
import { recordPhoneDebug } from '../utils/phoneDebugBridge';
import {reportMuxedReturn} from '../utils/muxedReturnDiagnostics';
import { AuthorizedMediaResolver } from '../utils/authorizedMedia';
import { configurePhoneAudio } from '../native/phoneCaptureOwnership';
import { continuousCaptureRuntimeEnabled } from '../native/iosContinuousCapturePolicy';
import { boundedVisualStart } from '../utils/optionalVisualStart';
import type { OptionalVisualStart } from '../utils/optionalVisualStart';
import type { BufferedMediaLease } from '../relay/bufferedMedia';
import {sameSource,parseJournalBatch} from '../dev/muxedContinuousProtocol';
import type {ContinuousBufferedAudio,ContinuousMetadata,SourceGrant,RunSnapshot,TailCursor} from '../dev/muxedContinuousProtocol';
import { narrationPauseMs, narrationProfile } from '../utils/narrationPace';
import type { NarrationPace } from '../utils/narrationPace';
import { nativePlaybackError } from '../utils/nativePlaybackError';
import type {ProgressivePcmSource} from '../native/progressivePcm';

const PLAYBACK_STATUS_INTERVAL_MS = 100;
const PLAYBACK_FALLBACK_GRACE_MS = 1500;
const PLAYBACK_START_TIMEOUT_MS = 30_000;
const UNKNOWN_DURATION_PLAYBACK_TIMEOUT_MS = 2 * 60 * 1000;
const MAX_PLAYBACK_FALLBACK_MS = 10 * 60 * 1000;
// Native failure strings are diagnostic data, not authority. Never log an
// arbitrary wire value: even syntactically valid identifiers may contain data.
const CONTINUOUS_NATIVE_FAILURE_CAUSES = new Set([
  'authority', 'expiry', 'output_revocation', 'presentation', 'native_state',
  'source_admission', 'reservation', 'journal', 'terminal_invalid',
  'mutation_ack', 'mutation_schedule', 'mutation_ambiguous', 'mutation_revision',
  'seal_ack', 'seal_schedule', 'seal_ambiguous', 'prune_ack', 'prune_schedule', 'prune_ambiguous',
  'event_identity', 'event_order', 'journal_capacity', 'open_failed', 'stage_registry',
  'pending_owner', 'initial_binding',
  'source_registry', 'append_unconfirmed', 'seal_unconfirmed', 'player_enrollment',
  'player_prepare', 'player_attach_post', 'native_end', 'native_failure',
  'audio_disabled', 'module_destroyed', 'public_loop', 'public_rate',
  'registry_remove', 'public_source', 'public_seek',
  'stop', 'skip', 'replacement', 'recovery', 'failure',
]);
function continuousNativeFailureCause(snapshot:RunSnapshot):string {
  const cause=snapshot.failure?.code;
  return cause===undefined?'unknown':CONTINUOUS_NATIVE_FAILURE_CAUSES.has(cause)?cause:'other';
}
function recordContinuousNativeFailure(snapshot:RunSnapshot,appliedCursor:number):void {
  // Observation only, before ACK/check/cleanup can hide the native first cause.
  // Logging cannot delay fencing, fail playback or expose opaque identities.
  try {
    void recordPhoneDebug('error','continuous_native_failure',{
      state:snapshot.state,nativeCause:continuousNativeFailureCause(snapshot),
      publishedCursor:snapshot.publishedCursor,acknowledgedCursor:snapshot.acknowledgedCursor,appliedCursor,
      tailSequence:snapshot.speechTail.source.sequenceIndex,sourceCount:snapshot.sources.length,
      startedCount:snapshot.sources.filter(source=>source.started).length,
      completedCount:snapshot.sources.filter(source=>source.completed).length,
      readersClosedCount:snapshot.sources.filter(source=>source.readersClosed).length,
    }).catch(()=>undefined);
  } catch { /* Diagnostics must not escape into playback or reader cleanup. */ }
}
// Expo fixes this option at construction and otherwise deactivates the shared
// session on pause/completion. Cover players prepared before Live starts too.
const continuousCapturePlayerOptions = () => continuousCaptureRuntimeEnabled() ? { keepAudioSessionActive: true } : {};

export type PlaybackState = {
  enabled: boolean;
  volume: number;
  playingId: string;
  playedCount: number;
  // Observation only: advances on a natural finish, including explicit replay.
  lastCompletedChunk?: { id: string; revision: number } | null;
  error: string;
  currentChunk: AudioChunk | null;
  preparedChunk: AudioChunk | null;
  positionSeconds: number;
  sourceClockRequired?:boolean;
  isPlaying: boolean;
  isBetweenSegments?: boolean;
  activePlayer: AudioPlayer | null;
  getPlaybackClock: (player: AudioPlayer, chunkId: string) => PlaybackClock | null;
  getLiveSample: () => readonly number[] | null;
  setLiveSample: (sample: readonly number[] | null) => void;
  setEnabled: (enabled: boolean) => void;
  playNow: (chunk: AudioChunk) => Promise<void>;
  interrupt: () => void;
  stop: () => void;
  reset: () => void;
  skipReply: (requestId: string) => void;
  stopExplicitPlayback: (() => void) | null;
  explicitPlaybackPending?:boolean;
  stopCharacterPreview: (id: string) => void;
  activeReplyId: string | null;
  hasReplyAudio: boolean;
  freezeReply: (interruptionId: string) => PhoneReplyReceipt | null;
  replyDrained: (requestId: string, finalSequence: number | null) => boolean;
  finishReply: (requestId: string) => boolean;
  replyFinished: (requestId: string) => boolean;
  retireVisualCarrier: () => Promise<void>;
  completedReplySequence: (requestId: string) => number;
  appendReplyMedia: (requestId: string, chunks: AudioChunk[]) => void;
  recoveryEpoch: number;
  suspendReplyPlayback: (checkpoint: NativeReplyContinuation) => void;
  restoreReplyPlayback: (checkpoint: NativeReplyContinuation, chunks: AudioChunk[], recoveryEpoch: number) => Promise<boolean>;
  cancelReplyContinuation: () => void;
  manualRecovery?: NativeReplyContinuation | null;
  suspendForPeerInterruption: () => NativeReplyContinuation | null;
  paused: boolean;
  pause: () => void | Promise<void>;
  resume: () => Promise<void>;
  playSequence: (chunks: AudioChunk[]) => Promise<void>;
};

export type PlaybackClock = {
  seconds: number;
  sampledAtMs: number;
  playing: boolean;
  buffering: boolean;
  rate?: number;
};

type AudioQueueOptions = {
  // Installed only for the explicitly negotiated buffered-media path. The
  // owner checks reply authority; the queue retains a pin until native detach.
  bufferedAudio?: {
    acquire(chunk: AudioChunk, signal: AbortSignal): Promise<BufferedMediaLease>;
    owns(chunk: AudioChunk, uri: string): boolean;
    // Explicit development muxed lane only. It prepares the same registered
    // player before output and must confirm native detach before file release.
    createPlayer?(chunk: AudioChunk, options: Parameters<typeof createPhoneAudioPlayer>[1], ticket: string | null,
      signal: AbortSignal): Promise<{ player: AudioPlayer; detach: () => Promise<void>; dispose?: () => void | Promise<void>;
        continuous?:ContinuousMetadata }>;
    continuous?:ContinuousBufferedAudio;
    continuousRequired?:boolean;
    // A development session can retain files ahead, but its one native player
    // must not replace the active source during ordinary queue prefetch.
    deferNativePreparation?: boolean;
    attach?(player: AudioPlayer, chunk: AudioChunk, ticket: string | null): Promise<() => void>;
    replay?: {
      acquire(chunk: AudioChunk, signal: AbortSignal): Promise<BufferedMediaLease>;
      owns(chunk: AudioChunk, uri: string): boolean;
    };
  };
  // undefined: local/generated queue; null: awaiting backend sync; []: synced empty.
  initialSnapshot?: AudioChunk[] | null;
  resolveOwnedAudio?: (chunk: AudioChunk) => string | null;
  getReplyAuth?: (chunk: AudioChunk) => PhoneReplyAuth | null;
  onChunkFinished?: (chunk: AudioChunk) => void;
  // Observation only, before native detach. Unlike generic settlement this
  // excludes errors/timeouts/Stop and requires actual started automatic output.
  onChunkDrained?: (chunk: AudioChunk, player: AudioPlayer) => void;
  // Optional trial observer after recovery validation, before any activation.
  onReplyMediaRestored?: (requestId: string, chunks: readonly AudioChunk[]) => void;
  onAssistantPlaybackStarted?: (requestId: string) => void;
  sourceKey?: string;
  continuationScopeKey?: string;
  autoplayEnabled?: boolean;
  volume?: number;
  narrationPace?: NarrationPace;
  onAutoplayEnabledChange?: (enabled: boolean) => void;
  onBeforePlayback?: () => Promise<void> | void;
  onBeforeAutomaticVisualStart?: OptionalVisualStart;
  automaticVisualStartBudgetMs?: () => number;
  allowAutomaticChunk?: (chunk: AudioChunk) => boolean;
  automaticPolicyRevision?: number;
  playbackTicket?: string | null;
  requirePlaybackTicket?: boolean;
  phoneReplyControls?: boolean;
  ownedReplyIds?: string[];
  nativeAdmittedReplyIds?: string[];
  onReplyFailure?: (reason: string) => void;
  onCharacterPreviewError?: (message: string) => void;
  canRecoverTransportLoss?: () => boolean;
  manualContinuationEnabled?: boolean;
  transportConnected?: boolean;
};

type AudioStatus = {
  nativeFailureReason?: string;
  nativePlayerErrorCode?: number;
  playWhenReady?: boolean;
  currentTime?: number;
  didJustFinish?: boolean;
  error?: string;
  isLoaded?: boolean;
  playing?: boolean;
  playbackState?: string;
  timeControlStatus?: string;
  reasonForWaitingToPlay?: string;
  isBuffering?: boolean;
  focusInterrupted?: boolean;
};

type AudioPlayerHandle = {
  ncAVPlayer?: boolean;
  seekTo?: (seconds: number, toleranceBefore?: number, toleranceAfter?: number) => Promise<void>;
  currentTime?: number;
  play: () => void;
  pause?: () => void;
  release?: () => void;
  remove?: () => void;
  volume?: number;
  shouldCorrectPitch?: boolean;
  setPlaybackRate?: (rate: number, quality?: 'high') => void;
  isLoaded?: boolean;
  addListener?: (
    event: string,
    listener: (status: AudioStatus) => void,
  ) => { remove?: () => void } | undefined;
};

type PlayerSlot = {
  playbackRate?: number;
  boundaryPause?: { remainingMs: number; deadlineMs: number; timer?: ReturnType<typeof setTimeout>; complete: () => void };
  resumeTimers?: () => void;
  mediaLease?: BufferedMediaLease;
  ownsMedia?: () => boolean;
  id: string;
  chunk: AudioChunk;
  player: AudioPlayerHandle;
  createdAtMs: number;
  sourceUrl: string;
  subscription?: { remove?: () => void };
  fallbackTimer?: ReturnType<typeof setTimeout>;
  hardFallbackTimer?: ReturnType<typeof setTimeout>;
  focusWaitTimer?: ReturnType<typeof setTimeout>;
  focusInterrupted?: boolean;
  playbackStartedLogged?: boolean;
  lastPlaybackPositionSeconds?: number;
  preparedLogged?: boolean;
  lastStatus?: AudioStatus;
  lastStatusAtMs?: number;
  waitingForSource?: boolean;
  automatic: boolean;
  playbackTicket: string | null;
  requirePlaybackTicket: boolean;
  continuous?:ContinuousQueueRun;
};
type ContinuousQueueEntry={chunk:AudioChunk;source?:SourceGrant;lease?:BufferedMediaLease;
  uri:string;started:boolean;completed:boolean;closing?:Promise<void>};
type ContinuousQueueRun={metadata:ContinuousMetadata;adapter:ContinuousBufferedAudio;abort:AbortController;
  entries:Map<string,ContinuousQueueEntry>;cursor:number;tail:TailCursor;snapshot?:RunSnapshot;
  speechDeparture?:Readonly<{replyId:string;finalSequence:number}>;
  clockAtMs?:number;polling?:Promise<void>;wakePending?:boolean;cancelled:boolean;unsubscribe?:()=>void;closing?:Promise<void>};

function applyNarrationRate(player: AudioPlayerHandle, chunk: AudioChunk, pace: NarrationPace | undefined): number {
  if (player.ncAVPlayer || progressiveSources.has(player) || bufferedFactories.has(player) || continuousFactories.has(player) || !player.setPlaybackRate || chunk.id.startsWith('character-preview-')) return 1;
  const rate = narrationProfile(pace).rate;
  try {
    player.shouldCorrectPitch = true;
    player.setPlaybackRate(rate, 'high');
    return rate;
  } catch {
    // Unsupported native output keeps its normal pace, without blocking audio.
    try { player.setPlaybackRate(1); } catch { /* Player owns its fallback. */ }
    return 1;
  }
}

function normalizeVolume(value: number | undefined): number {
  const parsed = Number(value ?? 1);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(0, Math.min(1, parsed));
}

function playbackError(chunk: AudioChunk, error: unknown): string {
  if (/^file:/i.test(chunk.url_path)) return 'Local audio playback failed. Try replaying or clearing the phone queue.';
  return error instanceof Error ? error.message : String(error || 'Audio playback failed.');
}

const bufferedObservers = new WeakMap<AudioPlayerHandle, () => void>();
const bufferedFactories = new WeakMap<AudioPlayerHandle, () => Promise<void>>();
const bufferedDisposers = new WeakMap<AudioPlayerHandle, () => void | Promise<void>>();
const bufferedRetirements = new WeakMap<AudioPlayerHandle, Promise<void>>();
const continuousFactories = new WeakMap<AudioPlayerHandle,ContinuousMetadata>();
const progressiveSources = new WeakMap<AudioPlayerHandle,ProgressivePcmSource>();
async function createQueuePlayer(buffered: AudioQueueOptions['bufferedAudio'], chunk: AudioChunk, source: string,
  settings: Parameters<typeof createPhoneAudioPlayer>[1], ticket: string | null, signal: AbortSignal): Promise<AudioPlayerHandle> {
  if (!buffered?.createPlayer){if(buffered?.continuousRequired)throw Error('Update NC Remote for required continuous muxed factory.');
    return createPhoneAudioPlayer(source, settings, ticket) as AudioPlayerHandle;}
  const prepared = await buffered.createPlayer(chunk, settings, ticket, signal);
  const player = prepared.player as AudioPlayerHandle;
  if(prepared.continuous)continuousFactories.set(player,prepared.continuous);else continuousFactories.delete(player);
  await bufferedRetirements.get(player);
  bufferedRetirements.delete(player);
  if(prepared.dispose)bufferedDisposers.set(player,prepared.dispose);else bufferedDisposers.delete(player);
  bufferedFactories.set(player, prepared.detach);
  return player;
}
async function attachBufferedPlayer(buffered: AudioQueueOptions['bufferedAudio'], player: AudioPlayerHandle,
  chunk: AudioChunk, ticket: string | null): Promise<void> {
  if (!buffered?.attach || bufferedObservers.has(player)) return;
  const detach = await buffered.attach(player as AudioPlayer, chunk, ticket);
  bufferedObservers.set(player, detach);
}

function releasePlayer(player: AudioPlayerHandle | undefined): Promise<void> {
  if (!player) {
    return Promise.resolve();
  }
  const retiring = bufferedRetirements.get(player); if (retiring) return retiring;
  progressiveSources.get(player)?.close();
  const detach = bufferedObservers.get(player); bufferedObservers.delete(player);
  try { detach?.(); } catch { /* Visual cleanup cannot prevent audio Stop. */ }
  try { player.pause?.(); } catch { /* Native player may already be released. */ }
  const customDispose = bufferedDisposers.get(player);
  const dispose = () => {
  if(customDispose)return customDispose();
  // Expo remove unregisters activity-resume ownership; shared-object release
  // disposes the engine but does not remove Android's player registry entry.
  try { player.remove?.(); } catch { /* Still release if already unregistered. */ }
  try { player.release?.(); } catch { /* One failure must not block the queue. */ }
  };
  const close = bufferedFactories.get(player);
  if (!close) { dispose(); return Promise.resolve(); }
  // Failed native detach deliberately retains the leases. Never unlink media
  // still owned by a native decoder, including a late prepare after Stop.
  const pending = Promise.resolve().then(close).then(dispose);
  bufferedRetirements.set(player, pending);
  void pending.catch(() => undefined);
  return pending;
}

function timingDetails(chunk: AudioChunk, eventAtMs: number): Record<string, number | string> {
  const backendCreatedAtMs = Math.max(0, Number(chunk.created_at || 0) * 1000);
  return {
    chunk_id: String(chunk.id || ''),
    sequence_index: Number(chunk.sequence_index ?? chunk.index ?? 0),
    backend_created_at_ms: Math.round(backendCreatedAtMs),
    backend_to_event_ms: backendCreatedAtMs > 0 ? Math.max(0, Math.round(eventAtMs - backendCreatedAtMs)) : 0,
  };
}

// Failure-only transport evidence. Never log the authorized URL, body, or raw
// network exception (which can contain the pairing code or a media ticket).
async function probeAudioMedia(chunk: AudioChunk, sourceUrl: string): Promise<void> {
  if (!/^https?:\/\//i.test(sourceUrl)) return;
  const controller = new AbortController();
  const deadline = setTimeout(() => controller.abort(), 5000);
  const details: Record<string, number | string> = { ...timingDetails(chunk, Date.now()) };
  try {
    const response = await fetch(sourceUrl, {
      headers: { Range: 'bytes=0-1' },
      signal: controller.signal,
    });
    details.http_status = response.status;
    const contentType = response.headers.get('content-type') || '';
    const contentRange = response.headers.get('content-range') || '';
    const contentLength = response.headers.get('content-length') || '';
    details.content_type = /^[\w.+-]+\/[\w.+-]+$/.test(contentType) ? contentType : 'other or missing';
    details.content_range = /^bytes (?:\d+-\d+|\*)\/(?:\d+|\*)$/.test(contentRange) ? contentRange : 'other or missing';
    details.content_length = /^\d+$/.test(contentLength) ? contentLength : 'other or missing';
  } catch {
    details.error = controller.signal.aborted ? 'request timeout' : 'network request failed';
  } finally {
    // Do not consume a full audio body if a server ignored the range request.
    controller.abort();
    clearTimeout(deadline);
  }
  await recordPhoneDebug('info', 'audio_media_probe', details);
}

export function useAudioQueue(client: RemoteClient, chunks: AudioChunk[], options: AudioQueueOptions = {}): PlaybackState {
  const retainedChunks = useRef(new Map<string, AudioChunk>());
  const continuation = useRef<NativeReplyContinuation | null>(null);
  const suspended = useRef(false);
  const heard = useRef(new Set<string>());
  const resumePositions = useRef(new Map<string, number>());
  const [recoveryEpoch, setRecoveryEpoch] = useState(0);
  const [retainedRevision, reviseRetained] = useState(0);
  chunks = useMemo(() => retainedChunks.current.size
    ? [...new Map([...retainedChunks.current, ...chunks.map(c => [c.id, c] as const)]).values()]
      .sort((a, b) => a.phone_request_id === b.phone_request_id ? Number(a.sequence_index ?? 0) - Number(b.sequence_index ?? 0) : 0)
    : chunks, [chunks, retainedRevision]);
  // Connection identity deliberately excludes secrets. Media authorization must
  // also follow credential replacement at the same server without resetting history.
  const mediaResolver = useMemo(() => new AuthorizedMediaResolver(client), [
    client.identityKey, client.pairingCode,
    client.auth.kind === 'internet' ? client.auth.deviceToken : '',
  ]);
  const [enabled, setEnabledState] = useState(options.autoplayEnabled ?? true);
  const [playingId, setPlayingId] = useState('');
  const [playedCount, setPlayedCount] = useState(0);
  const [lastCompletedChunk, setLastCompletedChunk] = useState<PlaybackState['lastCompletedChunk']>(null);
  const [error, setError] = useState('');
  const [currentChunk, setCurrentChunk] = useState<AudioChunk | null>(null);
  const [preparedChunk, setPreparedChunk] = useState<AudioChunk | null>(null);
  const [positionSeconds, setPositionSeconds] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [manualRecovery, setManualRecovery] = useState<NativeReplyContinuation | null>(null);
  const [activePlayer, setActivePlayer] = useState<AudioPlayer | null>(null);
  const volume = normalizeVolume(options.volume);
  const played = useRef<Set<string>>(new Set());
  const autoplaySeen = useRef<Set<string>>(new Set());
  const historyIdentity = useRef(options.continuationScopeKey || client.identityKey);
  const initialSnapshotConsumed = useRef(false);
  const active = useRef<PlayerSlot | null>(null);
  const retiringRuns=useRef(new Set<Promise<void>>());
  const diagnosticSample = useRef({at:0, state:''});
  const prepared = useRef<PlayerSlot | null>(null);
  const activationRevision = useRef(0);
  const activationDownload = useRef<AbortController | null>(null);
  const preparationDownload = useRef<AbortController | null>(null);
  const visualStartAbort = useRef<AbortController | null>(null);
  const visualReply = useRef<string | null>(null);
  const pendingActivation = useRef<{ id: string; automatic: boolean } | null>(null);
  const preparationRevision = useRef(0);
  const pendingPreparation = useRef<string | null>(null);
  const pendingAVPreparation = useRef<string | null>(null);
  const busyPreparation = useRef<{id:string; active:PlayerSlot; until:number; failures:number; timer:ReturnType<typeof setTimeout>|null}|null>(null);
  const chunksRef = useRef<AudioChunk[]>(chunks);
  const enabledRef = useRef(enabled);
  const [paused, setPaused] = useState(false);
  const pausedRef = useRef(false);
  const explicitQueue = useRef<AudioChunk[]>([]);
  const volumeRef = useRef(volume);
  const playNextRef = useRef<() => void>(() => undefined);
  const prepareNextRef = useRef<() => void>(() => undefined);
  const optionsRef = useRef(options);
  const liveSampleBuffer = useRef(createLatestAudioSampleBuffer()).current;
  const replyRecords = useRef(new Map<string, { suppressed: boolean; finished: boolean; started: string[]; settled: Set<number>; bound: boolean; progressive?: boolean }>());
  const ongoingReply = useRef<string | null>(null);
  const replyCapacityClosed = useRef(false);

  chunksRef.current = chunks;
  enabledRef.current = enabled;
  volumeRef.current = volume;
  optionsRef.current = options;

  // This is deliberately absent for ordinary foreground queues.
  const automaticEligible = (chunk: AudioChunk, preparing: boolean) =>
    enabledRef.current && !suspended.current && !replyCapacityClosed.current && !replyRecords.current.get(chunk.phone_request_id || '')?.suppressed
      && ((!retainedChunks.current.has(chunk.id) && !(optionsRef.current.phoneReplyControls && chunk.phone_request_id)) || !chunk.sequence_index
        || Array.from({length: chunk.sequence_index}, (_, i) => i).every(i =>
          replyRecords.current.get(chunk.phone_request_id || '')?.settled.has(i)
          // Preparation may retain the immediate successor while its predecessor
          // speaks. File players stay silent until completion; late retention
          // manifests must not cancel the download or let later chunks jump ahead.
          || (preparing && i === chunk.sequence_index! - 1 && active.current?.automatic
            && active.current.chunk.phone_request_id === chunk.phone_request_id
            && active.current.chunk.sequence_index === i)))
      && optionsRef.current.allowAutomaticChunk?.(chunk) !== false;
  const automaticAllowed = (chunk: AudioChunk) => automaticEligible(chunk, false);
  const preparationAllowed = (chunk: AudioChunk) => automaticEligible(chunk, true);
  // Completed speech metadata/policy is not the continuing visual membership.
  // This only distinguishes normal reply cleanup; native retains permission and
  // every explicit Stop, ticket/connection replacement and suspension still fences.
  const finishedVisualCarrier = (slot:PlayerSlot|null) => {
    const run=slot?.continuous,departure=run?.speechDeparture;
    return !!departure&&!run!.cancelled&&enabledRef.current&&!suspended.current&&!replyCapacityClosed.current
      &&replyRecords.current.get(departure.replyId)?.finished===true;
  };
  const replyRecord = (requestId: string) => {
    let record = replyRecords.current.get(requestId);
    if (!record && replyRecords.current.size < 256) {
      record = { suppressed: false, finished: false, started: [], settled: new Set(), bound: false };
      replyRecords.current.set(requestId, record);
    }
    if (!record && !replyCapacityClosed.current) { replyCapacityClosed.current = true; optionsRef.current.onReplyFailure?.('reply_record_capacity'); }
    return record;
  };
  const settleChunk = (chunk: AudioChunk) => {
    if (optionsRef.current.phoneReplyControls && chunk.phone_request_id) {
      const index = chunk.sequence_index;
      if (Number.isInteger(index) && Number(index) >= 0 && Number(index) < 2048) replyRecord(chunk.phone_request_id)?.settled.add(Number(index));
    }
    optionsRef.current.onChunkFinished?.(chunk);
  };
  const bindReply = (player: AudioPlayerHandle, chunk: AudioChunk, ticket: string | null, automatic: boolean) => {
    if (!automatic || !optionsRef.current.phoneReplyControls || !chunk.phone_request_id) return;
    const record = replyRecord(chunk.phone_request_id);
    if (!record || (ticket && !continuousFactories.has(player)&&!bindPhoneReplyChunk(player as AudioPlayer, ticket, chunk.phone_request_id, chunk.id))) {
      // The failure callback can synchronously interrupt this queue, causing
      // the outer catch to discard stale work. Preserve evidence before that
      // teardown; never include tickets, media URLs or conversation content.
      try {
        void recordPhoneDebug('error', 'audio_reply_admission_failed', {
          reason: record ? 'native_binding_rejected' : 'reply_record_capacity',
          sequence_index: chunk.sequence_index,
          reply_record_count: replyRecords.current.size,
          started_chunk_count: record?.started.length ?? 0,
          previously_bound: record?.bound === true,
          suppressed: record?.suppressed === true,
          finished: record?.finished === true,
          native_admitted: optionsRef.current.nativeAdmittedReplyIds?.includes(chunk.phone_request_id) === true,
          protected_output: Boolean(ticket),
        }).catch(() => undefined);
      } catch { /* Diagnostics must not prevent rejection or cleanup. */ }
      releasePlayer(player); optionsRef.current.onReplyFailure?.('player_binding_rejected');
      throw new Error('Reply audio admission ended. Stop Live and restart when ready.');
    }
    record.bound = Boolean(ticket);
    if (progressiveSources.has(player)) record.progressive = true;
  };
  const ticketAllowed = (ticket: string | null, required: boolean) =>
    required === (optionsRef.current.requirePlaybackTicket === true)
    && ticket === (optionsRef.current.playbackTicket ?? null)
    && (!required || Boolean(ticket));

  useEffect(() => {
    configurePhoneAudio({ playsInSilentMode: true }).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (typeof options.autoplayEnabled === 'boolean') {
      setEnabledState(options.autoplayEnabled);
    }
  }, [options.autoplayEnabled]);

  useEffect(() => {
    if (active.current?.player) {
      active.current.player.volume = volume;
    }
    if (prepared.current?.player) {
      prepared.current.player.volume = volume;
    }
  }, [volume]);

  const setEnabled = useCallback((nextEnabled: boolean) => {
    setEnabledState(Boolean(nextEnabled));
    options.onAutoplayEnabledChange?.(Boolean(nextEnabled));
  }, [options.onAutoplayEnabledChange]);

  const resolveAudio = useCallback(async (chunk: AudioChunk) => {
    const ownedUri = optionsRef.current.resolveOwnedAudio?.(chunk);
    if (ownedUri) return { url: ownedUri };
    if (/^file:/i.test(chunk.url_path)) throw new Error('Local audio is not owned by this phone session.');
    const media = await mediaResolver.resolve(chunk.url_path);
    if (/^file:/i.test(media.url) && !client.ownsRelayMediaUrl?.(media.url)) {
      throw new Error('Remote audio is not owned by this connection.');
    }
    return media;
  }, [mediaResolver, client]);

  const releaseActive = useCallback((clearPlaying = true, preserveVisualReply = false, releaseReason = 'cancel_or_replace') => {
    activationDownload.current?.abort(); activationDownload.current = null;
    if (!preserveVisualReply) {
      visualStartAbort.current?.abort(); visualStartAbort.current = null; visualReply.current = null;
    }
    activationRevision.current++;
    pendingActivation.current = null;
    const current = active.current;
    active.current = null;
    if (current?.boundaryPause?.timer) clearTimeout(current.boundaryPause.timer);
    if (current) connectionTrace.event('audio_player_released', {
      chunk_id:current.id, reply_id:current.chunk.phone_request_id,
      position_seconds:Number(current.lastStatus?.currentTime || 0),
      automatic:Number(current.automatic), paused:Number(pausedRef.current),
      reason:preserveVisualReply ? 'natural_boundary' : releaseReason,
      queued:explicitQueue.current.length, retained:retainedChunks.current.size,
    });
    if (current?.fallbackTimer) {
      clearTimeout(current.fallbackTimer);
    }
    if (current?.hardFallbackTimer) {
      clearTimeout(current.hardFallbackTimer);
    }
    if (current?.focusWaitTimer) clearTimeout(current.focusWaitTimer);
    try { current?.subscription?.remove?.(); } catch { /* Already detached. */ }
    if(current?.continuous){
      const run=current.continuous;run.cancelled=true;
      // Native fences before outstanding admissions/readers are joined. Source
      // file leases stay charged until the exact run and every reader close.
      const fence=run.adapter.invalidate(run.metadata.run,'stop');run.abort.abort();run.unsubscribe?.();
      run.closing=(async()=>{const results=await Promise.allSettled([fence,run.polling]);
        // A poll cancelled during acquire/append may reject after delivering
        // its exact grant. Native fencing still permits confirmed retirement.
        const fenced=results[0];if(fenced?.status==='rejected')throw fenced.reason;
        await run.adapter.retireRun(run.metadata.run);
        await Promise.all([...run.entries.values()].map(async e=>{if(e.source)await run.adapter.retireSource(e.source);
          await e.closing;await e.lease?.release();}));
      })();void run.closing.catch(()=>undefined);
      retiringRuns.current.add(run.closing);
      void run.closing.then(()=>{retiringRuns.current.delete(run.closing!);},()=>{
        // Keep failed joins in the barrier: loss of the UI slot is not proof
        // of reader exit and must never authorize a new physical owner.
      });
    }else void releasePlayer(current?.player).then(() => current?.mediaLease?.release()).catch(() => undefined);
    setCurrentChunk(null);
    setActivePlayer(null);
    setPositionSeconds(0);
    setIsPlaying(false);
    liveSampleBuffer.set(null);
    if (clearPlaying) {
      setPlayingId('');
    }
  }, [liveSampleBuffer]);

  const startContinuous = (slot:PlayerSlot,metadata:ContinuousMetadata,adapter:ContinuousBufferedAudio) => {
    const run:ContinuousQueueRun={metadata,adapter,abort:new AbortController(),entries:new Map(),cursor:0,
      tail:metadata.tail,cancelled:false};slot.continuous=run;
    run.entries.set(slot.chunk.id,{chunk:slot.chunk,source:metadata.source,lease:slot.mediaLease,uri:slot.sourceUrl,started:false,completed:false});
    slot.mediaLease=undefined;
    const check=()=>{
      if(run.cancelled||run.abort.signal.aborted||active.current!==slot||!ticketAllowed(slot.playbackTicket,slot.requirePlaybackTicket))
        throw Error('Continuous queue owner ended.');
      for(const e of run.entries.values())if(!e.completed&&(!optionsRef.current.bufferedAudio?.owns(e.chunk,e.uri)
        ||optionsRef.current.allowAutomaticChunk?.(e.chunk)===false))throw Error('Continuous queue source authority ended.');
    };
    const poll=()=>{
      if(run.cancelled||run.abort.signal.aborted||active.current!==slot)return;
      if(run.polling){run.wakePending=true;return;}
      run.wakePending=false;
      const work=(async()=>{
        check();
        const batch=parseJournalBatch(await adapter.read(metadata.run,run.cursor),metadata.run,run.cursor);
        if(batch.snapshot.state==='failed'||batch.snapshot.state==='invalidated')
          recordContinuousNativeFailure(batch.snapshot,run.cursor);
        check();run.snapshot=batch.snapshot;run.tail=batch.snapshot.speechTail;run.clockAtMs=performance.now();
        for(const event of batch.events){
          if(event.membership==='visual'){adapter.onApplied(event);run.cursor=event.cursor;continue;}
          const entry=run.entries.get(event.source.chunkId);
          if(!entry?.source||!sameSource(entry.source,event.source))throw Error('Continuous queue journal source changed.');
          adapter.onApplied(event);
          if(event.kind==='source_started'){
            entry.started=true;slot.id=entry.chunk.id;slot.chunk=entry.chunk;slot.sourceUrl=entry.uri;
            slot.playbackStartedLogged=true;setCurrentChunk(entry.chunk);setPlayingId(entry.chunk.id);
            setActivePlayer(slot.player as AudioPlayer);
            if(entry.chunk.phone_request_id){const record=replyRecord(entry.chunk.phone_request_id);
              if(!record)throw Error('Continuous reply record capacity.');
              if(!record.started.includes(entry.chunk.id))record.started.push(entry.chunk.id);
              ongoingReply.current=entry.chunk.phone_request_id;}
          }else if(event.kind==='source_completed'){
            entry.completed=true;heard.current.add(entry.chunk.id);settleChunk(entry.chunk);
            // A pending final-source close cannot block journal ACK or run join.
            entry.closing=adapter.retireSource(event.source).then(()=>entry.lease?.release()).then(()=>{entry.lease=undefined;});
            void entry.closing.catch(()=>undefined);
          }else if(event.kind==='speech_membership_completed'){
            const replyId=entry.chunk.phone_request_id,finalSequence=event.source.sequenceIndex;
            if(!replyId||!batch.snapshot.speechMembershipCompleted||batch.snapshot.tail.kind!=='visual'
              ||!sameSource(batch.snapshot.tail.source.parent,event.source)||!sameSource(run.tail.source,event.source)
              ||[...run.entries.values()].some(e=>!e.completed||e.chunk.phone_request_id!==replyId)
              ||Array.from({length:finalSequence+1},(_,index)=>index)
                .some(index=>!replyRecords.current.get(replyId)?.settled.has(index)))
              throw Error('Continuous speech departure unconfirmed.');
            run.speechDeparture=Object.freeze({replyId,finalSequence});
            if(ongoingReply.current===replyId)ongoingReply.current=null;
            setCurrentChunk(null);setPlayingId('');setActivePlayer(null);setIsPlaying(false);setPositionSeconds(0);
          }
          run.cursor=event.cursor;
        }
        if(run.cursor>batch.snapshot.acknowledgedCursor)await adapter.acknowledge(metadata.run,run.cursor);
        check();
        const clock=batch.snapshot.clock;
        if(clock?.kind==='speech'&&!run.speechDeparture){setPositionSeconds(clock.seconds);setIsPlaying(clock.playing);}
        if(batch.snapshot.state==='failed'||batch.snapshot.state==='invalidated')
          throw Error(`Continuous native run ended (${continuousNativeFailureCause(batch.snapshot)}).`);
        if(batch.snapshot.state==='drained'){
          reportMuxedReturn('run_retire_start');
          await adapter.retireRun(metadata.run);check();
          reportMuxedReturn('run_retire_done');
          await Promise.all([...run.entries.values()].map(async e=>{if(e.source)await adapter.retireSource(e.source);
            await e.closing;await e.lease?.release();e.lease=undefined;}));
          reportMuxedReturn('source_joins_done');
          // Whole-run joins publish reader-closure events after the drained
          // batch. Apply and ACK that retained journal before Session can open
          // another run; neither retirement nor ACK manufactures a receipt.
          const joined=parseJournalBatch(await adapter.read(metadata.run,run.cursor),metadata.run,run.cursor);check();
          if(joined.snapshot.state!=='retired')throw Error('Continuous run retirement unconfirmed.');
          for(const event of joined.events){
            if(event.membership==='visual'){
              if(event.kind==='visual_started')throw Error('Continuous retired journal epoch changed.');
              adapter.onApplied(event);run.cursor=event.cursor;continue;
            }
            const entry=run.entries.get(event.source.chunkId);
            if(event.kind!=='source_readers_closed'||!entry?.source||!sameSource(entry.source,event.source))
              throw Error('Continuous retired journal source changed.');
            adapter.onApplied(event);run.cursor=event.cursor;
          }
          if(run.cursor>joined.snapshot.acknowledgedCursor)await adapter.acknowledge(metadata.run,run.cursor);
          check();run.snapshot=joined.snapshot;
          reportMuxedReturn('closure_ack_done');
          check();reportMuxedReturn('return_callback_start');await adapter.onDrained?.(batch.snapshot);check();
          reportMuxedReturn('return_callback_done');
          run.cancelled=true;run.unsubscribe?.();active.current=null;
          try{slot.subscription?.remove?.();}catch{}
          setCurrentChunk(null);setPlayingId('');setActivePlayer(null);setIsPlaying(false);
          setTimeout(()=>playNextRef.current(),0);return;
        }
        if(batch.snapshot.state!=='open'||batch.snapshot.tail.kind==='visual')return;
        const tailEntry=run.entries.get(run.tail.source.chunkId),tailState=batch.snapshot.sources.find(s=>sameSource(s.source,run.tail.source));
        if(!tailEntry?.source||!tailState?.layoutInstalled)return;
        const next=chunksRef.current.find(c=>c.phone_request_id===tailEntry.chunk.phone_request_id
          &&c.sequence_index===tailEntry.chunk.sequence_index!+1);
        if(next){
          // Reuse the ordinary future eligibility, including exact source policy.
          // Only the immediate native predecessor may still be unsettled.
          const priorSettled=Array.from({length:next.sequence_index!},(_,i)=>i===tailEntry.chunk.sequence_index
            ||replyRecords.current.get(next.phone_request_id!)?.settled.has(i));
          if(!enabledRef.current||suspended.current||replyRecords.current.get(next.phone_request_id!)?.suppressed
            ||priorSettled.some(x=>!x)||optionsRef.current.allowAutomaticChunk?.(next)===false)return;
          const candidate=adapter.candidate(run.tail,next);if(candidate==='pending')return;
          if(candidate==='compatible'){
            let entry=run.entries.get(next.id);
            if(!entry){entry={chunk:{...next},uri:'',started:false,completed:false};run.entries.set(next.id,entry);}
            if(!entry.source){
              if(!entry.lease){const lease=await optionsRef.current.bufferedAudio!.acquire(next,run.abort.signal);
                entry.lease=lease;entry.uri=lease.uri;check();}
              const admitted=await adapter.appendSource(run.tail,next,slot.playbackTicket!,run.abort.signal);
              // Preserve a grant even if Stop arrived during its native ACK;
              // shutdown must retire that exact reader before releasing files.
              if(admitted.kind==='admitted'){entry.source=admitted.source;autoplaySeen.current.add(next.id);
                played.current.add(next.id);setPlayedCount(played.current.size);}
              check();
            }
            return;
          }
        }
        // Exact finality admits Desktop RETURN on the same carrier. A missing
        // nonfinal successor keeps this player open (holding its last frame),
        // just like a successor whose acquisition is still pending.
        const finalReturn=await adapter.finalReturn(run.tail);check();
        if(finalReturn!=='nonfinal'||!next)return;
        // Preserve the existing incompatible-plan boundary; never append a
        // successor that failed the continuity/ownership checks above.
        await adapter.sealTail(run.tail);
      })();
      run.polling=work;
      void work.catch(error=>{if(!run.cancelled){setError(playbackError(slot.chunk,error));
        suspended.current=true;releaseActive(true);optionsRef.current.onReplyFailure?.('continuous_queue_failed');
      }}).finally(()=>{if(run.polling===work){run.polling=undefined;
        // Coalesce wakes received during read/ACK/admission into one followup.
        // Terminal owners cannot be revived by their queued native callbacks.
        if(run.wakePending&&!run.cancelled&&!run.abort.signal.aborted&&active.current===slot)poll();
      }});
    };
    run.unsubscribe=adapter.subscribe(metadata.run,poll);poll();
  };

  const resumeBoundaryPause = (slot: PlayerSlot) => {
    const pause = slot.boundaryPause;
    if (!pause || active.current !== slot || pausedRef.current) return;
    if (pause.timer) clearTimeout(pause.timer);
    pause.deadlineMs = performance.now() + pause.remainingMs;
    const timer = setTimeout(() => {
      if (active.current !== slot || pause.timer !== timer || pausedRef.current) return;
      pause.timer = undefined;
      pause.complete();
    }, pause.remainingMs);
    pause.timer = timer;
  };

  const releasePrepared = useCallback(() => {
    preparationDownload.current?.abort(); preparationDownload.current = null;
    preparationRevision.current++;
    pendingPreparation.current = null;
    pendingAVPreparation.current = null;
    const current = prepared.current;
    prepared.current = null;
    try { current?.subscription?.remove?.(); } catch { /* Already detached. */ }
    void releasePlayer(current?.player).then(() => current?.mediaLease?.release()).catch(() => undefined);
    setPreparedChunk(null);
  }, []);

  const suspendForAVDisconnect = (nativeReason?: string) => {
    const streamFailure = ['concealment_limit', 'stream_discontinuity', 'media_stall'].includes(nativeReason ?? '');
    if ((!client.avTransportClosed && !streamFailure) || !optionsRef.current.phoneReplyControls
        || optionsRef.current.canRecoverTransportLoss?.() !== true) return false;
    // Peer teardown can notify a player before React observes disconnected.
    // Do not turn that ordering into an explicit Live Stop/Skip. Only the
    // existing native checkpoint + authenticated recovery may reopen playback.
    suspended.current = true;
    // Replace the failed output/peer only while same-owner Live intent is active.
    // Do this before releasing players: native invalidation must observe closed.
    if (!client.avTransportClosed) {
      try { if (!client.requestAVRecovery()) return false; } catch { return false; }
    }
    releaseActive(true); releasePrepared();
    setError('');
    void recordPhoneDebug('info', 'audio_waiting_for_connection_recovery', { native_reason: nativeReason ?? '' }).catch(() => undefined);
    return true;
  };

  const suspendManualReply = (reason: 'peer_interrupted' | 'player_error' | 'playback_timeout' | 'media_owner_lost' | 'connection_changed' | 'user_pause') => {
    if (!optionsRef.current.manualContinuationEnabled || !optionsRef.current.continuationScopeKey) return false;
    if (suspended.current && continuation.current) return true;
    const slot = active.current;
    // Incomplete PCM has no seek/recovery route. Never replay a spoken prefix.
    if (slot && progressiveSources.has(slot.player)) return false;
    if (!slot?.automatic || !slot.chunk.phone_request_id) return false;
    // A failed native startup still owns an unheard chunk that can be resumed.
    if (!slot.playbackStartedLogged && reason !== 'player_error') return false;
    const ids = optionsRef.current.ownedReplyIds ?? [];
    if (!ids.includes(slot.chunk.phone_request_id)) return false;
    const checkpoint: NativeReplyContinuation = { recoveryEpoch: (continuation.current?.recoveryEpoch ?? 0) + 1,
      // Pending manual turns have no audio manifest yet. They retain their own
      // receipt and must not become prerequisites for resuming this response.
      replies: [slot.chunk.phone_request_id].map(requestId => ({ requestId,
        completedChunkIds: chunksRef.current.filter(c => c.phone_request_id === requestId && heard.current.has(c.id)).map(c => c.id),
        activeChunkId: requestId === slot.chunk.phone_request_id ? slot.id : null,
        positionSeconds: requestId === slot.chunk.phone_request_id ? Math.max(0, Number(slot.lastStatus?.currentTime ?? 0)) : null })) };
    continuation.current = checkpoint; suspended.current = true;
    setManualRecovery(checkpoint); setRecoveryEpoch(checkpoint.recoveryEpoch);
    releaseActive(true, false, `suspended_${reason}`); releasePrepared();
    setError(reason === 'peer_interrupted' || reason === 'connection_changed'
      ? 'Connection interrupted. The reply will resume when you return and reconnect.'
      : reason === 'user_pause' ? 'Reply paused. Tap Resume response in Audio to continue.'
      : 'Audio playback interrupted. Tap Resume response in Audio to continue.');
    void recordPhoneDebug('info', 'manual_reply_suspended', { reply_count: checkpoint.replies.length,
      reason, reply_id: slot.chunk.phone_request_id, chunk_id: slot.id,
      native_error_code: slot.lastStatus?.nativePlayerErrorCode,
      focus_interrupted: Boolean(slot.lastStatus?.focusInterrupted),
      play_when_ready: slot.lastStatus?.playWhenReady,
      sequence_index: slot.chunk.sequence_index, position_seconds: checkpoint.replies.find(r => r.activeChunkId)?.positionSeconds }).catch(() => undefined);
    return true;
  };

  const activateChunk = useCallback(async (
    chunk: AudioChunk,
    preparedSlot?: PlayerSlot | null,
    automatic = true,
  ) => {
    const chunkId = String(chunk.id || '').trim();
    if (!chunkId) {
      return;
    }
    if (!automatic && chunk.progressive_audio) throw new Error('This reply is still generating. Replay is available when it finishes.');
    if (chunk.progressive_audio) chunk = {...chunk,duration_seconds:Math.max(1,(chunk.text?.length || 0)/14)};
    if (automatic && !automaticAllowed(chunk)) return;
    const playbackTicket = optionsRef.current.playbackTicket ?? null;
    const requirePlaybackTicket = optionsRef.current.requirePlaybackTicket === true;
    if (!ticketAllowed(playbackTicket, requirePlaybackTicket)) return;
    const visualCallback = automatic ? optionsRef.current.onBeforeAutomaticVisualStart : undefined;
    const continuingVisual = Boolean(visualCallback && chunk.phone_request_id && chunk.sequence_index! > 0
      && visualReply.current === chunk.phone_request_id && visualStartAbort.current && !visualStartAbort.current.signal.aborted);
    releaseActive(false, continuingVisual);
    let visualBudget = 1000;
    try {
      const requested = optionsRef.current.automaticVisualStartBudgetMs?.();
      if (requested === Infinity) visualBudget = Infinity;
      else if (typeof requested === 'number' && Number.isFinite(requested)) visualBudget = Math.max(0,Math.min(2500,requested));
    } catch { /* Optional policy failure retains the normal bounded budget. */ }
    const visualDeadline = visualCallback ? performance.now()+(chunk.playback_recovery_epoch
      ? Math.min(1000, visualBudget) : (optionsRef.current.bufferedAudio || chunk.sequence_index === 0) ? visualBudget : 0) : 0;
    const visualAbort = visualCallback ? (continuingVisual ? visualStartAbort.current! : new AbortController()) : null;
    visualStartAbort.current = visualAbort;
    visualReply.current = visualAbort ? chunk.phone_request_id ?? null : null;
    const revision = activationRevision.current;
    pendingActivation.current = { id: chunkId, automatic };
    let player: AudioPlayerHandle | undefined;
    let acquiredLease: BufferedMediaLease | undefined;
    const configuredBufferedAudio = optionsRef.current.bufferedAudio;
    // Character samples are explicit, short previews, not reply-continuation audio.
    // A buffered replay lease requires a reply owner and would reject these samples.
    const characterPreview = chunk.id.startsWith('character-preview-');
    const progressive = automatic && Boolean(chunk.progressive_audio);
    const bufferedAudio = characterPreview || progressive ? undefined : automatic ? configuredBufferedAudio : configuredBufferedAudio?.replay;
    const download = new AbortController(); activationDownload.current = download;
    let createdAtMs = Date.now();
    let sourceUrl = '';
    let usedPreparedPlayer = false;
    try {
      if(configuredBufferedAudio&&!bufferedAudio&&!characterPreview&&!progressive)throw new Error('Buffered Replay is unavailable. Update NC Remote.');
      try {
        await optionsRef.current.onBeforePlayback?.();
      } catch {
        if (requirePlaybackTicket) throw new Error('Protected playback ownership could not be confirmed.');
        // Playback must remain available if microphone cleanup fails.
      }
      if (revision !== activationRevision.current) return;
      if (!ticketAllowed(playbackTicket, requirePlaybackTicket)) return;
      if (automatic && !automaticAllowed(chunk)) return;
      const replyAuth = automatic && (playbackTicket || progressive) && optionsRef.current.phoneReplyControls
        ? optionsRef.current.getReplyAuth?.(chunk) : null;
      const stream = replyAuth && !bufferedAudio && !progressive ? await client.getAVOutput?.() : null;
      if (revision !== activationRevision.current || !ticketAllowed(playbackTicket, requirePlaybackTicket)
          || (automatic && !automaticAllowed(chunk))) return;
      if (visualCallback && visualAbort && !stream && !bufferedAudio && !progressive) {
        await boundedVisualStart(visualCallback, chunk, visualAbort.signal, visualDeadline);
        if (revision !== activationRevision.current) return;
        if (!ticketAllowed(playbackTicket, requirePlaybackTicket)) return;
        if (automatic && !automaticAllowed(chunk)) return;
      }
      if (preparedSlot && prepared.current === preparedSlot && preparedSlot.id === chunkId
          && preparedSlot.playbackTicket === playbackTicket
          && preparedSlot.requirePlaybackTicket === requirePlaybackTicket) {
        prepared.current = null;
        preparationRevision.current++;
        setPreparedChunk(null);
        try { preparedSlot.subscription?.remove?.(); } catch { /* Already detached. */ }
        preparedSlot.subscription = undefined;
        player = preparedSlot.player;
        createdAtMs = preparedSlot.createdAtMs;
        sourceUrl = preparedSlot.sourceUrl;
        acquiredLease = preparedSlot.mediaLease;
        preparedSlot.mediaLease = undefined;
        usedPreparedPlayer = true;
      } else {
        releasePrepared();
        if (progressive) {
          if (!replyAuth || client.avHandle) throw new Error('Progressive audio owner is unavailable.');
          const {openProgressivePcmSource} = await import('../native/progressivePcm');
          const source = await openProgressivePcmSource(client,replyAuth,chunk,download.signal);
          try {
            player = createPhoneAudioPlayer({uri:source.uri}, {
              updateInterval:PLAYBACK_STATUS_INTERVAL_MS,...continuousCapturePlayerOptions(),
            },playbackTicket) as AudioPlayerHandle;
            progressiveSources.set(player,source); sourceUrl = source.uri;
          } catch (error) { source.close(); throw error; }
          if (revision !== activationRevision.current || !ticketAllowed(playbackTicket,requirePlaybackTicket)
            || !automaticAllowed(chunk)) { releasePlayer(player); return; }
        } else if (stream && replyAuth && playbackTicket) {
          player = await stream.prepare(chunk, replyAuth, playbackTicket,
            Math.round((resumePositions.current.get(chunkId) ?? 0) * 48000));
          sourceUrl = 'nc-av://native-output';
          if (revision !== activationRevision.current || !ticketAllowed(playbackTicket, requirePlaybackTicket)
              || !automaticAllowed(chunk)) { releasePlayer(player); return; }
        } else {
          const media = bufferedAudio ? await (async () => {
            acquiredLease = await bufferedAudio.acquire(chunk, download.signal);
            if (!bufferedAudio.owns(chunk, acquiredLease.uri)) throw new Error('Buffered audio authority ended.');
            return { url: acquiredLease.uri };
          })() : await resolveAudio(chunk);
          if (revision !== activationRevision.current) return;
          if (!ticketAllowed(playbackTicket, requirePlaybackTicket)) return;
          if (automatic && !automaticAllowed(chunk)) return;
          sourceUrl = media.url;
          player = await createQueuePlayer(bufferedAudio, chunk, media.url, {
            updateInterval: PLAYBACK_STATUS_INTERVAL_MS,
            ...continuousCapturePlayerOptions(),
          }, playbackTicket, download.signal);
          if(automatic&&configuredBufferedAudio?.continuousRequired
            &&(!configuredBufferedAudio.continuous||!continuousFactories.has(player)))
            throw Error('Update NC Remote for required continuous muxed metadata.');
        }
        bindReply(player, chunk, playbackTicket, automatic);
        createdAtMs = Date.now();
        void recordPhoneDebug('info', 'audio_player_created', {
          ...timingDetails(chunk, createdAtMs),
          prepared: false,
          automatic,
          buffered: Boolean(bufferedAudio),
          native_stream: Boolean(stream),
        });
      }
      if (bufferedAudio && !bufferedAudio.owns(chunk,sourceUrl)) throw new Error('Buffered audio authority ended.');
      const resumePosition = resumePositions.current.get(chunkId);
      if (resumePosition !== undefined && resumePosition > 0) {
        if (progressiveSources.has(player)) throw new Error('Progressive audio cannot resume while generating. Start a fresh reply.');
        if (bufferedFactories.has(player)) throw new Error('Muxed trial resume is unavailable. Start a fresh reply.');
        // Seek on an inaudible fresh player. Timeout destroys it: a late seek
        // must never move the replacement player's clock after it starts.
        let timer: ReturnType<typeof setTimeout> | undefined;
        try {
          if (!player.seekTo) throw new Error('Seeking unavailable');
          await Promise.race([player.seekTo(resumePosition, 0, 0), new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error('Seek timeout')), 2000);
          })]);
          if (!Number.isFinite(player.currentTime) || Math.abs(player.currentTime! - resumePosition) > 0.1) throw new Error('Seek not confirmed');
        } catch {
          if (player.ncAVPlayer) throw new Error('Streamed reply resume position was not confirmed.');
          releasePlayer(player);
          if (revision !== activationRevision.current || !ticketAllowed(playbackTicket, requirePlaybackTicket) || !automaticAllowed(chunk)) return;
          player = createPhoneAudioPlayer(sourceUrl, { updateInterval: PLAYBACK_STATUS_INTERVAL_MS, ...continuousCapturePlayerOptions() }, playbackTicket) as AudioPlayerHandle;
          bindReply(player, chunk, playbackTicket, automatic);
        } finally { if (timer) clearTimeout(timer); }
        if (revision !== activationRevision.current || !ticketAllowed(playbackTicket, requirePlaybackTicket) || !automaticAllowed(chunk)) { releasePlayer(player); return; }
        resumePositions.current.delete(chunkId);
      }
      await attachBufferedPlayer(bufferedAudio,player,chunk,playbackTicket);
      // Local video observes this exact silent player. Waiting for its pixels
      // before creating/binding the audio player would deadlock both gates.
      if (bufferedAudio && visualCallback && visualAbort) {
        await boundedVisualStart(visualCallback,chunk,visualAbort.signal,visualDeadline);
      }
      if (revision !== activationRevision.current || !ticketAllowed(playbackTicket,requirePlaybackTicket)
          || (automatic && !automaticAllowed(chunk)) || (bufferedAudio && !bufferedAudio.owns(chunk,sourceUrl))) {
        releasePlayer(player); return;
      }
      setPlayingId(chunkId);
      setError('');
      player.volume = volumeRef.current;
      const slot: PlayerSlot = {
        playbackRate: applyNarrationRate(player, chunk, optionsRef.current.narrationPace),
        mediaLease: acquiredLease,
        ownsMedia: bufferedAudio ? () => bufferedAudio.owns(chunk,sourceUrl) : undefined,
        id: chunkId,
        chunk,
        player,
        createdAtMs,
        sourceUrl,
        // Explicit character samples are local WAV files delivered over the
        // existing peer media channel. A fresh Android player may still be
        // preparing that file; playing it before READY silently does nothing.
        waitingForSource: (usedPreparedPlayer || characterPreview) && player.isLoaded !== true,
        automatic,
        playbackTicket,
        requirePlaybackTicket,
      };
      active.current = slot;
      acquiredLease = undefined;
      setCurrentChunk(chunk);
      setPositionSeconds(0);
      setIsPlaying(false);
      liveSampleBuffer.set(null);
      const continuous=continuousFactories.get(player);
      if(continuous){
        const adapter=automatic?configuredBufferedAudio?.continuous:undefined;
        if(!adapter)
          throw Error('Update NC Remote for required continuous muxed adapter.');
        slot.subscription=player.addListener?.('playbackStatusUpdate',(status)=>{
          if(status.error&&active.current===slot){setError(playbackError(slot.chunk,status.error));
            suspended.current=true;releaseActive(true);optionsRef.current.onReplyFailure?.('continuous_native_status');}
        });
        player.play();autoplaySeen.current.add(chunkId);played.current.add(chunkId);setPlayedCount(played.current.size);
        startContinuous(slot,continuous,adapter);return;
      }
      const durationMs = progressiveSources.has(player) ? 0 : Math.max(0, Number(chunk.duration_seconds || 0) * 1000);
      const hardTimeoutMs = MAX_PLAYBACK_FALLBACK_MS / (slot.playbackRate || 1);
      const playbackTimeoutMs = durationMs > 0
        ? Math.min(hardTimeoutMs, durationMs / (slot.playbackRate || 1) + PLAYBACK_FALLBACK_GRACE_MS)
        : UNKNOWN_DURATION_PLAYBACK_TIMEOUT_MS;
      const failTimeout = (timeoutError?: string) => {
        if (pausedRef.current) return;
        if (active.current !== slot) return;
        if (slot.focusInterrupted) return;
        if (progressiveSources.has(slot.player)) {
          setError('Progressive audio was interrupted. Retry the reply.');
          suspended.current = true; releaseActive(true); optionsRef.current.onReplyFailure?.('progressive_audio_timeout'); return;
        }
        connectionTrace.event('audio_timeout', {chunk_id:chunkId, reply_id:chunk.phone_request_id,
          position_seconds:Number(slot.lastStatus?.currentTime || 0), loaded:Number(Boolean(slot.lastStatus?.isLoaded)),
          paused:Number(pausedRef.current), status_age_ms:slot.lastStatusAtMs === undefined ? undefined : Math.max(0,performance.now()-slot.lastStatusAtMs),
          native_error_code:slot.lastStatus?.nativePlayerErrorCode,
          play_when_ready:typeof slot.lastStatus?.playWhenReady==='boolean' ? Number(slot.lastStatus.playWhenReady) : undefined,
          focus_interrupted:Number(Boolean(slot.lastStatus?.focusInterrupted)),
          queued:explicitQueue.current.length, retained:retainedChunks.current.size}, true);
        if (suspendForAVDisconnect()) return;
        if (suspendManualReply('playback_timeout')) return;
        const message = slot.playbackStartedLogged
          ? 'Audio playback did not finish.'
          : 'Audio did not start. Open audio controls to retry.';
        setError(message);
        if (characterPreview) optionsRef.current.onCharacterPreviewError?.(message);
        void recordPhoneDebug('error', 'audio_playback_failed', {
          ...timingDetails(chunk, Date.now()),
          error: timeoutError || (slot.playbackStartedLogged ? 'playback completion timeout' : 'playback start timeout'),
          is_loaded: Boolean(slot.lastStatus?.isLoaded),
          position_seconds: Number(slot.lastStatus?.currentTime || 0),
          playback_state: slot.lastStatus?.playbackState || 'unknown',
          time_control_status: slot.lastStatus?.timeControlStatus || 'unknown',
          waiting_reason: slot.lastStatus?.reasonForWaitingToPlay || 'unknown',
          is_buffering: Boolean(slot.lastStatus?.isBuffering),
           native_error_code: slot.lastStatus?.nativePlayerErrorCode,
           play_when_ready: slot.lastStatus?.playWhenReady,
           focus_interrupted: Boolean(slot.lastStatus?.focusInterrupted),
          prepared: usedPreparedPlayer,
        });
        if (!slot.playbackStartedLogged) void probeAudioMedia(chunk, slot.sourceUrl);
        releaseActive(true, false, 'playback_timeout');
        if (retainedChunks.current.has(chunkId)) { suspended.current = true; optionsRef.current.onReplyFailure?.('retained_playback_timeout'); return; }
        settleChunk(chunk);
        setTimeout(() => playNextRef.current(), 0);
      };
      const armTimeout = (milliseconds: number) => {
        if (slot.fallbackTimer) clearTimeout(slot.fallbackTimer);
        slot.fallbackTimer = setTimeout(() => {
          failTimeout();
        }, milliseconds);
      };
      slot.resumeTimers = () => {
        armTimeout(playbackTimeoutMs);
        if (slot.hardFallbackTimer) clearTimeout(slot.hardFallbackTimer);
        slot.hardFallbackTimer = setTimeout(() => failTimeout('playback hard timeout'), hardTimeoutMs);
      };
      armTimeout(PLAYBACK_START_TIMEOUT_MS);
      slot.subscription = player.addListener?.('playbackStatusUpdate', (status: AudioStatus) => {
        status = {...status, error: nativePlaybackError(status)};
        const current = active.current;
        if (!current || current.id !== chunkId || current.player !== player) {
          return;
        }
        if (status.error && suspendForAVDisconnect(status.nativeFailureReason)) return;
        if (!ticketAllowed(current.playbackTicket, current.requirePlaybackTicket) || current.ownsMedia?.() === false) {
          if ((client.avTransportClosed || current.ownsMedia?.() === false) && suspendManualReply(client.avTransportClosed ? 'peer_interrupted' : 'media_owner_lost')) return;
          releaseActive(true);
          return;
        }
        if (current.automatic && !automaticAllowed(current.chunk)) { releaseActive(true); return; }
        if (current.boundaryPause && !status.error) return;
        if (current.waitingForSource && status.isLoaded && !pausedRef.current) {
          if (current.automatic && !automaticAllowed(current.chunk)) {
            releaseActive(true);
            return;
          }
          current.waitingForSource = false;
          try {
            current.player.play();
          } catch (exc) {
            status = { ...status, error: exc instanceof Error ? exc.message : 'Audio playback failed.' };
          }
        }
        current.lastStatus = status;
        current.lastStatusAtMs = performance.now();
        const diagnosticState = `${chunkId}:${Boolean(status.playing)}:${Boolean(status.isLoaded)}:${Boolean(status.error)}:${status.nativePlayerErrorCode ?? ''}:${status.playWhenReady ?? ''}`;
        const diagnosticNow = performance.now();
        if (diagnosticSample.current.state !== diagnosticState || diagnosticNow-diagnosticSample.current.at >= 5000) {
          diagnosticSample.current = {at:diagnosticNow, state:diagnosticState};
          connectionTrace.event('audio_progress', {chunk_id:chunkId, reply_id:chunk.phone_request_id,
            position_seconds:Number(status.currentTime || 0), playing:Number(Boolean(status.playing)),
            loaded:Number(Boolean(status.isLoaded)), paused:Number(pausedRef.current),
             native_error_code:status.nativePlayerErrorCode,
             play_when_ready:typeof status.playWhenReady==='boolean' ? Number(status.playWhenReady) : undefined,
             focus_interrupted:Number(Boolean(status.focusInterrupted)),
            queued:explicitQueue.current.length, retained:retainedChunks.current.size,
            state:status.playbackState, reason:status.error ? 'player_error' : 'status'}, Boolean(status.error));
        }
        setPositionSeconds(Math.max(0, Number(status.currentTime || 0)));
        setIsPlaying(Boolean(status.playing) && !pausedRef.current);
        if (status.focusInterrupted && !status.error && !status.didJustFinish && !pausedRef.current) {
          if (!current.focusInterrupted) current.focusWaitTimer = setTimeout(() => {
            if (active.current !== current || !current.focusInterrupted || pausedRef.current) return;
            connectionTrace.event('audio_focus_wait', {chunk_id:chunkId, reply_id:chunk.phone_request_id,
              position_seconds:Number(current.lastStatus?.currentTime || 0), duration_ms:30000,
              reason:'native_focus_not_returned', focus_interrupted:1});
          }, 30000);
          if (!current.focusInterrupted) connectionTrace.event('audio_focus_interrupted', {
            chunk_id:chunkId, reply_id:chunk.phone_request_id, position_seconds:Number(status.currentTime || 0),
            reason:'native_focus_loss', focus_interrupted:1});
          current.focusInterrupted = true;
          if (current.fallbackTimer) clearTimeout(current.fallbackTimer);
          if (current.hardFallbackTimer) clearTimeout(current.hardFallbackTimer);
          return;
        }
        if (current.focusInterrupted && (status.focusInterrupted === false || status.playing || status.error || status.didJustFinish)) {
          if (current.focusWaitTimer) clearTimeout(current.focusWaitTimer);
          current.focusInterrupted = false;
          connectionTrace.event('audio_focus_recovered', {chunk_id:chunkId, reply_id:chunk.phone_request_id,
            playing:Number(Boolean(status.playing)), reason:status.error ? 'player_error' : 'native_focus_cleared'});
          current.resumeTimers?.();
        }
        if (status.playing && !current.playbackStartedLogged) {
          current.playbackStartedLogged = true;
          if (current.automatic && chunk.phone_request_id && chunk.sequence_index === 0) {
            try { optionsRef.current.onAssistantPlaybackStarted?.(chunk.phone_request_id); }
            catch { /* Optional background scene cues cannot affect speech. */ }
          }
          if (current.automatic && optionsRef.current.phoneReplyControls && chunk.phone_request_id) {
            const record = replyRecord(chunk.phone_request_id);
            if (record && !record.started.includes(chunk.id)) {
              if (record.started.length >= 2048) { optionsRef.current.onReplyFailure?.('started_chunk_capacity'); releaseActive(true); return; }
              record.started.push(chunk.id); ongoingReply.current = chunk.phone_request_id;
            }
          }
          // Android's PCM sampler needs the session created by actual playback.
          setActivePlayer(current.player as AudioPlayer);
          armTimeout(playbackTimeoutMs);
          if (current.hardFallbackTimer) clearTimeout(current.hardFallbackTimer);
          current.hardFallbackTimer = setTimeout(() => failTimeout('playback hard timeout'), hardTimeoutMs);
          const startedAtMs = Date.now();
          void recordPhoneDebug('info', 'audio_playback_started', {
            ...timingDetails(chunk, startedAtMs),
            player_create_to_start_ms: Math.max(0, startedAtMs - createdAtMs),
            prepared: usedPreparedPlayer,
            playback_rate: slot.playbackRate || 1,
          });
        }
        const position = Number(status.currentTime);
        if (!pausedRef.current && current.playbackStartedLogged && !status.didJustFinish && !status.error && Number.isFinite(position)) {
          if (current.lastPlaybackPositionSeconds === undefined) {
            current.lastPlaybackPositionSeconds = position;
          } else if (position > current.lastPlaybackPositionSeconds) {
            current.lastPlaybackPositionSeconds = position;
            armTimeout(playbackTimeoutMs);
          }
        }
        if (!status.didJustFinish && !status.error) {
          return;
        }
        if (status.error && progressiveSources.has(player)) {
          setError('Progressive audio was interrupted. Retry the reply.');
          suspended.current = true; releaseActive(true); optionsRef.current.onReplyFailure?.('progressive_audio_failed'); return;
        }
        const finishedAtMs = Date.now();
        if (status.error && suspendManualReply('player_error')) return;
        if (status.error) {
          const message = playbackError(chunk, status.error);
          setError(message);
          if (chunk.id.startsWith('character-preview-')) optionsRef.current.onCharacterPreviewError?.(message);
          void recordPhoneDebug('error', 'audio_playback_failed', {
            ...timingDetails(chunk, finishedAtMs),
            error: message,
             native_error_code: status.nativePlayerErrorCode,
            prepared: usedPreparedPlayer,
          });
        } else {
          if(current.automatic&&current.playbackStartedLogged){
            try{optionsRef.current.onChunkDrained?.(chunk,player as AudioPlayer);}
            catch{void recordPhoneDebug('warning','audio_drain_observer_failed',{}).catch(()=>undefined);}
          }
          void recordPhoneDebug('info', 'audio_playback_finished', {
            ...timingDetails(chunk, finishedAtMs),
            prepared: usedPreparedPlayer,
          });
        }
        const complete = () => {
          if (active.current !== current) return;
          if (!ticketAllowed(current.playbackTicket, current.requirePlaybackTicket)
              || current.ownsMedia?.() === false || (current.automatic && !automaticAllowed(current.chunk))) {
            releaseActive(true); return;
          }
          // The completed slot owns the breath too: incoming snapshots cannot
          // jump ahead, and Stop/Skip/identity changes cancel through releaseActive.
          releaseActive(true, !status.error && current.automatic, status.error ? 'player_error' : 'completed');
          if (status.error && retainedChunks.current.has(chunkId)) { suspended.current = true; optionsRef.current.onReplyFailure?.('retained_playback_status'); return; }
          if (!status.error) {
            heard.current.add(chunkId);
            setLastCompletedChunk(previous => ({ id: chunkId, revision: (previous?.revision ?? 0) + 1 }));
          }
          settleChunk(chunk);
          setTimeout(() => playNextRef.current(), 0);
        };
        const breathMs = !status.error && !player.ncAVPlayer && !progressiveSources.has(player) && !bufferedFactories.has(player) && !chunk.id.startsWith('character-preview-')
          ? narrationPauseMs(optionsRef.current.narrationPace, current.chunk.text) : 0;
        if (breathMs > 0) {
          if (current.fallbackTimer) clearTimeout(current.fallbackTimer);
          if (current.hardFallbackTimer) clearTimeout(current.hardFallbackTimer);
          current.boundaryPause = {remainingMs:breathMs,deadlineMs:0,complete};
          resumeBoundaryPause(current);
        } else complete();
      });
      // Expo's download-first player has a null source until replacement finishes.
      if (!ticketAllowed(playbackTicket, requirePlaybackTicket) || (automatic && !automaticAllowed(chunk))) {
        releaseActive(true);
        return;
      }
      progressiveSources.get(player)?.start(() => Number(slot.lastStatus?.currentTime ?? player?.currentTime ?? 0), () => {
        if (active.current !== slot) return;
        setError('Progressive audio was interrupted. Retry the reply.');
        suspended.current = true; releaseActive(true); optionsRef.current.onReplyFailure?.('progressive_audio_failed');
      });
      if (!slot.waitingForSource && !pausedRef.current) player.play();
      autoplaySeen.current.add(chunkId);
      played.current.add(chunkId);
      setPlayedCount(played.current.size);
      prepareNextRef.current();
    } catch (exc) {
      if (revision !== activationRevision.current) return;
      if (suspendForAVDisconnect()) return;
      if (automatic && automaticAllowed(chunk)) autoplaySeen.current.add(chunkId);
      if (player && active.current?.player !== player) releasePlayer(player);
      releaseActive(true);
      const message = playbackError(chunk, exc);
      setError(message);
      if (progressive) {
        suspended.current = true; optionsRef.current.onReplyFailure?.('progressive_audio_failed'); return;
      }
      if (chunk.id.startsWith('character-preview-')) optionsRef.current.onCharacterPreviewError?.(message);
      void recordPhoneDebug('error', 'audio_playback_failed', {
        ...timingDetails(chunk, Date.now()),
        error: message,
        prepared: usedPreparedPlayer,
      });
      if (retainedChunks.current.has(chunkId)) { suspended.current = true; optionsRef.current.onReplyFailure?.('retained_activation_failed'); return; }
      settleChunk(chunk);
      setTimeout(() => playNextRef.current(), 0);
    } finally {
      // Includes late resolution after Stop and failures before native attach.
      if (acquiredLease) {
        await releasePlayer(player);
        await acquiredLease.release();
      }
      if (activationDownload.current === download) activationDownload.current = null;
      if (revision === activationRevision.current) pendingActivation.current = null;
    }
  }, [client, resolveAudio, releaseActive, releasePrepared]);

  const prepareNext = useCallback(async () => {
    if(optionsRef.current.bufferedAudio?.deferNativePreparation){releasePrepared();return;}
    const current = active.current;
    if (current && progressiveSources.has(current.player)) { releasePrepared(); return; }
    const playbackTicket = optionsRef.current.playbackTicket ?? null;
    const requirePlaybackTicket = optionsRef.current.requirePlaybackTicket === true;
    if (pausedRef.current || suspended.current || !enabledRef.current || !current || !current.automatic
      || (optionsRef.current.phoneReplyControls && optionsRef.current.transportConnected === false)
      || !ticketAllowed(playbackTicket, requirePlaybackTicket)
      || (optionsRef.current.initialSnapshot !== undefined && !initialSnapshotConsumed.current)) {
      releasePrepared();
      return;
    }
    const next = nextUnseenAudioChunk(
      chunksRef.current.filter(preparationAllowed),
      autoplaySeen.current,
      current.id,
    );
    if (!next) {
      releasePrepared();
      return;
    }
    if (next.progressive_audio) { releasePrepared(); return; }
    const busyRetry=busyPreparation.current;
    if(busyRetry?.id===next.id&&busyRetry.active===current&&Date.now()<busyRetry.until)return;
    // Snapshot polling must not cancel/re-admit the same async preparation.
    // RTP has a bounded active+next queue; duplicate admission retires speech.
    if (prepared.current?.id === next.id || pendingPreparation.current === next.id) {
      return;
    }
    releasePrepared();
    const revision = preparationRevision.current;
    pendingPreparation.current = next.id;
    const retainedPreparation = Boolean(current.player.ncAVPlayer || optionsRef.current.bufferedAudio);
    pendingAVPreparation.current = retainedPreparation ? next.id : null;
    // Only genuine completion can hand this in-flight native successor on to
    // an empty active slot. Stop/replacement still invalidates the revision.
    const predecessorAvailable = () => active.current === current
      || (retainedPreparation && !active.current && heard.current.has(current.id));
    let pendingPlayer: AudioPlayerHandle | undefined;
    let acquiredLease: BufferedMediaLease | undefined;
    const bufferedAudio = optionsRef.current.bufferedAudio;
    const download = new AbortController(); preparationDownload.current = download;
    try {
      const replyAuth = playbackTicket && optionsRef.current.phoneReplyControls
        ? optionsRef.current.getReplyAuth?.(next) : null;
      const stream = replyAuth && !bufferedAudio ? await client.getAVOutput?.() : null;
      const media = stream ? { url: 'nc-av://native-output' } : bufferedAudio ? await (async () => {
        acquiredLease = await bufferedAudio.acquire(next, download.signal);
        if (!bufferedAudio.owns(next, acquiredLease.uri)) throw new Error('Buffered audio authority ended.');
        return { url: acquiredLease.uri };
      })() : await resolveAudio(next);
      if (revision !== preparationRevision.current || !enabledRef.current || !predecessorAvailable() || prepared.current) return;
      if (!ticketAllowed(playbackTicket, requirePlaybackTicket)) return;
      if (!preparationAllowed(next)) return;
      const createdAtMs = Date.now();
      const player: AudioPlayerHandle = stream && replyAuth && playbackTicket
        ? await stream.prepare(next, replyAuth, playbackTicket)
        : await createQueuePlayer(bufferedAudio, next, media.url, {
        updateInterval: PLAYBACK_STATUS_INTERVAL_MS,
        // Phone reply binding captures the exact nonnil initial item. Expo's
        // download-first factory installs its item later through replace.
        downloadFirst: !(playbackTicket && optionsRef.current.phoneReplyControls && next.phone_request_id),
        ...continuousCapturePlayerOptions(),
      }, playbackTicket, download.signal);
      pendingPlayer = player;
      if (revision !== preparationRevision.current || !enabledRef.current || !predecessorAvailable() || prepared.current
          || !ticketAllowed(playbackTicket, requirePlaybackTicket) || !preparationAllowed(next)) { releasePlayer(player); return; }
      bindReply(player, next, playbackTicket, true);
      await attachBufferedPlayer(bufferedAudio,player,next,playbackTicket);
      if (revision !== preparationRevision.current || !enabledRef.current || !predecessorAvailable() || prepared.current
          || !ticketAllowed(playbackTicket,requirePlaybackTicket) || !preparationAllowed(next)
          || (bufferedAudio && !bufferedAudio.owns(next,media.url))) { releasePlayer(player); return; }
      player.volume = volumeRef.current;
      const slot: PlayerSlot = {
        mediaLease: acquiredLease,
        ownsMedia: bufferedAudio ? () => bufferedAudio.owns(next,media.url) : undefined,
        id: next.id,
        chunk: next,
        player,
        createdAtMs,
        sourceUrl: media.url,
        automatic: true,
        playbackTicket,
        requirePlaybackTicket,
      };
      prepared.current = slot;
      if(busyPreparation.current?.timer)clearTimeout(busyPreparation.current.timer);
      busyPreparation.current=null;
      acquiredLease = undefined;
      setPreparedChunk(next);
      void recordPhoneDebug('info', 'audio_player_created', {
        ...timingDetails(next, createdAtMs),
        prepared: true,
      });
      slot.subscription = player.addListener?.('playbackStatusUpdate', (status: AudioStatus) => {
        status = {...status, error: nativePlaybackError(status)};
        const currentPrepared = prepared.current;
        if (!currentPrepared || currentPrepared.id !== next.id || currentPrepared.player !== player) {
          return;
        }
        if (status.error && suspendForAVDisconnect(status.nativeFailureReason)) return;
        if (!ticketAllowed(currentPrepared.playbackTicket, currentPrepared.requirePlaybackTicket)
            || !preparationAllowed(currentPrepared.chunk) || currentPrepared.ownsMedia?.() === false) {
          releasePrepared();
          return;
        }
        if (status.isLoaded && !currentPrepared.preparedLogged) {
          currentPrepared.preparedLogged = true;
          const preparedAtMs = Date.now();
          void recordPhoneDebug('info', 'audio_player_prepared', {
            ...timingDetails(next, preparedAtMs),
            prepare_ms: Math.max(0, preparedAtMs - createdAtMs),
          });
        }
        if (status.error) {
          void recordPhoneDebug('error', 'audio_playback_failed', {
            ...timingDetails(next, Date.now()),
            error: playbackError(next, status.error),
            phase: 'prepare',
          });
          releasePrepared();
        }
      });
      // Native active+next output owns the boundary clock. Waiting for JS to
      // promote the next player could discard its first RTP samples.
      if (player.ncAVPlayer) player.play();
    } catch (exc) {
      if (pendingPlayer && prepared.current?.player !== pendingPlayer) releasePlayer(pendingPlayer);
      if (revision !== preparationRevision.current) return;
      if (suspendForAVDisconnect()) return;
      if (optionsRef.current.phoneReplyControls && optionsRef.current.transportConnected === false) {
        releasePrepared();
        return;
      }
      if(exc instanceof Error&&exc.message==='Internet peer is busy or disconnected.'&&active.current===current){
        const previous=busyPreparation.current;
        const failures=previous?.id===next.id&&previous.active===current?previous.failures+1:1;
        const delay=Math.min(4000,250*2**Math.min(failures-1,4));
        if(previous?.timer)clearTimeout(previous.timer);
        const retry={id:next.id,active:current,until:Date.now()+delay,failures,timer:null as ReturnType<typeof setTimeout>|null};
        busyPreparation.current=retry;
        retry.timer=setTimeout(()=>{
          if(busyPreparation.current!==retry)return;
          retry.timer=null;
          if(active.current===current)prepareNextRef.current();
        },delay+5);
        releasePrepared();
        return;
      }
      const failedHandoff = retainedPreparation && !active.current && heard.current.has(current.id);
      releasePrepared();
      void recordPhoneDebug('error', 'audio_playback_failed', {
        ...timingDetails(next, Date.now()),
        error: playbackError(next, exc),
        phase: 'prepare',
      });
      if (failedHandoff && retainedChunks.current.has(next.id)) {
        suspended.current = true;
        setError(playbackError(next, exc));
        optionsRef.current.onReplyFailure?.('retained_handoff_failed');
      }
    } finally {
      if (acquiredLease) {
        await releasePlayer(pendingPlayer);
        await acquiredLease.release();
      }
      if (preparationDownload.current === download) preparationDownload.current = null;
      if (revision === preparationRevision.current) {
        pendingPreparation.current = null;
        pendingAVPreparation.current = null;
        if (retainedPreparation && prepared.current && !active.current) playNextRef.current();
      }
    }
  }, [client, resolveAudio, releasePrepared]);

  const playNext = useCallback(() => {
    if (pausedRef.current) return;
    if (!active.current && !pendingActivation.current && explicitQueue.current.length) {
      void activateChunk(explicitQueue.current.shift()!, null, false);
      return;
    }
    if (suspended.current || !enabledRef.current || active.current || pendingActivation.current || pendingAVPreparation.current
      || (optionsRef.current.phoneReplyControls && optionsRef.current.transportConnected === false)
      || (optionsRef.current.initialSnapshot !== undefined && !initialSnapshotConsumed.current)) {
      return;
    }
    const preparedSlot = prepared.current;
    if (
      preparedSlot
      && !autoplaySeen.current.has(preparedSlot.id)
      && chunksRef.current.some((chunk) => chunk.id === preparedSlot.id)
    ) {
      void activateChunk(preparedSlot.chunk, preparedSlot);
      return;
    }
    if (preparedSlot) {
      releasePrepared();
    }
    const next = nextUnseenAudioChunk(chunksRef.current.filter(automaticAllowed), autoplaySeen.current);
    if (next) {
      void activateChunk(next);
    }
  }, [activateChunk, releasePrepared]);

  playNextRef.current = playNext;
  prepareNextRef.current = prepareNext;

  const playNow = useCallback(async (chunk: AudioChunk) => {
    if (chunk.progressive_audio) throw new Error('This reply is still generating. Replay is available when it finishes.');
    explicitQueue.current = []; pausedRef.current = false; setPaused(false);
    const preparedSlot = prepared.current?.id === chunk.id ? prepared.current : null;
    await activateChunk(chunk, preparedSlot, false);
  }, [activateChunk]);

  useEffect(() => () => {
    // Cancel pending resolutions and dispose players authorized with old credentials.
    if(busyPreparation.current?.timer)clearTimeout(busyPreparation.current.timer);
    busyPreparation.current=null;
    explicitQueue.current = [];
    suspendManualReply('connection_changed');
    releaseActive(true);
    releasePrepared();
  }, [mediaResolver, releaseActive, releasePrepared]);

  useEffect(() => {
    // Ownership replacement is a cancellation boundary, including explicit
    // playback. A policy-only revision below still leaves rejected work pending.
    explicitQueue.current = [];
    for (const id of [pendingActivation.current?.id, pendingPreparation.current, active.current?.id, prepared.current?.id]) {
      if (id) autoplaySeen.current.add(id);
    }
    releaseActive(true);
    releasePrepared();
  }, [options.playbackTicket ?? null, options.requirePlaybackTicket === true, releaseActive, releasePrepared]);

  useEffect(() => {
    releaseActive(true);
    releasePrepared();
    played.current = audioHistoryAfterBoundary(played.current, 'connection_changed');
    const identity = optionsRef.current.continuationScopeKey || client.identityKey;
    const identityChanged = historyIdentity.current !== identity;
    if (identityChanged) {
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      setManualRecovery(null);
      retainedChunks.current.clear(); continuation.current = null; suspended.current = false; resumePositions.current.clear(); heard.current.clear();
      historyIdentity.current = identity;
      initialSnapshotConsumed.current = false;
      replyRecords.current.clear(); ongoingReply.current = null; replyCapacityClosed.current = false;
    }
    // A temporary off/HQ transition must not forget the backend chunks consumed
    // during this session. Local/native queues retain their existing reset policy.
    if (identityChanged || optionsRef.current.initialSnapshot === undefined) {
      autoplaySeen.current = audioHistoryAfterBoundary(autoplaySeen.current, 'connection_changed');
    }
    setPlayedCount(0);
    setError('');
  }, [client.identityKey, options.sourceKey, options.continuationScopeKey, releaseActive, releasePrepared]);

  useEffect(() => {
    if (options.initialSnapshot !== undefined && !initialSnapshotConsumed.current) {
      if (options.initialSnapshot === null) return;
      for (const item of options.initialSnapshot) {
        if (item.id) autoplaySeen.current.add(item.id);
      }
      initialSnapshotConsumed.current = true;
    }
    if (!chunks.length) {
      // Explicit output is independent of snapshots; completed ordered carriers retain their visual lifetime.
      if ((pendingActivation.current?.automatic || active.current?.automatic) && !finishedVisualCarrier(active.current)) releaseActive(true);
      releasePrepared();
      played.current = audioHistoryAfterBoundary(played.current, 'empty_snapshot');
      autoplaySeen.current = audioHistoryAfterBoundary(autoplaySeen.current, 'empty_snapshot');
      setPlayedCount(played.current.size);
      setError('');
      return;
    }
    const continuous=active.current?.continuous;
    if(continuous){
      const identity=(c:AudioChunk)=>JSON.stringify([c.id,c.phone_request_id,c.sequence_index,c.url_path,c.playback_recovery_epoch]);
      if([...continuous.entries.values()].some(entry=>{
        if(entry.completed)return false;
        const current=chunks.find(c=>c.id===entry.chunk.id);
        return !current||identity(current)!==identity(entry.chunk)||optionsRef.current.allowAutomaticChunk?.(entry.chunk)===false
          ||replyRecords.current.get(entry.chunk.phone_request_id??'')?.suppressed;
      }))releaseActive(true);
    }
    const updatedActive = refreshAudioChunkMetadata(
      active.current?.chunk ?? null,
      chunks,
    );
    if (updatedActive && active.current && active.current.chunk !== updatedActive) {
      // The active player keeps its admitted PCM route when final metadata
      // removes the flag for future Replay. Its reading cursor stays monotonic.
      active.current.chunk = progressiveSources.has(active.current.player)
        ? {...updatedActive,progressive_audio:active.current.chunk.progressive_audio,
          ...(updatedActive.progressive_audio ? {duration_seconds:Math.max(1,(updatedActive.text?.length || 0)/14)} : {})}
        : updatedActive;
      if(!active.current.continuous?.speechDeparture)setCurrentChunk(active.current.chunk);
    }
    const updatedPrepared = refreshAudioChunkMetadata(
      prepared.current?.chunk ?? null,
      chunks,
    );
    if (updatedPrepared && prepared.current && prepared.current.chunk !== updatedPrepared) {
      prepared.current.chunk = updatedPrepared;
      setPreparedChunk(updatedPrepared);
    }
    const pendingChunk = pendingActivation.current
      ? chunks.find((chunk) => chunk.id === pendingActivation.current?.id)
      : undefined;
    if (pendingActivation.current?.automatic && pendingChunk && !automaticAllowed(pendingChunk)) {
      releaseActive(true);
    }
    if (active.current?.automatic && !automaticAllowed(active.current.chunk)&&!finishedVisualCarrier(active.current)) {
      releaseActive(true);
    }
    if (prepared.current?.automatic && !preparationAllowed(prepared.current.chunk)) {
      releasePrepared();
    }
    const validIds = new Set(chunks.map((chunk) => chunk.id).filter(Boolean));
    if (pendingActivation.current?.automatic && !validIds.has(pendingActivation.current.id)) {
      releaseActive(true);
    }
    if (active.current?.automatic && !validIds.has(active.current.id) && !finishedVisualCarrier(active.current)) {
      releaseActive(true);
    }
    if (prepared.current && !validIds.has(prepared.current.id)) {
      releasePrepared();
    }
    if (!enabled) {
      if (pendingActivation.current?.automatic) releaseActive(true);
      releasePrepared();
      for (const item of chunks) {
        if (item.id) {
          autoplaySeen.current.add(item.id);
        }
      }
      return;
    }
    if (active.current) {
      prepareNextRef.current();
    } else {
      playNextRef.current();
    }
  }, [chunks, enabled, client.identityKey, mediaResolver, options.sourceKey, options.initialSnapshot,
    options.automaticPolicyRevision, options.playbackTicket, options.requirePlaybackTicket,
    releaseActive, releasePrepared]);

  const skipReply = (requestId: string) => {
    pausedRef.current = false; setPaused(false);
    if (continuation.current?.replies.some(reply => reply.requestId === requestId)) {
      continuation.current = null; suspended.current = false; setManualRecovery(null);
    }
    const record = replyRecord(requestId);
    if (record) record.suppressed = true;
    if (ongoingReply.current === requestId) ongoingReply.current = null;
    const ticket = optionsRef.current.playbackTicket;
    if (ticket && optionsRef.current.phoneReplyControls && skipPhoneReplyAudio(ticket, requestId) && record) record.bound = true;
    const matches = (id: string | null | undefined) => chunksRef.current.some(c => c.id === id && c.phone_request_id === requestId);
    if (active.current?.chunk.phone_request_id === requestId || matches(pendingActivation.current?.id)) releaseActive(true);
    if (prepared.current?.chunk.phone_request_id === requestId || matches(pendingPreparation.current)) releasePrepared();
    setTimeout(() => playNextRef.current(), 0);
  };
  const explicitPlayback = active.current?.automatic === false && active.current.requirePlaybackTicket ? active.current : null;
  const activeReplyId = (explicitPlayback ? null : currentChunk?.phone_request_id) ?? preparedChunk?.phone_request_id
    ?? options.ownedReplyIds?.find(id => !replyRecords.current.get(id)?.suppressed && !replyRecords.current.get(id)?.finished) ?? null;
  return {
    paused: paused || Boolean(manualRecovery),
    pause: () => {
      const slot = active.current;
      if (pausedRef.current || manualRecovery) return;
      if (slot?.continuous || (slot && bufferedFactories.has(slot.player))) throw new Error('Ordered playback pause is unavailable for this session.');
      if (slot?.player.ncAVPlayer) {
        if (!suspendManualReply('user_pause')) throw new Error('Stream pause is unavailable for this session.');
        setError('Response paused. Tap Play to continue from this position.');
      } else if (slot) {
        if (!slot.player.pause) throw new Error('This player does not support pause.');
        slot.player.pause();
        if (slot.focusWaitTimer) clearTimeout(slot.focusWaitTimer);
        if (slot.fallbackTimer) clearTimeout(slot.fallbackTimer);
        if (slot.hardFallbackTimer) clearTimeout(slot.hardFallbackTimer);
        if (slot.boundaryPause) {
          const breath = slot.boundaryPause;
          if (breath.timer) clearTimeout(breath.timer);
          breath.timer = undefined;
          breath.remainingMs = Math.max(0, breath.deadlineMs - performance.now());
        }
      }
      pausedRef.current = true; setPaused(true); setIsPlaying(false);
    },
    resume: async () => {
      if (manualRecovery) throw new Error('Restore the interrupted response before resuming.');
      const slot = active.current;
      if (slot && !ticketAllowed(slot.playbackTicket, slot.requirePlaybackTicket)) throw new Error('Playback ownership changed.');
      pausedRef.current = false; setPaused(false);
      if (slot?.boundaryPause) resumeBoundaryPause(slot);
      else if (slot) { slot.player.play(); slot.resumeTimers?.(); }
      else playNextRef.current();
    },
    playSequence: async items => {
      if (!items.length) throw new Error('No retained audio to replay.');
      if (items.some(item=>item.progressive_audio)) throw new Error('This reply is still generating. Replay is available when it finishes.');
      releaseActive(true); releasePrepared();
      pausedRef.current = false; setPaused(false);
      explicitQueue.current = items.slice(1);
      await activateChunk(items[0]!, null, false);
    },
    manualRecovery,
    suspendForPeerInterruption: () => {
      // Only an already playing, owned reply can be resumed from its exact
      // position. Explicit pauses and previews remain under user control.
      if (pausedRef.current || manualRecovery || !active.current?.automatic) return null;
      return suspendManualReply('peer_interrupted') ? continuation.current : null;
    },
    completedReplySequence: id => {
      const items = chunksRef.current.filter(c => c.phone_request_id === id);
      let sequence = -1;
      while (items.some(c => c.sequence_index === sequence + 1 && heard.current.has(c.id))) sequence++;
      return sequence;
    },
    appendReplyMedia: (id, items) => {
      if (items.length > 2048 || items.some((c,i) => c.phone_request_id !== id || c.sequence_index !== i)
        || new Set(items.map(c => c.id)).size !== items.length) throw new Error('Incomplete reply audio manifest.');
      let changed = false;
      for (const item of items) {
        const old = retainedChunks.current.get(item.id);
        if (!old) { retainedChunks.current.set(item.id, item); changed = true; }
      }
      if (changed) reviseRetained(value => value + 1);
    },
    recoveryEpoch,
    suspendReplyPlayback: checkpoint => {
      if (continuation.current && checkpoint.recoveryEpoch < continuation.current.recoveryEpoch) return;
      continuation.current = checkpoint; suspended.current = true;
      mediaResolver.clear();
      releaseActive(true); releasePrepared();
      setRecoveryEpoch(checkpoint.recoveryEpoch);
    },
    cancelReplyContinuation: () => {
      setManualRecovery(null);
      continuation.current = null; suspended.current = false;
      retainedChunks.current.clear(); resumePositions.current.clear();
      releaseActive(true); releasePrepared(); reviseRetained(value => value + 1);
    },
    restoreReplyPlayback: async (checkpoint, manifest, epoch) => {
      if (continuation.current !== checkpoint || checkpoint.recoveryEpoch !== epoch || !suspended.current) return false;
      if (manifest.some(chunk=>chunk.progressive_audio)
        || checkpoint.replies.some(reply=>replyRecords.current.get(reply.requestId)?.progressive)) return false;
      const admitted = optionsRef.current.manualContinuationEnabled
        ? optionsRef.current.ownedReplyIds ?? [] : optionsRef.current.nativeAdmittedReplyIds ?? [];
      if (checkpoint.replies.some(r => !admitted.includes(r.requestId) || replyRecords.current.get(r.requestId)?.suppressed)) return false;
      const ids = new Set<string>();
      for (const reply of checkpoint.replies) {
        const items = manifest.filter(c => c.phone_request_id === reply.requestId);
        if (items.length > 2048 || items.some((c, i) => c.sequence_index !== i || ids.has(c.id) || !ids.add(c.id))) return false;
        if (reply.completedChunkIds.some(id => !items.some(c => c.id === id)) || (reply.activeChunkId && !items.some(c => c.id === reply.activeChunkId))) return false;
      }
      for (const reply of checkpoint.replies) {
        const record = replyRecord(reply.requestId);
        if (!record) return false;
        optionsRef.current.onReplyMediaRestored?.(reply.requestId, manifest
          .filter(item => item.phone_request_id === reply.requestId && !reply.completedChunkIds.includes(item.id))
          .map(item => ({ ...item, playback_recovery_epoch: epoch })));
        record.settled.clear();
        for (const item of manifest.filter(c => c.phone_request_id === reply.requestId)) {
          retainedChunks.current.set(item.id, { ...item, playback_recovery_epoch: epoch });
          if (reply.completedChunkIds.includes(item.id)) {
            heard.current.add(item.id); autoplaySeen.current.add(item.id); record.settled.add(item.sequence_index!);
          } else { autoplaySeen.current.delete(item.id); heard.current.delete(item.id); }
        }
        if (reply.activeChunkId && reply.positionSeconds !== null && Number.isFinite(reply.positionSeconds) && reply.positionSeconds >= 0)
          resumePositions.current.set(reply.activeChunkId, reply.positionSeconds);
      }
      chunksRef.current = [...retainedChunks.current.values()];
      suspended.current = false; reviseRetained(value => value + 1);
      pausedRef.current = false; setPaused(false);
      setManualRecovery(null); setError('');
      const next = nextUnseenAudioChunk(chunksRef.current.filter(automaticAllowed), autoplaySeen.current);
      if (next) await activateChunk(next);
      return continuation.current === checkpoint && !suspended.current
        && !checkpoint.replies.some(r => replyRecords.current.get(r.requestId)?.suppressed);
    },
    activeReplyId,
    hasReplyAudio: Boolean(activeReplyId),
    skipReply,
    // Capture this exact local slot so a stale UI action cannot stop a later
    // Replay or automatic reply. Historical request metadata is not ownership.
    explicitPlaybackPending:Boolean(explicitPlayback || (pendingActivation.current && !pendingActivation.current.automatic) || explicitQueue.current.length),
    stopExplicitPlayback: explicitPlayback ? () => {
      if (active.current !== explicitPlayback
        || !ticketAllowed(explicitPlayback.playbackTicket, explicitPlayback.requirePlaybackTicket)) return;
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      releaseActive(true);
    } : null,
    stopCharacterPreview: id => {
      const slot = active.current;
      if (!id.startsWith('character-preview-') || slot?.chunk.id !== id || slot.automatic) return;
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      releaseActive(true);
    },
    freezeReply: interruptionId => {
      const continuous=active.current?.continuous,continuousReply=active.current?.chunk.phone_request_id;
      if(continuous&&!continuous.cancelled&&continuousReply){
        const ticket=optionsRef.current.playbackTicket;
        if(!ticket)return null;
        const receipt=freezePhoneReplyReceipt(ticket,continuousReply,interruptionId);
        if(receipt)skipReply(continuousReply);
        return receipt;
      }
      const id = ongoingReply.current;
      const record = id ? replyRecords.current.get(id) : undefined;
      if (!id || !record || record.suppressed || !record.started.length) return null;
      const ticket = optionsRef.current.playbackTicket;
      const receipt = ticket ? freezePhoneReplyReceipt(ticket, id, interruptionId)
        : Object.freeze({ phone_request_id: id, interruption_id: interruptionId, started_chunk_ids: Object.freeze([...record.started]) as unknown as string[] });
      skipReply(id);
      return receipt;
    },
    replyDrained: (id, finalSequence) => {
      if (suspended.current && continuation.current?.replies.some(r => r.requestId === id)) return false;
      const departure=active.current?.continuous?.speechDeparture;
      if (active.current?.chunk.phone_request_id===id&&!(departure?.replyId===id&&departure.finalSequence===finalSequence)
        ||prepared.current?.chunk.phone_request_id===id
        || chunksRef.current.some(c => c.phone_request_id === id && [pendingActivation.current?.id, pendingPreparation.current].includes(c.id))) return false;
      const record = replyRecords.current.get(id);
      if (record?.suppressed || finalSequence === null) return true;
      for (let index = 0; index <= finalSequence; index++) if (!record?.settled.has(index)) return false;
      return true;
    },
    finishReply: id => {
      const ticket = optionsRef.current.playbackTicket;
      const record = replyRecord(id);
      if (!record) return false;
      if(active.current?.chunk.phone_request_id===id&&active.current.continuous
        &&active.current.continuous.speechDeparture?.replyId!==id)return false;
      if (ticket && (record?.bound || optionsRef.current.nativeAdmittedReplyIds?.includes(id)) && !finishPhoneReplyAudio(ticket, id)) return false;
      if (record) { record.finished = true; record.suppressed = true; }
      for (const [chunkId, chunk] of retainedChunks.current) if (chunk.phone_request_id === id) retainedChunks.current.delete(chunkId);
      if (ongoingReply.current === id) ongoingReply.current = null;
      if (visualReply.current === id) {
        visualStartAbort.current?.abort('completed'); visualStartAbort.current = null; visualReply.current = null;
      }
      return true;
    },
    enabled,
    volume,
    playingId,
    playedCount,
    lastCompletedChunk,
    error,
    currentChunk,
    preparedChunk,
    positionSeconds,
    sourceClockRequired: Boolean(active.current && progressiveSources.has(active.current.player)),
    isPlaying,
    isBetweenSegments: Boolean(active.current?.boundaryPause),
    activePlayer,
    getPlaybackClock: (player, chunkId) => {
      const slot = active.current;
      if(slot?.continuous){const run=slot.continuous,clock=run.snapshot?.clock;
        if(slot.player!==player||run.cancelled||run.speechDeparture||!clock||clock.kind!=='speech'||clock.source.chunkId!==chunkId
          ||!ticketAllowed(slot.playbackTicket,slot.requirePlaybackTicket)||run.clockAtMs===undefined)return null;
        return {seconds:clock.seconds,sampledAtMs:run.clockAtMs,playing:clock.playing,buffering:clock.buffering};}
      if (!slot || slot.player !== player || slot.id !== chunkId || !slot.playbackStartedLogged
        || !ticketAllowed(slot.playbackTicket, slot.requirePlaybackTicket)
        || (slot.automatic && !automaticAllowed(slot.chunk))) return null;
      const status = slot.lastStatus;
      const seconds = status?.currentTime;
      if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0
        || slot.lastStatusAtMs === undefined || status?.error || status?.didJustFinish) return null;
      // The visual consumer mounts after playback confirmation. Preserve that
      // event and its age; never turn play() or another player's status into a clock.
      return {seconds, sampledAtMs:slot.lastStatusAtMs, playing:Boolean(status?.playing),
        buffering:Boolean(status?.isBuffering) || !status?.isLoaded,
        ...(slot.playbackRate !== 1 ? {rate:slot.playbackRate} : {})};
    },
    getLiveSample: liveSampleBuffer.get,
    setLiveSample: liveSampleBuffer.set,
    setEnabled,
    playNow,
    replyFinished: id => replyRecords.current.get(id)?.finished===true,
    retireVisualCarrier: async () => {
      const slot=active.current;
      releaseActive(true);
      // Capture the exact predecessor's chain. A late join never inspects or
      // releases whatever slot a successor might subsequently own.
      await Promise.all([...retiringRuns.current]);
    },
    interrupt: () => {
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      setManualRecovery(null);
      continuation.current = null; suspended.current = false; retainedChunks.current.clear(); resumePositions.current.clear();
      for (const item of chunksRef.current) {
        if (item.id) {
          autoplaySeen.current.add(item.id);
          played.current.add(item.id);
        }
      }
      releaseActive(true, false, 'user_interrupt');
      releasePrepared();
      setPlayedCount(played.current.size);
      setError('');
    },
    stop: () => {
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      const pending = pendingActivation.current;
      const pendingChunk = pending
        ? chunksRef.current.find((chunk) => chunk.id === pending.id)
        : undefined;
      if (pending?.automatic && pendingChunk && automaticAllowed(pendingChunk)) {
        autoplaySeen.current.add(pending.id);
      }
      releaseActive(true, false, 'user_stop');
      releasePrepared();
      setError('');
    },
    reset: () => {
      explicitQueue.current = []; pausedRef.current = false; setPaused(false);
      if (manualRecovery) {
        setManualRecovery(null); continuation.current = null; suspended.current = false;
        retainedChunks.current.clear(); resumePositions.current.clear();
      }
      releaseActive(true, false, 'user_reset');
      releasePrepared();
      played.current = audioHistoryAfterBoundary(played.current, 'explicit_reset');
      autoplaySeen.current = audioHistoryAfterBoundary(autoplaySeen.current, 'explicit_reset');
      setPlayedCount(0);
      setError('');
    },
  };
}
