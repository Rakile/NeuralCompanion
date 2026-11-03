// NeuralCompanion, MIT. Video presentation never acknowledges audio playback.
#import <WebRTC/RTCVideoFrame.h>
#import <WebRTC/RTCVideoRenderer.h>

NS_ASSUME_NONNULL_BEGIN
@interface NCRtpVideoSink : NSObject <RTCVideoRenderer>
// Visibility runs on main. The view owner MUST ignore a generation that no
// longer owns its view; a retired sink cannot hide a replacement's frame.
- (instancetype)initWithRenderer:(id<RTCVideoRenderer>)renderer
                     generation:(uint64_t)generation
                 firstTimestamp:(uint32_t)timestamp
                   audioSamples:(uint32_t)samples
                           idle:(BOOL)idle
                     visibility:(void (^)(uint64_t generation, BOOL visible))visibility;
- (BOOL)admit:(uint64_t)generation;
- (void)played:(uint32_t)samples generation:(uint64_t)generation;
- (void)stop;
@end
NS_ASSUME_NONNULL_END
