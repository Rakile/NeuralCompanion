export type LiveMicDetectorPhase = 'listening' | 'speech';
export type LiveMicDecision = 'none' | 'rotate' | 'upload';

export type LiveMicDetectorState = {
  phase: LiveMicDetectorPhase;
  noiseFloorDb: number;
  consecutiveVoiceSamples: number;
  voiceStartedAtMs: number;
  lastSampleAtMs: number;
  playbackActive: boolean;
  lastVoiceAtMs: number;
};

export type LiveMicSample = {
  elapsedMs: number;
  meteringDb?: number;
  playbackActive?: boolean;
};

export type LiveMicDetectorResult = {
  state: LiveMicDetectorState;
  decision: LiveMicDecision;
};

export type LiveMicPauseInput = {
  connected: boolean;
  voiceAvailable: boolean;
  phonePlaying: boolean;
  backendStatus: string;
};

const DEFAULT_NOISE_FLOOR_DB = -60;
const MIN_ACTIVATION_DB = -45;
const ACTIVATION_MARGIN_DB = 12;
const RELEASE_HYSTERESIS_DB = 4;
const REQUIRED_VOICE_SAMPLES = 3;
const PLAYBACK_REQUIRED_VOICE_SAMPLES = 5;
const MIN_VOICE_DURATION_MS = 200;
const PLAYBACK_MIN_VOICE_DURATION_MS = 400;
const MAX_SAMPLE_GAP_MS = 300;
const PLAYBACK_ACTIVATION_FLOOR_DB = -35;
const NOISE_FLOOR_ALPHA = 0.05;
const QUIET_ROTATION_MS = 2_500;
const TRAILING_SILENCE_MS = 1_000;
const MAX_UTTERANCE_MS = 60_000;

function finiteMetering(value: number | undefined): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function activationThreshold(noiseFloorDb: number): number {
  return Math.max(MIN_ACTIVATION_DB, noiseFloorDb + ACTIVATION_MARGIN_DB);
}

function sampleActivationThreshold(noiseFloorDb: number, playbackActive: boolean): number {
  const threshold = activationThreshold(noiseFloorDb);
  return playbackActive ? Math.max(PLAYBACK_ACTIVATION_FLOOR_DB, threshold) : threshold;
}

export function createLiveMicDetector(noiseFloorDb = DEFAULT_NOISE_FLOOR_DB): LiveMicDetectorState {
  return {
    phase: 'listening',
    noiseFloorDb: Math.max(-90, Math.min(-30, finiteMetering(noiseFloorDb) ?? DEFAULT_NOISE_FLOOR_DB)),
    consecutiveVoiceSamples: 0,
    voiceStartedAtMs: -1,
    lastSampleAtMs: -1,
    playbackActive: false,
    lastVoiceAtMs: 0,
  };
}

export function advanceLiveMicDetector(
  state: LiveMicDetectorState,
  sample: LiveMicSample,
): LiveMicDetectorResult {
  const elapsedMs = Math.max(0, Number(sample.elapsedMs) || 0);
  const meteringDb = finiteMetering(sample.meteringDb);
  const playbackActive = Boolean(sample.playbackActive);
  // Playback/UI changes can rerun the hook with the same native meter sample.
  if (elapsedMs <= state.lastSampleAtMs) {
    return { state, decision: 'none' };
  }
  const sampleGap = elapsedMs - state.lastSampleAtMs;
  const candidateInterrupted = sampleGap > MAX_SAMPLE_GAP_MS || playbackActive !== state.playbackActive;
  const sampledState = { ...state, lastSampleAtMs: elapsedMs, playbackActive };

  if (state.phase === 'speech') {
    if (elapsedMs >= MAX_UTTERANCE_MS) {
      return { state: sampledState, decision: 'upload' };
    }
    const releaseThreshold = sampleActivationThreshold(state.noiseFloorDb, playbackActive) - RELEASE_HYSTERESIS_DB;
    const voicePresent = meteringDb !== undefined && meteringDb >= releaseThreshold;
    const nextState = voicePresent
      ? { ...sampledState, lastVoiceAtMs: elapsedMs }
      : sampledState;
    if (elapsedMs - nextState.lastVoiceAtMs >= TRAILING_SILENCE_MS) {
      return { state: nextState, decision: 'upload' };
    }
    return { state: nextState, decision: 'none' };
  }

  if (elapsedMs >= MAX_UTTERANCE_MS) {
    return { state: sampledState, decision: 'rotate' };
  }

  const threshold = sampleActivationThreshold(state.noiseFloorDb, playbackActive);
  if (meteringDb !== undefined && meteringDb >= threshold) {
    const consecutiveVoiceSamples = candidateInterrupted ? 1 : state.consecutiveVoiceSamples + 1;
    const voiceStartedAtMs = candidateInterrupted || state.voiceStartedAtMs < 0 ? elapsedMs : state.voiceStartedAtMs;
    const requiredVoiceSamples = playbackActive
      ? PLAYBACK_REQUIRED_VOICE_SAMPLES
      : REQUIRED_VOICE_SAMPLES;
    const requiredDurationMs = playbackActive ? PLAYBACK_MIN_VOICE_DURATION_MS : MIN_VOICE_DURATION_MS;
    if (consecutiveVoiceSamples >= requiredVoiceSamples && elapsedMs - voiceStartedAtMs >= requiredDurationMs) {
      return {
        state: {
          ...sampledState,
          phase: 'speech',
          consecutiveVoiceSamples,
          voiceStartedAtMs,
          lastVoiceAtMs: elapsedMs,
        },
        decision: 'none',
      };
    }
    return {
      state: { ...sampledState, consecutiveVoiceSamples, voiceStartedAtMs },
      decision: 'none',
    };
  }

  return {
    state: {
      ...sampledState,
      // Speaker leakage is not the room noise floor; learning it can hide the
      // user's next quiet utterance after phone playback has ended.
      noiseFloorDb: playbackActive || meteringDb === undefined
        ? state.noiseFloorDb
        : Math.max(-90, Math.min(-30, state.noiseFloorDb + (meteringDb - state.noiseFloorDb) * NOISE_FLOOR_ALPHA)),
      consecutiveVoiceSamples: 0,
      voiceStartedAtMs: -1,
    },
    decision: elapsedMs >= QUIET_ROTATION_MS ? 'rotate' : 'none',
  };
}

export function liveMicPauseReason(input: LiveMicPauseInput): string {
  if (!input.connected) {
    return 'Reconnect to use Live Mic.';
  }
  if (!input.voiceAvailable) {
    return 'Phone voice input is unavailable.';
  }
  return '';
}
