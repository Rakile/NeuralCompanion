// NeuralCompanion, MIT. A scoped bridge to the existing RN WebRTC factory.
#import <Foundation/Foundation.h>
#import <WebRTC/WebRTC.h>
@class WebRTCModule;
NS_ASSUME_NONNULL_BEGIN
@interface NCTrackAttachment : NSObject
@property(nonatomic, readonly) BOOL ready;
@property(nonatomic, readonly) BOOL failed;
- (void)close;
@end
@interface NCTrackAccess : NSObject
+ (NSString *)registerModule:(WebRTCModule *)module;
+ (void)unregisterFactory:(NSString *)factory;
+ (NCTrackAttachment *)attachFactory:(NSString *)factory peer:(NSNumber *)peer audio:(NSString *)audio video:(NSString *)video
    pcm:(void (^)(NSData *, uint32_t, BOOL, BOOL))pcm frame:(void (^)(RTCVideoFrame *))frame
    closed:(dispatch_block_t)closed NS_SWIFT_NAME(attach(factory:peer:audio:video:pcm:frame:closed:));
@end
NS_ASSUME_NONNULL_END
