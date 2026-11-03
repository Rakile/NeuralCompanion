// NeuralCompanion, MIT. Attach/detach on the SDK worker, never in its callback.
#import <WebRTC/RTCAudioTrack.h>
#import "NCPcmOutput.h"
NS_ASSUME_NONNULL_BEGIN
// The factory's silent decoder device is a REQUIRED independent default-output
// gate. Merely attaching this sink does not mute automatic WebRTC playback.
@interface NCRtpAudioSink : NSObject <RTCNcRtpAudioSink>
- (nullable instancetype)initWithGeneration:(uint64_t)generation;
- (BOOL)addOutput:(NCPcmOutput *)output generation:(uint64_t)generation;
- (void)removeOutput:(NCPcmOutput *)output;
- (void)stop;
@end
NS_ASSUME_NONNULL_END
