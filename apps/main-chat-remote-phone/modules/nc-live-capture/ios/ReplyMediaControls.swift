import Foundation
#if canImport(ExpoAudio)
import ExpoAudio
#elseif canImport(NCPlaybackGuardCore)
import NCPlaybackGuardCore
#endif

// Only the platform sink is substituted in Foundation tests; ownership and
// queued lifecycle checks below are the same code used by the Expo module.
protocol ReplyMediaSink: AnyObject {
    func install(scope: String, command: @escaping (String) -> Bool) -> () -> Void
    func publish(scope: String, playing: Bool, nextToggles: Bool)
    func clear(scope: String)
}

// Main-queue owner of reply-level commands; never starts a microphone or player.
final class ReplyMediaControls {
    private let owner: NCPlaybackGuard
    private let mediaOwner = UUID()
    private let enqueue: (@escaping () -> Void) -> Void
    private let sink: ReplyMediaSink
    private let lock = NSLock()
    private var requested: UUID?
    private var requestedScope: String?
    private var destroyed = false
    // Accessed only by the supplied main executor, under the lifecycle lock.
    private var scope: String?
    private var removeTargets: (() -> Void)?
    var emit: ((String, String) -> Void)?

    init(owner: NCPlaybackGuard, enqueue: @escaping (@escaping () -> Void) -> Void, sink: ReplyMediaSink) {
        self.owner = owner; self.enqueue = enqueue; self.sink = sink
    }

    func configure(scope value: String?, playing: Bool, nextToggles: Bool) {
        lock.lock()
        guard !destroyed else { lock.unlock(); return }
        let generation = UUID()
        requested = generation; requestedScope = value
        lock.unlock()
        enqueue { [self] in
            // Keep request invalidation and the native publication atomic. The
            // sink never waits, emits JS or calls output/capture operations.
            lock.lock(); defer { lock.unlock() }
            guard !destroyed, requested == generation else { return }
            guard let value else { clear(); return }
            let accepted = owner.publishReplyMedia(owner: mediaOwner) {
                if scope != value { removeTargets?(); removeTargets = nil }
                scope = value
                if removeTargets == nil {
                    removeTargets = sink.install(scope: value) { [weak self] command in
                        guard let self, self.commandIsCurrent(scope: value) else { return false }
                        self.emit?(value, command)
                        return true
                    }
                }
                sink.publish(scope: value, playing: playing, nextToggles: nextToggles)
            }
            // Always remove our tokens, even if Live/Expo now owns global state.
            if !accepted { clear() }
        }
    }
    private func commandIsCurrent(scope value: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return !destroyed && requestedScope == value && scope == value && owner.replyMediaIsCurrent(owner: mediaOwner)
    }
    private func clear() {
        removeTargets?(); removeTargets = nil
        if let scope { owner.clearReplyMedia(owner: mediaOwner) { sink.clear(scope: scope) } }
        scope = nil
    }
    func destroy() {
        lock.lock(); destroyed = true; requested = nil; requestedScope = nil; lock.unlock()
        enqueue { [self] in
            lock.lock(); defer { lock.unlock() }
            clear()
        }
    }
}

#if canImport(MediaPlayer)
import MediaPlayer

extension ReplyMediaControls {
    convenience init() {
        self.init(owner: .shared, enqueue: { DispatchQueue.main.async(execute: $0) }, sink: SystemReplyMediaSink())
    }
}

private final class SystemReplyMediaSink: ReplyMediaSink {
    func install(scope: String, command handler: @escaping (String) -> Bool) -> () -> Void {
        let center = MPRemoteCommandCenter.shared()
        var targets: [(MPRemoteCommand, Any)] = []
        for (command, name) in [(center.playCommand, "play"), (center.pauseCommand, "pause"),
            (center.togglePlayPauseCommand, "toggle"), (center.stopCommand, "stop"), (center.nextTrackCommand, "next")] {
            let token = command.addTarget { _ in
                guard command.isEnabled, handler(name) else { return .commandFailed }
                return .success
            }
            targets.append((command, token))
        }
        return { for (command, token) in targets { command.removeTarget(token) } }
    }
    func publish(scope: String, playing: Bool, nextToggles: Bool) {
        let center = MPRemoteCommandCenter.shared()
        center.playCommand.isEnabled = true
        center.pauseCommand.isEnabled = true
        center.togglePlayPauseCommand.isEnabled = true
        center.stopCommand.isEnabled = true
        center.nextTrackCommand.isEnabled = nextToggles
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: "NeuralCompanion response",
            MPNowPlayingInfoPropertyExternalContentIdentifier: scope,
            MPNowPlayingInfoPropertyPlaybackRate: playing ? 1.0 : 0.0,
        ]
        MPNowPlayingInfoCenter.default().playbackState = playing ? .playing : .paused
    }
    func clear(scope: String) {
        let center = MPNowPlayingInfoCenter.default()
        if center.nowPlayingInfo?[MPNowPlayingInfoPropertyExternalContentIdentifier] as? String == scope {
            center.nowPlayingInfo = nil
            center.playbackState = .stopped
        }
    }
}
#endif
