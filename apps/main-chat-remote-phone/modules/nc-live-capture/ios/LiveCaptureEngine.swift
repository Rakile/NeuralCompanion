import AVFAudio
import Foundation
import ExpoAudio
import UIKit

// The tap retains this immutable owner, not a bare pointer or the engine. Even
// a callback already executing during removeTap keeps the C allocation alive.
private final class CaptureRingStorage {
    let pointer: OpaquePointer
    init(capacity: UInt32, channels: UInt32) throws {
        guard let pointer = nc_ring_create(capacity, channels) else { throw CaptureFailure.startFailed }
        self.pointer = pointer
    }
    deinit { nc_ring_destroy(pointer) }
}

private final class CaptureConversion {
    let ring: CaptureRingStorage
    let converter: AVAudioConverter
    let inputBuffer: AVAudioPCMBuffer
    let outputBuffer: AVAudioPCMBuffer
    let interleaved: UnsafeMutablePointer<Float>
    let channels: Int
    var pcm = [Int16]()

    init(format: AVAudioFormat) throws {
        guard format.commonFormat == .pcmFormatFloat32, !format.isInterleaved,
              (1...2).contains(format.channelCount), format.sampleRate.isFinite,
              (8000...96000).contains(format.sampleRate),
              let output = AVAudioFormat(commonFormat: .pcmFormatFloat32,
                  sampleRate: 16000, channels: 1, interleaved: false),
              let converter = AVAudioConverter(from: format, to: output),
              let inputBuffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: 2048),
              let outputBuffer = AVAudioPCMBuffer(pcmFormat: output, frameCapacity: 1600)
        else { throw CaptureFailure.unsupportedFormat }
        self.ring = try CaptureRingStorage(capacity: UInt32(format.sampleRate), channels: format.channelCount)
        self.converter = converter
        self.inputBuffer = inputBuffer
        self.outputBuffer = outputBuffer
        self.channels = Int(format.channelCount)
        self.interleaved = .allocate(capacity: 2048 * channels)
        pcm.reserveCapacity(1600)
    }

    deinit { interleaved.deallocate() }

    func drain(_ consume: ([Int16]) throws -> Void) throws {
        // Maximum one second of converted work per tick. The ring holds at most
        // one second too; backpressure beyond that fails instead of growing work.
        for _ in 0..<10 {
            outputBuffer.frameLength = 0
            var conversionError: NSError?
            var inputCalls = 0
            var inputBudget = Int(ringCapacityFrames)
            let status = converter.convert(to: outputBuffer, error: &conversionError) { [self] requested, state in
                // Bound even pathological converter input demand. Real PCM
                // requests consume <=2,048 frames per reused input buffer.
                inputCalls += 1
                guard inputCalls <= 64, inputBudget > 0,
                      let planes = inputBuffer.floatChannelData else {
                    state.pointee = .noDataNow
                    return nil
                }
                let limit = min(requested, UInt32(min(2048, inputBudget)))
                let count = nc_ring_read(ring.pointer, interleaved, limit)
                guard count > 0 else { state.pointee = .noDataNow; return nil }
                inputBudget -= Int(count)
                for frame in 0..<Int(count) {
                    for channel in 0..<channels {
                        planes[channel][frame] = interleaved[frame * channels + channel]
                    }
                }
                inputBuffer.frameLength = count
                state.pointee = .haveData
                return inputBuffer
            }
            guard status != .error, status != .endOfStream, conversionError == nil,
                  inputCalls <= 64, let samples = outputBuffer.floatChannelData?[0]
            else { throw CaptureFailure.unsupportedFormat }
            pcm.removeAll(keepingCapacity: true)
            for index in 0..<Int(outputBuffer.frameLength) {
                let sample = samples[index]
                guard sample.isFinite else { throw CaptureFailure.unsupportedFormat }
                let scaled = (Double(sample) * 32768).rounded()
                pcm.append(Int16(max(-32768, min(32767, scaled))))
            }
            if !pcm.isEmpty { try consume(pcm) }
            if status == .inputRanDry || pcm.isEmpty { return }
        }
    }

    func discard() {
        // Consume only the bounded ring and reset converter history. Never
        // reset the producer's indices while the real-time tap is writing.
        for _ in 0..<64 {
            if nc_ring_read(ring.pointer, interleaved, 2048) == 0 { break }
        }
        converter.reset()
        pcm.removeAll(keepingCapacity: true)
        _ = nc_ring_take_overflows(ring.pointer)
    }

    private var ringCapacityFrames: UInt32 { UInt32(inputBuffer.format.sampleRate) }
}

private final class NativeCaptureInput: CaptureInput {
    private let duckingLevel: LiveDuckingLevel
    private let engine = AVAudioEngine()
    private let invalidated: (CaptureInput, CaptureFailure) -> Void
    private let enteredBackground: (CaptureInput) -> Void
    private(set) var backgroundRouteKey: String?
    private var conversion: CaptureConversion?
    private var tapInstalled = false
    private var observers: [NSObjectProtocol] = []
    private var connectionCue: AVAudioPlayer?
    private var resumeDiscardGeneration: UInt32?

    init(duckingLevel: LiveDuckingLevel, enteredBackground: @escaping (CaptureInput) -> Void,
         invalidated: @escaping (CaptureInput, CaptureFailure) -> Void) {
        self.duckingLevel = duckingLevel
        self.enteredBackground = enteredBackground
        self.invalidated = invalidated
    }

    var voiceProcessingActive: Bool {
        engine.isRunning && engine.inputNode.isVoiceProcessingEnabled
    }

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        guard session.recordPermission == .granted else { throw CaptureFailure.permissionDenied }
        guard Self.foreground() else { throw CaptureFailure.interrupted }
        do {
            try session.setCategory(.playAndRecord, mode: .voiceChat,
                                    options: [.defaultToSpeaker, .allowBluetooth])
            try session.setActive(true)
            // Available since iOS 13; module deployment target is iOS 15.1.
            // Apple requires a stopped engine when switching voice processing.
            try engine.inputNode.setVoiceProcessingEnabled(true)
            guard engine.inputNode.isVoiceProcessingEnabled else { throw CaptureFailure.startFailed }
            // Configure only this new Live input. The shared Expo player gain and
            // echo cancellation remain untouched; default preserves Apple's setup.
            if #available(iOS 17.0, *), duckingLevel != .systemDefault {
                engine.inputNode.voiceProcessingOtherAudioDuckingConfiguration = duckingLevel.configuration
            }
            let format = engine.inputNode.outputFormat(forBus: 0)
            let resources = try CaptureConversion(format: format)
            conversion = resources
            let ring = resources.ring
            let channels = format.channelCount
            let sampleRate = format.sampleRate
            engine.inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [ring] buffer, _ in
                // No dispatch, arrays, I/O, locks, session changes or conversion
                // here. Format mismatch becomes the ring's discontinuity flag.
                guard buffer.format.commonFormat == .pcmFormatFloat32,
                      !buffer.format.isInterleaved, buffer.format.channelCount == channels,
                      buffer.format.sampleRate == sampleRate,
                      let planes = buffer.floatChannelData else {
                    _ = nc_ring_write(ring.pointer, nil, buffer.frameLength)
                    return
                }
                let immutablePlanes = UnsafeRawPointer(planes).assumingMemoryBound(to: UnsafePointer<Float>?.self)
                _ = nc_ring_write(ring.pointer, immutablePlanes, buffer.frameLength)
            }
            tapInstalled = true
            observeSystemEvents()
            engine.prepare()
            try engine.start()
            // Closes the race with backgrounding during permission/session setup.
            guard Self.foreground() else { throw CaptureFailure.interrupted }
            backgroundRouteKey = BackgroundCaptureRoute.current().key
        } catch {
            // Lifecycle retires protected output before stopping this partial input.
            throw (error as? CaptureFailure) ?? CaptureFailure.startFailed
        }
    }

    func stop() {
        connectionCue?.stop(); connectionCue = nil
        backgroundRouteKey = nil
        for observer in observers { NotificationCenter.default.removeObserver(observer) }
        observers.removeAll()
        engine.stop()
        if tapInstalled {
            engine.inputNode.removeTap(onBus: 0)
            tapInstalled = false
        }
        // Processing shares the lifecycle queue, so no converter call can race
        // this release. A finishing tap still owns only its ring allocation.
        conversion = nil
        // Do not deactivate the shared session: the existing player owns output.
    }

    func takeOverflow() -> Bool {
        guard let conversion else { return false }
        return nc_ring_take_overflows(conversion.ring.pointer) != 0
    }

    func drain(_ consume: ([Int16]) throws -> Void) throws {
        guard let conversion else { return }
        try conversion.drain(consume)
    }

    func discardBufferedAudio() throws {
        guard AVAudioSession.sharedInstance().recordPermission == .granted else { throw CaptureFailure.permissionDenied }
        guard engine.isRunning else { throw CaptureFailure.interrupted }
        guard backgroundRouteKey == BackgroundCaptureRoute.current().key else { throw CaptureFailure.routeChanged }
        conversion?.discard()
    }

    func finishConnectionResume() throws -> Bool {
        guard let conversion else { throw CaptureFailure.interrupted }
        guard let generation = resumeDiscardGeneration else {
            resumeDiscardGeneration = nc_ring_request_discard(conversion.ring.pointer)
            return false
        }
        guard nc_ring_discard_is_acknowledged(conversion.ring.pointer, generation) != 0 else { return false }
        try discardBufferedAudio()
        resumeDiscardGeneration = nil
        return true
    }

    func playConnectionCue(sessionId: String, ticket: String, recoveryEpoch: Int, recovered: Bool) throws -> TimeInterval {
        resumeDiscardGeneration = nil
        guard engine.isRunning, AVAudioSession.sharedInstance().recordPermission == .granted,
              backgroundRouteKey == BackgroundCaptureRoute.current().key else { throw CaptureFailure.interrupted }
        let duration = ConnectionCue.duration(recovered: recovered)
        let player = try AVAudioPlayer(data: ConnectionCue.wave(recovered: recovered))
        player.volume = 1.0 // PCM peak already capped below the previous cue's output.
        player.prepareToPlay()
        // No session category/mode activation: keep the existing duplex route,
        // system volume, voice processing and native background authorization.
        guard NCPlaybackGuard.shared.performConnectionCue(ticket: ticket, sessionId: sessionId, recoveryEpoch: recoveryEpoch,
            stop: { player.stop() }, play: { player.play() }) else { throw CaptureFailure.interrupted }
        connectionCue = player
        return duration
    }

    static func foreground() -> Bool {
        if Thread.isMainThread { return UIApplication.shared.applicationState == .active }
        return DispatchQueue.main.sync { UIApplication.shared.applicationState == .active }
    }

    private func observeSystemEvents() {
        let center = NotificationCenter.default
        // These callbacks never read mutable engine/lifecycle state. They enqueue
        // a driver identity; the serial owner rejects identities already stopped.
        observers.append(center.addObserver(forName: UIApplication.didEnterBackgroundNotification,
            object: nil, queue: nil) { [weak self] _ in
                guard let self else { return }
                self.enteredBackground(self)
            })
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification,
            object: nil, queue: nil) { [weak self] notification in
                guard let self else { return }
                let raw = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
                let reason = raw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
                if NCPlaybackGuard.shared.admitSetupRouteChange(
                    isSetupChange: reason == .categoryChange || reason == .routeConfigurationChange,
                    routeKey: NCPlaybackGuard.nativeRouteKey()) { return }
                self.invalidated(self, .routeChanged)
            })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification,
            object: nil, queue: nil) { [weak self] notification in
                guard let self,
                      let raw = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber,
                      raw.uintValue == AVAudioSession.InterruptionType.began.rawValue else { return }
                self.invalidated(self, .interrupted)
            })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification,
            object: nil, queue: nil) { [weak self] _ in
                guard let self else { return }
                self.invalidated(self, .interrupted)
            })
    }
}

// A route identity stays entirely native. Include both directions so changing
// microphones cannot inherit a confirmation for the previous duplex route.
private struct BackgroundCaptureRoute {
    let output: BackgroundOutput
    let key: String

    var category: String {
        switch output {
        case .wired: return "wired"
        case .bluetooth: return "bluetooth"
        case .ineligible: return "ineligible"
        }
    }

    static func current() -> BackgroundCaptureRoute {
        let route = AVAudioSession.sharedInstance().currentRoute
        let output: BackgroundOutput
        if route.outputs.count == 1, let port = route.outputs.first {
            switch port.portType {
            case .headphones: output = .wired
            case .bluetoothHFP, .bluetoothA2DP, .bluetoothLE: output = .bluetooth
            default: output = .ineligible
            }
        } else { output = .ineligible }
        let key = NCPlaybackGuard.nativeRouteKey(route)
        return BackgroundCaptureRoute(output: output, key: key)
    }
}

// Expo .runOnQueue, timer and native notifications all use this serial worker.
// Stop resolves only after earlier work and producer teardown. Remaining ring /
// partial segment data is discarded, never flushed as an utterance on Stop.
final class LiveCaptureEngine {
    private var startDuckingLevel: LiveDuckingLevel = .systemDefault
    let queue = DispatchQueue(label: "nc.live-capture.worker", qos: .userInitiated)
    private var lifecycle: CaptureLifecycle?
    private var timer: DispatchSourceTimer?
    private var emit: ((CaptureNotification) -> Void)?
    private var closed = false
    private var backgroundCommands: (sessionId: String, owner: BackgroundLiveCommands)?
    // These observers own only the protected session/ticket, never an input tap.
    private var outputSafety: (sessionId: String, ticket: String, observers: [NSObjectProtocol])?

    func setEmitter(_ emit: @escaping (CaptureNotification) -> Void) {
        queue.async { [self] in self.emit = emit }
    }

    func capabilities() -> [String: Any] {
        dispatchPrecondition(condition: .onQueue(queue))
        let route = AVAudioSession.sharedInstance().currentRoute
        return ["available": !closed, "reason": closed ? "Capture module is closed." : "",
            "voiceProcessingSupported": true,
            "lastRetirementCause": NCPlaybackGuard.shared.lastRetirementCause,
            "duckingSupported": !closed && LiveDuckingLevel.supported,
            "backgroundLiveVersion": 1,
            "playbackGuardVersion": NCPlaybackGuard.version,
            "stopListeningVersion": 1,
            "foregroundReplyControlsVersion": 1,
            "connectionRecoveryVersion": NCPlaybackGuard.connectionRecoveryVersion,
            "replyContinuationVersion": 1,
            "backgroundRoute": closed ? "ineligible" : BackgroundCaptureRoute.current().category,
            "voiceProcessingActive": lifecycle?.voiceProcessingActive ?? false,
            "inputRoute": Self.routeCategories(route.inputs),
            "outputRoute": Self.routeCategories(route.outputs)]
    }

    func start(sessionId: String, duckingLevel: String = "default") throws {
        dispatchPrecondition(condition: .onQueue(queue))
        let startingFromIdle = lifecycle?.currentSessionId == nil
        do {
            guard !closed else { throw CaptureFailure.startFailed }
            guard NativeCaptureInput.foreground() else { throw CaptureFailure.interrupted }
            let level = try LiveDuckingLevel.resolve(duckingLevel, supported: LiveDuckingLevel.supported)
            let capture = try getLifecycle()
            startDuckingLevel = level
            defer { startDuckingLevel = .systemDefault }
            let output = NCPlaybackGuard.shared
            if startingFromIdle, let ticket = output.currentTicket, output.protectedSessionId(for: ticket) == sessionId {
                try output.prepareProtectedInput(ticket: ticket, sessionId: sessionId, snapshot: {
                    (NativeCaptureInput.foreground(), BackgroundCaptureRoute.current().key)
                }) { try capture.start(sessionId: sessionId) }
            } else {
                try capture.start(sessionId: sessionId)
            }
            if timer == nil {
                let timer = DispatchSource.makeTimerSource(queue: queue)
                timer.schedule(deadline: .now() + .milliseconds(20), repeating: .milliseconds(20), leeway: .milliseconds(5))
                timer.setEventHandler { [weak self] in
                    guard let self else { return }
                    autoreleasepool { self.lifecycle?.process() }
                    self.cancelTimerIfStopped()
                }
                self.timer = timer
                timer.resume()
            }
        } catch {
            // Permission/foreground/ducking failures can occur before input.start.
            // Retire only this pending attempt, never a running owner's ticket.
            if startingFromIdle { try? lifecycle?.stop(sessionId: sessionId) }
            throw error
        }
    }

    func outputState() -> [String: Any] {
        dispatchPrecondition(condition: .onQueue(queue))
        let guardOwner = NCPlaybackGuard.shared
        guard let ticket = guardOwner.currentTicket else {
            return ["ticket": NSNull(), "open": false, "sessionId": NSNull()]
        }
        let sessionId = guardOwner.protectedSessionId(for: ticket)
        let open = guardOwner.ticketIsOpen(ticket)
        return ["ticket": ticket, "open": open, "sessionId": open ? (sessionId as Any? ?? NSNull()) : NSNull()]
    }

    func beginProtectedOutput(sessionId: String, expectedTicket: String?) throws -> String {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !closed else { throw CaptureFailure.startFailed }
        let capture = try getLifecycle()
        // No output/media lock is held when crossing to main. The actual UIKit
        // foreground read and Begin happen in the same main-thread operation.
        return try capture.beginProtectedOutput(sessionId: sessionId) {
            try DispatchQueue.main.sync {
                try NCPlaybackGuard.shared.beginProtected(sessionId: sessionId, expectedTicket: expectedTicket,
                    foreground: UIApplication.shared.applicationState == .active)
            }
        }
    }

    func beginForegroundOutput(expectedTicket: String?) throws -> String {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !closed else { throw CaptureFailure.startFailed }
        return try DispatchQueue.main.sync {
            try NCPlaybackGuard.shared.beginForeground(expectedTicket: expectedTicket,
                foreground: UIApplication.shared.applicationState == .active)
        }
    }

    func beginForegroundProtectedOutput(sessionId: String, expectedTicket: String?) throws -> String {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !closed else { throw CaptureFailure.startFailed }
        let capture = try getLifecycle()
        return try capture.beginProtectedOutput(sessionId: sessionId, foregroundOnly: true) {
            try DispatchQueue.main.sync {
                try NCPlaybackGuard.shared.beginProtected(sessionId: sessionId, expectedTicket: expectedTicket,
                    foreground: UIApplication.shared.applicationState == .active, foregroundOnly: true)
            }
        }
    }

    func retireOutput(ticket: String) {
        dispatchPrecondition(condition: .onQueue(queue))
        NCPlaybackGuard.shared.retire(ticket: ticket)
        lifecycle?.retireMatchingOutput(ticket: ticket)
        cancelTimerIfStopped()
    }

    func stop(sessionId: String) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        defer { cancelTimerIfStopped() }
        try lifecycle?.stop(sessionId: sessionId)
    }

    func stopListening(sessionId: String, permit: ReplyTailPermit) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        defer { cancelTimerIfStopped() }
        if lifecycle?.currentSessionId == sessionId, AVAudioSession.sharedInstance().recordPermission != .granted {
            lifecycle?.endForSystemEvent(.permissionDenied)
            return
        }
        try lifecycle?.stopListening(sessionId: sessionId, permit: permit)
    }

    func registerSubmittedUpload(sessionId: String, utteranceId: String, uploadId: String) -> Bool {
        lifecycle?.registerSubmittedUpload(sessionId: sessionId, utteranceId: utteranceId, uploadId: uploadId) ?? false
    }
    func registerSubmittedTurn(sessionId: String, ticket: String, submissionId: String, kind: String) -> Bool {
        lifecycle?.registerSubmittedTurn(sessionId: sessionId, ticket: ticket, submissionId: submissionId, kind: kind) ?? false
    }
    func admitReplyForUpload(sessionId: String, ticket: String, uploadId: String, requestId: String) -> Bool {
        lifecycle?.admitReplyForUpload(sessionId: sessionId, ticket: ticket, uploadId: uploadId, requestId: requestId) ?? false
    }
    func abandonSubmittedUpload(sessionId: String, ticket: String, uploadId: String) {
        lifecycle?.abandonSubmittedUpload(sessionId: sessionId, ticket: ticket, uploadId: uploadId)
    }
    func finishReplyOutput(sessionId: String, ticket: String, completedRequestIds: [String]) throws {
        defer { cancelTimerIfStopped() }
        guard let lifecycle else { throw CaptureFailure.replyTailUnavailable }
        try lifecycle.finishReplyOutput(sessionId: sessionId, ticket: ticket, completedRequestIds: completedRequestIds)
    }

    func armBackground(sessionId: String, bluetoothConfirmed: Bool) -> Bool {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !closed, NativeCaptureInput.foreground() else { return false }
        let route = BackgroundCaptureRoute.current()
        guard let lifecycle, lifecycle.armBackground(sessionId: sessionId, foreground: NativeCaptureInput.foreground(),
            output: route.output, routeKey: route.key, bluetoothConfirmed: bluetoothConfirmed) else { return false }
        guard let ticket = NCPlaybackGuard.shared.currentTicket,
              NCPlaybackGuard.shared.armProtectedOutput(ticket: ticket, sessionId: sessionId,
                foreground: NativeCaptureInput.foreground(), routeKey: BackgroundCaptureRoute.current().key),
              let command = lifecycle.conversationStopCommand(sessionId: sessionId) else {
            lifecycle.endForSystemEvent(.interrupted)
            cancelTimerIfStopped()
            return false
        }
        if backgroundCommands?.sessionId == sessionId { return true }
        deactivateBackgroundCommands()
        let owner = BackgroundLiveCommands.conversation(ticket: command.ticket, sessionId: sessionId)
        backgroundCommands = (sessionId, owner)
        owner.activate(stop: command.stop)
        observeOutputSafety(sessionId: sessionId, ticket: command.ticket)
        return true
    }

    func disarmBackground(sessionId: String) {
        dispatchPrecondition(condition: .onQueue(queue))
        guard lifecycle?.currentSessionId == sessionId, lifecycle?.foregroundOnly != true else { return }
        deactivateBackgroundCommands()
        lifecycle?.disarmBackground(sessionId: sessionId)
        if !NativeCaptureInput.foreground() {
            lifecycle?.endForSystemEvent(.interrupted)
            cancelTimerIfStopped()
        }
    }

    func armForeground(sessionId: String) -> Bool {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !closed, let lifecycle,
              lifecycle.armForeground(sessionId: sessionId, foreground: NativeCaptureInput.foreground()) else { return false }
        guard let ticket = NCPlaybackGuard.shared.currentTicket,
              NCPlaybackGuard.shared.armForegroundProtectedOutput(ticket: ticket, sessionId: sessionId,
                foreground: NativeCaptureInput.foreground(), routeKey: BackgroundCaptureRoute.current().key),
              let command = lifecycle.conversationStopCommand(sessionId: sessionId) else {
            lifecycle.endForSystemEvent(.interrupted)
            cancelTimerIfStopped()
            return false
        }
        if backgroundCommands?.sessionId == sessionId { return true }
        deactivateBackgroundCommands()
        let owner = BackgroundLiveCommands.conversation(ticket: command.ticket, sessionId: sessionId)
        backgroundCommands = (sessionId, owner)
        owner.activate(stop: command.stop)
        observeOutputSafety(sessionId: sessionId, ticket: command.ticket, foregroundOnly: true)
        return true
    }

    func setPlaybackActive(sessionId: String, active: Bool) {
        lifecycle?.setPlaybackActive(sessionId: sessionId, active: active)
    }

    func pauseConnection(sessionId: String, ticket: String, recoveryEpoch: Int) -> Bool {
        lifecycle?.pauseConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch) ?? false
    }
    func pauseReplyContinuation(sessionId: String, ticket: String, recoveryEpoch: Int) -> [String: Any]? {
        guard let checkpoint = NCPlaybackGuard.shared.pauseReplyContinuation(ticket: ticket, sessionId: sessionId, recoveryEpoch: recoveryEpoch) else { return nil }
        guard pauseConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch) else {
            NCPlaybackGuard.shared.retire(ticket: ticket)
            return nil
        }
        return checkpoint.payload
    }
    func resumeReplyContinuation(sessionId: String, ticket: String, recoveryEpoch: Int, requestIds: [String], completion: @escaping (Bool) -> Void) {
        guard NCPlaybackGuard.shared.prepareReplyContinuation(ticket: ticket, sessionId: sessionId, recoveryEpoch: recoveryEpoch, requestIds: requestIds) else { completion(false); return }
        resumeConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch, completion: completion)
    }

    func resumeConnection(sessionId: String, ticket: String, recoveryEpoch: Int, completion: @escaping (Bool) -> Void) {
        guard let lifecycle else { completion(false); return }
        lifecycle.resumeConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch, completion: completion)
    }

    func acquire(sessionId: String, utteranceId: String) throws -> [String: Any] {
        guard let lifecycle else { throw CaptureFailure.fileFailed }
        let clip = try lifecycle.acquire(sessionId: sessionId, utteranceId: utteranceId)
        return ["sessionId": clip.sessionId, "utteranceId": clip.utteranceId,
            "uri": clip.uri, "byteLength": clip.byteLength, "durationMs": clip.durationMs]
    }

    func release(sessionId: String, utteranceId: String) throws {
        try lifecycle?.release(sessionId: sessionId, utteranceId: utteranceId)
    }

    func acknowledgeState(sessionId: String, sequence: Int) {
        lifecycle?.acknowledgeState(sessionId: sessionId, sequence: sequence)
    }

    func destroy() {
        queue.async { [self] in
            closed = true
            timer?.cancel()
            timer = nil
            lifecycle?.shutdown()
            deactivateBackgroundCommands()
            emit = nil
            // Retain the owning store as long as this module object is reachable;
            // already queued releases still resolve through its original mapping.
        }
    }

    func readerContextDestroyed() {
        queue.async { [self] in
            closed = true
            timer?.cancel()
            timer = nil
            lifecycle?.shutdown()
            deactivateBackgroundCommands()
            lifecycle?.retireReaderLeases()
            emit = nil
        }
    }

    private func getLifecycle() throws -> CaptureLifecycle {
        if let lifecycle { return lifecycle }
        guard let root = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first
        else { throw CaptureFailure.fileFailed }
        let store: UtteranceStore
        do { store = try UtteranceStore(rootDirectory: root) }
        catch { throw CaptureFailure.fileFailed }
        let capture = CaptureLifecycle(queue: queue, store: store, makeInput: { [weak self] in
            NativeCaptureInput(duckingLevel: self?.startDuckingLevel ?? .systemDefault,
                enteredBackground: { [weak self] source in
                    guard let self else { return }
                    self.queue.async { [weak self] in
                        self?.lifecycle?.enterBackground(routeKey: BackgroundCaptureRoute.current().key, source: source)
                        self?.cancelTimerIfStopped()
                    }
                }) { [weak self] source, reason in
                guard let self else { return }
                self.queue.async { [weak self] in
                    self?.lifecycle?.endForSystemEvent(reason, source: source)
                    self?.cancelTimerIfStopped()
                }
            }
        }, outputIsOpen: { sessionId, ticket in
            NCPlaybackGuard.shared.protectedSessionId(for: ticket) == sessionId
        }, retireOutput: { ticket in
            NCPlaybackGuard.shared.retire(ticket: ticket)
        }, outputNotificationObject: NCPlaybackGuard.shared, onOutputRetirement: { [weak self] in
            self?.cancelTimerIfStopped()
        }, registerSubmission: { session, ticket, upload in
            NCPlaybackGuard.shared.registerReplySubmission(ticket: ticket, sessionId: session, uploadId: upload)
        }, sealReplyTail: { session, ticket, requests, pending in
            NCPlaybackGuard.shared.sealReplyTail(ticket: ticket, sessionId: session, requestIds: requests, pendingUploadIds: pending)
        }, admitReply: { session, ticket, upload, request in
            NCPlaybackGuard.shared.admitReplyForUpload(ticket: ticket, sessionId: session, uploadId: upload, requestId: request)
        }, abandonSubmission: { session, ticket, upload in
            NCPlaybackGuard.shared.abandonSubmittedUpload(ticket: ticket, sessionId: session, uploadId: upload)
        }, finishReplyTail: { session, ticket, requests in
            NCPlaybackGuard.shared.finishReplyTail(ticket: ticket, sessionId: session, completedRequestIds: requests)
        }, freezeReplyOnset: { session, ticket, interruption in
            switch NCPlaybackGuard.shared.freezeCurrentPhoneReplyReceipt(ticket: ticket, sessionId: session, interruptionId: interruption) {
            case .none: return .none
            case .unavailable: return .unavailable
            case let .receipt(receipt):
                return .receipt(CaptureReplyReceipt(phoneRequestId: receipt.phoneRequestId,
                    interruptionId: receipt.interruptionId, startedChunkIds: receipt.startedChunkIds))
            }
        }, pauseOutputConnection: { session, ticket, epoch in
            NCPlaybackGuard.shared.pauseConnection(ticket: ticket, sessionId: session, recoveryEpoch: epoch)
        }, resumeOutputConnection: { session, ticket, epoch in
            NCPlaybackGuard.shared.resumeConnection(ticket: ticket, sessionId: session, recoveryEpoch: epoch)
        }, emit: { [weak self] event in
            if event.lifetime == .closed, self?.backgroundCommands?.sessionId == event.sessionId {
                self?.deactivateBackgroundCommands()
            }
            self?.emit?(event)
        })
        lifecycle = capture
        return capture
    }

    private func cancelTimerIfStopped() {
        if lifecycle?.isCapturing != true {
            timer?.cancel()
            timer = nil
        }
        if lifecycle?.lifetime == .closed {
            deactivateBackgroundCommands()
        }
    }

    private func deactivateBackgroundCommands() {
        if let safety = outputSafety {
            for observer in safety.observers { NotificationCenter.default.removeObserver(observer) }
            outputSafety = nil
        }
        backgroundCommands?.owner.deactivate()
        backgroundCommands = nil
    }

    private func observeOutputSafety(sessionId: String, ticket: String, foregroundOnly: Bool = false) {
        let center = NotificationCenter.default
        let stop: (CaptureFailure, NCPlaybackGuard.RetirementCause) -> Void = { [weak self] reason, cause in
            // Immediate native output stop even if capture/main/JS are delayed.
            NCPlaybackGuard.shared.retire(ticket: ticket, cause: cause)
            self?.queue.async { [weak self] in
                self?.lifecycle?.endForOutputSystemEvent(reason, sessionId: sessionId, ticket: ticket)
                self?.cancelTimerIfStopped()
            }
        }
        var observers: [NSObjectProtocol] = []
        if foregroundOnly {
            observers.append(center.addObserver(forName: UIApplication.willResignActiveNotification, object: nil, queue: nil) { _ in
                stop(.interrupted, .foregroundLeft)
            })
        }
        observers.append(center.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: nil) { event in
            let raw = event.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt
            let reason = raw.flatMap(AVAudioSession.RouteChangeReason.init(rawValue:))
            let isSetupChange = reason == .categoryChange || reason == .routeConfigurationChange
            let routeKey = BackgroundCaptureRoute.current().key
            if NCPlaybackGuard.shared.allowsArmedSetupRouteChange(ticket: ticket,
                isSetupChange: isSetupChange, routeKey: routeKey)
                || NCPlaybackGuard.shared.allowsReplyTailRouteChange(ticket: ticket,
                    isSetupChange: isSetupChange, routeKey: routeKey) { return }
            let cause = NCPlaybackGuard.shared.routeChangeCause(
                isSetupChange: isSetupChange, routeKey: routeKey)
            stop(.routeChanged, cause)
        })
        observers.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: nil) { event in
            guard let raw = event.userInfo?[AVAudioSessionInterruptionTypeKey] as? NSNumber,
                  raw.uintValue == AVAudioSession.InterruptionType.began.rawValue else { return }
            stop(.interrupted, .interruption)
        })
        observers.append(center.addObserver(forName: AVAudioSession.mediaServicesWereResetNotification, object: nil, queue: nil) { _ in stop(.interrupted, .mediaReset) })
        observers.append(center.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: nil) { _ in
            if AVAudioSession.sharedInstance().recordPermission != .granted { stop(.permissionDenied, .permissionRevoked) }
        })
        outputSafety = (sessionId, ticket, observers)
    }

    private static func routeCategories(_ ports: [AVAudioSessionPortDescription]) -> String {
        let known: [(AVAudioSession.Port, String)] = [
            (.builtInMic, "builtInMic"), (.builtInSpeaker, "builtInSpeaker"),
            (.builtInReceiver, "builtInReceiver"), (.headphones, "headphones"),
            (.headsetMic, "headsetMic"), (.bluetoothHFP, "bluetoothHFP"),
            (.bluetoothA2DP, "bluetoothA2DP"), (.bluetoothLE, "bluetoothLE"),
            (.usbAudio, "usbAudio"), (.carAudio, "carAudio"),
            (.lineIn, "lineIn"), (.lineOut, "lineOut"), (.airPlay, "airPlay"), (.HDMI, "HDMI")]
        let categories = ports.prefix(4).map { port in
            known.first { $0.0 == port.portType }?.1 ?? "unknown"
        }
        return categories.isEmpty ? "none" : categories.joined(separator: ",")
    }
}
