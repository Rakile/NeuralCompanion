#import "NCPcmStream.h"

@interface NCStreamBuffer : NSObject
@property(nonatomic, strong) NSData *pcm;
@property(nonatomic, copy) dispatch_block_t completion;
@property(nonatomic) BOOL completed;
@end
@implementation NCStreamBuffer
@end

@interface NCStreamLease : NSObject <NCPcmDevice>
@property(nonatomic, weak) NCPcmStream *owner;
@property(nonatomic, strong) NSMutableArray<NCStreamBuffer *> *pending;
@property(nonatomic) BOOL started, stopped, inputFinished;
@property(nonatomic) NSUInteger submitted, played;
@property(atomic, copy, nullable) dispatch_block_t invalidated;
@end

@interface NCPcmStream ()
- (BOOL)prepare:(NSError **)error;
- (void)invalidateDevice:(uint64_t)epoch;
- (void)playLease:(NCStreamLease *)lease;
- (BOOL)isPlayingLease:(NCStreamLease *)lease;
- (void)stopLease:(NCStreamLease *)lease;
- (void)stopLease:(NCStreamLease *)lease reason:(NSString *)reason;
- (NSString *)failureReason;
- (uint64_t)streamProgress;
- (void)schedule:(NSData *)pcm completion:(dispatch_block_t)completion lease:(NCStreamLease *)lease;
- (void)finishInput:(NCStreamLease *)lease;
- (float)volume;
- (void)setVolume:(float)value;
@end

@implementation NCStreamLease
- (instancetype)init { if ((self = [super init])) _pending = [NSMutableArray new]; return self; }
- (BOOL)prepare:(NSError **)error { return [self.owner prepare:error]; }
- (void)play { [self.owner playLease:self]; }
- (BOOL)isPlaying { return [self.owner isPlayingLease:self]; }
- (void)stop { [self.owner stopLease:self]; }
- (void)stopWithFailureReason:(NSString *)reason { [self.owner stopLease:self reason:reason]; }
- (NSString *)failureReason { return [self.owner failureReason] ?: @""; }
- (uint64_t)streamProgress { return [self.owner streamProgress]; }
- (void)schedulePCM:(NSData *)pcm completion:(dispatch_block_t)completion { [self.owner schedule:pcm completion:completion lease:self]; }
- (void)finishInput { [self.owner finishInput:self]; }
- (float)volume { return [self.owner volume]; }
- (void)setVolume:(float)value { [self.owner setVolume:value]; }
@end

@implementation NCPcmStream {
  id<NCPcmDevice> _device;
  NSRecursiveLock *_lock;
  dispatch_queue_t _completions;
  NSMutableArray<NCStreamLease *> *_leases;
  BOOL _prepared, _preparing, _terminal, _playing;
  uint64_t _deviceEpoch;
  uint64_t _playedSamples;
  NSString *_failureReason;
}
- (instancetype)initWithDevice:(id<NCPcmDevice>)device {
  if ((self = [super init])) {
    _device = device; _lock = [NSRecursiveLock new]; _leases = [NSMutableArray new];
    _completions = dispatch_queue_create("nc.pcm.stream.completion", DISPATCH_QUEUE_SERIAL);
  }
  return self;
}
- (id<NCPcmDevice>)nextDevice {
  [_lock lock];
  NCStreamLease *lease = nil;
  if (!_terminal && _leases.count < 2) {
    lease = [NCStreamLease new]; lease.owner = self; [_leases addObject:lease];
  }
  [_lock unlock]; return lease;
}
- (BOOL)prepare:(NSError **)error {
  [_lock lock];
  if (_terminal || _prepared || _preparing) { BOOL ready = _prepared && !_terminal; [_lock unlock]; return ready; }
  _preparing = YES;
  const uint64_t epoch = ++_deviceEpoch;
  if ([_device respondsToSelector:@selector(setInvalidated:)]) {
    __weak NCPcmStream *weakSelf = self;
    dispatch_queue_t completions = _completions;
    // The engine's internal notification queue must never wait on this lock:
    // releasing a drained graph can itself wait for that queue to finish.
    _device.invalidated = ^{
      dispatch_async(completions, ^{ [weakSelf invalidateDevice:epoch]; });
    };
  }
  [_lock unlock];
  BOOL ready = [_device prepare:error]; // Outside locks; route notifications can reenter.
  [_lock lock]; _preparing = NO;
  if (!ready || _terminal) [self stopLocked]; else _prepared = YES;
  ready = _prepared && !_terminal;
  [_lock unlock]; return ready;
}
- (void)invalidateDevice:(uint64_t)epoch {
  [_lock lock];
  if (epoch == _deviceEpoch) [self stopLocked];
  [_lock unlock];
}
- (void)playLease:(NCStreamLease *)lease {
  [_lock lock];
  if (!_terminal && _prepared && !lease.stopped && [_leases containsObject:lease]) {
    // Admit input now, but prime the independent hardware clock before play.
    // Native receipts still require actual device completion callbacks.
    lease.started = YES;
    if (_playing && ![_device isPlaying]) [self stopLocked];
  }
  [_lock unlock];
}
- (BOOL)isPlayingLease:(NCStreamLease *)lease {
  [_lock lock]; BOOL playing = !_terminal && lease.started && !lease.stopped && (!_playing || [_device isPlaying]); [_lock unlock]; return playing;
}
- (void)schedule:(NSData *)pcm completion:(dispatch_block_t)completion lease:(NCStreamLease *)lease {
  [_lock lock];
  if (!_terminal && lease.started && !lease.stopped && !lease.inputFinished) {
    if (pcm.length == 0 || pcm.length % 2 || lease.submitted - lease.played + pcm.length / 2 > 24000) {
      [self stopLocked];
    } else {
      NCStreamBuffer *item = [NCStreamBuffer new]; item.pcm = pcm; item.completion = completion;
      [lease.pending addObject:item]; lease.submitted += pcm.length / 2;
      [self flushLocked];
    }
  }
  [_lock unlock];
}
- (void)finishInput:(NCStreamLease *)lease {
  [_lock lock];
  if (!_terminal && !lease.stopped && lease.submitted > 0) { lease.inputFinished = YES; [self flushLocked]; }
  [_lock unlock];
}
- (void)flushLocked {
  if (_terminal) return;
  if (!_playing) {
    NCStreamLease *first = _leases.firstObject;
    if (!first.started || (!first.inputFinished && first.submitted < 2880)) return;
  }
  BOOL scheduled = NO;
  for (NCStreamLease *lease in _leases) {
    while (lease.pending.count) {
      NCStreamBuffer *item = lease.pending.firstObject; [lease.pending removeObjectAtIndex:0];
      __weak NCPcmStream *weakSelf = self;
      __weak NCStreamLease *weakLease = lease;
      dispatch_queue_t completions = _completions;
      [_device schedulePCM:item.pcm completion:^{
        // Never wait for our lock from AVAudioPlayerNode's render callback:
        // scheduleBuffer/stop can themselves be waiting for that render thread.
        dispatch_async(completions, ^{ [weakSelf completed:item lease:weakLease]; });
      }];
      scheduled = YES;
    }
    if (!lease.inputFinished) break;
  }
  if (!_playing && scheduled) {
    [_device play]; _playing = [_device isPlaying];
    if (!_playing) [self stopLocked];
  }
}
- (void)completed:(NCStreamBuffer *)item lease:(NCStreamLease *)lease {
  [_lock lock]; dispatch_block_t callback = nil;
  if (!_terminal && lease && !lease.stopped && !item.completed) {
    item.completed = YES; lease.played += item.pcm.length / 2; callback = item.completion;
    _playedSamples += item.pcm.length / 2;
  }
  [_lock unlock];
  if (callback) callback(); // Output queues it; never acquires guard from OS render callback.
}
- (void)stopLease:(NCStreamLease *)lease {
  [self stopLease:lease reason:@""];
}
- (NSString *)failureReason { [_lock lock]; NSString *value = _failureReason ?: @""; [_lock unlock]; return value; }
- (uint64_t)streamProgress { [_lock lock]; uint64_t value = _playedSamples; [_lock unlock]; return value; }
- (void)stopLease:(NCStreamLease *)lease reason:(NSString *)reason {
  [_lock lock];
  if (!lease.stopped) {
    BOOL drained = lease.inputFinished && lease.submitted > 0 && lease.played == lease.submitted;
    lease.stopped = YES;
    if (!drained) {
      if (!_terminal && reason.length) _failureReason = [reason copy];
      [self stopLocked];
    }
    [_leases removeObject:lease];
    if (drained && _leases.count == 0 && !_terminal) {
      // No old output remains authorized. A manual microphone session may now
      // change the hardware format without poisoning a later admitted reply.
      ++_deviceEpoch; _prepared = NO; _playing = NO;
      [_device stop];
      if ([_device respondsToSelector:@selector(releaseIdle)]) [_device releaseIdle];
    }
  }
  [_lock unlock];
}
- (void)stopLocked {
  if (_terminal) return;
  if (!_failureReason.length) _failureReason = @"device_invalidated";
  _terminal = YES; // Fence completion callbacks BEFORE the platform flush.
  ++_deviceEpoch;
  [_device stop];
  for (NCStreamLease *lease in _leases) {
    [lease.pending removeAllObjects];
    __weak NCStreamLease *weakLease = lease;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT, 0), ^{
      dispatch_block_t invalidated = weakLease.invalidated;
      if (invalidated) invalidated();
    });
  }
}
- (void)stop { [_lock lock]; [self stopLocked]; [_lock unlock]; }
- (float)volume { [_lock lock]; float value = _device.volume; [_lock unlock]; return value; }
- (void)setVolume:(float)value { [_lock lock]; if (!_terminal) _device.volume = value; [_lock unlock]; }
- (void)dealloc {
  if ([_device respondsToSelector:@selector(setInvalidated:)]) _device.invalidated = nil;
  [self stop];
}
@end
