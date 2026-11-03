const path = require('node:path');
const configPlugins = require('expo/config-plugins');

const EXPO_AUDIO_TEST_POD = "pod 'ExpoAudio', :path => '../node_modules/expo-audio/ios', :testspecs => ['NCPlaybackAdapters']";

function containingTarget(contents, marker) {
  const candidates = [...contents.matchAll(/^([ \t]*)target\s+['"][^'"]+['"]\s+do[ \t]*$/gm)]
    .filter((target) => target.index < marker.index && target[1].length < marker[1].length)
    .map((target) => {
      const bodyStart = target.index + target[0].length;
      const escapedIndent = target[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const closing = new RegExp(`^${escapedIndent}end[ \\t]*$`, 'gm').exec(contents.slice(bodyStart));
      return { bodyStart, bodyEnd: closing ? bodyStart + closing.index : -1 };
    })
    .filter((target) => target.bodyEnd > marker.index);
  if (candidates.length !== 1) {
    throw new Error('Unsupported generated iOS Podfile: use_expo_modules! must be inside one concrete open app target.');
  }
  return candidates[0];
}

function enrollExpoAudioAdapterTests(contents) {
  const useExpoModules = [...contents.matchAll(/^(\s*)use_expo_modules!\s*$/gm)];
  if (useExpoModules.length !== 1) {
    throw new Error('Unsupported generated iOS Podfile: expected exactly one use_expo_modules! inside the app target.');
  }
  const target = containingTarget(contents, useExpoModules[0]);

  const existingExpoAudio = [...contents.matchAll(/^([ \t]*)pod\s+['"]ExpoAudio['"].*$/gm)];
  if (existingExpoAudio.length > 0) {
    const exact = existingExpoAudio.length === 1 && existingExpoAudio[0][0].trim() === EXPO_AUDIO_TEST_POD;
    let declarationTarget;
    try {
      declarationTarget = exact ? containingTarget(contents, existingExpoAudio[0]) : null;
    } catch { /* Report all invalid existing declarations through one stable error. */ }
    const sameTarget = declarationTarget?.bodyStart === target.bodyStart
      && declarationTarget?.bodyEnd === target.bodyEnd;
    if (!exact || !sameTarget || existingExpoAudio[0].index > useExpoModules[0].index) {
      throw new Error('Unsupported generated iOS Podfile: conflicting ExpoAudio declaration.');
    }
    return contents;
  }

  const declaration = `${useExpoModules[0][1]}${EXPO_AUDIO_TEST_POD}\n`;
  return contents.slice(0, useExpoModules[0].index) + declaration + contents.slice(useExpoModules[0].index);
}

function defaultVerifyPatch({ projectRoot }) {
  const verifyPatch = process.env.EXPO_PUBLIC_NC_AV_TRACKS !== '0'
    ? require('../scripts/apply-native-av-patch.cjs').verifyIOS
    : require('../scripts/apply-ios-audio-stop-patch.cjs').verifyPatch;
  verifyPatch({
    moduleRoot: path.join(projectRoot, 'node_modules', 'expo-audio'),
    patchRoot: path.join(projectRoot, 'patches', 'expo-audio-1.1.1-ios-stop'),
    env: process.env,
  });
}

function createWithIosBackgroundLive(plugins, verifyPatch = defaultVerifyPatch) {
  return function withIosBackgroundLive(config) {
    config = plugins.withInfoPlist(config, (config) => {
      config.modResults.UIBackgroundModes = Array.from(new Set([
        ...(config.modResults.UIBackgroundModes || []), 'audio',
      ]));
      return config;
    });
    return plugins.withPodfile(config, (config) => {
      verifyPatch({ projectRoot: config.modRequest.projectRoot });
      config.modResults.contents = enrollExpoAudioAdapterTests(config.modResults.contents);
      return config;
    });
  };
}

module.exports = createWithIosBackgroundLive(configPlugins);
module.exports.createWithIosBackgroundLive = createWithIosBackgroundLive;
module.exports.enrollExpoAudioAdapterTests = enrollExpoAudioAdapterTests;
module.exports.defaultVerifyPatch = defaultVerifyPatch;
