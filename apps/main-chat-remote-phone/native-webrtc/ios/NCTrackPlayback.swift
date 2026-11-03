// NeuralCompanion, MIT. Compiled beside the EXISTING Expo NCPlaybackGuard.
// Candidate only: not yet enrolled in the phone module or exposed to JavaScript.
import Foundation

final class NCTrackPlayback: NCPlaybackActions {
  struct Snapshot {
    let started: Bool
    let completed: Bool
    let positionSeconds: Double
    let failed: Bool
    let stopped: Bool
    let failureReason: String
    let failureAtMs: Double
  }
  private let output: NCPcmOutput
  private let offsetSeconds: Double
  private let identity = NSObject()
  private let stateLock = NSLock()
  private var binding: NCPlaybackBinding!
  private var bound = false
  private var started = false
  private var completed = false
  private var stopped = false
  private let progress: (UInt32, Bool) -> Void

  init(output: NCPcmOutput, owner: NCPlaybackGuard = .shared, offsetSeconds: Double = 0,
       progress: @escaping (UInt32, Bool) -> Void = { _, _ in }) {
    precondition(offsetSeconds.isFinite && offsetSeconds >= 0 && offsetSeconds <= 600)
    self.output = output
    self.offsetSeconds = offsetSeconds
    self.progress = progress
    binding = NCPlaybackBinding(owner: owner, actions: self)
    output.changed = { [weak self] in self?.refreshReceipts() }
  }
  func bind(ticket: String, requestId: String, chunkId: String, rejected: (String) -> Void = { _ in }) -> Bool {
    let accepted = binding.bindPhoneReplyChunk(ticket: ticket, requestId: requestId, chunkId: chunkId, rejected: rejected)
    stateLock.lock(); bound = accepted; stateLock.unlock()
    return accepted
  }
  func play() -> Bool { play(activate: {}) }
  func play(activate: () throws -> Void) rethrows -> Bool {
    stateLock.lock(); let admitted = bound; stateLock.unlock()
    // NCPlaybackBinding also supports legacy unmanaged Expo players. A remote
    // track must never opt into that branch merely by arriving before metadata.
    guard admitted else { return false }
    return try binding.play(rate: 1, activate: activate) && output.isPlaying
  }
  func stop() {
    binding.remove()
    ncPause()
  }
  func snapshot() -> Snapshot {
    stateLock.lock(); let didStart = started, didComplete = completed, didStop = stopped; stateLock.unlock()
    return Snapshot(started: didStart, completed: didComplete,
                    positionSeconds: offsetSeconds + Double(output.confirmedSamples) / 48000,
                    failed: output.failed, stopped: didStop,
                    failureReason: output.failureReason, failureAtMs: output.failureAtMs)
  }
  private func refreshReceipts() {
    // Native completion delivery occurs outside the output lock. Never hold our
    // status lock while calling the guard: its actions may reenter this object.
    if output.failed { stop(); return }
    guard output.confirmedSamples > 0 else { return }
    if binding.acknowledgePhoneReplyStart(expectedItemIdentity: ncCurrentItemIdentity) {
      stateLock.lock(); started = true; stateLock.unlock()
    }
    if output.drained && binding.acknowledgePhoneReplyCompletion(expectedItemIdentity: ncCurrentItemIdentity) {
      stateLock.lock(); completed = true; stateLock.unlock()
    }
    stateLock.lock(); let terminal = stopped; stateLock.unlock()
    progress(output.confirmedSamples, terminal)
  }
  var ncIsPlaying: Bool { output.isPlaying && output.confirmedSamples > 0 }
  var ncCurrentItemIdentity: ObjectIdentifier? { ObjectIdentifier(identity) }
  var ncPositionSeconds: Double? { offsetSeconds + Double(output.confirmedSamples) / 48000 }
  func ncPlay(rate: Float?) {
    guard rate == nil || rate == 1 else { output.fail(); return }
    _ = output.start()
  }
  func ncPause() {
    stateLock.lock(); stopped = true; stateLock.unlock()
    output.stop()
    progress(output.confirmedSamples, true)
  }
  func ncSetRate(_ rate: Float) { if rate != 1 { output.fail() } }
  deinit {
    output.changed = nil
    binding.remove()
    output.stop()
  }
}
