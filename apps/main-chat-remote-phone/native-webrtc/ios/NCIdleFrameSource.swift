import AVFoundation
import CoreGraphics

/// Silent, bounded boundary-frame preparation. Public operations are main-only;
/// asset IO, seeking and pixel conversion run on the private serial worker.
/// A ready frame is NOT a presentation observation. The native surface owner
/// must confirm it after submitting the matching frame, under its current lease.
final class NCIdleFrameSource {
  final class Frame {
    let image: CGImage, sourceFrame: Int, pts: CMTime
    fileprivate let request: NCIdleFrameState.Request
    fileprivate init(_ image: CGImage, _ pts: CMTime, _ sourceFrame: Int, _ request: NCIdleFrameState.Request) {
      self.image = image; self.pts = pts; self.sourceFrame = sourceFrame; self.request = request
    }
  }
  private let state: NCIdleFrameState
  private let worker = DispatchQueue(label:"nc.idle.frame",qos:.userInitiated)
  private let lifetime = NSLock()
  private var revision = 0
  private var closed = false
  // Main-owned candidate: at most one prepared frame, plus the caller's surface.
  private var candidate: Frame?
  private var completion: ((Frame?) -> Void)?
  // Worker-owned decoder and one reusable decoded frame. No decoded-loop cache.
  private var player: AVPlayer?
  private var output: AVPlayerItemVideoOutput?
  private var stride = 1
  private var cached: (CGImage,CMTime,Int)?

  init?(url: URL, generation: String, motionId: String, sourceFrameCount: Int) {
    precondition(Thread.isMainThread)
    guard url.isFileURL, let state = NCIdleFrameState(generation:generation,motionId:motionId,sourceFrameCount:sourceFrameCount) else { return nil }
    self.state = state
    worker.async { [weak self] in
      guard let self, self.isCurrent(nil) else { return }
      let asset = AVURLAsset(url:url)
      let tracks = asset.tracks(withMediaType:.video)
      guard asset.tracks(withMediaType:.audio).isEmpty, tracks.count == 1 else { return }
      let fps = Int(tracks[0].nominalFrameRate.rounded())
      guard [6,8,12,24].contains(fps) else { return }
      self.stride = 24/fps
      let item = AVPlayerItem(asset:asset)
      let output = AVPlayerItemVideoOutput(pixelBufferAttributes:[
        kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA])
      item.add(output)
      let player = AVPlayer(playerItem:item); player.isMuted = true; player.volume = 0
      self.output = output; self.player = player
    }
  }
  private func isCurrent(_ epoch: Int?) -> Bool {
    lifetime.lock(); defer { lifetime.unlock() }; return !closed && (epoch == nil || epoch == revision)
  }
  private func advance(closing: Bool = false) -> Int {
    lifetime.lock(); defer { lifetime.unlock() }
    revision += 1; closed = closed || closing; return revision
  }
  func prepareFrame(_ sourceFrame: Int, done: @escaping (Frame?) -> Void) {
    precondition(Thread.isMainThread)
    guard let request = state.request(sourceFrame) else { done(nil); return }
    let epoch = advance(), previous = completion
    candidate = nil; completion = done; previous?(nil)
    let deadline = ProcessInfo.processInfo.systemUptime + 1.8
    worker.async { [weak self] in self?.seek(request,epoch,deadline) }
  }
  private func seek(_ request: NCIdleFrameState.Request, _ epoch: Int, _ deadline: Double) {
    guard isCurrent(epoch) else { return }
    guard ProcessInfo.processInfo.systemUptime < deadline, player?.currentItem?.status != .failed else {
      deliver(nil,request,epoch); return
    }
    guard let player, player.currentItem?.status == .readyToPlay else {
      worker.asyncAfter(deadline:.now()+0.005) { [weak self] in self?.seek(request,epoch,deadline) }; return
    }
    let target = request.sourceFrame/stride*stride
    if let cached, cached.2 == target { deliver(cached,request,epoch); return }
    player.pause(); player.currentItem?.cancelPendingSeeks()
    let time = CMTime(value:CMTimeValue(target),timescale:24)
    player.seek(to:time,toleranceBefore:.zero,toleranceAfter:.zero) { [weak self] finished in
      guard let self else { return }
      self.worker.async {
        guard self.isCurrent(epoch) else { return }
        if finished { self.read(request,epoch,deadline,time) }
        else { self.deliver(nil,request,epoch) }
      }
    }
  }
  private func read(_ request: NCIdleFrameState.Request, _ epoch: Int, _ deadline: Double, _ time: CMTime) {
    guard isCurrent(epoch) else { return }
    guard ProcessInfo.processInfo.systemUptime < deadline, let output else { deliver(nil,request,epoch); return }
    var pts = CMTime.invalid
    guard output.hasNewPixelBuffer(forItemTime:time),
          let pixels = output.copyPixelBuffer(forItemTime:time,itemTimeForDisplay:&pts), pts.isNumeric else {
      worker.asyncAfter(deadline:.now()+0.005) { [weak self] in self?.read(request,epoch,deadline,time) }; return
    }
    // AVFoundation already converted the video to BGRA. Running it through
    // Core Image again applies another transfer-function conversion (the native
    // fixture changed gray 56 -> 64). Preserve those decoded bytes verbatim.
    CVPixelBufferLockBaseAddress(pixels,.readOnly)
    defer { CVPixelBufferUnlockBaseAddress(pixels,.readOnly) }
    let width = CVPixelBufferGetWidth(pixels), height = CVPixelBufferGetHeight(pixels)
    let row = CVPixelBufferGetBytesPerRow(pixels)
    guard let base = CVPixelBufferGetBaseAddress(pixels), width > 0, height > 0,
          width <= 4096, height <= 4096, row >= width*4, row <= 32768,
          let provider = CGDataProvider(data:Data(bytes:base,count:row*height) as CFData),
          let rgb = CGImage(width:width,height:height,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:row,
            space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGBitmapInfo(rawValue:
              CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue),
            provider:provider,decode:nil,shouldInterpolate:true,intent:.defaultIntent) else {
      deliver(nil,request,epoch); return
    }
    let sourceFrame = Int((CMTimeGetSeconds(pts)*24).rounded())
    guard isCurrent(epoch) else { return }
    cached = (rgb,pts,sourceFrame)
    deliver(cached,request,epoch)
  }
  private func deliver(_ value: (CGImage,CMTime,Int)?, _ request: NCIdleFrameState.Request, _ epoch: Int) {
    DispatchQueue.main.async { [weak self] in
      guard let self, self.isCurrent(epoch), self.state.current(request) else { return }
      if let value, self.state.decoded(request,pts:value.1.value,timescale:value.1.timescale) {
        self.candidate = Frame(value.0,value.1,value.2,request)
      }
      let callback = self.completion; self.completion = nil; callback?(self.candidate)
    }
  }
  func confirmPresented(_ frame: Frame, visible: Bool) -> Bool {
    precondition(Thread.isMainThread)
    guard candidate === frame else { return false }
    let now = Int64(ProcessInfo.processInfo.systemUptime*1_000_000_000)
    guard state.present(frame.request,now:now,visible:visible) != nil else { return false }
    candidate = nil; return true
  }
  func observe() -> NCIdleFrameState.Presented? { precondition(Thread.isMainThread); return state.observe() }
  func pause() {
    precondition(Thread.isMainThread)
    _ = advance(); state.pause(); candidate = nil
    let callback = completion; completion = nil; callback?(nil)
    worker.async { [weak self] in self?.player?.pause(); self?.player?.currentItem?.cancelPendingSeeks() }
  }
  func close() {
    precondition(Thread.isMainThread)
    _ = advance(closing:true); state.close(); candidate = nil
    let callback = completion; completion = nil; callback?(nil)
    worker.async { [self] in
      player?.pause(); player?.currentItem?.cancelPendingSeeks(); player?.replaceCurrentItem(with:nil)
      player = nil; output = nil; cached = nil
    }
  }
}
