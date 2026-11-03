#import "NCRtpAudioSink.h"

@implementation NCRtpAudioSink {
  NSLock *_lock;
  NSMutableArray<NCPcmOutput *> *_outputs;
  uint64_t _generation;
  BOOL _closed;
}
- (instancetype)initWithGeneration:(uint64_t)generation {
  if (!generation) return nil;
  if ((self = [super init])) { _lock = [NSLock new]; _outputs = [NSMutableArray new]; _generation = generation; }
  return self;
}
- (BOOL)addOutput:(NCPcmOutput *)output generation:(uint64_t)generation {
  [_lock lock]; BOOL accepted = NO;
  if (!_closed && generation == _generation && [output belongsToGeneration:generation]) {
    accepted = [_outputs containsObject:output];
    if (!accepted && _outputs.count < 2) { [_outputs addObject:output]; accepted = YES; }
  }
  [_lock unlock]; return accepted;
}
- (void)removeOutput:(NCPcmOutput *)output {
  [_lock lock]; BOOL removed = [_outputs containsObject:output]; [_outputs removeObject:output]; [_lock unlock];
  if (removed) [output stop];
}
- (void)stop {
  [_lock lock];
  _closed = YES; NSArray<NCPcmOutput *> *previous = [_outputs copy]; [_outputs removeAllObjects];
  [_lock unlock];
  for (NCPcmOutput *output in previous) [output stop];
}
- (void)didReceivePCM:(const void *)pcm bitsPerSample:(int)bits sampleRate:(int)rate
             channels:(NSUInteger)channels frames:(NSUInteger)frames rtpTimestamp:(uint32_t)timestamp
         rtpClockRate:(int)clockRate timestampValid:(BOOL)valid concealed:(BOOL)concealed {
  [_lock lock]; NSArray<NCPcmOutput *> *current = _closed ? @[] : [_outputs copy]; [_lock unlock];
  for (NCPcmOutput *output in current) {
    if (bits != 16 || channels != 1 || frames == 0 || frames > 960 || rate != 48000 || clockRate != 48000) {
      [output fail]; continue;
    }
    [output receivePCM:(const int16_t *)pcm frames:(uint32_t)frames channels:1 sampleRate:48000
             timestamp:timestamp clockRate:48000 valid:valid concealed:concealed];
  }
}
- (void)dealloc { [self stop]; }
@end
