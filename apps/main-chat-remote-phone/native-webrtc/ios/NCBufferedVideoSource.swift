import AVFoundation
import QuartzCore
import WebRTC

/// Reads the existing segment AVPlayer's decoded output. Uses the output's
/// actual itemTimeForDisplay, never a requested seek or wall-clock estimate.
final class NCBufferedVideoSource:NSObject {
  static func presentable(_ tick:Int,samples:Int,playing:Bool)->Bool {
    guard playing,tick>=0,samples>=0 else { return false }
    let heard=samples/2000
    // Same 120-ms lead tolerance as the existing segment player's videoStep.
    return Double(tick)*2000<=Double(samples)+5760 && tick>=heard-3
  }
  private weak var player:AVPlayer?
  private let item:AVPlayerItem,output:AVPlayerItemVideoOutput
  private let start:Int,frames:Int,frame:(Int,RTCVideoFrame)->Void
  private var timer:CADisplayLink?
  private var last:CMTime = .invalid
  private var closed=false
  private var prepared:(Int,RTCVideoFrame)?
  private var openingOffered=false
  private(set) var decoded=false
  init?(player:AVPlayer,start:Int,frames:Int,frame:@escaping (Int,RTCVideoFrame)->Void) {
    guard Thread.isMainThread,let item=player.currentItem,(0...14399).contains(start),
      (1...1440).contains(frames),start+frames<=14400 else { return nil }
    self.player=player;self.item=item;self.start=start;self.frames=frames;self.frame=frame
    output=AVPlayerItemVideoOutput(pixelBufferAttributes:[
      kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
    super.init()
    item.add(output)
    // A weak target avoids retaining this source when its segment is retired.
    let target=TickTarget(self),link=CADisplayLink(target:target,selector:#selector(TickTarget.tick))
    timer=link;link.add(to:.main,forMode:.common)
  }
  private final class TickTarget:NSObject {
    weak var owner:NCBufferedVideoSource?
    init(_ owner:NCBufferedVideoSource){self.owner=owner}
    @objc func tick(){owner?.tick()}
  }
  private func tick() {
    guard !closed,let player,player.currentItem === item else { return }
    // Paused pre-roll must be offered again when its existing player starts;
    // the unchanged item time otherwise makes hasNewPixelBuffer skip frame zero.
    if player.rate>0,let ready=prepared { prepared=nil;frame(ready.0,ready.1) }
    let at=player.currentTime()
    guard output.hasNewPixelBuffer(forItemTime:at) else { return }
    var displayed=CMTime.invalid
    guard let pixels=output.copyPixelBuffer(forItemTime:at,itemTimeForDisplay:&displayed),displayed.isNumeric,
      displayed != last else { return }
    let seconds=displayed.seconds
    guard seconds.isFinite,seconds>=0,seconds<Double(frames)/24 else { return }
    let tick=Int((seconds*24+0.000024).rounded(.down))
    guard (0..<frames).contains(tick) else { return }
    last=displayed;decoded=true
    let picture=RTCVideoFrame(buffer:RTCCVPixelBuffer(pixelBuffer:pixels),rotation:._0,
      timeStampNs:Int64(seconds*1_000_000_000))
    if player.rate==0 { prepared=(start+tick,picture) }
    frame(start+tick,picture)
  }
  /// Called only with guarded, started audio; doesn't advance the video player.
  @discardableResult func presentOpening(samples:Int)->Bool {
    precondition(Thread.isMainThread)
    guard !closed,!openingOffered,let ready=prepared,ready.0==0,(0...6000).contains(samples) else { return false }
    openingOffered=true
    frame(ready.0,ready.1)
    return true
  }
  func close() {
    precondition(Thread.isMainThread)
    guard !closed else { return };closed=true;prepared=nil;timer?.invalidate();timer=nil;item.remove(output)
  }
  deinit { timer?.invalidate() }
}
