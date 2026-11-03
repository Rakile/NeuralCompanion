import Foundation

enum ConversationMediaCommand: CaseIterable, Hashable {
    case pause, stop, toggle, play, next, previous, skipForward, skipBackward
    case seekForward, seekBackward, position, rate

    private var terminates: Bool { self == .pause || self == .stop || self == .toggle }
    static func configure(setEnabled: (ConversationMediaCommand, Bool) -> Void) {
        for command in allCases { setEnabled(command, command.terminates) }
    }
    static func register(add: (ConversationMediaCommand, @escaping () -> Void) -> (() -> Void),
                         stop: @escaping () -> Void) -> (() -> Void) {
        let removals = allCases.filter(\.terminates).map { add($0, stop) }
        return { for remove in removals { remove() } }
    }
}

// Epochs may change on the capture worker; all registration/cleanup is scheduled
// on main. No lock is held while calling a platform adapter or native Stop.
final class BackgroundLiveCommands {
    private let enqueue: (@escaping () -> Void) -> Void
    private let register: (@escaping () -> Void) -> (() -> Void)?
    private let lock = NSLock()
    private var epoch: UUID?
    // Accessed only by the supplied main executor.
    private var installed: (epoch: UUID, remove: () -> Void)?

    init(enqueue: @escaping (@escaping () -> Void) -> Void,
         register: @escaping (@escaping () -> Void) -> (() -> Void)?) {
        self.enqueue = enqueue
        self.register = register
    }

    func activate(stop: @escaping () -> Void) {
        lock.lock()
        guard epoch == nil else { lock.unlock(); return }
        let requested = UUID()
        epoch = requested
        lock.unlock()
        enqueue { [self] in
            guard isCurrent(requested) else { return }
            installed?.remove()
            installed = nil
            if let remove = register({ [weak self] in
                guard self?.isCurrent(requested) == true else { return }
                stop()
            }) { installed = (requested, remove) }
        }
    }

    func deactivate() {
        lock.lock()
        guard let previous = epoch else { lock.unlock(); return }
        epoch = nil
        lock.unlock()
        enqueue { [self] in
            guard installed?.epoch == previous else { return }
            installed?.remove()
            installed = nil
        }
    }

    private func isCurrent(_ requested: UUID) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return epoch == requested
    }
}

#if canImport(MediaPlayer) && canImport(UIKit) && canImport(ExpoAudio)
import MediaPlayer
import UIKit
import ExpoAudio

extension BackgroundLiveCommands {
    static func conversation(ticket: String, sessionId: String) -> BackgroundLiveCommands {
        BackgroundLiveCommands(enqueue: { DispatchQueue.main.async(execute: $0) }, register: { stop in
            dispatchPrecondition(condition: .onQueue(.main))
            let center = MPRemoteCommandCenter.shared()
            func native(_ command: ConversationMediaCommand) -> MPRemoteCommand {
                switch command {
                case .pause: return center.pauseCommand
                case .stop: return center.stopCommand
                case .toggle: return center.togglePlayPauseCommand
                case .play: return center.playCommand
                case .next: return center.nextTrackCommand
                case .previous: return center.previousTrackCommand
                case .skipForward: return center.skipForwardCommand
                case .skipBackward: return center.skipBackwardCommand
                case .seekForward: return center.seekForwardCommand
                case .seekBackward: return center.seekBackwardCommand
                case .position: return center.changePlaybackPositionCommand
                case .rate: return center.changePlaybackRateCommand
                }
            }
            var enabled: [(MPRemoteCommand, Bool)] = []
            let published = NCPlaybackGuard.shared.publishConversationMedia(ticket: ticket, sessionId: sessionId) {
                ConversationMediaCommand.configure { kind, newValue in
                    let command = native(kind)
                    enabled.append((command, command.isEnabled))
                    command.isEnabled = newValue
                }
                MPNowPlayingInfoCenter.default().nowPlayingInfo = [
                    MPMediaItemPropertyTitle: "NC Live conversation",
                    MPNowPlayingInfoPropertyIsLiveStream: true,
                    MPNowPlayingInfoPropertyPlaybackRate: 1.0,
                ]
                MPNowPlayingInfoCenter.default().playbackState = .playing
            }
            guard published else { return nil }
            let removeTokens = ConversationMediaCommand.register(add: { kind, handler in
                let command = native(kind)
                let token = command.addTarget { _ in
                    // Native output retirement is synchronous; capture teardown is async.
                    handler()
                    return .success
                }
                return { command.removeTarget(token) }
            }, stop: stop)
            return {
                dispatchPrecondition(condition: .onQueue(.main))
                removeTokens()
                NCPlaybackGuard.shared.clearConversationMedia(ticket: ticket) {
                    for (command, wasEnabled) in enabled { command.isEnabled = wasEnabled }
                    MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
                    MPNowPlayingInfoCenter.default().playbackState = .stopped
                }
            }
        })
    }
}
#endif
