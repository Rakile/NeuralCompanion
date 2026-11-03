#import "NCAVAudioPcmDevice.h"
#import <AVFoundation/AVFoundation.h>

@implementation NCAVAudioPcmDevice {
  AVAudioEngine *_engine;
  AVAudioPlayerNode *_player;
  AVAudioFormat *_format;
  id _configurationObserver;
  float _volume;
}
- (instancetype)init {
  if ((self = [super init])) {
    _volume = 1;
  }
  return self;
}
- (BOOL)prepare:(NSError **)error {
  // The peer can exist before Live changes the audio route. Build its output
  // graph only when an authenticated reply actually needs it, not on connect.
  if (!_engine) {
    _engine = [AVAudioEngine new]; _player = [AVAudioPlayerNode new];
    _format = [[AVAudioFormat alloc] initStandardFormatWithSampleRate:48000 channels:1];
    [_engine attachNode:_player];
    [_engine connect:_player to:_engine.mainMixerNode format:_format];
    _player.volume = _volume;
    // Capture THIS graph's callback, not a later graph's mutable invalidator.
    // The stream fences delayed notifications using its preparation epoch.
    dispatch_block_t invalidate = self.invalidated;
    _configurationObserver = [[NSNotificationCenter defaultCenter]
        addObserverForName:AVAudioEngineConfigurationChangeNotification object:_engine queue:nil
        usingBlock:^(NSNotification *notification) {
          // Notify the owning adapter, which invalidates before flushing. Never
          // restart a graph in response to a route/configuration notification.
          if (invalidate) invalidate();
        }];
  }
  [_engine prepare]; return [_engine startAndReturnError:error];
}
- (void)play { if (_engine.isRunning) [_player play]; }
- (BOOL)isPlaying { return _engine.isRunning && _player.isPlaying; }
- (void)stop { [_player stop]; }
- (void)releaseIdle {
  // Called only after all shared-stream leases drain, never from the engine's
  // configuration callback. Keep the peer/idle video, not an idle audio engine.
  if (_configurationObserver) [[NSNotificationCenter defaultCenter] removeObserver:_configurationObserver];
  _configurationObserver = nil;
  [_player stop]; [_engine stop];
  _player = nil; _engine = nil; _format = nil;
}
- (float)volume { return _volume; }
- (void)setVolume:(float)volume { _volume = volume; _player.volume = volume; }
- (void)schedulePCM:(NSData *)data completion:(dispatch_block_t)completion {
  AVAudioFrameCount frames = (AVAudioFrameCount)(data.length / sizeof(int16_t));
  AVAudioPCMBuffer *buffer = [[AVAudioPCMBuffer alloc] initWithPCMFormat:_format frameCapacity:frames];
  buffer.frameLength = frames;
  const int16_t *input = (const int16_t *)data.bytes;
  float *output = buffer.floatChannelData[0];
  for (AVAudioFrameCount i = 0; i < frames; ++i) output[i] = input[i] / 32768.0f;
  [_player scheduleBuffer:buffer atTime:nil options:0
      completionCallbackType:AVAudioPlayerNodeCompletionDataPlayedBack
      completionHandler:^(AVAudioPlayerNodeCompletionCallbackType type) {
        if (type == AVAudioPlayerNodeCompletionDataPlayedBack) completion();
      }];
}
- (void)dealloc {
  if (_configurationObserver) [[NSNotificationCenter defaultCenter] removeObserver:_configurationObserver];
  [_player stop]; [_engine stop];
}
@end
