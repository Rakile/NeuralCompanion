// NeuralCompanion maintained extension to expo-audio; MIT licensed.
import Foundation

/// Memory-only IDs from one output ticket. No text, credentials or media URLs.
public struct NCPhoneReplyReceipt: Equatable {
  public let phoneRequestId: String
  public let interruptionId: String
  public let startedChunkIds: [String]
  public var payload: [String: Any] {
    ["phone_request_id": phoneRequestId, "interruption_id": interruptionId, "started_chunk_ids": startedChunkIds]
  }
}

public enum NCPhoneReplyOnsetResult: Equatable {
  case none
  case unavailable
  case receipt(NCPhoneReplyReceipt)
}
public struct NCReplyCheckpoint {
  public let requestId: String
  public let completedChunkIds: [String]
  public let activeChunkId: String?
  public let positionSeconds: Double?
  public var payload: [String: Any] {
    ["requestId": requestId, "completedChunkIds": completedChunkIds,
     "activeChunkId": activeChunkId as Any? ?? NSNull(), "positionSeconds": positionSeconds as Any? ?? NSNull()]
  }
}
public struct NCReplyContinuation {
  public let recoveryEpoch: Int
  public let replies: [NCReplyCheckpoint]
  public var payload: [String: Any] { ["recoveryEpoch": recoveryEpoch, "replies": replies.map { $0.payload }] }
}

/// One ordering boundary for output ownership and actual native output operations.
/// Actions must never wait on main/capture queues or publish JS/status callbacks.
public final class NCPlaybackGuard {
  public enum RetirementCause: String {
    case other, explicit, interruption
    case mediaReset = "media_reset", foregroundLeft = "foreground_left", permissionRevoked = "permission_revoked"
    case routeSetupSame = "route_setup_same", routeSetupDifferent = "route_setup_different"
    case routeOtherSame = "route_other_same", routeOtherDifferent = "route_other_different"
  }
  public static let shared = NCPlaybackGuard()
  public static let version = 1
  public static let phoneReplyReceiptVersion = 1
  public static let connectionRecoveryVersion = 1
  private let lock = NSRecursiveLock()
  // Lock order is mediaPublicationLock -> output lock. Metadata is never published
  // while holding the output lock; protected begin cannot overtake final publication.
  private let mediaPublicationLock = NSRecursiveLock()
  private let outputThreadKey = "NCPlaybackGuard.output." + UUID().uuidString
  private let conversationMediaThreadKey = "NCPlaybackGuard.conversationMedia." + UUID().uuidString
  // One bounded last-publication marker, independent of issued/retired tickets.
  // Reply UUIDs never grant output/capture permission or identify playback tickets.
  private enum MediaPublicationOwner: Equatable { case conversation(String), reply(UUID) }
  private var mediaPublicationOwner: MediaPublicationOwner?
  private var depth = 0
  private var ticket: String?
  private var sessionId: String?
  private var open = false
  private var connectionPaused = false
  private var recoveryEpoch = 0
  private var stopConnectionCue: (() -> Void)?
  private var continuation: NCReplyContinuation?
  private var continuationApproved = false
  private var retirementCause = "none"
  private enum ProtectedPhase { case negotiating, sealed, armed }
  private var protectedPhase: ProtectedPhase?
  // Fixed when issuing a ticket; arming can never upgrade background permission.
  private var foregroundOnly = false
  private var sealedRouteKey: String?
  private var records: [WeakBinding] = []
  // Retain across inter-chunk gaps/disposal. Never evict and reopen an old request.
  // Exhaustion fails admission until this listening/output ticket is retired.
  private var phoneReplies: [String: PhoneReply] = [:]
  private var lastAcknowledgedPhoneRequestId: String?
  // Native capture validates each submission before entering this guard. ACKs
  // grant admission, never delivery evidence. One current reply plus two turns.
  private var submittedRequests: Set<String> = []
  private var pendingReplySubmissions: Set<String> = []
  private var issuedReplySubmissions: Set<String> = []
  private var acknowledgedReplySubmissions: [String: String] = [:]
  private var replyTailRequests: Set<String>?
  private final class PhoneReply {
    var started: [String] = []
    var seen: Set<String> = []
    var completed: [String] = []
    var interruptedChunk: String?
    var interruptedPosition: Double?
    var closed = false
    var unavailable = false
    var frozen: NCPhoneReplyReceipt?
  }
  private var pendingRetirements: [[String: String]] = []
  private struct WeakBinding { weak var value: NCPlaybackBinding? }
  enum Failure: Error { case foregroundRequired, staleTicket, retirementRequired, emptySession, reentrantOwnershipChange }

  // Internal construction supports Foundation tests; production uses shared only.
  init() {}
  public var currentTicket: String? { synchronized { ticket } }
  public var lastRetirementCause: String { synchronized { retirementCause } }
  public func routeChangeCause(isSetupChange: Bool, routeKey: String) -> RetirementCause {
    synchronized {
      if isSetupChange { return sealedRouteKey == routeKey ? .routeSetupSame : .routeSetupDifferent }
      return sealedRouteKey == routeKey ? .routeOtherSame : .routeOtherDifferent
    }
  }
  var canUseMediaControls: Bool { synchronized { !protectedOpen } }
  public func ticketIsOpen(_ ticket: String) -> Bool { synchronized { self.ticket == ticket && open } }
  public func protectedSessionId(for ticket: String) -> String? {
    synchronized { self.ticket == ticket && open ? sessionId : nil }
  }
  public func beginProtected(sessionId: String, expectedTicket: String?, foreground: Bool, foregroundOnly: Bool = false) throws -> String {
    guard canEnterMedia else { throw Failure.reentrantOwnershipChange }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    return try synchronized {
      guard foreground else { throw Failure.foregroundRequired }
      guard !sessionId.isEmpty else { throw Failure.emptySession }
      guard ticket == expectedTicket else { throw Failure.staleTicket }
      guard !open || self.sessionId == nil else { throw Failure.retirementRequired }
      closeCurrent()
      return issue(sessionId: sessionId, foregroundOnly: foregroundOnly)
    }
  }
  public func beginForeground(expectedTicket: String?, foreground: Bool) throws -> String {
    guard canEnterMedia else { throw Failure.reentrantOwnershipChange }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    return try synchronized {
      guard foreground else { throw Failure.foregroundRequired }
      guard ticket == expectedTicket else { throw Failure.staleTicket }
      guard !open else { throw Failure.retirementRequired }
      return issue(sessionId: nil)
    }
  }
  public func retire(ticket: String, cause: RetirementCause = .explicit) {
    synchronized { if self.ticket == ticket { closeCurrent(cause: cause) } }
  }
  public func pauseConnection(ticket: String, sessionId: String, recoveryEpoch: Int) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open,
            protectedPhase == .armed, replyTailRequests == nil, recoveryEpoch > 0 else { return false }
      if recoveryEpoch == self.recoveryEpoch { return connectionPaused }
      guard recoveryEpoch > self.recoveryEpoch else { return false }
      self.recoveryEpoch = recoveryEpoch
      connectionPaused = true
      stopConnectionCue?(); stopConnectionCue = nil
      pendingReplySubmissions.removeAll()
      acknowledgedReplySubmissions.removeAll()
      submittedRequests.removeAll()
      lastAcknowledgedPhoneRequestId = nil
      // Keep bounded tombstones: neither late admission nor old chunks/receipts
      // can become valid again when the same capture ticket resumes.
      for reply in phoneReplies.values {
        reply.closed = true; reply.unavailable = true; reply.frozen = nil
      }
      let players = records.compactMap(\.value).filter { $0.ticket == ticket }
      for player in players { player.terminal = true }
      records.removeAll()
      for player in players { player.actions?.ncPause() }
      return true
    }
  }
  public func pauseReplyContinuation(ticket: String, sessionId: String, recoveryEpoch: Int) -> NCReplyContinuation? {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open, protectedPhase == .armed,
            replyTailRequests == nil, recoveryEpoch > 0, recoveryEpoch >= self.recoveryEpoch else { return nil }
      if recoveryEpoch == self.recoveryEpoch { return connectionPaused ? continuation : nil }
      let players = records.compactMap(\.value).filter { $0.ticket == ticket && !$0.terminal }
      // Freeze ownership before pausing AVPlayer; callbacks cannot advance evidence.
      self.recoveryEpoch = recoveryEpoch; connectionPaused = true; continuationApproved = false
      stopConnectionCue?(); stopConnectionCue = nil
      for player in players {
        if player.phoneStartAcknowledged, let id = player.phoneRequestId, let reply = phoneReplies[id],
           let chunk = player.phoneChunkId, !reply.completed.contains(chunk),
           player.phoneItemIdentity == player.actions?.ncCurrentItemIdentity {
          player.actions?.ncPause()
          let position = player.actions?.ncPositionSeconds
          reply.interruptedChunk = chunk
          reply.interruptedPosition = position.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        }
        player.terminal = true
      }
      let snapshots = knownOpenRequests.sorted().compactMap { id -> NCReplyCheckpoint? in
        guard let reply = phoneReplies[id], !reply.closed else { return nil }
        let chunk = reply.interruptedChunk.flatMap { reply.completed.contains($0) ? nil : $0 }
          ?? reply.started.last(where: { !reply.completed.contains($0) })
        return NCReplyCheckpoint(requestId: id, completedChunkIds: reply.completed,
          activeChunkId: chunk, positionSeconds: chunk == reply.interruptedChunk ? reply.interruptedPosition : nil)
      }
      continuation = NCReplyContinuation(recoveryEpoch: recoveryEpoch, replies: snapshots)
      pendingReplySubmissions.removeAll(); acknowledgedReplySubmissions.removeAll(); records.removeAll()
      for player in players { player.actions?.ncPause() }
      return continuation
    }
  }
  public func prepareReplyContinuation(ticket: String, sessionId: String, recoveryEpoch: Int, requestIds: [String]) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open, connectionPaused,
            self.recoveryEpoch == recoveryEpoch, let continuation, requestIds.count <= 3,
            Set(requestIds).count == requestIds.count,
            requestIds.allSatisfy({ id in continuation.replies.contains { $0.requestId == id } && phoneReplies[id]?.closed == false }) else { return false }
      for reply in continuation.replies where !requestIds.contains(reply.requestId) { closePhoneReply(reply.requestId) }
      continuationApproved = true
      return true
    }
  }
  public func resumeConnection(ticket: String, sessionId: String, recoveryEpoch: Int) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open,
            connectionPaused, self.recoveryEpoch == recoveryEpoch,
            continuation == nil || continuationApproved else { return false }
      stopConnectionCue?(); stopConnectionCue = nil
      connectionPaused = false
      continuation = nil; continuationApproved = false
      return true
    }
  }
  /// Native cue output shares the same Stop ordering boundary as protected audio.
  /// Effects touch only the local player and never wait on another queue.
  public func performConnectionCue(ticket: String, sessionId: String, recoveryEpoch: Int,
      stop: @escaping () -> Void, play: () -> Bool) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open,
            connectionPaused, self.recoveryEpoch == recoveryEpoch else { return false }
      stopConnectionCue?()
      stopConnectionCue = stop
      let started = play()
      guard self.ticket == ticket, self.sessionId == sessionId, open,
            connectionPaused, self.recoveryEpoch == recoveryEpoch else { stop(); return false }
      return started
    }
  }
  private func replyScopeIsOpen(ticket: String, sessionId: String) -> Bool {
    self.ticket == ticket && self.sessionId == sessionId && open && !connectionPaused && protectedPhase == .armed
  }
  private var knownOpenRequests: Set<String> {
    var result = submittedRequests.filter { phoneReplies[$0]?.closed == false }
    if let current = lastAcknowledgedPhoneRequestId, phoneReplies[current]?.closed == false { result.insert(current) }
    return result
  }
  public func registerReplySubmission(ticket: String, sessionId: String, uploadId: String) -> Bool {
    synchronized {
      guard replyScopeIsOpen(ticket: ticket, sessionId: sessionId), replyTailRequests == nil,
            validPhoneId(uploadId) else { return false }
      if pendingReplySubmissions.contains(uploadId) { return true }
      guard !issuedReplySubmissions.contains(uploadId), issuedReplySubmissions.count < 256,
            pendingReplySubmissions.count < 2, knownOpenRequests.count + pendingReplySubmissions.count < 3 else { return false }
      issuedReplySubmissions.insert(uploadId)
      pendingReplySubmissions.insert(uploadId)
      return true
    }
  }
  public func sealReplyTail(ticket: String, sessionId: String, requestIds: [String], pendingUploadIds: [String]) -> [String]? {
    synchronized {
      guard replyScopeIsOpen(ticket: ticket, sessionId: sessionId), replyTailRequests == nil,
            requestIds.count <= 3, pendingUploadIds.count <= 2,
            requestIds.count + pendingUploadIds.count <= 3,
            Set(requestIds).count == requestIds.count, Set(pendingUploadIds).count == pendingUploadIds.count,
            !requestIds.isEmpty || !pendingUploadIds.isEmpty else { return nil }
      var canonicalRequests = Set(requestIds)
      for upload in pendingUploadIds where !pendingReplySubmissions.contains(upload) {
        guard let request = acknowledgedReplySubmissions[upload], phoneReplies[request]?.closed == false else { return nil }
        canonicalRequests.insert(request)
      }
      let retainedPending = pendingReplySubmissions.intersection(Set(pendingUploadIds))
      guard canonicalRequests == knownOpenRequests, canonicalRequests.count + retainedPending.count <= 3 else { return nil }
      // Omitted reservations never reached HTTP dispatch. Their IDs stay issued
      // (cannot be reused), but neither late ACK nor registration can admit them.
      pendingReplySubmissions = retainedPending
      replyTailRequests = canonicalRequests
      // Seal before pausing any excluded prepared player: reentrant callbacks
      // must see the new admission boundary. Ticket-only players cannot play.
      let excluded = records.compactMap(\.value).filter {
        $0.ticket == ticket && ($0.phoneRequestId == nil || !canonicalRequests.contains($0.phoneRequestId!))
      }
      for player in excluded { player.terminal = true }
      for player in excluded { player.actions?.ncPause() }
      return canonicalRequests.sorted()
    }
  }
  public func admitReplyForUpload(ticket: String, sessionId: String, uploadId: String, requestId: String) -> Bool {
    synchronized {
      guard replyScopeIsOpen(ticket: ticket, sessionId: sessionId), validPhoneId(requestId),
            phoneReplies[requestId]?.closed != true else { return false }
      if let acknowledged = acknowledgedReplySubmissions[uploadId] { return acknowledged == requestId }
      guard pendingReplySubmissions.contains(uploadId) else { return false }
      if phoneReplies[requestId] == nil {
        guard phoneReplies.count < 256 else { return false }
        phoneReplies[requestId] = PhoneReply()
      }
      pendingReplySubmissions.remove(uploadId)
      acknowledgedReplySubmissions[uploadId] = requestId
      submittedRequests.insert(requestId)
      if replyTailRequests != nil { replyTailRequests?.insert(requestId) }
      return true
    }
  }
  public func abandonSubmittedUpload(ticket: String, sessionId: String, uploadId: String) {
    synchronized {
      guard replyScopeIsOpen(ticket: ticket, sessionId: sessionId) else { return }
      pendingReplySubmissions.remove(uploadId)
    }
  }
  public func finishReplyTail(ticket: String, sessionId: String, completedRequestIds: [String]) -> Bool {
    synchronized {
      guard replyScopeIsOpen(ticket: ticket, sessionId: sessionId), let admitted = replyTailRequests,
            completedRequestIds.count <= 3, Set(completedRequestIds).count == completedRequestIds.count,
            Set(completedRequestIds) == admitted, pendingReplySubmissions.isEmpty else { return false }
      guard !records.contains(where: { record in
        guard let player = record.value, player.ticket == ticket, let actions = player.actions else { return false }
        return !player.terminal || actions.ncIsPlaying
      }) else { return false }
      closeCurrent()
      return true
    }
  }
  /// Capture worker -> output only. No main, status, media or capture callbacks.
  /// Acknowledged current ownership survives gaps/disposal until explicit finish
  /// or closure. A reply that has never acknowledged a start returns none.
  /// A repeat onset keeps its immutable result even after the player was disposed.
  public func freezeCurrentPhoneReplyReceipt(ticket: String, sessionId: String,
      interruptionId: String) -> NCPhoneReplyOnsetResult {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open, !connectionPaused,
            validPhoneId(interruptionId) else { return .unavailable }
      if let frozen = phoneReplies.values.compactMap({ $0.frozen }).first(where: { $0.interruptionId == interruptionId }) {
        return .receipt(frozen)
      }
      var requests = Set(records.compactMap { record -> String? in
        guard let player = record.value, eligible(player), player.phoneStartAcknowledged,
              player.actions?.ncIsPlaying == true else { return nil }
        return player.phoneRequestId
      })
      // Player disposal is not producer completion. Keep the latest acknowledged
      // request through a chunk gap until the trusted completion/drain handoff.
      if let requestId = lastAcknowledgedPhoneRequestId, let reply = phoneReplies[requestId],
          !reply.closed, !reply.started.isEmpty {
        requests.insert(requestId)
      }
      guard !requests.isEmpty else {
        if let requestId = lastAcknowledgedPhoneRequestId, phoneReplies[requestId]?.unavailable == true { return .unavailable }
        return .none
      }
      // The existing queue has one active reply. Ambiguous native ownership is
      // unavailable; close its candidates rather than invent a delivered prefix.
      guard requests.count == 1, let requestId = requests.first else {
        for requestId in requests { closePhoneReply(requestId, unavailable: true) }
        return .unavailable
      }
      guard let receipt = freezePhoneReplyReceipt(ticket: ticket, requestId: requestId, interruptionId: interruptionId) else {
        return .unavailable
      }
      return .receipt(receipt)
    }
  }
  public func freezePhoneReplyReceipt(ticket: String, requestId: String,
      interruptionId: String) -> NCPhoneReplyReceipt? {
    synchronized {
      guard self.ticket == ticket, open, !connectionPaused, validPhoneId(interruptionId),
            let reply = phoneReplies[requestId], !reply.unavailable else { return nil }
      if let frozen = reply.frozen { return frozen.interruptionId == interruptionId ? frozen : nil }
      guard !reply.closed,
            !phoneReplies.values.contains(where: { $0.frozen?.interruptionId == interruptionId }) else { return nil }
      let frozen = NCPhoneReplyReceipt(phoneRequestId: requestId, interruptionId: interruptionId, startedChunkIds: reply.started)
      reply.frozen = frozen
      closePhoneReply(requestId)
      return frozen
    }
  }
  /// Audio-only Skip also closes a request whose first chunk has not arrived.
  /// It never creates a receipt and never retires the surrounding listening ticket.
  public func skipPhoneReplyAudio(ticket: String, requestId: String) -> Bool {
    synchronized {
      guard self.ticket == ticket, open, validPhoneId(requestId) else { return false }
      if phoneReplies[requestId] == nil {
        guard phoneReplies.count < 256 else { return false }
        phoneReplies[requestId] = PhoneReply()
      }
      closePhoneReply(requestId)
      if lastAcknowledgedPhoneRequestId == requestId { lastAcknowledgedPhoneRequestId = nil }
      return true
    }
  }
  /// Caller must have explicit producer completion AND a drained request queue.
  /// Native disposal is required: paused/buffering/prepared bindings are not drain.
  /// Retain the request tombstone/prefix/frozen receipt until ticket retirement.
  public func finishPhoneReplyAudio(ticket: String, requestId: String) -> Bool {
    synchronized {
      guard self.ticket == ticket, open, validPhoneId(requestId), phoneReplies[requestId] != nil else { return false }
      let hasOwnedOutput = records.contains { record in
        guard let player = record.value, player.ticket == ticket, player.phoneRequestId == requestId,
              let actions = player.actions else { return false }
        return !player.terminal || actions.ncIsPlaying
      }
      guard !hasOwnedOutput else { return false }
      closePhoneReply(requestId)
      if lastAcknowledgedPhoneRequestId == requestId { lastAcknowledgedPhoneRequestId = nil }
      return true
    }
  }
  private func validPhoneId(_ value: String) -> Bool { !value.isEmpty && value.unicodeScalars.count <= 128 }
  private func closePhoneReply(_ requestId: String, unavailable: Bool = false) {
    guard let reply = phoneReplies[requestId] else { return }
    reply.closed = true
    submittedRequests.remove(requestId)
    acknowledgedReplySubmissions = acknowledgedReplySubmissions.filter { $0.value != requestId }
    reply.unavailable = reply.unavailable || unavailable
    if !reply.unavailable && lastAcknowledgedPhoneRequestId == requestId { lastAcknowledgedPhoneRequestId = nil }
    // Close every active/prepared identity before the first pause can call KVO.
    let players = records.compactMap(\.value).filter { $0.ticket == ticket && $0.phoneRequestId == requestId && !$0.terminal }
    for player in players { player.terminal = true }
    for player in players { player.actions?.ncPause() }
  }
  func retireProtected(cause: RetirementCause = .other) { synchronized { if sessionId != nil { closeCurrent(cause: cause) } } }
  // Begin has already read real UIKit foreground state on main. Native resign
  // closes unarmed AND foreground-only ownership immediately, including tails.
  // Returning active never reopens either kind of retired ownership.
  public func retireUnarmedProtected() {
    synchronized { if protectedOpen && (foregroundOnly || protectedPhase != .armed) { closeCurrent(cause: .foregroundLeft) } }
  }
  private func backgroundRouteEligible(_ key: String) -> Bool {
    !key.isEmpty && !key.hasPrefix("foreground:")
  }
  /// Input teardown can reconfigure the session without changing its duplex route.
  /// This read-only, ticket-scoped exception cannot authorize capture or revive output.
  public func allowsReplyTailRouteChange(ticket: String, isSetupChange: Bool, routeKey: String) -> Bool {
    synchronized {
      self.ticket == ticket && protectedOpen && protectedPhase == .armed && replyTailRequests != nil
        && isSetupChange && sealedRouteKey == routeKey && (foregroundOnly || backgroundRouteEligible(routeKey))
    }
  }
  /// Setup notifications may arrive after input has armed. A nonempty exact
  /// duplex route and current ticket are required; this never reopens output.
  public func allowsArmedSetupRouteChange(ticket: String, isSetupChange: Bool, routeKey: String) -> Bool {
    synchronized {
      self.ticket == ticket && protectedOpen && protectedPhase == .armed
        && isSetupChange && !routeKey.isEmpty && sealedRouteKey == routeKey
    }
  }
  /// Called at the native notification boundary by both capture and Expo.
  /// No main/capture waits: current AV route is read before entering this lock.
  @discardableResult
  public func admitSetupRouteChange(isSetupChange: Bool, routeKey: String) -> Bool {
    synchronized {
      guard protectedOpen else { return false }
      if let ticket, (allowsArmedSetupRouteChange(ticket: ticket, isSetupChange: isSetupChange, routeKey: routeKey)
          || allowsReplyTailRouteChange(ticket: ticket, isSetupChange: isSetupChange, routeKey: routeKey)) {
        return true
      }
      if isSetupChange && (foregroundOnly || backgroundRouteEligible(routeKey)) &&
          (protectedPhase == .negotiating || (protectedPhase == .sealed && sealedRouteKey == routeKey)) {
        return true
      }
      closeCurrent(cause: routeChangeCause(isSetupChange: isSetupChange, routeKey: routeKey))
      return false
    }
  }
  /// Production capture Start boundary. Hardware work and fresh native snapshots
  /// run OUTSIDE both locks. A terminal event during Start cannot be sealed away.
  public func prepareProtectedInput(ticket: String, sessionId: String,
      snapshot: () -> (foreground: Bool, routeKey: String), start: () throws -> Void) throws {
    guard canEnterMedia else { throw Failure.reentrantOwnershipChange }
    do {
      let before = snapshot()
      try synchronized {
        guard self.ticket == ticket, self.sessionId == sessionId, open, protectedPhase == .negotiating,
              before.foreground, foregroundOnly || backgroundRouteEligible(before.routeKey) else { throw Failure.staleTicket }
      }
      try start()
      let settled = snapshot()
      try synchronized {
        guard self.ticket == ticket, self.sessionId == sessionId, open, protectedPhase == .negotiating,
              settled.foreground, foregroundOnly || backgroundRouteEligible(settled.routeKey) else { throw Failure.staleTicket }
        sealedRouteKey = settled.routeKey
        protectedPhase = .sealed
      }
    } catch {
      retire(ticket: ticket)
      throw error
    }
  }
  /// Capture calls only after its foreground/headphone/confirmation policy passes.
  /// Sealed ownership is open for binding, but has no playback authorization.
  public func armProtectedOutput(ticket: String, sessionId: String, foreground: Bool, routeKey: String) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open, !foregroundOnly else { return false }
      guard foreground, backgroundRouteEligible(routeKey), sealedRouteKey == routeKey,
            protectedPhase == .sealed || protectedPhase == .armed else { closeCurrent(); return false }
      protectedPhase = .armed
      return true
    }
  }
  /// Foreground input/output authorization only; speaker is not a background route.
  public func armForegroundProtectedOutput(ticket: String, sessionId: String, foreground: Bool, routeKey: String) -> Bool {
    synchronized {
      guard self.ticket == ticket, self.sessionId == sessionId, open, foregroundOnly else { return false }
      guard foreground, sealedRouteKey == routeKey,
            protectedPhase == .sealed || protectedPhase == .armed else { closeCurrent(); return false }
      protectedPhase = .armed
      return true
    }
  }
  func activateSession(players: [NCPlaybackBinding], hasRecorders: Bool, explicitPreparation: Bool = false, effect: () throws -> Void) rethrows {
    try synchronized {
      let hasUnmanagedUsers = players.contains { !$0.attemptedBinding && !$0.terminal }
      let hasCurrentPlayer = players.contains { $0.attemptedBinding && eligible($0) }
      guard ticket == nil || (explicitPreparation && open) || hasCurrentPlayer || hasUnmanagedUsers || hasRecorders else { return }
      try effect()
    }
  }
  @discardableResult
  func publishMedia(for player: NCPlaybackBinding?, claimsOwnership: Bool = true,
                    ifCurrent: () -> Bool = { true }, effect: () -> Void) -> Bool {
    // A synchronous AV callback must fail closed, never invert output -> media.
    guard canEnterMedia else { return false }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    let allowed = synchronized { !protectedOpen && (player.map { eligible($0) } ?? true) }
    guard allowed, ifCurrent() else { return false }
    if claimsOwnership { mediaPublicationOwner = nil }
    effect()
    return true
  }
  private var canEnterMedia: Bool {
    Thread.current.threadDictionary[outputThreadKey] == nil &&
      Thread.current.threadDictionary[conversationMediaThreadKey] == nil
  }
  /// Publish native NC metadata AND global command configuration in one effect.
  /// Effects must be synchronous native sink writes only: no waits, JS, output
  /// operations, or recursive ownership/publication calls. Output lock is released.
  @discardableResult
  public func publishConversationMedia(ticket: String, sessionId: String, effect: () -> Void) -> Bool {
    guard canEnterMedia else { return false }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    let allowed = synchronized { self.ticket == ticket && open && self.sessionId == sessionId }
    guard allowed else { return false }
    mediaPublicationOwner = .conversation(ticket)
    Thread.current.threadDictionary[conversationMediaThreadKey] = true
    defer { Thread.current.threadDictionary.removeObject(forKey: conversationMediaThreadKey) }
    effect()
    return true
  }
  /// Consume only the last NC publisher's cleanup right, even after a newer ticket
  /// was issued without publication. Always remove caller-owned tokens separately;
  /// restore global metadata/command state only inside this accepted native effect.
  @discardableResult
  public func clearConversationMedia(ticket: String, effect: () -> Void) -> Bool {
    clearMedia(owner: .conversation(ticket), effect: effect)
  }
  /// Reply-level controls share the same publication fence as Expo and Live.
  /// The UUID is a cleanup identity only; protected output always wins admission.
  /// Effects obey publishConversationMedia's synchronous native-sink-only contract.
  @discardableResult
  public func publishReplyMedia(owner: UUID, effect: () -> Void) -> Bool {
    publishMedia(for: nil, claimsOwnership: false) {
      mediaPublicationOwner = .reply(owner)
      Thread.current.threadDictionary[conversationMediaThreadKey] = true
      defer { Thread.current.threadDictionary.removeObject(forKey: conversationMediaThreadKey) }
      effect()
    }
  }
  public func replyMediaIsCurrent(owner: UUID) -> Bool {
    guard canEnterMedia else { return false }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    return mediaPublicationOwner == .reply(owner) && synchronized { !protectedOpen }
  }
  @discardableResult
  public func clearReplyMedia(owner: UUID, effect: () -> Void) -> Bool {
    clearMedia(owner: .reply(owner), effect: effect)
  }
  private func clearMedia(owner: MediaPublicationOwner, effect: () -> Void) -> Bool {
    guard canEnterMedia else { return false }
    mediaPublicationLock.lock()
    defer { mediaPublicationLock.unlock() }
    guard mediaPublicationOwner == owner else { return false }
    mediaPublicationOwner = nil
    Thread.current.threadDictionary[conversationMediaThreadKey] = true
    defer { Thread.current.threadDictionary.removeObject(forKey: conversationMediaThreadKey) }
    effect()
    return true
  }
  private func issue(sessionId: String?, foregroundOnly: Bool = false) -> String {
    let next = UUID().uuidString
    ticket = next; self.sessionId = sessionId; open = true
    connectionPaused = false; recoveryEpoch = 0
    retirementCause = "none"
    protectedPhase = sessionId == nil ? nil : .negotiating
    self.foregroundOnly = foregroundOnly
    sealedRouteKey = nil
    return next
  }
  private func closeCurrent(cause: RetirementCause = .other) {
    guard open else { return }
    retirementCause = cause.rawValue
    open = false
    connectionPaused = false
    continuation = nil; continuationApproved = false
    stopConnectionCue?(); stopConnectionCue = nil
    phoneReplies.removeAll()
    lastAcknowledgedPhoneRequestId = nil
    protectedPhase = nil
    foregroundOnly = false
    submittedRequests.removeAll()
    pendingReplySubmissions.removeAll()
    issuedReplySubmissions.removeAll()
    acknowledgedReplySubmissions.removeAll()
    replyTailRequests = nil
    sealedRouteKey = nil
    if let ticket, let sessionId {
      pendingRetirements.append(["ticket": ticket, "sessionId": sessionId])
    }
    // Close all identities before pausing: synchronous AV callbacks cannot re-enter play.
    let players = records.compactMap(\.value)
    for player in players where player.ticket == ticket { player.terminal = true }
    records.removeAll()
    for player in players where player.ticket == ticket { player.actions?.ncPause() }
  }
  fileprivate func synchronized<T>(_ body: () throws -> T) rethrows -> T {
    lock.lock(); depth += 1
    Thread.current.threadDictionary[outputThreadKey] = true
    defer {
      depth -= 1
      if depth == 0 { Thread.current.threadDictionary.removeObject(forKey: outputThreadKey) }
      let notifications = depth == 0 ? pendingRetirements : []
      if depth == 0 { pendingRetirements.removeAll() }
      lock.unlock()
      for info in notifications {
        NotificationCenter.default.post(name: Notification.Name("NCPlaybackGuardDidRetire"), object: self, userInfo: info)
      }
    }
    return try body()
  }
  fileprivate func bind(_ player: NCPlaybackBinding, ticket: String, rejected: (String) -> Void = { _ in }) -> Bool {
    synchronized {
      if player.attemptedBinding {
        let accepted = !player.terminal && player.ticket == ticket && self.ticket == ticket && open && !connectionPaused
        if !accepted { rejected(connectionPaused ? "connection_paused" : "binding_not_current") }
        return accepted
      }
      player.attemptedBinding = true
      guard !player.used, !player.terminal, self.ticket == ticket, open, !connectionPaused else {
        rejected(player.used ? "binding_already_used" : player.terminal ? "binding_terminal" :
          self.ticket != ticket || !open ? "owner_not_open" : "connection_paused")
        player.terminal = true
        if player.used { player.actions?.ncPause() }
        return false
      }
      records.removeAll { $0.value == nil || $0.value?.actions == nil }
      guard records.count < 16 else {
        rejected("binding_capacity")
        player.terminal = true
        closeCurrent()
        return false
      }
      player.ticket = ticket
      records.append(WeakBinding(value: player))
      return true
    }
  }
  fileprivate func eligible(_ player: NCPlaybackBinding) -> Bool {
    !connectionPaused && !player.terminal && (!player.attemptedBinding ||
      (open && player.ticket == ticket && (sessionId == nil || protectedPhase == .armed))) &&
      (!open || recoveryEpoch == 0 || sessionId == nil || (player.attemptedBinding && player.phoneRequestId != nil)) &&
      (replyTailRequests == nil || (player.phoneRequestId.map { replyTailRequests!.contains($0) } ?? false)) &&
      (player.phoneRequestId == nil ||
        (phoneReplies[player.phoneRequestId!]?.closed == false && player.phoneItemIdentity == player.actions?.ncCurrentItemIdentity))
  }
  fileprivate func bindPhoneReplyChunk(_ player: NCPlaybackBinding, ticket: String, requestId: String, chunkId: String,
                                      rejected: (String) -> Void = { _ in }) -> Bool {
    synchronized {
      if let existing = player.phoneRequestId {
        let accepted = existing == requestId && player.phoneChunkId == chunkId && player.ticket == ticket &&
          self.ticket == ticket && open && !player.terminal &&
          player.phoneItemIdentity == player.actions?.ncCurrentItemIdentity
        if !accepted { rejected("binding_identity_mismatch") }
        return accepted
      }
      let item = player.actions?.ncCurrentItemIdentity
      let reason: String? = !validPhoneId(requestId) || !validPhoneId(chunkId) ? "invalid_descriptor" :
        player.used ? "binding_already_used" :
        recoveryEpoch != 0 && !submittedRequests.contains(requestId) ? "request_not_submitted" :
        replyTailRequests != nil && !replyTailRequests!.contains(requestId) ? "request_outside_tail" :
        item == nil ? "item_missing" : nil
      if let reason { rejected(reason) }
      guard reason == nil, let item,
            bind(player, ticket: ticket, rejected: rejected) else {
        player.terminal = true
        if player.used { player.actions?.ncPause() }
        return false
      }
      if phoneReplies[requestId] == nil {
        guard phoneReplies.count < 256 else { rejected("reply_capacity"); player.terminal = true; return false }
        phoneReplies[requestId] = PhoneReply()
      }
      guard phoneReplies[requestId]?.closed == false else { rejected("reply_closed"); player.terminal = true; return false }
      player.phoneRequestId = requestId; player.phoneChunkId = chunkId; player.phoneItemIdentity = item
      return true
    }
  }
  fileprivate func acknowledgePhoneReplyStart(_ player: NCPlaybackBinding, expectedItemIdentity: ObjectIdentifier?) -> Bool {
    synchronized {
      guard let requestId = player.phoneRequestId else { return false }
      guard eligible(player) else {
        // An AV start callback can arrive after freeze/Stop; reassert native stop.
        if player.actions?.ncIsPlaying == true { player.actions?.ncPause() }
        return false
      }
      guard player.used, let expectedItemIdentity, expectedItemIdentity == player.phoneItemIdentity,
            expectedItemIdentity == player.actions?.ncCurrentItemIdentity,
            player.actions?.ncIsPlaying == true, let chunkId = player.phoneChunkId,
            let reply = phoneReplies[requestId], !reply.closed else { return false }
      player.phoneStartAcknowledged = true
      lastAcknowledgedPhoneRequestId = requestId
      guard !reply.seen.contains(chunkId) else { return true }
      guard reply.started.count < 2048 else { closePhoneReply(requestId, unavailable: true); return false }
      reply.seen.insert(chunkId); reply.started.append(chunkId)
      return true
    }
  }
  fileprivate var protectedOpen: Bool { open && sessionId != nil }
  fileprivate func acknowledgePhoneReplyCompletion(_ player: NCPlaybackBinding, expectedItemIdentity: ObjectIdentifier?) -> Bool {
    synchronized {
      guard eligible(player), player.phoneStartAcknowledged, let expectedItemIdentity,
            expectedItemIdentity == player.phoneItemIdentity, expectedItemIdentity == player.actions?.ncCurrentItemIdentity,
            let id = player.phoneRequestId, let chunk = player.phoneChunkId, let reply = phoneReplies[id] else { return false }
      if !reply.completed.contains(chunk) { reply.completed.append(chunk) }
      return true
    }
  }
  fileprivate func remove(_ player: NCPlaybackBinding) {
    synchronized {
      guard player.attemptedBinding else { return }
      let mustPause = !player.terminal
      player.terminal = true
      records.removeAll { $0.value == nil || $0.value === player }
      if mustPause { player.actions?.ncPause() }
    }
  }
  fileprivate func observePhoneReply(_ player: NCPlaybackBinding, ticket: String, requestId: String, chunkId: String) -> NCPlaybackObservation? {
    synchronized {
      guard player.attemptedBinding, player.ticket == ticket, player.phoneRequestId == requestId,
            player.phoneChunkId == chunkId, eligible(player), let actions = player.actions,
            let reply = phoneReplies[requestId] else { return nil }
      let position = player.phoneStartAcknowledged ? actions.ncPositionSeconds : nil
      return NCPlaybackObservation(started: player.phoneStartAcknowledged, completed: reply.completed.contains(chunkId),
        playing: player.phoneStartAcknowledged && actions.ncIsPlaying,
        positionSeconds: position.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil })
    }
  }
}

/// Read-only native progress for visuals; observing cannot authorize or acknowledge playback.
struct NCPlaybackObservation {
  let started: Bool
  let completed: Bool
  let playing: Bool
  let positionSeconds: Double?
}

/// The only injected operations are AVPlayer effects; policy executes in production.
protocol NCPlaybackActions: AnyObject {
  var ncIsPlaying: Bool { get }
  var ncCurrentItemIdentity: ObjectIdentifier? { get }
  var ncPositionSeconds: Double? { get }
  func ncPlay(rate: Float?)
  func ncPause()
  func ncSetRate(_ rate: Float)
}
extension NCPlaybackActions { var ncPositionSeconds: Double? { nil } }

final class NCPlaybackBinding {
  private var completionObserver:(()->Void)?
  private var completionObserved=false
  func setCompletionObserver(_ observer:(()->Void)?) { owner.synchronized { completionObserver=observer } }
  private let owner: NCPlaybackGuard
  fileprivate weak var actions: NCPlaybackActions?
  fileprivate var ticket: String?
  fileprivate var terminal = false
  fileprivate var attemptedBinding = false
  fileprivate var used = false
  fileprivate var phoneRequestId: String?
  fileprivate var phoneChunkId: String?
  fileprivate var phoneItemIdentity: ObjectIdentifier?
  fileprivate var phoneStartAcknowledged = false
  init(owner: NCPlaybackGuard = .shared, actions: NCPlaybackActions) {
    self.owner = owner; self.actions = actions
  }
  func bind(ticket: String) -> Bool { owner.bind(self, ticket: ticket) }
  func observePhoneReply(ticket: String, requestId: String, chunkId: String) -> NCPlaybackObservation? {
    owner.observePhoneReply(self, ticket: ticket, requestId: requestId, chunkId: chunkId)
  }
  func bindPhoneReplyChunk(ticket: String, requestId: String, chunkId: String, rejected: (String) -> Void = { _ in }) -> Bool {
    owner.bindPhoneReplyChunk(self, ticket: ticket, requestId: requestId, chunkId: chunkId, rejected: rejected)
  }
  @discardableResult
  func acknowledgePhoneReplyStart(expectedItemIdentity: ObjectIdentifier?) -> Bool {
    owner.acknowledgePhoneReplyStart(self, expectedItemIdentity: expectedItemIdentity)
  }
  var canUseMediaControls: Bool { owner.synchronized { owner.eligible(self) && !owner.protectedOpen } }
  @discardableResult
  func acknowledgePhoneReplyCompletion(expectedItemIdentity: ObjectIdentifier?) -> Bool {
    let accepted=owner.acknowledgePhoneReplyCompletion(self, expectedItemIdentity: expectedItemIdentity)
    let observer:(()->Void)?=owner.synchronized {
      guard accepted && !completionObserved else { return nil }
      completionObserved=true;return completionObserver
    }
    observer?()
    return accepted
  }
  @discardableResult
  func play(rate: Float, activate: () throws -> Void = {}) rethrows -> Bool {
    try owner.synchronized {
      used = true
      guard owner.eligible(self) else { return false }
      try activate()
      // setActive can synchronously deliver a safety notification on this thread.
      guard owner.eligible(self) else { return false }
      actions?.ncPlay(rate: rate)
      if !owner.eligible(self) { actions?.ncPause() }
      return true
    }
  }
  @discardableResult
  func resume(activate: () throws -> Void = {}) rethrows -> Bool {
    try owner.synchronized {
      used = true
      guard owner.eligible(self) else { return false }
      // Upstream foreground resume does not activate unmanaged players' sessions.
      if attemptedBinding { try activate() }
      guard owner.eligible(self) else { return false }
      actions?.ncPlay(rate: nil)
      if !owner.eligible(self) { actions?.ncPause() }
      return true
    }
  }
  func setRate(_ rate: Float) {
    owner.synchronized {
      guard owner.eligible(self), actions?.ncIsPlaying == true else { return }
      used = true
      actions?.ncSetRate(rate)
      if !owner.eligible(self) { actions?.ncPause() }
    }
  }
  func pause() { owner.synchronized { actions?.ncPause() } }
  func mediaPlay(rate: Float, toggle: Bool) -> Bool {
    owner.synchronized {
      guard owner.eligible(self), !owner.protectedOpen else { return false }
      used = true
      if toggle && actions?.ncIsPlaying == true {
        actions?.ncPause()
      } else {
        actions?.ncPlay(rate: rate)
        if !owner.eligible(self) { actions?.ncPause() }
      }
      return true
    }
  }
  func replace(_ replaceItem: () -> Void) {
    owner.synchronized {
      guard owner.eligible(self), phoneRequestId == nil else { return }
      let wasPlaying = actions?.ncIsPlaying == true
      actions?.ncPause()
      guard owner.eligible(self) else { return }
      replaceItem()
      if wasPlaying && owner.eligible(self) { actions?.ncPlay(rate: nil) }
      if !owner.eligible(self) { actions?.ncPause() }
    }
  }
  func loop(isCurrentItem: () -> Bool, seek: () -> Void) {
    owner.synchronized {
      guard owner.eligible(self), isCurrentItem() else { return }
      seek()
      if owner.eligible(self) { actions?.ncPlay(rate: nil) }
      if !owner.eligible(self) { actions?.ncPause() }
    }
  }
  func deactivate(_ effect: () -> Void) {
    owner.synchronized {
      guard owner.eligible(self), !owner.protectedOpen else { return }
      effect()
    }
  }
  @discardableResult
  func command(_ effect: () -> Void) -> Bool {
    owner.synchronized {
      guard owner.eligible(self), !owner.protectedOpen else { return false }
      effect()
      return true
    }
  }
  func remove() { owner.remove(self) }
}
