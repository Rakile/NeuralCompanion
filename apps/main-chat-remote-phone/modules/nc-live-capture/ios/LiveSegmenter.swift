import Foundation

enum SegmentEvent {
    case onset(id: UInt64)
    case completed(id: UInt64, samples: [Int16])
}

/// Confined to the capture worker, including snapshot reads and reset(). Input
/// is continuous mono 16 kHz PCM16. The engine feeds bounded conversion batches
/// (at most 1,600 samples), and handles/releases returned events before the next
/// batch. Arbitrary chunk boundaries are supported; never pass whole recordings
/// in production or retain an unbounded collection of returned completed PCM.
final class LiveSegmenter {
    private static let windowSize = 1600
    private static let historySize = 16000
    private static let leadInSize = 5600
    private static let segmentLimit = 960000

    private var window = [Int16](repeating: 0, count: LiveSegmenter.windowSize)
    private var windowCount = 0
    private var windowPlayback = false
    private var inputPlayback: Bool?
    private var previousWindowPlayback: Bool?
    private var history = [Int16](repeating: 0, count: LiveSegmenter.historySize)
    private var historyCount = 0
    private var historyNext = 0
    private var position = 0
    private var noiseFloorDb = -60.0
    private var candidateStart: Int?
    private var candidateWindows = 0
    private var speaking = false
    private var quietSamples = 0
    private var currentSamples: [Int16] = []
    private var currentID: UInt64?
    private var nextID: UInt64 = 1

    private(set) var meteringDb: Double?
    var phase: String { speaking ? "speech" : "listening" }
    /// Current physical segment duration, including retained lead-in and tail.
    var durationMs: Double { Double(currentSamples.count) / 16.0 }

    func consume(_ samples: [Int16], playbackActive: Bool) -> [SegmentEvent] {
        guard !samples.isEmpty else { return [] }
        // A playback transition breaks an unconfirmed candidate even if it
        // occurs inside an analysis window. Mixed windows use playback policy.
        if let previous = inputPlayback, previous != playbackActive, !speaking {
            clearCandidate()
        }
        inputPlayback = playbackActive
        var events: [SegmentEvent] = []
        for sample in samples {
            windowPlayback = windowCount == 0 ? playbackActive : windowPlayback || playbackActive
            window[windowCount] = sample
            windowCount += 1
            if windowCount == Self.windowSize {
                analyzeWindow(events: &events)
                windowCount = 0
            }
        }
        return events
    }

    /// Overflow, route change, or another discontinuity discards all partial
    /// speech without completion. IDs remain unique if reset within a session.
    func reset() {
        windowCount = 0
        windowPlayback = false
        inputPlayback = nil
        previousWindowPlayback = nil
        historyCount = 0
        historyNext = 0
        position = 0
        noiseFloorDb = -60
        clearCandidate()
        speaking = false
        quietSamples = 0
        currentSamples = []
        currentID = nil
        meteringDb = nil
    }

    private func analyzeWindow(events: inout [SegmentEvent]) {
        var energy = 0.0
        let start = position
        for sample in window {
            let normalized = Double(sample) / 32768.0
            energy += normalized * normalized
            history[historyNext] = sample
            historyNext = (historyNext + 1) % Self.historySize
        }
        position += Self.windowSize
        historyCount = min(Self.historySize, historyCount + Self.windowSize)
        let db = max(-90, 10 * log10(max(energy / Double(Self.windowSize), 1e-9)))
        meteringDb = db
        let activation = max(windowPlayback ? -35.0 : -45.0, noiseFloorDb + 12.0)

        if speaking {
            append(window[...], events: &events)
            quietSamples = db >= activation - 4 ? 0 : quietSamples + Self.windowSize
            if quietSamples >= 16000 {
                complete(events: &events)
                speaking = false
                quietSamples = 0
                clearCandidate()
            }
        } else {
            if previousWindowPlayback != windowPlayback { clearCandidate() }
            if db >= activation {
                if candidateStart == nil { candidateStart = start }
                candidateWindows += 1
                let required = windowPlayback ? 5 : 3
                if candidateWindows >= required, let candidate = candidateStart {
                    speaking = true
                    quietSamples = 0
                    currentID = allocateID()
                    events.append(.onset(id: currentID!))
                    // Candidate start is the beginning of its first window,
                    // not the later confirmation window. History includes the
                    // confirming window; this preserves the full lead-in.
                    let retainedStart = max(position - historyCount, candidate - Self.leadInSize)
                    currentSamples.reserveCapacity(Self.segmentLimit)
                    for offset in retainedStart..<position {
                        let back = position - offset
                        let index = (historyNext - back + Self.historySize) % Self.historySize
                        currentSamples.append(history[index])
                    }
                }
            } else {
                if !windowPlayback {
                    noiseFloorDb = max(-90, min(-30, noiseFloorDb + (db - noiseFloorDb) * 0.05))
                }
                clearCandidate()
            }
        }
        previousWindowPlayback = windowPlayback
    }

    private func clearCandidate() {
        candidateStart = nil
        candidateWindows = 0
    }

    private func allocateID() -> UInt64 {
        let id = nextID
        nextID += 1
        return id
    }

    private func append(_ samples: ArraySlice<Int16>, events: inout [SegmentEvent]) {
        var offset = samples.startIndex
        while offset < samples.endIndex {
            if currentID == nil {
                currentID = allocateID()
                currentSamples.reserveCapacity(Self.segmentLimit)
            }
            let end = min(samples.endIndex, offset + Self.segmentLimit - currentSamples.count)
            currentSamples.append(contentsOf: samples[offset..<end])
            offset = end
            if currentSamples.count == Self.segmentLimit {
                // Continue the same logical speech at the very next sample;
                // no repeated onset, no lead-in copy, and no dropped tail.
                complete(events: &events)
            }
        }
    }

    private func complete(events: inout [SegmentEvent]) {
        if let id = currentID, !currentSamples.isEmpty {
            events.append(.completed(id: id, samples: currentSamples))
        }
        currentSamples = []
        currentID = nil
    }
}
