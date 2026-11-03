#import "NCPcmOutput.h"
#include "../output/NCPlaybackWindow.h"
#include <cmath>
#include <memory>
#include <chrono>

@interface NCOutputSample : NSObject
@property(nonatomic) uint32_t end;
@property(nonatomic, copy) NSArray<NSNumber *> *values;
@end
@implementation NCOutputSample
@end

@interface NCPcmOutput ()
- (void)failWithReason:(NSString *)reason;
- (void)failDeviceWithReason:(NSString *)fallback;
@end

@implementation NCPcmOutput {
  id<NCPcmDevice> _device;
  NSRecursiveLock *_lock;
  dispatch_queue_t _completions;
  dispatch_source_t _watchdog;
  std::chrono::steady_clock::time_point _lastProgress;
  std::unique_ptr<nc::PlaybackWindow> _window;
  uint64_t _generation;
  uint64_t _lastStreamProgress;
  uint32_t _first;
  NSMutableArray<NCOutputSample *> *_samples;
  NSArray<NSNumber *> *_latestSample;
  BOOL _prepared, _started, _terminal, _failed;
  NSString *_failureReason;
  double _failureAtMs;
  dispatch_block_t _changed;
}
- (instancetype)initWithDevice:(id<NCPcmDevice>)device generation:(uint64_t)generation
                    firstSample:(uint32_t)first sampleCount:(uint32_t)count {
  if ((self = [super init])) {
    _device = device; _generation = generation; _lock = [NSRecursiveLock new];
    _first = first; _samples = [NSMutableArray new];
    _window = std::make_unique<nc::PlaybackWindow>(generation, first, count);
    _completions = dispatch_queue_create("nc.pcm.completion", DISPATCH_QUEUE_SERIAL);
    if ([_device respondsToSelector:@selector(setInvalidated:)]) {
      __weak NCPcmOutput *weakSelf = self;
      _device.invalidated = ^{
        NCPcmOutput *strongSelf = weakSelf;
        if (!strongSelf) return;
        [strongSelf failDeviceWithReason:@"device_invalidated"];
      };
    }
  }
  return self;
}
- (BOOL)prepare:(NSError **)error {
  [_lock lock];
  if (_terminal || _prepared) { BOOL result = !_terminal && _prepared; [_lock unlock]; return result; }
  [_lock unlock];
  // Session/engine setup may synchronously retire ownership. Never hold the
  // playback owner or output lock during it. Recheck before allowing start.
  BOOL prepared = [_device prepare:error];
  [_lock lock];
  if (!prepared || _terminal) {
    if (!prepared) [self failDeviceWithReason:@"device_prepare_failed"];
    _terminal = YES; _window->Stop(); [_device stop];
  } else _prepared = YES;
  BOOL result = _prepared && !_terminal;
  [_lock unlock]; return result;
}
- (BOOL)start {
  [_lock lock];
  BOOL result = NO;
  if (_prepared && !_terminal) {
    if (!_started && _window->Admit(_generation)) {
      _started = YES; [_device play];
      if (![_device isPlaying]) [self failDeviceWithReason:@"device_stopped"];
      if (!_terminal) {
        _lastProgress = std::chrono::steady_clock::now();
        if ([_device respondsToSelector:@selector(streamProgress)]) _lastStreamProgress = _device.streamProgress;
        _watchdog = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, _completions);
        __weak NCPcmOutput *weakSelf = self;
        dispatch_source_set_event_handler(_watchdog, ^{ [weakSelf checkStall]; });
        dispatch_source_set_timer(_watchdog, dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC),
                                 100 * NSEC_PER_MSEC, 10 * NSEC_PER_MSEC);
        dispatch_resume(_watchdog);
      }
    }
    result = _started && !_terminal && [_device isPlaying];
  }
  [_lock unlock]; return result;
}
- (BOOL)belongsToGeneration:(uint64_t)generation { return _generation == generation; }
- (void)stop {
  [_lock lock];
  // Invalidate BEFORE OS stop: AVAudioPlayerNode can invoke completion while
  // unscheduling, and that is not evidence that the discarded sound played.
  _terminal = YES; _window->Stop();
  if (_failureReason.length && [_device respondsToSelector:@selector(stopWithFailureReason:)]) [_device stopWithFailureReason:_failureReason];
  else [_device stop];
  [_samples removeAllObjects]; _latestSample = nil;
  [self cancelWatchdog];
  [self notifyChanged];
  [_lock unlock];
}
- (void)fail { [self failWithReason:@"unknown"]; }
- (void)failDeviceWithReason:(NSString *)fallback {
  // A queued completion/watchdog can observe a shared flush before its
  // invalidation callback. All device-failure paths retain the original cause.
  NSString *reason = [_device respondsToSelector:@selector(failureReason)] ? _device.failureReason : nil;
  [self failWithReason:reason.length ? reason : fallback];
}
- (void)failWithReason:(NSString *)reason {
  [_lock lock];
  // An explicit Stop or a later sibling cleanup cannot become a new failure.
  if (!_terminal) {
    _failureReason = [reason copy]; _failureAtMs = NSDate.date.timeIntervalSince1970 * 1000;
    _failed = YES; [self stop];
  }
  [_lock unlock];
}
- (void)receivePCM:(const int16_t *)pcm frames:(uint32_t)frames channels:(uint32_t)channels
       sampleRate:(uint32_t)rate timestamp:(uint32_t)timestamp clockRate:(uint32_t)clockRate
             valid:(BOOL)valid concealed:(BOOL)concealed {
  [_lock lock];
  if (!_started || _terminal) { [_lock unlock]; return; }
  if (!pcm || channels != 1 || rate != 48000 || clockRate != 48000) {
    [self failWithReason:@"invalid_pcm_format"]; [_lock unlock]; return;
  }
  auto slice = _window->Reserve(_generation, timestamp, frames, valid, concealed);
  if (_window->Failed()) { [self failWithReason:[NSString stringWithUTF8String:_window->FailureReason()]]; [_lock unlock]; return; }
  if (slice) {
    NSData *copy = [NSData dataWithBytes:pcm + slice->skip length:slice->frames * sizeof(int16_t)];
    NCOutputSample *sample = [NCOutputSample new];
    sample.end = timestamp + slice->skip + slice->frames - _first;
    const uint32_t count = std::min(64U, slice->frames);
    NSMutableArray<NSNumber *> *values = [NSMutableArray arrayWithCapacity:count];
    for (uint32_t i = 0; i < count; ++i) {
      uint32_t offset = count == 1 ? 0 : i * (slice->frames - 1) / (count - 1);
      [values addObject:@(pcm[slice->skip + offset] / 32768.0f)];
    }
    sample.values = values; [_samples addObject:sample];
    const uint64_t token = slice->token;
    __weak NCPcmOutput *weakSelf = self;
    dispatch_queue_t completions = _completions;
    [_device schedulePCM:copy completion:^{
      // Never stop AVAudioPlayerNode or acquire a guard from its render callback.
      dispatch_async(completions, ^{
        NCPcmOutput *strongSelf = weakSelf;
        if (!strongSelf) return;
        [strongSelf->_lock lock];
        if (!strongSelf->_terminal) {
          if ([strongSelf->_device isPlaying]) {
            if (strongSelf->_window->Played(strongSelf->_generation, token))
              strongSelf->_lastProgress = std::chrono::steady_clock::now();
            while (strongSelf->_samples.count &&
                   strongSelf->_samples.firstObject.end <= strongSelf->_window->ConfirmedSamples()) {
              strongSelf->_latestSample = strongSelf->_samples.firstObject.values;
              [strongSelf->_samples removeObjectAtIndex:0];
            }
            if (strongSelf->_window->Drained()) [strongSelf cancelWatchdog];
          }
          else [strongSelf failDeviceWithReason:@"device_stopped"];
        }
        dispatch_block_t changed = strongSelf->_changed;
        [strongSelf->_lock unlock];
        if (changed) changed();
      });
    }];
  }
  if (_window->InputComplete() && [_device respondsToSelector:@selector(finishInput)])
    [_device finishInput];
  [_lock unlock];
}
- (uint32_t)confirmedSamples {
  [_lock lock]; auto value = _window->ConfirmedSamples(); [_lock unlock]; return value;
}
- (NSArray<NSNumber *> *)latestSample {
  [_lock lock]; NSArray<NSNumber *> *value = _latestSample; [_lock unlock]; return value;
}
- (BOOL)drained { [_lock lock]; BOOL value = _window->Drained(); [_lock unlock]; return value; }
- (BOOL)failed { [_lock lock]; BOOL value = _failed; [_lock unlock]; return value; }
- (NSString *)failureReason { [_lock lock]; NSString *value = _failureReason ?: @""; [_lock unlock]; return value; }
- (double)failureAtMs { [_lock lock]; double value = _failureAtMs; [_lock unlock]; return value; }
- (BOOL)isPlaying {
  [_lock lock]; BOOL value = _started && !_terminal && [_device isPlaying]; [_lock unlock]; return value;
}
- (float)volume { [_lock lock]; float value = _device.volume; [_lock unlock]; return value; }
- (void)setVolume:(float)value {
  if (!std::isfinite(value)) return;
  [_lock lock]; _device.volume = std::max(0.0f, std::min(1.0f, value)); [_lock unlock];
}
- (dispatch_block_t)changed { [_lock lock]; dispatch_block_t value = _changed; [_lock unlock]; return value; }
- (void)setChanged:(dispatch_block_t)value { [_lock lock]; _changed = [value copy]; [_lock unlock]; }
- (void)cancelWatchdog {
  if (_watchdog) { dispatch_source_cancel(_watchdog); _watchdog = nil; }
}
- (void)checkStall {
  [_lock lock];
  if (!_terminal && !_window->Drained()) {
    if ([_device respondsToSelector:@selector(streamProgress)]) {
      const uint64_t progress = _device.streamProgress;
      if (progress != _lastStreamProgress) _lastProgress = std::chrono::steady_clock::now();
      _lastStreamProgress = progress;
    }
    if (![_device isPlaying]) [self failDeviceWithReason:@"device_stopped"];
    else if (std::chrono::steady_clock::now() - _lastProgress > std::chrono::seconds(15))
      [self failWithReason:@"media_stall"]; // Never a synthetic completion.
  }
  [_lock unlock];
}
- (void)notifyChanged {
  // Called under the output lock; publish only after returning from it. Even a
  // synchronous callback from stop cannot invert output -> ownership lock order.
  __weak NCPcmOutput *weakSelf = self;
  dispatch_async(_completions, ^{
    NCPcmOutput *strongSelf = weakSelf;
    dispatch_block_t changed = strongSelf.changed;
    if (changed) changed();
  });
}
- (void)dealloc {
  if (_watchdog) dispatch_source_cancel(_watchdog);
  if ([_device respondsToSelector:@selector(setInvalidated:)]) _device.invalidated = nil;
  _window->Stop(); [_device stop];
}
@end
