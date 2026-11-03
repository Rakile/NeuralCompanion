import UIKit
import WebRTC

struct NCBufferedVisualSource {
  let motion:String,count:Int,indices:[Int],generation:String,id:String,file:URL,start:Int,fade:Int
  static func parse(_ data:[String:Any])->NCBufferedVisualSource? {
    func integer(_ name:String)->Int? {
      guard let n=data[name] as? NSNumber,CFGetTypeID(n) != CFBooleanGetTypeID() else { return nil }
      let v=n.doubleValue;guard v.isFinite,v==floor(v),v>=0,v<=Double(Int32.max) else { return nil };return Int(v)
    }
    guard let motion=data["motionId"] as? String,let count=integer("sourceFrameCount"),let start=integer("startFrame"),let fade=integer("fadeMs"),
      let generation=data["idleGeneration"] as? String,let id=data["idleId"] as? String,let rows=data["sourceIndices"] as? [NSNumber],
      let uri=data["idleUri"] as? String,let file=URL(string:uri),file.isFileURL,
      motion.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,id.range(of:"^[a-f0-9]{64}$",options:.regularExpression) != nil,
      (1...1024).contains(generation.count),(1...1440).contains(count),(0..<count).contains(start),(0...5000).contains(fade),(1...720).contains(rows.count),
      rows.allSatisfy({ CFGetTypeID($0) != CFBooleanGetTypeID() && $0.doubleValue.isFinite && $0.doubleValue==floor($0.doubleValue) && $0.doubleValue>=0 && $0.doubleValue<Double(count) }) else { return nil }
    return NCBufferedVisualSource(motion:motion,count:count,indices:rows.map{$0.intValue},generation:generation,id:id,file:file,start:start,fade:fade)
  }
}

/// Main-thread composition of existing silent players. Only the playback
/// hardware observer calls heard(); no method here acknowledges audio. Layer
/// commits are diagnostic observations, not proof of physical display scanout.
final class NCVisualTransition {
  private weak var host:UIView?
  private let observed:(UIImageView,String,Int,Double)->Void
  lazy var idle:NCIdleVideo = NCIdleVideo(host:host!,observed:{ [weak self] view,source,at in
    guard let self else { return }
    self.observed(view,self.returning ? "returned" : "idle",source,at)
    if self.phase == "preparing",self.ready,source == self.sequence.first {
      self.host?.bringSubviewToFront(self.retainedHost);self.phase="retained"
      self.idle.display(allowed:self.allowed,speech:true);self.retained?.setPaused(false)
    }
  })
  private lazy var opening=NCSpeechOpening(host:host!,observed:{ [weak self] view,source,at in
    guard let self,self.phase == "speech" else { return }
    self.lastSpeech=source;self.observed(view,"opening",source,at)
  })
  private let retainedHost=UIView()
  private var retained:NCHandoffVideo?,retiring=[NCHandoffVideo]()
  private var key:UInt64=0,openingKey:UInt64=0
  private var owner="",plan="",sequence=[Int](),timeline=[Int](),successors=[UInt64:[Int]]()
  private var source:NCBufferedVisualSource?,sourceSuccessors=[UInt64:NCBufferedVisualSource](),returnRevision=0
  private var count=0,revision=0,lastSpeech = -1,preparedReturn = -1
  private var ready=false,allowed=false,returning=false,returnReady=false
  private var appointment=0.0,failure=""
  private(set) var phase="ended"
  init(host:UIView,observed:@escaping (UIImageView,String,Int,Double)->Void = { _,_,_,_ in }) {
    self.host=host;self.observed=observed
    retainedHost.frame=host.bounds;retainedHost.autoresizingMask=[.flexibleWidth,.flexibleHeight]
    host.insertSubview(retainedHost,at:0)
  }
  func layout() { retainedHost.frame=host?.bounds ?? .zero;idle.layout();opening.layout() }
  private func createRetained()->NCHandoffVideo {
    NCHandoffVideo(host:retainedHost,presented:{ [weak self] view,_,_,at in
      guard let self,self.phase != "ended" else { return }
      if !self.ready { self.ready=true;self.retained?.setPaused(true);return }
      if self.phase == "retained",let source=self.retained?.status["sourceFrame"] as? Int { self.observed(view,"retained",source,at) }
    },failed:{ [weak self] reason in
      guard let self else { return };self.phase="degraded";self.failure=reason;self.idle.display(allowed:self.allowed,speech:false)
    })
  }
  func begin(_ generation:String,key nextKey:UInt64,media:String,indices:[Int],sourceCount:Int)->Bool {
    precondition(Thread.isMainThread)
    guard phase == "ended",retiring.isEmpty,(1...UInt64(Int32.max)).contains(nextKey),allowed,
      idle.position?["sourceCount"] as? Int == sourceCount else { return false }
    let reader=createRetained()
    guard reader.begin(owner:generation,id:media,sequence:indices,sourceCount:sourceCount) else { reader.close();return false }
    retained=reader;revision += 1;owner=generation;key=nextKey;openingKey=nextKey;plan=media;sequence=indices;count=sourceCount
    ready=false;returning=false;lastSpeech = -1;appointment=0;failure="";phase="preparing";return true
  }
  func append(_ value:UInt64,index:Int,file:URL,done:@escaping (Bool)->Void) {
    guard value==key,phase != "ended",let retained else { done(false);return }
    retained.append(owner:owner,id:plan,index:index,url:file,done:done)
  }
  func prepareOpening(_ generation:String,key value:UInt64,media:String,file:URL,indices:[Int],sourceCount:Int,done:@escaping (Bool)->Void) {
    guard value==key,generation==owner,sourceCount==count,(1...720).contains(indices.count),
      indices.allSatisfy({(0..<count).contains($0)}),indices.first==sequence.first else { done(false);return }
    timeline=indices;if source==nil { prepareReturn((indices.last!+1)%count) }
    opening.prepare(owner:generation,key:value,media:media,file:file,indices:Array(indices.prefix(12)),sourceCount:sourceCount,done:done)
  }
  func arm(_ value:UInt64,minimumMs:Int,maximumMs:Int)->Double {
    guard value==key,phase=="retained",opening.ready(key),allowed else { return 0 }
    let at=retained?.armExit(owner:owner,id:plan,minLeadMs:minimumMs,maxLeadMs:maximumMs) ?? 0
    if at>0 { appointment=at };return at
  }
  func heard(_ value:UInt64,samples:Int,completed:Bool,successor:Bool) {
    precondition(Thread.isMainThread)
    // Native-started playback can still report position zero. Callers must
    // supply the existing guard's start observation, not download readiness.
    guard phase != "ended",allowed,samples>=0,value>=key else { return }
    if value>key && !advance(value) { return }
    if ["retained","preparing","degraded"].contains(phase),opening.ready(key),let first=timeline.first {
      let source=(phase=="retained" ? retained?.status["sourceFrame"] : idle.position?["sourceFrame"]) as? Int
      let delta=source.map { abs($0-first) }
      let matching=delta.map { min($0,count-$0)<=1 } ?? false
      if !matching || appointment==0 || abs(ProcessInfo.processInfo.systemUptime-appointment)>0.125 { failure="alignment_missed" }
      phase="speech";lastSpeech=first;retained?.setPaused(true);idle.display(allowed:allowed,speech:true)
    }
    if phase=="speech" { opening.heard(key,samples:samples) }
    if completed && !successor && successors.isEmpty && ["speech","stream"].contains(phase) && lastSpeech>=0 {
      // Complete against the declared timeline, not its last observed picture:
      // the display may omit a final frame after native audio has completed.
      phase="returning";returning=true;let token=revision,source=self.source?.start ?? ((timeline.last!+1)%count)
      let finish:(Bool)->Void = { [weak self] accepted in
        guard let self,token==self.revision,self.phase=="returning" else { return }
        if accepted { self.phase="returned";self.opening.cover();self.idle.display(allowed:self.allowed,speech:false) }
        else { self.phase="degraded";self.failure="return_unavailable";self.returning=false }
      }
      if returnReady && preparedReturn==source { finish(idle.selectContinuation(source)) }
      else if let configured=self.source {
        idle.prepareContinuation(generation:configured.generation,id:configured.id,file:configured.file,sourceCount:configured.count,source:source) { ready in
          finish(ready && self.idle.selectContinuation(source))
        }
      } else { idle.continueAt(source,done:finish) }
    }
  }
  @discardableResult func streamed(_ value:UInt64,sourceTick:Int)->Bool {
    guard value>=key,["speech","stream"].contains(phase) else { return false }
    if value>key && !advance(value) { return false }
    guard timeline.indices.contains(sourceTick) else { return false }
    // Display cadence can skip pictures, including at lower encoded quality.
    // Source continuity is the declared chunk boundary checked in advance.
    lastSpeech=timeline[sourceTick];phase="stream";retained?.setPaused(true);return true
  }
  func streamFrame(_ value:UInt64,sourceTick:Int,frame:RTCVideoFrame)->Bool {
    let mapping=value==key ? timeline : successors[value]
    guard allowed,["speech","stream"].contains(phase),let mapping,mapping.indices.contains(sourceTick) else { return false }
    let token=revision
    return opening.stream(openingKey,frame:frame) { [weak self] view,at in
      guard let self,token==self.revision,self.allowed,self.streamed(value,sourceTick:sourceTick) else { return }
      self.observed(view,"rtp",self.lastSpeech,at)
    }
  }
  func next(_ value:UInt64,sourceCount:Int,indices:[Int])->Bool {
    guard !["ended","returned","returning"].contains(phase),value>key,value<=UInt64(Int32.max),sourceCount==count,
      indices.count<=720,indices.allSatisfy({(0..<count).contains($0)}),successors.isEmpty || successors[value] != nil else { return false }
    if let old=successors[value],!old.isEmpty { return old==indices }
    successors[value]=indices
    if let last=indices.last { prepareReturn((last+1)%count) };return true
  }
  private func prepareReturn(_ source:Int) {
    let token=revision;returnRevision += 1;let preparing=returnRevision;preparedReturn=source;returnReady=false
    idle.prepareContinuation(source) { [weak self] ready in
      guard let self,token==self.revision,preparing==self.returnRevision,self.preparedReturn==source else { return };self.returnReady=ready
    }
  }
  func configure(_ value:UInt64,source next:NCBufferedVisualSource,done:@escaping (Bool)->Void) {
    guard !["ended","returned","returning"].contains(phase),value>=key,value<=UInt64(Int32.max),
      value != key || (source==nil && next.count==count),value==key || successors.isEmpty || successors[value] != nil else { done(false);return }
    if value==key { source=next } else { successors[value]=next.indices;sourceSuccessors[value]=next }
    let token=revision;returnRevision += 1;let preparing=returnRevision;preparedReturn=next.start;returnReady=false
    idle.prepareContinuation(generation:next.generation,id:next.id,file:next.file,sourceCount:next.count,source:next.start) { [weak self] ready in
      guard let self else { done(false);return }
      let current=token==self.revision && preparing==self.returnRevision && self.phase != "ended"
      if current { self.returnReady=ready };done(current && ready)
    }
  }
  private func advance(_ value:UInt64)->Bool {
    guard let next=successors[value],!next.isEmpty else { return false }
    let configured=sourceSuccessors[value],changed=configured != nil && configured?.motion != source?.motion
    if !changed,let last=timeline.last,let first=next.first {
      let difference=abs(first-last)
      if min(difference,count-difference)>1 && failure.isEmpty { failure="stream_alignment_missed" }
    }
    if changed,let configured { opening.beginFade(configured.fade) }
    if let configured { source=configured;count=configured.count }
    sourceSuccessors=sourceSuccessors.filter{$0.key>value}
    key=value;timeline=next;successors=successors.filter { $0.key>value };phase="stream";return true
  }
  func display(_ visible:Bool,ordinarySpeech:Bool) {
    allowed=visible
    retainedHost.isHidden = !visible;opening.display(visible)
    idle.display(allowed:visible,speech:ordinarySpeech || ["retained","speech","stream","returning"].contains(phase))
    retained?.setPaused(!visible || (ready && phase != "retained"))
  }
  var status:[String:Any] {
    let source:Int
    switch phase {
    case "speech","stream","returning":source=lastSpeech
    case "preparing","returned","degraded":source=idle.position?["sourceFrame"] as? Int ?? -1
    case "retained":source=retained?.status["sourceFrame"] as? Int ?? -1
    default:source = -1
    }
    return ["key":key,"state":phase,"failure":failure,"ready":ready,"openingReady":opening.ready(openingKey),"sourceFrame":source,
      "fadeCount":opening.fadeCount,"motionId":self.source?.motion ?? "","sourceFrameCount":count,
      "opening":opening.status]
  }
  var activeKey:UInt64 { phase=="ended" ? 0 : key }
  func clearDetached(_ done:@escaping (Bool)->Void) {
    precondition(Thread.isMainThread)
    revision += 1;returnRevision += 1;phase="ended";ready=false;returning=false;key=0;timeline=[];successors.removeAll();source=nil;sourceSuccessors.removeAll()
    returnReady=false;preparedReturn = -1;idle.cancelContinuation()
    if let retained { retiring.append(retained) };retained=nil
    let pending=retiring;var remaining=pending.count+1,safe=true
    let finish:(Bool)->Void = { result in safe=safe && result;remaining -= 1;if remaining==0 { self.idle.display(allowed:self.allowed,speech:false);done(safe) } }
    for reader in pending { reader.clearDetached { detached in
      if detached { reader.close();self.retiring.removeAll { $0 === reader } };finish(detached)
    } }
    opening.clearAll(finish)
  }
}
