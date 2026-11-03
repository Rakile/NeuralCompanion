import Foundation

/// Main-serialized visual policy. No audio authority, samples or receipts.
final class NCFrameHandoff {
  struct Timeline {
    let motionId: String, sourceFrameCount: Int, sourceIndices: [Int]
    init?(motionId: String, sourceFrameCount: Int, sourceIndices: [Int]) {
      guard motionId.count == 64, motionId.allSatisfy({ "abcdef0123456789".contains($0) }),
        (1...1440).contains(sourceFrameCount), (1...1440).contains(sourceIndices.count),
        sourceIndices.allSatisfy({ (0..<sourceFrameCount).contains($0) }) else { return nil }
      self.motionId = motionId; self.sourceFrameCount = sourceFrameCount; self.sourceIndices = sourceIndices
    }
  }
  final class Return {
    fileprivate let revision: Int64, key: Int64
    let motionId: String, sourceFrame: Int
    fileprivate init(_ revision:Int64,_ key:Int64,_ motionId:String,_ sourceFrame:Int) {
      self.revision=revision;self.key=key;self.motionId=motionId;self.sourceFrame=sourceFrame
    }
  }
  private let generation: String, nowMs: () -> Int64
  private(set) var state = "idle"
  private(set) var deadlineMs:Int64 = 0
  private var key:Int64 = 0, highestKey:Int64 = 0, revision:Int64 = 0
  private var timeline:Timeline?
  private var openingReady = false
  private var pending:String?
  private var observation:NCIdleFrameState.Presented?, outgoing:NCIdleFrameState.Presented?
  private var lastSpeechFrame:Int?, heardSamples:Int64 = 0
  private var returnLease:Return?
  init(generation:String,nowMs:@escaping () -> Int64) { self.generation=generation;self.nowMs=nowMs }
  private func fresh(_ frame:NCIdleFrameState.Presented) -> Bool {
    let now=nowMs()
    guard now >= 0, frame.observedAtNanos >= 0 else { return false }
    let at=frame.observedAtNanos/1_000_000
    return frame.generation == generation && at <= now && now-at <= 750
  }
  func begin(_ ownerGeneration:String,_ nextKey:Int64,_ value:Timeline,_ readyAtMs:Int64) -> Bool {
    guard state != "closed", ownerGeneration == generation, (1...9_007_199_254_740_991).contains(nextKey),
      readyAtMs >= 0, readyAtMs <= nowMs(), readyAtMs <= Int64.max-2000 else { return false }
    if nextKey == key && ["preparing","armed","speech"].contains(state) {
      return timeline?.motionId == value.motionId && timeline?.sourceFrameCount == value.sourceFrameCount &&
        timeline?.sourceIndices == value.sourceIndices
    }
    guard nextKey > highestKey else { return false }
    revision += 1;key=nextKey;highestKey=nextKey;timeline=value
    deadlineMs=readyAtMs+2000;openingReady=false;pending=nil
    outgoing=nil;lastSpeechFrame=nil;heardSamples=0;returnLease=nil;state="preparing";return true
  }
  func observe(_ frame:NCIdleFrameState.Presented) {
    if state != "closed", (0...1439).contains(frame.sourceFrame), fresh(frame),
      frame.observedAtNanos >= (observation?.observedAtNanos ?? 0) { observation=frame }
  }
  func speechReady(_ value:Int64) -> Bool {
    guard value == key, state == "preparing" else { return false }
    openingReady=true;return true
  }
  private func adjacent(_ frame:NCIdleFrameState.Presented,_ incoming:Int,_ value:Timeline) -> Bool {
    guard frame.motionId == value.motionId, (0..<value.sourceFrameCount).contains(frame.sourceFrame) else { return false }
    let delta=(incoming-frame.sourceFrame+value.sourceFrameCount)%value.sourceFrameCount
    // Ping-pong anticipation may exit backwards; never widen the one-frame tolerance.
    return min(delta,value.sourceFrameCount-delta) <= 1
  }
  func decision() -> String {
    if let result=pending { pending=nil;return result }
    guard state == "preparing" else { return "wait" }
    // Elapsed time cannot authorize a visual switch; wait for ready pixels
    // and the matching pose. Cancellation/hidden remain separate exits.
    guard let value=timeline else { return "unmapped" }
    if openingReady, let frame=observation, fresh(frame),
      frame.motionId != value.motionId || adjacent(frame,value.sourceIndices[0],value) {
      outgoing=frame;state="armed";return "arm"
    }
    return "wait"
  }
  func presentedSpeech(_ value:Int64,_ sourceTick:Int) -> Bool {
    guard let mapping=timeline, value == key, ["armed","speech"].contains(state),
      mapping.sourceIndices.indices.contains(sourceTick) else { return false }
    let frame=mapping.sourceIndices[sourceTick]
    if state == "armed", outgoing?.motionId == mapping.motionId {
      if let previous=observation, fresh(previous), sourceTick == 0, adjacent(previous,frame,mapping) {
        pending="aligned"
      } else {
        pending="alignment_mismatch";state="preparing";outgoing=nil;return false
      }
    }
    state="speech";lastSpeechFrame=frame;return true
  }
  func heard(_ value:Int64,_ samples:Int64) {
    if value == key, ["armed","speech"].contains(state), samples >= heardSamples { heardSamples=samples }
  }
  func completed(_ value:Int64) {
    guard let mapping=timeline, value == key, state == "speech", let last=lastSpeechFrame else { return }
    state="returning";revision += 1;returnLease=Return(revision,key,mapping.motionId,(last+1)%mapping.sourceFrameCount)
  }
  func returnFrame(_ value:Int64) -> Return? { state == "returning" && value == key ? returnLease : nil }
  func returnPresented(_ lease:Return,_ frame:NCIdleFrameState.Presented) -> Bool {
    guard state == "returning", lease === returnLease, lease.revision == revision, lease.key == key,
      fresh(frame), frame.motionId == lease.motionId, frame.sourceFrame == lease.sourceFrame else { return false }
    observation=frame;returnLease=nil;state="idle";return true
  }
  func hidden() {
    observation=nil;outgoing=nil
    if state == "preparing" { state="armed";pending="hidden" }
    if state == "returning" { revision += 1;returnLease=nil;state="idle" }
  }
  func cancel(_ value:Int64) {
    guard value == key, !["closed","idle"].contains(state) else { return }
    revision += 1;returnLease=nil;pending="cancelled";openingReady=false
    lastSpeechFrame=nil;outgoing=nil;state="idle"
  }
  func fadeMs(_ from:String,_ to:String,_ configured:Int) -> Int { from == to ? 0 : max(0,min(5000,configured)) }
  func close() {
    revision += 1;returnLease=nil;pending=nil;observation=nil;outgoing=nil;timeline=nil;state="closed"
  }
}
