package expo.modules.nclivecapture

import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.Callable
import java.util.concurrent.FutureTask
import java.util.concurrent.RejectedExecutionException
import java.util.concurrent.ThreadPoolExecutor
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

enum class CaptureFailure(val wireValue: String) {
  PERMISSION_DENIED("permission_denied"), UNSUPPORTED_FORMAT("unsupported_format"),
  CAPTURE_OVERFLOW("capture_overflow"), BACKLOG_FULL("backlog_full"), ROUTE_CHANGED("route_changed"),
  INTERRUPTED("interrupted"), START_FAILED("start_failed"), RELEASE_FAILED("release_failed"),
  FILE_FAILED("file_failed"), BACKGROUND_SESSION_LIMIT("background_session_limit"),
  CONVERSATION_STOPPED("conversation_stopped"), REPLY_TAIL_TIMEOUT("reply_tail_timeout"),
  REPLY_TAIL_UNAVAILABLE("reply_tail_unavailable")
}

class CapturePolicyException(val failure: CaptureFailure, cause: Throwable? = null) : RuntimeException(failure.wireValue, cause)
enum class CaptureLifetime(val wireValue: String) { CAPTURING("capturing"), REPLY_TAIL("reply-tail"), CLOSED("closed") }
enum class BackgroundRoute(val wireValue: String) { WIRED("wired"), BLUETOOTH("bluetooth"), INELIGIBLE("ineligible") }
enum class CleanupDisposition { COMPLETE, RETRY_VISIBLE, RETRY_HIDDEN }

// Foreground capture owns its microphone route. A bound background duplex route
// additionally owns the output, which remains strict after headphone admission.
internal fun routeKeyMatches(expected: String, actual: String): Boolean =
  expected.isEmpty() || if ('|' in expected) expected == actual else expected == actual.substringBefore('|')

// AudioRecord can acquire its final built-in mic ID after startRecording. Set
// the foreground baseline once, before admitting input; later checks stay exact.
internal fun foregroundArmInputKey(expected: String, observed: String): String {
  val previousType = expected.substringBefore(':').toIntOrNull()
  val input = observed.substringBefore('|')
  val currentType = input.substringBefore(':').toIntOrNull()
  val currentId = input.substringAfter(':', "").toIntOrNull()
  return if (currentType != null && currentType >= 0 && currentId != null && currentId >= 0
    && (previousType == -1 || previousType == currentType)) input else expected
}

class CleanupSupervisor {
  private var reason: CaptureFailure? = null
  private var serviceVisible = false
  private var destroyRequested = false
  val pending get() = reason != null
  val pendingReason get() = reason
  val retainsVisibleService get() = pending && serviceVisible
  val mayShutdown get() = destroyRequested && !pending

  fun begin(reason: CaptureFailure, serviceVisible: Boolean) {
    if (this.reason == null) {
      this.reason = reason
      this.serviceVisible = serviceVisible
    } else {
      this.serviceVisible = this.serviceVisible || serviceVisible
    }
  }
  fun serviceDestroyed() { serviceVisible = false }
  fun requestDestroy() { destroyRequested = true }
  fun attempt(cleanup: () -> Unit): CleanupDisposition = try {
    cleanup()
    reason = null
    serviceVisible = false
    CleanupDisposition.COMPLETE
  } catch (_: Throwable) {
    if (serviceVisible) CleanupDisposition.RETRY_VISIBLE else CleanupDisposition.RETRY_HIDDEN
  }
}

class BoundedSerialDispatcher(name: String, private val audioCapacity: Int, controlReserve: Int) {
  private val queuedAudio = AtomicInteger(0)
  private val dropped = AtomicInteger(0)
  private val evicted = AtomicInteger(0)
  @Volatile private var ownerThread: Thread? = null
  private val executor = ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
    ArrayBlockingQueue(audioCapacity + controlReserve), { runnable ->
      Thread(runnable, name).also { ownerThread = it }
    }, ThreadPoolExecutor.AbortPolicy())

  val audioDrops get() = dropped.get()
  val audioQueued get() = queuedAudio.get()
  val audioLimit get() = audioCapacity
  val audioEvictions get() = evicted.get()
  val isShutdown get() = executor.isShutdown
  val isOwnerThread get() = Thread.currentThread() === ownerThread

  private inner class AudioTask(private val action: () -> Unit) : Runnable {
    private val counted = AtomicBoolean(true)
    override fun run() {
      try { action() } finally { releaseCount() }
    }
    fun drop(controlEviction: Boolean = false) {
      if (releaseCount()) { if (controlEviction) evicted.incrementAndGet(); dropped.incrementAndGet() }
    }
    private fun releaseCount(): Boolean = counted.compareAndSet(true, false).also { if (it) queuedAudio.decrementAndGet() }
  }

  fun executeAudio(action: () -> Unit): Boolean {
    while (true) {
      val count = queuedAudio.get()
      if (count >= audioCapacity || isShutdown) { dropped.incrementAndGet(); return false }
      if (queuedAudio.compareAndSet(count, count + 1)) break
    }
    val task = AudioTask(action)
    return try { executor.execute(task); true }
    catch (_: RejectedExecutionException) { task.drop(); false }
  }

  fun executeControl(action: () -> Unit) {
    val task = Runnable(action)
    try { executor.execute(task); return } catch (_: RejectedExecutionException) {
      if (isShutdown) throw RejectedExecutionException("lifecycle owner is shut down")
    }
    val victim = executor.queue.firstOrNull { it is BoundedSerialDispatcher.AudioTask }
    if (victim is BoundedSerialDispatcher.AudioTask && executor.queue.remove(victim)) victim.drop(controlEviction = true)
    executor.execute(task)
  }

  fun <T> submitControl(action: () -> T): FutureTask<T> {
    val future = FutureTask(Callable(action))
    try { executeControl { future.run() } }
    catch (error: RejectedExecutionException) { future.cancel(false); throw error }
    return future
  }

  fun shutdown() { executor.shutdown() }
}

data class LifecycleSnapshot(val lifetime: CaptureLifetime, val requestIds: Set<String> = emptySet())
data class OnsetAttachment(val receipt: Map<String, Any>? = null, val unavailable: Boolean = false)

class CaptureOnsetFence {
  private var pending: Pair<String, OnsetAttachment>? = null
  fun freeze(utteranceId: String, freeze: () -> OnsetAttachment, stillOpen: () -> Boolean): Boolean {
    val attachment = freeze()
    if (!stillOpen()) { pending = null; return false }
    pending = utteranceId to attachment
    return true
  }
  fun peek(utteranceId: String): OnsetAttachment? = pending?.takeIf { it.first == utteranceId }?.second
  fun takeForCompletion(utteranceId: String): OnsetAttachment? {
    val value = pending?.takeIf { it.first == utteranceId }?.second ?: return null
    pending = null
    return value
  }
  fun clear() { pending = null }
}

object CompletedClipFence {
  fun <T> persist(sourceIsCurrent: () -> Boolean, takeOverflow: () -> Boolean,
    write: () -> T, discard: (T) -> Unit): T {
    if (!sourceIsCurrent()) throw CapturePolicyException(CaptureFailure.INTERRUPTED)
    if (takeOverflow()) throw CapturePolicyException(CaptureFailure.CAPTURE_OVERFLOW)
    val value = write()
    val failure = when { !sourceIsCurrent() -> CaptureFailure.INTERRUPTED; takeOverflow() -> CaptureFailure.CAPTURE_OVERFLOW; else -> null }
    if (failure != null) { discard(value); throw CapturePolicyException(failure) }
    return value
  }
}

class ExactOwnerFailureFence(private val onFailure: (String?, Long) -> Unit) {
  data class Token(val generation: Long, val ticket: String?)
  private var next = 0L
  private var current: Token? = null
  @Synchronized fun issue(ticket: String?): Token = Token(++next, ticket).also { current = it }
  @Synchronized fun admits(token: Token): Boolean = current == token
  fun failed(token: Token) {
    val deliver = synchronized(this) { if (current != token) null else token.also { current = null } }
    deliver?.let { onFailure(it.ticket, it.generation) }
  }
  @Synchronized fun clear(token: Token) { if (current == token) current = null }
}

data class RouteSnapshot(val category: BackgroundRoute, val key: String, val input: String, val output: String)

/** Monotonic capture gate; queued buffers retain their original admission epoch/time. */
class ConnectionRecoveryClock {
  private val clock = expo.modules.audio.NCConnectionRecoveryClock()
  val epoch get() = clock.epoch
  fun pause(epoch: Long, now: Long) = clock.pause(epoch, now)
  fun takeWaitingCue(now: Long) = clock.takeWaitingCue(now)
  fun resume(epoch: Long, now: Long) = clock.resume(epoch, now)
  fun acceptsInput(epoch: Long, capturedAt: Long) = clock.acceptsInput(epoch, capturedAt)
  fun cancel() = clock.cancel()
  companion object { const val RESUME_SUPPRESSION_MS = expo.modules.audio.NCConnectionRecoveryClock.RESUME_SUPPRESSION_MS }
}

interface CaptureRouteLease {
  fun release()
  fun retainedSnapshot(): RouteSnapshot? = null
}

/** Runs on the engine's serial owner; all native effects are inside the admission transaction. */
class BackgroundAdmission(private val policy: LiveCapturePolicy) {
  fun arm(requested: String, bluetoothConfirmed: Boolean, foreground: () -> Boolean,
    bind: () -> RouteSnapshot?, armOutput: (String, String) -> Boolean,
    startService: () -> Unit, failClose: () -> Unit): Boolean {
    if (!policy.canArmBackground(requested, foreground())) return false
    val source = policy.driverIdentity
    val lease = policy.routeIdentity
    if (policy.backgroundAuthorized) return policy.permitsBackground((source as CaptureDriver).routeKey)
    var admitted = false
    try {
      val route = bind() ?: return false
      if (!policy.armBackground(requested, foreground(), route.category, route.key, bluetoothConfirmed)) return false
      val ticket = policy.outputTicket ?: return false
      if (!armOutput(ticket, requested)) return false
      startService()
      admitted = true
      return true
    } catch (_: Throwable) {
      return false
    } finally {
      if (!admitted && policy.currentSessionId == requested && policy.driverIdentity === source && policy.routeIdentity === lease)
        failClose()
    }
  }
}

interface CaptureDriver {
  val routeLease: CaptureRouteLease? get() = null
  val voiceProcessingActive: Boolean
  val routeKey: String
  fun start()
  /** Returns only after the producer is stopped and all in-flight reads have exited. */
  fun stopAndDrain()
}

class LiveCapturePolicy(
  private val retireOutput: (String) -> Unit = {},
  private val registerSubmission: (String, String, String) -> Boolean = { _, _, _ -> false },
  private val sealReplyTail: (String, String, List<String>, List<String>) -> List<String>? = { _, _, r, p ->
    r.takeIf { r.distinct().size == r.size && p.distinct().size == p.size && r.size + p.size <= 3 }
  },
  private val finishEmptyTail: (String, String) -> Boolean = { _, _ -> true },
  private val detachCapture: (String, String) -> Unit = { _, _ -> }
) {
  private data class Output(val session: String, val ticket: String, val foregroundOnly: Boolean, val independent:Boolean=false)
  private var output: Output? = null
  private var session: String? = null
  private var driver: CaptureDriver? = null
  private var route: CaptureRouteLease? = null
  private var cleanupPending = false
  private var tail: Set<String>? = null
  private var backgroundRouteKey: String? = null
  private var backgroundArmed = false
  private var backgroundWasRequested = false
  private var foregroundArmed = false
  private var closed = false
  private val protectedSessions = mutableSetOf<String>()
  private val submissions = linkedMapOf<String, String>()
  private var recoveryEpoch = 0L
  var connectionPaused = false
    private set

  var lastFailure: CaptureFailure? = null
    private set
  val isCapturing get() = driver != null
  val driverIdentity get(): Any? = driver
  val routeIdentity get(): CaptureRouteLease? = route
  val currentSessionId get() = session
  val lifetime get() = when { driver != null -> CaptureLifetime.CAPTURING; tail != null -> CaptureLifetime.REPLY_TAIL; else -> CaptureLifetime.CLOSED }
  val backgroundAuthorized get() = backgroundArmed
  val eventBackgroundAuthorized: Boolean? get() = if (foregroundOnly) false else if (backgroundWasRequested) backgroundArmed else null
  val foregroundOnly get() = output?.foregroundOnly == true
  val outputTicket get() = output?.ticket
  val outputSessionId get() = output?.session
  val independentCapture get() = output?.independent==true
  val voiceProcessingActive get() = driver?.voiceProcessingActive == true

  fun capabilityRoute(live: RouteSnapshot?): RouteSnapshot? = live ?: if (
    driver == null && tail != null && backgroundArmed && !cleanupPending
  ) route?.retainedSnapshot()?.copy(input = "unknown") else null

  fun canArmBackground(requested: String, foreground: Boolean): Boolean = foreground && !closed && !cleanupPending &&
    driver != null && session == requested && output?.session == requested && !foregroundOnly

  fun adoptProtectedOutput(requested: String, ticket: String, foregroundOnly: Boolean) {
    if (closed || !validId(requested) || !validId(ticket) || output != null || requested in protectedSessions ||
      protectedSessions.size >= 256 || (session != null && session != requested)) {
      throw CapturePolicyException(if (protectedSessions.size >= 256) CaptureFailure.BACKGROUND_SESSION_LIMIT else CaptureFailure.START_FAILED)
    }
    protectedSessions += requested
    output = Output(requested, ticket, foregroundOnly)
    recoveryEpoch = 0; connectionPaused = false
  }

  fun adoptCapture(requested:String,ticket:String,foregroundOnly:Boolean) {
    adoptProtectedOutput(requested,ticket,foregroundOnly)
    output=output!!.copy(independent=true)
  }

  fun ownsConnection(requested: String, ticket: String): Boolean = !closed && !cleanupPending &&
    driver != null && tail == null && session == requested && output?.ticket == ticket &&
    (backgroundArmed || foregroundArmed)

  fun pauseConnection(requested: String, ticket: String, epoch: Long): Boolean {
    if (!ownsConnection(requested, ticket) || epoch <= 0 || epoch < recoveryEpoch) return false
    if (epoch == recoveryEpoch) return connectionPaused
    recoveryEpoch = epoch; connectionPaused = true; submissions.clear()
    return true
  }

  fun canResumeConnection(requested: String, ticket: String, epoch: Long): Boolean =
    ownsConnection(requested, ticket) && connectionPaused && epoch == recoveryEpoch

  fun resumeConnection(requested: String, ticket: String, epoch: Long): Boolean {
    if (!canResumeConnection(requested, ticket, epoch)) return false
    connectionPaused = false
    return true
  }

  fun start(requested: String, makeDriver: () -> CaptureDriver) {
    if (closed || !validId(requested) || tail != null || output?.session?.let { it != requested } == true) {
      throw CapturePolicyException(CaptureFailure.START_FAILED)
    }
    if (session != null) {
      if (session == requested && driver != null && !cleanupPending) return
      if (cleanupPending) throw CapturePolicyException(CaptureFailure.RELEASE_FAILED)
      throw CapturePolicyException(CaptureFailure.START_FAILED)
    }
    backgroundWasRequested = false
    val candidate = makeDriver()
    route = candidate.routeLease
    try {
      candidate.start()
      driver = candidate
      session = requested
      cleanupPending = false
      lastFailure = null
    } catch (start: Throwable) {
      try { candidate.stopAndDrain(); route?.release(); route = null } catch (cleanup: Throwable) {
        driver = candidate
        session = requested
        cleanupPending = true
        throw CapturePolicyException(CaptureFailure.RELEASE_FAILED, cleanup)
      }
      retireMatchingOutput(requested)
      throw CapturePolicyException((start as? CapturePolicyException)?.failure ?: CaptureFailure.START_FAILED, start)
    }
  }

  fun stop(requested: String): LifecycleSnapshot {
    if (session != requested && output?.session != requested) return LifecycleSnapshot(lifetime)
    val stopping = driver
    try { stopping?.stopAndDrain(); route?.release(); route = null } catch (error: Throwable) {
      cleanupPending = true
      throw CapturePolicyException(CaptureFailure.RELEASE_FAILED, error)
    }
    driver = null
    session = null
    cleanupPending = false
    tail = null
    connectionPaused = false
    submissions.clear()
    backgroundArmed = false
    backgroundRouteKey = null
    foregroundArmed = false
    retireMatchingOutput(requested)
    return LifecycleSnapshot(CaptureLifetime.CLOSED)
  }

  fun stopListening(requested: String, requestIds: List<String>, pendingUploadIds: List<String>): LifecycleSnapshot {
    if (connectionPaused && session == requested) return stop(requested)
    tail?.let { return LifecycleSnapshot(CaptureLifetime.REPLY_TAIL, it) }
    if (session != requested || driver == null) return LifecycleSnapshot(lifetime, tail.orEmpty())
    val owner = output
    val authorized = backgroundArmed || foregroundArmed
    if (!authorized || owner?.session != requested || requestIds.size > 3 || pendingUploadIds.size > 2 ||
      requestIds.size + pendingUploadIds.size > 3) {
      stop(requested)
      return LifecycleSnapshot(CaptureLifetime.CLOSED)
    }
    val canonical = sealReplyTail(requested, owner.ticket, requestIds, pendingUploadIds)
    if (canonical == null) {
      stop(requested)
      return LifecycleSnapshot(CaptureLifetime.CLOSED)
    }
    if (canonical.isEmpty() && pendingUploadIds.isEmpty() && !finishEmptyTail(owner.ticket, requested)) {
      stop(requested)
      throw CapturePolicyException(CaptureFailure.REPLY_TAIL_UNAVAILABLE)
    }
    val stopping = driver
    try {
      stopping?.stopAndDrain()
      if (owner.independent || (canonical.isEmpty() && pendingUploadIds.isEmpty())) { route?.release(); route = null }
    } catch (error: Throwable) {
      cleanupPending = true
      throw CapturePolicyException(CaptureFailure.RELEASE_FAILED, error)
    }
    driver = null
    cleanupPending = false
    submissions.keys.retainAll(pendingUploadIds.toSet())
    if(owner.independent) {
      // The guard retains accepted submissions under this exact session; they
      // do not retain the driver slot, SCO lease or microphone service role.
      retireMatchingOutput(requested)
      session=null;submissions.clear();backgroundArmed=false;foregroundArmed=false
      backgroundRouteKey=null;tail=null
      return LifecycleSnapshot(if(canonical.isEmpty()&&pendingUploadIds.isEmpty()) CaptureLifetime.CLOSED else CaptureLifetime.REPLY_TAIL,canonical.toSet())
    }
    if (canonical.isEmpty() && pendingUploadIds.isEmpty()) {
      session = null
      retireMatchingOutput(requested)
      return LifecycleSnapshot(CaptureLifetime.CLOSED)
    }
    tail = canonical.toSet()
    return LifecycleSnapshot(CaptureLifetime.REPLY_TAIL, tail.orEmpty())
  }

  fun armBackground(requested: String, foreground: Boolean, route: BackgroundRoute, routeKey: String, bluetoothConfirmed: Boolean): Boolean {
    if (!canArmBackground(requested, foreground) ||
      routeKey.isEmpty() || route == BackgroundRoute.INELIGIBLE || (route == BackgroundRoute.BLUETOOTH && !bluetoothConfirmed)) return false
    backgroundArmed = true
    backgroundWasRequested = true
    backgroundRouteKey = routeKey
    return true
  }

  fun armForeground(requested: String, foreground: Boolean): Boolean {
    val owner = output
    if (!foreground || driver == null || session != requested || owner?.session != requested || !owner.foregroundOnly) return false
    foregroundArmed = true
    return true
  }

  fun disarmBackground(requested: String) {
    if (session != requested || foregroundOnly) return
    backgroundArmed = false
    backgroundRouteKey = null
  }

  fun permitsBackground(routeKey: String): Boolean = backgroundArmed && backgroundRouteKey == routeKey

  fun registerSubmittedTurn(requested: String, ticket: String, submissionId: String, kind: String): Boolean {
    if (kind != "text" && kind != "image") return false
    return register(requested, ticket, submissionId, "explicit:$kind")
  }

  fun registerSubmittedUpload(requested: String, ticket: String, utteranceId: String, uploadId: String): Boolean =
    register(requested, ticket, uploadId, "upload:$utteranceId")

  private fun register(requested: String, ticket: String, id: String, kind: String): Boolean {
    val owner = output
    if (connectionPaused || session != requested || driver == null || (!backgroundArmed && !foregroundArmed) || owner?.ticket != ticket ||
      !validId(id)) return false
    submissions[id]?.let { return it == kind }
    if (submissions.size >= 2 || !registerSubmission(ticket, requested, id)) return false
    submissions[id] = kind
    return true
  }

  fun abandonSubmission(requested: String, ticket: String, id: String): Boolean {
    if (output?.ticket != ticket || session != requested) return false
    return submissions.remove(id) != null
  }

  fun endForSystemEvent(reason: CaptureFailure, source: Any?) {
    if (driver != null && source !== driver) return
    if (driver == null && source != null) return
    val current = session ?: output?.session ?: return
    try { stop(current) } finally { lastFailure = reason }
  }

  fun endForRouteEvent(source: CaptureRouteLease, reason: CaptureFailure) {
    if (source !== route) return
    endForSystemEvent(reason, driver)
  }

  fun destroy() {
    closed = true
    session?.let { stop(it) }
    output?.session?.let { retireMatchingOutput(it) }
  }

  private fun retireMatchingOutput(requested: String) {
    val owner = output?.takeIf { it.session == requested } ?: return
    if(owner.independent)detachCapture(owner.session,owner.ticket)
    output = null
    if(!owner.independent)retireOutput(owner.ticket)
  }

  companion object {
    fun validId(id: String): Boolean = id.isNotEmpty() && id.length <= 128 && id.all {
      it in '0'..'9' || it in 'A'..'Z' || it in 'a'..'z' || it == '-' || it == '_'
    }
  }
}
