import { requireOptionalNativeModule } from 'expo';
import { AppRegistry, Platform } from 'react-native';
import { pulseBackgroundClock } from '../utils/backgroundClock';

// Native owns the lifetime, audio and notification. This keeps RN's existing
// queue/poll timers running after Activity.onPause; it does not start another app.
export function registerBackgroundPlayback(): void {
  if (Platform.OS !== 'android') return;
  const clock = requireOptionalNativeModule<{
    playbackClockVersion?(): number;
    isPlaybackServiceActive(generation: number): boolean;
    addListener(event: string, listener: (event: {generation: number}) => void): {remove(): void};
  }>('NcLiveCapture');
  if (clock?.playbackClockVersion?.() === 1) {
    clock.addListener('playbackClock', ({generation}) => {
      if (Number.isSafeInteger(generation) && generation > 0 && clock.isPlaybackServiceActive(generation)) pulseBackgroundClock();
    });
  }
  AppRegistry.registerHeadlessTask('NCReplyPlayback', () => async ({ generation }: { generation: number }) => {
    if (!Number.isSafeInteger(generation) || generation < 1) return;
    const native = requireOptionalNativeModule<{
      isPlaybackServiceActive(generation: number): boolean;
    }>('NcLiveCapture');
    while (native?.isPlaybackServiceActive(generation)) {
      await new Promise<void>(resolve => setTimeout(resolve, 1000));
    }
  });
}
