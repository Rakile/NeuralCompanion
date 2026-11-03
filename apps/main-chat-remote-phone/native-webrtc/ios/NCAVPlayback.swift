// NeuralCompanion, MIT. Native audio is the speech video clock, not JavaScript.
import Foundation
import WebRTC

private final class NCAVRenderer: NSObject, RTCVideoRenderer {
  let frame: (RTCVideoFrame) -> Void
  init(_ frame: @escaping (RTCVideoFrame) -> Void) { self.frame = frame }
  func setSize(_ size: CGSize) {}
  func renderFrame(_ frame: RTCVideoFrame?) { if let frame { self.frame(frame) } }
}

final class NCAVPlayback {
  private let generation: UInt64
  private let lock = NSRecursiveLock()
  private var audio: NCTrackQueue!
  private var videos = [UInt64: NCRtpVideoSink]()
  private var ranges = [(UInt64, UInt32, UInt64)]()
  private var counts = [UInt64: UInt32]()
  private var audible = Set<UInt64>()
  private var pendingSpeech = Set<UInt64>()
  private var terminal = false
  private var presenting = false
  private var localShown = false
  private var visualDeadline: TimeInterval = 0
  private var ticket: String?
  private var idle: NCRtpVideoSink?
  private var idleToken: String?
  private var renderer: RTCVideoRenderer?
  private var clear: (() -> Void)?
  private var visibleToken: String?
  private var visibleKey: UInt64 = 0
  private var lastFrame: TimeInterval = 0
  private var completedHandoff = false
  private var progressObserver:((UInt64,UInt32,Bool,Bool)->Void)?

  init(generation: UInt64, device: NCPcmDevice, owner: NCPlaybackGuard = .shared) {
    self.generation = generation
    audio = NCTrackQueue(generation: generation, device: device, owner: owner) { [weak self] key, count, stopped in
      guard let self else { return }
      let video: NCRtpVideoSink? = self.sync {
        if stopped || count >= (self.counts[key] ?? 0) { self.audible.remove(key); self.pendingSpeech.remove(key) }
        else if count > 0 { self.audible.insert(key) }
        return self.videos[key]
      }
      if stopped { video?.stop() } else { video?.played(count, generation: generation) }
      let observation:( ((UInt64,UInt32,Bool,Bool)->Void)?,Bool )=self.sync {
        (self.progressObserver,!stopped && count >= (self.counts[key] ?? UInt32.max))
      }
      observation.0?(key,count,stopped,observation.1)
    }
  }
  private func sync<T>(_ body: () -> T) -> T { lock.lock(); defer { lock.unlock() }; return body() }

  func setRenderer(_ value: RTCVideoRenderer?, clearImage: (() -> Void)?) {
    let previous: (() -> Void)? = sync {
      let old = clear
      renderer = terminal ? nil : value; clear = terminal ? nil : clearImage
      localShown = false; visibleToken = nil; visibleKey = 0; lastFrame = 0
      completedHandoff = false
      return old
    }
    previous?()
  }
  var visible: Bool { sync { !terminal && presenting && renderer != nil && visibleToken != nil &&
    (completedHandoff || ProcessInfo.processInfo.systemUptime - lastFrame < 0.75) } }
  var localVisualAllowed: Bool { sync { !terminal && presenting && renderer != nil &&
    ProcessInfo.processInfo.systemUptime < visualDeadline } }
  var speaking: Bool { sync { !terminal && !audible.isEmpty } }
  // Native completion, not silence or network delivery, ends a visual reply.
  var idleReturnAllowed: Bool { sync { !terminal && pendingSpeech.isEmpty && audible.isEmpty } }
  func hasSuccessor(_ key:UInt64)->Bool { sync { pendingSpeech.contains { $0 != key } } }
  func setProgressObserver(_ value:((UInt64,UInt32,Bool,Bool)->Void)?) { sync { progressObserver=value } }
  func frameIdentity(_ timestamp:UInt32)->(UInt64,Int)? {
    sync {
      guard !terminal else { return nil }
      for (key,first,count) in ranges.reversed() {
        let delta=UInt64(timestamp &- first)
        if delta<count { return (key,Int(delta/3750)) }
      }
      return nil
    }
  }
  func setLocalVisible(_ value: Bool) { sync { localShown = value } }
  var localVisible: Bool { sync { localShown && localVisualAllowed } }

  private func sink(first: UInt32, count: UInt32, key: UInt64, token: String, isIdle: Bool) -> NCRtpVideoSink {
    let target = NCAVRenderer { [weak self] frame in
      guard let self else { return }
      self.sync {
        let holdSpeech = !self.pendingSpeech.isEmpty && (self.visibleKey > 0 || self.completedHandoff)
        guard !self.terminal, self.presenting, let renderer = self.renderer,
              isIdle ? (self.idleToken == token && self.audible.isEmpty && !holdSpeech) : (key >= self.visibleKey) else { return }
        renderer.setSize(CGSize(width: CGFloat(frame.width), height: CGFloat(frame.height)))
        renderer.renderFrame(frame)
        self.visibleToken = token; self.visibleKey = key; self.lastFrame = ProcessInfo.processInfo.systemUptime
        self.completedHandoff = false
      }
    }
    return NCRtpVideoSink(renderer: target, generation: generation, firstTimestamp: first,
                          audioSamples: count, idle: isIdle) { [weak self] _, visible in
      guard !visible, let self else { return }
      self.sync {
        if self.visibleToken == token {
          self.visibleToken = nil; self.visibleKey = 0; self.lastFrame = 0; self.clear?()
        }
      }
    }
  }
  func visual(first: UInt32, count: UInt32, enabled: Bool) -> Bool {
    var previous: NCRtpVideoSink?
    let accepted: Bool = sync {
      guard !terminal, !enabled || (count > 0 && count <= 28_800_000) else { return false }
      previous = idle; idle = nil; idleToken = nil; presenting = enabled
      visualDeadline = enabled ? ProcessInfo.processInfo.systemUptime + Double(count) / 48000 : 0
      if !enabled { localShown = false; visibleToken = nil; visibleKey = 0; lastFrame = 0; completedHandoff = false; clear?() }
      else {
        let token = UUID().uuidString
        let next = sink(first: first, count: count, key: 0, token: token, isIdle: true)
        guard next.admit(generation) else { return false }
        idleToken = token; idle = next
        // Previous idle's queued hide must not erase the renewed surface.
        if visibleKey == 0 { visibleToken = token }
      }
      return true
    }
    previous?.stop()
    return accepted
  }
  func prepare(key: UInt64, ticket: String, requestId: String, chunkId: String,
               firstAudio: UInt32, firstVideo: UInt32, count: UInt32, offsetSeconds: Double, rejected: (String) -> Void = { _ in }) -> Bool {
    let candidate: NCRtpVideoSink? = sync {
      guard !terminal else { rejected("output_terminal"); return nil }
      guard videos.count < 2 else { rejected("video_queue_capacity"); return nil }
      guard videos[key] == nil else { rejected("duplicate_key"); return nil }
      guard self.ticket == nil || self.ticket == ticket else { rejected("owner_mismatch"); return nil }
      let value = sink(first: firstVideo, count: count, key: key, token: UUID().uuidString, isIdle: false)
      videos[key] = value; return value
    }
    guard let candidate else { return false }
    let ready = audio.prepare(key: key, ticket: ticket, requestId: requestId, chunkId: chunkId,
                              first: firstAudio, count: count, offsetSeconds: offsetSeconds, rejected: rejected)
    let accepted: Bool = sync {
      if ready && !terminal && videos[key] === candidate {
        self.ticket = ticket; counts[key] = count; pendingSpeech.insert(key)
        ranges.append((key, firstVideo, UInt64(count) * 90000 / 48000))
        if ranges.count > 64 { ranges.removeFirst() }
        return true
      }
      videos.removeValue(forKey: key); return false
    }
    if !accepted { if ready { rejected("prepare_superseded") }; candidate.stop(); audio.retire(key: key) }
    return accepted
  }
  func play(key: UInt64, activate: () throws -> Void) rethrows -> Bool {
    guard let video = sync({ terminal ? nil : videos[key] }) else { return false }
    _ = video.admit(generation)
    do {
      let result = try audio.play(key: key, activate: activate)
      if !result { _ = sync { pendingSpeech.remove(key) }; video.stop() }
      return result
    } catch {
      _ = sync { pendingSpeech.remove(key) }; video.stop(); throw error
    }
  }
  func receive(_ data: Data, timestamp: UInt32, valid: Bool, concealed: Bool) {
    data.withUnsafeBytes { bytes in
      if let pcm = bytes.bindMemory(to: Int16.self).baseAddress {
        audio.receive(pcm, frames: UInt32(data.count / 2), channels: 1, sampleRate: 48000,
                      timestamp: timestamp, clockRate: 48000, valid: valid, concealed: concealed)
      }
    }
  }
  func frame(_ frame: RTCVideoFrame) {
    let current: [NCRtpVideoSink] = sync {
      if terminal { return [] }
      let speech = ranges.contains { _, first, count in UInt64(ncRtpTimestamp(frame.timeStamp) &- first) < count }
      return Array(videos.values) + (speech ? [] : idle.map { [$0] } ?? [])
    }
    current.forEach { $0.renderFrame(frame) }
  }
  func snapshot(key: UInt64) -> NCTrackPlayback.Snapshot? { audio.snapshot(key: key) }
  func samples(key: UInt64) -> [NSNumber]? { audio.samples(key: key) }
  func setVolume(_ volume: Float) { audio.setVolume(volume) }
  func retire(key: UInt64) {
    let state = audio.snapshot(key: key)
    let video: NCRtpVideoSink? = sync {
      // A confirmed completed image can bridge to authorized idle, never a
      // failed/stopped output. Moving its token fences the queued old-sink hide.
      if !terminal, presenting, let idleToken, visibleKey == key,
         let state, state.completed, !state.failed, !state.stopped {
        visibleToken = idleToken; visibleKey = 0; completedHandoff = true
      }
      audible.remove(key); pendingSpeech.remove(key); counts.removeValue(forKey: key)
      let removed = videos.removeValue(forKey: key)
      // Release only the drained reply identity, not the authenticated peer or
      // visual lease. The next prepare still binds through NCPlaybackGuard.
      if videos.isEmpty, let state, state.completed, !state.failed, !state.stopped { ticket = nil }
      return removed
    }
    video?.stop(); audio.retire(key: key)
  }
  func stop() {
    let current: [NCRtpVideoSink] = sync {
      if terminal { return [] }
      terminal = true; pendingSpeech.removeAll(); return Array(videos.values) + (idle.map { [$0] } ?? [])
    }
    audio.stop(); current.forEach { $0.stop() }; setRenderer(nil, clearImage: nil)
  }
  func close() { stop(); sync { videos.removeAll(); idle = nil }; audio.close() }
  deinit { close() }
}
