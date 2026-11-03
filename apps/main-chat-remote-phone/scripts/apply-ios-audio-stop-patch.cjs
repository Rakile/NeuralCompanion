const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const TARGETS = ['ios/AudioModule.swift', 'ios/AudioPlayer.swift', 'ios/MediaController.swift', 'ios/NCPlaybackGuard.swift',
  'ios/ExpoAudio.podspec'];
const ADDED_TARGETS = ['ios/NCPlaybackGuard.swift'];
const REPAIR = 'Restore the exact expo-audio 1.1.1 installation, then apply this maintained patch again. Do not hand-edit or fuzzy-apply dependency sources.';
const hash = data => crypto.createHash('sha256').update(data).digest('hex');
function fail(message) { throw new Error(`${message}. ${REPAIR}`); }
function rejectLinks(target) {
  let cursor = path.resolve(target);
  while (true) {
    try {
      if (fs.lstatSync(cursor).isSymbolicLink()) fail(`Refusing symlink/junction path ${cursor}`);
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    const parent = path.dirname(cursor);
    if (parent === cursor) break;
    cursor = parent;
  }
}
function inspect(options = {}) {
  const env = options.env || process.env;
  if (env.EAS_BUILD_PLATFORM === 'android') return { skipped: true, reason: 'android' };
  const moduleRoot = path.resolve(options.moduleRoot || path.join(__dirname, '../node_modules/expo-audio'));
  const patchRoot = path.resolve(options.patchRoot || path.join(__dirname, '../patches/expo-audio-1.1.1-ios-stop'));
  rejectLinks(moduleRoot); rejectLinks(patchRoot);
  const manifest = JSON.parse(fs.readFileSync(path.join(patchRoot, 'manifest.json'), 'utf8'));
  if (manifest.version !== '1.1.1' || manifest.package !== 'expo-audio' || manifest.format !== 1) fail('Unsupported patch version/manifest');
  const version = JSON.parse(fs.readFileSync(path.join(moduleRoot, 'package.json'), 'utf8')).version;
  if (version !== manifest.version) fail(`Unexpected expo-audio version ${version}`);
  if (!Array.isArray(manifest.files) || manifest.files.length !== TARGETS.length ||
      new Set(manifest.files.map(f => f.path)).size !== TARGETS.length ||
      manifest.files.some(f => !TARGETS.includes(f.path))) fail('Unexpected native target path in manifest');
  const files = manifest.files.map(entry => {
    const destination = path.resolve(moduleRoot, entry.path);
    if (!destination.startsWith(path.join(moduleRoot, 'ios') + path.sep)) fail('Target path escapes iOS directory');
    const artifact = path.join(patchRoot, entry.path);
    rejectLinks(destination); rejectLinks(artifact);
    if (entry.previousAfter !== undefined &&
        (typeof entry.previousAfter !== 'string' || !/^[a-f0-9]{64}$/.test(entry.previousAfter) ||
          entry.previousAfter === entry.before || entry.previousAfter === entry.after)) fail('Invalid previous generation hash');
    if (!/^[a-f0-9]{64}$/.test(entry.after) || (entry.before !== null && !/^[a-f0-9]{64}$/.test(entry.before))) fail('Invalid manifest hash');
    if (ADDED_TARGETS.includes(entry.path) !== (entry.before === null)) fail('Unexpected native source before-image');
    const data = fs.readFileSync(artifact);
    if (hash(data) !== entry.after) fail(`Unexpected patch artifact ${entry.path}`);
    if (entry.license !== 'MIT') fail('Unexpected source license');
    let actual = null;
    if (fs.existsSync(destination)) {
      if (!fs.lstatSync(destination).isFile()) fail(`Unexpected target type ${entry.path}`);
      actual = hash(fs.readFileSync(destination));
    }
    if (actual !== entry.before && actual !== entry.after && actual !== entry.previousAfter) fail(`Unexpected source ${entry.path}`);
    return { destination, data, before: actual === entry.before, after: actual === entry.after,
      previous: actual === (entry.previousAfter ?? entry.after) };
  });
  const pristine = files.every(f => f.before);
  const applied = files.every(f => f.after);
  // The previous vector includes unchanged entries at their current after hash.
  // Accept only a complete generation, never individually recognizable mixtures.
  const previous = manifest.files.some(entry => entry.previousAfter !== undefined) && files.every(file => file.previous);
  if (!pristine && !applied && !previous) fail('Partial/mixed patch application');
  return { files, applied };
}
function verifyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (!state.applied) fail('Required iOS playback patch is not applied');
  return { state: 'verified' };
}
function applyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (state.applied) return { state: 'already-applied' };
  // All hashes/paths are checked before any write. A process crash across files is
  // intentionally detected as partial state on the next install/config verification.
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
    if (args.length > 1 || (args.length === 1 && args[0] !== '--verify')) throw new Error('Usage: apply-ios-audio-stop-patch.cjs [--verify]');
    console.log('[ios-audio-stop-patch]', args[0] === '--verify' ? verifyPatch() : applyPatch());
  } catch (error) {
    console.error('[ios-audio-stop-patch]', error.message);
    process.exitCode = 1;
  }
}
module.exports = { applyPatch, verifyPatch };
