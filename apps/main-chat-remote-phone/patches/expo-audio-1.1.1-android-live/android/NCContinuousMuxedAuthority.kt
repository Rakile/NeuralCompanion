package expo.modules.audio

import kotlin.math.floor

internal data class NCOrderedMuxedSessionDescriptor(val ticket:String,val owner:String,val connectionEpoch:String,
  val recoveryEpoch:Long,val streamId:String,val generation:Long,val expiresAtMs:Double) {
  init {require(ticket.isNotBlank() &&ticket.length<=128 &&owner.isNotBlank() &&owner.length<=2048
    &&connectionEpoch.isNotBlank() &&connectionEpoch.length<=256 &&recoveryEpoch in 0..9007199254740991L
    &&streamId.matches(Regex("[a-f0-9]{32}")) &&generation in 0..9007199254740991L
    &&expiresAtMs.isFinite() &&expiresAtMs>0 &&expiresAtMs<=9007199254740991.0)}
}

/** Retained source plan plus ordered stream scope. No phone frame selection. */
internal data class NCOrderedMuxedSourceDescriptor(val session:NCOrderedMuxedSessionDescriptor,val kind:String,
  val sourceId:String,val replyId:String?,val sequenceIndex:Int?,val mediaId:String,
  val plan:NCMuxedTrialStreamRanges.Plan,val firstOrdinal:Long,val expiresAtMs:Double,
  val validatedStagingIdentity:String) {
  val silent get()=kind!="speech"
  init {
    require(kind in listOf("idle","transition","speech") &&sourceId.matches(Regex("[A-Za-z0-9_-]{1,128}"))
      &&mediaId.matches(Regex("[a-f0-9]{32}")) &&firstOrdinal in 0..9007199254740991L-plan.totalRanges
      &&expiresAtMs.isFinite() &&expiresAtMs>0 &&expiresAtMs<=session.expiresAtMs
      &&validatedStagingIdentity.isNotBlank() &&validatedStagingIdentity.length<=128)
    if(silent)require(replyId==null &&sequenceIndex==null &&plan.samples==plan.frames*2000L)
    else require(replyId!=null &&replyId.matches(Regex("[A-Za-z0-9_-]{1,128}")) &&sequenceIndex in 0..63)
  }
  fun matches(chunk:NCOrderedOutputChunk):Boolean = chunk.streamId==session.streamId
    &&chunk.generation==session.generation &&chunk.kind==kind &&chunk.sourceId==sourceId
    &&chunk.replyId==replyId &&chunk.sequenceIndex==sequenceIndex?.toLong() &&chunk.mediaId==mediaId
    &&chunk.sourceRange.totalFrames==plan.frames.toLong() &&chunk.sourceRange.start%12==0L
    &&chunk.ordinal==firstOrdinal+chunk.sourceRange.start/12
    &&chunk.sampleCount.toLong()==(if(chunk.sourceRange.end==plan.frames.toLong())plan.samples-chunk.sourceRange.start*2000 else 24000L)
}

/** Immutable retained Desktop/phone metadata. Consistency is not remote
 * authentication or output permission; the existing relay and native guard
 * must still admit this exact source. Network and local recovery epochs are
 * deliberately different domains.
 */
internal data class NCContinuousMuxedSourceDescriptor(
  val ticket:String,val owner:String,val connectionEpoch:String,val recoveryEpoch:Long,
  val replyId:String,val chunkId:String,val sequenceIndex:Int,val expiresAtMs:Double,
  val mediaId:String,val plan:NCMuxedTrialStreamRanges.Plan,val motionId:String,
  val sourceFrameCount:Int,val avatarId:String,val quality:Quality,
  val firstSourceFrame:Int,val lastSourceFrame:Int,val idleReturnEntry:Int,
  val unsupportedAnticipation:Boolean,val validatedStagingIdentity:String
) {
  data class Quality(val kbps:Int,val width:Int,val fps:Int) {
    init {require(kbps in 100..2000 && width in 160..448 && width%2==0 && fps==24)}
  }
  init {
    require(listOf(ticket,replyId,chunkId).all {it.isNotEmpty() && it.codePointCount(0,it.length)<=128})
    require(owner.isNotEmpty() && connectionEpoch.isNotEmpty()
      && recoveryEpoch in 0..9007199254740991L && sequenceIndex in 0..63
      && expiresAtMs.isFinite() && expiresAtMs>0
      && mediaId.matches(Regex("[a-f0-9]{32}")) && motionId.matches(Regex("[a-f0-9]{64}"))
      && sourceFrameCount in 1..1440 && avatarId.length in 1..256
      && firstSourceFrame in 0 until sourceFrameCount && lastSourceFrame in 0 until sourceFrameCount
      && idleReturnEntry in 0 until sourceFrameCount && validatedStagingIdentity.isNotEmpty())
  }

  /** Read-only early join check. Neither descriptor readiness nor adjacency
   * permits decoder input, output or a receipt.
   */
  fun compatibleSuccessor(next:NCContinuousMuxedSourceDescriptor):Boolean =
    ticket==next.ticket && owner==next.owner && connectionEpoch==next.connectionEpoch
      && recoveryEpoch==next.recoveryEpoch && replyId==next.replyId
      && sequenceIndex<63 && next.sequenceIndex==sequenceIndex+1 && chunkId!=next.chunkId
      && expiresAtMs==next.expiresAtMs && motionId==next.motionId
      && sourceFrameCount==next.sourceFrameCount && avatarId==next.avatarId && quality==next.quality
      && next.firstSourceFrame==(lastSourceFrame+1)%sourceFrameCount
      && idleReturnEntry==next.firstSourceFrame && !next.unsupportedAnticipation
}

/** Captures a wall-clock expiry once into a conservative monotonic deadline.
 * No later wall-clock sample can renew it. Expiry or clock regression is sticky.
 * The owner must fence and flush actual output when this becomes inactive.
 */
internal class NCContinuousMuxedDeadline private constructor(private val deadline:Long,
  private var lastElapsed:Long) {
  internal val expiresElapsedMs get()=deadline
  internal val capturedElapsedMs=lastElapsed
  private var valid=true
  @Synchronized fun active(elapsedNowMs:Long):Boolean {
    if(!valid)return false
    if(elapsedNowMs<lastElapsed || elapsedNowMs>=deadline){valid=false;return false}
    lastElapsed=elapsedNowMs
    return true
  }
  companion object {
    fun capture(expiresAtMs:Double,wallNowMs:Double,elapsedNowMs:Long):NCContinuousMuxedDeadline? {
      if(!expiresAtMs.isFinite() || !wallNowMs.isFinite() || elapsedNowMs<0)return null
      val remaining=floor(expiresAtMs-wallNowMs)
      if(!remaining.isFinite() || remaining<1 || remaining>=Long.MAX_VALUE.toDouble())return null
      val end=try {Math.addExact(elapsedNowMs,remaining.toLong())} catch(_:ArithmeticException){return null}
      return NCContinuousMuxedDeadline(end,elapsedNowMs)
    }
  }
}

internal data class NCContinuousMuxedSourceState(val grant:NCContinuousMuxedAuthority.SourceGrant,
  val layoutInstalled:Boolean,val started:Boolean,val completed:Boolean,val readersClosed:Boolean)

/** Copied authenticated finality/locked RETURN metadata. It is not a native
 * grant: retained files, the exact open tail and Guard must independently agree. */
internal data class NCContinuousMuxedReturnDescriptor(val parent:NCContinuousMuxedSourceDescriptor,
  val finalSequenceIndex:Int,val sourceId:String,val requestId:String,val mediaId:String,
  val scopeIdentity:String,val motionId:String,val sourceFrameCount:Int,val avatarId:String,
  val quality:NCContinuousMuxedSourceDescriptor.Quality,val startFrame:Int,
  val expiresAtMs:Double,val validatedStagingIdentity:String) {
  fun matches(d:NCContinuousMuxedSourceDescriptor,rejected:(String)->Unit={}):Boolean {
    fun valid(name:String,value:Boolean):Boolean {
      if(!value)try{rejected("descriptor.$name")}catch(_:Exception){}
      return value
    }
    return valid("parent",parent==d) &&valid("sequence",finalSequenceIndex==d.sequenceIndex)
      &&valid("source_id",sourceId.matches(Regex("[a-f0-9]{32}")))
      &&valid("request_id",requestId.matches(Regex("[a-f0-9]{32}")))
      &&valid("media_id",mediaId.matches(Regex("[a-f0-9]{32}")))
      &&valid("distinct_media",mediaId!=d.mediaId)
      &&valid("scope_identity",scopeIdentity.isNotBlank() &&scopeIdentity.length<=256)
      &&valid("motion",motionId==d.motionId) &&valid("frame_count",sourceFrameCount==d.sourceFrameCount)
      &&valid("avatar",avatarId==d.avatarId) &&valid("quality",quality==d.quality)
      &&valid("start_frame",startFrame==(d.lastSourceFrame+1)%d.sourceFrameCount)
      &&valid("return_entry",startFrame==d.idleReturnEntry)
      &&valid("deadline",expiresAtMs.isFinite() &&expiresAtMs>0 &&expiresAtMs<=d.expiresAtMs)
      &&valid("staging_identity",validatedStagingIdentity.isNotBlank() &&validatedStagingIdentity.length<=128)
      &&valid("distinct_stage",validatedStagingIdentity!=d.validatedStagingIdentity)
  }
}

/** Native grant/receipt adapter, still capability-disabled and not wired to a
 * live player. The concrete queue supplies real validated staging reservations
 * and invokes acknowledgeTimeline ONLY after the actual Media3 mutation ACK.
 * Caller clocks are platform boundaries, not playback-position estimators.
 */
internal class NCContinuousMuxedAuthority(private val guard:NCPlaybackGuard,
  private val presentation:NCContinuousMuxedPresentation,private val queue:NCContinuousMuxedQueueState,
  private val journal:NCContinuousMuxedJournal,private val wallNowMs:()->Double,
  private val elapsedNowMs:()->Long,
  private val resolveStage:(String)->NCContinuousMuxedQueueState.Token?,
  private val stopAndFlush:()->Unit) {
  data class RunHandle(val id:String,val revision:Long)
  class OrderedGrant private constructor(internal val origin:NCContinuousMuxedAuthority,
    val run:RunHandle,internal val descriptor:NCOrderedMuxedSourceDescriptor,
    internal val replyPermit:NCPlaybackGuard.OrderedReplyPermit?) {
    val id get()=descriptor.validatedStagingIdentity
    companion object {internal fun create(origin:NCContinuousMuxedAuthority,run:RunHandle,
      descriptor:NCOrderedMuxedSourceDescriptor,reply:NCPlaybackGuard.OrderedReplyPermit?)=
      OrderedGrant(origin,run,descriptor,reply)}
  }
  class SourceGrant private constructor(internal val origin:NCContinuousMuxedAuthority,
    val run:RunHandle,val id:String,internal val descriptor:NCContinuousMuxedSourceDescriptor) {
    val chunkId get()=descriptor.chunkId
    val sequenceIndex get()=descriptor.sequenceIndex
    companion object {
      internal fun create(owner:NCContinuousMuxedAuthority,run:RunHandle,d:NCContinuousMuxedSourceDescriptor)=
        SourceGrant(owner,run,d.validatedStagingIdentity,d)
    }
  }
  class VisualGrant private constructor(internal val origin:NCContinuousMuxedAuthority,
    val run:RunHandle,val id:String,internal val descriptor:NCContinuousMuxedReturnDescriptor,
    internal val parent:SourceGrant,internal val tail:NCContinuousMuxedQueueState.Tail,
    internal val reservation:NCContinuousMuxedQueueState.Token,internal val permission:NCPlaybackGuard.VisualPermit) {
    companion object {
      internal fun create(owner:NCContinuousMuxedAuthority,run:RunHandle,d:NCContinuousMuxedReturnDescriptor,
        parent:SourceGrant,tail:NCContinuousMuxedQueueState.Tail,token:NCContinuousMuxedQueueState.Token,
        permission:NCPlaybackGuard.VisualPermit)=VisualGrant(owner,run,d.validatedStagingIdentity,d,parent,tail,token,permission)
    }
  }
  /** Native-only output permission publication. The renderer does not acquire
   * Authority/Guard monitors; actual receipts still validate through them.
   * No wire handle, reservation or scheduled mutation can publish these keys.
   * This denies output; queued PCM discard is a separate concrete sink gate.
   */
  class OutputLease private constructor(val run:RunHandle,
    private val permit:NCPlaybackGuard.ContinuousPermit?,
    private val model:NCContinuousMuxedPresentation,deadline:NCContinuousMuxedDeadline,
    private val nativeElapsedMs:()->Long,
    private val orderedCarrier:NCPlaybackGuard.OrderedCarrierPermit?=null) {
    val expiresElapsedMs=deadline.expiresElapsedMs
    private enum class Lifetime { LIVE,REVOKED,NATURAL }
    private val capturedElapsedMs=deadline.capturedElapsedMs
    private val clockLock=Any()
    private var lastElapsed=capturedElapsedMs
    @Volatile private var keys:Set<NCContinuousMuxedClipKey> = emptySet()
    @Volatile private var visualMembership:Pair<String,NCPlaybackGuard.VisualPermit>?=null
    @Volatile private var orderedMemberships:Map<String,NCPlaybackGuard.OrderedReplyPermit?> = emptyMap()
    @Synchronized internal fun attachOrderedSource(handle:String,reply:NCPlaybackGuard.OrderedReplyPermit?):Boolean {
      val carrier=orderedCarrier?:return false
      if(isRevoked ||handle in orderedMemberships ||orderedMemberships.size>=64
        ||!carrier.currentNow() ||model.orderedSourceIsVisual(handle)!=(reply==null)
        ||reply?.let{it.carrier!==carrier ||!it.currentNow()}==true)return false
      orderedMemberships=orderedMemberships+(handle to reply)
      return !isRevoked
    }
    @Synchronized internal fun releaseOrderedSource(handle:String):Boolean {
      if(orderedCarrier==null ||handle !in orderedMemberships ||keys.any{it.sourceHandle==handle})return false
      orderedMemberships=orderedMemberships-handle;return true
    }
    internal fun attachVisual(handle:String,visual:NCPlaybackGuard.VisualPermit):Boolean {
      if(orderedCarrier!=null ||isRevoked ||visualMembership!=null ||visual.parent!==permit ||!visual.currentNow())return false
      visualMembership=handle to visual;return !isRevoked
    }
    private fun kindPermitted(key:NCContinuousMuxedClipKey):Boolean {
      if(orderedCarrier!=null) {
        val membership=orderedMemberships
        return key.sourceHandle in membership &&orderedCarrier.currentNow()
          &&membership[key.sourceHandle]?.retainedCurrentNow()!=false
      }
      val visual=visualMembership
      return if(visual?.first==key.sourceHandle)visual.second.currentNow() else permit?.speechDetached==false
    }
    private data class OutputPhase(val lifetime:Lifetime=Lifetime.LIVE,val inFlight:Boolean=false,
      val terminal:NCContinuousMuxedOutputGate.TrackWitness?=null,
      val closedOrderedReplies:Set<NCPlaybackGuard.OrderedReplyPermit> = emptySet())
    private val outputPhase=java.util.concurrent.atomic.AtomicReference(OutputPhase())
    val isNaturallyRetired get()=outputPhase.get().lifetime==Lifetime.NATURAL
    private val outputActor=java.util.concurrent.atomic.AtomicReference<NCContinuousMuxedOutputGate?>(null)
    internal fun enrollOutputActor(actor:NCContinuousMuxedOutputGate)=outputActor.compareAndSet(null,actor)
    internal fun ownsOutputActor(actor:NCContinuousMuxedOutputGate)=outputActor.get()===actor
    internal fun acceptsCapture(capture:NCContinuousMuxedPresentation.NativeTrackCapture)=model.matchesNativeTrack(capture)
    internal fun acceptsLockPause(p:NCPlaybackGuard.LockPausePermit)=
      orderedCarrier===p.carrier &&!isRevoked &&!hasTerminalSelection &&p.currentNow()
    internal fun acceptsInitialCapture(capture:NCContinuousMuxedPresentation.NativeTrackCapture)=model.canInitializeCapturedTrack(capture)
    internal fun matchesPresentation(expected:NCContinuousMuxedPresentation)=model===expected
    internal fun hasOutputKey(key:NCContinuousMuxedClipKey)=key in keys
    val hasTerminalSelection get()=outputPhase.get().terminal!=null
    val isRevoked get()=outputPhase.get().lifetime!=Lifetime.LIVE || permit?.cancelled==true ||orderedCarrier?.cancelled==true
    internal fun publish(next:Set<NCContinuousMuxedClipKey>) {keys=next.toSet()}
    /** Return the atomic winner, not an earlier natural-status snapshot. */
    internal fun revoke():Boolean {
      while(true) {
        val prior=outputPhase.get()
        if(prior.lifetime==Lifetime.NATURAL)return false
        if(prior.lifetime==Lifetime.REVOKED || outputPhase.compareAndSet(prior,prior.copy(lifetime=Lifetime.REVOKED)))return true
      }
    }
    internal fun retireNaturally():Boolean {
      if(orderedCarrier!=null)return false // An open Desktop stream has no natural carrier END.
      while(permit?.cancelled==false) {
        val prior=outputPhase.get()
        if(prior.lifetime!=Lifetime.LIVE || prior.inFlight)return false
        if(outputPhase.compareAndSet(prior,prior.copy(lifetime=Lifetime.NATURAL)))return true
      }
      return false
    }
    internal fun selectTerminal(witness:NCContinuousMuxedOutputGate.TrackWitness):Boolean {
      while(!isRevoked) {
        val prior=outputPhase.get()
        if(prior.lifetime!=Lifetime.LIVE || prior.inFlight || prior.terminal!=null)return false
        if(outputPhase.compareAndSet(prior,prior.copy(terminal=witness)))return !isRevoked
      }
      return false
    }
    internal fun selectedTerminal(witness:NCContinuousMuxedOutputGate.TrackWitness)=outputPhase.get().terminal===witness
    /** Enter before the delegate, leave only after its output checkpoint.
     * Terminal selection and submission use the same atomic boundary; a pure
     * preflight permits() read is never sufficient to enter the normal sink.
     */
    internal fun beginSubmission(key:NCContinuousMuxedClipKey,epoch:Long?,now:Long):Boolean {
      if(!(if(epoch==null)permitsInitialization(key,now) else permits(key,epoch,now)))return false
      while(!isRevoked) {
        val prior=outputPhase.get()
        if(prior.lifetime!=Lifetime.LIVE || prior.inFlight || prior.terminal!=null)return false
        val reply=orderedMemberships[key.sourceHandle]
        if(reply!=null &&(reply in prior.closedOrderedReplies ||!reply.currentNow()))return false
        if(outputPhase.compareAndSet(prior,prior.copy(inFlight=true)))return !isRevoked
      }
      return false
    }
    /** Source completion and entering the real sink compete at this one CAS.
     * A completed reply may retain video/control origins, never submit more PCM. */
    internal fun completeOrderedSpeech(reply:NCPlaybackGuard.OrderedReplyPermit):Boolean {
      if(reply.carrier!==orderedCarrier ||!reply.currentNow())return false
      while(!isRevoked) {
        val prior=outputPhase.get()
        if(prior.lifetime!=Lifetime.LIVE ||prior.inFlight ||prior.terminal!=null)return false
        if(reply in prior.closedOrderedReplies)return true
        if(outputPhase.compareAndSet(prior,prior.copy(closedOrderedReplies=prior.closedOrderedReplies+reply)))return !isRevoked
      }
      return false
    }
    internal fun releaseOrderedReply(reply:NCPlaybackGuard.OrderedReplyPermit):Boolean {
      if(reply.carrier!==orderedCarrier ||!reply.released ||orderedMemberships.values.any{it===reply})return false
      while(true) {
        val prior=outputPhase.get()
        if(reply !in prior.closedOrderedReplies)return true
        if(outputPhase.compareAndSet(prior,prior.copy(closedOrderedReplies=prior.closedOrderedReplies-reply)))return true
      }
    }
    internal fun endSubmission():Boolean {
      while(true) {
        val prior=outputPhase.get()
        if(!prior.inFlight)return false
        if(outputPhase.compareAndSet(prior,prior.copy(inFlight=false)))return !isRevoked
      }
    }
    /** Control-only lifetime check. Terminal selection still denies new PCM;
     * cancellation/deadline must remain enforced after the witnessed EOS stop.
     */
    internal fun controlAt(elapsedNowMs:Long):Boolean {
      if(elapsedNowMs<capturedElapsedMs || elapsedNowMs>=expiresElapsedMs){revoke();return false}
      return controlNow()!=null
    }
    /** Sample inside a tiny clock-only lock. Caller-captured times may arrive
     * out of order across threads; only the serialized native supplier can
     * establish an actual rollback. Never takes Authority/Guard/model locks.
     */
    internal fun controlNow():Long? = synchronized(clockLock) {
      if(isRevoked)return@synchronized null
      if(orderedCarrier?.currentNow()==false){revoke();return@synchronized null}
      if(visualMembership?.second?.currentNow()==false){revoke();return@synchronized null}
      val now=try {nativeElapsedMs()} catch(_:RuntimeException){revoke();return@synchronized null}
      if(now<lastElapsed || now>=expiresElapsedMs){revoke();return@synchronized null}
      lastElapsed=now
      now.takeUnless {isRevoked}
    }
    fun activeAt(elapsedNowMs:Long):Boolean {
      if(hasTerminalSelection || !controlAt(elapsedNowMs))return false
      val cursors=model.protectedCursors()
      if(!cursors.known){revoke();return false}
      return !isRevoked && cursors.runRevision==run.revision
    }
    fun permits(key:NCContinuousMuxedClipKey,sinkEpoch:Long,elapsedNowMs:Long):Boolean {
      if(!activeAt(elapsedNowMs) || sinkEpoch !in 1..9007199254740991L || key !in keys ||!kindPermitted(key))return false
      val cursors=model.protectedCursors()
      // Recheck immediate revocation after the small presentation read.
      return !isRevoked && !hasTerminalSelection && cursors.known && cursors.runRevision==run.revision
        && (cursors.sinkEpoch==0L || cursors.sinkEpoch==sinkEpoch)
    }
    /** Video carries its own processed-stream origin. It cannot borrow the
     * audio renderer's current period or invent an AudioTrack epoch. The exact
     * physical enrollment/model must still be checked by the video output bridge.
     * This read-only admission grants no presentation or speech receipt.
     */
    fun permitsVideo(key:NCContinuousMuxedClipKey,elapsedNowMs:Long):Boolean {
      if(!activeAt(elapsedNowMs) ||key !in keys ||!kindPermitted(key))return false
      val cursors=model.protectedCursors()
      return !isRevoked &&!hasTerminalSelection &&cursors.known &&cursors.runRevision==run.revision
    }
    internal fun beginVideoSubmission(key:NCContinuousMuxedClipKey,now:Long):Boolean {
      if(!permitsVideo(key,now))return false
      while(!isRevoked) {
        val prior=outputPhase.get()
        if(prior.lifetime!=Lifetime.LIVE ||prior.inFlight ||prior.terminal!=null)return false
        if(outputPhase.compareAndSet(prior,prior.copy(inFlight=true)))return !isRevoked
      }
      return false
    }
    /** Initialization only: the output actor additionally requires its positive
     * pristine-sink witness. This cannot prove an epoch, PCM or presentation.
     */
    internal fun permitsInitialization(key:NCContinuousMuxedClipKey,elapsedNowMs:Long):Boolean {
      if(!activeAt(elapsedNowMs) || key !in keys ||!kindPermitted(key))return false
      val cursors=model.protectedCursors()
      return !isRevoked && !hasTerminalSelection && cursors.known && cursors.runRevision==run.revision && cursors.sinkEpoch==0L
    }
    companion object {
      internal fun create(run:RunHandle,permit:NCPlaybackGuard.ContinuousPermit,
        model:NCContinuousMuxedPresentation,deadline:NCContinuousMuxedDeadline,now:()->Long)=OutputLease(run,permit,model,deadline,now)
      internal fun createOrdered(run:RunHandle,permit:NCPlaybackGuard.OrderedCarrierPermit,
        model:NCContinuousMuxedPresentation,deadline:NCContinuousMuxedDeadline,now:()->Long):OutputLease {
        require(model.desktopOrdered)
        return OutputLease(run,null,model,deadline,now,permit)
      }
    }
  }
  /** Native-only historical endpoint, not a reusable live Presentation proof.
   * Minted under Authority->Guard->Presentation validation before delegate EOS.
   * The output actor publishes only its causally witnessed normal stop here.
   */
  class TerminalAttestation private constructor(
    internal val lease:OutputLease,internal val witness:NCContinuousMuxedOutputGate.TrackWitness,
    private val model:NCContinuousMuxedPresentation,private val invalidation:Long,
    internal val tail:NCContinuousMuxedQueueState.Tail,internal val mutationRevision:Long,
  ) {
    private val stop=java.util.concurrent.atomic.AtomicReference<NCContinuousMuxedOutputGate.NormalEosStopProof?>(null)
    private val delegating=java.util.concurrent.atomic.AtomicBoolean()
    internal fun controlAlive():Boolean {
      val elapsed=lease.controlNow()?:return false
      return elapsed>=witness.firstAttemptElapsedMs && elapsed<witness.expiresElapsedMs
    }
    private fun knownEndpoint():Boolean = model.protectedCursors().let {
      it.known && it.runRevision==lease.run.revision && it.sinkEpoch==witness.sinkEpoch
        && model.invalidationRevision()==invalidation
    }
    internal fun beforeDelegate(owner:NCContinuousMuxedOutputGate):Boolean {
      if(!lease.selectedTerminal(witness) || !controlAlive() || stop.get()!=null
        || !witness.matchesPending(owner,lease) || !knownEndpoint())return false
      return !delegating.get() && controlAlive()
    }
    internal fun beginDelegation() {delegating.set(true)}
    internal fun endDelegation() {delegating.set(false)}
    private fun stoppedMapping():Boolean {
      val cursors=model.protectedCursors()
      if(cursors.runRevision!=lease.run.revision || cursors.sinkEpoch!=witness.sinkEpoch)return false
      if(cursors.known)return model.invalidationRevision()==invalidation
      // No blanket exemption for failure11: only the published exact native
      // stop proof and a zero raw head on its still-owned STOPPED track qualify.
      return model.invalidationRevision()==invalidation+1 && model.failureCode()==11
        && witness.rawHeadIsReset()
    }
    internal fun publishStop(candidate:NCContinuousMuxedOutputGate.NormalEosStopProof):Boolean {
      if(!controlAlive() || !candidate.matches(witness,lease) || !stoppedMapping())return false
      return stop.compareAndSet(null,candidate)
    }
    internal fun hasWitnessedStop()=stop.get()!=null
    internal fun validPending():Boolean = controlAlive() && when {
      delegating.get()->witness.matchesDelegating(lease) && (knownEndpoint() || stoppedMapping())
      stop.get()==null->knownEndpoint() && witness.matchesPending(null,lease)
      else->stoppedMapping() && stop.get()!!.matches(witness,lease)
    }
    internal fun validEnded():Boolean = !delegating.get() && hasWitnessedStop() && validPending()
    companion object {
      internal fun create(lease:OutputLease,witness:NCContinuousMuxedOutputGate.TrackWitness,
        model:NCContinuousMuxedPresentation,tail:NCContinuousMuxedQueueState.Tail,revision:Long)=
        TerminalAttestation(lease,witness,model,model.invalidationRevision(),tail,revision)
    }
  }
  private data class Entry(val grant:SourceGrant,var lastObservation:NCPlaybackObservation?=null)
  enum class AdmissionStatus {ADMITTED,FUTURE_OCCUPIED,CAPACITY,REJECTED}
  data class AdmissionResult(val status:AdmissionStatus,val grant:SourceGrant?=null) {
    init {require((status==AdmissionStatus.ADMITTED)==(grant!=null))}
  }
  private var run:RunHandle?=null
  private var initial:NCContinuousMuxedSourceDescriptor?=null
  private var permit:NCPlaybackGuard.ContinuousPermit?=null
  private var deadline:NCContinuousMuxedDeadline?=null
  private var outputLease:OutputLease?=null
  private var terminal:TerminalAttestation?=null
  private var visual:VisualGrant?=null
  private var mixedRetirement:NCContinuousMuxedQueue.MixedRetirement?=null
  private val entries=linkedMapOf<String,Entry>()
  private var failed=false
  private var drained=false
  private var orderedSession:NCOrderedMuxedSessionDescriptor?=null
  private var orderedCarrier:NCPlaybackGuard.OrderedCarrierPermit?=null
  private var orderedCancellationReported=false
  private data class OrderedEntry(val grant:OrderedGrant,var started:Boolean=false,
    var completed:Boolean=false,var readersClosed:Boolean=false)
  private data class OrderedReply(val permit:NCPlaybackGuard.OrderedReplyPermit,var nextSequence:Int=0,
    var completed:Boolean=false)
  private val orderedEntries=linkedMapOf<String,OrderedEntry>()
  private val orderedReplies=linkedMapOf<String,OrderedReply>()
  private var orderedTail:NCOrderedMuxedSourceDescriptor?=null

  @Synchronized internal fun beginOrderedRun(d:NCOrderedMuxedSessionDescriptor,binding:NCPlaybackBinding):RunHandle? {
    if(run!=null ||failed ||!queue.desktopOrdered ||!presentation.desktopOrdered ||!journal.desktopOrdered)return null
    val captured=NCContinuousMuxedDeadline.capture(d.expiresAtMs,wallNowMs(),elapsedNowMs())?:return null
    val enrolled=guard.enrollOrderedCarrier(binding,d.ticket,d.recoveryEpoch,captured,elapsedNowMs) {
      synchronized(this){
        val first=!orderedCancellationReported
        orderedCancellationReported=true
        fence("ordered_owner_cancelled")
        // Cancellation dispatch is synchronous, so the initiating guard/capture
        // call is still on this stack. Record once, AFTER permission revocation.
        // Never include arguments, exception messages, tickets or arbitrary paths.
        if(first)try {
          val roots=listOf("expo.modules.audio.NCPlaybackGuard",
            "expo.modules.nclivecapture.LiveCaptureEngine")
          val origin=Throwable().stackTrace.mapNotNull { frame ->
            val root=roots.firstOrNull {frame.className==it ||frame.className.startsWith(it+"$")}
              ?:return@mapNotNull null
            val method=frame.methodName.substringBefore('$').take(64)
            if(!method.matches(Regex("[A-Za-z0-9_]+")))return@mapNotNull null
            "${root.substringAfterLast('.')}.$method:${frame.lineNumber}"
          }.distinct().take(24).joinToString(">")
          android.util.Log.d("NCContinuousOwner","event=ordered_cancel origin=${origin.ifEmpty {"unavailable"}}")
        } catch(_:Exception) { /* Diagnostic failure cannot change cleanup. */ }
      }
    }?:return null
    return RunHandle(java.util.UUID.randomUUID().toString(),queue.runRevision).also {
      run=it;orderedSession=d;orderedCarrier=enrolled;deadline=captured
      outputLease=OutputLease.createOrdered(it,enrolled,presentation,captured,elapsedNowMs)
    }
  }
  private fun orderedOwned(g:OrderedGrant)=g.origin===this &&g.run==run &&orderedEntries[g.id]?.grant===g
  @Synchronized internal fun admitOrderedSource(expectedRun:RunHandle,d:NCOrderedMuxedSourceDescriptor,
    revision:Long,rejected:(String)->Unit={}):OrderedGrant? {
    fun reject(reason:String):OrderedGrant? {try{rejected(reason)}catch(_:Exception){};return null}
    if(expectedRun!=run)return reject("run_identity")
    if(d.session!=orderedSession)return reject("session_scope")
    if(!active())return reject("carrier_authority")
    if(orderedEntries.size>=64)return reject("capacity.sources")
    if(d.validatedStagingIdentity in orderedEntries)return reject("source_already_admitted")
    if(revision!=queue.snapshot().mutationRevision)return reject("mutation_revision")
    val previous=orderedTail
    if(d.firstOrdinal!=(previous?.let{it.firstOrdinal+it.plan.totalRanges}?:0L))return reject("source_ordinal")
    if(previous?.let{!queue.layoutInstalled(it.validatedStagingIdentity,it.plan.totalRanges)}==true)return reject("previous_layout_incomplete")
    val token=resolveStage(d.validatedStagingIdentity)?:return reject("stage_missing")
    val rows=queue.reservation(token)?:return reject("reservation_missing")
    if(rows.isEmpty() ||rows.withIndex().any{(index,row)->row.key.sourceHandle!=d.validatedStagingIdentity
      ||row.key.rangeIndex!=index ||row.key.ordinal!=d.firstOrdinal+index ||row.totalRanges!=d.plan.totalRanges
      ||(row.kind==NCContinuousMuxedQueueState.RangeKind.VISUAL)!=d.silent})return reject("reservation_layout")
    var reply:OrderedReply?=null
    if(!d.silent) {
      val id=d.replyId!!
      reply=orderedReplies[id]
      if(reply==null) {
        if(d.sequenceIndex!=0)return reject("reply_first_sequence")
        if(orderedReplies.size>=2)return reject("capacity.replies")
        val expiry=NCContinuousMuxedDeadline.capture(d.expiresAtMs,wallNowMs(),elapsedNowMs())?:return reject("reply_expiry")
        val permission=guard.admitOrderedReply(orderedCarrier!!,id,expiry){reject("guard.$it")}?:return null
        reply=OrderedReply(permission);orderedReplies[id]=reply
      }
      if(reply.completed)return reject("reply_completed")
      if(d.sequenceIndex!=reply.nextSequence)return reject("reply_next_sequence")
      if(!guard.admitOrderedChunk(reply.permit,d.sourceId))return reject("guard.chunk_permission")
    }
    if(!journal.reserveOrderedSource(d.validatedStagingIdentity,d.silent) ||!queue.claimReservation(token)) {
      fence("ordered_reservation");return reject("reservation_commit")
    }
    val grant=OrderedGrant.create(this,run!!,d,reply?.permit)
    if(!presentation.registerOrderedSource(grant.id,d.plan,d.firstOrdinal,d.silent)
      ||outputLease?.attachOrderedSource(grant.id,reply?.permit)!=true) {
      fence("ordered_source_mapping");return reject("source_mapping")
    }
    orderedEntries[grant.id]=OrderedEntry(grant);orderedTail=d
    if(reply!=null)reply.nextSequence++
    return grant
  }
  @Synchronized internal fun allowsOrderedTimelineCommit(g:OrderedGrant,revision:Long):Boolean =
    orderedOwned(g) &&active() &&revision==queue.snapshot().mutationRevision
      &&(g.replyPermit?.currentNow()!=false)
  @Synchronized internal fun acknowledgeOrderedTimeline(g:OrderedGrant,token:NCContinuousMuxedQueueState.Token,
    revision:Long):NCContinuousMuxedQueueState.Ack {
    val rows=queue.reservation(token)
    if(!allowsOrderedTimelineCommit(g,revision) ||rows==null ||rows.any{it.key.sourceHandle!=g.id}) {
      fence("ordered_timeline_authority")
      return queue.snapshot().let{NCContinuousMuxedQueueState.Ack(it.runRevision,it.mutationRevision,it.tail,
        NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED)}
    }
    val ack=queue.commit(token,revision)
    if(ack.outcome!=NCContinuousMuxedQueueState.Outcome.COMMITTED)fence("ordered_timeline_ack")
    else outputLease?.publish(queue.outputKeys())
    return ack
  }
  private fun orderedEvent(e:OrderedEntry,kind:NCContinuousMuxedJournal.Kind):Boolean {
    if(journal.publish(e.grant.id,kind,elapsedNowMs()))return true
    fence("ordered_journal");return false
  }
  private fun reconcileOrderedPresentation(expectedRun:RunHandle):Boolean {
    if(expectedRun!=run ||!active())return false
    val epoch=presentation.protectedCursors().sinkEpoch
    if(epoch==0L)return true
    for(entry in orderedEntries.values) {
      val g=entry.grant;val d=g.descriptor
      if(!entry.started) {
        if(d.silent) {
          val proof=presentation.visualStartProof(g.id,expectedRun.revision,epoch)?:return true
          if(!proof.matches(presentation,g.id,expectedRun.revision,epoch))return false
        } else {
          val proof=presentation.sourceStartProof(g.id,expectedRun.revision,epoch)?:return true
          if(!guard.commitOrderedReceipts(g.replyPermit!!,listOf(d.sourceId to true)) {
            active() &&proof.matches(presentation,g.id,expectedRun.revision,epoch)
          })return false
        }
        if(!orderedEvent(entry,if(d.silent)NCContinuousMuxedJournal.Kind.VISUAL_STARTED else NCContinuousMuxedJournal.Kind.STARTED))return false
        entry.started=true
      }
      if(!entry.completed) {
        if(!queue.layoutInstalled(g.id,d.plan.totalRanges))return true
        if(d.silent) {
          val key=NCContinuousMuxedClipKey(g.id,d.plan.totalRanges-1,d.firstOrdinal+d.plan.totalRanges-1)
          val proof=presentation.visualCompletionProof(key,expectedRun.revision,epoch)?:return true
          if(!proof.matches(presentation,key,expectedRun.revision,epoch))return false
        } else {
          val proof=presentation.sourceCompletionProof(g.id,expectedRun.revision,epoch)?:return true
          if(!guard.commitOrderedReceipts(g.replyPermit!!,listOf(d.sourceId to false)) {
            active() &&proof.matches(presentation,g.id,expectedRun.revision,epoch)
          } ||!orderedEvent(entry,NCContinuousMuxedJournal.Kind.COMPLETED))return false
        }
        entry.completed=true
      }
    }
    return true
  }
  /** Caller supplies retained authenticated whole-reply finality, never just a
   * temporary empty queue. The Guard additionally requires every real receipt. */
  @Synchronized internal fun completeOrderedReply(expectedRun:RunHandle,replyId:String,finalSequence:Int):Boolean {
    if(expectedRun!=run ||!active() ||finalSequence !in 0..63)return false
    val reply=orderedReplies[replyId]?:return false
    if(reply.completed)return reply.nextSequence==finalSequence+1
    if(reply.nextSequence!=finalSequence+1)return false
    if(!guard.completeOrderedReply(reply.permit) {
      active() &&orderedEntries.values.filter{it.grant.descriptor.replyId==replyId}.all{it.completed}
        &&outputLease?.completeOrderedSpeech(reply.permit)==true
    })return false
    reply.completed=true;return releaseCompletedOrderedReply(replyId)
  }
  private fun reconcileOrderedClosures():Boolean {
    for(e in orderedEntries.values)if(!e.readersClosed &&queue.sourceReadersClosed(e.grant.id)) {
      val visual=e.grant.descriptor.silent
      if(!orderedEvent(e,if(visual)NCContinuousMuxedJournal.Kind.VISUAL_READERS_CLOSED else NCContinuousMuxedJournal.Kind.READERS_CLOSED))return false
      if(visual &&!orderedEvent(e,NCContinuousMuxedJournal.Kind.VISUAL_RETIRED))return false
      e.readersClosed=true
    }
    return true
  }
  @Synchronized internal fun releaseOrderedSource(g:OrderedGrant):Boolean {
    val e=orderedEntries[g.id]?:return false
    val joinedThrough=queue.snapshot().orderedReadersClosedThrough?:return false
    if(!orderedOwned(g) ||!e.readersClosed ||g.descriptor==orderedTail
      ||g.descriptor.firstOrdinal+g.descriptor.plan.totalRanges-1>joinedThrough
      ||journal.snapshot().events.any{it.sourceHandle==g.id} ||!presentation.forgetClosedOrderedSource(g.id))return false
    if(!outputLease!!.releaseOrderedSource(g.id) ||!queue.releaseOrderedSource(g.id) ||!journal.releaseOrderedSource(g.id)) {
      fence("ordered_release");return false
    }
    orderedEntries.remove(g.id)
    val replyId=g.descriptor.replyId
    return replyId==null ||releaseCompletedOrderedReply(replyId)
  }
  private fun releaseCompletedOrderedReply(replyId:String):Boolean {
    val reply=orderedReplies[replyId]?:return false
    if(!reply.completed ||orderedEntries.values.any{it.grant.descriptor.replyId==replyId})return true
    if(!guard.releaseOrderedReply(reply.permit){true} ||outputLease?.releaseOrderedReply(reply.permit)!=true) {
      fence("ordered_reply_release");return false
    }
    orderedReplies.remove(replyId);return true
  }
  /** Observation only: does not reconcile/publish receipts, acknowledge the
   * journal, renew deadlines, sample a player, or modify the output model. */
  @Synchronized internal fun orderedPlaybackClock(expectedRun:RunHandle):Map<String,Any?>? {
    val session=orderedSession?:return null
    val carrier=orderedCarrier?:return null
    if(expectedRun!=run ||failed ||drained)return null
    val paused=guard.orderedUserPauseState(carrier)?:return null
    val unknown=mapOf<String,Any?>("version" to 1,"run" to wireRun(expectedRun),
      "streamId" to session.streamId,"generation" to session.generation,"known" to false,
      "sourceId" to null,"replyId" to null,"sequenceIndex" to null,"seconds" to null,"userPaused" to paused)
    val clock=presentation.orderedPlaybackClock()?:return unknown
    val entry=orderedEntries[clock["sourceHandle"]]?:return unknown
    val d=entry.grant.descriptor
    val samples=clock["samples"] as? Long?:return unknown
    if(d.silent ||d.replyId==null ||entry.grant.replyPermit?.currentNow()!=true
      ||samples !in 1..d.plan.samples)return unknown
    return unknown+mapOf("known" to true,"sourceId" to d.sourceId,"replyId" to d.replyId,
      "sequenceIndex" to d.sequenceIndex,"seconds" to samples/48000.0)
  }
  @Synchronized internal fun orderedSnapshot(expectedRun:RunHandle):Map<String,Any?>? {
    if(expectedRun!=run ||orderedSession==null)return null
    if(!failed)active()
    val state=queue.snapshot();val events=journal.snapshot()
    return mapOf("version" to 1,"run" to wireRun(expectedRun),"streamId" to orderedSession!!.streamId,
      "generation" to orderedSession!!.generation,"state" to state.state.name.lowercase(),
      "nextOrdinal" to (state.tail?.ordinal?.plus(1)?:0L),"mutationRevision" to state.mutationRevision,
      "publishedCursor" to events.publishedCursor,"acknowledgedCursor" to events.acknowledgedCursor,
      "readersClosedThrough" to state.orderedReadersClosedThrough,
      "failure" to state.failure,"sources" to orderedEntries.values.map{e->
        val d=e.grant.descriptor
        mapOf("id" to e.grant.id,"sourceId" to d.sourceId,"kind" to d.kind,"replyId" to d.replyId,
          "sequenceIndex" to d.sequenceIndex,"firstOrdinal" to d.firstOrdinal,"rangeCount" to d.plan.totalRanges,
          "started" to e.started,"completed" to e.completed,"readersClosed" to e.readersClosed)
      })
  }
  @Synchronized internal fun readOrderedJournal(expectedRun:RunHandle,cursor:Long):Map<String,Any?>? {
    val snapshot=orderedSnapshot(expectedRun)?:return null;val events=journal.snapshot()
    if(cursor<events.acknowledgedCursor ||cursor>events.publishedCursor)return null
    val result=mapOf("version" to 1,"snapshot" to snapshot,"events" to events.events.filter{it.cursor>cursor}.map {
      mapOf("cursor" to it.cursor,"sourceId" to it.sourceHandle,"kind" to it.kind.wire)
    })
    val interruption=if(events.failure=="ordered_owner_cancelled")orderedCarrier?.let{guard.orderedInterruption(it)} else null
    return if(interruption==null)result else result+mapOf("interruption" to interruption.payload())
  }
  init {require(queue.runRevision==journal.runRevision && queue.runRevision==presentation.protectedCursors().runRevision)}

  private fun prefixReservation(d:NCContinuousMuxedSourceDescriptor):NCContinuousMuxedQueueState.Token? {
    val token=resolveStage(d.validatedStagingIdentity)?:return null
    val rows=queue.reservation(token)?:return null
    return token.takeIf {rows.size>=minOf(2,d.plan.totalRanges) && rows.withIndex().all {(index,row)->
      row.key.sourceHandle==d.validatedStagingIdentity && row.key.rangeIndex==index
        && row.totalRanges==d.plan.totalRanges}}
  }
  @Synchronized fun beginRun(d:NCContinuousMuxedSourceDescriptor,binding:NCPlaybackBinding):RunHandle? {
    if(run!=null || failed || prefixReservation(d)==null)return null
    val captured=NCContinuousMuxedDeadline.capture(d.expiresAtMs,wallNowMs(),elapsedNowMs())?:return null
    val enrolled=guard.enrollContinuous(binding,d.ticket,d.replyId,d.chunkId,d.recoveryEpoch,captured) {
      synchronized(this){fence("authority")}
    }?:return null
    return RunHandle(java.util.UUID.randomUUID().toString(),queue.runRevision).also {
      run=it;initial=d;permit=enrolled;deadline=captured
      outputLease=OutputLease.create(it,enrolled,presentation,captured,elapsedNowMs)}
  }
  @Synchronized fun nativeOutputLease(expectedRun:RunHandle):OutputLease? = outputLease?.takeIf {it.run==expectedRun}
  /** Retained identity only, including after revocation; not output permission. */
  @Synchronized internal fun nativeVisualGrant(expectedRun:RunHandle,id:String):VisualGrant? =
    visual?.takeIf {expectedRun==run &&it.run==expectedRun &&it.id==id}
  /** Admission survives an uncommitted prefix for forced cleanup, not permission. */
  @Synchronized internal fun nativeVisualGrant(expectedRun:RunHandle):VisualGrant? =
    visual?.takeIf {expectedRun==run &&it.run==expectedRun}
  @Synchronized internal fun refreshNativeOutputLease() {outputLease?.publish(queue.outputKeys())}
  private fun active():Boolean {
    if(failed || drained || run==null)return false
    if(terminal!=null) {if(!terminalActive())fence("terminal_invalid");return false}
    val current=permit
    val eligible=orderedCarrier?.let{guard.orderedCarrierEligible(it)}?:
      (current!=null &&guard.continuousEligible(current))
    if(!eligible) {
      // Guard revocation precedes its outside-lock callback. A reader may own
      // this monitor first; preserve cancellation identity so the exact frozen
      // onset receipt remains available, without granting the cancelled output.
      fence(if(orderedCarrier?.cancelled==true)"ordered_owner_cancelled" else "authority")
      return false
    }
    // Ordered carrier owns and serializes its deadline sample; independently
    // sampled timestamps here could falsely look like a clock rollback.
    if(orderedCarrier==null &&deadline?.active(elapsedNowMs())!=true) {fence("expiry");return false}
    if(outputLease?.isRevoked==true){fence("output_revocation");return false}
    if(!presentation.protectedCursors().known){fence("presentation");return false}
    if(journal.snapshot().failure!=null || queue.snapshot().state !in listOf(
      NCContinuousMuxedQueueState.State.OPEN,NCContinuousMuxedQueueState.State.SEALED)) {
      fence("native_state");return false
    }
    return true
  }
  private fun terminalActive():Boolean {
    val captured=terminal?:return false
    val snapshot=queue.snapshot()
    return !failed && !drained && permit?.let {guard.continuousEligible(it)}==true
      && snapshot.state==NCContinuousMuxedQueueState.State.SEALED && snapshot.pendingStages==0
      && snapshot.tail==captured.tail && snapshot.mutationRevision==captured.mutationRevision
      && captured.validPending()
  }
  private fun owned(grant:SourceGrant)=grant.origin===this && grant.run==run && entries[grant.id]?.grant===grant
  fun admitSource(expectedRun:RunHandle,d:NCContinuousMuxedSourceDescriptor,
    expectedMutationRevision:Long):SourceGrant? = admitSourceResult(expectedRun,d,expectedMutationRevision).grant
  @Synchronized fun admitSourceResult(expectedRun:RunHandle,d:NCContinuousMuxedSourceDescriptor,
    expectedMutationRevision:Long):AdmissionResult {
    if(expectedRun!=run ||visual!=null || !active() || queue.snapshot().state!=NCContinuousMuxedQueueState.State.OPEN
      || expectedMutationRevision!=queue.snapshot().mutationRevision
      || d.validatedStagingIdentity in entries)return AdmissionResult(AdmissionStatus.REJECTED)
    val previous=entries.values.lastOrNull()?.grant
    if(previous==null) {if(d!=initial)return AdmissionResult(AdmissionStatus.REJECTED)}
    else {
      if(!previous.descriptor.compatibleSuccessor(d) || !queue.layoutInstalled(previous.id,previous.descriptor.plan.totalRanges))
        return AdmissionResult(AdmissionStatus.REJECTED)
      val live=entries.values.filter {guard.observeContinuousChunk(permit!!,it.grant.chunkId)?.completed!=true}
      if(live.size>=2 || live.singleOrNull()?.let {
        guard.observeContinuousChunk(permit!!,it.grant.chunkId)?.started!=true}==true)return AdmissionResult(AdmissionStatus.FUTURE_OCCUPIED)
    }
    if(entries.size>=64)return AdmissionResult(AdmissionStatus.CAPACITY)
    val prefix=prefixReservation(d)?:return AdmissionResult(AdmissionStatus.REJECTED)
    // Queue range/byte reservation exists before this journal reservation and
    // before permission. Rejection leaves all staged files owned by the queue.
    if(!journal.reserveSource(d.validatedStagingIdentity))return AdmissionResult(AdmissionStatus.REJECTED)
    if(!guard.admitContinuousChunk(permit!!,d.chunkId)){fence("source_admission");return AdmissionResult(AdmissionStatus.REJECTED)}
    if(!queue.claimReservation(prefix)){fence("reservation");return AdmissionResult(AdmissionStatus.REJECTED)}
    val grant=SourceGrant.create(this,run!!,d)
    entries[grant.id]=Entry(grant)
    presentation.registerSource(grant.id,d.plan)
    if(!presentation.protectedCursors().known){fence("presentation");return AdmissionResult(AdmissionStatus.REJECTED)}
    return AdmissionResult(AdmissionStatus.ADMITTED,grant)
  }
  /** Permission is minted before concrete decoder exposure, but only the actual
   * mutation ACK below publishes keys. Staging or finality alone cannot play. */
  @Synchronized fun admitFinalReturn(expectedRun:RunHandle,parent:SourceGrant,d:NCContinuousMuxedReturnDescriptor,
    expectedTail:NCContinuousMuxedQueueState.Tail,expectedMutationRevision:Long,
    rejected:(String)->Unit={}):VisualGrant? {
    fun reject(reason:String):VisualGrant? {try{rejected(reason)}catch(_:Exception){};return null}
    fun checked(reason:String,value:Boolean):Boolean {if(!value)reject(reason);return value}
    if(expectedRun!=run)return reject("run_current")
    if(visual!=null)return reject("visual_absent")
    if(!owned(parent))return reject("parent_owned")
    if(!active())return reject("authority_active")
    if(entries.values.lastOrNull()?.grant!==parent)return reject("parent_is_last")
    if(!d.matches(parent.descriptor,rejected))return null
    val snapshot=queue.snapshot()
    if(snapshot.state!=NCContinuousMuxedQueueState.State.OPEN)return reject("queue.open")
    if(snapshot.tail!=expectedTail)return reject("queue.tail")
    if(snapshot.speechTail!=expectedTail)return reject("queue.speech_tail")
    if(snapshot.mutationRevision!=expectedMutationRevision)return reject("queue.mutation_revision")
    if(snapshot.pendingStages!=1)return reject("queue.pending_stages")
    if(expectedTail.sourceHandle!=parent.id)return reject("tail.parent")
    if(expectedTail.lastRange!=parent.descriptor.plan.totalRanges-1)return reject("tail.last_range")
    if(!queue.layoutInstalled(parent.id,parent.descriptor.plan.totalRanges))return reject("queue.layout_installed")
    val token=resolveStage(d.validatedStagingIdentity)?:return reject("stage.resolved")
    val rows=queue.reservation(token)?:return reject("stage.reservation")
    if(token.returnParent!=expectedTail)return reject("stage.return_parent")
    if(rows.size !in 2..6)return reject("stage.row_count")
    for((index,row) in rows.withIndex()) {
      if(row.kind!=NCContinuousMuxedQueueState.RangeKind.VISUAL)return reject("stage.row_kind")
      if(row.totalRanges!=0)return reject("stage.row_total")
      if(row.key.sourceHandle!=d.validatedStagingIdentity)return reject("stage.row_source")
      if(row.key.rangeIndex!=index)return reject("stage.row_index")
      if(row.key.ordinal!=expectedTail.ordinal+1+index)return reject("stage.row_ordinal")
    }
    val captured=NCContinuousMuxedDeadline.capture(d.expiresAtMs,wallNowMs(),elapsedNowMs())?:return reject("deadline.capture")
    var reserved=false
    val permission=guard.admitContinuousVisual(permit!!,captured,elapsedNowMs) {
      val current=queue.snapshot()
      checked("commit.snapshot_unchanged",current==snapshot)
        &&checked("commit.reservation_unchanged",queue.reservation(token)==rows)
        &&checked("commit.journal_reserved",journal.reserveVisualEpoch(d.validatedStagingIdentity,parent.id))
        .also {reserved=it}
        &&checked("commit.reservation_claimed",queue.claimReservation(token))
        &&checked("commit.presentation_registered",presentation.registerVisualSource(d.validatedStagingIdentity,
          NCContinuousMuxedClipKey(expectedTail.sourceHandle,expectedTail.lastRange,expectedTail.ordinal)))
    }?:run {if(reserved)fence("visual_reservation");return reject("guard.visual_permission")}
    val grant=VisualGrant.create(this,expectedRun,d,parent,expectedTail,token,permission)
    visual=grant
    if(outputLease?.attachVisual(grant.id,permission)!=true){fence("visual_authority");return reject("output.attach_visual")}
    return grant
  }
  @Synchronized fun acknowledgeReturn(grant:VisualGrant,token:NCContinuousMuxedQueueState.Token,
    expectedMutationRevision:Long):NCContinuousMuxedQueueState.Ack {
    val snapshot=queue.snapshot();val rows=queue.reservation(token)
    if(grant.origin!==this ||visual!==grant ||grant.run!=run ||!active() ||!grant.permission.currentNow()
      ||snapshot.state!=NCContinuousMuxedQueueState.State.OPEN ||snapshot.mutationRevision!=expectedMutationRevision
      ||rows==null ||rows.any {it.kind!=NCContinuousMuxedQueueState.RangeKind.VISUAL ||it.key.sourceHandle!=grant.id}
      ||(token.returnParent!=null &&(token!==grant.reservation ||token.returnParent!=grant.tail)))
      return NCContinuousMuxedQueueState.Ack(snapshot.runRevision,snapshot.mutationRevision,snapshot.tail,
        NCContinuousMuxedQueueState.Outcome.REJECTED_BEFORE_MUTATION)
    return queue.commit(token,expectedMutationRevision).also {
      if(it.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED)refreshNativeOutputLease()
    }
  }
  @Synchronized internal fun allowsReturnTimelineCommit(grant:VisualGrant,revision:Long):Boolean =
    grant.origin===this &&visual===grant &&grant.run==run &&active() &&grant.permission.currentNow()
      &&queue.snapshot().state==NCContinuousMuxedQueueState.State.OPEN &&queue.snapshot().mutationRevision==revision
  @Synchronized fun sourceDescriptor(grant:SourceGrant):NCContinuousMuxedSourceDescriptor {
    require(owned(grant));return grant.descriptor
  }
  @Synchronized fun allowsTimelineCommit(grant:SourceGrant,expectedMutationRevision:Long):Boolean =
    owned(grant) && active() && queue.snapshot().state==NCContinuousMuxedQueueState.State.OPEN
      && expectedMutationRevision==queue.snapshot().mutationRevision
  @Synchronized internal fun allowsNativeControl(expectedMutationRevision:Long):Boolean =
    active() && expectedMutationRevision==queue.snapshot().mutationRevision
  @Synchronized fun acknowledgeTimeline(grant:SourceGrant,token:NCContinuousMuxedQueueState.Token,
    expectedMutationRevision:Long):NCContinuousMuxedQueueState.Ack {
    val rows=queue.reservation(token)
    if(!allowsTimelineCommit(grant,expectedMutationRevision) || rows==null || rows.any {
      it.key.sourceHandle!=grant.id || it.totalRanges!=grant.descriptor.plan.totalRanges}) {
      val snapshot=queue.snapshot()
      return NCContinuousMuxedQueueState.Ack(snapshot.runRevision,snapshot.mutationRevision,snapshot.tail,
        NCContinuousMuxedQueueState.Outcome.REJECTED_BEFORE_MUTATION)
    }
    return queue.commit(token,expectedMutationRevision).also {
      if(it.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED)refreshNativeOutputLease()
    }
  }
  @Synchronized fun allowsProcessedOutput(grant:SourceGrant,key:NCContinuousMuxedClipKey,sinkEpoch:Long):Boolean {
    if(!owned(grant) || !active() ||permit?.speechDetached==true || key.sourceHandle!=grant.id || !queue.installed(key)
      || sinkEpoch !in 1..9007199254740991L)return false
    val cursors=presentation.protectedCursors()
    if(!cursors.known){fence("presentation");return false}
    return cursors.runRevision==grant.run.revision && (cursors.sinkEpoch==0L || cursors.sinkEpoch==sinkEpoch)
  }
  @Synchronized fun sourceState(grant:SourceGrant):NCContinuousMuxedSourceState? {
    if(!owned(grant))return null
    val entry=entries[grant.id]!!
    val observed=guard.observeContinuousChunk(permit!!,grant.chunkId)?:entry.lastObservation
    return NCContinuousMuxedSourceState(grant,queue.layoutInstalled(grant.id,grant.descriptor.plan.totalRanges),
      observed?.started==true,observed?.completed==true,queue.sourceReadersClosed(grant.id))
  }
  @Synchronized internal fun recordReadersClosed(grant:SourceGrant):Boolean {
    if(!owned(grant) || !queue.sourceReadersClosed(grant.id))return false
    // Housekeeping after natural retirement/cancellation is not permission to
    // manufacture any output receipt. Guard history remains in its own ledger.
    if(!journal.publish(grant.id,NCContinuousMuxedJournal.Kind.READERS_CLOSED,elapsedNowMs())) {
      fence("journal");return false
    }
    return true
  }
  @Synchronized internal fun reconcileReaderClosures():Boolean {
    if(orderedSession!=null)return reconcileOrderedClosures()
    if(!entries.values.filter {queue.sourceReadersClosed(it.grant.id)}.map {recordReadersClosed(it.grant)}.all {it})return false
    val returning=visual?:return true
    // OPEN empty visual windows are not epoch closure. Queue certifies a
    // non-OPEN epoch only after its actual installed and reserved readers join.
    if(!queue.sourceReadersClosed(returning.id))return true
    if(!journal.publish(returning.id,NCContinuousMuxedJournal.Kind.VISUAL_READERS_CLOSED,elapsedNowMs())) {
      fence("journal");return false
    }
    return true
  }
  private fun wireRun(value:RunHandle):Map<String,Any> = mapOf("id" to value.id,"revision" to value.revision)
  /** Housekeeping only, after actual queue closure and positive sink settlement.
   * It cannot create onset, a speech receipt or a new output permission. */
  @Synchronized internal fun recordMixedRetirement(certificate:NCContinuousMuxedQueue.MixedRetirement):Boolean {
    if(certificate.run!=run ||certificate.visual!==visual ||!certificate.matches(this)
      ||!queue.sourceReadersClosed(certificate.visual.id)
      ||!journal.hasPublished(certificate.visual.id,NCContinuousMuxedJournal.Kind.VISUAL_READERS_CLOSED))return false
    mixedRetirement?.let {return it===certificate}
    if(!journal.publish(certificate.visual.id,NCContinuousMuxedJournal.Kind.VISUAL_RETIRED,elapsedNowMs()))return false
    mixedRetirement=certificate;return true
  }
  private fun wireSource(value:SourceGrant):Map<String,Any> = mapOf("run" to wireRun(value.run),
    "id" to value.id,"chunkId" to value.chunkId,"sequenceIndex" to value.sequenceIndex)
  private fun wireVisual(value:VisualGrant):Map<String,Any> = mapOf("run" to wireRun(value.run),
    "id" to value.id,"parent" to wireSource(value.parent))
  private fun wireTail(tail:NCContinuousMuxedQueueState.Tail,revision:Long):Map<String,Any>? {
    val speech=entries[tail.sourceHandle]?.grant
    val returning=visual?.takeIf {it.id==tail.sourceHandle}
    val source=if(speech!=null)wireSource(speech) else returning?.let {wireVisual(it)}?:return null
    return mapOf("kind" to if(speech!=null)"speech" else "visual","source" to source,
      "nextRange" to tail.lastRange+1,"appendRevision" to revision)
  }
  /** Copied current-protocol data, never authority. Startup before the initial
   * prefix ACK has no wire tail; the factory must resolve/retire that privately.
   * Only an actually playing source exposes its conservative source watermark.
   */
  @Synchronized fun runSnapshot(expectedRun:RunHandle):Map<String,Any?>? {
    if(expectedRun!=run)return null
    val live=active()
    val snapshot=queue.snapshot();val tail=snapshot.tail?:return null
    val physicalTail=wireTail(tail,snapshot.mutationRevision)?:return null
    val speechTail=snapshot.speechTail?.let {wireTail(it,snapshot.mutationRevision)}?:return null
    val journalState=journal.snapshot()
    val sources=entries.values.map {sourceState(it.grant)!!}
    val current=sources.singleOrNull {it.started && !it.completed}
    val observed=current?.let {guard.observeContinuousChunk(permit!!,it.grant.chunkId)}
    val watermark=if(live && observed?.playing==true)presentation.evidence(current!!.grant.id) else null
    val speechClock=watermark?.takeIf {it.started && !it.naturalEnd && presentation.protectedCursors().known}?.let {
      mapOf("kind" to "speech","source" to wireSource(current!!.grant),"seconds" to it.presentedSamples.toDouble()/48000.0,
        "playing" to true,"buffering" to false)
    }
    val returning=visual
    val visualClock=returning?.takeIf {live &&permit?.speechDetached==true
      &&permit?.binding?.actions?.ncIsPlayingSnapshot==true &&it.permission.currentNow()}?.let {value->
      val cursors=presentation.protectedCursors()
      presentation.visualStartProof(value.id,expectedRun.revision,cursors.sinkEpoch)?.takeIf {
        it.matches(presentation,value.id,expectedRun.revision,cursors.sinkEpoch)
      }?.let {proof->mapOf("kind" to "visual","source" to wireVisual(value),
        "seconds" to proof.presentedSamples.toDouble()/48000.0,"playing" to true,"buffering" to false)}
    }
    val visualState=returning?.let {mapOf("epoch" to wireVisual(it),
      "started" to journal.hasPublished(it.id,NCContinuousMuxedJournal.Kind.VISUAL_STARTED),
      "readersClosed" to journal.hasPublished(it.id,NCContinuousMuxedJournal.Kind.VISUAL_READERS_CLOSED),
      "retired" to journal.hasPublished(it.id,NCContinuousMuxedJournal.Kind.VISUAL_RETIRED))}
    val cause=snapshot.failure?:journalState.failure
    return mapOf("version" to 2,"run" to wireRun(expectedRun),"state" to snapshot.state.name.lowercase(java.util.Locale.ROOT),
      "publishedCursor" to journalState.publishedCursor,"acknowledgedCursor" to journalState.acknowledgedCursor,
      "tail" to physicalTail,"speechTail" to speechTail,"visual" to visualState,
      "speechMembershipCompleted" to (permit?.speechDetached==true),
      "retirement" to mixedRetirement?.let {mapOf("mode" to if(it.natural)"natural" else "forced",
        "run" to wireRun(it.run),"visual" to wireVisual(it.visual),"mutationRevision" to it.closure.mutationRevision)},
      "sources" to sources.map {mapOf("source" to wireSource(it.grant),"layoutInstalled" to it.layoutInstalled,
        "started" to it.started,"completed" to it.completed,"readersClosed" to it.readersClosed)},
      "clock" to (visualClock?:speechClock),"failure" to cause?.let {mapOf("code" to
        if(it.matches(Regex("[A-Za-z0-9_.-]{1,128}")))it else "native_failure")})
  }
  @Synchronized fun readJournal(expectedRun:RunHandle,afterCursor:Long):Map<String,Any?>? {
    if(expectedRun!=run)return null
    // The permission refresh can fence/flush and reconcile native readers.
    // Capture the journal only after those same-thread publications settle.
    val snapshot=runSnapshot(expectedRun)?:return null
    val journalState=journal.snapshot()
    if(afterCursor<journalState.acknowledgedCursor || afterCursor>journalState.publishedCursor)return null
    val events=journalState.events.filter {it.cursor>afterCursor}.map {
      val isVisual=it.kind in listOf(NCContinuousMuxedJournal.Kind.VISUAL_STARTED,
        NCContinuousMuxedJournal.Kind.VISUAL_READERS_CLOSED,NCContinuousMuxedJournal.Kind.VISUAL_RETIRED)
      val source=if(isVisual)visual?.takeIf {value->value.id==it.sourceHandle}?.let {value->wireVisual(value)}
        else entries[it.sourceHandle]?.grant?.let {value->wireSource(value)}
      if(source==null)return null
      mapOf("cursor" to it.cursor,"run" to wireRun(expectedRun),"source" to source,
        "membership" to if(isVisual)"visual" else "speech","kind" to it.kind.wire)
    }
    return mapOf("version" to 2,"snapshot" to snapshot,"events" to events)
  }
  @Synchronized fun acknowledgeJournal(expectedRun:RunHandle,cursor:Long):Boolean =
    expectedRun==run && journal.acknowledge(expectedRun.revision,cursor)
  private fun proofEligible(grant:SourceGrant,epoch:Long,complete:Boolean):Boolean = owned(grant)
    && active() && epoch>0 && presentation.protectedCursors().let {
      it.known && it.runRevision==grant.run.revision && it.sinkEpoch==epoch}
    && (!complete || queue.layoutInstalled(grant.id,grant.descriptor.plan.totalRanges))
  /** Native worker consumes the model's actual conservative watermark. This
   * updates the existing Guard ledger even while JavaScript is suspended.
   * A shared endpoint commits outgoing completion before incoming onset in
   * the same Guard transaction; input/enqueue alone produces neither.
   */
  @Synchronized fun reconcileNativePresentation(expectedRun:RunHandle):Boolean {
    if(orderedSession!=null)return reconcileOrderedPresentation(expectedRun)
    if(expectedRun!=run)return false
    if(drained)return true
    if(terminal!=null)return terminalActive()
    if(!active())return false
    if(permit?.speechDetached==true)return reconcileVisualPresentation()
    val cursors=presentation.protectedCursors()
    if(!cursors.known)return false
    if(cursors.sinkEpoch==0L)return true
    val sources=entries.values.map {it.grant}
    var index=0
    while(index<sources.size) {
      val current=sources[index]
      var observed=guard.observeContinuousChunk(permit!!,current.chunkId)?:return false
      if(!observed.started) {
        val start=presentation.sourceStartProof(current.id,expectedRun.revision,cursors.sinkEpoch)?:return true
        if(!recordStarted(guard,current,start))return false
        observed=guard.observeContinuousChunk(permit!!,current.chunkId)?:return false
      }
      if(!observed.completed) {
        val end=presentation.sourceCompletionProof(current.id,expectedRun.revision,cursors.sinkEpoch)?:return true
        val next=sources.getOrNull(index+1)
        val start=next?.let {presentation.sourceStartProof(it.id,expectedRun.revision,cursors.sinkEpoch)}
        if(next!=null && start!=null) {
          if(!recordBoundary(guard,current,end,next,start))return false
        } else if(!recordCompleted(guard,current,end))return false
      }
      index++
    }
    val returning=visual
    return (if(returning!=null &&returnInstalled(returning))completeSpeechMembership(returning) else true)
      &&reconcileVisualPresentation()
  }
  private fun returnInstalled(grant:VisualGrant):Boolean {
    val snapshot=queue.snapshot()
    return visual===grant &&snapshot.speechTail==grant.tail &&snapshot.tail?.let {
      it.sourceHandle==grant.id &&it.lastRange>=1
    }==true // Exact ACK history survives genuine protected prefix pruning.
  }
  private fun reconcileVisualPresentation():Boolean {
    val returning=visual?:return true
    if(!returnInstalled(returning))return true
    val cursors=presentation.protectedCursors()
    val proof=presentation.visualStartProof(returning.id,returning.run.revision,cursors.sinkEpoch)?:return true
    if(!returning.permission.currentNow() ||!proof.matches(presentation,returning.id,returning.run.revision,cursors.sinkEpoch))return false
    if(!journal.publish(returning.id,NCContinuousMuxedJournal.Kind.VISUAL_STARTED,elapsedNowMs())) {
      fence("journal");return false
    }
    return true
  }
  /** The native worker owns this transaction. No JS acknowledgement, global
   * END, reader cleanup or source replacement is needed at the final endpoint. */
  private fun completeSpeechMembership(grant:VisualGrant):Boolean {
    val current=permit?:return false
    if(current.speechDetached)return true
    val cursors=presentation.protectedCursors()
    if(!returnInstalled(grant) ||!cursors.known ||cursors.runRevision!=grant.run.revision ||cursors.sinkEpoch<=0)return false
    val completed=entries.values.map {entry->
      val source=entry.grant
      if(guard.observeContinuousChunk(current,source.chunkId)?.completed!=true
        ||!queue.layoutInstalled(source.id,source.descriptor.plan.totalRanges))return false
      source to (presentation.sourceCompletionProof(source.id,source.run.revision,cursors.sinkEpoch)?:return false)
    }
    if(!guard.completeContinuousSpeech(current,grant.permission) {
      returnInstalled(grant) &&grant.permission.currentNow() &&completed.all {(source,proof)->
        proof.matches(presentation,source.id,source.run.revision,cursors.sinkEpoch)
      }
    })return false
    if(!journal.publish(grant.parent.id,NCContinuousMuxedJournal.Kind.SPEECH_MEMBERSHIP_COMPLETED,elapsedNowMs())) {
      fence("journal");return false
    }
    return true
  }
  private fun publish(grant:SourceGrant,kind:NCContinuousMuxedJournal.Kind):Boolean {
    entries[grant.id]!!.lastObservation=guard.observeContinuousChunk(permit!!,grant.chunkId)
    if(!journal.publish(grant.id,kind,elapsedNowMs())){fence("journal");return false}
    return true
  }
  @Synchronized internal fun recordStarted(caller:NCPlaybackGuard,grant:SourceGrant,
    proof:NCContinuousMuxedPresentation.SourceStartProof):Boolean {
    if(caller!==guard || !proofEligible(grant,proof.sinkEpoch,false))return false
    if(!guard.commitContinuousReceipts(permit!!,listOf(grant.chunkId to true)) {
      deadline?.active(elapsedNowMs())==true
        && proof.matches(presentation,grant.id,grant.run.revision,proof.sinkEpoch)}) {
      active();return false
    }
    return publish(grant,NCContinuousMuxedJournal.Kind.STARTED)
  }
  @Synchronized internal fun recordCompleted(caller:NCPlaybackGuard,grant:SourceGrant,
    proof:NCContinuousMuxedPresentation.SourceNaturalCompletionProof):Boolean {
    if(caller!==guard || !proofEligible(grant,proof.sinkEpoch,true))return false
    if(!guard.commitContinuousReceipts(permit!!,listOf(grant.chunkId to false)) {
      deadline?.active(elapsedNowMs())==true && queue.layoutInstalled(grant.id,grant.descriptor.plan.totalRanges)
        && proof.matches(presentation,grant.id,grant.run.revision,proof.sinkEpoch)}) {
      active();return false
    }
    return publish(grant,NCContinuousMuxedJournal.Kind.COMPLETED)
  }
  @Synchronized internal fun recordBoundary(caller:NCPlaybackGuard,outgoing:SourceGrant,
    end:NCContinuousMuxedPresentation.SourceNaturalCompletionProof,incoming:SourceGrant,
    start:NCContinuousMuxedPresentation.SourceStartProof):Boolean {
    if(caller!==guard || !proofEligible(outgoing,end.sinkEpoch,true) || !proofEligible(incoming,start.sinkEpoch,false)
      || end.sinkEpoch!=start.sinkEpoch || !outgoing.descriptor.compatibleSuccessor(incoming.descriptor))return false
    if(!guard.commitContinuousReceipts(permit!!,listOf(outgoing.chunkId to false,incoming.chunkId to true)) {
      deadline?.active(elapsedNowMs())==true && queue.layoutInstalled(outgoing.id,outgoing.descriptor.plan.totalRanges)
        && end.matches(presentation,outgoing.id,outgoing.run.revision,end.sinkEpoch)
        && start.matches(presentation,incoming.id,incoming.run.revision,start.sinkEpoch)}) {
      active();return false
    }
    // The ledger commit is one guard transaction: A completion precedes B onset.
    return publish(outgoing,NCContinuousMuxedJournal.Kind.COMPLETED)
      && publish(incoming,NCContinuousMuxedJournal.Kind.STARTED)
  }
  /** Native application-thread callback only, after the concrete adapter has
   * matched genuine current-item STATE_ENDED. Global END creates no receipt.
   * This inactive run retains journal/history without poisoning the reply.
   */
  @Synchronized fun recordNativeRunEnd(expectedRun:RunHandle,expectedTail:NCContinuousMuxedQueueState.Tail,
    expectedMutationRevision:Long):Boolean {
    terminal?.let {captured->
      if(expectedRun!=run || expectedTail!=captured.tail || expectedMutationRevision!=captured.mutationRevision
        || !terminalActive() || !captured.validEnded())return false
      val retired=guard.retireContinuous(permit!!) {
        deadline?.active(elapsedNowMs())==true && captured.validEnded()
          && markNaturalDrain(expectedTail,expectedMutationRevision)
      }
      if(!retired){if(!terminalActive())fence("terminal_invalid");return false}
      drained=true;return true
    }
    if(expectedRun!=run ||visual!=null || !active() || entries.isEmpty())return false
    val snapshot=queue.snapshot();val cursors=presentation.protectedCursors()
    if(snapshot.state!=NCContinuousMuxedQueueState.State.SEALED || snapshot.tail!=expectedTail
      || snapshot.mutationRevision!=expectedMutationRevision || snapshot.pendingStages!=0
      || !cursors.known || cursors.runRevision!=expectedRun.revision || cursors.sinkEpoch<=0)return false
    val completed=entries.values.map {entry->
      val grant=entry.grant;val observation=guard.observeContinuousChunk(permit!!,grant.chunkId)
      if(observation?.completed!=true || !queue.layoutInstalled(grant.id,grant.descriptor.plan.totalRanges))return false
      val proof=presentation.sourceCompletionProof(grant.id,expectedRun.revision,cursors.sinkEpoch)?:return false
      Triple(entry,observation,proof)
    }
    val retired=guard.retireContinuous(permit!!) {
      deadline?.active(elapsedNowMs())==true && completed.all {(entry,_,proof)->
        proof.matches(presentation,entry.grant.id,expectedRun.revision,cursors.sinkEpoch)
      } && markNaturalDrain(expectedTail,expectedMutationRevision)
    }
    if(!retired){active();return false}
    completed.forEach {(entry,observation,_)->entry.lastObservation=observation}
    drained=true;return true
  }
  private fun markNaturalDrain(tail:NCContinuousMuxedQueueState.Tail,revision:Long):Boolean {
    // Publish under the successful Guard retirement validation transaction,
    // BEFORE its volatile permit cancellation. Old expiry work cannot mistake
    // that natural revoke for Stop while application-thread cleanup catches up.
    // Atomic lease retirement must win against revoke before DRAINED publishes.
    return queue.markDrained(tail,revision) {outputLease?.retireNaturally()==true}
  }
  /** Concrete Queue invokes this under its mutation gate, off the output path.
   * Pending mutations must have settled first. END later consumes the stored
   * token, never supplied JS metadata or diagnostic historical rows.
   */
  @Synchronized fun attestTerminal(expectedRun:RunHandle,expectedTail:NCContinuousMuxedQueueState.Tail,
    expectedMutationRevision:Long,witness:NCContinuousMuxedOutputGate.TrackWitness):TerminalAttestation? {
    if(expectedRun!=run || terminal!=null || !active() || entries.isEmpty())return null
    val snapshot=queue.snapshot();val cursors=presentation.protectedCursors();val lease=outputLease?:return null
    if(snapshot.state!=NCContinuousMuxedQueueState.State.SEALED || snapshot.tail!=expectedTail
      || snapshot.mutationRevision!=expectedMutationRevision || snapshot.pendingStages!=0
      || !cursors.known || !witness.matchesLive(lease,cursors.sinkEpoch))return null
    val tailKey=NCContinuousMuxedClipKey(expectedTail.sourceHandle,expectedTail.lastRange,expectedTail.ordinal)
    val visualProof=visual?.let {returning->
      if(permit?.speechDetached!=true ||expectedTail.sourceHandle!=returning.id ||!returning.permission.currentNow())return null
      presentation.visualCompletionProof(tailKey,expectedRun.revision,cursors.sinkEpoch)?:return null
    }
    val proofs=entries.values.map {entry->
      val grant=entry.grant
      if(!queue.layoutInstalled(grant.id,grant.descriptor.plan.totalRanges))return null
      presentation.sourceCompletionProof(grant.id,expectedRun.revision,cursors.sinkEpoch)?:return null
    }
    var captured:TerminalAttestation?=null
    if(!guard.validateContinuousTerminal(permit!!,true) {
      deadline?.active(elapsedNowMs())==true && witness.matchesLive(lease,cursors.sinkEpoch)
        &&(visualProof==null ||visualProof.matches(presentation,tailKey,expectedRun.revision,cursors.sinkEpoch))
        && proofs.withIndex().all {(index,proof)->proof.matches(presentation,
          entries.values.elementAt(index).grant.id,expectedRun.revision,cursors.sinkEpoch)}
        && run {
          if(!lease.selectTerminal(witness))false else {
            captured=TerminalAttestation.create(lease,witness,presentation,expectedTail,expectedMutationRevision)
            terminal=captured;true
          }
        }
    })return null
    return captured
  }
  private fun fence(cause:String) {
    if(failed || drained)return
    failed=true;outputLease?.revoke();queue.fence(cause);journal.latchTerminalFailure(cause);presentation.fence("authority")
    permit?.let {guard.invalidateContinuous(it)}
    orderedCarrier?.let {guard.invalidateOrderedCarrier(it)}
    // Concrete player integration must synchronously stop AND flush only the
    // exact enrolled owner; deleting a grant cannot revoke already queued PCM.
    stopAndFlush()
  }
  @Synchronized fun fenceRun(expectedRun:RunHandle,cause:String) {if(expectedRun==run)fence(cause)}
}

/** Strong native-only entrypoints. The small guard stays independent of Media3;
 * these adapters validate exact model-origin proof before its ledger transaction.
 */
internal fun NCPlaybackGuard.recordContinuousStarted(grant:NCContinuousMuxedAuthority.SourceGrant,
  proof:NCContinuousMuxedPresentation.SourceStartProof)=grant.origin.recordStarted(this,grant,proof)
internal fun NCPlaybackGuard.recordContinuousNaturallyCompleted(grant:NCContinuousMuxedAuthority.SourceGrant,
  proof:NCContinuousMuxedPresentation.SourceNaturalCompletionProof)=grant.origin.recordCompleted(this,grant,proof)
internal fun NCPlaybackGuard.recordContinuousBoundary(outgoing:NCContinuousMuxedAuthority.SourceGrant,
  end:NCContinuousMuxedPresentation.SourceNaturalCompletionProof,incoming:NCContinuousMuxedAuthority.SourceGrant,
  start:NCContinuousMuxedPresentation.SourceStartProof)=outgoing.origin.recordBoundary(this,outgoing,end,incoming,start)
