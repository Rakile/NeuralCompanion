// NeuralCompanion, MIT. Shared hardware, distinct guarded chunk lifetimes.
#import "NCPcmOutput.h"
NS_ASSUME_NONNULL_BEGIN
@interface NCPcmStream : NSObject
- (instancetype)initWithDevice:(id<NCPcmDevice>)device;
// Bounded to the active and next chunk. This allocates no playback authority.
- (nullable id<NCPcmDevice>)nextDevice;
- (void)stop;
@end
NS_ASSUME_NONNULL_END
