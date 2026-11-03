// NeuralCompanion, MIT. Low-level output, not an authorization owner.
#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN
// Only the platform boundary is substitutable in the host tests. A completion
// MUST mean device playback, never queued/written/decoded PCM. stop clears it.
@protocol NCPcmDevice <NSObject>
- (BOOL)prepare:(NSError * _Nullable * _Nullable)error;
- (void)play;
- (void)stop;
- (BOOL)isPlaying;
- (void)schedulePCM:(NSData *)monoInt16 completion:(dispatch_block_t)completion;
@property(nonatomic) float volume;
@optional
// Shared OS progress is liveness only, never a receipt for a waiting chunk.
@property(nonatomic, readonly) uint64_t streamProgress;
- (void)stopWithFailureReason:(NSString *)reason;
@property(nonatomic, readonly) NSString *failureReason;
- (void)finishInput;
// Shared-stream owner only, after every lease has physically drained/retired.
// Release the idle graph; a later explicit prepare must rebuild it. Never call
// from a platform configuration notification or while a successor is queued.
- (void)releaseIdle;
@property(atomic, copy, nullable) dispatch_block_t invalidated;
@end

// A fresh object per admitted chunk. Existing NCPlaybackBinding is the caller:
// prepare outside its lock, start/stop inside it. It never issues its own ticket.
// No automatic resume, audio-session policy, filesystem or network operations.
@interface NCPcmOutput : NSObject
- (instancetype)initWithDevice:(id<NCPcmDevice>)device generation:(uint64_t)generation
                    firstSample:(uint32_t)first sampleCount:(uint32_t)count;
- (BOOL)prepare:(NSError * _Nullable * _Nullable)error;
- (BOOL)start;
- (BOOL)belongsToGeneration:(uint64_t)generation;
- (void)stop;
- (void)fail;
- (void)receivePCM:(const int16_t *)pcm frames:(uint32_t)frames channels:(uint32_t)channels
       sampleRate:(uint32_t)rate timestamp:(uint32_t)timestamp clockRate:(uint32_t)clockRate
             valid:(BOOL)valid concealed:(BOOL)concealed;
@property(nonatomic, readonly) uint32_t confirmedSamples;
// At most 64 normalized PCM values from confirmed output, nil before output or
// after stop. Visualization only; never an admission or completion signal.
@property(nonatomic, readonly, nullable) NSArray<NSNumber *> *latestSample;
@property(nonatomic, readonly) BOOL drained;
@property(nonatomic, readonly) BOOL failed;
// First native failure, captured before asynchronous JS observation/cleanup.
@property(nonatomic, readonly) NSString *failureReason;
@property(nonatomic, readonly) double failureAtMs;
@property(nonatomic, readonly) BOOL isPlaying;
@property(nonatomic) float volume;
// Called off the OS render callback and outside the output lock. The existing
// owner can reject a late notification; this callback itself grants no receipt.
@property(nonatomic, copy, nullable) dispatch_block_t changed;
@end
NS_ASSUME_NONNULL_END
