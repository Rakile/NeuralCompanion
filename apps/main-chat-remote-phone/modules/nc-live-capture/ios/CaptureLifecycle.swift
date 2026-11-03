import Foundation

enum CaptureFailure: String, Error {
    case permissionDenied = "permission_denied"
    case unsupportedFormat = "unsupported_format"
    case captureOverflow = "capture_overflow"
    case backlogFull = "backlog_full"
    case routeChanged = "route_changed"
    case interrupted
    case startFailed = "start_failed"
    case releaseFailed = "release_failed"
    case fileFailed = "file_failed"
    case backgroundSessionLimit = "background_session_limit"
    case conversationStopped = "conversation_stopped"
    case replyTailTimeout = "reply_tail_timeout"
    case replyTailUnavailable = "reply_tail_unavailable"
}

enum CaptureLifetime: String { case capturing, replyTail = "reply-tail", closed }
struct ReplyTailPermit { let requestIds: [String]; let pendingUploadIds: [String] }
struct CaptureReplyReceipt: Equatable {
    let phoneRequestId: String
    let interruptionId: String
    let startedChunkIds: [String]
    var payload: [String: Any] {
        ["phone_request_id": phoneRequestId, "interruption_id": interruptionId, "started_chunk_ids": startedChunkIds]
    }
}
enum CaptureReplyOnset { case none, unavailable, receipt(CaptureReplyReceipt) }

// One bounded request receipt. Its lock never spans guard calls or queue dispatch.
private final class ConversationStopReceipt {
    let sessionId: String
    let ticket: String
    private let lock = NSLock()
    private var enabled = true
    private var requested = false
    init(sessionId: String, ticket: String) {
        self.sessionId = sessionId; self.ticket = ticket
    }
    func request() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard enabled, !requested else { return false }
        requested = true
        return true
    }
    var wasRequested: Bool { lock.lock(); defer { lock.unlock() }; return requested }
    func invalidate() { lock.lock(); enabled = false; lock.unlock() }
}

protocol CaptureInput: AnyObject {
    var voiceProcessingActive: Bool { get }
    var backgroundRouteKey: String? { get }
    func start() throws
    // Must stop the producer and detach its tap before returning. The tap owns
    // its ring independently, so an already executing callback remains safe.
    func stop()
    func takeOverflow() -> Bool
    // Bounded work; each delivered PCM batch is at most 1,600 mono samples.
    func drain(_ consume: ([Int16]) throws -> Void) throws
    func discardBufferedAudio() throws
    func finishConnectionResume() throws -> Bool
    func playConnectionCue(sessionId: String, ticket: String, recoveryEpoch: Int, recovered: Bool) throws -> TimeInterval
}

extension CaptureInput {
    var backgroundRouteKey: String? { nil }
    func discardBufferedAudio() throws { try drain { _ in }; _ = takeOverflow() }
    func finishConnectionResume() throws -> Bool { try discardBufferedAudio(); return true }
    func playConnectionCue(sessionId: String, ticket: String, recoveryEpoch: Int, recovered: Bool) throws -> TimeInterval { 0 }
}

struct CaptureNotification {
    let sessionId: String
    let sequence: Int
    let kind: String
    let phase: String
    let utteranceId: String?
    let durationMs: Double
    let meteringDb: Double?
    let error: String?
    var backgroundAuthorized: Bool? = nil
    var lifetime: CaptureLifetime = .closed
    var phoneReplyReceipt: CaptureReplyReceipt? = nil
    var phoneReplyUnavailable: Bool = false

    var payload: [String: Any] {
        var result: [String: Any] = ["sessionId": sessionId, "sequence": sequence,
            "kind": kind, "phase": phase, "durationMs": durationMs]
        if let utteranceId { result["utteranceId"] = utteranceId }
        if let meteringDb { result["meteringDb"] = meteringDb }
        if let error { result["error"] = error }
        if let backgroundAuthorized { result["backgroundAuthorized"] = backgroundAuthorized }
        result["lifetime"] = lifetime.rawValue
        if let phoneReplyReceipt { result["phoneReplyReceipt"] = phoneReplyReceipt.payload }
        if phoneReplyUnavailable { result["phoneReplyUnavailable"] = true }
        return result
    }
}

// Every entry point, including snapshot reads, runs on the supplied serial
// worker queue. No synchronous dispatch back to this queue is performed here.
// Expo calls, timer work, and system notifications enqueue on that same owner:
// stop/release therefore wait for an in-progress conversion/export to finish.
final class CaptureLifecycle {
    private struct LeaseKey: Hashable {
        let sessionId: String
        let utteranceId: String
    }
    private let queue: DispatchQueue
    private let store: UtteranceStore
    private let makeInput: () -> CaptureInput
    private let emit: (CaptureNotification) -> Void
    private let clock: () -> TimeInterval
    private let outputIsOpen: (String, String) -> Bool
    private let retireOutput: (String) -> Void
    private var protectedOutput: (sessionId: String, ticket: String, foregroundOnly: Bool)?
    private var foregroundArmed = false
    private let registerSubmission: (String, String, String) -> Bool
    private let sealReplyTail: (String, String, [String], [String]) -> [String]?
    private let admitReply: (String, String, String, String) -> Bool
    private let abandonSubmission: (String, String, String) -> Void
    private let finishReplyTail: (String, String, [String]) -> Bool
    private let freezeReplyOnset: (String, String, String) -> CaptureReplyOnset
    private let scheduleTailDeadline: (TimeInterval, @escaping () -> Void) -> (() -> Void)
    private var cancelTailDeadline: (() -> Void)?
    private var tailRequests: Set<String>?
    private enum SubmittedKind: Equatable { case upload(LeaseKey), explicit(String) }
    private var pendingSubmissions: [String: SubmittedKind] = [:]
    private var onsetResult: (utteranceId: String, result: CaptureReplyOnset)?
    private var conversationStopReceipt: ConversationStopReceipt?
    // Every issued protected session stays fenced for this native lifecycle.
    // Refuse new protected ownership at capacity; never evict or reuse an ID.
    private var protectedSessionIds: Set<String> = []
    private static let protectedSessionCapacity = 256
    private var outputRetirementObserver: NSObjectProtocol?
    private let segmenter = LiveSegmenter()
    private var input: CaptureInput?
    private var sessionId: String?
    private var eventSession: String?
    private var sequence = 0
    private var playbackActive = false
    private var outstandingState: Int?
    private var pendingState: (phase: String, duration: Double, meter: Double?)?
    private var lastStateTime = -Double.infinity
    private var stateFlushScheduled = false
    private var closed = false
    private var backgroundPolicy = BackgroundLivePolicy()
    private var backgroundWasRequested = false
    // At most two keys: insertion follows successful acquire from the bounded
    // store; ordinary stop/shutdown never expires a live reader.
    private var readerLeases: Set<LeaseKey> = []
    private var invalidatedReaderLeases: Set<LeaseKey> = []
    private let pauseOutputConnection: (String, String, Int) -> Bool
    private let resumeOutputConnection: (String, String, Int) -> Bool
    private let scheduleConnectionRecovery: (TimeInterval, @escaping () -> Void) -> (() -> Void)
    private var cancelConnectionRecovery: (() -> Void)?
    private var recoveryEpoch = 0
    private var connectionPaused = false
    private var recoveryCompletion: ((Bool) -> Void)?

    init(queue: DispatchQueue, store: UtteranceStore,
         makeInput: @escaping () -> CaptureInput,
         clock: @escaping () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
         outputIsOpen: @escaping (String, String) -> Bool = { _, _ in false },
         retireOutput: @escaping (String) -> Void = { _ in },
         outputNotificationObject: AnyObject? = nil,
         onOutputRetirement: @escaping () -> Void = {},
         registerSubmission: @escaping (String, String, String) -> Bool = { _, _, _ in false },
         sealReplyTail: @escaping (String, String, [String], [String]) -> [String]? = { _, _, _, _ in nil },
         admitReply: @escaping (String, String, String, String) -> Bool = { _, _, _, _ in false },
         abandonSubmission: @escaping (String, String, String) -> Void = { _, _, _ in },
         finishReplyTail: @escaping (String, String, [String]) -> Bool = { _, _, _ in false },
         freezeReplyOnset: @escaping (String, String, String) -> CaptureReplyOnset = { _, _, _ in .none },
         scheduleTailDeadline: ((TimeInterval, @escaping () -> Void) -> (() -> Void))? = nil,
         pauseOutputConnection: @escaping (String, String, Int) -> Bool = { _, _, _ in false },
         resumeOutputConnection: @escaping (String, String, Int) -> Bool = { _, _, _ in false },
         scheduleConnectionRecovery: ((TimeInterval, @escaping () -> Void) -> (() -> Void))? = nil,
         emit: @escaping (CaptureNotification) -> Void) {
        self.queue = queue
        self.store = store
        self.makeInput = makeInput
        self.clock = clock
        self.outputIsOpen = outputIsOpen
        self.retireOutput = retireOutput
        self.registerSubmission = registerSubmission
        self.sealReplyTail = sealReplyTail
        self.admitReply = admitReply
        self.abandonSubmission = abandonSubmission
        self.finishReplyTail = finishReplyTail
        self.freezeReplyOnset = freezeReplyOnset
        self.scheduleTailDeadline = scheduleTailDeadline ?? { seconds, action in
            let item = DispatchWorkItem(block: action)
            queue.asyncAfter(deadline: .now() + seconds, execute: item)
            return { item.cancel() }
        }
        self.emit = emit
        self.pauseOutputConnection = pauseOutputConnection
        self.resumeOutputConnection = resumeOutputConnection
        self.scheduleConnectionRecovery = scheduleConnectionRecovery ?? { seconds, action in
            let item = DispatchWorkItem(block: action)
            queue.asyncAfter(deadline: .now() + seconds, execute: item)
            return { item.cancel() }
        }
        if let outputNotificationObject {
            outputRetirementObserver = NotificationCenter.default.addObserver(
                forName: Notification.Name("NCPlaybackGuardDidRetire"), object: outputNotificationObject,
                queue: nil) { [weak self] notification in
                    guard let self, let ticket = notification.userInfo?["ticket"] as? String,
                          let sessionId = notification.userInfo?["sessionId"] as? String else { return }
                    // Guard output is already closed. Its notification arrives
                    // after output unlock and never waits for capture or main.
                    self.queue.async { [weak self] in
                        guard let self else { return }
                        self.outputDidRetire(ticket: ticket, sessionId: sessionId)
                        onOutputRetirement()
                    }
                }
        }
    }

    deinit {
        cancelTailDeadline?()
        cancelConnectionRecovery?()
        if let outputRetirementObserver { NotificationCenter.default.removeObserver(outputRetirementObserver) }
    }

    var isCapturing: Bool { assertOwner(); return input != nil }
    var voiceProcessingActive: Bool { assertOwner(); return input?.voiceProcessingActive ?? false }
    var currentSessionId: String? { assertOwner(); return sessionId }
    var backgroundAuthorized: Bool { assertOwner(); return backgroundPolicy.armed }
    var foregroundOnly: Bool { assertOwner(); return protectedOutput?.foregroundOnly == true }
    private var replyControlsAuthorized: Bool { backgroundPolicy.armed || foregroundArmed }
    var lifetime: CaptureLifetime {
        assertOwner()
        return input != nil ? .capturing : (tailRequests != nil ? .replyTail : .closed)
    }

    func canBeginProtectedOutput(sessionId requested: String) -> Bool {
        assertOwner()
        do { try validateProtectedBegin(sessionId: requested); return true }
        catch { return false }
    }

    private func validateProtectedBegin(sessionId requested: String) throws {
        guard !closed, Self.validID(requested), protectedOutput == nil,
              sessionId == nil || sessionId == requested,
              !protectedSessionIds.contains(requested) else { throw CaptureFailure.startFailed }
        guard protectedSessionIds.count < Self.protectedSessionCapacity
        else { throw CaptureFailure.backgroundSessionLimit }
    }

    func beginProtectedOutput(sessionId requested: String, foregroundOnly: Bool = false, issue: () throws -> String) throws -> String {
        assertOwner()
        // Admission precedes the shared guard's issuance. Its native callback
        // only enqueues here, so no other capture operation can interleave.
        try validateProtectedBegin(sessionId: requested)
        let ticket = try issue()
        do { try adoptProtectedOutput(sessionId: requested, ticket: ticket, foregroundOnly: foregroundOnly) }
        catch { retireOutput(ticket); throw error }
        return ticket
    }

    func adoptProtectedOutput(sessionId requested: String, ticket: String, foregroundOnly: Bool = false) throws {
        assertOwner()
        try validateProtectedBegin(sessionId: requested)
        // Reserve even an issued ticket that retired before adoption. Its late
        // Start must never become ordinary capture after some later attempt.
        protectedSessionIds.insert(requested)
        guard outputIsOpen(requested, ticket) else { throw CaptureFailure.startFailed }
        protectedOutput = (requested, ticket, foregroundOnly)
        foregroundArmed = false
    }

    func outputDidRetire(ticket: String, sessionId requested: String) {
        assertOwner()
        guard let output = protectedOutput, output.ticket == ticket, output.sessionId == requested
        else { return }
        if sessionId == requested {
            let commandStop = conversationStopReceipt.map {
                $0.sessionId == requested && $0.ticket == ticket && $0.wasRequested
            } ?? false
            endForSystemEvent(commandStop ? .conversationStopped : .interrupted)
        } else {
            retireProtectedOutput(sessionId: requested)
        }
    }

    private func retireProtectedOutput(sessionId requested: String) {
        guard let output = protectedOutput, output.sessionId == requested else { return }
        // Clear the capture association before the guard emits its idempotent
        // native notification. Output closes before producer stop or JS events.
        protectedOutput = nil
        foregroundArmed = false
        retireOutput(output.ticket)
    }

    func retireMatchingOutput(ticket: String) {
        assertOwner()
        guard let output = protectedOutput, output.ticket == ticket else { return }
        outputDidRetire(ticket: ticket, sessionId: output.sessionId)
    }

    func armBackground(sessionId requested: String, foreground: Bool, output: BackgroundOutput,
                       routeKey: String, bluetoothConfirmed: Bool) -> Bool {
        assertOwner()
        guard sessionId == requested, let input,
              input.backgroundRouteKey == routeKey,
              let outputOwner = protectedOutput, outputOwner.sessionId == requested, !outputOwner.foregroundOnly,
              outputIsOpen(requested, outputOwner.ticket) else { return false }
        backgroundWasRequested = true
        let armed = backgroundPolicy.arm(foreground: foreground, output: output,
            routeKey: routeKey, bluetoothConfirmed: bluetoothConfirmed)
        state(phase: segmenter.phase, duration: segmenter.durationMs, meter: segmenter.meteringDb)
        return armed
    }

    func armForeground(sessionId requested: String, foreground: Bool) -> Bool {
        assertOwner()
        guard foreground, sessionId == requested, input != nil,
              let output = protectedOutput, output.sessionId == requested, output.foregroundOnly,
              outputIsOpen(requested, output.ticket) else { return false }
        foregroundArmed = true
        return true
    }

    func disarmBackground(sessionId requested: String) {
        assertOwner()
        guard sessionId == requested else { return }
        guard !foregroundOnly else { return }
        if connectionPaused { endForSystemEvent(.interrupted); return }
        if tailRequests != nil { endForSystemEvent(.interrupted); return }
        invalidateConversationStop()
        backgroundPolicy.revoke()
        state(phase: segmenter.phase, duration: segmenter.durationMs, meter: segmenter.meteringDb)
    }

    func conversationStopCommand(sessionId requested: String) -> (ticket: String, stop: () -> Void)? {
        assertOwner()
        guard replyControlsAuthorized, sessionId == requested,
              let output = protectedOutput, output.sessionId == requested,
              outputIsOpen(requested, output.ticket) else { return nil }
        let receipt: ConversationStopReceipt
        if let current = conversationStopReceipt { receipt = current }
        else {
            receipt = ConversationStopReceipt(sessionId: requested, ticket: output.ticket)
            conversationStopReceipt = receipt
        }
        let retire = retireOutput
        return (output.ticket, { [weak self] in
            guard receipt.request() else { return }
            // Mark before retirement: its observer can win capture queue ordering.
            retire(receipt.ticket)
            self?.queue.async { [weak self] in
                guard let self, self.conversationStopReceipt === receipt,
                      self.sessionId == receipt.sessionId, self.protectedOutput?.ticket == receipt.ticket else { return }
                self.endForSystemEvent(.conversationStopped)
            }
        })
    }

    private func invalidateConversationStop() {
        conversationStopReceipt?.invalidate()
        conversationStopReceipt = nil
    }

    func enterBackground(routeKey: String, source: CaptureInput) {
        assertOwner()
        guard input === source else { return }
        guard let output = protectedOutput,
              outputIsOpen(output.sessionId, output.ticket),
              backgroundPolicy.permitsBackground(routeKey: routeKey) else {
            endForSystemEvent(.interrupted, source: source)
            return
        }
    }

    func start(sessionId requested: String) throws {
        assertOwner()
        guard !closed, Self.validID(requested) else { throw CaptureFailure.startFailed }
        guard tailRequests == nil else { throw CaptureFailure.startFailed }
        if protectedSessionIds.contains(requested) {
            guard let output = protectedOutput, output.sessionId == requested,
                  outputIsOpen(requested, output.ticket) else { throw CaptureFailure.interrupted }
        }
        if let output = protectedOutput {
            guard output.sessionId == requested else { throw CaptureFailure.startFailed }
        }
        if let current = sessionId {
            guard current == requested else { throw CaptureFailure.startFailed }
            return
        }
        eventSession = requested
        backgroundPolicy.revoke()
        backgroundWasRequested = false
        sequence = 0
        outstandingState = nil
        pendingState = nil
        // Do not reset lastStateTime: even rapid new sessions remain <=10 Hz.
        segmenter.reset()
        playbackActive = false
        recoveryEpoch = 0
        let candidate = makeInput()
        do {
            if let output = protectedOutput, !outputIsOpen(requested, output.ticket) {
                throw CaptureFailure.interrupted
            }
            try store.cleanup(now: Date())
            try candidate.start()
            if let output = protectedOutput, !outputIsOpen(requested, output.ticket) {
                throw CaptureFailure.interrupted
            }
            input = candidate
            sessionId = requested
            state(phase: "listening", duration: 0, meter: nil)
        } catch {
            retireProtectedOutput(sessionId: requested)
            candidate.stop()
            let failure = (error as? CaptureFailure) ??
                (error is UtteranceStoreError ? .fileFailed : .startFailed)
            publish(kind: "error", phase: "off", error: failure.rawValue)
            throw failure
        }
    }

    func stop(sessionId requested: String) throws {
        assertOwner()
        if sessionId == requested { invalidateConversationStop() }
        retireProtectedOutput(sessionId: requested)
        guard sessionId == requested else { return }
        cancelRecovery()
        cancelTailDeadline?(); cancelTailDeadline = nil
        tailRequests = nil
        pendingSubmissions.removeAll()
        onsetResult = nil
        // Fence before producer teardown. Queued ticks cannot consume afterwards.
        backgroundPolicy.revoke()
        sessionId = nil
        let stopped = input
        input = nil
        stopped?.stop()
        segmenter.reset()
        playbackActive = false
        state(phase: "off", duration: 0, meter: nil)
        do { try store.stop(sessionId: requested) }
        catch { throw CaptureFailure.fileFailed }
    }

    func registerSubmittedUpload(sessionId requested: String, utteranceId: String, uploadId: String) -> Bool {
        assertOwner()
        let key = LeaseKey(sessionId: requested, utteranceId: utteranceId)
        guard readerLeases.contains(key), !invalidatedReaderLeases.contains(key) else { return false }
        return register(sessionId: requested, submissionId: uploadId, kind: .upload(key))
    }

    func registerSubmittedTurn(sessionId requested: String, ticket: String, submissionId: String, kind: String) -> Bool {
        assertOwner()
        guard protectedOutput?.ticket == ticket, kind == "text" || kind == "image" else { return false }
        return register(sessionId: requested, submissionId: submissionId, kind: .explicit(kind))
    }

    private func register(sessionId requested: String, submissionId: String, kind: SubmittedKind) -> Bool {
        guard !connectionPaused, sessionId == requested, input != nil, replyControlsAuthorized,
              Self.validID(submissionId), let output = protectedOutput,
              output.sessionId == requested, outputIsOpen(requested, output.ticket) else { return false }
        if let existing = pendingSubmissions[submissionId] { return existing == kind }
        guard pendingSubmissions.count < 2 else { return false }
        if case .upload = kind, pendingSubmissions.values.contains(kind) { return false }
        guard registerSubmission(requested, output.ticket, submissionId) else { return false }
        pendingSubmissions[submissionId] = kind
        return true
    }

    func stopListening(sessionId requested: String, permit: ReplyTailPermit) throws {
        assertOwner()
        if sessionId == requested, connectionPaused { try stop(sessionId: requested); return }
        guard sessionId == requested, input != nil else {
            if tailRequests == nil { try stop(sessionId: requested) }
            return
        }
        guard replyControlsAuthorized, let output = protectedOutput, output.sessionId == requested,
              permit.requestIds.count <= 3, permit.pendingUploadIds.count <= 2,
              let canonicalRequests = sealReplyTail(requested, output.ticket, permit.requestIds, permit.pendingUploadIds),
              outputIsOpen(requested, output.ticket) else {
            try stop(sessionId: requested)
            return
        }
        tailRequests = Set(canonicalRequests)
        pendingSubmissions = pendingSubmissions.filter { permit.pendingUploadIds.contains($0.key) }
        // Output safety and command ownership already exist before input removal.
        // No idle-gap inference and no capture polling timer powers this deadline.
        cancelTailDeadline = scheduleTailDeadline(900) { [weak self] in
            self?.endForOutputSystemEvent(.replyTailTimeout, sessionId: requested, ticket: output.ticket)
        }
        let stopped = input; input = nil
        stopped?.stop()
        segmenter.reset(); playbackActive = false; onsetResult = nil
        do { try store.stop(sessionId: requested) }
        catch { endForSystemEvent(.fileFailed); throw CaptureFailure.fileFailed }
        state(phase: "off", duration: 0, meter: nil)
    }

    func admitReplyForUpload(sessionId requested: String, ticket: String, uploadId: String, requestId: String) -> Bool {
        assertOwner()
        guard !connectionPaused, sessionId == requested, protectedOutput?.ticket == ticket,
              admitReply(requested, ticket, uploadId, requestId) else { return false }
        pendingSubmissions.removeValue(forKey: uploadId)
        tailRequests?.insert(requestId)
        return true
    }

    func abandonSubmittedUpload(sessionId requested: String, ticket: String, uploadId: String) {
        assertOwner()
        guard sessionId == requested, protectedOutput?.ticket == ticket,
              pendingSubmissions.removeValue(forKey: uploadId) != nil else { return }
        abandonSubmission(requested, ticket, uploadId)
    }

    func finishReplyOutput(sessionId requested: String, ticket: String, completedRequestIds: [String]) throws {
        assertOwner()
        guard sessionId == requested, protectedOutput?.ticket == ticket, let requests = tailRequests,
              completedRequestIds.count <= 3, Set(completedRequestIds).count == completedRequestIds.count,
              Set(completedRequestIds) == requests, pendingSubmissions.isEmpty,
              finishReplyTail(requested, ticket, completedRequestIds) else { throw CaptureFailure.replyTailUnavailable }
        try stop(sessionId: requested)
    }

    func endForOutputSystemEvent(_ reason: CaptureFailure, sessionId requested: String, ticket: String) {
        assertOwner()
        guard sessionId == requested, protectedOutput?.ticket == ticket else { return }
        endForSystemEvent(reason)
    }

    func setPlaybackActive(sessionId requested: String, active: Bool) {
        assertOwner()
        guard sessionId == requested, !connectionPaused else { return }
        playbackActive = active
    }

    func acquire(sessionId: String, utteranceId: String) throws -> OwnedClip {
        assertOwner()
        do {
            let clip = try store.acquire(sessionId: sessionId, utteranceId: utteranceId)
            readerLeases.insert(LeaseKey(sessionId: sessionId, utteranceId: utteranceId))
            return clip
        }
        catch { throw CaptureFailure.fileFailed }
    }

    func release(sessionId: String, utteranceId: String) throws {
        assertOwner()
        // Store.release revokes a valid lease before attempting deletion, even
        // on file failure. Do not accumulate retired keys across failed unlinks.
        defer {
            let key = LeaseKey(sessionId: sessionId, utteranceId: utteranceId)
            readerLeases.remove(key); invalidatedReaderLeases.remove(key)
        }
        do {
            try store.release(sessionId: sessionId, utteranceId: utteranceId)
        }
        catch { throw CaptureFailure.releaseFailed }
    }

    func acknowledgeState(sessionId: String, sequence: Int) {
        assertOwner()
        guard eventSession == sessionId, outstandingState == sequence else { return }
        outstandingState = nil
        flushState()
    }

    func process() {
        assertOwner()
        guard let source = input, let session = sessionId else { return }
        do {
            if connectionPaused {
                // The authorized input stays running, but no offline audio enters
                // the detector or private file store. Overflow here is discarded.
                try source.discardBufferedAudio()
                return
            }
            try checkOverflow(source)
            try source.drain { samples in
                try checkOverflow(source)
                guard samples.count <= 1600 else { throw CaptureFailure.unsupportedFormat }
                let events = segmenter.consume(samples, playbackActive: playbackActive)
                for event in events {
                    try checkOverflow(source)
                    switch event {
                    case let .onset(id):
                        let result: CaptureReplyOnset
                        if let output = protectedOutput {
                            result = freezeReplyOnset(session, output.ticket, UUID().uuidString)
                            // System Stop may retire output during freeze, before JS.
                            guard outputIsOpen(session, output.ticket) else { throw CaptureFailure.interrupted }
                        } else { result = .none }
                        onsetResult = (String(id), result)
                        publish(kind: "onset", phase: "speech", utteranceId: String(id),
                            duration: segmenter.durationMs, meter: segmenter.meteringDb)
                    case let .completed(id, pcm):
                        let clip: OwnedClip
                        do { clip = try store.write(sessionId: session, utteranceId: String(id), samples: pcm) }
                        catch UtteranceStoreError.backlogFull { throw CaptureFailure.backlogFull }
                        catch { throw CaptureFailure.fileFailed }
                        // File I/O can let the producer overflow concurrently. Do
                        // not expose this clip if continuity was lost during export.
                        try checkOverflow(source)
                        publish(kind: "utterance", phase: segmenter.phase,
                            utteranceId: clip.utteranceId, duration: clip.durationMs,
                            meter: segmenter.meteringDb)
                        onsetResult = nil
                    }
                }
            }
            try checkOverflow(source)
            state(phase: segmenter.phase, duration: segmenter.durationMs, meter: segmenter.meteringDb)
        } catch {
            endForSystemEvent((error as? CaptureFailure) ?? .unsupportedFormat)
        }
    }

    func pauseConnection(sessionId requested: String, ticket: String, recoveryEpoch epoch: Int) -> Bool {
        assertOwner()
        guard ownsRecovery(sessionId: requested, ticket: ticket), epoch > 0 else { return false }
        if epoch == recoveryEpoch { return connectionPaused }
        guard epoch > recoveryEpoch, pauseOutputConnection(requested, ticket, epoch) else { return false }
        cancelRecovery()
        recoveryEpoch = epoch; connectionPaused = true
        segmenter.reset(); onsetResult = nil; playbackActive = false
        pendingSubmissions.removeAll(); pendingState = nil
        invalidatedReaderLeases.formUnion(readerLeases)
        do {
            try input?.discardBufferedAudio()
            // Retire completed-but-unconsumed clips too; existing reader leases
            // stay pinned for safe release, but cannot register old submissions.
            try store.stop(sessionId: requested)
            pingConnection(sessionId: requested, ticket: ticket, epoch: epoch)
            return connectionPaused && isCapturing
        } catch { endForSystemEvent((error as? CaptureFailure) ?? .fileFailed); return false }
    }

    func resumeConnection(sessionId requested: String, ticket: String, recoveryEpoch epoch: Int,
                          completion: @escaping (Bool) -> Void) {
        assertOwner()
        guard ownsRecovery(sessionId: requested, ticket: ticket), connectionPaused,
              recoveryEpoch == epoch, recoveryCompletion == nil else { completion(false); return }
        cancelConnectionRecovery?(); cancelConnectionRecovery = nil
        recoveryCompletion = completion
        do {
            let duration = try input!.playConnectionCue(sessionId: requested, ticket: ticket, recoveryEpoch: epoch, recovered: true)
            // A bounded acoustic tail prevents the cue itself becoming speech.
            cancelConnectionRecovery = scheduleConnectionRecovery(min(1, max(0, duration)) + 0.25) { [weak self] in
                guard let self else { return }
                self.completeConnectionRecovery(sessionId: requested, ticket: ticket, epoch: epoch, deadline: self.clock() + 1)
            }
        } catch { endForSystemEvent(.interrupted) }
    }

    private func completeConnectionRecovery(sessionId requested: String, ticket: String, epoch: Int, deadline: TimeInterval) {
        guard ownsRecovery(sessionId: requested, ticket: ticket), connectionPaused,
              recoveryEpoch == epoch, recoveryCompletion != nil else { return }
        guard clock() < deadline else { endForSystemEvent(.interrupted); return }
        do {
            // Wait for a producer-side boundary as well as draining the consumer:
            // an already-running tap may otherwise publish offline audio afterward.
            guard try input!.finishConnectionResume() else {
                cancelConnectionRecovery = scheduleConnectionRecovery(0.02) { [weak self] in
                    self?.completeConnectionRecovery(sessionId: requested, ticket: ticket, epoch: epoch, deadline: deadline)
                }
                return
            }
            segmenter.reset(); onsetResult = nil
            guard resumeOutputConnection(requested, ticket, epoch) else { endForSystemEvent(.interrupted); return }
            connectionPaused = false
            cancelConnectionRecovery = nil
            let resolve = recoveryCompletion; recoveryCompletion = nil
            state(phase: "listening", duration: 0, meter: nil)
            resolve?(true)
        } catch { endForSystemEvent((error as? CaptureFailure) ?? .unsupportedFormat) }
    }

    private func ownsRecovery(sessionId requested: String, ticket: String) -> Bool {
        !closed && sessionId == requested && input != nil && replyControlsAuthorized &&
            protectedOutput?.ticket == ticket && outputIsOpen(requested, ticket)
    }

    private func pingConnection(sessionId requested: String, ticket: String, epoch: Int) {
        guard ownsRecovery(sessionId: requested, ticket: ticket), connectionPaused,
              recoveryEpoch == epoch, recoveryCompletion == nil else { return }
        do {
            _ = try input!.playConnectionCue(sessionId: requested, ticket: ticket, recoveryEpoch: epoch, recovered: false)
            cancelConnectionRecovery = scheduleConnectionRecovery(5) { [weak self] in
                self?.pingConnection(sessionId: requested, ticket: ticket, epoch: epoch)
            }
        } catch { endForSystemEvent(.interrupted) }
    }

    private func cancelRecovery() {
        cancelConnectionRecovery?(); cancelConnectionRecovery = nil
        connectionPaused = false
        let resolve = recoveryCompletion; recoveryCompletion = nil
        resolve?(false)
    }

    // A notification from an old detached driver must not stop a newer driver.
    func endForSystemEvent(_ reason: CaptureFailure, source: CaptureInput? = nil) {
        assertOwner()
        if let source, input !== source { return }
        guard let current = sessionId else { return }
        do { try stop(sessionId: current) }
        catch {
            // The original capture failure remains actionable; cleanup failures
            // keep their files/quota in the persistent store for subsequent retry.
        }
        publish(kind: "error", phase: "off", error: reason.rawValue)
    }

    func shutdown() {
        assertOwner()
        if let output = protectedOutput { retireProtectedOutput(sessionId: output.sessionId) }
        if let current = sessionId { try? stop(sessionId: current) }
        closed = true
        pendingState = nil
        outstandingState = nil
    }

    // ONLY the bridge's OnAppContextDestroys calls this after shutdown. Pinned
    // Expo SDK54 synchronous file reads retain that context until completion;
    // ordinary ModuleHolder OnDestroy is not sufficient proof of reader death.
    func retireReaderLeases() {
        assertOwner()
        precondition(closed)
        for key in readerLeases {
            // Store.release revokes its process pin before deletion. If unlink
            // fails, the file still consumes disk quota and is stale-cleanable.
            try? store.release(sessionId: key.sessionId, utteranceId: key.utteranceId)
        }
        readerLeases.removeAll()
        invalidatedReaderLeases.removeAll()
    }

    private func checkOverflow(_ source: CaptureInput) throws {
        if source.takeOverflow() { throw CaptureFailure.captureOverflow }
    }

    private func state(phase: String, duration: Double, meter: Double?) {
        pendingState = (phase, duration, meter)
        flushState()
    }

    private func flushState() {
        guard !closed, outstandingState == nil, let latest = pendingState else { return }
        let delay = 0.1 - (clock() - lastStateTime)
        if delay > 0 {
            if !stateFlushScheduled {
                stateFlushScheduled = true
                queue.asyncAfter(deadline: .now() + delay) { [weak self] in
                    guard let self else { return }
                    self.stateFlushScheduled = false
                    self.flushState()
                }
            }
            return
        }
        pendingState = nil
        lastStateTime = clock()
        // Assign only at actual emission; an onset/completion may have occurred
        // while this latest snapshot was waiting for an acknowledgement.
        outstandingState = sequence + 1
        publish(kind: "state", phase: latest.phase, duration: latest.duration, meter: latest.meter)
    }

    private func publish(kind: String, phase: String, utteranceId: String? = nil,
                         duration: Double = 0, meter: Double? = nil, error: String? = nil) {
        guard let session = eventSession, !closed else { return }
        sequence += 1
        emit(CaptureNotification(sessionId: session, sequence: sequence, kind: kind,
            phase: phase, utteranceId: utteranceId, durationMs: duration, meteringDb: meter, error: error,
            backgroundAuthorized: foregroundOnly ? false : (backgroundWasRequested ? backgroundPolicy.armed : nil),
            lifetime: lifetime, phoneReplyReceipt: receiptForEvent(utteranceId),
            phoneReplyUnavailable: unavailableForEvent(utteranceId)))
    }

    private func receiptForEvent(_ id: String?) -> CaptureReplyReceipt? {
        guard let id, let onset = onsetResult, onset.utteranceId == id,
              case let .receipt(receipt) = onset.result else { return nil }
        return receipt
    }
    private func unavailableForEvent(_ id: String?) -> Bool {
        guard let id, let onset = onsetResult, onset.utteranceId == id else { return false }
        if case .unavailable = onset.result { return true }
        return false
    }

    private func assertOwner() { dispatchPrecondition(condition: .onQueue(queue)) }

    private static func validID(_ id: String) -> Bool {
        let bytes = id.utf8
        return !bytes.isEmpty && bytes.count <= 128 && bytes.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45 || $0 == 95
        }
    }
}
