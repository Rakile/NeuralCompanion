#import "NCTrackAccess.h"
#import "WebRTCModule.h"

@interface NCTrackAttachment () <RTCNcRtpAudioSink, RTCVideoRenderer>
- (instancetype)initWithModule:(WebRTCModule *)module pcm:(void (^)(NSData *, uint32_t, BOOL, BOOL))pcm
                         frame:(void (^)(RTCVideoFrame *))frame closed:(dispatch_block_t)closed;
- (void)attachPeer:(NSNumber *)peer audio:(NSString *)audio video:(NSString *)video;
@end

@implementation NCTrackAccess
+ (NSMapTable<NSString *, WebRTCModule *> *)factories {
  static NSMapTable *values; static dispatch_once_t once;
  dispatch_once(&once, ^{ values = [NSMapTable strongToWeakObjectsMapTable]; }); return values;
}
+ (NSMutableDictionary<NSString *, NSHashTable<NCTrackAttachment *> *> *)attachments {
  static NSMutableDictionary *values; static dispatch_once_t once;
  dispatch_once(&once, ^{ values = [NSMutableDictionary new]; }); return values;
}
+ (NSString *)registerModule:(WebRTCModule *)module {
  @synchronized(self) {
    NSString *key = NSUUID.UUID.UUIDString;
    [[self factories] setObject:module forKey:key];
    [self attachments][key] = [NSHashTable weakObjectsHashTable];
    return key;
  }
}
+ (void)unregisterFactory:(NSString *)factory {
  if (!factory) return;
  NSArray *current;
  @synchronized(self) {
    [[self factories] removeObjectForKey:factory];
    current = [self attachments][factory].allObjects;
    [[self attachments] removeObjectForKey:factory];
  }
  for (NCTrackAttachment *attachment in current) [attachment close];
}
+ (NCTrackAttachment *)attachFactory:(NSString *)factory peer:(NSNumber *)peer audio:(NSString *)audio video:(NSString *)video
    pcm:(void (^)(NSData *, uint32_t, BOOL, BOOL))pcm frame:(void (^)(RTCVideoFrame *))frame closed:(dispatch_block_t)closed {
  NCTrackAttachment *attachment;
  @synchronized(self) {
    WebRTCModule *module = [[self factories] objectForKey:factory];
    attachment = [[NCTrackAttachment alloc] initWithModule:module pcm:pcm frame:frame closed:closed];
    if (module) [[self attachments][factory] addObject:attachment];
    [attachment attachPeer:peer audio:audio video:video];
  }
  return attachment;
}
@end

@implementation NCTrackAttachment {
  __weak WebRTCModule *_module;
  NSRecursiveLock *_lock;
  RTCAudioTrack *_audio;
  RTCVideoTrack *_video;
  BOOL _terminal, _ready, _failed;
  void (^_pcm)(NSData *, uint32_t, BOOL, BOOL);
  void (^_frame)(RTCVideoFrame *);
  dispatch_block_t _closed;
}
- (instancetype)initWithModule:(WebRTCModule *)module pcm:(void (^)(NSData *, uint32_t, BOOL, BOOL))pcm
                         frame:(void (^)(RTCVideoFrame *))frame closed:(dispatch_block_t)closed {
  if ((self = [super init])) {
    _module = module; _lock = [NSRecursiveLock new];
    _pcm = [pcm copy]; _frame = [frame copy]; _closed = [closed copy];
  }
  return self;
}
- (BOOL)ready { [_lock lock]; BOOL value = _ready && !_terminal; [_lock unlock]; return value; }
- (BOOL)failed { [_lock lock]; BOOL value = _failed; [_lock unlock]; return value; }
- (void)attachPeer:(NSNumber *)peer audio:(NSString *)audio video:(NSString *)video {
  WebRTCModule *module = _module;
  if (!module || peer.longLongValue < 0 || peer.longLongValue > INT32_MAX ||
      !audio.length || audio.length > 128 || !video.length || video.length > 128) {
    [_lock lock]; _failed = YES; [_lock unlock]; [self close]; return;
  }
  dispatch_async(module.workerQueue, ^{
    [self->_lock lock];
    if (!self->_terminal) {
      RTCPeerConnection *connection = module.peerConnections[peer];
      RTCAudioTrack *foundAudio = nil; RTCVideoTrack *foundVideo = nil;
      for (RTCRtpReceiver *receiver in connection.receivers) {
        RTCMediaStreamTrack *track = receiver.track;
        if (track.readyState != RTCMediaStreamTrackStateLive) continue;
        if ([track.trackId isEqualToString:audio] && [track isKindOfClass:RTCAudioTrack.class]) foundAudio = (RTCAudioTrack *)track;
        if ([track.trackId isEqualToString:video] && [track isKindOfClass:RTCVideoTrack.class]) foundVideo = (RTCVideoTrack *)track;
      }
      if (foundAudio && foundVideo && !module.localTracks[audio] && !module.localTracks[video]) {
        self->_audio = foundAudio; self->_video = foundVideo;
        // SDK add/remove can synchronously cross to its decoder worker. Never
        // hold the callback fence while waiting on that worker.
        [self->_lock unlock];
        [foundAudio addRtpAudioSink:self]; [foundVideo addRenderer:self];
        [self->_lock lock];
        if (!self->_terminal) self->_ready = YES;
      } else { self->_failed = YES; }
    }
    BOOL failed = self->_failed;
    [self->_lock unlock];
    if (failed) [self close];
  });
}
- (void)didReceivePCM:(const void *)pcm bitsPerSample:(int)bits sampleRate:(int)rate
             channels:(NSUInteger)channels frames:(NSUInteger)frames rtpTimestamp:(uint32_t)timestamp
         rtpClockRate:(int)clockRate timestampValid:(BOOL)valid concealed:(BOOL)concealed {
  [_lock lock];
  if (!_terminal && _ready) {
    if (!pcm || bits != 16 || rate != 48000 || channels != 1 || !frames || frames > 960 || clockRate != 48000) {
      _failed = YES; [_lock unlock]; [self close]; return;
    }
    _pcm([NSData dataWithBytes:pcm length:frames * sizeof(int16_t)], timestamp, valid, concealed);
  }
  [_lock unlock];
}
- (void)setSize:(CGSize)size {}
- (void)renderFrame:(RTCVideoFrame *)frame {
  [_lock lock]; if (!_terminal && _ready && frame) _frame(frame); [_lock unlock];
}
- (void)close {
  [_lock lock];
  if (_terminal) { [_lock unlock]; return; }
  _terminal = YES; _ready = NO;
  dispatch_block_t closed = _closed; _closed = nil; _pcm = nil; _frame = nil;
  RTCAudioTrack *audio = _audio; RTCVideoTrack *video = _video; _audio = nil; _video = nil;
  WebRTCModule *module = _module;
  [_lock unlock];
  if (closed) closed(); // Fence output now; SDK detach never blocks the caller.
  if (module && (audio || video)) dispatch_async(module.workerQueue, ^{
    [audio removeRtpAudioSink:self]; [video removeRenderer:self];
  });
}
@end
