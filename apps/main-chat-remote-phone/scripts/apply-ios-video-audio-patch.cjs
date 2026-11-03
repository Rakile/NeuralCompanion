const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

const TARGET = 'ios/VideoManager.swift';
const REPAIR = 'Restore the exact expo-video 3.0.16 installation, then reapply this maintained patch. Do not fuzzy-apply or overwrite unknown native sources.';
// Git may check out these text artifacts with CRLF on Windows. Native source
// integrity is identical across line endings; every other byte stays checked.
const hash = data => crypto.createHash('sha256').update(data.toString('utf8').replace(/\r\n/g, '\n')).digest('hex');
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
    if (parent === cursor) return;
    cursor = parent;
  }
}
function inspect(options = {}) {
  const env = options.env || process.env;
  if (env.EAS_BUILD_PLATFORM === 'android') return { skipped: true, reason: 'android' };
  const moduleRoot = path.resolve(options.moduleRoot || path.join(__dirname, '../node_modules/expo-video'));
  const patchRoot = path.resolve(options.patchRoot || path.join(__dirname, '../patches/expo-video-3.0.16-ios-audio'));
  const manifestPath = path.join(patchRoot, 'manifest.json');
  const packagePath = path.join(moduleRoot, 'package.json');
  rejectLinks(manifestPath); rejectLinks(packagePath);
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (manifest.format !== 1 || manifest.package !== 'expo-video' || manifest.version !== '3.0.16') fail('Unexpected patch manifest');
  const version = JSON.parse(fs.readFileSync(packagePath, 'utf8')).version;
  if (version !== manifest.version) fail(`Unexpected expo-video version ${version}`);
  if (!Array.isArray(manifest.files) || manifest.files.length !== 1 || manifest.files[0]?.path !== TARGET) fail('Unexpected native target path');
  const entry = manifest.files[0];
  if (!/^[a-f0-9]{64}$/.test(entry.before) || !/^[a-f0-9]{64}$/.test(entry.after) || entry.before === entry.after) fail('Invalid manifest hash');
  if (entry.license !== 'MIT') fail('Unexpected source license');
  const destination = path.join(moduleRoot, TARGET);
  const artifact = path.join(patchRoot, TARGET);
  rejectLinks(destination); rejectLinks(artifact);
  if (!fs.lstatSync(destination).isFile() || !fs.lstatSync(artifact).isFile()) fail('Unexpected source type');
  const data = fs.readFileSync(artifact);
  if (hash(data) !== entry.after) fail('Unexpected patch artifact');
  const actual = hash(fs.readFileSync(destination));
  if (actual !== entry.before && actual !== entry.after) fail('Unexpected source VideoManager.swift');
  return { destination, data, applied: actual === entry.after };
}
function verifyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (!state.applied) fail('Required iOS silent-video patch is not applied');
  return { state: 'verified' };
}
function applyPatch(options = {}) {
  const state = inspect(options);
  if (state.skipped) return state;
  if (state.applied) return { state: 'already-applied' };
  // A single checked source replacement; partial writes are rejected on retry.
  fs.writeFileSync(state.destination, state.data);
  verifyPatch(options);
  return { state: 'applied' };
}
if (require.main === module) {
  try {
    const args = process.argv.slice(2);
    if (args.length > 1 || (args.length === 1 && args[0] !== '--verify')) throw new Error('Usage: apply-ios-video-audio-patch.cjs [--verify]');
    console.log('[ios-video-audio-patch]', args[0] === '--verify' ? verifyPatch() : applyPatch());
  } catch (error) {
    console.error('[ios-video-audio-patch]', error.message);
    process.exitCode = 1;
  }
}
module.exports = { applyPatch, verifyPatch };
