export type LiveMicDetectorPhase = 'listening' | 'speech';
export type LiveMicDecision = 'none' | 'rotate' | 'upload';

export type LiveMicDetectorState = {
  phase: LiveMicDetectorPhase;
  noiseFloorDb: number;
  consecutiveVoiceSamples: number;
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
const REQUIRED_VOICE_SAMPLES = 2;
const PLAYBACK_REQUIRED_VOICE_SAMPLES = 5;
const PLAYBACK_ACTIVATION_FLOOR_DB = -35;
const NOISE_FLOOR_ALPHA = 0.05;
const QUIET_ROTATION_MS = 2_500;
const TRAILING_SILENCE_MS = 1_000;
const MAX_UTTERANCE_MS = 60_000;

function finiteMetering(value: number | undefined): number | undefined {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
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
    noiseFloorDb: finiteMetering(noiseFloorDb) ?? DEFAULT_NOISE_FLOOR_DB,
    consecutiveVoiceSamples: 0,
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

  if (state.phase === 'speech') {
    if (elapsedMs >= MAX_UTTERANCE_MS) {
      return { state, decision: 'upload' };
    }
    const releaseThreshold = sampleActivationThreshold(state.noiseFloorDb, playbackActive) - RELEASE_HYSTERESIS_DB;
    const voicePresent = meteringDb !== undefined && meteringDb >= releaseThreshold;
    const nextState = voicePresent
      ? { ...state, lastVoiceAtMs: elapsedMs }
      : state;
    if (elapsedMs - nextState.lastVoiceAtMs >= TRAILING_SILENCE_MS) {
      return { state: nextState, decision: 'upload' };
    }
    return { state: nextState, decision: 'none' };
  }

  if (elapsedMs >= QUIET_ROTATION_MS) {
    return { state, decision: 'rotate' };
  }
  if (meteringDb === undefined) {
    return { state, decision: 'none' };
  }

  const threshold = sampleActivationThreshold(state.noiseFloorDb, playbackActive);
  if (meteringDb >= threshold) {
    const consecutiveVoiceSamples = state.consecutiveVoiceSamples + 1;
    const requiredVoiceSamples = playbackActive
      ? PLAYBACK_REQUIRED_VOICE_SAMPLES
      : REQUIRED_VOICE_SAMPLES;
    if (consecutiveVoiceSamples >= requiredVoiceSamples) {
      return {
        state: {
          ...state,
          phase: 'speech',
          consecutiveVoiceSamples,
          lastVoiceAtMs: elapsedMs,
        },
        decision: 'none',
      };
    }
    return {
      state: { ...state, consecutiveVoiceSamples },
      decision: 'none',
    };
  }

  return {
    state: {
      ...state,
      noiseFloorDb: state.noiseFloorDb + (meteringDb - state.noiseFloorDb) * NOISE_FLOOR_ALPHA,
      consecutiveVoiceSamples: 0,
    },
    decision: 'none',
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
