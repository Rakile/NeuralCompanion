// NeuralCompanion, MIT. WebRTC decoder clock without an automatic audio output.
#import <WebRTC/RTCAudioDevice.h>

NS_ASSUME_NONNULL_BEGIN
// Owned/configured on WebRTC's ADM thread. Does not own AVAudioSession or a mic.
// Install before creating the peer factory, never after remote audio arrives.
@interface NCSilentAudioDevice : NSObject <RTCAudioDevice>
@end
NS_ASSUME_NONNULL_END
