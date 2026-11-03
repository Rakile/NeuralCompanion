const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const TARGETS = [
  'android/src/main/java/expo/modules/audio/NCProgressivePcmMediaSource.kt',
  'android/src/main/java/expo/modules/audio/NCProgressivePcmQueue.kt',
  'android/src/main/java/expo/modules/audio/NCCaptureRoute.kt',
  'android/src/main/java/expo/modules/audio/AudioRecorder.kt',
  'android/src/main/java/expo/modules/audio/NCManualDeparturePolicy.kt',
  'android/src/main/java/expo/modules/audio/NCOrderedIdleCache.kt',
  'android/src/main/java/expo/modules/audio/NCDiagnosticContract.kt',
  'android/src/main/java/expo/modules/audio/NCDiagnosticRecorder.kt',
  'android/src/main/java/expo/modules/audio/NCDiagnosticSchema.kt',
  'android/src/main/java/expo/modules/audio/NCDiagnosticPolicy.kt',
  'android/src/main/java/expo/modules/audio/NCDiagnosticPolicyData.kt',
  'android/src/main/java/expo/modules/audio/AudioModule.kt',
  'android/src/main/java/expo/modules/audio/AudioPlayer.kt',
  'android/src/main/java/expo/modules/audio/service/AudioControlsService.kt',
  'android/src/main/java/expo/modules/audio/NCPlaybackGuard.kt',
  'android/src/main/java/expo/modules/audio/NCMuxedTrialReceipt.kt',
  'android/src/main/java/expo/modules/audio/NCMuxedTrialPlayer.kt',
  'android/src/main/java/expo/modules/audio/NCMuxedTrialView.kt',
  'android/src/main/java/expo/modules/audio/NCOrderedCachedIdle.kt',
  'android/src/main/java/expo/modules/audio/NCOrderedCachedVideo.kt',
  'android/src/main/java/expo/modules/audio/NCMuxedTrialSourceOwner.kt',
  'android/src/main/java/expo/modules/audio/NCMuxedTrialReaderFence.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedPresentation.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedAudioRenderer.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedVideoRenderer.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedAudioSink.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedAuthority.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedQueueState.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedQueue.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedTailSource.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedJournal.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedOutputGate.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedSinkController.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedRequests.kt',
  'android/src/main/java/expo/modules/audio/NCContinuousMuxedRpc.kt',
  'android/src/main/java/expo/modules/audio/NCOrderedContinuation.kt',
  'android/src/main/java/expo/modules/audio/NCConnectionCueOutput.kt',
  'android/src/main/java/expo/modules/audio/NCSoundscapePolicy.kt',
  'android/src/main/java/expo/modules/audio/NCSoundscapeController.kt',
  'android/src/main/java/expo/modules/audio/NCSoundscapeFiles.kt',
  'android/src/main/java/expo/modules/audio/NCSoundscapeActivity.kt',
];
const REPAIR = 'Restore the exact expo-audio 1.1.1 installation, then apply this maintained patch again. Do not hand-edit dependency sources.';
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
function fail(message) { throw new Error(`${message}. ${REPAIR}`); }
function rejectLinks(target) {
  let cursor = path.resolve(target);
  while (true) {
    try { if (fs.lstatSync(cursor).isSymbolicLink()) fail(`Refusing symlink/junction path ${cursor}`); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
}
function inspect(options = {}) {
  const env = options.env || process.env;
  if (env.EAS_BUILD_PLATFORM === 'ios') return { skipped: true, reason: 'ios' };
  const moduleRoot = path.resolve(options.moduleRoot || path.join(__dirname, '../node_modules/expo-audio'));
  const patchRoot = path.resolve(options.patchRoot || path.join(__dirname, '../patches/expo-audio-1.1.1-android-live'));
  rejectLinks(moduleRoot); rejectLinks(patchRoot);
  const manifest = JSON.parse(fs.readFileSync(path.join(patchRoot, 'manifest.json'), 'utf8'));
  if (manifest.format !== 1 || manifest.package !== 'expo-audio' || manifest.version !== '1.1.1') fail('Unsupported patch manifest');
  if (JSON.parse(fs.readFileSync(path.join(moduleRoot, 'package.json'), 'utf8')).version !== manifest.version) fail('Unexpected expo-audio version');
  if (!Array.isArray(manifest.files) || manifest.files.length !== TARGETS.length ||
      new Set(manifest.files.map(file => file.path)).size !== TARGETS.length ||
      manifest.files.some(file => !TARGETS.includes(file.path))) fail('Unexpected native target path in manifest');
  const files = manifest.files.map(entry => {
    if (!entry.path.startsWith('android/') || !entry.artifact.startsWith('android/')) fail('Target path escapes Android directory');
    const destination = path.resolve(moduleRoot, entry.path);
    const artifact = path.resolve(patchRoot, entry.artifact);
    if (!destination.startsWith(path.join(moduleRoot, 'android') + path.sep) ||
        !artifact.startsWith(path.join(patchRoot, 'android') + path.sep)) fail('Target path escapes Android directory');
    rejectLinks(destination); rejectLinks(artifact);
    if (entry.previousAfter === null && entry.before !== null) fail('Invalid previous generation hash');
    // A newly maintained upstream file is pristine in the previous generation.
    // The complete-generation check below still rejects mixed installations.
    if (entry.previousAfter !== undefined && entry.previousAfter !== null &&
        (typeof entry.previousAfter !== 'string' || !/^[a-f0-9]{64}$/.test(entry.previousAfter) ||
          entry.previousAfter === entry.after)) fail('Invalid previous generation hash');
    if (!/^[a-f0-9]{64}$/.test(entry.after) || (entry.before !== null && !/^[a-f0-9]{64}$/.test(entry.before)) || entry.license !== 'MIT') fail('Invalid manifest entry');
    const data = fs.readFileSync(artifact);
    if (hash(data) !== entry.after) fail(`Unexpected patch artifact ${entry.artifact}`);
    let actual = null;
    if (fs.existsSync(destination)) {
      if (!fs.lstatSync(destination).isFile()) fail(`Unexpected target type ${entry.path}`);
      actual = hash(fs.readFileSync(destination));
    }
    if (actual !== entry.before && actual !== entry.after && actual !== entry.previousAfter) fail(`Unexpected source ${entry.path}`);
    return { destination, data, before: actual === entry.before, after: actual === entry.after,
      previous: actual === (entry.previousAfter === undefined ? entry.after : entry.previousAfter) ||
        (entry.before === null && entry.previousAfter === undefined && actual === null) };
  });
  const pristine = files.every(file => file.before);
  const applied = files.every(file => file.after);
  // The previous vector includes unchanged entries at their current after hash.
  // Accept only a complete generation, never individually recognizable mixtures.
  const previous = manifest.files.some(entry => entry.previousAfter !== undefined) && files.every(file => file.previous);
  if (!pristine && !applied && !previous) fail('Partial/mixed patch application');
  return { files, applied };
}
function verifyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (!state.applied) fail('Required Android playback patch is not applied');
  return { state: 'verified' };
}
function applyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (state.applied) return { state: 'already-applied' };
  for (const file of state.files) {
    fs.mkdirSync(path.dirname(file.destination), { recursive: true });
    fs.writeFileSync(file.destination, file.data);
  }
  verifyPatch(options);
  return { state: 'applied' };
}
if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    if (args.length > 1 || (args.length === 1 && args[0] !== '--verify')) throw new Error('Usage: apply-android-audio-live-patch.cjs [--verify]');
    console.log('[android-audio-live-patch]', args[0] === '--verify' ? verifyPatch() : applyPatch());
  } catch (error) {
    console.error('[android-audio-live-patch]', error.message);
    process.exitCode = 1;
  }
}
module.exports = { applyPatch, verifyPatch };
