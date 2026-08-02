import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  advanceLiveMicDetector,
  createLiveMicDetector,
  liveMicPauseReason,
} from '../src/utils/liveMicPolicy.ts';

function advance(state, elapsedMs, meteringDb) {
  return advanceLiveMicDetector(state, { elapsedMs, meteringDb });
}

let detector = createLiveMicDetector();
let result = advance(detector, 0, -62);
detector = result.state;
result = advance(detector, 2_500, -61);
assert.equal(result.decision, 'rotate', 'quiet recordings must rotate instead of growing indefinitely');

detector = createLiveMicDetector();
result = advance(detector, 100, -20);
detector = result.state;
assert.equal(detector.phase, 'listening');
result = advance(detector, 200, -62);
assert.equal(result.state.phase, 'listening', 'one loud sample must not create an utterance');
assert.equal(result.decision, 'none');

detector = createLiveMicDetector();
detector = advance(detector, 100, -22).state;
result = advance(detector, 200, -21);
detector = result.state;
assert.equal(detector.phase, 'speech', 'sustained voice must activate the utterance');
assert.equal(result.decision, 'none');

detector = advance(detector, 300, -20).state;
detector = advance(detector, 900, -62).state;
result = advance(detector, 1_300, -62);
assert.equal(result.decision, 'upload', 'one second of trailing silence must complete speech');

detector = createLiveMicDetector();
for (let sampleIndex = 1; sampleIndex <= 4; sampleIndex += 1) {
  detector = advanceLiveMicDetector(detector, {
    elapsedMs: sampleIndex * 100,
    meteringDb: -20,
    playbackActive: true,
  }).state;
}
assert.equal(detector.phase, 'listening', 'phone playback must require sustained foreground speech');
result = advanceLiveMicDetector(detector, {
  elapsedMs: 500,
  meteringDb: -20,
  playbackActive: true,
});
assert.equal(result.state.phase, 'speech', 'sustained foreground speech must barge in during phone playback');

detector = createLiveMicDetector();
for (let sampleIndex = 1; sampleIndex <= 5; sampleIndex += 1) {
  detector = advanceLiveMicDetector(detector, {
    elapsedMs: sampleIndex * 100,
    meteringDb: -36,
    playbackActive: true,
  }).state;
}
assert.equal(detector.phase, 'listening', 'speaker leakage below the playback activation floor must be ignored');

detector = createLiveMicDetector();
detector = advance(detector, 100, -20).state;
detector = advance(detector, 200, -20).state;
result = advance(detector, 60_000, -20);
assert.equal(result.decision, 'upload', 'the existing 60 second safety limit must end an utterance');

assert.equal(
  liveMicPauseReason({ connected: false, voiceAvailable: true, phonePlaying: false, backendStatus: '' }),
  'Reconnect to use Live Mic.',
);
assert.equal(
  liveMicPauseReason({ connected: true, voiceAvailable: false, phonePlaying: false, backendStatus: '' }),
  'Phone voice input is unavailable.',
);
assert.equal(
  liveMicPauseReason({ connected: true, voiceAvailable: true, phonePlaying: true, backendStatus: '' }),
  '',
);
assert.equal(
  liveMicPauseReason({ connected: true, voiceAvailable: true, phonePlaying: false, backendStatus: 'Generating response' }),
  '',
);
assert.equal(
  liveMicPauseReason({ connected: true, voiceAvailable: true, phonePlaying: false, backendStatus: 'Speaking' }),
  '',
);
assert.equal(
  liveMicPauseReason({ connected: true, voiceAvailable: true, phonePlaying: false, backendStatus: 'Ready' }),
  '',
);

const recorderSource = readFileSync(new URL('../src/hooks/useRecorder.ts', import.meta.url), 'utf8');
const audioQueueSource = readFileSync(new URL('../src/hooks/useAudioQueue.ts', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../App.tsx', import.meta.url), 'utf8');

assert.match(
  recorderSource,
  /audioSource:\s*'voice_communication'/,
  'Live Mic must request the Android voice-communication source for echo control',
);
assert.match(
  recorderSource,
  /playbackActive:\s*optionsRef\.current\.playbackActive/,
  'Live Mic must pass phone playback state into the detector',
);
assert.match(
  recorderSource,
  /previousPhase\s*===\s*'listening'[\s\S]*result\.state\.phase\s*===\s*'speech'/,
  'Live Mic must issue barge-in once on the listening-to-speech transition',
);
assert.match(
  recorderSource,
  /mode\s*===\s*'idle'/,
  'Live Mic rolling capture must react to recorder mode returning to idle',
);
assert.match(
  recorderSource,
  /\[[^\]]*beginRecording[^\]]*busy[^\]]*finishCurrentRecording[^\]]*liveEnabled[^\]]*mode[^\]]*options\.livePauseReason[^\]]*\]/,
  'Live Mic rolling capture effect must depend on recorder mode',
);
assert.doesNotMatch(
  recorderSource,
  /playbackGuardUntilRef/,
  'phone playback must not leave Live Mic stranded behind a timer-only guard',
);
assert.match(
  audioQueueSource,
  /interrupt:\s*\(\)\s*=>/,
  'Phone audio queue must expose an immediate response interruption operation',
);
assert.match(
  appSource,
  /sendControl\('interrupt_response'/,
  'Live Mic speech onset must coordinate interruption with the desktop runtime',
);

console.log('Live Mic policy smoke passed.');
