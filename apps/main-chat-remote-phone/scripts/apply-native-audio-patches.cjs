const path = require('node:path');
const { spawnSync } = require('node:child_process');

function patchScripts(env = process.env) {
  if (env.EAS_BUILD_PLATFORM === 'android') return ['apply-android-audio-live-patch.cjs'];
  if (env.EAS_BUILD_PLATFORM === 'ios') return ['apply-ios-audio-stop-patch.cjs', 'apply-ios-video-audio-patch.cjs'];
  return ['apply-ios-audio-stop-patch.cjs', 'apply-ios-video-audio-patch.cjs', 'apply-android-audio-live-patch.cjs'];
}

function runPatchScript(script, env) {
  const result = spawnSync(process.execPath, [path.join(__dirname, script)], {
    env,
    stdio: 'inherit',
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${script} failed with exit code ${result.status ?? 'unknown'}`);
}

function applyNativePatches(env = process.env, runner = runPatchScript,
  verifyAV = () => require('./apply-native-av-patch.cjs').verifyIOS()) {
  let verifiedAV = false;
  if (env.EAS_BUILD_PLATFORM === 'ios') {
    // Expo may run npm install again after prebuild. Do not feed the exact AV
    // after-image into the older base-only checker. Partial/unknown trees still
    // go through that checker and fail closed; there is no marker-file bypass.
    try { verifyAV(); verifiedAV = true; } catch { /* First install or invalid tree. */ }
  }
  for (const script of patchScripts(env)) {
    if (verifiedAV && script === 'apply-ios-audio-stop-patch.cjs') continue;
    runner(script, env);
  }
  runner('apply-native-av-patch.cjs', env);
}

if (require.main === module) {
  try {
    applyNativePatches();
    // Shared JS list geometry is installed alongside the existing native patches.
    console.log('[list-metrics-patch]', require('./apply-list-metrics-patch.cjs').applyPatch());
  } catch (error) {
    console.error('[native-audio-patches]', error.message);
    process.exitCode = 1;
  }
}

module.exports = { applyNativePatches, patchScripts, runPatchScript };
