import UIKit

/// Cached silent H.264 with the same bounded sequential renderer as retained
/// handoffs. Presentation observations never authorize audio or receipts.
final class NCIdleVideo {
  private final class Slot {
    let generation: String, id: String, sourceCount: Int, file:URL
    let container=UIView()
    let owner=UUID().uuidString.replacingOccurrences(of:"-",with:"").lowercased()
    let plan=UUID().uuidString.replacingOccurrences(of:"-",with:"").lowercased()
    var ready=false, closed=false,selecting=false
    var renderer: NCHandoffVideo!
    init(generation: String, id: String, sourceCount: Int,file:URL) {
      self.generation=generation; self.id=id; self.sourceCount=sourceCount;self.file=file
    }
  }
  private weak var host: UIView?
  private let observed:(UIImageView,Int,Double)->Void
  private var current: Slot?, next: Slot?, retiring: Slot?
  private var detaching=[Slot]()
  private var completion: ((Bool)->Void)?
  private var fadeMs=0, allowed=false, speech=false
  private(set) var visible=false
  init(host: UIView,observed:@escaping (UIImageView,Int,Double)->Void = { _,_,_ in }) { self.host=host;self.observed=observed }
  func layout() { for slot in [current,next,retiring].compactMap({$0}) { slot.container.frame=host?.bounds ?? .zero } }
  func prepareAt(generation: String, id: String, file: URL, fade: Int, sourceCount: Int,
    startFrame: Int, done: @escaping (Bool)->Void) {
    prepare(generation:generation,id:id,file:file,fade:fade,sourceCount:sourceCount,startFrame:startFrame,reuseCurrent:true,done:done)
  }
  private func prepare(generation:String,id:String,file:URL,fade:Int,sourceCount:Int,startFrame:Int,reuseCurrent:Bool,done:@escaping (Bool)->Void) {
    precondition(Thread.isMainThread)
    guard let host else { done(false); return }
    guard (1...1440).contains(sourceCount), (0..<sourceCount).contains(startFrame) else { done(false); return }
    if reuseCurrent,let current, current.generation == generation, current.id == id, current.sourceCount == sourceCount, current.ready, !current.closed, startFrame == 0 { done(true); return }
    if reuseCurrent,let current, current.generation != generation { clear() }
    let cancelled=completion; completion=nil; cancelled?(false)
    if let next { retire(next) }; next=nil
    if let retiring { retire(retiring) }; retiring=nil
    let slot=Slot(generation:generation,id:id,sourceCount:sourceCount,file:file)
    next=slot; completion=done; fadeMs=max(0,min(5000,fade))
    slot.container.frame=host.bounds; slot.container.autoresizingMask=[.flexibleWidth,.flexibleHeight]
    host.insertSubview(slot.container,at:0)
    slot.renderer=NCHandoffVideo(host:slot.container,presented:{ [weak self,weak slot] view,_,_,at in
      guard let self, let slot, !slot.closed, self.next === slot || self.current === slot else { return }
      if !slot.ready {
        slot.ready=true; slot.renderer.setPaused(true)
        let callback=self.completion; self.completion=nil; callback?(true)
      }
      if !slot.closed,self.current === slot,let source=slot.renderer.status["sourceFrame"] as? Int { self.observed(view,source,at) }
    },failed:{ [weak self,weak slot] _ in
      guard let self, let slot, !slot.closed else { return }
      if self.next === slot { self.next=nil; let callback=self.completion; self.completion=nil; callback?(false) }
      if self.current === slot { self.current=nil; self.visible=false }
      self.retire(slot)
    })
    let began=file.lastPathComponent.hasPrefix("nc_musetalk_idle_")
      ? slot.renderer.beginCycleAt(owner:slot.owner,id:slot.plan,sourceCount:sourceCount,startTick:startFrame)
      : slot.renderer.beginCachedCycle(owner:slot.owner,id:slot.plan,contentId:id,sourceCount:sourceCount,startTick:startFrame)
    guard began else {
      next=nil; completion=nil; retire(slot); done(false); return
    }
    slot.renderer.append(owner:slot.owner,id:slot.plan,index:0,url:file) { [weak self,weak slot] accepted in
      guard let self, let slot, !accepted, self.next === slot else { return }
      self.next=nil; let callback=self.completion; self.completion=nil; self.retire(slot); callback?(false)
    }
  }
  func select(generation: String, id: String) -> Bool {
    precondition(Thread.isMainThread)
    if let current, current.generation == generation, current.id == id, current.ready, !current.closed, next == nil { return true }
    guard let slot=next, slot.generation == generation, slot.id == id, slot.ready, !slot.closed else { return false }
    if let retiring { retire(retiring) }
    let old=current; retiring=old; current=slot; next=nil
    old?.renderer.setPaused(true)
    let duration=visible && old != nil && old?.id != id ? Double(fadeMs)/1000 : 0
    slot.container.alpha=0; host?.bringSubviewToFront(slot.container)
    visible=allowed && !speech; slot.renderer.setPaused(!visible || slot.selecting)
    UIView.animate(withDuration:duration,animations:{ slot.container.alpha=self.visible ? 1 : 0 },completion:{ [weak self] _ in
      if let old { self?.retire(old) }; if self?.retiring === old { self?.retiring=nil }
    })
    return true
  }
  func display(allowed: Bool, speech: Bool) {
    precondition(Thread.isMainThread)
    self.allowed=allowed; self.speech=speech
    let show=allowed && !speech && current?.ready == true && current?.closed == false
    if visible != show {
      visible=show; current?.container.layer.removeAllAnimations(); current?.container.alpha=show ? 1 : 0
      if let retiring { retire(retiring) }; retiring=nil
    }
    if let current { current.renderer.setPaused(!show || current.selecting) }
  }
  func prepareContinuation(_ source:Int,done:@escaping (Bool)->Void) {
    guard let slot=current,!slot.closed,(0..<slot.sourceCount).contains(source) else { done(false);return }
    prepare(generation:slot.generation,id:slot.id,file:slot.file,fade:0,sourceCount:slot.sourceCount,startFrame:source,reuseCurrent:false,done:done)
  }
  func continueAt(_ source:Int,done:@escaping (Bool)->Void) {
    prepareContinuation(source) { ready in done(ready && self.selectContinuation(source)) }
  }
  func prepareContinuation(generation:String,id:String,file:URL,sourceCount:Int,source:Int,done:@escaping (Bool)->Void) {
    prepare(generation:generation,id:id,file:file,fade:0,sourceCount:sourceCount,startFrame:source,reuseCurrent:false,done:done)
  }
  func selectContinuation(_ source:Int)->Bool {
    guard let slot=next,slot.renderer.status["sourceFrame"] as? Int == source else { return false }
    slot.selecting=true
    guard select(generation:slot.generation,id:slot.id) else { slot.selecting=false;return false }
    slot.renderer.observeSelected { [weak self,weak slot] in
      guard let self,let slot,self.current === slot,!slot.closed else { return }
      slot.selecting=false;slot.renderer.setPaused(!self.visible)
    }
    return true
  }
  func cancelContinuation() {
    let callback=completion;completion=nil
    if let next { retire(next) };next=nil;callback?(false)
  }
  var position: [String:Any]? {
    guard let current, current.ready, !current.closed else { return nil }
    return current.renderer.status.merging(["generation":current.generation,"id":current.id,"mediaId":current.plan,"sourceCount":current.sourceCount,"visible":visible]) { _,new in new }
  }
  private func retire(_ slot: Slot) {
    guard !slot.closed else { return }; slot.closed=true; slot.container.layer.removeAllAnimations(); detaching.append(slot)
    slot.renderer.clearDetached { [weak self] safe in
      if safe { slot.renderer.close(); slot.container.removeFromSuperview(); self?.detaching.removeAll { $0 === slot } }
    }
  }
  func clear() { clearDetached { _ in } }
  func clearDetached(_ done: @escaping (Bool)->Void) {
    precondition(Thread.isMainThread)
    let callback=completion; completion=nil
    var slots=[Slot]()
    for slot in [current,next,retiring].compactMap({$0})+detaching { if !slots.contains(where:{$0 === slot}) { slots.append(slot) } }
    current=nil; next=nil; retiring=nil; visible=false
    for slot in slots { retire(slot) }; callback?(false)
    if slots.isEmpty { done(true); return }
    var remaining=slots.count, safe=true
    for slot in slots { slot.renderer.clearDetached { detached in
      safe=safe && detached; remaining -= 1; if remaining == 0 { done(safe) }
    } }
  }
}
