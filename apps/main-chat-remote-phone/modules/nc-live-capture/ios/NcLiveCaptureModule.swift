import ExpoModulesCore

private struct ReplyTailOptions: Record {
    @Field var requestIds: [String] = []
    @Field var pendingUploadIds: [String] = []
}

public final class NcLiveCaptureModule: Module {
    private let capture = LiveCaptureEngine()
    private let replyMedia = ReplyMediaControls()

    public func definition() -> ModuleDefinition {
        Name("NcLiveCapture")
        Events("captureEvent", "replyMediaCommand")

        OnCreate {
            self.replyMedia.emit = { [weak self] scope, command in
                self?.sendEvent("replyMediaCommand", ["scope": scope, "command": command])
            }
            self.capture.setEmitter { [weak self] event in
                self?.sendEvent("captureEvent", event.payload)
            }
        }

        AsyncFunction("capabilities") { (promise: Promise) in
            promise.resolve(self.capture.capabilities())
        }.runOnQueue(capture.queue)

        AsyncFunction("configureReplyMediaControls") { (scope: String?, playing: Bool, nextToggles: Bool) in
            self.replyMedia.configure(scope: scope, playing: playing, nextToggles: nextToggles)
        }

        AsyncFunction("outputState") { (promise: Promise) in
            promise.resolve(self.capture.outputState())
        }.runOnQueue(capture.queue)

        AsyncFunction("beginProtectedOutput") { (sessionId: String, expectedTicket: String?, promise: Promise) in
            self.resolve(promise, fallback: .startFailed) {
                try self.capture.beginProtectedOutput(sessionId: sessionId, expectedTicket: expectedTicket)
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("beginForegroundOutput") { (expectedTicket: String?, promise: Promise) in
            self.resolve(promise, fallback: .startFailed) {
                try self.capture.beginForegroundOutput(expectedTicket: expectedTicket)
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("beginForegroundProtectedOutput") { (sessionId: String, expectedTicket: String?, promise: Promise) in
            self.resolve(promise, fallback: .startFailed) {
                try self.capture.beginForegroundProtectedOutput(sessionId: sessionId, expectedTicket: expectedTicket)
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("retireOutput") { (ticket: String, promise: Promise) in
            self.capture.retireOutput(ticket: ticket)
            promise.resolve()
        }.runOnQueue(capture.queue)

        AsyncFunction("start") { (sessionId: String, promise: Promise) in
            self.resolve(promise, fallback: .startFailed) {
                try self.capture.start(sessionId: sessionId)
                return nil
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("stop") { (sessionId: String, promise: Promise) in
            self.resolve(promise, fallback: .fileFailed) {
                try self.capture.stop(sessionId: sessionId)
                return nil
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("stopListening") { (sessionId: String, permit: ReplyTailOptions, promise: Promise) in
            self.resolve(promise, fallback: .replyTailUnavailable) {
                try self.capture.stopListening(sessionId: sessionId,
                    permit: ReplyTailPermit(requestIds: permit.requestIds, pendingUploadIds: permit.pendingUploadIds))
                return nil
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("registerSubmittedUpload") { (sessionId: String, utteranceId: String, uploadId: String, promise: Promise) in
            promise.resolve(self.capture.registerSubmittedUpload(sessionId: sessionId, utteranceId: utteranceId, uploadId: uploadId))
        }.runOnQueue(capture.queue)

        AsyncFunction("registerSubmittedTurn") { (sessionId: String, ticket: String, submissionId: String, kind: String, promise: Promise) in
            promise.resolve(self.capture.registerSubmittedTurn(sessionId: sessionId, ticket: ticket, submissionId: submissionId, kind: kind))
        }.runOnQueue(capture.queue)

        AsyncFunction("admitReplyForUpload") { (sessionId: String, ticket: String, uploadId: String, requestId: String, promise: Promise) in
            promise.resolve(self.capture.admitReplyForUpload(sessionId: sessionId, ticket: ticket, uploadId: uploadId, requestId: requestId))
        }.runOnQueue(capture.queue)

        AsyncFunction("abandonSubmittedUpload") { (sessionId: String, ticket: String, uploadId: String, promise: Promise) in
            self.capture.abandonSubmittedUpload(sessionId: sessionId, ticket: ticket, uploadId: uploadId)
            promise.resolve()
        }.runOnQueue(capture.queue)

        AsyncFunction("finishReplyOutput") { (sessionId: String, ticket: String, completedRequestIds: [String], promise: Promise) in
            self.resolve(promise, fallback: .replyTailUnavailable) {
                try self.capture.finishReplyOutput(sessionId: sessionId, ticket: ticket, completedRequestIds: completedRequestIds)
                return nil
            }
        }.runOnQueue(capture.queue)

        // Additive method: existing JS and existing binaries keep start(sessionId).
        AsyncFunction("startWithDucking") { (sessionId: String, level: String, promise: Promise) in
            self.resolve(promise, fallback: .startFailed) {
                try self.capture.start(sessionId: sessionId, duckingLevel: level)
                return nil
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("setPlaybackActive") { (sessionId: String, active: Bool, promise: Promise) in
            self.capture.setPlaybackActive(sessionId: sessionId, active: active)
            promise.resolve()
        }.runOnQueue(capture.queue)

        AsyncFunction("pauseConnection") { (sessionId: String, ticket: String, recoveryEpoch: Int, promise: Promise) in
            promise.resolve(self.capture.pauseConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch))
        }.runOnQueue(capture.queue)
        AsyncFunction("pauseReplyContinuation") { (sessionId: String, ticket: String, recoveryEpoch: Int, promise: Promise) in
            promise.resolve(self.capture.pauseReplyContinuation(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch))
        }.runOnQueue(capture.queue)
        AsyncFunction("resumeReplyContinuation") { (sessionId: String, ticket: String, recoveryEpoch: Int, requestIds: [String], promise: Promise) in
            self.capture.resumeReplyContinuation(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch, requestIds: requestIds) { promise.resolve($0) }
        }.runOnQueue(capture.queue)

        AsyncFunction("resumeConnection") { (sessionId: String, ticket: String, recoveryEpoch: Int, promise: Promise) in
            self.capture.resumeConnection(sessionId: sessionId, ticket: ticket, recoveryEpoch: recoveryEpoch) { resumed in
                promise.resolve(resumed)
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("armBackground") { (sessionId: String, bluetoothConfirmed: Bool, promise: Promise) in
            promise.resolve(self.capture.armBackground(sessionId: sessionId, bluetoothConfirmed: bluetoothConfirmed))
        }.runOnQueue(capture.queue)

        AsyncFunction("disarmBackground") { (sessionId: String, promise: Promise) in
            self.capture.disarmBackground(sessionId: sessionId)
            promise.resolve()
        }.runOnQueue(capture.queue)

        AsyncFunction("armForeground") { (sessionId: String, promise: Promise) in
            promise.resolve(self.capture.armForeground(sessionId: sessionId))
        }.runOnQueue(capture.queue)

        AsyncFunction("acquireUtterance") { (sessionId: String, utteranceId: String, promise: Promise) in
            self.resolve(promise, fallback: .fileFailed) {
                try self.capture.acquire(sessionId: sessionId, utteranceId: utteranceId)
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("releaseUtterance") { (sessionId: String, utteranceId: String, promise: Promise) in
            self.resolve(promise, fallback: .releaseFailed) {
                try self.capture.release(sessionId: sessionId, utteranceId: utteranceId)
                return nil
            }
        }.runOnQueue(capture.queue)

        AsyncFunction("acknowledgeState") { (sessionId: String, sequence: Int, promise: Promise) in
            self.capture.acknowledgeState(sessionId: sessionId, sequence: sequence)
            promise.resolve()
        }.runOnQueue(capture.queue)

        OnDestroy { self.replyMedia.destroy(); self.capture.destroy() }
        OnAppContextDestroys { self.capture.readerContextDestroyed() }
    }

    private func resolve(_ promise: Promise, fallback: CaptureFailure, _ operation: () throws -> Any?) {
        do { promise.resolve(try operation()) }
        catch {
            let code = ((error as? CaptureFailure) ?? fallback).rawValue
            // Direct Promise rejection preserves the fixed code. Throwing an
            // NSError through Expo would wrap it and expose native descriptions.
            promise.reject(code, code)
        }
    }
}
