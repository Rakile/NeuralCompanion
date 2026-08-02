import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  audioHistoryAfterBoundary,
  mergeAudioSnapshot,
  mergeRemoteSnapshot,
  nextUnseenAudioChunk,
} from '../src/utils/audioFastStart.ts';
import * as audioFastStart from '../src/utils/audioFastStart.ts';

const originalState = {
  status_line: 'Speaking',
  media: {
    available: true,
    generation: 1,
    items: [{ id: 'one', url_path: '/api/audio/file/one', index: 1 }],
  },
};
const nextAudio = {
  available: true,
  status: 'ready',
  generation: 2,
  items: [
    { id: 'one', url_path: '/api/audio/file/one', index: 1 },
    { id: 'two', url_path: '/api/audio/file/two', index: 2 },
  ],
};

const merged = mergeAudioSnapshot(originalState, nextAudio);
assert.notEqual(merged, originalState);
assert.equal(merged?.status_line, 'Speaking');
assert.equal(merged?.media?.generation, 2);
assert.equal(merged?.media?.items?.length, 2);

assert.equal(mergeAudioSnapshot(originalState, { items: 'bad' }), originalState);
assert.equal(
  mergeAudioSnapshot(originalState, {
    generation: 3,
    items: [{ id: '', url_path: '/api/audio/file/bad', index: 1 }],
  }),
  originalState,
);
assert.equal(mergeAudioSnapshot(null, nextAudio), null);

assert.equal(nextUnseenAudioChunk(nextAudio.items, new Set(['one']))?.id, 'two');
assert.equal(nextUnseenAudioChunk(nextAudio.items, new Set(), 'one')?.id, 'two');
assert.equal(nextUnseenAudioChunk(nextAudio.items, new Set(['one', 'two'])), undefined);

const generationFive = {
  ...originalState,
  media: {
    available: false,
    generation: 5,
    items: [],
  },
};
const staleGenerationFour = {
  ...originalState,
  media: {
    available: true,
    generation: 4,
    items: [{ id: 'old', url_path: '/api/audio/file/old', index: 1 }],
  },
};
assert.equal(
  mergeRemoteSnapshot(generationFive, staleGenerationFour).media.generation,
  5,
);
assert.equal(
  mergeAudioSnapshot(generationFive, staleGenerationFour.media)?.media?.generation,
  5,
);

const playedBeforeEmptySnapshot = new Set(['already-played']);
assert.deepEqual(
  [...audioHistoryAfterBoundary(playedBeforeEmptySnapshot, 'empty_snapshot')],
  ['already-played'],
);
assert.equal(
  audioHistoryAfterBoundary(playedBeforeEmptySnapshot, 'connection_changed').size,
  0,
);
assert.equal(
  audioHistoryAfterBoundary(playedBeforeEmptySnapshot, 'explicit_reset').size,
  0,
);

assert.equal(typeof audioFastStart.refreshAudioChunkMetadata, 'function');
const pendingSpectrumChunk = {
  id: 'pending-spectrum',
  url_path: '/api/audio/file/pending-spectrum',
  spectrum_status: 'pending',
};
const readySpectrumChunk = {
  ...pendingSpectrumChunk,
  spectrum_status: 'ready',
  spectrum_url_path: '/api/audio/spectrum/pending-spectrum',
};
assert.deepEqual(
  audioFastStart.refreshAudioChunkMetadata(
    pendingSpectrumChunk,
    [readySpectrumChunk],
  ),
  readySpectrumChunk,
);
assert.equal(
  audioFastStart.refreshAudioChunkMetadata(
    pendingSpectrumChunk,
    [{ id: 'different', url_path: '/api/audio/file/different' }],
  ),
  pendingSpectrumChunk,
);
assert.equal(typeof audioFastStart.shouldInterruptForPhoneText, 'function');
assert.equal(audioFastStart.shouldInterruptForPhoneText('idle', ''), false);
assert.equal(audioFastStart.shouldInterruptForPhoneText('listening', ''), false);
assert.equal(audioFastStart.shouldInterruptForPhoneText('thinking', ''), true);
assert.equal(audioFastStart.shouldInterruptForPhoneText('speaking', ''), true);
assert.equal(audioFastStart.shouldInterruptForPhoneText('idle', 'chunk-1'), true);
assert.equal(typeof audioFastStart.createLatestAudioSampleBuffer, 'function');
const latestSample = audioFastStart.createLatestAudioSampleBuffer();
assert.equal(latestSample.get(), null);
const liveSample = [0.1, 0.4, 0.8];
latestSample.set(liveSample);
assert.equal(latestSample.get(), liveSample);
latestSample.set(null);
assert.equal(latestSample.get(), null);

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const connectionSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'useRemoteConnection.ts'),
  'utf8',
);
assert.match(connectionSource, /message\.type === 'audio'/);
assert.match(connectionSource, /mergeAudioSnapshot/);
assert.match(connectionSource, /text_turn_submit_started/);
assert.match(connectionSource, /text_turn_accepted/);

const audioQueueSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'useAudioQueue.ts'),
  'utf8',
);
assert.match(audioQueueSource, /const prepared = useRef</);
assert.match(audioQueueSource, /downloadFirst: true/);
assert.match(audioQueueSource, /PLAYBACK_STATUS_INTERVAL_MS = 100/);
assert.match(audioQueueSource, /updateInterval: PLAYBACK_STATUS_INTERVAL_MS/);
assert.match(audioQueueSource, /releasePrepared/);
assert.match(audioQueueSource, /audio_player_prepared/);
assert.match(audioQueueSource, /audio_playback_started/);
assert.match(audioQueueSource, /nextUnseenAudioChunk/);

const recorderSource = fs.readFileSync(
  path.join(scriptDir, '..', 'src', 'hooks', 'useRecorder.ts'),
  'utf8',
);
assert.match(recorderSource, /stt_upload_started/);
assert.match(recorderSource, /stt_upload_completed/);

console.log('Audio fast-start policy smoke passed.');
