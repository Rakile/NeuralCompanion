import UIKit
import WebRTC

/// Silent decoded opening behind the outgoing surface. This prepares pixels;
/// it does not authorize Opus, claim display completion, or emit receipts.
final class NCSpeechOpening {
  private final class Slot {
    let key: UInt64, first: Int
    let container=UIView()
    var ended=false, ready=false,shown=false,selected=false
    var completion: ((Bool)->Void)?
    var renderer: NCHandoffVideo!
    init(key: UInt64, first: Int) { self.key=key;self.first=first }
  }
  private weak var host: UIView?
  private let observed: (UIImageView,Int,Double)->Void
  private var active: Slot?
  private weak var lastView:UIImageView?
  private var fadeImage:UIImageView?,fadeMs=0,fading=false
  private(set) var fadeCount=0
  private func clearFade() { fadeImage?.layer.removeAllAnimations();fadeImage?.removeFromSuperview();fadeImage=nil;fadeMs=0;fading=false }
  func beginFade(_ milliseconds:Int) {
    clearFade()
    guard milliseconds>0,let host,let picture=lastView?.image else { return }
    let image=UIImageView(image:picture);image.frame=host.bounds;image.autoresizingMask=[.flexibleWidth,.flexibleHeight];image.contentMode = .scaleToFill
    fadeImage=image;fadeMs=min(5000,milliseconds);host.addSubview(image)
  }
  private var retiring=[Slot]()
  init(host: UIView, observed: @escaping (UIImageView,Int,Double)->Void = { _,_,_ in }) {
    self.host=host;self.observed=observed
  }
  func layout() { active?.container.frame=host?.bounds ?? .zero }
  var status:[String:Any] {
    guard let slot=active else { return ["active":false] }
    return ["active":true,"key":slot.key,"ready":slot.ready,"shown":slot.shown,
      "selected":slot.selected,"ended":slot.ended,"renderer":slot.renderer.status]
  }
  func ready(_ key:UInt64)->Bool { active.map { $0.key==key && $0.ready && !$0.ended } ?? false }
  @discardableResult func heard(_ key:UInt64,samples:Int)->Bool {
    guard let slot=active,slot.key==key,slot.ready,!slot.ended,samples>=0 else { return false }
    slot.renderer.limitTo(samples/2000)
    if !slot.shown {
      slot.shown=true;host?.bringSubviewToFront(slot.container)
      slot.renderer.observeSelected { [weak self,weak slot] in
        guard let self,let slot,self.active === slot,slot.shown,!slot.ended else { return }
        // Keep the prepared image still; the buffered file player owns motion.
        slot.selected=true
      }
    }
    return true
  }
  func cover() { clearFade();active?.shown=false;active?.selected=false;active?.container.alpha=0;active?.renderer.setPaused(true) }
  func display(_ allowed:Bool) { active?.container.isHidden = !allowed }
  func stream(_ key:UInt64,frame:RTCVideoFrame,shown:@escaping (UIImageView,Double)->Void)->Bool {
    guard let slot=active,slot.key==key,slot.ready,slot.shown,slot.selected,!slot.ended else { return false }
    return slot.renderer.streamFrame(frame) { [weak self,weak slot] view,at in
      guard let self,let slot,self.active === slot,slot.shown,!slot.ended else { return }
      self.lastView=view;slot.container.alpha=1;self.host?.bringSubviewToFront(slot.container)
      if let image=self.fadeImage {
        self.host?.bringSubviewToFront(image)
        if !self.fading {
          self.fading=true;self.fadeCount += 1
          UIView.animate(withDuration:Double(self.fadeMs)/1000,animations:{image.alpha=0},completion:{ [weak self,weak image] _ in
            if let self,let image,self.fadeImage === image { self.clearFade() }
          })
        }
      }
      shown(view,at)
    }
  }
  func prepare(owner: String, key: UInt64, media: String, file: URL, indices: [Int], sourceCount: Int, done: @escaping (Bool)->Void) {
    precondition(Thread.isMainThread)
    guard let host,active == nil,retiring.isEmpty,(1...UInt64(Int32.max)).contains(key),(1...12).contains(indices.count) else { done(false);return }
    let slot=Slot(key:key,first:indices[0]);active=slot;slot.completion=done
    slot.container.frame=host.bounds;slot.container.autoresizingMask=[.flexibleWidth,.flexibleHeight]
    host.insertSubview(slot.container,at:0)
    slot.renderer=NCHandoffVideo(host:slot.container,presented:{ [weak self,weak slot] view,segment,position,at in
      guard let self,let slot,self.active === slot,!slot.ended else { return }
      if slot.ready {
        if slot.shown,let source=slot.renderer.status["sourceFrame"] as? Int { self.observed(view,source,at) }
        return
      }
      guard let source=slot.renderer.status["sourceFrame"] as? Int,source == slot.first,segment == 0,position == 0 else {
        self.clear(key:slot.key) { _ in };return
      }
      slot.renderer.setPaused(true);slot.ready=true;self.observed(view,source,at)
      guard self.active === slot,!slot.ended else { return }
      let callback=slot.completion;slot.completion=nil;callback?(true)
    },failed:{ [weak self,weak slot] _ in
      guard let self,let slot,self.active === slot else { return };self.clear(key:slot.key) { _ in }
    })
    guard slot.renderer.begin(owner:owner,id:media,sequence:indices,sourceCount:sourceCount) else { clear(key:key) { _ in };return }
    slot.renderer.append(owner:owner,id:media,index:0,url:file) { [weak self,weak slot] accepted in
      guard let self,let slot,!accepted,self.active === slot else { return };self.clear(key:key) { _ in }
    }
  }
  func clear(key: UInt64, done: @escaping (Bool)->Void) {
    precondition(Thread.isMainThread)
    if let slot=active,slot.key != key { done(false);return }
    clearFade();lastView=nil
    if let slot=active {
      guard slot.key == key else { done(false);return }
      active=nil;slot.ended=true;retiring.append(slot)
      let callback=slot.completion;slot.completion=nil;callback?(false)
    }
    let pending=retiring.filter { $0.key == key }
    guard !pending.isEmpty else { done(true);return }
    var remaining=pending.count,safe=true
    for slot in pending { slot.renderer.clearDetached { [weak self] detached in
      if detached { slot.renderer.close();slot.container.removeFromSuperview();self?.retiring.removeAll { $0 === slot } }
      safe = safe && detached;remaining -= 1;if remaining == 0 { done(safe) }
    } }
  }
  func clearAll(_ done: @escaping (Bool)->Void) {
    guard let key=active?.key ?? retiring.first?.key else { done(true);return };clear(key:key,done:done)
  }
}
