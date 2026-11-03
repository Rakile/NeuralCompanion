#import "NCRtpVideoSink.h"
#include "../output/NCVideoWindow.h"
#include <memory>

// Cover the bounded 500ms PCM backlog at 24fps, plus four frames of jitter.
static const NSUInteger kMaxPendingFrames = 16;

@implementation NCRtpVideoSink {
  NSRecursiveLock *_lock;
  id<RTCVideoRenderer> _renderer;
  void (^_visibility)(uint64_t, BOOL);
  NSMutableArray<RTCVideoFrame *> *_pending;
  std::unique_ptr<nc::VideoWindow> _window;
  uint64_t _generation;
  BOOL _admitted, _closed, _scheduled;
}
- (instancetype)initWithRenderer:(id<RTCVideoRenderer>)renderer
                     generation:(uint64_t)generation
                 firstTimestamp:(uint32_t)timestamp
                   audioSamples:(uint32_t)samples
                           idle:(BOOL)idle
                     visibility:(void (^)(uint64_t, BOOL))visibility {
  if ((self = [super init])) {
    _lock = [NSRecursiveLock new];
    _renderer = renderer;
    _visibility = [visibility copy];
    _pending = [NSMutableArray new];
    _generation = generation;
    _window = std::make_unique<nc::VideoWindow>(generation, timestamp, samples, idle);
  }
  return self;
}
- (BOOL)admit:(uint64_t)generation {
  [_lock lock];
  BOOL accepted = !_closed && _window->Admit(generation);
  if (accepted) _admitted = YES;
  [_lock unlock];
  return accepted;
}
- (void)scheduleLocked {
  if (_scheduled) return;
  _scheduled = YES;
  __weak NCRtpVideoSink *weakSelf = self;
  dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf present]; });
}
- (void)played:(uint32_t)samples generation:(uint64_t)generation {
  [_lock lock];
  if (!_closed) {
    _window->Played(generation, samples);
    if (_pending.count) [self scheduleLocked];
  }
  [_lock unlock];
}
- (void)setSize:(CGSize)size {
  // Use the size of the frame actually presented, not a future decoder frame.
}
- (void)renderFrame:(RTCVideoFrame *)frame {
  [_lock lock];
  if (_admitted && !_closed && frame && frame.width > 0 && frame.height > 0 &&
      frame.width <= 448 && frame.height <= 672) {
    BOOL duplicate = NO;
    for (RTCVideoFrame *queued in _pending) {
      if (queued.timeStamp == frame.timeStamp) { duplicate = YES; break; }
    }
    if (!duplicate) {
      if (_pending.count == kMaxPendingFrames) [_pending removeObjectAtIndex:0];
      [_pending addObject:frame];
      [self scheduleLocked];
    }
  }
  [_lock unlock];
}
- (void)present {
  NSAssert([NSThread isMainThread], @"Native video presentation must run on main");
  [_lock lock];
  _scheduled = NO;
  if (_closed) {
    [_pending removeAllObjects];
    _visibility(_generation, NO);
    [_lock unlock];
    return;
  }
  NSArray<RTCVideoFrame *> *frames = [_pending copy];
  [_pending removeAllObjects];
  for (RTCVideoFrame *frame in frames) {
    if (_closed) break;
    // SDK timeStamp is source RTP; timeStampNs is a different clock.
    auto decision = _window->Frame(_generation, (uint32_t)frame.timeStamp);
    if (decision == nc::VideoWindow::Decision::Wait) {
      [_pending addObject:frame];
    } else if (decision == nc::VideoWindow::Decision::Show) {
      CGSize size = frame.rotation % 180 == 0 ? CGSizeMake(frame.width, frame.height)
                                             : CGSizeMake(frame.height, frame.width);
      [_renderer setSize:size];
      if (_closed) break;
      [_renderer renderFrame:frame];
      if (!_closed) _visibility(_generation, YES);
    }
  }
  [_lock unlock];
}
- (void)stop {
  [_lock lock];
  if (!_closed) {
    _closed = YES;
    _window->Stop();
    [_pending removeAllObjects];
    // RTCMTLVideoView ignores renderFrame:nil; hide through its owner instead.
    // Keep the terminal UI action alive even if the owner immediately releases
    // this sink. The generation-aware view owner rejects a retired generation.
    void (^visibility)(uint64_t, BOOL) = _visibility;
    uint64_t generation = _generation;
    dispatch_async(dispatch_get_main_queue(), ^{ visibility(generation, NO); });
  }
  [_lock unlock];
}
@end
