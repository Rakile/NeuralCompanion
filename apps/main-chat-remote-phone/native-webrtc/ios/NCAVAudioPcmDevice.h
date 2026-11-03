#import "NCPcmOutput.h"
NS_ASSUME_NONNULL_BEGIN
// AVAudioSession remains owned by existing Expo/Live policy. This device never
// calls setCategory/setActive and cannot authorize background audio itself.
@interface NCAVAudioPcmDevice : NSObject <NCPcmDevice>
@property(atomic, copy, nullable) dispatch_block_t invalidated;
@end
NS_ASSUME_NONNULL_END
