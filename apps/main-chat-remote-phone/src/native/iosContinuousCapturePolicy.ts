import { Platform } from 'react-native';

// Temporary development gate shared by capture composition and player creation.
// Keep direct property access for Expo's build-time environment substitution.
const testContinuousCapture = __DEV__
  && process.env.EXPO_PUBLIC_NC_IOS_CONTINUOUS_CAPTURE === '1';

// Android continuous capture ships only in the explicitly opted-in custom
// build. Unlike the temporary iOS development gate, release builds are valid.
const androidContinuousCapture =
  process.env.EXPO_PUBLIC_NC_ANDROID_CONTINUOUS_CAPTURE === '1';

export const iosContinuousCaptureEnabled = Platform.OS === 'ios' && testContinuousCapture;
export const androidContinuousCaptureEnabled = Platform.OS === 'android' && androidContinuousCapture;
export const continuousCaptureEnabled = iosContinuousCaptureEnabled || androidContinuousCaptureEnabled;

type AndroidContinuousCapabilities = {
  available?: boolean;
  backgroundLiveVersion?: number;
  playbackGuardVersion?: number;
  stopListeningVersion?: number;
  foregroundReplyControlsVersion?: number;
};

let androidRuntimeReady = false;

export function completeAndroidContinuousCaptureCapabilities(capabilities: AndroidContinuousCapabilities): boolean {
  return capabilities.available === true
    && capabilities.backgroundLiveVersion === 1
    && capabilities.playbackGuardVersion === 1
    && capabilities.stopListeningVersion === 1
    && capabilities.foregroundReplyControlsVersion === 1;
}

export function androidBackgroundLivePlatformEligible(): boolean {
  const apiLevel = typeof Platform.Version === 'number'
    ? Platform.Version : Number.parseInt(String(Platform.Version), 10);
  return Platform.OS === 'android' && Number.isFinite(apiLevel) && apiLevel >= 31;
}

export function setAndroidContinuousCaptureRuntimeReady(ready: boolean): void {
  androidRuntimeReady = androidContinuousCaptureEnabled && ready === true;
}

export function androidContinuousCaptureRuntimeEnabled(): boolean {
  return androidContinuousCaptureEnabled && androidRuntimeReady;
}

export function continuousCaptureRuntimeEnabled(): boolean {
  return iosContinuousCaptureEnabled || androidContinuousCaptureRuntimeEnabled();
}
