// NeuralCompanion maintained extension to expo-audio; MIT licensed.
package expo.modules.audio
import java.util.UUID

/** Route ownership outlives capture, but never the exact protected ticket. */
class NCCommunicationRoute {
  class Token internal constructor(val ticket: String, val deviceId: Int, val deviceType: Int)
  private var current: Token? = null
  private var preparation: Token? = null
  private var preparationDeadline = 0L
  private var restoringTicket: String? = null
  private var restoringDevices = emptySet<Int>()
  private var restoringDeadline = 0L
  private val observers = mutableSetOf<() -> Unit>()
  fun observe(listener: () -> Unit): () -> Unit {
    synchronized(this) { observers += listener }
    return { synchronized(this) { observers -= listener }; Unit }
  }
  private fun changed() {
    // Never dispatch player work while holding the microphone route lock.
    val listeners = synchronized(this) { observers.toList() }
    listeners.forEach { it() }
  }
  val active: Boolean @Synchronized get() = current != null
  @Synchronized fun acquire(ticket: String, deviceId: Int, deviceType: Int): Token {
    check(current == null) { "communication route already owned" }
    return Token(ticket, deviceId, deviceType).also { current = it }
  }
  @Synchronized fun forTicket(ticket: String?): Token? = current?.takeIf { it.ticket == ticket }
  @Synchronized fun isCurrent(token: Token): Boolean = current === token
  @Synchronized fun accepts(token: Token, deviceId: Int?, deviceType: Int?): Boolean =
    current === token && token.deviceId == deviceId && token.deviceType == deviceType
  fun beginPreparation(token: Token) {
    synchronized(this) {
      check(current === token) { "capture_route_owner_changed" }
      preparation = token
      preparationDeadline = System.nanoTime() + 8_000_000_000L
    }
    changed()
  }
  fun endPreparation(token: Token) {
    val ended = synchronized(this) {
      (preparation === token).also { if (it) preparation = null }
    }
    if (ended) changed()
  }
  @Synchronized fun isPreparing(ticket: String?): Boolean = current?.let {
    it.ticket == ticket && preparation === it && System.nanoTime() < preparationDeadline
  } == true
  @Synchronized fun expectRestoration(token: Token, deviceIds: Set<Int>) {
    check(current === token) { "capture_route_owner_changed" }
    restoringTicket = token.ticket; restoringDevices = deviceIds
    restoringDeadline = System.nanoTime() + 2_000_000_000L
  }
  @Synchronized fun expectedRemoval(ticket: String?, deviceIds: Set<Int>): Boolean {
    if (ticket == null || ticket != restoringTicket || deviceIds.isEmpty() ||
      System.nanoTime() >= restoringDeadline || !restoringDevices.containsAll(deviceIds)) return false
    restoringDevices = restoringDevices - deviceIds
    return true
  }
  fun release(token: Token) {
    val released = synchronized(this) {
      (current === token).also { if (it) { preparation = null; current = null } }
    }
    if (released) changed()
  }
  companion object { val shared = NCCommunicationRoute() }
}

/** Called by the guard on the existing player application thread. */
class NCPlaybackRouteEffects(
  private val routes: NCCommunicationRoute,
  private val configure: (NCCommunicationRoute.Token?) -> Unit,
  private val start: () -> Unit, private val stop: () -> Unit,
  private val profile: (Boolean) -> Unit = {},
  private val dispatch: (() -> Unit) -> Unit = { it() },
  private val eligible: (String?) -> Boolean = { true }
) {
  private var unsubscribe: (() -> Unit)? = null
  @Volatile private var epoch = 0L
  private var stableCommunication = false
  /** Before muxed preparation: changing Media3 attributes later flushes audio. */
  fun prepareCommunication() { stableCommunication = true; profile(true) }
  private fun detach() { epoch++; unsubscribe?.invoke(); unsubscribe = null }
  fun play(ticket: String?) {
    detach()
    val currentEpoch = epoch
    if (ticket != null) unsubscribe = routes.observe {
      dispatch {
        if (epoch == currentEpoch && eligible(ticket)) configure(routes.forTicket(ticket))
      }
    }
    val route = routes.forTicket(ticket)
    profile(stableCommunication || route != null)
    configure(route); start()
  }
  fun pause() { detach(); stop(); configure(null); profile(stableCommunication) }
  fun close() { detach(); configure(null) }
}

data class NCPhoneReplyReceipt(
  val phoneRequestId: String,
  val interruptionId: String,
  val startedChunkIds: List<String>
) {
  fun payload(): Map<String, Any> = mapOf(
    "phone_request_id" to phoneRequestId,
    "interruption_id" to interruptionId,
    "started_chunk_ids" to startedChunkIds.toList()
  )
}
sealed class NCPhoneReplyOnset {
  data object None : NCPhoneReplyOnset()
  data object Unavailable : NCPhoneReplyOnset()
  data class Receipt(val value: NCPhoneReplyReceipt) : NCPhoneReplyOnset()
}
data class NCPlaybackOutputState(
  val ticket: String?, val sessionId: String?, val open: Boolean,
  val armed: Boolean, val lastRetirementCause: String
)
data class NCReplyCheckpoint(val requestId: String, val completedChunkIds: List<String>, val activeChunkId: String?, val positionSeconds: Double?) {
  fun payload(): Map<String, Any?> = mapOf("requestId" to requestId, "completedChunkIds" to completedChunkIds,
    "activeChunkId" to activeChunkId, "positionSeconds" to positionSeconds)
}
data class NCReplyContinuation(val recoveryEpoch: Long, val replies: List<NCReplyCheckpoint>) {
  fun payload(): Map<String, Any> = mapOf("recoveryEpoch" to recoveryEpoch, "replies" to replies.map { it.payload() })
}
interface NCPlaybackActions {
  // Updated only by the player's native onIsPlayingChanged callback.
  val ncIsPlayingSnapshot: Boolean
  val ncIsAliveSnapshot: Boolean
  val ncItemIdentity: String?
  val ncPlayerIdentity: String? get() = null
  // Read only on the player's application thread. Not a receipt/checkpoint.
  val ncPositionSeconds: Double? get() = null
  fun ncDispatch(effect: () -> Unit)
  fun ncPlay()
  fun ncPause()
  fun ncPauseForLock(permit:NCPlaybackGuard.LockPausePermit) = ncPause()
}

data class NCPlaybackObservation(
  val started: Boolean, val completed: Boolean, val playing: Boolean, val positionSeconds: Double?
)

/** Optional native stream contract. Must stop/fence output synchronously without
 * dispatching to another thread or reentering this guard. Legacy players do not
 * implement this and retain their existing null checkpoint behavior. */
interface NCPlaybackCheckpointActions {
  fun ncStopAndCheckpoint(): Double?
}

class NCAudioFocusLifecycle {
  class Event internal constructor(val request: Long, val epoch: Long)
  private var nextRequest = 0L
  private var nextEpoch = 0L
  private var currentRequest: Long? = null
  private var acquired = false

  @Synchronized fun beginRequest(): Long {
    val request = ++nextRequest
    currentRequest = request
    acquired = false
    return request
  }

  @Synchronized fun currentRequest(): Long? = currentRequest
  @Synchronized fun isAcquired(): Boolean = acquired
  @Synchronized fun markGranted(request: Long): Boolean {
    if (currentRequest != request) return false
    acquired = true
    return true
  }

  @Synchronized fun observe(request: Long): Event =
    if (request == currentRequest) Event(request, ++nextEpoch) else Event(request, -1)
  @Synchronized fun apply(event: Event, nowAcquired: Boolean?): Boolean {
    if (event.request != currentRequest || event.epoch != nextEpoch) return false
    if (nowAcquired != null) acquired = nowAcquired
    return true
  }

  @Synchronized fun abandon(request: Long?) {
    if (request != null && currentRequest == request) {
      currentRequest = null
      acquired = false
      nextEpoch += 1
    }
  }
}

class NCPlaybackGuard(private val maxBindings:Int=16,private val maxRequests:Int=256,private val maxChunksPerRequest:Int=2048){
  /** Issued only by the confirmed service owner; not a wire capability. The
   * output thread checks this without entering the Guard monitor. */
  class LockPausePermit internal constructor(internal val carrier:OrderedCarrierPermit,
    private val ownerActive:java.util.concurrent.atomic.AtomicBoolean) {
    @Volatile private var active=true
    internal fun currentNow()=active &&ownerActive.get() &&carrier.currentNow() &&
      carrier.binding.actions.ncIsAliveSnapshot &&carrier.binding.actions.ncItemIdentity==carrier.item
    internal fun revoke(){active=false}
  }
  /** A visual carrier is not a speech permit. Native-only memberships are
   * separate from the existing single-reply lane. Wire handles confer no grant. */
  internal class OrderedCarrierPermit private constructor(internal val owner:NCPlaybackGuard,
    internal val binding:NCPlaybackBinding,internal val epoch:Long,internal val item:String,
    internal val deadline:NCContinuousMuxedDeadline,internal val elapsedNow:()->Long,
    internal val onCancelled:()->Unit) {
    @Volatile internal var cancelled=false
    internal val replies=linkedMapOf<String,OrderedReplyPermit>()
    internal var focusPaused=false
    internal var userPaused=false
    internal var transportPaused=false
    internal var transportEpoch=0L
    internal var transportPauseActive:java.util.concurrent.atomic.AtomicBoolean?=null
    @Volatile internal var transportCueStop:(()->Unit)?=null
    @Volatile private var clockFailed=false
    @Synchronized internal fun currentNow():Boolean = !cancelled && !clockFailed &&
      try {deadline.active(elapsedNow())}catch(_:RuntimeException){clockFailed=true;false}
    companion object {
      internal fun create(owner:NCPlaybackGuard,binding:NCPlaybackBinding,epoch:Long,item:String,
        deadline:NCContinuousMuxedDeadline,elapsedNow:()->Long,onCancelled:()->Unit)=
        OrderedCarrierPermit(owner,binding,epoch,item,deadline,elapsedNow,onCancelled)
    }
  }
  internal class OrderedReplyPermit private constructor(internal val carrier:OrderedCarrierPermit,
    internal val requestId:String,internal val deadline:NCContinuousMuxedDeadline) {
    internal val chunks=linkedSetOf<String>()
    @Volatile internal var detached=false
    @Volatile internal var released=false
    private var clockFailed=false
    @Synchronized internal fun currentNow():Boolean = !detached &&retainedCurrentNow()
    @Synchronized internal fun retainedCurrentNow():Boolean {
      if(released ||clockFailed ||!carrier.currentNow())return false
      return try{deadline.active(carrier.elapsedNow())}catch(_:RuntimeException){clockFailed=true;false}
    }
    companion object {
      internal fun create(carrier:OrderedCarrierPermit,requestId:String,deadline:NCContinuousMuxedDeadline)=
        OrderedReplyPermit(carrier,requestId,deadline)
    }
  }
  /** Native-only enrollment. Wire run/source handles are never permits. The
   * authority's typed proof adapter is the only continuous receipt caller.
   */
  internal class ContinuousPermit private constructor(internal val owner:NCPlaybackGuard,
    internal val binding:NCPlaybackBinding,internal val epoch:Long,internal val item:String,
    internal val chunks:LinkedHashSet<String>,internal val speechDeadline:NCContinuousMuxedDeadline?,
    internal val onCancelled:()->Unit) {
    @Volatile internal var cancelled=false
    @Volatile internal var speechDetached=false
      private set
    @Volatile internal var visual:VisualPermit?=null
      private set
    internal fun attachVisual(grant:VisualPermit) {visual=grant}
    internal fun detachSpeech() {speechDetached=true}
    companion object {
      internal fun create(owner:NCPlaybackGuard,binding:NCPlaybackBinding,epoch:Long,item:String,chunk:String,
        speechDeadline:NCContinuousMuxedDeadline?,onCancelled:()->Unit)=
        ContinuousPermit(owner,binding,epoch,item,linkedSetOf(chunk),speechDeadline,onCancelled)
    }
  }
  /** Native-only logical visual permission for the same immutable physical
   * binding. It owns no new player/track/focus and cannot renew either deadline.
   * Output hooks can read it without entering the Guard/Authority monitor. */
  internal class VisualPermit private constructor(internal val parent:ContinuousPermit,
    internal val deadline:NCContinuousMuxedDeadline,private val nativeElapsedMs:()->Long) {
    internal val expiresElapsedMs=deadline.expiresElapsedMs
    private val clockLock=Any()
    private var lastElapsed=deadline.capturedElapsedMs
    @Volatile private var expired=false
    internal fun currentNow():Boolean=synchronized(clockLock) {
      if(expired ||parent.cancelled ||parent.visual!==this ||parent.binding.item!=parent.item
        ||parent.binding.actions.ncItemIdentity!=parent.item ||!parent.binding.actions.ncIsAliveSnapshot)return@synchronized false
      val now=try {nativeElapsedMs()}catch(_:RuntimeException){expired=true;return@synchronized false}
      if(now<lastElapsed ||!deadline.active(now)){expired=true;return@synchronized false}
      lastElapsed=now;!parent.cancelled
    }
    companion object {
      internal fun create(parent:ContinuousPermit,deadline:NCContinuousMuxedDeadline,nativeElapsedMs:()->Long)=
        VisualPermit(parent,deadline,nativeElapsedMs)
    }
  }
  enum class RetirementCause(val wireValue:String){ OTHER("other"),EXPLICIT("explicit"),INTERRUPTION("interruption"),AUDIO_FOCUS_LOSS("audio_focus_loss"),ROUTE_CHANGE("route_change"),FOREGROUND_LEFT("foreground_left"),AUDIO_DISABLED("audio_disabled") }
  private enum class Phase{NEGOTIATING,ARMED}; private enum class Kind{PLAY,PAUSE}
  private data class Effect(val b:NCPlaybackBinding,val item:String?,val ticket:String?,val kind:Kind,
    val cancelled:ContinuousPermit?=null,val orderedCancelled:OrderedCarrierPermit?=null)
  private class Reply { val started=mutableListOf<String>(); val seen=mutableSetOf<String>(); val completed=linkedSetOf<String>(); val bound=mutableSetOf<String>(); var closed=false; var unavailable=false; var frozen:NCPhoneReplyReceipt?=null
    var checkpointChunk: String? = null; var checkpointSeconds: Double? = null
  }
  private val lock=Any(); private var ticket:String?=null; private var session:String?=null; private var open=false; private var phase:Phase?=null; private var foregroundOnly=false; private var cause="none"; private var lastRequest:String?=null
  private val bindings=mutableListOf<NCPlaybackBinding>(); private val replies=linkedMapOf<String,Reply>(); private val issued=mutableSetOf<String>(); private val pending=mutableSetOf<String>(); private val acks=mutableMapOf<String,String>(); private var tail:Set<String>?=null
  private var connectionPaused = false
  private var recoveryEpoch = 0L
  private var stopConnectionCue: (() -> Unit)? = null
  private var continuation: NCReplyContinuation? = null
  private var continuationApproved = false
  private var replyPlaybackService:Pair<String,Long>?=null
  private var playbackOwner: BackgroundPlaybackOwner? = null
  data class CaptureAttachment(val ticket:String,val sessionId:String,val captureId:String)
  private class CaptureScope(val attachment:CaptureAttachment) {
    var inputReleased=false
    val uploads=linkedSetOf<String>()
    val acknowledgements=linkedMapOf<String,String>()
    var sealed:Set<String>?=null
  }
  private val captures=linkedMapOf<String,CaptureScope>()
  // Tombstones prohibit a late callback from adopting a replacement input.
  // Capacity is explicit and bounded for the lifetime of this output ticket.
  private val captureSessions=mutableSetOf<String>()
  private var activeCapture:CaptureAttachment?=null

  fun attachCapture(t:String,s:String):CaptureAttachment=synchronized(lock) {
    require(valid(s)) {"capture_session_invalid"}
    check(opened(t)&&phase==Phase.ARMED&&session==null&&!connectionPaused) {"capture_output_unavailable"}
    check(activeCapture==null) {"capture_input_owned"}
    check(s !in captureSessions) {"capture_session_reused"}
    check(captureSessions.size<maxRequests) {"capture_scope_capacity"}
    CaptureAttachment(t,s,UUID.randomUUID().toString()).also {
      captureSessions+=s;captures[s]=CaptureScope(it);activeCapture=it
    }
  }
  private fun captureScope(t:String,s:String)=captures[s]?.takeIf{opened(t)&&it.attachment.ticket==t}
  fun captureCurrent(a:CaptureAttachment)=synchronized(lock) {
    opened(a.ticket)&&activeCapture==a&&captureScope(a.ticket,a.sessionId)?.inputReleased==false
  }
  fun detachCapture(a:CaptureAttachment)=synchronized(lock) {
    val scope=captureScope(a.ticket,a.sessionId)
    if(scope?.attachment!=a)false else {
      scope.inputReleased=true
      if(activeCapture==a)activeCapture=null
      true
    }
  }
  fun captureState(a:CaptureAttachment):Map<String,Any?> = synchronized(lock) {
    val scope=captureScope(a.ticket,a.sessionId)?.takeIf{it.attachment==a}
    mapOf("attached" to (scope!=null),"inputReleased" to (scope?.inputReleased==true),
      "pendingReplyCount" to (scope?.let {it.uploads.size+it.acknowledgements.values.toSet().count{r->replies[r]?.closed==false}}?:0))
  }

  /** Service-only capability. It cannot admit replies or renew stream deadlines. */
  inner class BackgroundPlaybackOwner internal constructor(
    private val issuedTicket:String, internal val actions:NCPlaybackActions
  ) {
    internal var confirmed=false
    internal var locked=false
    private val pauseOwnerActive=java.util.concurrent.atomic.AtomicBoolean(true)
    fun current()=synchronized(lock){current0()}
    private fun current0()=playbackOwner===this && opened(issuedTicket) && session==null &&
      phase==Phase.ARMED && actions.ncIsAliveSnapshot
    fun confirm()=synchronized(lock){if(!current0())false else {confirmed=true;true}}
    fun ready()=synchronized(lock){current0()&&confirmed}
    fun pauseForLock() {
      val pause=synchronized(lock){if(!current0()||locked)false else{
        locked=true
        bindings.filter{it.actions===actions}.forEach{it.orderedCarrier?.let{p->
          val stop=p.transportCueStop;p.transportCueStop=null;stop?.invoke()
        }}
        true
      }}
      if(pause)actions.ncDispatch {
        val permit=synchronized(lock) {
          if(!current0()||!confirmed||!locked)null else {
            val carrier=bindings.firstOrNull{it.actions===actions &&eligible(it)}?.orderedCarrier
            if(carrier==null ||!orderedCarrierEligible0(carrier))null else {
              // Each queued command closes its own permit. A fast second lock
              // must not revoke the first command before the output consumes it.
              LockPausePermit(carrier,pauseOwnerActive)
            }
          }
        }
        if(permit!=null)try {actions.ncPauseForLock(permit)}catch(error:RuntimeException) {
          permit.revoke();invalidateOrderedCarrier(permit.carrier);throw error
        } else if(synchronized(lock){current0()&&locked})actions.ncPause()
      }
    }
    fun resumeForeground() = mutate<Unit> { effects ->
      if(current0()&&confirmed&&locked) {
        locked=false
        bindings.filter{it.actions===actions&&it.orderedCarrier!=null&&eligible(it)}.forEach {
          effects+=Effect(it,it.actions.ncItemIdentity,it.ticket,Kind.PLAY)
        }
      }
    }
    fun release()=synchronized(lock){pauseOwnerActive.set(false);if(playbackOwner===this)playbackOwner=null}
    fun retire()=mutate<Unit>{effects->if(current0())close(RetirementCause.EXPLICIT,effects)}
  }

  fun backgroundPlaybackOwner(t:String,playerId:String):BackgroundPlaybackOwner?=synchronized(lock) {
    if(!opened(t)||session!=null||phase!=Phase.ARMED||playbackOwner!=null)return@synchronized null
    val binding=bindings.firstOrNull {it.ticket==t && it.actions.ncPlayerIdentity==playerId &&
      it.actions.ncIsAliveSnapshot && it.orderedCarrier!=null && eligible(it)} ?: return@synchronized null
    BackgroundPlaybackOwner(t,binding.actions).also{playbackOwner=it}
  }
  private fun retainedPlayback()=playbackOwner?.ready()==true
  private fun playbackUnlocked(b:NCPlaybackBinding)=b.orderedCarrier?.transportPaused!=true &&
    b.orderedCarrier?.userPaused!=true &&b.orderedCarrier?.focusPaused!=true &&
    playbackOwner?.let{it.actions!==b.actions||!it.locked}!=false

  fun pauseReplyContinuation(t: String, s: String, epoch: Long): NCReplyContinuation? = mutate { effects ->
    if (!opened(t) || !captureOrOutputSession(t,s) || phase != Phase.ARMED || tail != null || epoch <= 0 || epoch < recoveryEpoch) return@mutate null
    if (epoch == recoveryEpoch) return@mutate continuation.takeIf { connectionPaused }
    val checkpoints = replies.filterValues { !it.closed }.map { (id, reply) ->
      val active = reply.started.lastOrNull { it !in reply.completed }
      val native = bindings.singleOrNull { it.ticket == t && it.requestId == id && it.chunkId == active && !it.terminal }
        ?.actions as? NCPlaybackCheckpointActions
      // No ExoPlayer cross-thread reads or guessed elapsed time. Only a native
      // output that can stop atomically supplies a confirmed source checkpoint.
      val position = native?.ncStopAndCheckpoint()?.takeIf { it.isFinite() && it >= 0 }
        ?: reply.checkpointSeconds.takeIf { active != null && reply.checkpointChunk == active }
      NCReplyCheckpoint(id, reply.completed.toList(), active, position)
    }
    recoveryEpoch = epoch; connectionPaused = true; continuationApproved = false; stopCue()
    continuation = NCReplyContinuation(epoch, checkpoints)
    bindings.filter { it.ticket == t }.forEach { terminate(it, effects) }; bindings.clear()
    pending.clear(); acks.clear(); captures.values.forEach{it.uploads.clear()}
    continuation
  }
  fun prepareReplyContinuation(t: String, s: String, epoch: Long, ids: List<String>) = mutate { effects ->
    val sealed = continuation
    if (!opened(t) || !captureOrOutputSession(t,s) || !connectionPaused || recoveryEpoch != epoch || sealed == null ||
      ids.size > 3 || ids.toSet().size != ids.size || ids.any { id -> sealed.replies.none { it.requestId == id } || replies[id]?.closed != false }) false
    else {
      sealed.replies.filter { it.requestId !in ids }.forEach { closeReply(it.requestId, false, effects) }
      continuationApproved = true; true
    }
  }

  fun begin(expectedTicket:String?,sessionId:String,foregroundOnly:Boolean)=synchronized(lock){ require(valid(sessionId)); check(ticket==expectedTicket){"stale ticket"}; check(!open){"retirement required"}; issue(sessionId,Phase.NEGOTIATING,foregroundOnly) }
  fun beginForegroundOutput(expectedTicket:String?)=synchronized(lock){ check(ticket==expectedTicket){"stale ticket"}; check(!open){"retirement required"}; issue(null,Phase.ARMED,true) }
  private fun issue(s:String?,p:Phase,f:Boolean):String{ val n=UUID.randomUUID().toString(); ticket=n;session=s;open=true;phase=p;foregroundOnly=f;cause="none";connectionPaused=false;recoveryEpoch=0;continuation=null;continuationApproved=false;playbackOwner=null;replyPlaybackService=null;return n }
  fun isOpen(t:String)=synchronized(lock){opened(t)}; fun currentTicket()=synchronized(lock){ticket}; fun protectedSessionId(t:String)=synchronized(lock){session.takeIf{opened(t)}}
  fun outputState()=synchronized(lock){NCPlaybackOutputState(ticket,session,open,phase==Phase.ARMED,cause)}
  // Read-only permission for a local UI tone; never acquires or renews ownership.
  fun characterCueTicket(): String? = synchronized(lock) {
    ticket.takeIf { open && phase == Phase.ARMED && !connectionPaused &&
      bindings.any { eligible(it) && it.actions.ncIsPlayingSnapshot } }
  }
  fun arm(t:String,s:String)=synchronized(lock){if(!opened(t)||session!=s||phase!=Phase.NEGOTIATING)false else{phase=Phase.ARMED;true}}
  fun retire(t:String,c:RetirementCause=RetirementCause.EXPLICIT)=mutate<Unit>{if(ticket==t)close(c,it)}
  fun pauseConnection(t: String, s: String, epoch: Long) = mutate { effects ->
    if (!opened(t) || !captureOrOutputSession(t,s) || phase != Phase.ARMED || tail != null || epoch <= 0 || epoch < recoveryEpoch) false
    else if (epoch == recoveryEpoch) connectionPaused
    else {
      recoveryEpoch = epoch; connectionPaused = true
      stopCue()
      bindings.filter { it.ticket == t }.forEach { terminate(it, effects) }
      bindings.clear()
      // Keep tombstones so old IDs cannot become fresh reply/upload admissions.
      replies.values.forEach { it.closed = true; it.unavailable = true; it.frozen = null }
      pending.clear(); acks.clear(); captures.values.forEach{it.uploads.clear()}; lastRequest = null
      true
    }
  }
  fun resumeConnection(t: String, s: String, epoch: Long) = synchronized(lock) {
    if (!opened(t) || !captureOrOutputSession(t,s) || !connectionPaused || recoveryEpoch != epoch || tail != null || (continuation != null && !continuationApproved)) false
    else { stopCue(); connectionPaused = false; continuation = null; continuationApproved = false; true }
  }
  // Cue effects touch only a local AudioTrack, never another queue or audio focus.
  fun performConnectionCue(t: String, s: String, epoch: Long, stop: () -> Unit, play: () -> Boolean) = synchronized(lock) {
    if (!opened(t) || !captureOrOutputSession(t,s) || !connectionPaused || recoveryEpoch != epoch) false
    else {
      stopCue(); stopConnectionCue = stop
      val started = play()
      if (!opened(t) || !captureOrOutputSession(t,s) || !connectionPaused || recoveryEpoch != epoch) { stopCue(); false } else started
    }
  }
  private fun stopCue() { val stop = stopConnectionCue; stopConnectionCue = null; stop?.invoke() }
  fun retireProtected(c:RetirementCause=RetirementCause.OTHER)=mutate<Unit>{if(open&&session!=null)close(c,it)}
  fun retireIfCurrent(observed: String?, retirementCause: RetirementCause) = mutate { effects ->
    if (observed == null || !opened(observed)) false
    else { close(retirementCause, effects); true }
  }

  // True lets capture ignore expected setup notifications; false tells it to
  // stop invalid input. Neither outcome retires the independent visual owner.
  fun retireForRouteChange(observed: String?) = synchronized(lock) {
    observed != null && opened(observed) &&
      (phase == Phase.NEGOTIATING || NCCommunicationRoute.shared.isPreparing(observed))
  }
  fun retireForegroundOnly(c:RetirementCause=RetirementCause.FOREGROUND_LEFT)=mutate<Unit>{if(open&&foregroundOnly&&!retainedPlayback()&&!retainedReply())close(c,it)}
  // No global audio-mode mutation: authorization expires with this exact ticket.
  fun confirmReplyPlayback(t:String,generation:Long)=synchronized(lock) {
    if(!opened(t)||session!=null||phase!=Phase.ARMED)false else {replyPlaybackService=t to generation;true}
  }
  fun releaseReplyPlayback(t:String,generation:Long)=synchronized(lock) {
    if(replyPlaybackService==(t to generation))replyPlaybackService=null
  }
  private fun retainedReply()=open&&phase==Phase.ARMED&&replyPlaybackService?.first==ticket
  fun retainsBackgroundFocus()=synchronized(lock){backgroundAuthorized()||retainedPlayback()||retainedReply()}
  internal fun allowsBackgroundPlayback(b:NCPlaybackBinding)=synchronized(lock){(backgroundAuthorized()||retainedReply()||(retainedPlayback()&&playbackOwner?.actions===b.actions))&&b.attempted&&(b.requestId!=null||b.orderedCarrier!=null||retainedReply())&&eligible(b)}
  private fun backgroundAuthorized()=open&&session!=null&&phase==Phase.ARMED&&!foregroundOnly

  fun admitForegroundReply(t:String,r:String)=synchronized(lock){
    opened(t)&&phase==Phase.ARMED&&!connectionPaused&&session==null&&activeCapture==null&&valid(r)&&
      captures.values.none{r in it.acknowledgements.values}&&replies[r]?.closed!=true&&ensure(r)
  }
  fun registerReplySubmission(t:String,s:String,u:String)=synchronized(lock){
    val capture=captureScope(t,s)
    if(capture!=null) {
      if(!scope(t,s)||capture.inputReleased||capture.sealed!=null||!valid(u))false
      else if(u in capture.uploads)true
      else if(u in issued||issued.size>=maxRequests||pending.size>=2)false
      else {issued+=u;pending+=u;capture.uploads+=u;true}
    } else if(!scope(t,s)||tail!=null||!valid(u))false else if(u in pending)true else if(u in issued||issued.size>=maxRequests||pending.size>=2)false else{issued+=u;pending+=u;true}}
  fun admitReplyForUpload(t:String,s:String,u:String,r:String)=synchronized(lock){
    val capture=captureScope(t,s)
    if(capture!=null) {
      if(connectionPaused||!valid(r))false
      else capture.acknowledgements[u]?.let{it==r&&replies[r]?.closed==false}?:if(u !in capture.uploads||
        (replies[r]!=null&&(replies[r]?.closed==true||r !in capture.acknowledgements.values))||!ensure(r))false
      else {capture.uploads-=u;pending-=u;capture.acknowledgements[u]=r;capture.sealed=capture.sealed?.plus(r);true}
    } else if(!scope(t,s)||!valid(r))false else acks[u]?.let{it==r}?:if(u !in pending||replies[r]?.closed==true||!ensure(r))false else{pending-=u;acks[u]=r;tail=tail?.plus(r);true}}
  fun abandonSubmittedUpload(t:String,s:String,u:String)=synchronized(lock){
    val capture=captureScope(t,s)
    if(capture!=null) {if(capture.uploads.remove(u))pending-=u}
    else if(scope(t,s))pending-=u
  }
  // Used by native Activity backgrounding before JS can acknowledge Live-off.
  fun currentReplyTailPermit(t: String, s: String): Pair<List<String>, List<String>>? = synchronized(lock) {
    if (!scope(t, s) || phase != Phase.ARMED) null
    else replies.filterValues { !it.closed }.keys.toList() to pending.toList()
  }
  fun sealReplyTail(t:String,s:String,rs:List<String>,us:List<String>)=mutate<List<String>?>{e->
    val capture=captureScope(t,s)
    if(capture!=null) {
      val owned=capture.acknowledgements.values.filter{replies[it]?.closed==false}.toSet()
      if(connectionPaused||phase!=Phase.ARMED||capture.sealed!=null||rs.size>3||us.size>2||rs.size+us.size>3||
        rs.toSet().size!=rs.size||us.toSet().size!=us.size||rs.toSet()!=owned||us.any{it !in capture.uploads})return@mutate null
      pending.removeAll(capture.uploads-us.toSet());capture.uploads.retainAll(us.toSet())
      capture.sealed=owned
      return@mutate owned.sorted()
    }
    if(!scope(t,s)||tail!=null||rs.size>3||us.size>2||rs.size+us.size>3||rs.toSet().size!=rs.size||us.toSet().size!=us.size||rs.any{replies[it]?.closed!=false}||us.any{it !in pending})null else{
      val c=rs.toSet();if(c!=replies.filterValues{!it.closed}.keys)null else{
        pending.retainAll(us.toSet());tail=c
        // Ordered carriers span idle and several separately admitted replies.
        // Their binding has no single requestId; per-reply admission still
        // restricts speech to the sealed tail (including its pending uploads).
        bindings.filter{it.ticket==t && !(it.orderedCarrier!=null && (c.isNotEmpty()||pending.isNotEmpty()))
          && (it.requestId==null||it.requestId !in c)}.forEach{terminate(it,e)}
        c.sorted()}}}
  private fun finishCaptureTail(capture:CaptureScope,done:List<String>):Boolean {
    val expected=capture.sealed?:return false
    if(done.size!=done.toSet().size||done.toSet()!=expected||capture.uploads.isNotEmpty()||
      expected.any {r->replies[r]?.closed!=true ||bindings.any {b->b.orderedCarrier?.replies?.containsKey(r)==true ||
        (b.requestId==r&&(!b.terminal||b.actions.ncIsPlayingSnapshot)&&!completedVisualMembership(b))}})return false
    return true
  }
  fun finishReplyTail(t:String,s:String,done:List<String>)=mutate{e->
    captureScope(t,s)?.let{return@mutate finishCaptureTail(it,done)}
    val x=tail;if(x==null||!scope(t,s)||done.toSet()!=x||pending.isNotEmpty()||bindings.any{it.ticket==t&&(!it.terminal||it.actions.ncIsPlayingSnapshot)})false else{close(RetirementCause.OTHER,e);true}}
  fun finishEmptyTail(t:String,s:String)=mutate{e->
    captureScope(t,s)?.let{return@mutate finishCaptureTail(it,emptyList())}
    if(!scope(t,s)||replies.values.any{!it.closed}||pending.isNotEmpty()||bindings.any{!it.terminal||it.actions.ncIsPlayingSnapshot})false else{close(RetirementCause.OTHER,e);true}}

  fun freezePhoneReplyReceipt(t:String,r:String,i:String)=mutate<NCPhoneReplyReceipt?>{e->if(connectionPaused||!opened(t)||!valid(i))null else freeze(r,i,e)}
  fun freezeCurrentPhoneReplyReceipt(ticket: String, sessionId: String, interruptionId: String) =
    mutate<NCPhoneReplyOnset> { effects ->
      if (!scope(ticket, sessionId) || !valid(interruptionId)) return@mutate NCPhoneReplyOnset.Unavailable
      replies.values.mapNotNull { it.frozen }.firstOrNull { it.interruptionId == interruptionId }?.let {
        return@mutate NCPhoneReplyOnset.Receipt(it)
      }
      val active = bindings.mapNotNull { binding ->
        binding.requestId.takeIf {
          // Completed speech may retain this binding solely for final idle video.
          // That visual owner is not a reply that microphone onset can interrupt.
          it != null && replies[it]?.closed == false && eligible(binding) && binding.started && binding.actions.ncIsPlayingSnapshot
        }
      }.toMutableSet()
      lastRequest?.let { request ->
        if (replies[request]?.let { !it.closed && it.started.isNotEmpty() } == true) active += request
      }
      if (active.isEmpty()) {
        return@mutate if (lastRequest?.let { replies[it]?.unavailable } == true || replies.values.any { it.unavailable })
          NCPhoneReplyOnset.Unavailable else NCPhoneReplyOnset.None
      }
      if (active.size != 1) {
        active.forEach { closeReply(it, true, effects) }
        return@mutate NCPhoneReplyOnset.Unavailable
      }
      freeze(active.first(), interruptionId, effects)?.let { NCPhoneReplyOnset.Receipt(it) }
        ?: NCPhoneReplyOnset.Unavailable
    }
  private fun freeze(r:String,i:String,e:MutableList<Effect>):NCPhoneReplyReceipt?{val x=replies[r]?:return null;if(x.unavailable)return null;x.frozen?.let{return it.takeIf{z->z.interruptionId==i}};if(x.closed||replies.values.any{it.frozen?.interruptionId==i})return null;val out=NCPhoneReplyReceipt(r,i,x.started.toList());x.frozen=out;closeReply(r,false,e);return out}
  fun skipPhoneReplyAudio(t:String,r:String)=mutate{e->if(!opened(t)||!valid(r)||replies[r]==null)false else{closeReply(r,false,e);true}}
  fun finishPhoneReplyAudio(t:String,r:String)=mutate{e->if(!opened(t)||replies[r]==null||bindings.any{
    it.ticket==t&&((it.requestId==r&&(!it.terminal||it.actions.ncIsPlayingSnapshot)&&!completedVisualMembership(it))
      ||it.orderedCarrier?.replies?.get(r)?.let {p->!p.detached&&!p.released}==true)
  })false else{closeReply(r,false,e,normalCompletion=true);true}}

  fun newBinding(a:NCPlaybackActions)=NCPlaybackBinding(this,a)
  internal fun bind(b:NCPlaybackBinding,t:String)=mutate{e->bind0(b,t,e)}
  private fun bind0(b:NCPlaybackBinding,t:String,e:MutableList<Effect>,rejected:(String)->Unit={}):Boolean {
    if(b.attempted) {
      val accepted=!connectionPaused&&!b.terminal&&b.ticket==t&&opened(t)
      if(!accepted) rejected(if(connectionPaused) "connection_paused" else "binding_not_current")
      return accepted
    }
    b.attempted=true
    val reason=when { connectionPaused->"connection_paused"; b.used->"binding_already_used";
      b.terminal->"binding_terminal"; !opened(t)->"owner_not_open";
      bindings.size>=maxBindings->"binding_capacity"; else->null }
    if(reason!=null) { rejected(reason);b.terminal=true;if(bindings.size>=maxBindings)close(RetirementCause.OTHER,e);return false }
    b.ticket=t;bindings+=b;return true
  }
  internal fun bindChunk(b:NCPlaybackBinding,t:String,r:String,c:String,rejected:(String)->Unit={})=mutate{e->
    if(b.orderedCarrier!=null){rejected("ordered_carrier_binding");return@mutate false}
    if(b.requestId!=null) {
      val accepted=b.requestId==r&&b.chunkId==c&&b.item==b.actions.ncItemIdentity&&eligible(b)
      if(!accepted) rejected("binding_identity_mismatch")
      return@mutate accepted
    }
    val reason=when { !valid(r)||!valid(c)->"invalid_descriptor"; b.used->"binding_already_used";
      !opened(t)->"owner_not_open"; tail!=null&&r !in tail!!->"request_outside_tail"; else->null }
    if(reason!=null) rejected(reason)
    if(reason!=null||!bind0(b,t,e,rejected)){terminate(b,e);return@mutate false}
    // Ordinary foreground output has no protected upload-admission phase.
    if(session==null && replies[r]==null && (captureAdmissionRequired()||!ensure(r))) { rejected("reply_admission");terminate(b,e);return@mutate false }
    val x=replies[r];if(x?.closed!=false){rejected(if(x==null) "request_not_submitted" else "reply_closed");terminate(b,e);return@mutate false}
    if(c !in x.bound&&x.bound.size>=maxChunksPerRequest){rejected("chunk_capacity");closeReply(r,true,e);return@mutate false};val item=b.actions.ncItemIdentity;if(item==null){rejected("item_missing");terminate(b,e);return@mutate false};x.bound+=c;b.requestId=r;b.chunkId=c;b.item=item;true}
  internal fun play(b:NCPlaybackBinding)=mutate{e->b.used=true;if(!eligible(b)||!playbackUnlocked(b))false else{e+=Effect(b,b.item?:b.actions.ncItemIdentity,b.ticket,Kind.PLAY);true}}
  internal fun systemPlay(b:NCPlaybackBinding,item:String?)=mutate{e->if(!controls(b)||!playbackUnlocked(b)||b.actions.ncItemIdentity!=item)false else{e+=Effect(b,item,b.ticket,Kind.PLAY);true}}
  internal fun acknowledge(b:NCPlaybackBinding)=mutate{e->if(b.continuousPermit!=null)return@mutate false;val r=b.requestId?:return@mutate false;val x=replies[r];if(!eligible(b)||!b.used||!b.actions.ncIsPlayingSnapshot||b.item!=b.actions.ncItemIdentity||x==null){if(b.actions.ncIsPlayingSnapshot)e+=Effect(b,b.item,b.ticket,Kind.PAUSE);false}else{val c=b.chunkId?:return@mutate false;b.started=true;lastRequest=r;if(c in x.seen)true else{x.seen+=c;x.started+=c;true}}}
  internal fun pause(b:NCPlaybackBinding)=mutate<Unit>{e->
    if(b.continuousPermit!=null||b.orderedCarrier!=null)terminate(b,e)
    else e+=Effect(b,b.item?:b.actions.ncItemIdentity,b.ticket,Kind.PAUSE)}
  internal fun completed(b: NCPlaybackBinding) = synchronized(lock) {
    val reply = replies[b.requestId]
    val chunk = b.chunkId
    if (b.continuousPermit!=null || b.orderedCarrier!=null || !eligible(b) || !b.started || chunk == null || reply == null) false
    else { reply.completed += chunk; true }
  }

  internal fun enrollOrderedCarrier(b:NCPlaybackBinding,t:String,epoch:Long,
    deadline:NCContinuousMuxedDeadline,elapsedNow:()->Long,onCancelled:()->Unit):OrderedCarrierPermit?=synchronized(lock) {
    val item=b.actions.ncItemIdentity?:return@synchronized null
    // A recovered visual-first binding has no reply yet. Validate the exact
    // resumed owner directly; ordinary eligible() needs an enrolled membership.
    if(b !in bindings ||!b.attempted ||b.terminal ||connectionPaused ||!opened(t)
      ||phase!=Phase.ARMED ||!b.actions.ncIsAliveSnapshot ||b.used ||b.started
      ||b.actions.ncIsPlayingSnapshot ||b.continuousPermit!=null ||b.orderedCarrier!=null
      ||b.ticket!=t ||b.requestId!=null ||b.chunkId!=null ||epoch!=recoveryEpoch)return@synchronized null
    val permit=OrderedCarrierPermit.create(this,b,epoch,item,deadline,elapsedNow,onCancelled)
    if(!permit.currentNow())return@synchronized null
    b.item=item;b.orderedCarrier=permit;permit
  }
  private fun orderedCarrierEligible0(p:OrderedCarrierPermit):Boolean = p.owner===this && !p.cancelled
    &&p.binding in bindings &&p.binding.orderedCarrier===p &&p.epoch==recoveryEpoch
    &&p.binding.item==p.item &&p.binding.actions.ncItemIdentity==p.item
    &&p.binding.actions.ncIsAliveSnapshot &&eligible(p.binding) &&p.currentNow()
  internal fun orderedCarrierEligible(p:OrderedCarrierPermit):Boolean=synchronized(lock){orderedCarrierEligible0(p)}
  /** Reuse the exact native temporary-pause permit; this changes neither the
   * carrier's admission epoch nor capture ownership. Only play is held. */
  /** User intent is independent of lock and connection recovery. It cannot
   * change carrier epochs, source deadlines, journal cursors or receipts. */
  internal fun orderedUserPauseState(b:NCPlaybackBinding,t:String):Boolean?=synchronized(lock) {
    val p=b.orderedCarrier?:return@synchronized null
    if(b.ticket!=t ||!orderedCarrierEligible0(p))null else p.userPaused
  }
  internal fun orderedUserPauseState(p:OrderedCarrierPermit):Boolean?=synchronized(lock) {
    if(!orderedCarrierEligible0(p))null else p.userPaused
  }
  internal fun pauseOrderedFocus(b:NCPlaybackBinding,t:String):LockPausePermit?=synchronized(lock) {
    val p=b.orderedCarrier?:return@synchronized null
    if(b.ticket!=t ||!orderedCarrierEligible0(p))return@synchronized null
    p.focusPaused=true
    val stop=p.transportCueStop;p.transportCueStop=null;stop?.invoke()
    LockPausePermit(p,java.util.concurrent.atomic.AtomicBoolean(true))
  }
  internal fun resumeOrderedFocus(b:NCPlaybackBinding,t:String):Boolean=mutate {effects->
    val p=b.orderedCarrier?:return@mutate false
    if(b.ticket!=t ||!orderedCarrierEligible0(p))return@mutate false
    p.focusPaused=false
    if(playbackUnlocked(b))effects+=Effect(b,p.item,t,Kind.PLAY)
    true
  }
  internal fun pauseOrderedUser(b:NCPlaybackBinding,t:String):LockPausePermit?=synchronized(lock) {
    val p=b.orderedCarrier?:return@synchronized null
    if(b.ticket!=t ||!orderedCarrierEligible0(p))return@synchronized null
    p.userPaused=true
    val stop=p.transportCueStop;p.transportCueStop=null;stop?.invoke()
    LockPausePermit(p,java.util.concurrent.atomic.AtomicBoolean(true))
  }
  internal fun resumeOrderedUser(b:NCPlaybackBinding,t:String):Boolean=mutate {effects->
    val p=b.orderedCarrier?:return@mutate false
    if(b.ticket!=t ||!orderedCarrierEligible0(p))return@mutate false
    p.userPaused=false
    if(playbackUnlocked(b))effects+=Effect(b,p.item,t,Kind.PLAY)
    true
  }
  internal fun pauseOrderedTransport(p:OrderedCarrierPermit,epoch:Long):LockPausePermit?=synchronized(lock) {
    if(!orderedCarrierEligible0(p) ||epoch !in 1..9007199254740991L ||epoch<p.transportEpoch
      ||epoch==p.transportEpoch&&!p.transportPaused)return@synchronized null
    p.transportPauseActive?.set(false)
    val active=java.util.concurrent.atomic.AtomicBoolean(true)
    p.transportEpoch=epoch;p.transportPaused=true;p.transportPauseActive=active
    LockPausePermit(p,active)
  }
  internal fun resumeOrderedTransport(p:OrderedCarrierPermit,epoch:Long):Boolean=mutate {effects->
    if(!orderedCarrierEligible0(p) ||!p.transportPaused ||epoch!=p.transportEpoch)return@mutate false
    val stop=p.transportCueStop;p.transportCueStop=null;stop?.invoke()
    p.transportPauseActive?.set(false);p.transportPauseActive=null;p.transportPaused=false
    if(playbackUnlocked(p.binding))effects+=Effect(p.binding,p.item,p.binding.ticket,Kind.PLAY)
    true
  }
  internal fun performOrderedConnectionCue(p:OrderedCarrierPermit,epoch:Long,stop:()->Unit,play:()->Boolean):Boolean=synchronized(lock) {
    fun current()=orderedCarrierEligible0(p) &&!p.userPaused &&!p.focusPaused &&p.transportPaused &&p.transportEpoch==epoch &&
      playbackOwner?.let{it.actions!==p.binding.actions||!it.locked}!=false
    if(!current())return@synchronized false
    val previous=p.transportCueStop;p.transportCueStop=null;previous?.invoke()
    p.transportCueStop=stop
    val started=play()
    if(!current()){p.transportCueStop=null;stop();false}else started
  }
  // Evidence from the exact cancelled carrier, never an arbitrary last receipt.
  // Only a still-owned Live session may replace output after microphone onset.
  internal fun orderedInterruption(p:OrderedCarrierPermit):NCPhoneReplyReceipt?=synchronized(lock){
    if(p.owner!==this ||!p.cancelled ||(session==null&&activeCapture==null) ||!opened(p.binding.ticket?:"")
      ||p.epoch!=recoveryEpoch ||p.binding.orderedCarrier!==p)return@synchronized null
    p.replies.keys.mapNotNull {replies[it]?.frozen}.singleOrNull()
  }
  internal fun invalidateOrderedCarrier(p:OrderedCarrierPermit)=mutate<Unit>{e->
    if(p.owner===this &&p.binding.orderedCarrier===p)terminate(p.binding,e)
  }
  private fun orderedReplyEligible0(p:OrderedReplyPermit):Boolean {
    val carrier=p.carrier
    if(!orderedCarrierEligible0(carrier) ||p.released ||p.detached
      ||carrier.replies[p.requestId]!==p ||replies[p.requestId]?.closed!=false)return false
    return p.currentNow()
  }
  internal fun admitOrderedReply(carrier:OrderedCarrierPermit,r:String,
    deadline:NCContinuousMuxedDeadline,rejected:(String)->Unit={}):OrderedReplyPermit?=synchronized(lock) {
    fun reject(reason:String):OrderedReplyPermit? {try{rejected(reason)}catch(_:Exception){};return null}
    if(!orderedCarrierEligible0(carrier))return@synchronized reject("carrier_eligibility")
    if(!valid(r))return@synchronized reject("reply_identity")
    if(r in carrier.replies)return@synchronized reject("reply_already_admitted")
    if(carrier.replies.size>=2)return@synchronized reject("reply_capacity")
    if(tail!=null&&r !in tail!!)return@synchronized reject("reply_not_in_tail")
    if(session==null&&replies[r]==null&&(captureAdmissionRequired()||!ensure(r)))return@synchronized reject("foreground_admission")
    val reply=replies[r]?:return@synchronized reject("reply_missing")
    if(reply.closed)return@synchronized reject("reply_closed")
    if(reply.seen.isNotEmpty())return@synchronized reject("reply_already_started")
    val permit=OrderedReplyPermit.create(carrier,r,deadline)
    if(!try{deadline.active(carrier.elapsedNow())}catch(_:RuntimeException){false})return@synchronized reject("reply_deadline")
    carrier.replies[r]=permit;permit
  }
  internal fun admitOrderedChunk(p:OrderedReplyPermit,c:String):Boolean=synchronized(lock) {
    val reply=replies[p.requestId]
    if(!orderedReplyEligible0(p) ||!valid(c) ||reply==null ||c in reply.seen
      ||p.chunks.size>=64 ||(c !in reply.bound&&reply.bound.size>=maxChunksPerRequest))false
    else{p.chunks+=c;reply.bound+=c;true}
  }
  /** Native proof adapter only, just like commitContinuousReceipts. The callback
   * validates sink/model evidence and actual queue ACKs, not JS booleans. */
  internal fun commitOrderedReceipts(p:OrderedReplyPermit,events:List<Pair<String,Boolean>>,
    validate:()->Boolean):Boolean=synchronized(lock) {
    val b=p.carrier.binding;val reply=replies[p.requestId]
    if(!orderedReplyEligible0(p) ||!b.used ||reply==null ||events.isEmpty() ||events.size>128
      ||!validate())return@synchronized false
    val seen=reply.seen.toMutableSet();val started=reply.started.toMutableList();val completed=reply.completed.toMutableSet()
    for((chunk,onset) in events) {
      if(chunk !in p.chunks)return@synchronized false
      if(onset &&chunk !in seen) {
        if(started.any{it !in completed} ||p.chunks.takeWhile{it!=chunk}.any{it !in seen||it !in completed})return@synchronized false
        // One physical output must never acknowledge overlapping replies.
        if(p.carrier.replies.values.any {other->other!==p &&!other.detached &&
          replies[other.requestId]?.let{it.started.any{c->c !in it.completed}}==true})return@synchronized false
        seen+=chunk;started+=chunk
      } else if(!onset) {
        if(chunk !in seen)return@synchronized false
        completed+=chunk
      }
    }
    reply.seen.clear();reply.seen+=seen;reply.started.clear();reply.started+=started
    reply.completed.clear();reply.completed+=completed
    if(events.any{it.second}){b.started=true;lastRequest=p.requestId}
    true
  }
  internal fun completeOrderedReply(p:OrderedReplyPermit,validate:()->Boolean):Boolean=synchronized(lock) {
    val reply=replies[p.requestId]
    if(!orderedReplyEligible0(p) ||reply==null ||p.chunks.isEmpty()
      ||p.chunks.any{it !in reply.seen ||it !in reply.completed} ||!validate())return@synchronized false
    p.detached=true;true
  }
  internal fun releaseOrderedReply(p:OrderedReplyPermit,readersClosed:()->Boolean):Boolean=synchronized(lock) {
    if(p.carrier.owner!==this ||p.carrier.replies[p.requestId]!==p ||p.released
      ||!p.detached ||!readersClosed())return@synchronized false
    p.released=true;p.carrier.replies.remove(p.requestId);true
  }

  internal fun enrollContinuous(b:NCPlaybackBinding,t:String,r:String,c:String,epoch:Long,
    speechDeadline:NCContinuousMuxedDeadline?=null,onCancelled:()->Unit={}):ContinuousPermit? = synchronized(lock) {
    if(b !in bindings || !eligible(b) || !b.actions.ncIsAliveSnapshot || b.used || b.started
      || b.actions.ncIsPlayingSnapshot || b.continuousPermit!=null || b.orderedCarrier!=null || b.ticket!=t || b.requestId!=r
      || b.chunkId!=c || b.item==null || b.item!=b.actions.ncItemIdentity || epoch!=recoveryEpoch
      || replies[r]?.let {it.closed || c in it.seen}!=false)return@synchronized null
    ContinuousPermit.create(this,b,epoch,b.item!!,c,speechDeadline,onCancelled).also {b.continuousPermit=it}
  }
  private fun continuousEligible0(p:ContinuousPermit):Boolean = p.owner===this && !p.cancelled
    && p.binding.continuousPermit===p && p.epoch==recoveryEpoch && p.binding.item==p.item
    && p.binding.actions.ncItemIdentity==p.item && p.binding.actions.ncIsAliveSnapshot && eligible(p.binding)
  internal fun continuousEligible(p:ContinuousPermit):Boolean=synchronized(lock){continuousEligible0(p)}
  /** Exact native reservation validation runs in the owning Authority transaction;
   * no public RPC accepts the callback as proof. Grant precedes decoder exposure. */
  internal fun admitContinuousVisual(p:ContinuousPermit,deadline:NCContinuousMuxedDeadline,
    nativeElapsedMs:()->Long,validate:()->Boolean):VisualPermit?=synchronized(lock) {
    val speech=p.speechDeadline?:return@synchronized null
    val now=try {nativeElapsedMs()}catch(_:RuntimeException){return@synchronized null}
    if(!continuousEligible0(p) ||p.visual!=null ||p.speechDetached
      ||deadline.capturedElapsedMs<speech.capturedElapsedMs ||deadline.capturedElapsedMs>now
      ||deadline.expiresElapsedMs>speech.expiresElapsedMs
      ||deadline.expiresElapsedMs-deadline.capturedElapsedMs !in 1..6000000L
      ||!speech.active(now) ||!deadline.active(now) ||!validate())return@synchronized null
    VisualPermit.create(p,deadline,nativeElapsedMs).also {p.attachVisual(it)}
  }
  /** Genuine completed-speech membership transaction, not physical END or an
   * output effect. Exact installed RETURN/proofs are checked by Authority. */
  internal fun completeContinuousSpeech(p:ContinuousPermit,visual:VisualPermit,
    validate:()->Boolean):Boolean=synchronized(lock) {
    val b=p.binding;val reply=replies[b.requestId]
    if(!continuousEligible0(p) ||p.visual!==visual ||visual.parent!==p ||!visual.currentNow()
      ||!b.used ||!b.started ||reply==null ||p.chunks.any {it !in reply.seen ||it !in reply.completed}
      ||!validate())return@synchronized false
    p.detachSpeech();true
  }
  /** Read-only terminal transaction into the same authoritative reply ledger.
   * Caller validation uses actual model proofs; this creates no receipts.
   */
  internal fun validateContinuousTerminal(p:ContinuousPermit,requirePlaying:Boolean,
    validate:()->Boolean):Boolean=synchronized(lock) {
    val b=p.binding;val reply=replies[b.requestId]
    continuousEligible0(p) && b.used && b.started && reply!=null
      && (!requirePlaying || b.actions.ncIsPlayingSnapshot)
      && p.chunks.all {it in reply.seen && it in reply.completed} && validate()
  }
  /** Native sealed-END retirement, not Stop and not reply/session retirement.
   * Receipts must already exist; validate checks exact native drain identity.
   * No cancellation effect, output action or reply-history deletion occurs.
   */
  internal fun retireContinuous(p:ContinuousPermit,validate:()->Boolean):Boolean=synchronized(lock) {
    val b=p.binding;val reply=replies[b.requestId]
    if(!continuousEligible0(p) || b.actions.ncIsPlayingSnapshot || reply==null
      || p.chunks.any {it !in reply.seen || it !in reply.completed} || !validate())return@synchronized false
    p.cancelled=true;b.terminal=true;bindings-=b;true
  }
  internal fun invalidateContinuous(p:ContinuousPermit)=mutate<Unit>{effects->
    if(p.owner===this && p.binding.continuousPermit===p)terminate(p.binding,effects)}
  internal fun admitContinuousChunk(p:ContinuousPermit,c:String):Boolean=synchronized(lock) {
    val reply=replies[p.binding.requestId]
    if(!continuousEligible0(p) ||p.visual!=null ||p.speechDetached || !valid(c) || reply==null || c in reply.seen
      || p.chunks.size>=64 || (c !in reply.bound && reply.bound.size>=maxChunksPerRequest))false
    else {p.chunks+=c;reply.bound+=c;true}
  }
  /** Ordered native transaction into the EXISTING reply ledger. The caller
   * holds its authority lock; validate checks native-only model proofs and ACKs.
   * No observation/model monitor may be held while entering this guard.
   * These internal operations have no JS RPC or Boolean-proof wire format.
   */
  internal fun commitContinuousReceipts(p:ContinuousPermit,events:List<Pair<String,Boolean>>,
    validate:()->Boolean):Boolean=synchronized(lock) {
    val b=p.binding;val reply=replies[b.requestId]
    if(!continuousEligible0(p) ||p.speechDetached || !b.used || reply==null || events.isEmpty() || events.size>128
      || !validate())return@synchronized false
    val seen=reply.seen.toMutableSet();val started=reply.started.toMutableList();val completed=reply.completed.toMutableSet()
    for((chunk,onset) in events) {
      if(chunk !in p.chunks)return@synchronized false
      if(onset) {
        if(chunk !in seen) {
          if(started.any {it !in completed} || p.chunks.takeWhile {it!=chunk}.any {
            it !in seen || it !in completed})return@synchronized false
          seen+=chunk;started+=chunk
        }
      } else {
        if(chunk !in seen)return@synchronized false
        completed+=chunk
      }
    }
    reply.seen.clear();reply.seen+=seen;reply.started.clear();reply.started+=started
    reply.completed.clear();reply.completed+=completed
    if(events.any {it.second}){b.started=true;lastRequest=b.requestId}
    true
  }
  internal fun observeContinuousChunk(p:ContinuousPermit,c:String):NCPlaybackObservation?=synchronized(lock) {
    if(!continuousEligible0(p) || c !in p.chunks)return@synchronized null
    val reply=replies[p.binding.requestId]?:return@synchronized null
    val started=c in reply.seen;val completed=c in reply.completed
    // The persistent player's global position is NOT source-relative.
    NCPlaybackObservation(started,completed,started&&!completed&&p.binding.actions.ncIsPlayingSnapshot,null)
  }
  internal fun observePhoneReply(b: NCPlaybackBinding, t: String, r: String, c: String): NCPlaybackObservation? = synchronized(lock) {
    if (b.continuousPermit!=null || !b.attempted || b.ticket != t || b.requestId != r || b.chunkId != c ||
      !b.actions.ncIsAliveSnapshot || !eligible(b)) return@synchronized null
    val reply = replies[r] ?: return@synchronized null
    val position = if (b.started) b.actions.ncPositionSeconds?.takeIf { it.isFinite() && it >= 0 } else null
    NCPlaybackObservation(b.started, c in reply.completed, b.started && b.actions.ncIsPlayingSnapshot, position)
  }
  internal fun remove(b: NCPlaybackBinding) = mutate<Unit> { effects ->
    val reply = replies[b.requestId]
    // Transport disposal can precede the JS recovery event. Preserve one bounded
    // OS-confirmed checkpoint, never a wall-clock estimate or a completion.
    if (b in bindings && b.ticket == ticket && open && !connectionPaused && b.started
        && b.chunkId != null && reply?.closed == false && b.chunkId !in reply.completed) {
      val position = (b.actions as? NCPlaybackCheckpointActions)?.ncStopAndCheckpoint()
      if (position != null && position.isFinite() && position >= 0) {
        reply.checkpointChunk = b.chunkId; reply.checkpointSeconds = position
      }
    }
    if (b.attempted && !b.terminal) terminate(b, effects)
    bindings -= b
  }
  internal fun canUseMediaControls(b:NCPlaybackBinding)=synchronized(lock){controls(b)};private fun controls(b:NCPlaybackBinding)=eligible(b)&&session==null
  internal fun allowsFocusEffect(binding: NCPlaybackBinding, observedTicket: String?, item: String?) = synchronized(lock) {
    binding.actions.ncIsAliveSnapshot && !binding.terminal && binding.actions.ncItemIdentity == item &&
      (!binding.attempted || binding.ticket == observedTicket)
  }
  internal fun replace(b:NCPlaybackBinding,f:()->Unit):Boolean{if(!synchronized(lock){eligible(b)&&b.requestId==null&&b.orderedCarrier==null})return false;b.actions.ncDispatch{if(synchronized(lock){eligible(b)&&b.requestId==null&&b.orderedCarrier==null})f()};return true}

  private fun captureOrOutputSession(t:String,s:String)=session==s||captureScope(t,s)?.let{activeCapture==it.attachment&&!it.inputReleased}==true
  private fun scope(t:String,s:String)=!connectionPaused&&opened(t)&&phase==Phase.ARMED&&captureOrOutputSession(t,s)
  private fun captureAdmissionRequired()=activeCapture!=null||captures.values.any{it.uploads.isNotEmpty()}
  private fun opened(t:String)=open&&ticket==t
  private fun completedVisualMembership(b:NCPlaybackBinding):Boolean=b.continuousPermit?.let {
    it.owner===this &&it.binding===b &&it.epoch==recoveryEpoch &&!it.cancelled &&it.speechDetached
      &&it.visual?.currentNow()==true
  }==true
  private fun eligible(b:NCPlaybackBinding)=!connectionPaused&&!b.terminal&&(!b.attempted||(open&&b.ticket==ticket&&phase==Phase.ARMED))&&(!open||recoveryEpoch==0L||session==null||(b.attempted&&(b.requestId!=null||b.orderedCarrier?.epoch==recoveryEpoch)))&&(tail==null||b.requestId in tail!!||b.orderedCarrier!=null)&&(b.requestId==null||((replies[b.requestId]?.closed==false||completedVisualMembership(b))&&b.item==b.actions.ncItemIdentity))&&(b.orderedCarrier?.let{!it.cancelled&&it.item==b.actions.ncItemIdentity&&it.currentNow()}!=false)
  private fun ensure(r:String):Boolean{if(replies[r]!=null)return true;if(replies.size>=maxRequests)return false;replies[r]=Reply();return true}
  private fun closeReply(r:String,u:Boolean,e:MutableList<Effect>,normalCompletion:Boolean=false){val x=replies[r]?:return;x.closed=true;x.unavailable=x.unavailable||u;acks.entries.removeAll{it.value==r};if(!x.unavailable&&lastRequest==r)lastRequest=null;bindings.filter{b->b.ticket==ticket&&((b.requestId==r&&!(normalCompletion&&completedVisualMembership(b)))||(b.orderedCarrier?.replies?.get(r)?.let{!normalCompletion||!it.detached}==true))}.forEach{terminate(it,e)}}
  private fun close(c:RetirementCause,e:MutableList<Effect>){
    // Device/track/capture route callbacks do not invalidate the visual owner.
    // Input safety still stops invalid capture independently. Never turn an
    // audio route switch into whole-player retirement and replacement.
    if(c==RetirementCause.ROUTE_CHANGE||!open)return
    open=false;connectionPaused=false;stopCue();cause=c.wireValue;phase=null;foregroundOnly=false;bindings.filter{it.ticket==ticket}.forEach{terminate(it,e)};bindings.clear();replies.clear();lastRequest=null;pending.clear();issued.clear();acks.clear();tail=null;activeCapture=null;captures.clear();captureSessions.clear()
  }
  private fun terminate(b:NCPlaybackBinding,e:MutableList<Effect>){if(b.terminal)return;b.terminal=true;val p=b.continuousPermit;p?.cancelled=true;val ordered=b.orderedCarrier;ordered?.cancelled=true;e+=Effect(b,b.item?:b.actions.ncItemIdentity,b.ticket,Kind.PAUSE,p,ordered)}
  private inline fun<T>mutate(f:(MutableList<Effect>)->T):T{val e=mutableListOf<Effect>();val r=synchronized(lock){f(e)};dispatch(e);return r}
  private fun dispatch(es:List<Effect>)=es.forEach{x->
    // Permission is already invalid under the guard lock. Notify outside it,
    // even for a replaced item: the old run must keep its files fenced/owned.
    // Its callback may flush ONLY its exact enrolled player/item, not a successor.
    try{x.cancelled?.onCancelled?.invoke()}catch(_:RuntimeException){}
    try{x.orderedCancelled?.onCancelled?.invoke()}catch(_:RuntimeException){}
    x.orderedCancelled?.let{p->
      val stop=p.transportCueStop;p.transportCueStop=null
      try{stop?.invoke()}catch(_:RuntimeException){}
    }
    x.b.actions.ncDispatch{val ok=synchronized(lock){x.b.actions.ncItemIdentity==x.item&&(x.kind==Kind.PAUSE||(x.b.ticket==x.ticket&&eligible(x.b)&&playbackUnlocked(x.b)))};if(ok){if(x.kind==Kind.PLAY)x.b.actions.ncPlay()else x.b.actions.ncPause()};if(x.kind==Kind.PLAY&&synchronized(lock){!eligible(x.b)||!playbackUnlocked(x.b)||x.b.actions.ncItemIdentity!=x.item}&&x.b.actions.ncIsPlayingSnapshot)x.b.actions.ncPause()}}
  private fun valid(v:String)=v.isNotEmpty()&&v.codePointCount(0,v.length)<=128
  companion object{const val VERSION=1;const val PHONE_REPLY_RECEIPT_VERSION=1;@JvmField val shared=NCPlaybackGuard()}
}
class NCPlaybackBinding internal constructor(private val owner:NCPlaybackGuard,internal val actions:NCPlaybackActions){internal var ticket:String?=null;internal var requestId:String?=null;internal var chunkId:String?=null;internal var item:String?=null;internal var attempted=false;internal var used=false;internal var terminal=false;internal var started=false
  internal var continuousPermit:NCPlaybackGuard.ContinuousPermit?=null
  internal var orderedCarrier:NCPlaybackGuard.OrderedCarrierPermit?=null
  private val completionObserved = java.util.concurrent.atomic.AtomicBoolean()
  @Volatile private var completionObserver: (() -> Unit)? = null
  internal fun setCompletionObserver(observer: (() -> Unit)?) { completionObserver = observer }
  fun observePhoneReply(ticket: String, requestId: String, chunkId: String) = owner.observePhoneReply(this, ticket, requestId, chunkId)
  fun acknowledgeCompleted(): Boolean {
    val accepted = owner.completed(this)
    // Read-only visual observers run on the native callback before JS can
    // retire a short completed player. They grant no playback permission.
    if (accepted && completionObserved.compareAndSet(false,true)) {
      // A visual observer cannot swallow the guarded audio completion. The
      // renderer reports its own failure; it owns no playback receipt.
      try { completionObserver?.invoke() } catch (_: RuntimeException) {}
    }
    return accepted
  }
  fun allowsBackgroundPlayback()=owner.allowsBackgroundPlayback(this)
  fun bind(t:String)=owner.bind(this,t);fun bindPhoneReplyChunk(t:String,r:String,c:String,rejected:(String)->Unit={})=owner.bindChunk(this,t,r,c,rejected);fun play()=owner.play(this);fun systemPlay(item:String?)=owner.systemPlay(this,item);fun acknowledgeStarted()=owner.acknowledge(this);fun canUseMediaControls()=owner.canUseMediaControls(this);fun allowsFocusEffect(t:String?,item:String?)=owner.allowsFocusEffect(this,t,item);fun replace(f:()->Unit)=owner.replace(this,f);fun pause()=owner.pause(this);fun remove()=owner.remove(this)}
