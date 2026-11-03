import Foundation

/// Quiet mono PCM on the existing route. Echo is baked in, never a delayed player.
enum ConnectionCue {
    static let sampleRate = 16000
    static func duration(recovered: Bool) -> Double { recovered ? 0.86 : 0.70 }
    static func samples(recovered: Bool) -> [Int16] {
        func tone(_ t: Double, _ length: Double, _ from: Double, _ to: Double) -> Double {
            guard t >= 0, t < length else { return 0 }
            let envelope = pow(sin(Double.pi * t / length), 2)
            let phase = 2 * Double.pi * (from * t + (to - from) * t * t / (2 * length))
            return sin(phase) * envelope
        }
        func dry(_ t: Double) -> Double {
            recovered ? tone(t, 0.24, 440, 440) + tone(t - 0.28, 0.24, 554.37, 554.37)
                      : tone(t, 0.36, 420, 360)
        }
        return (0..<(recovered ? 13760 : 11200)).map { index in
            let t = Double(index) / Double(sampleRate)
            let wet = dry(t) + 0.25 * dry(t - 0.17) + 0.10 * dry(t - 0.34)
            return Int16(max(-1600, min(1600, wet * 1120)))
        }
    }
    static func wave(recovered: Bool) -> Data {
        let pcm = samples(recovered: recovered)
        var data = Data()
        func text(_ value: String) { data.append(contentsOf: value.utf8) }
        func integer<T: FixedWidthInteger>(_ value: T) {
            var little = value.littleEndian
            withUnsafeBytes(of: &little) { data.append(contentsOf: $0) }
        }
        text("RIFF"); integer(UInt32(36 + pcm.count * 2)); text("WAVEfmt ")
        integer(UInt32(16)); integer(UInt16(1)); integer(UInt16(1))
        integer(UInt32(sampleRate)); integer(UInt32(sampleRate * 2)); integer(UInt16(2)); integer(UInt16(16))
        text("data"); integer(UInt32(pcm.count * 2))
        for sample in pcm { integer(sample) }
        return data
    }
}
