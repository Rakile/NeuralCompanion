// NeuralCompanion, MIT.
#import "NCSilentAudioDevice.h"
#include "NCDecoderPump.h"
#include <memory>

@implementation NCSilentAudioDevice {
  id<RTCAudioDeviceDelegate> _delegate;
  std::unique_ptr<nc::DecoderPump> _pump;
  BOOL _playoutInitialized;
}
- (double)deviceInputSampleRate { return 48000; }
- (double)deviceOutputSampleRate { return 48000; }
- (NSTimeInterval)inputIOBufferDuration { return 0.01; }
- (NSTimeInterval)outputIOBufferDuration { return 0.01; }
- (NSInteger)inputNumberOfChannels { return 1; }
- (NSInteger)outputNumberOfChannels { return 1; }
- (NSTimeInterval)inputLatency { return 0; }
- (NSTimeInterval)outputLatency { return 0; }
- (BOOL)isInitialized { return _delegate != nil; }
- (BOOL)isPlayoutInitialized { return _playoutInitialized; }
- (BOOL)isPlaying { return _pump && _pump->Running(); }
- (BOOL)isRecordingInitialized { return NO; }
- (BOOL)isRecording { return NO; }
- (BOOL)initializeRecording { return NO; }
- (BOOL)startRecording { return NO; }
- (BOOL)stopRecording { return YES; }

- (BOOL)initializeWithDelegate:(id<RTCAudioDeviceDelegate>)delegate {
  if (!delegate || _delegate) return NO;
  _delegate = delegate;
  return YES;
}
- (BOOL)initializePlayout {
  if (!_delegate) return NO;
  _playoutInitialized = YES;
  return YES;
}
- (BOOL)startPlayout {
  if (!_delegate || !_playoutInitialized) return NO;
  if (_pump) return _pump->Running();
  RTCAudioDeviceGetPlayoutDataBlock pull = [_delegate.getPlayoutData copy];
  if (!pull) return NO;
  _pump = std::make_unique<nc::DecoderPump>([pull](int16_t *pcm, size_t frames, int64_t sample) {
    @autoreleasepool {
      AudioUnitRenderActionFlags flags = 0;
      AudioTimeStamp time = {};
      time.mSampleTime = sample;
      time.mFlags = kAudioTimeStampSampleTimeValid;
      AudioBufferList buffers = {};
      buffers.mNumberBuffers = 1;
      buffers.mBuffers[0] = {1, static_cast<UInt32>(frames * sizeof(int16_t)), pcm};
      // The mixed buffer is intentionally discarded by DecoderPump. Only the
      // timestamped per-track sinks may feed a separately admitted output owner.
      return pull(&flags, &time, 0, static_cast<UInt32>(frames), &buffers) == noErr;
    }
  });
  return _pump->Start();
}
- (BOOL)stopPlayout {
  if (_pump) {
    _pump->Stop();  // Join before releasing delegate or permitting a new thread.
    _pump.reset();
    id<RTCAudioDeviceDelegate> delegate = _delegate;
    [delegate dispatchSync:^{ [delegate notifyAudioOutputInterrupted]; }];
  }
  return YES;
}
- (BOOL)terminateDevice {
  [self stopPlayout];
  _playoutInitialized = NO;
  _delegate = nil;
  return YES;
}
- (void)dealloc {
  // Do not dispatch back to the ADM from dealloc. Normal teardown terminates it
  // first; this last join merely keeps a borrowed decoder block from outliving us.
  if (_pump) _pump->Stop();
}
@end
