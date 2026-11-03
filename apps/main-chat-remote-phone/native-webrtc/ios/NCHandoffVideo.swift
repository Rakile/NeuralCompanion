import AVFoundation
import UIKit
import WebRTC

/// Silent cached cycles and retained H.264 segments. Combined handoff capability
/// remains disabled pending acceptance. No audio session, receipts or reverse seeks.
/// Main owns presentation; two workers own sequential readers and bounded queues.
final class NCHandoffVideo {
  struct Picture { let image: CGImage, tick: Int, step: Int }
  private final class Slot {
    let index: Int, url: URL, ticks: Int, startTick: Int
    private let condition = NSCondition()
    private var cancelled = false, finished = false
    private var failure = ""
    private var pictures = [Picture]()
    init(index: Int, url: URL, ticks: Int, startTick: Int = 0) { self.index=index; self.url=url; self.ticks=ticks; self.startTick=startTick }
    private func live() -> Bool { condition.lock(); defer { condition.unlock() }; return !cancelled }
    func cancel() { condition.lock(); cancelled=true; pictures.removeAll(); condition.broadcast(); condition.unlock() }
    func take() -> Picture? {
      condition.lock(); defer { condition.unlock() }
      guard !pictures.isEmpty else { return nil }; let value=pictures.removeFirst(); condition.signal(); return value
    }
    var status: (finished: Bool, queued: Int, failure: String) {
      condition.lock(); defer { condition.unlock() }; return (finished,pictures.count,failure)
    }
    private func put(_ picture: Picture) -> Bool {
      condition.lock(); defer { condition.unlock() }
      while !cancelled && pictures.count >= 3 { condition.wait(until:Date(timeIntervalSinceNow:0.02)) }
      guard !cancelled else { return false }; pictures.append(picture); return true
    }
    func decode() {
      var reader: AVAssetReader?
      var reason = ""
      defer {
        reader?.cancelReading(); reader=nil
        condition.lock(); failure=cancelled ? "" : reason; finished=true; condition.unlock()
      }
      do {
        guard live() else { return }
        let asset=AVURLAsset(url:url), tracks=asset.tracks(withMediaType:.video)
        guard asset.tracks.count == 1, tracks.count == 1 else { reason="invalid_tracks"; return }
        let track=tracks[0], fps=Int(track.nominalFrameRate.rounded())
        guard [6,8,12,24].contains(fps), !track.formatDescriptions.isEmpty,
          track.formatDescriptions.allSatisfy({ CMFormatDescriptionGetMediaSubType($0 as! CMFormatDescription) == kCMVideoCodecType_H264 })
          else { reason="invalid_format"; return }
        let step=24/fps, source=try AVAssetReader(asset:asset)
        let output=AVAssetReaderTrackOutput(track:track,outputSettings:[
          kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA])
        output.alwaysCopiesSampleData=false
        guard source.canAdd(output) else { reason="invalid_output"; return }
        source.add(output); reader=source
        if startTick > 0 { source.timeRange=CMTimeRange(start:CMTime(value:Int64(startTick),timescale:24),duration:.positiveInfinity) }
        guard source.startReading() else { reason="decode_start_failed"; return }
        var previousTick = -1
        while live() {
          // One sample/image at a time outside the bounded three-picture queue.
          let more: Bool = autoreleasepool {
            guard let sample=output.copyNextSampleBuffer() else { return false }
            let pts=CMSampleBufferGetPresentationTimeStamp(sample)
            guard pts.isNumeric else { reason="invalid_pts"; return false }
            let tick=Int((CMTimeGetSeconds(pts)*24).rounded())
            guard tick >= startTick, tick < ticks, tick%step == 0,
              (previousTick < 0 ? tick-startTick < step : tick == previousTick+step),
              let pixels=CMSampleBufferGetImageBuffer(sample), let image=Self.image(pixels)
              else { reason="source_tick_mismatch"; return false }
            previousTick=tick
            return put(Picture(image:image,tick:tick,step:step))
          }
          if !more { break }
        }
        if live() && reason.isEmpty && (source.status != .completed || previousTick != ((ticks-1)/step)*step) {
          reason="decode_incomplete"
        }
      } catch { reason="decode_failed" }
    }
    private static func image(_ pixels: CVPixelBuffer) -> CGImage? {
      CVPixelBufferLockBaseAddress(pixels,.readOnly)
      defer { CVPixelBufferUnlockBaseAddress(pixels,.readOnly) }
      let width=CVPixelBufferGetWidth(pixels), height=CVPixelBufferGetHeight(pixels), row=CVPixelBufferGetBytesPerRow(pixels)
      guard (1...448).contains(width), (1...672).contains(height), (width*4...8192).contains(row),
        let bytes=CVPixelBufferGetBaseAddress(pixels),
        let provider=CGDataProvider(data:Data(bytes:bytes,count:row*height) as CFData) else { return nil }
      // Preserve AVFoundation's BGRA bytes; do not apply a second Core Image
      // transfer-function conversion (the earlier native colour fixture caught it).
      return CGImage(width:width,height:height,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:row,
        space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGBitmapInfo(rawValue:
          CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue),
        provider:provider,decode:nil,shouldInterpolate:true,intent:.defaultIntent)
    }
  }
  private weak var host: UIView?
  private let presented: (UIImageView,Int,Int,Double) -> Void
  private let failed: (String) -> Void
  private let io=DispatchQueue(label:"nc.handoff.files",qos:.userInitiated)
  private let decoders: OperationQueue = {
    let queue=OperationQueue(); queue.name="nc.handoff.decode"; queue.maxConcurrentOperationCount=2; return queue
  }()
  private var work=DispatchGroup()
  private var retiringWork=[DispatchGroup]()
  private var revision=0, generation="", plan="", indices=[Int](), chunkTicks=12
  private var files=[Int:URL](), sizes=[Int:Int](), pending=Set<Int>()
  private var current: Slot?, next: Slot?, view: UIImageView?
  private var closed=false, submitted=false
  private var dueAt=0.0, clockAt=0.0, waitingAt=0.0, submittedAt=0.0
  private var elapsedTicks=0, lastTick = -1, observations=0
  private var exitTick=0, exitAt=0.0, exitState="none"
  private var exitSourceTick = -1
  private var pausedAt=0.0, observedAt=0.0, initialTick=0, cachedId=""
  private var maximumTick:Int?,streamBusy=false
  private(set) var state="ended"
  init(host: UIView, presented: @escaping (UIImageView,Int,Int,Double) -> Void, failed: @escaping (String) -> Void) {
    self.host=host; self.presented=presented; self.failed=failed
  }
  private var now: Double { ProcessInfo.processInfo.systemUptime }
  private func hex(_ value: String) -> Bool { value.range(of:"^[a-f0-9]{32}$",options:.regularExpression) != nil }
  func begin(owner: String, id: String, sequence: [Int], sourceCount: Int) -> Bool {
    precondition(Thread.isMainThread)
    guard !closed, let host, hex(owner), hex(id), (1...1440).contains(sourceCount),
      (1...1440).contains(sequence.count), sequence.allSatisfy({ (0..<sourceCount).contains($0) }) else { return false }
    clear(); generation=owner; plan=id; indices=sequence; state="waiting"
    let image=UIImageView(frame:host.bounds); image.contentMode = .scaleAspectFit
    image.autoresizingMask=[.flexibleWidth,.flexibleHeight]; host.addSubview(image); view=image
    waitingAt=now; schedule(revision,0); return true
  }
  func beginCycle(owner: String, id: String, sourceCount: Int) -> Bool {
    beginCycleAt(owner:owner,id:id,sourceCount:sourceCount,startTick:0)
  }
  func beginCycleAt(owner: String, id: String, sourceCount: Int, startTick: Int) -> Bool {
    guard (1...1440).contains(sourceCount), (0..<sourceCount).contains(startTick),
      begin(owner:owner,id:id,sequence:Array(0..<sourceCount),sourceCount:sourceCount) else { return false }
    chunkTicks=sourceCount; initialTick=startTick; return true
  }
  func beginCachedCycle(owner: String, id: String, contentId: String, sourceCount: Int, startTick: Int) -> Bool {
    guard contentId.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
      beginCycleAt(owner:owner,id:id,sourceCount:sourceCount,startTick:startTick) else { return false }
    cachedId=contentId; return true
  }
  func setPaused(_ value: Bool) {
    precondition(Thread.isMainThread)
    if value && pausedAt == 0 { pausedAt=now }
    else if !value && pausedAt != 0 {
      let elapsed=now-pausedAt
      if clockAt != 0 { clockAt += elapsed; dueAt += elapsed }
      if waitingAt != 0 { waitingAt += elapsed }
      pausedAt=0
    }
  }
  func limitTo(_ tick:Int) { precondition(Thread.isMainThread);maximumTick=max(0,min(indices.count-1,tick)) }
  // Layer-commit observation, NOT evidence of physical scanout. The Apple
  // pixel/timing fixture must verify this path before capability activation.
  func observeSelected(_ done:@escaping ()->Void) {
    precondition(Thread.isMainThread)
    guard let view,lastTick>=0,pausedAt != 0,view.window != nil else { return }
    let token=revision
    CATransaction.begin();CATransaction.setDisableActions(true)
    CATransaction.setCompletionBlock { DispatchQueue.main.async {
      guard token==self.revision,!self.closed,self.view === view,view.window != nil else { return }
      self.observedAt=self.now
      self.presented(view,self.lastTick/self.chunkTicks,(self.lastTick%self.chunkTicks)*1000/24,self.observedAt)
      if token==self.revision,!self.closed { done() }
    } }
    view.layer.setNeedsDisplay();CATransaction.commit()
  }
  func streamFrame(_ frame:RTCVideoFrame,shown:@escaping (UIImageView,Double)->Void)->Bool {
    precondition(Thread.isMainThread)
    guard let view,!closed,!submitted,!streamBusy,observedAt>0 else { return false }
    let token=revision,group=work;streamBusy=true;setPaused(true);group.enter()
    io.async {
      let image=autoreleasepool { NCStreamPicture.image(frame) }
      group.leave()
      DispatchQueue.main.async {
        guard token==self.revision,!self.closed,self.view === view else { return }
        guard let image,view.window != nil else { self.streamBusy=false;return }
        CATransaction.begin();CATransaction.setDisableActions(true)
        CATransaction.setCompletionBlock { DispatchQueue.main.async {
          guard token==self.revision,!self.closed,self.view === view else { return }
          self.streamBusy=false
          if view.window != nil { shown(view,self.now) }
        } }
        view.image=UIImage(cgImage:image);CATransaction.commit()
      }
    }
    return true
  }
  /// Scheduling metadata only. Audio admission and heard receipts are unchanged.
  func armExit(owner: String, id: String, minLeadMs: Int, maxLeadMs: Int) -> Double {
    armTick(owner:owner,id:id,sourceTick:0,minLeadMs:minLeadMs,maxLeadMs:maxLeadMs)
  }
  func armSourceExit(owner: String, id: String, sourceFrame: Int, minLeadMs: Int, maxLeadMs: Int) -> Double {
    precondition(Thread.isMainThread)
    guard chunkTicks == indices.count, indices.indices.allSatisfy({indices[$0] == $0}),
      indices.indices.contains(sourceFrame) else { return 0 }
    return armTick(owner:owner,id:id,sourceTick:sourceFrame,minLeadMs:minLeadMs,maxLeadMs:maxLeadMs)
  }
  private func armTick(owner: String, id: String, sourceTick: Int, minLeadMs: Int, maxLeadMs: Int) -> Double {
    precondition(Thread.isMainThread)
    guard !closed, owner == generation, id == plan, clockAt > 0, pausedAt == 0, !indices.isEmpty,
      (0...2000).contains(minLeadMs), (minLeadMs...2000).contains(maxLeadMs),
      ["prepared","presented","waiting"].contains(state) else { return 0 }
    if exitState != "none" {
      if exitSourceTick != sourceTick { return 0 }
      if exitState == "armed" { return exitAt }
      if exitState != "missed" { return 0 }
    }
    let at=now, length=indices.count
    // Use the observed picture when a previous display stall left the reader
    // behind its nominal clock; commit this correction only on a valid arm.
    let shownTick=max(0,elapsedTicks-1)/length*length+lastTick
    let observedLag=observedAt-(clockAt+Double(shownTick)/24)
    let lag=lastTick>=0 && observedLag>1.0/24 ? observedLag : 0
    let reference=clockAt+lag
    let earliest=max(elapsedTicks,Int(ceil((at+Double(minLeadMs)/1000-reference)*24)))
    let boundary=sourceTick+max(0,(earliest-sourceTick+length-1)/length)*length
    let target=reference+Double(boundary)/24
    guard target >= at, target-at <= Double(maxLeadMs)/1000 else { return 0 }
    clockAt=reference;dueAt += lag
    exitTick=boundary; exitAt=target; exitState="armed"; exitSourceTick=sourceTick; return target
  }
  func append(owner: String, id: String, index: Int, url: URL, done: @escaping (Bool) -> Void) {
    precondition(Thread.isMainThread)
    guard !closed, owner == generation, id == plan, (0..<((indices.count+chunkTicks-1)/chunkTicks)).contains(index),
      pending.insert(index).inserted else { done(false); return }
    let token=revision, group=work, allowedCacheId=cachedId; group.enter()
    io.async {
      let root=FileManager.default.urls(for:.cachesDirectory,in:.userDomainMask)[0].resolvingSymlinksInPath().standardizedFileURL
      let file=url.resolvingSymlinksInPath().standardizedFileURL
      var length=0
      let owned=allowedCacheId.isEmpty ? file.deletingLastPathComponent() == root &&
        file.lastPathComponent.range(of:"^nc_musetalk_idle_[A-Za-z0-9_.-]+\\.mp4$",options:.regularExpression) != nil
        : file == root.appendingPathComponent("nc-idle-v1/"+allowedCacheId+".mp4")
      if url.isFileURL && owned,
        let attributes=try? FileManager.default.attributesOfItem(atPath:file.path),
        attributes[.type] as? FileAttributeType == .typeRegular, let size=attributes[.size] as? NSNumber {
        length=size.intValue
      }
      group.leave()
      DispatchQueue.main.async {
        guard token == self.revision, !self.closed else { done(false); return }
        self.pending.remove(index)
        guard (1...16*1024*1024).contains(length), self.files[index] == nil,
          self.sizes.values.reduce(0,+)+length <= 128*1024*1024 else { done(false); return }
        self.files[index]=file; self.sizes[index]=length
        if self.current == nil && index == 0 { self.current=self.slot(0,startTick:self.initialTick) }
        self.prepareNext(); done(true)
      }
    }
  }
  private func slot(_ index: Int, startTick: Int = 0) -> Slot? {
    guard let file=files[index] else { return nil }
    let slot=Slot(index:index,url:file,ticks:min(chunkTicks,indices.count-index*chunkTicks),startTick:startTick), group=work
    group.enter(); decoders.addOperation { autoreleasepool { slot.decode() }; group.leave() }; return slot
  }
  private func prepareNext() {
    guard let current, next == nil else { return }
    next=slot((current.index+1)%((indices.count+chunkTicks-1)/chunkTicks))
  }
  private func schedule(_ token: Int, _ delay: Double) {
    DispatchQueue.main.asyncAfter(deadline:.now()+max(0,delay)) {
      if token == self.revision && !self.closed { self.tick(token) }
    }
  }
  private func tick(_ token: Int) {
    if submitted {
      if now-submittedAt > 2 { fail("presentation_timeout") } else { schedule(token,0.005) }; return
    }
    if pausedAt != 0 { schedule(token,0.02); return }
    if let maximumTick,elapsedTicks>maximumTick { schedule(token,0.005);return }
    guard let view, view.window != nil, var active=current else { waitForData(token); return }
    if !active.status.failure.isEmpty { fail(active.status.failure); return }
    if now < dueAt { schedule(token,dueAt-now); return }
    if exitTick > 0 && elapsedTicks >= exitTick {
      // Not-ready speech means another cycle, never a frozen handoff frame.
      exitTick=0; exitState="missed"
    }
    if active.status.finished && active.status.queued == 0 {
      guard let ready=next else { prepareNext(); waitForData(token); return }
      active.cancel(); current=ready; next=nil; active=ready; prepareNext()
    }
    guard let picture=active.take() else { waitForData(token); return }
    submitted=true; submittedAt=now; waitingAt=0; state="prepared"
    let segment=active.index, ticks=active.ticks
    CATransaction.begin(); CATransaction.setDisableActions(true)
    view.image=UIImage(cgImage:picture.image)
    CATransaction.setCompletionBlock {
      DispatchQueue.main.async {
        guard token == self.revision, !self.closed, self.view === view, view.window != nil else { return }
        self.submitted=false; self.observations += 1; self.state="presented"
        self.lastTick=segment*self.chunkTicks+picture.tick
        let at=self.now; self.observedAt=at
        if self.clockAt == 0 { self.elapsedTicks=self.lastTick; self.clockAt=at-Double(self.elapsedTicks)/24 }
        self.elapsedTicks += min(picture.step,ticks-picture.tick)
        self.dueAt=self.clockAt+Double(self.elapsedTicks)/24
        self.presented(view,segment,picture.tick*1000/24,at)
      }
    }; CATransaction.commit(); schedule(token,0.005)
  }
  private func waitForData(_ token: Int) {
    state="waiting"; if waitingAt == 0 { waitingAt=now }
    if now-waitingAt > 2 { fail("segment_wait_timeout") } else { schedule(token,0.005) }
  }
  var status: [String:Any] {
    ["state":state,"players":[current,next].compactMap({$0}).count,"files":files.count,
     "segment":current?.index ?? -1,"sourceTick":lastTick,"presented":observations,
     "sourceFrame":indices.indices.contains(lastTick) ? indices[lastTick] : -1,"observedAtSeconds":observedAt,"paused":pausedAt != 0,
     "exitState":exitState,"exitAtSeconds":exitAt,
     "decodedAhead":(current?.status.queued ?? 0)+(next?.status.queued ?? 0),
     "pictureSubmitted":submitted,"streamBusy":streamBusy,"viewAttached":view?.window != nil]
  }
  private func fail(_ reason: String) { clear(); state="failed"; failed(reason) }
  func clear() { clearDetached { _ in } }
  func clearDetached(_ done: @escaping (Bool) -> Void) {
    precondition(Thread.isMainThread)
    revision += 1
    retiringWork.removeAll { $0.wait(timeout:.now()) == .success }
    retiringWork.append(work); work=DispatchGroup()
    let retired=DispatchGroup()
    for group in retiringWork {
      retired.enter(); group.notify(queue:io) { retired.leave() }
    }
    generation=""; plan=""; indices=[]; chunkTicks=12; files.removeAll(); sizes.removeAll(); pending.removeAll()
    current?.cancel(); next?.cancel(); current=nil; next=nil
    view?.image=nil; view?.removeFromSuperview(); view=nil
    submitted=false; dueAt=0; clockAt=0; elapsedTicks=0; lastTick = -1; observations=0; state="ended"
    exitTick=0; exitAt=0; exitState="none"; exitSourceTick = -1
    pausedAt=0; observedAt=0; initialTick=0; cachedId=""
    maximumTick=nil;streamBusy=false
    // Never block main on a codec or unlink while a reader still holds the file.
    var settled=false
    retired.notify(queue:.main) { if !settled { settled=true; done(true) } }
    DispatchQueue.main.asyncAfter(deadline:.now()+5) { if !settled { settled=true; done(false) } }
  }
  func close() { precondition(Thread.isMainThread); if !closed { clear(); closed=true } }
}
