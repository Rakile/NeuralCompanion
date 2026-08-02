import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  DEFAULT_LIVE_FULLSCREEN_SETTINGS,
  normalizeLiveFullscreenSettings,
} from '../src/utils/liveFullscreenSettings.ts';
import * as spectrumPolicy from '../src/utils/liveFullscreenSpectrum.ts';
import {
  advanceSpectrumPhase,
  decodeSpectrumTimeline,
  directionalSpectrumSeconds,
  frameAtPlaybackTime,
  hasSpectrumFrameAtTime,
  normalizeMicLevel,
  playbackSpectrumFrame,
  proceduralSpectrum,
  resampleSpectrum,
  sampleToSpectrum,
  selectSpectrumSource,
} from '../src/utils/liveFullscreenSpectrum.ts';
import {
  captureVisualReplyBaseline,
  isFreshVisualReply,
} from '../src/utils/liveFullscreenVisual.ts';
import { decideFullscreenGesture } from '../src/utils/liveFullscreenGestures.ts';
import {
  isPrivateLiveFullscreenUri,
  normalizedImportedExtension,
  shouldDeleteReplacedBackground,
} from '../src/utils/liveFullscreenMediaPolicy.ts';
import {
  spectrumBarRadii,
  spectrumRadius,
} from '../src/utils/liveFullscreenGeometry.ts';
import { shouldExitLiveFullscreen } from '../src/utils/liveFullscreenSession.ts';
import {
  backgroundTransformFromGesture,
  chooseTransformTarget,
  circleTransformFromGesture,
  createFullscreenTransformResponderCallbacks,
  sliderValueFromDrag,
  twoTouchMetrics,
} from '../src/utils/liveFullscreenTransform.ts';

assert.deepEqual(normalizeLiveFullscreenSettings(undefined), DEFAULT_LIVE_FULLSCREEN_SETTINGS);
const clamped = normalizeLiveFullscreenSettings({
  circleSizePct: 900,
  waveformDepthPct: -4,
  verticalPositionPct: 99,
  longPressSeconds: 0.2,
  backgroundKind: 'invalid',
  backgroundUri: 22,
});
assert.equal(clamped.circleSizePct, 200);
assert.equal(clamped.waveformDepthPct, 0);
assert.equal(clamped.verticalPositionPct, 90);
assert.equal(clamped.longPressSeconds, 1);
assert.equal(clamped.backgroundKind, 'bundled_still');
assert.equal(clamped.backgroundUri, '');
assert.equal(clamped.spectrumFps, 24);
assert.equal(normalizeLiveFullscreenSettings({ spectrumFps: 1 }).spectrumFps, 12);
assert.equal(normalizeLiveFullscreenSettings({ spectrumFps: 120 }).spectrumFps, 60);
const transformedSettings = normalizeLiveFullscreenSettings({
  circleHorizontalPositionPct: 200,
  verticalPositionPct: -10,
  rotationSpeedPct: 250,
  spectrumBarCount: 51,
  backgroundOffsetXPct: -140,
  backgroundOffsetYPct: 140,
});
assert.equal(transformedSettings.circleHorizontalPositionPct, 90);
assert.equal(transformedSettings.verticalPositionPct, 10);
assert.equal(transformedSettings.rotationSpeedPct, 200);
assert.equal(transformedSettings.spectrumBarCount, 52);
assert.equal(transformedSettings.backgroundOffsetXPct, -100);
assert.equal(transformedSettings.backgroundOffsetYPct, 100);

assert.equal(sliderValueFromDrag(100, 50, 200, 0, 200, 1), 150);
assert.equal(sliderValueFromDrag(100, -300, 200, 0, 200, 1), 0);
assert.equal(sliderValueFromDrag(3, 20, 100, 1, 6, 0.5), 4);
const startTouches = twoTouchMetrics([
  { pageX: 100, pageY: 200 },
  { pageX: 200, pageY: 200 },
]);
assert.deepEqual(startTouches, { midpointX: 150, midpointY: 200, distance: 100 });
assert.equal(twoTouchMetrics([{ pageX: 100, pageY: 200 }]), null);
assert.equal(twoTouchMetrics([
  { pageX: 100, pageY: 200 },
  { pageX: Number.NaN, pageY: 200 },
]), null);
assert.equal(
  chooseTransformTarget(
    startTouches,
    { left: 80, top: 120, width: 180, height: 180 },
    true,
  ),
  'circle',
);
assert.equal(
  chooseTransformTarget(
    { midpointX: 80, midpointY: 210, distance: 80 },
    { left: 80, top: 120, width: 180, height: 180 },
    true,
  ),
  'circle',
);
assert.equal(
  chooseTransformTarget(
    { midpointX: 80, midpointY: 120, distance: 80 },
    { left: 80, top: 120, width: 180, height: 180 },
    true,
  ),
  'background',
);
assert.equal(
  chooseTransformTarget(
    { midpointX: 20, midpointY: 20, distance: 80 },
    { left: 80, top: 120, width: 180, height: 180 },
    true,
  ),
  'background',
);
assert.equal(
  chooseTransformTarget(
    { midpointX: 20, midpointY: 20, distance: 80 },
    { left: 80, top: 120, width: 180, height: 180 },
    false,
  ),
  null,
);
assert.deepEqual(
  circleTransformFromGesture(
    { circleSizePct: 100, circleHorizontalPositionPct: 50, verticalPositionPct: 34 },
    startTouches,
    { midpointX: 200, midpointY: 300, distance: 150 },
    { width: 400, height: 800 },
  ),
  { circleSizePct: 150, circleHorizontalPositionPct: 62.5, verticalPositionPct: 46.5 },
);
assert.deepEqual(
  circleTransformFromGesture(
    { circleSizePct: 190, circleHorizontalPositionPct: 85, verticalPositionPct: 15 },
    { midpointX: 100, midpointY: 100, distance: 0 },
    { midpointX: 500, midpointY: -500, distance: 400 },
    { width: 400, height: 800 },
  ),
  { circleSizePct: 190, circleHorizontalPositionPct: 90, verticalPositionPct: 10 },
);
assert.deepEqual(
  backgroundTransformFromGesture(
    { backgroundScalePct: 100, backgroundOffsetXPct: 0, backgroundOffsetYPct: 0 },
    startTouches,
    { midpointX: 350, midpointY: -200, distance: 250 },
    { width: 400, height: 800 },
  ),
  { backgroundScalePct: 200, backgroundOffsetXPct: 50, backgroundOffsetYPct: -50 },
);
assert.deepEqual(
  backgroundTransformFromGesture(
    { backgroundScalePct: 190, backgroundOffsetXPct: 90, backgroundOffsetYPct: -90 },
    startTouches,
    { midpointX: 1000, midpointY: -1000, distance: 500 },
    { width: 400, height: 800 },
  ),
  { backgroundScalePct: 200, backgroundOffsetXPct: 100, backgroundOffsetYPct: -100 },
);

const bytes = Uint8Array.from({ length: 96 }, (_, index) => index);
const payload = {
  version: 1,
  fps: 24,
  bars: 48,
  frame_count: 2,
  encoding: 'uint8-base64',
  data: Buffer.from(bytes).toString('base64'),
};
const timeline = decodeSpectrumTimeline(payload);
assert.equal(timeline.frames.length, 2);
assert.equal(frameAtPlaybackTime(timeline, 1 / 48).length, 48);
assert.equal(hasSpectrumFrameAtTime(timeline, 0), true);
assert.equal(hasSpectrumFrameAtTime(timeline, timeline.frames.length / timeline.fps), false);
assert.equal(playbackSpectrumFrame(timeline, 0, null).source, 'analyzed');
const postTimelineLiveSample = Array(48).fill(0.65);
const fallbackSeed = Array.from({ length: 48 }, (_, index) => index / 48);
const postTimelineLive = playbackSpectrumFrame(
  timeline,
  timeline.frames.length / timeline.fps,
  postTimelineLiveSample,
);
assert.equal(postTimelineLive.source, 'live');
assert.deepEqual(postTimelineLive.energies, postTimelineLiveSample);
const postTimelineProcedural = playbackSpectrumFrame(
  timeline,
  timeline.frames.length / timeline.fps,
  null,
);
assert.equal(postTimelineProcedural.source, 'procedural');
assert.deepEqual(postTimelineProcedural.energies, Array(48).fill(0));
assert.deepEqual(
  playbackSpectrumFrame(timeline, 1, null, fallbackSeed).energies,
  playbackSpectrumFrame(timeline, 99, null, fallbackSeed).energies,
);
assert.equal(selectSpectrumSource(true, true), 'analyzed');
assert.equal(selectSpectrumSource(false, true), 'live');
assert.equal(selectSpectrumSource(false, false), 'procedural');
assert.equal(normalizeMicLevel(-60), 0);
assert.equal(normalizeMicLevel(0), 1);
assert.equal(typeof spectrumPolicy.spectrumFrameIntervalMs, 'function');
assert.equal(spectrumPolicy.spectrumFrameIntervalMs(24), 1000 / 24);
assert.equal(spectrumPolicy.spectrumFrameIntervalMs(1), 1000 / 12);
assert.equal(spectrumPolicy.spectrumFrameIntervalMs(120), 1000 / 60);
assert.equal(typeof spectrumPolicy.shouldPublishSpectrumFrame, 'function');
assert.equal(spectrumPolicy.shouldPublishSpectrumFrame(1020, 1000, 24), false);
assert.equal(spectrumPolicy.shouldPublishSpectrumFrame(1042, 1000, 24), true);
assert.equal(typeof spectrumPolicy.spectrumPhaseAtTime, 'function');
assert.equal(spectrumPolicy.spectrumPhaseAtTime(5000, 0.012, 0), 0);
assert.equal(spectrumPolicy.spectrumPhaseAtTime(5000, 0.012, 100), 60);
assert.equal(typeof spectrumPolicy.spectrumRotationPhase, 'function');
assert.equal(spectrumPolicy.spectrumRotationPhase('speaking', 20_000, 0.012, 200), 0);
assert.equal(spectrumPolicy.spectrumRotationPhase('listening', 20_000, 0.012, 200), 0);
assert.ok(spectrumPolicy.spectrumRotationPhase('thinking', 20_000, 0.045, 100) > 0);
assert.equal(spectrumPolicy.spectrumRotationPhase('thinking', 20_000, 0.045, 0), 0);
assert.equal(typeof spectrumPolicy.fixedPlaybackFallback, 'function');
const decayedFallback = spectrumPolicy.fixedPlaybackFallback(Array(48).fill(0.8));
assert.ok(decayedFallback.every((value) => value > 0 && value < 0.8));
const afterLongChunkBoundary = playbackSpectrumFrame(timeline, 18.1, null, decayedFallback).energies;
assert.ok(afterLongChunkBoundary.every((value, index) => value < decayedFallback[index]));
assert.deepEqual(
  spectrumPolicy.fixedPlaybackFallback(null),
  Array(48).fill(0),
);
assert.equal(typeof spectrumPolicy.microphoneVuSpectrum, 'function');
const quietMicrophone = spectrumPolicy.microphoneVuSpectrum(0);
const speakingMicrophone = spectrumPolicy.microphoneVuSpectrum(0.75);
assert.deepEqual(quietMicrophone, Array(48).fill(0));
assert.equal(speakingMicrophone.length, 48);
assert.ok(speakingMicrophone.some((value) => value > 0.5));
assert.deepEqual(spectrumPolicy.microphoneVuSpectrum(0.75), speakingMicrophone);
assert.equal(typeof spectrumPolicy.smoothMicDisplayLevel, 'function');
const micAttack = spectrumPolicy.smoothMicDisplayLevel(0.1, -18);
const micRelease = spectrumPolicy.smoothMicDisplayLevel(micAttack, -60);
assert.ok(micAttack > 0.5);
assert.ok(micRelease > 0);
assert.ok(micRelease < micAttack);
assert.equal(spectrumPolicy.smoothMicDisplayLevel(0, undefined), 0);
assert.equal(typeof spectrumPolicy.createMicSpectrumHistoryState, 'function');
assert.equal(typeof spectrumPolicy.advanceMicSpectrumHistoryState, 'function');
assert.equal(typeof spectrumPolicy.composeLiveFullscreenEnergies, 'function');
let micHistory = spectrumPolicy.createMicSpectrumHistoryState(0);
assert.deepEqual(micHistory.energies, Array(48).fill(0));
micHistory = spectrumPolicy.advanceMicSpectrumHistoryState(micHistory, {
  frameTimeMs: 42,
  microphoneActive: true,
  meteringDb: -30,
  meteringRevision: 1,
});
const firstMicHistory = [...micHistory.energies];
assert.ok(firstMicHistory.at(-1) > 0);
const sameMicRevision = spectrumPolicy.advanceMicSpectrumHistoryState(micHistory, {
  frameTimeMs: 84,
  microphoneActive: true,
  meteringDb: -30,
  meteringRevision: 1,
});
assert.deepEqual(sameMicRevision.energies, firstMicHistory);
const secondMicRevision = spectrumPolicy.advanceMicSpectrumHistoryState(sameMicRevision, {
  frameTimeMs: 126,
  microphoneActive: true,
  meteringDb: -12,
  meteringRevision: 2,
});
assert.deepEqual(secondMicRevision.energies.slice(0, -1), firstMicHistory.slice(1));
assert.ok(secondMicRevision.energies.at(-1) > firstMicHistory.at(-1));

let variedMicHistory = spectrumPolicy.createMicSpectrumHistoryState(0);
const variedMeteringDb = [-58, -44, -31, -22, -38, -17, -49, -27];
for (let revision = 1; revision <= 48; revision += 1) {
  variedMicHistory = spectrumPolicy.advanceMicSpectrumHistoryState(variedMicHistory, {
    frameTimeMs: revision * 42,
    microphoneActive: true,
    meteringDb: variedMeteringDb[(revision - 1) % variedMeteringDb.length],
    meteringRevision: revision,
  });
}
assert.equal(variedMicHistory.energies.length, 48);
assert.ok(new Set(variedMicHistory.energies.map((value) => value.toFixed(3))).size >= 6);
const inactiveMicHistory = spectrumPolicy.advanceMicSpectrumHistoryState(variedMicHistory, {
  frameTimeMs: 48 * 42 + 84,
  microphoneActive: false,
  meteringDb: undefined,
  meteringRevision: 48,
});
assert.ok(inactiveMicHistory.energies.some(
  (value, index) => value < variedMicHistory.energies[index],
));
assert.ok(inactiveMicHistory.energies.every(
  (value, index) => value <= variedMicHistory.energies[index],
));
const staleMicHistory = spectrumPolicy.advanceMicSpectrumHistoryState(variedMicHistory, {
  frameTimeMs: 48 * 42 + 400,
  microphoneActive: true,
  meteringDb: -27,
  meteringRevision: 48,
});
assert.ok(staleMicHistory.energies.some(
  (value, index) => value < variedMicHistory.energies[index],
));
assert.deepEqual(
  spectrumPolicy.createMicSpectrumHistoryState(9000).energies,
  Array(48).fill(0),
);
assert.deepEqual(
  spectrumPolicy.composeLiveFullscreenEnergies({
    ttsEnergies: [0.1, 0.2, 0.3, 0.4],
    ttsPlaybackActive: true,
    microphoneEnergies: [0.4, 0.3, 0.2, 0.1],
    barCount: 4,
  }),
  {
    outerEnergies: [0.1, 0.2, 0.3, 0.4],
    innerEnergies: [0.4, 0.3, 0.2, 0.1],
  },
);
const sampled = sampleToSpectrum([{ frames: [0, 0.5, -1, 0.25] }]);
assert.equal(sampled.length, 48);
assert.ok(sampled.some((value) => value > 0));
assert.deepEqual(resampleSpectrum([], 16), Array(16).fill(0));
assert.deepEqual(resampleSpectrum([0, 1], 4), [0, 1 / 3, 2 / 3, 1]);
assert.equal(resampleSpectrum(sampled, 96).length, 96);
assert.deepEqual(
  spectrumBarRadii(100, 20, 'inward', 52),
  { innerRadius: 80, outerRadius: 100 },
);
assert.deepEqual(
  spectrumBarRadii(100, 20, 'outward', 52),
  { innerRadius: 100, outerRadius: 120 },
);
assert.throws(() => decodeSpectrumTimeline({ ...payload, bars: 47 }));
assert.equal(advanceSpectrumPhase(12, 50, 0.045, 0), 12);
assert.ok(advanceSpectrumPhase(12, 50, 0.045, 100) > 12);
assert.equal(directionalSpectrumSeconds(42, 0), 0);
assert.equal(directionalSpectrumSeconds(42, 100), 42);
const fixedDirectionalPhase = directionalSpectrumSeconds(42, 0);
const quietFixedBars = proceduralSpectrum(fixedDirectionalPhase, 0.2);
const loudFixedBars = proceduralSpectrum(fixedDirectionalPhase, 0.8);
assert.ok(loudFixedBars.every((value, index) => value > quietFixedBars[index]));

const baseline = captureVisualReplyBaseline({
  state: { image_cache_key: 'old', updated_at: 100 },
});
assert.equal(
  isFreshVisualReply(baseline, {
    image_url_path: '/api/visual/image',
    image_cache_key: 'old',
    updated_at: 100,
  }),
  false,
);
assert.equal(
  isFreshVisualReply(baseline, {
    image_url_path: '/api/visual/image',
    image_cache_key: 'new',
    updated_at: 101,
  }),
  true,
);
assert.equal(
  isFreshVisualReply(baseline, {
    image_url_path: '/api/visual/image',
    image_cache_key: 'old',
    updated_at: 99,
  }),
  false,
);

assert.equal(
  decideFullscreenGesture({ heldMs: 3100, thresholdMs: 3000, taps: 1, movedPx: 3 }),
  'long',
);
assert.equal(
  decideFullscreenGesture({ heldMs: 120, thresholdMs: 3000, taps: 2, movedPx: 3 }),
  'double',
);
assert.equal(
  decideFullscreenGesture({ heldMs: 120, thresholdMs: 3000, taps: 1, movedPx: 3 }),
  'single',
);
assert.equal(
  decideFullscreenGesture({ heldMs: 3100, thresholdMs: 3000, taps: 1, movedPx: 30 }),
  'none',
);
const transformContacts = [];
const singleTouchMoves = [];
let transformActive = false;
let transformEndCount = 0;
const transformResponder = createFullscreenTransformResponderCallbacks({
  isTransforming: () => transformActive,
  onSingleTouchMove: (distancePx) => singleTouchMoves.push(distancePx),
  onTransformContact: (metrics) => {
    transformActive = true;
    transformContacts.push(metrics);
  },
  onTransformEnd: () => {
    transformActive = false;
    transformEndCount += 1;
  },
});
transformResponder.onPanResponderStart({
  nativeEvent: {
    touches: [{ pageX: 100, pageY: 200 }],
  },
});
assert.deepEqual(transformContacts, []);
transformResponder.onPanResponderStart({
  nativeEvent: {
    touches: [
      { pageX: 100, pageY: 200 },
      { pageX: 200, pageY: 200 },
    ],
  },
});
assert.deepEqual(
  transformContacts,
  [{ midpointX: 150, midpointY: 200, distance: 100 }],
);
assert.deepEqual(singleTouchMoves, []);
transformResponder.onPanResponderMove(
  {
    nativeEvent: {
      touches: [
        { pageX: 90, pageY: 210 },
        { pageX: 220, pageY: 230 },
      ],
    },
  },
  { dx: 0, dy: 0 },
);
assert.deepEqual(
  transformContacts.at(-1),
  { midpointX: 155, midpointY: 220, distance: 131.529 },
);
transformResponder.onPanResponderEnd({
  nativeEvent: {
    touches: [{ pageX: 90, pageY: 210 }],
  },
});
assert.equal(transformEndCount, 1);

const root = 'file:///data/user/0/nc/files/live-fullscreen/';
assert.equal(isPrivateLiveFullscreenUri(`${root}background.mp4`, root), true);
assert.equal(isPrivateLiveFullscreenUri('file:///data/user/0/nc/files/other/photo.jpg', root), false);
assert.equal(normalizedImportedExtension('video/mp4', 'photo.bin'), '.mp4');
assert.equal(normalizedImportedExtension('image/jpeg', 'photo.bin'), '.jpg');
assert.equal(shouldDeleteReplacedBackground(`${root}old.mp4`, root, `${root}new.mp4`), true);
assert.equal(shouldDeleteReplacedBackground('asset:///bundled.png', root, `${root}new.mp4`), false);
assert.equal(spectrumRadius(400, 800, 100, 40), 152);
assert.equal(spectrumRadius(400, 800, 200, 40), 152);
assert.equal(
  shouldExitLiveFullscreen({ visible: true, demoMode: false, sessionActive: true }),
  false,
);
assert.equal(
  shouldExitLiveFullscreen({ visible: true, demoMode: false, sessionActive: false }),
  true,
);
assert.equal(
  shouldExitLiveFullscreen({ visible: true, demoMode: true, sessionActive: false }),
  false,
);
assert.equal(
  shouldExitLiveFullscreen({ visible: false, demoMode: false, sessionActive: false }),
  false,
);

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const phoneSettingsSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'usePhoneSettings.ts'),
  'utf8',
);
assert.match(phoneSettingsSource, /liveFullscreen: LiveFullscreenSettings/);
assert.match(phoneSettingsSource, /normalizeLiveFullscreenSettings\(data\.liveFullscreen\)/);
assert.match(phoneSettingsSource, /setLiveFullscreenSettings/);
assert.match(phoneSettingsSource, /current\.liveFullscreen/);
const apiTypesSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'api', 'types.ts'),
  'utf8',
);
assert.match(apiTypesSource, /spectrum_url_path\?: string/);
assert.match(apiTypesSource, /AudioSpectrumTimelinePayload/);
const apiClientSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'api', 'client.ts'),
  'utf8',
);
assert.match(apiClientSource, /audioSpectrum\(path: string\)/);
const audioQueueSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'useAudioQueue.ts'),
  'utf8',
);
assert.match(audioQueueSource, /currentChunk: AudioChunk \| null/);
assert.match(audioQueueSource, /positionSeconds: number/);
assert.match(audioQueueSource, /preparedChunk: AudioChunk \| null/);
assert.match(audioQueueSource, /setCurrentChunk\(updatedActive\)/);
assert.match(audioQueueSource, /setPreparedChunk\(updatedPrepared\)/);
const recorderSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'useRecorder.ts'),
  'utf8',
);
assert.match(recorderSource, /liveStatus,\s+meteringDb: recorderState\.metering/);
assert.match(recorderSource, /meteringDb: recorderState\.metering[\s\S]*livePhase,/);
assert.match(recorderSource, /meteringRevision: recorderState\.durationMillis/);
const spectrumHookPath = path.join(scriptDir, '..', 'src', 'hooks', 'useSpectrumPlayback.ts');
const audioSampleTapPath = path.join(
  scriptDir,
  '..',
  'src',
  'components',
  'live-fullscreen',
  'AudioSampleTap.tsx',
);
const mediaUtilityPath = path.join(scriptDir, '..', 'src', 'utils', 'liveFullscreenMedia.ts');
assert.equal(fs.existsSync(spectrumHookPath), true);
assert.equal(fs.existsSync(audioSampleTapPath), true);
assert.equal(fs.existsSync(mediaUtilityPath), true);
assert.match(fs.readFileSync(spectrumHookPath, 'utf8'), /client\.audioSpectrum/);
assert.match(fs.readFileSync(audioSampleTapPath, 'utf8'), /useAudioSampleListener/);
assert.match(fs.readFileSync(mediaUtilityPath, 'utf8'), /FileSystem\.documentDirectory/);
for (const componentName of [
  'CircularSpectrum.tsx',
  'LiveFullscreenBackground.tsx',
  'LiveFullscreenSlider.tsx',
  'LiveFullscreenSettings.tsx',
  'VisualReplyPortal.tsx',
  'LiveFullscreenGestureLayer.tsx',
  'LiveFullscreenActionTray.tsx',
  'LiveFullscreenScreen.tsx',
]) {
  assert.equal(
    fs.existsSync(path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', componentName)),
    true,
  );
}
const settingsPanelSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'SettingsPanel.tsx'),
  'utf8',
);
assert.match(settingsPanelSource, /live_fullscreen/);
assert.match(settingsPanelSource, /LiveFullscreenSettings/);
assert.match(settingsPanelSource, /onLiveFullscreenChange/);
assert.doesNotMatch(
  settingsPanelSource,
  /liveFullscreen:\s*\{\s*\.\.\.settings\.liveFullscreen,\s*\.\.\.updates/s,
);
const sliderSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', 'LiveFullscreenSlider.tsx'),
  'utf8',
);
assert.match(sliderSource, /draggingRef/);
assert.match(sliderSource, /startValueRef/);
assert.match(sliderSource, /sliderValueFromDrag/);
assert.doesNotMatch(
  sliderSource,
  /onPanResponderMove:\s*\(event\)\s*=>\s*applyPosition\(event\.nativeEvent\.locationX\)/,
);
const liveFullscreenSettingsSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', 'LiveFullscreenSettings.tsx'),
  'utf8',
);
assert.match(liveFullscreenSettingsSource, /Rotation speed/);
assert.match(liveFullscreenSettingsSource, /Spectrum bars/);
assert.match(liveFullscreenSettingsSource, /Circle horizontal position/);
assert.match(liveFullscreenSettingsSource, /Background horizontal position/);
assert.match(liveFullscreenSettingsSource, /Background vertical position/);
assert.match(liveFullscreenSettingsSource, /Reset circle transform/);
assert.match(liveFullscreenSettingsSource, /Reset background transform/);
assert.match(liveFullscreenSettingsSource, /paddingRight:\s*36/);
const circularSpectrumSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', 'CircularSpectrum.tsx'),
  'utf8',
);
assert.match(circularSpectrumSource, /rotationSpeedPct/);
assert.match(circularSpectrumSource, /barCount/);
assert.match(circularSpectrumSource, /resampleSpectrum/);
assert.match(circularSpectrumSource, /spectrumRotationPhase/);
assert.match(circularSpectrumSource, /outerEnergies: readonly number\[\]/);
assert.match(circularSpectrumSource, /innerEnergies: readonly number\[\]/);
assert.match(circularSpectrumSource, /spectrumBarRadii/);
assert.doesNotMatch(circularSpectrumSource, /const rotationPhase = spectrumPhaseAtTime/);
const backgroundSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', 'LiveFullscreenBackground.tsx'),
  'utf8',
);
assert.match(backgroundSource, /backgroundOffsetXPct/);
assert.match(backgroundSource, /backgroundOffsetYPct/);
const gestureLayerSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'live-fullscreen', 'LiveFullscreenGestureLayer.tsx'),
  'utf8',
);
assert.match(gestureLayerSource, /nativeEvent\.touches/);
assert.match(gestureLayerSource, /twoTouchMetrics/);
assert.match(gestureLayerSource, /onTransformPreview/);
assert.match(gestureLayerSource, /onTransformCommit/);
const fullscreenScreenPath = path.join(
  scriptDir,
  '..',
  'src',
  'components',
  'live-fullscreen',
  'LiveFullscreenScreen.tsx',
);
const fullscreenScreenSource = fs.readFileSync(fullscreenScreenPath, 'utf8');
assert.match(fullscreenScreenSource, /captureVisualReplyBaseline/);
assert.match(fullscreenScreenSource, /useSpectrumPlayback/);
assert.match(fullscreenScreenSource, /verticalPositionPct/);
assert.match(fullscreenScreenSource, /imageSpectrumOpacityPct/);
assert.match(fullscreenScreenSource, /transientSettings/);
assert.match(fullscreenScreenSource, /chooseTransformTarget/);
assert.match(fullscreenScreenSource, /onSettingsChange/);
assert.match(fullscreenScreenSource, /createMicSpectrumHistoryState/);
assert.match(fullscreenScreenSource, /advanceMicSpectrumHistoryState/);
assert.match(fullscreenScreenSource, /microphoneEnergies: micSpectrum\.energies/);
assert.doesNotMatch(fullscreenScreenSource, /microphoneLevel:/);
assert.doesNotMatch(fullscreenScreenSource, /microphoneVuSpectrum/);
assert.equal(
  (fullscreenScreenSource.match(/<CircularSpectrum/g) || []).length,
  1,
  'TTS and microphone bars must share one circle',
);
assert.doesNotMatch(fullscreenScreenSource, /circleSizePct=\{82\}/);
assert.doesNotMatch(
  fullscreenScreenSource,
  /proceduralSpectrum\(directionalSeconds, Math\.max\(0\.12, inputLevel\)\)/,
);
const appSource = fs.readFileSync(path.join(scriptDir, '..', 'App.tsx'), 'utf8');
assert.match(appSource, /import \{ LiveFullscreenScreen \}/);
assert.match(appSource, /<LiveFullscreenScreen/);
assert.match(appSource, /setLiveFullscreenSettings/);
assert.match(appSource, /audioQueue\.preparedChunk/);
assert.match(
  appSource,
  /microphoneActive=\{recorder\.liveEnabled\s*\|\|\s*recorder\.recording\}/,
);
assert.match(
  appSource,
  /microphoneSpeechDetected=\{recorder\.recording\s*\|\|\s*recorder\.livePhase === 'speech'\}/,
);
assert.match(appSource, /meteringRevision=\{recorder\.meteringRevision\}/);
const composerSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'Composer.tsx'),
  'utf8',
);
assert.match(composerSource, /onFullscreenPress/);
const photoCaptureSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'components', 'ChatPhotoCapture.tsx'),
  'utf8',
);
assert.match(photoCaptureSource, /onSent\?: \(\) => void/);

console.log('Live Fullscreen policy smoke passed.');
