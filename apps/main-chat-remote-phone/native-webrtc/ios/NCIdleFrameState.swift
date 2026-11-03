import Foundation

/// Serialized by the visual source. Never authorizes audio or playback receipts.
final class NCIdleFrameState {
  final class Request { let sourceFrame: Int; fileprivate init(_ frame: Int) { sourceFrame = frame } }
  struct Presented {
    let generation: String, motionId: String, sourceFrame: Int
    let pts: Int64, timescale: Int32, observedAtNanos: Int64
    var playing: Bool
  }
  let generation: String, motionId: String, sourceFrameCount: Int
  private var pending: Request?
  private var decodedPTS: (Int64,Int32)?
  private var observation: Presented?
  private var closed = false
  init?(generation: String, motionId: String, sourceFrameCount: Int) {
    guard !generation.isEmpty, generation.count <= 128, (1...1440).contains(sourceFrameCount),
          motionId.count == 64, motionId.allSatisfy({ "abcdef0123456789".contains($0) }) else { return nil }
    self.generation = generation; self.motionId = motionId; self.sourceFrameCount = sourceFrameCount
  }
  func request(_ sourceFrame: Int) -> Request? {
    guard !closed, (0..<sourceFrameCount).contains(sourceFrame) else { return nil }
    let request = Request(sourceFrame); pending = request; decodedPTS = nil; return request
  }
  func current(_ request: Request) -> Bool { !closed && pending === request }
  func decoded(_ request: Request, pts: Int64, timescale: Int32) -> Bool {
    guard current(request), pts >= 0, pts <= Int64.max/24, timescale > 0,
          sourceTick(pts, timescale) < sourceFrameCount else { return false }
    decodedPTS = (pts,timescale); return true
  }
  func present(_ request: Request, now: Int64, visible: Bool, playing: Bool = false) -> Presented? {
    guard let value = decodedPTS, current(request), visible, now >= 0 else { return nil }
    let result = Presented(generation: generation, motionId: motionId,
      sourceFrame: Int(sourceTick(value.0,value.1)), pts: value.0, timescale: value.1,
      observedAtNanos: now, playing: playing)
    pending = nil; decodedPTS = nil; observation = result; return result
  }
  func observe() -> Presented? { closed ? nil : observation }
  private func sourceTick(_ pts: Int64, _ scale: Int32) -> Int64 {
    let ticks = pts*24, divisor = Int64(scale)
    return ticks/divisor + ((ticks%divisor)*2 >= divisor ? 1 : 0)
  }
  func pause() { pending = nil; decodedPTS = nil; observation?.playing = false }
  func close() { pause(); closed = true; observation = nil }
}
