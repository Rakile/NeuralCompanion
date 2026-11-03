const { withMainApplication, withAppBuildGradle, withAndroidManifest, withDangerousMod } = require('expo/config-plugins');
const { registerPackage, addDependencies, stageNative } = require('./phone-speech-build.cjs');
module.exports = function withPhoneNativeAudio(config) {
  config = withMainApplication(config, (mod) => {
    mod.modResults.contents = registerPackage(mod.modResults.contents);
    return mod;
  });
  config = withAppBuildGradle(config, (mod) => {
    mod.modResults.contents = addDependencies(mod.modResults.contents);
    return mod;
  });
  config = withAndroidManifest(config, (mod) => {
    const manifest = mod.modResults.manifest;
    manifest.queries ??= [];
    for (const action of ['android.speech.RecognitionService', 'android.intent.action.TTS_SERVICE']) {
      if (!manifest.queries.some((query) => query.intent?.some((intent) => intent.action?.some((entry) => entry.$['android:name'] === action)))) {
        manifest.queries.push({ intent: [{ action: [{ $: { 'android:name': action } }] }] });
      }
    }
    return mod;
  });
  return withDangerousMod(config, ['android', async (mod) => {
    await stageNative(mod.modRequest.projectRoot, mod.modRequest.platformProjectRoot);
    return mod;
  }]);
};
