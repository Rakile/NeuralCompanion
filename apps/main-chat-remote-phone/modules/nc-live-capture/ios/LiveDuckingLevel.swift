import AVFAudio

enum LiveDuckingLevel: String {
    case systemDefault = "default"
    case min, mid, max

    static var supported: Bool {
        if #available(iOS 17.0, macOS 14.0, *) { return true }
        return false
    }

    static func resolve(_ value: String, supported: Bool) throws -> LiveDuckingLevel {
        guard let level = LiveDuckingLevel(rawValue: value), supported || level == .systemDefault else {
            throw CaptureFailure.startFailed
        }
        return level
    }

    @available(iOS 17.0, macOS 14.0, *)
    var configuration: AVAudioVoiceProcessingOtherAudioDuckingConfiguration {
        let level: AVAudioVoiceProcessingOtherAudioDuckingConfiguration.Level
        switch self {
        case .systemDefault: level = .default
        case .min: level = .min
        case .mid: level = .mid
        case .max: level = .max
        }
        return AVAudioVoiceProcessingOtherAudioDuckingConfiguration(
            enableAdvancedDucking: false, duckingLevel: level)
    }
}
