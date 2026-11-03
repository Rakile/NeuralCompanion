// Strictly versioned AV enrollment, standard on both supported platforms.
const path = require('node:path');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { enrollIOS, enrollIOSAudio, enrollAndroid, enrollAndroidAudio } = require('../native-webrtc/enroll-module.cjs');
const appRoot = path.resolve(__dirname, '..');

function verifyIOS({ moduleRoot = path.join(appRoot, 'node_modules/expo-audio'), patchRoot = path.join(appRoot, 'patches/expo-audio-1.1.1-ios-stop') } = {}) {
  const root = path.resolve(moduleRoot, '../..'), nativeRoot = path.join(root, 'native-webrtc');
  enrollIOS({ moduleRoot: path.join(root, 'node_modules/react-native-webrtc'), nativeRoot, verifyOnly: true });
  enrollIOSAudio({ audioRoot: moduleRoot, nativeRoot, verifyOnly: true });
  // The two transformed files above are pinned to the maintained base hashes.
  // Every other existing guard/player/adapter source still must match its exact
  // original manifest. Opt-in does NOT waive verification of ownership fixes.
  const manifest = JSON.parse(fs.readFileSync(path.join(patchRoot, 'manifest.json'), 'utf8'));
  for (const entry of manifest.files) {
    if (['ios/AudioModule.swift', 'ios/ExpoAudio.podspec'].includes(entry.path)) continue;
    const actual = crypto.createHash('sha256').update(fs.readFileSync(path.join(moduleRoot, entry.path))).digest('hex');
    if (actual !== entry.after) throw new Error(`Unverified original audio adapter: ${entry.path}`);
  }
  return { applied: true };
}

function apply() {
  const platform = process.env.EAS_BUILD_PLATFORM || (process.platform === 'darwin' ? 'ios' : 'android');
  if (!['ios', 'android'].includes(platform)) throw new Error('Set EAS_BUILD_PLATFORM to explicitly enroll a native AV build');
  if (platform === 'ios') { enrollIOS(); enrollIOSAudio(); verifyIOS(); }
  else { enrollAndroid(); enrollAndroidAudio(); }
  console.log('[native-av]', platform, 'buffered local playback enrolled with the standard WebRTC SDK.');
}
if (require.main === module) { try { apply(); } catch (error) { console.error('[native-av]', error.message); process.exitCode = 1; } }
module.exports = { verifyIOS, apply };
