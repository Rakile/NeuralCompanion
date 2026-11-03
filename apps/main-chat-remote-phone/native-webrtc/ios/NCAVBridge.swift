// NeuralCompanion, MIT. ExpoAudio keeps session policy and playback ownership.
import Foundation
import ExpoModulesCore
import WebRTC
import AVFoundation

final class NCAVBridge {
  final class IdleFence {
    let group=DispatchGroup()
    private let lock=NSLock()
    private var result: Bool?
    init(ready: Bool = false) { group.enter(); if ready { finish(true) } }
    func finish(_ safe: Bool) {
      lock.lock(); defer { lock.unlock() }
      guard result == nil else { return }; result=safe; group.leave()
    }
    var safe: Bool { lock.lock(); defer { lock.unlock() }; return result == true }
    func wait() -> Bool { !Thread.isMainThread && group.wait(timeout:.now()+6) == .success && safe }
  }
  final class Entry {
    var bufferedVideo=[String:(UInt64,NCBufferedVideoSource)]() // main-thread only
    lazy var bufferedClock=NCBufferedAudioClock { [weak self] value in
      guard let self,self.ready else { return };self.idleView?.bufferedHeard(value)
    }
    private var bufferedVisible = false, localShown = false
    var buffered: Bool { true }
    var localVisualAllowed: Bool { lock.lock(); defer { lock.unlock() }; return ready && bufferedVisible }
    func setLocalVisible(_ value: Bool) { lock.lock(); localShown=value; lock.unlock() }
    var localVisible: Bool { lock.lock(); defer { lock.unlock() }; return localVisualAllowed && localShown }
    func presentBuffered(_ enabled: Bool) -> Bool {
      lock.lock(); defer { lock.unlock() }
      guard buffered,ready else { return false }; bufferedVisible=enabled
      if !enabled { localShown=false }; return true
    }
    private let lock = NSRecursiveLock()
    private var ended = false
    private var keys = Set<UInt64>()
    private var view: ObjectIdentifier?
    weak var idleView: NCAVView?
    private var idleRevision: Int = 0
    private var idlePrepared: (Int,String,String)?
    private var idlePositionValue: [String:Any]?
    private var handoffStatusValue:[String:Any]?
    func setHandoffStatus(_ value:[String:Any]?) { lock.lock();handoffStatusValue=value;lock.unlock() }
    var handoffStatus:[String:Any]? { lock.lock();defer { lock.unlock() };return ended ? nil : handoffStatusValue }
    func setIdlePosition(_ value: [String:Any]?) { lock.lock(); idlePositionValue=value; lock.unlock() }
    var idlePosition: [String:Any]? { lock.lock(); defer { lock.unlock() }; return ended ? nil : idlePositionValue }
    private var idleDetached=IdleFence(ready:true)
    private var openingRevision=0
    private var openingKey: UInt64=0,lastOpeningKey: UInt64=0
    private var openingDetached=IdleFence(ready:true)
    func beginOpening(_ key: UInt64) -> Int {
      lock.lock();defer { lock.unlock() }
      guard ready,openingKey == 0,key > lastOpeningKey,openingDetached.safe else { return 0 }
      openingKey=key;lastOpeningKey=key;openingRevision += 1;return openingRevision
    }
    func openingCurrent(_ key: UInt64,_ revision: Int) -> Bool {
      lock.lock();defer { lock.unlock() };return ready && openingKey == key && revision > 0 && revision == openingRevision
    }
    func clearOpeningReaders(_ key: UInt64? = nil) -> IdleFence? {
      lock.lock();defer { lock.unlock() }
      if let key,key != lastOpeningKey { return nil }
      openingKey=0;openingRevision += 1
      let target=idleView,previous=openingDetached,cleared=IdleFence(),combined=IdleFence()
      openingDetached=combined
      previous.group.notify(queue:.main) { cleared.group.notify(queue:.main) { combined.finish(previous.safe && cleared.safe) } }
      DispatchQueue.main.async {
        if let target { target.clearOpeningDetached { cleared.finish($0) } } else { cleared.finish(true) }
      }
      return combined
    }
    func clearIdleReaders() -> IdleFence {
      lock.lock(); defer { lock.unlock() }
      let target=idleView, previous=idleDetached, cleared=IdleFence(), combined=IdleFence()
      idleDetached=combined
      previous.group.notify(queue:.main) {
        cleared.group.notify(queue:.main) { combined.finish(previous.safe && cleared.safe) }
      }
      DispatchQueue.main.async {
        if let target { target.clearIdleDetached { cleared.finish($0) } } else { cleared.finish(true) }
      }
      return combined
    }
    func idleBegin() -> Int { lock.lock(); defer { lock.unlock() }; idleRevision += 1; idlePrepared = nil; return idleRevision }
    func idleCurrent(_ revision: Int) -> Bool { lock.lock(); defer { lock.unlock() }; return !ended && revision > 0 && revision == idleRevision }
    func idleDecoded(_ revision: Int, _ generation: String, _ id: String) -> Bool {
      lock.lock(); defer { lock.unlock() }; guard idleCurrent(revision) else { return false }
      idlePrepared = (revision,generation,id); return true
    }
    func idleSelected(_ generation: String, _ id: String) -> Bool {
      lock.lock(); defer { lock.unlock() }; guard let value = idlePrepared else { return false }
      return idleCurrent(value.0) && value.1 == generation && value.2 == id
    }
    var ready: Bool { lock.lock(); defer { lock.unlock() }; return !ended }
    var terminal: Bool { lock.lock(); defer { lock.unlock() }; return ended }
    func stop() {
      lock.lock()
      if ended { lock.unlock(); return }
      ended = true; bufferedVisible=false; localShown=false; _ = idleBegin(); view = nil
      lock.unlock()
      DispatchQueue.main.async {
        self.bufferedClock.close();self.bufferedVideo.values.forEach { $0.1.close() };self.bufferedVideo.removeAll()
      }
      _ = clearIdleReaders()
      _ = clearOpeningReaders()
    }
    func attachView(_ token: NCAVView) {
      lock.lock(); defer { lock.unlock() }
      if !ended { view = ObjectIdentifier(token); idleView = token }
    }
    func detachView(_ token: AnyObject) {
      lock.lock(); defer { lock.unlock() }
      if view == ObjectIdentifier(token) { _ = clearIdleReaders(); _ = clearOpeningReaders(); _ = idleBegin(); view = nil; idleView = nil; localShown=false }
    }
  }
  private final class WeakEntry { weak var value: Entry?; init(_ value: Entry) { self.value = value } }
  private static let registryLock = NSLock()
  private static var registry = [String: WeakEntry]()
  static func entry(_ handle: String) -> Entry? {
    registryLock.lock(); defer { registryLock.unlock() }; return registry[handle]?.value
  }
  private let lock = NSRecursiveLock()
  private var entries = [String: Entry]()
  private var idleDetaches=[String:IdleFence]()
  private var destroyed = false
  private func sync<T>(_ body: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return body() }
  private func key(_ value: Double) -> UInt64? {
    value.isFinite && value.rounded(.down) == value && (1...Double(Int32.max)).contains(value) ? UInt64(value) : nil
  }
  func ready(_ handle: String) -> Bool { sync { entries[handle] }?.ready == true }
  func openBuffered() -> String? {
    sync {
      guard !destroyed,entries.isEmpty else { return nil }
      let entry=Entry(),handle=UUID().uuidString;entries[handle]=entry
      Self.registryLock.lock();Self.registry[handle]=WeakEntry(entry);Self.registryLock.unlock()
      return handle
    }
  }
  func presentBuffered(_ handle:String,enabled:Bool)->Bool { sync { entries[handle] }?.presentBuffered(enabled) == true }
  func bindBufferedAudio(_ handle:String,value:Double,player:AudioPlayer,ticket:String,request:String,chunk:String,samples:Int)->Bool {
    guard Thread.isMainThread,let key=key(value),let entry=sync({entries[handle]}),entry.ready,entry.buffered else { return false }
    return entry.bufferedClock.bind(key,binding:player.ncBinding,ticket:ticket,request:request,chunk:chunk,samples:samples)
  }
  func retireBufferedAudio(_ handle:String,value:Double) {
    guard let key=key(value),let entry=sync({entries[handle]}),entry.buffered else { return }
    DispatchQueue.main.async {
      entry.bufferedClock.remove(key)
      for token in entry.bufferedVideo.filter({$0.value.0==key}).map({$0.key}) { entry.bufferedVideo.removeValue(forKey:token)?.1.close() }
    }
  }
  func bindBufferedVideo(_ handle:String,value:Double,player:AVPlayer,uri:String,start:Int,frames:Int)->String? {
    guard Thread.isMainThread,let key=key(value),let entry=sync({entries[handle]}),entry.ready,entry.buffered,
      entry.bufferedVideo.count<8,entry.bufferedClock.sample(key)?.stopped==false,
      let expected=URL(string:uri),expected.isFileURL,
      (player.currentItem?.asset as? AVURLAsset)?.url==expected else { return nil }
    let token=UUID().uuidString
    guard let source=NCBufferedVideoSource(player:player,start:start,frames:frames,frame:{ [weak entry] tick,frame in
      guard let entry,entry.ready,entry.localVisualAllowed,entry.bufferedVideo[token] != nil,
        let state=entry.bufferedClock.sample(key),state.started,state.playing,!state.stopped,!state.completed else { return }
      entry.idleView?.bufferedFrame(key,tick:tick,frame:frame)
    }) else { return nil }
    entry.bufferedVideo[token]=(key,source);return token
  }
  func retireBufferedVideo(_ handle:String,token:String) {
    precondition(Thread.isMainThread)
    sync({entries[handle]})?.bufferedVideo.removeValue(forKey:token)?.1.close()
  }
  func bufferedVideoReady(_ handle:String,token:String)->Bool {
    precondition(Thread.isMainThread)
    return sync({entries[handle]})?.bufferedVideo[token]?.1.decoded==true
  }
  func visible(_ handle: String) -> Bool {
    guard let entry = sync({ entries[handle] }) else { return false }
    return entry.localVisible
  }
  func idleBegin(_ handle: String) -> Int { sync { entries[handle] }?.idleBegin() ?? 0 }
  func idleClear(_ handle: String) {
    let entry = sync { entries[handle] }
    guard let entry else { return }; _ = entry.idleBegin()
    entry.setLocalVisible(false)
    _ = entry.clearIdleReaders()
  }
  func idlePosition(_ handle: String) -> [String:Any]? {
    guard let entry=sync({entries[handle]}), entry.ready, var value=entry.idlePosition,
      let observed=value["observedAtSeconds"] as? Double, observed > 0 else { return nil }
    value["ageMs"]=(ProcessInfo.processInfo.systemUptime-observed)*1000; return value
  }
  func idleDetachBegin(_ handle: String) -> String? {
    sync {
      guard let entry=entries[handle], idleDetaches.count < 32 else { return nil }
      _ = entry.idleBegin(); entry.setLocalVisible(false)
      let ticket=UUID().uuidString; idleDetaches[ticket]=entry.clearIdleReaders(); return ticket
    }
  }
  func idleDetachWait(_ ticket: String) -> Bool {
    guard !Thread.isMainThread, let fence=sync({idleDetaches[ticket]}) else { return false }
    defer { _ = sync { idleDetaches.removeValue(forKey:ticket) } }
    return fence.wait()
  }
  func openingBegin(_ handle: String,value: Double) -> Int {
    guard let key=key(value) else { return 0 };return sync({entries[handle]})?.beginOpening(key) ?? 0
  }
  func openingDetachBegin(_ handle: String,value: Double) -> String? {
    sync {
      guard let key=key(value),let entry=entries[handle],idleDetaches.count < 32,let fence=entry.clearOpeningReaders(key) else { return nil }
      let ticket=UUID().uuidString;idleDetaches[ticket]=fence;return ticket
    }
  }
  func openingPrepare(_ handle: String,value: Double,revision: Int,owner: String,media: String,uri: String,sourceCount: Int,indices: [Int]) -> Bool {
    guard !Thread.isMainThread,let key=key(value),let entry=sync({entries[handle]}),entry.openingCurrent(key,revision),
      let file=URL(string:uri),file.isFileURL,(1...720).contains(indices.count),(1...1440).contains(sourceCount),
      indices.allSatisfy({(0..<sourceCount).contains($0)}) else { return false }
    let gate=DispatchSemaphore(value:0),resultLock=NSLock();var accepted=false,expired=false
    DispatchQueue.main.async {
      resultLock.lock();let current = !expired;resultLock.unlock()
      guard current,entry.openingCurrent(key,revision),let view=entry.idleView else { gate.signal();return }
      view.prepareOpening(owner:owner,key:key,media:media,file:file,indices:indices,sourceCount:sourceCount) { ready in
        resultLock.lock();accepted=ready && !expired && entry.openingCurrent(key,revision);resultLock.unlock();gate.signal()
      }
    }
    let finished=gate.wait(timeout:.now()+8) == .success
    resultLock.lock();expired = !finished;let result=accepted;resultLock.unlock()
    if !finished { _ = entry.clearOpeningReaders(key) }
    return finished && result && entry.openingCurrent(key,revision)
  }
  // The module worker waits; UIKit and the playback callback never do.
  private func handoffWork(_ handle:String,value:Double,revision:Int,action:@escaping (NCAVView,@escaping (Double)->Void)->Void)->Double {
    guard !Thread.isMainThread,let key=key(value),let entry=sync({entries[handle]}),entry.openingCurrent(key,revision) else { return 0 }
    let gate=DispatchSemaphore(value:0),resultLock=NSLock();var result=0.0,expired=false
    DispatchQueue.main.async {
      resultLock.lock();let current = !expired;resultLock.unlock()
      guard current,entry.openingCurrent(key,revision),let view=entry.idleView else { gate.signal();return }
      action(view) { accepted in
        resultLock.lock();if !expired && entry.openingCurrent(key,revision) { result=accepted };resultLock.unlock();gate.signal()
      }
    }
    let finished=gate.wait(timeout:.now()+8) == .success
    resultLock.lock();expired = !finished;let answer=result;resultLock.unlock()
    if !finished { _ = entry.clearOpeningReaders(key) }
    return finished && entry.openingCurrent(key,revision) ? answer : 0
  }
  func handoffBegin(_ handle:String,value:Double,revision:Int,owner:String,plan:String,count:Int,indices:[Int])->Bool {
    guard let key=key(value) else { return false }
    return handoffWork(handle,value:value,revision:revision) { view,done in
      done(view.beginHandoff(owner:owner,key:key,plan:plan,count:count,indices:indices) ? 1 : 0)
    } == 1
  }
  func handoffAppend(_ handle:String,value:Double,revision:Int,index:Int,uri:String)->Bool {
    guard let key=key(value),let file=URL(string:uri),file.isFileURL else { return false }
    return handoffWork(handle,value:value,revision:revision) { view,done in
      view.appendHandoff(key:key,index:index,file:file) { done($0 ? 1 : 0) }
    } == 1
  }
  func handoffArm(_ handle:String,value:Double,revision:Int)->Double {
    guard let key=key(value) else { return 0 }
    return handoffWork(handle,value:value,revision:revision) { view,done in done(view.armHandoff(key:key)) }
  }
  func handoffNext(_ handle:String,value:Double,revision:Int,next:Double,count:Int,indices:[Int])->Bool {
    guard let key=key(next) else { return false }
    return handoffWork(handle,value:value,revision:revision) { view,done in done(view.nextHandoff(key:key,count:count,indices:indices) ? 1 : 0) } == 1
  }
  func handoffStatus(_ handle:String)->[String:Any]? { sync({entries[handle]})?.handoffStatus }
  func bufferedSource(_ handle:String,value:Double,revision:Int,next:Double,data:[String:Any])->Bool {
    guard let nextKey=key(next),let source=NCBufferedVisualSource.parse(data),sync({entries[handle]})?.buffered==true else { return false }
    return handoffWork(handle,value:value,revision:revision) { view,done in
      view.bufferedSource(key:nextKey,source:source) { done($0 ? 1 : 0) }
    } == 1
  }
  // Module worker only. Native cache IO has just revalidated hash/owner/path;
  // verify media format here, then wait for actual decoded-layer readiness.
  func idlePrepare(_ handle: String, file: [String: Any], fade: Int, revision: Int, sourceTicks: Int = 0) -> Bool {
    guard !Thread.isMainThread, let entry = sync({ entries[handle] }), entry.ready,
          let uri = file["uri"] as? String, let url = URL(string: uri), url.isFileURL,
          let generation = file["generation"] as? String, let id = file["id"] as? String else { return false }
    guard entry.idleCurrent(revision) else { return false }
    let asset = AVURLAsset(url: url), tracks = asset.tracks(withMediaType: .video)
    guard asset.tracks(withMediaType: .audio).isEmpty, tracks.count == 1,
          !tracks[0].formatDescriptions.isEmpty,
          tracks[0].formatDescriptions.allSatisfy({ CMFormatDescriptionGetMediaSubType($0 as! CMFormatDescription) == kCMVideoCodecType_H264 }) else { return false }
    let gate = DispatchSemaphore(value: 0)
    let duration=CMTimeGetSeconds(asset.duration)
    guard duration.isFinite, duration > 0, duration <= 60 else { return false }
    var sourceCount=Int((duration*24).rounded())
    if sourceTicks != 0 {
      let fps=Int(tracks[0].nominalFrameRate.rounded())
      guard (1...1440).contains(sourceTicks), [6,8,12,24].contains(fps) else { return false }
      let step=24/fps
      guard (sourceTicks+step-1)/step == (sourceCount+step-1)/step else { return false }
      sourceCount=sourceTicks
    }
    guard (1...1440).contains(sourceCount) else { return false }
    let resultLock = NSLock(); var accepted = false, expired = false
    DispatchQueue.main.async {
      guard entry.idleCurrent(revision), let view = entry.idleView else { gate.signal(); return }
      view.prepareIdle(generation:generation,id:id,file:url,fade:fade,sourceCount:sourceCount) { ready in
        resultLock.lock(); accepted = ready && !expired && entry.idleDecoded(revision,generation,id); resultLock.unlock(); gate.signal()
      }
    }
    let finished = gate.wait(timeout: .now() + 8) == .success
    resultLock.lock(); defer { resultLock.unlock() }; expired = !finished
    return finished && accepted
  }
  // Called on main by the enrolled AsyncFunction.
  func idleSelect(_ handle: String, generation: String, id: String) -> Bool {
    guard Thread.isMainThread, let entry = sync({ entries[handle] }), entry.ready else { return false }
    return entry.idleSelected(generation,id) && entry.idleView?.selectIdle(generation: generation, id: id) == true
  }
  func close(_ handle: String) {
    guard let entry = sync({ entries.removeValue(forKey: handle) }) else { return }
    Self.registryLock.lock(); Self.registry.removeValue(forKey: handle); Self.registryLock.unlock()
    entry.stop()
  }
  func destroy() {
    let handles: [String] = sync { destroyed = true; return Array(entries.keys) }
    handles.forEach { close($0) }
  }
  deinit { destroy() }
}
