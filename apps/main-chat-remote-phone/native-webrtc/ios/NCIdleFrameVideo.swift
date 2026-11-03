import UIKit
import AVFoundation

/// Silent frame-backed cache output; no audio/session authority. A source keeps
/// only its displayed and incoming frame, not an entire decoded loop.
final class NCIdleFrameVideo {
  private final class Slot {
    let generation: String, id: String, motion: String, count: Int, fps: Int
    let view = UIImageView()
    let source: NCIdleFrameSource
    var frame: NCIdleFrameSource.Frame?
    var observation: NCIdleFrameState.Presented?
    var ready = false, closed = false, revision = 0
    var due: Double = 0
    var tick: DispatchWorkItem?
    var completion: ((Bool) -> Void)?
    init?(generation: String, id: String, url: URL, motion: String, count: Int, fps: Int) {
      guard [6,8,12,24].contains(fps), let source = NCIdleFrameSource(url:url,generation:generation,
        motionId:motion,sourceFrameCount:count) else { return nil }
      self.generation=generation; self.id=id; self.motion=motion; self.count=count; self.fps=fps; self.source=source
      view.contentMode = .scaleAspectFit
    }
    func pause() {
      revision += 1; tick?.cancel(); tick=nil; due=0; source.pause(); observation?.playing=false
    }
    func close() {
      guard !closed else { return }; closed=true; pause(); source.close()
      view.layer.removeAllAnimations(); view.removeFromSuperview()
      let done=completion; completion=nil; done?(false)
    }
  }
  private weak var host: UIView?
  private var current: Slot?, next: Slot?, retiring: Slot?
  private var fade: Double = 0
  private(set) var visible = false
  init(host: UIView) { self.host=host }
  func layout() { for slot in [current,next,retiring].compactMap({$0}) { slot.view.frame=host?.bounds ?? .zero } }
  func prepare(generation: String, id: String, url: URL, motion: String, count: Int,
               fps: Int, fadeMs: Int, done: @escaping (Bool) -> Void) {
    precondition(Thread.isMainThread)
    if let current, !current.closed, current.ready, current.generation == generation,
      current.id == id, current.motion == motion { done(true); return }
    guard let host else { done(false); return }
    if current?.generation != generation { clear() }
    next?.close(); retiring?.close(); retiring=nil
    guard let slot=Slot(generation:generation,id:id,url:url,motion:motion,count:count,fps:fps) else { done(false); return }
    next=slot; fade=Double(max(0,min(5000,fadeMs)))/1000; slot.completion=done
    slot.view.frame=host.bounds; host.insertSubview(slot.view,at:0)
    load(slot,0)
    DispatchQueue.main.asyncAfter(deadline:.now()+2) { [weak self, weak slot] in
      guard let self, let slot, self.next === slot, !slot.ready else { return }
      self.next=nil; slot.close()
    }
  }
  private func load(_ slot: Slot, _ index: Int) {
    slot.revision += 1; let revision=slot.revision
    slot.source.prepareFrame(index) { [weak self, weak slot] frame in
      guard let self, let slot, !slot.closed, slot.revision == revision else { return }
      guard let frame else { let done=slot.completion;slot.completion=nil;done?(false);return }
      slot.frame=frame
      CATransaction.begin(); CATransaction.setDisableActions(true)
      slot.view.image=UIImage(cgImage:frame.image)
      CATransaction.setCompletionBlock { [weak self, weak slot] in
        DispatchQueue.main.async {
          guard let self, let slot, !slot.closed, slot.revision == revision else { return }
          slot.ready=true
          if self.visible && self.current === slot { self.confirm(slot) }
          let done=slot.completion;slot.completion=nil;done?(true)
          self.schedule(slot)
        }
      }; CATransaction.commit()
    }
  }
  private func confirm(_ slot: Slot) {
    guard let frame=slot.frame, visible, current === slot,
      slot.source.confirmPresented(frame,visible:true) else { return }
    slot.observation=slot.source.observe(); slot.observation?.playing=true
  }
  private func schedule(_ slot: Slot) {
    slot.tick?.cancel();slot.tick=nil
    guard visible, current === slot, !slot.closed else { return }
    let now=ProcessInfo.processInfo.systemUptime
    slot.due=max(slot.due+1/Double(slot.fps),now)
    let task=DispatchWorkItem { [weak self, weak slot] in
      guard let self, let slot, self.visible, self.current === slot, !slot.closed else { return }
      let next=(slot.frame?.sourceFrame ?? 0)+24/slot.fps
      self.load(slot,next >= slot.count ? 0 : next)
    }
    slot.tick=task;DispatchQueue.main.asyncAfter(deadline:.now()+max(0.001,slot.due-now),execute:task)
  }
  func select(generation: String, id: String) -> Bool {
    if let current, current.generation == generation, current.id == id, current.ready, !current.closed { return true }
    guard let slot=next, slot.generation == generation, slot.id == id, slot.ready, !slot.closed else { return false }
    let old=current;retiring?.close();retiring=old;old?.pause()
    current=slot;next=nil;host?.bringSubviewToFront(slot.view);slot.view.alpha=0
    let duration=visible && old != nil && old?.motion != slot.motion ? fade : 0
    UIView.animate(withDuration:duration,animations:{slot.view.alpha=self.visible ? 1 : 0}) { [weak self, weak slot] _ in
      old?.close();guard let self, let slot else { return }
      if self.retiring === old { self.retiring=nil }
      if self.visible && self.current === slot { self.confirm(slot);self.schedule(slot) }
    }
    return true
  }
  func display(allowed: Bool, speech: Bool) {
    let show=allowed && !speech && current?.ready == true && current?.closed == false
    guard show != visible else { return };visible=show
    if let slot=current {
      slot.view.layer.removeAllAnimations();slot.view.alpha=show ? 1 : 0
      if show { confirm(slot);schedule(slot) } else { slot.pause() }
    }
    retiring?.close();retiring=nil
  }
  func position() -> NCIdleFrameState.Presented? { visible ? current?.observation : nil }
  func continuation(motion: String, frame: Int, done: @escaping (Bool) -> Void) {
    guard let slot=current, slot.motion == motion, (0..<slot.count).contains(frame), !slot.closed else { done(false);return }
    slot.pause();slot.completion?(false);slot.completion=done;load(slot,frame)
  }
  func clear() {
    visible=false
    let slots=[current,next,retiring].compactMap({$0});current=nil;next=nil;retiring=nil
    slots.forEach {$0.close()}
  }
}
