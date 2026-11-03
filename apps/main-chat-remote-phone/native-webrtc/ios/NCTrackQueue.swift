// NeuralCompanion, MIT. Shared PCM output, existing owner, active+next bound.
import Foundation

final class NCTrackQueue {
  private final class Entry {
    let output: NCPcmOutput
    let playback: NCTrackPlayback
    let requestId: String
    let chunkId: String
    let first: UInt32
    let count: UInt32
    var ready = false
    init(output: NCPcmOutput, playback: NCTrackPlayback, requestId: String, chunkId: String, first: UInt32, count: UInt32) {
      self.output = output; self.playback = playback; self.requestId = requestId
      self.chunkId = chunkId; self.first = first; self.count = count
    }
  }
  private let generation: UInt64
  private let owner: NCPlaybackGuard
  private let stream: NCPcmStream
  private let lock = NSLock()
  private var entries = [UInt64: Entry]()
  private var lastKey: UInt64 = 0
  private var terminal = false
  private var volume: Float = 1
  private let progress: (UInt64, UInt32, Bool) -> Void

  init(generation: UInt64, device: NCPcmDevice, owner: NCPlaybackGuard = .shared,
       progress: @escaping (UInt64, UInt32, Bool) -> Void = { _, _, _ in }) {
    precondition(generation > 0)
    self.generation = generation; self.owner = owner
    self.progress = progress
    stream = NCPcmStream(device: device)
  }
  private func synchronized<T>(_ work: () -> T) -> T {
    lock.lock(); defer { lock.unlock() }; return work()
  }

  // Hardware preparation is a module-worker operation, not a main/SDK callback.
  func prepare(key: UInt64, ticket: String, requestId: String, chunkId: String,
               first: UInt32, count: UInt32, offsetSeconds: Double, rejected: (String) -> Void = { _ in }) -> Bool {
    guard key > 0, count > 0, count <= 28_800_000,
          offsetSeconds.isFinite, offsetSeconds >= 0, offsetSeconds + Double(count) / 48000 <= 600,
          [ticket, requestId, chunkId].allSatisfy({ !$0.isEmpty && $0.count <= 128 }) else { rejected("invalid_descriptor"); return false }
    guard owner.ticketIsOpen(ticket) else { rejected("owner_not_open"); return false }
    let candidate: Entry? = synchronized {
      guard !terminal else { rejected("queue_terminal"); return nil }
      guard key > lastKey else { rejected("stale_key"); return nil }
      guard entries.count < 2 else { rejected("queue_capacity"); return nil }
      guard !entries.values.contains(where: { $0.requestId == requestId && $0.chunkId == chunkId }) else { rejected("duplicate_chunk"); return nil }
      guard !entries.values.contains(where: { (first &- $0.first) < $0.count || ($0.first &- first) < count }) else { rejected("overlapping_range"); return nil }
      guard let device = stream.nextDevice() else { rejected("stream_lease_unavailable"); return nil }
      let output = NCPcmOutput(device: device, generation: generation, firstSample: first, sampleCount: count)
      output.volume = volume
      let player = NCTrackPlayback(output: output, owner: owner, offsetSeconds: offsetSeconds) { [weak self] samples, stopped in
        self?.progress(key, samples, stopped)
      }
      let entry = Entry(output: output, playback: player,
                        requestId: requestId, chunkId: chunkId, first: first, count: count)
      entries[key] = entry; lastKey = key
      return entry
    }
    guard let entry = candidate else { return false }
    var prepared = false
    if entry.playback.bind(ticket: ticket, requestId: requestId, chunkId: chunkId, rejected: rejected) {
      do { try entry.output.prepare(); prepared = true } catch { rejected("device_prepare_failed") }
    }
    let accepted = synchronized {
      if prepared && !terminal && entries[key] === entry {
        entry.ready = true; return true
      }
      if entries[key] === entry { entries.removeValue(forKey: key) }
      return false
    }
    if !accepted { if prepared { rejected("prepare_superseded") }; entry.playback.stop() }
    return accepted
  }

  func play(key: UInt64) -> Bool { play(key: key, activate: {}) }
  func play(key: UInt64, activate: () throws -> Void) rethrows -> Bool {
    let entry: Entry? = synchronized { terminal ? nil : entries[key].flatMap { $0.ready ? $0 : nil } }
    return try entry?.playback.play(activate: activate) == true
  }
  func receive(_ pcm: UnsafePointer<Int16>, frames: UInt32, channels: UInt32, sampleRate: UInt32,
               timestamp: UInt32, clockRate: UInt32, valid: Bool, concealed: Bool) {
    let current: [Entry] = synchronized { terminal ? [] : entries.values.filter { $0.ready } }
    for entry in current {
      entry.output.receivePCM(pcm, frames: frames, channels: channels, sampleRate: sampleRate,
                              timestamp: timestamp, clockRate: clockRate, valid: valid, concealed: concealed)
    }
  }
  func snapshot(key: UInt64) -> NCTrackPlayback.Snapshot? {
    synchronized { entries[key] }?.playback.snapshot()
  }
  func samples(key: UInt64) -> [NSNumber]? { synchronized { entries[key] }?.output.latestSample }
  func setVolume(_ value: Float) {
    guard value.isFinite else { return }
    let bounded = max(0, min(1, value))
    let current: [Entry] = synchronized {
      volume = bounded; return terminal ? [] : Array(entries.values)
    }
    current.forEach { $0.output.volume = bounded }
  }
  func retire(key: UInt64) {
    let entry = synchronized { entries.removeValue(forKey: key) }
    entry?.playback.stop()
  }
  func stop() {
    let current: [Entry] = synchronized {
      if terminal { return [] }
      terminal = true; return Array(entries.values)
    }
    current.forEach { $0.playback.stop() }
  }
  func close() {
    stop()
    synchronized { entries.removeAll() }
    stream.stop()
  }
  deinit { close() }
}
