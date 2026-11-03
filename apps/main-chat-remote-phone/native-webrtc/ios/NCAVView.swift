import ExpoModulesCore
import WebRTC
import AVFoundation

final class NCAVView: ExpoView {
  private let video = RTCMTLVideoView(frame: .zero)
  private weak var entry: NCAVBridge.Entry?
  private var transitionDisplayed=false
  private lazy var transition = NCVisualTransition(host:self) { [weak self] _,kind,_,_ in
    if kind != "idle" && kind != "returned" { self?.transitionDisplayed=true }
  }
  private var idleVideo:NCIdleVideo { transition.idle }
  private lazy var opening = NCSpeechOpening(host:self)
  private var timer: Timer?
  private var speechDisplayed = false
  var idleVisible: Bool { idleVideo.visible && entry?.localVisualAllowed == true }
  var handle = "" { didSet { if handle != oldValue { bind() } } }
  required init(appContext: AppContext? = nil) {
    super.init(appContext: appContext)
    clipsToBounds = true; video.videoContentMode = .scaleAspectFit; video.isHidden = true
    addSubview(video)
  }
  override func layoutSubviews() { super.layoutSubviews(); video.frame = bounds; transition.layout();opening.layout() }
  override func didMoveToWindow() {
    super.didMoveToWindow(); bind(); timer?.invalidate(); timer = nil
    if window != nil { timer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in self?.refreshIdle() } }
  }
  private func refreshIdle() {
    let allowed = entry?.localVisualAllowed == true
    if entry?.buffered==true { entry?.bufferedClock.states.forEach { bufferedHeard($0,refresh:false) } }
    transition.display(allowed,ordinarySpeech:speechDisplayed)
    entry?.setHandoffStatus(transition.status)
    entry?.setIdlePosition(idleVideo.position)
    entry?.setLocalVisible(allowed && (idleVideo.visible || speechDisplayed || transitionDisplayed))
    video.isHidden = !allowed || !speechDisplayed
  }
  func prepareIdle(generation: String, id: String, file: URL, fade: Int, sourceCount: Int, done: @escaping (Bool) -> Void) {
    guard entry?.localVisualAllowed == true else { done(false); return }
    idleVideo.prepareAt(generation:generation,id:id,file:file,fade:fade,sourceCount:sourceCount,startFrame:0,done:done)
  }
  func selectIdle(generation: String, id: String) -> Bool {
    guard entry?.localVisualAllowed == true else { return false }
    let result = idleVideo.select(generation: generation, id: id); refreshIdle(); return result
  }
  func bufferedHeard(_ value:NCBufferedAudioClock.State,refresh:Bool=true) {
    guard entry?.buffered==true else { return }
    if value.stopped && value.key==transition.activeKey { transition.clearDetached { _ in } }
    else if value.started { transition.heard(value.key,samples:value.samples,completed:value.completed,successor:value.successor) }
    if let entry,entry.localVisualAllowed,value.started,value.playing,!value.completed,!value.stopped {
      for (key,source) in Array(entry.bufferedVideo.values) where key==value.key { source.presentOpening(samples:value.samples) }
    }
    if (value.completed || value.stopped) && !value.successor { speechDisplayed=false }
    if refresh { refreshIdle() }
  }
  func clearIdle() { transition.clearDetached { _ in };idleVideo.clear(); entry?.setLocalVisible(false) }
  func bufferedFrame(_ key:UInt64,tick:Int,frame:RTCVideoFrame) {
    guard Thread.isMainThread,entry?.buffered==true,entry?.localVisualAllowed==true else { return }
    guard let heard=entry?.bufferedClock.sample(key),
      NCBufferedVideoSource.presentable(tick,samples:heard.samples,playing:heard.started && heard.playing && !heard.stopped) else { return }
    if transition.activeKey>0 {
      bufferedHeard(heard,refresh:false)
      _ = transition.streamFrame(key,sourceTick:tick,frame:frame)
    }
    else { video.isHidden=false;video.renderFrame(frame);speechDisplayed=true;refreshIdle() }
  }
  func clearIdleDetached(_ done: @escaping (Bool)->Void) { idleVideo.clearDetached(done); entry?.setLocalVisible(false) }
  var idlePosition: [String:Any]? { idleVideo.position }
  func prepareOpening(owner: String, key: UInt64, media: String, file: URL, indices: [Int], sourceCount: Int, done: @escaping (Bool)->Void) {
    guard entry?.localVisualAllowed == true else { done(false);return }
    if transition.activeKey==key { transition.prepareOpening(owner,key:key,media:media,file:file,indices:indices,sourceCount:sourceCount,done:done) }
    else { opening.prepare(owner:owner,key:key,media:media,file:file,indices:Array(indices.prefix(12)),sourceCount:sourceCount,done:done) }
  }
  func beginHandoff(owner:String,key:UInt64,plan:String,count:Int,indices:[Int])->Bool {
    guard entry?.localVisualAllowed == true else { return false }
    return transition.begin(owner,key:key,media:plan,indices:indices,sourceCount:count)
  }
  func appendHandoff(key:UInt64,index:Int,file:URL,done:@escaping (Bool)->Void) { transition.append(key,index:index,file:file,done:done) }
  func nextHandoff(key:UInt64,count:Int,indices:[Int])->Bool { transition.next(key,sourceCount:count,indices:indices) }
  func bufferedSource(key:UInt64,source:NCBufferedVisualSource,done:@escaping (Bool)->Void) { transition.configure(key,source:source,done:done) }
  func armHandoff(key:UInt64)->Double {
    let at=transition.arm(key,minimumMs:700,maximumMs:1800)
    return at==0 ? 0 : max(0,(at-ProcessInfo.processInfo.systemUptime)*1000)
  }
  func clearOpeningDetached(_ done: @escaping (Bool)->Void) {
    transitionDisplayed=false
    transition.clearDetached { first in self.opening.clearAll { second in done(first && second) } }
  }
  private func bind() {
    entry?.setIdlePosition(nil);entry?.setHandoffStatus(nil)
    entry?.detachView(self); entry = nil; video.isHidden = true;transition.clearDetached { _ in };idleVideo.clear();opening.clearAll { _ in }; speechDisplayed = false;transitionDisplayed=false
    guard window != nil, let selected = NCAVBridge.entry(handle) else { return }
    entry = selected
    selected.attachView(self)
  }
  deinit { timer?.invalidate();entry?.detachView(self) }
}
