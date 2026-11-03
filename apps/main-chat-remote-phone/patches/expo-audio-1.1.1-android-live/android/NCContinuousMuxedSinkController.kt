package expo.modules.audio

import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import androidx.media3.exoplayer.audio.AudioSink
import java.util.IdentityHashMap

/** Native ownership assembly, dormant until wired to the normal provider/sink.
 * Strong records are independent of routing weak references and player source
 * generations. No record here grants output, certifies presentation, closes a
 * reader or settles a sink. Reclamation requires the later exact settlement
 * transaction; neither absence nor an asynchronous release hint can do that.
 */
internal class NCContinuousMuxedSinkController(private val threadCheck:(()->Boolean)?=null) {
  private var lockPauseScope:NCPlaybackGuard.LockPausePermit?=null
  private var lockPauseConsumed=false
  /** Player messages bracket setPlayWhenReady(false) on ExoPlayer's own
   * playback looper. No permission survives that command, even if unlock on
   * the application thread happens before the pause command is consumed. */
  fun pauseForLock(permit:NCPlaybackGuard.LockPausePermit,post:((()->Unit)->Unit),pause:()->Unit,
    completed:(Boolean)->Unit={}) {
    try {
      post {
        val admitted=isOutputThread()&&permit.currentNow()
        if(admitted){lockPauseScope=permit;lockPauseConsumed=false}
        logLockPause(1,admitted)
      }
      try {pause()} finally {
        post {
          val consumed=lockPauseScope===permit&&lockPauseConsumed
          val accepted=lockPauseScope===permit&&permit.currentNow()
          if(lockPauseScope===permit){lockPauseScope=null;lockPauseConsumed=false}
          permit.revoke();logLockPause(2,consumed)
          completed(accepted)
        }
      }
    } catch(error:RuntimeException) {permit.revoke();throw error}
  }
  /** Called after the exact pause command on the output looper, never from JS
   * or a UI position estimate. Preserve the existing timestamp admission. */
  fun orderedContinuationPosition(queue:NCContinuousMuxedQueue):Map<String,Long>? {
    if(!isOutputThread())return null
    val enrolled=synchronized(this){sinks.values.mapNotNull{it.enrollment}.singleOrNull()}?:return null
    val record=enrolled.record?:return null
    if(enrolled.queue!==queue ||enrolled.lease.isRevoked ||record.actual.playState==AudioTrack.PLAYSTATE_PLAYING)return null
    enrolled.observation.sampleTrack()
    if(enrolled.lease.isRevoked ||!ownsTrack(enrolled.slot,record,record.actual))return null
    return enrolled.model.orderedContinuationPosition()
  }
  private fun logLockPause(event:Int,accepted:Boolean) {
    try {Log.d("NCContinuousPause","event=$event accepted=${if(accepted)1 else 0} elapsedMs=${SystemClock.elapsedRealtime()}")}
    catch(_:RuntimeException) {} // Two causal rows per lock; never a progress snapshot or grant.
  }
  class SinkSlot internal constructor(internal val baseline:NCContinuousMuxedSinkBaseline)
  class TrackRecord internal constructor(internal val sink:SinkSlot,internal val actual:AudioTrack,
    internal val capturedInitialized:Boolean,internal val providerEpoch:Long)
  class Enrollment internal constructor(internal val slot:SinkSlot,internal val lease:NCContinuousMuxedAuthority.OutputLease,
    internal val model:NCContinuousMuxedPresentation,internal val observation:NCContinuousMuxedObservation) {
    internal lateinit var gate:NCContinuousMuxedOutputGate
    @Volatile internal var record:TrackRecord?=null
    @Volatile internal var capture:NCContinuousMuxedPresentation.NativeTrackCapture?=null
    @Volatile internal var queue:NCContinuousMuxedQueue?=null
    @Volatile internal var postProofWork:((()->Unit)->Boolean)?=null
    internal val proofBusy=java.util.concurrent.atomic.AtomicBoolean()
    @Volatile internal var terminalDiagnosticWindow:Pair<Long,Long>?=null
    internal var terminalDiagnosticPhase=-1
    @Volatile internal var terminal:NCContinuousMuxedAuthority.TerminalAttestation?=null
    internal var normalStopScope=false
    @Volatile internal var bufferingStopWitness:NCContinuousMuxedTailSource.HeldEof?=null
  }
  class Admission internal constructor(internal val slot:SinkSlot,internal val enrollment:Enrollment?,
    internal val key:NCContinuousMuxedClipKey?,val allowed:Boolean,internal val delegated:Boolean)
  class SinkSettlement private constructor(private val owner:NCContinuousMuxedSinkController,
    internal val prior:Enrollment,internal val delegate:AudioSink,internal val providerRevision:Long,
    internal val providerEpoch:Long) {
    private val consumed=java.util.concurrent.atomic.AtomicBoolean()
    private val observerClaimed=java.util.concurrent.atomic.AtomicBoolean()
    internal val isConsumed get()=consumed.get()
    internal fun belongsTo(controller:NCContinuousMuxedSinkController)=owner===controller
    internal fun canInspectRetirement():Boolean = !owner.isOutputThread() &&!consumed.get()
    /** Control-thread inspection of an issuer-published positive settlement.
     * Never substitutes a look-alike, consumed witness or another queue owner. */
    internal fun matchesRetirement(queue:NCContinuousMuxedQueue,
      closure:NCContinuousMuxedQueue.RetirementWitness,lease:NCContinuousMuxedAuthority.OutputLease):Boolean =
      canInspectRetirement() &&owner.ownsSettlement(this)
        &&prior.queue===queue &&prior.lease===lease &&closure.matches(queue,lease.run)
    internal fun canStageObservation(observation:NCContinuousMuxedObservation,old:NCContinuousMuxedPresentation?,slot:Any?)=
      !consumed.get() && owner.ownsSettlement(this) && observation===prior.observation
        && old===prior.model && slot===prior.slot
    internal fun consume(controller:NCContinuousMuxedSinkController)=owner===controller
      && owner.isOutputThread() && owner.ownsSettlement(this) && consumed.compareAndSet(false,true)
    internal fun claimObservation(observation:NCContinuousMuxedObservation,old:NCContinuousMuxedPresentation?,slot:Any?)=
      consumed.get() && owner.isOutputThread() && owner.ownsSettlement(this)
        && observation===prior.observation && old===prior.model && slot===prior.slot
        && observerClaimed.compareAndSet(false,true)
    companion object {internal fun create(owner:NCContinuousMuxedSinkController,prior:Enrollment,
      delegate:AudioSink,revision:Long,epoch:Long)=SinkSettlement(owner,prior,delegate,revision,epoch)}
  }
  private class SettlementAttempt(val prior:Enrollment,val closure:NCContinuousMuxedQueue.RetirementWitness,
    val delegate:AudioSink,val providerRevision:Long,val discard:NCContinuousMuxedOutputGate.DiscardAck?) {
    var failed=false
    var witness:SinkSettlement?=null
  }
  class IdleSettlement private constructor(private val owner:NCContinuousMuxedSinkController,
    internal val slot:SinkSlot,internal val closure:NCMuxedTrialSourceOwner.Retirement,
    internal val observation:NCContinuousMuxedObservation,internal val priorModel:NCContinuousMuxedPresentation?,
    internal val providerRevision:Long,internal val providerEpoch:Long) {
    private val consumed=java.util.concurrent.atomic.AtomicBoolean()
    private val observerClaimed=java.util.concurrent.atomic.AtomicBoolean()
    internal val isConsumed get()=consumed.get()
    internal fun canStageObservation(observer:NCContinuousMuxedObservation,old:NCContinuousMuxedPresentation?,identity:Any?)=
      !consumed.get() && owner.ownsIdleSettlement(this) && observer===observation && old===priorModel && identity==null
    internal fun consume(controller:NCContinuousMuxedSinkController)=owner===controller && owner.isOutputThread()
      && owner.ownsIdleSettlement(this) && consumed.compareAndSet(false,true)
    internal fun claimObservation(observer:NCContinuousMuxedObservation,old:NCContinuousMuxedPresentation?,identity:Any?)=
      consumed.get() && owner.isOutputThread() && owner.ownsIdleSettlement(this)
        && observer===observation && old===priorModel && identity==null && observerClaimed.compareAndSet(false,true)
    companion object {internal fun create(owner:NCContinuousMuxedSinkController,slot:SinkSlot,
      closure:NCMuxedTrialSourceOwner.Retirement,observation:NCContinuousMuxedObservation,
      model:NCContinuousMuxedPresentation?,revision:Long,epoch:Long)=
      IdleSettlement(owner,slot,closure,observation,model,revision,epoch)}
  }
  private class IdleSettlementAttempt(val closure:NCMuxedTrialSourceOwner.Retirement,val delegate:AudioSink,
    val providerRevision:Long,val pristine:NCContinuousMuxedSinkBaseline.ConstructionProof?) {
    var failed=false
    var witness:IdleSettlement?=null
  }
  private class SinkState(var baseline:NCContinuousMuxedSinkBaseline) {
    var delegate:AudioSink?=null
    var observation:NCContinuousMuxedObservation?=null
    var latest:TrackRecord?=null
    var providerEpoch=0L
    var providerRevision=0L
    @Volatile var targeted=false
    @Volatile var permanentlyClosed=false
    @Volatile var enrollment:Enrollment?=null
    var pending:Admission?=null
    var settlement:SettlementAttempt?=null
    var sourceOwner:NCMuxedTrialSourceOwner?=null
    var idleSettlement:IdleSettlementAttempt?=null
  }
  private val sinks=IdentityHashMap<SinkSlot,SinkState>()
  private val delegates=IdentityHashMap<AudioSink,SinkSlot>()
  private val tracks=IdentityHashMap<AudioTrack,TrackRecord>()
  @Volatile private var playbackHandler:Handler?=null
  private fun isOutputThread():Boolean=threadCheck?.invoke()
    ?: playbackHandler?.let {Looper.myLooper()===it.looper}==true
  @Synchronized fun attachPlaybackHandler(handler:Handler):Boolean {
    if(playbackHandler!=null)return playbackHandler===handler
    playbackHandler=handler;return true
  }

  /** Called during construction, before the normal delegate can escape. */
  @Synchronized fun openSink():SinkSlot = SinkSlot(NCContinuousMuxedSinkBaseline(::isOutputThread)).also {
    sinks[it]=SinkState(it.baseline)
  }
  @Synchronized fun bindDelegate(slot:SinkSlot,delegate:AudioSink):Boolean {
    val state=sinks[slot]?:return false
    if(state.delegate!=null || delegates.containsKey(delegate))return false
    state.delegate=delegate;delegates[delegate]=slot;return true
  }
  /** The maintained wrapper establishes its exact observer before exposure. */
  @Synchronized fun bindObservation(slot:SinkSlot,observation:NCContinuousMuxedObservation):Boolean {
    val state=sinks[slot]?:return false
    if(state.observation!=null)return state.observation===observation
    if(state.targeted)return false
    state.observation=observation;return true
  }
  @Synchronized fun bindSourceOwner(slot:SinkSlot,owner:NCMuxedTrialSourceOwner):Boolean {
    val state=sinks[slot]?:return false
    if(state.sourceOwner!=null)return state.sourceOwner===owner
    if(state.targeted || state.idleSettlement!=null)return false
    state.sourceOwner=owner;return true
  }
  /** Provider callback only. Keep even an unknown/uninitialized actual track
   * owned for failure cleanup, but never upgrade its initial evidence later.
   */
  @Synchronized fun providerCreated(slot:SinkSlot,actual:AudioTrack):TrackRecord? {
    if(!isOutputThread())return null
    val state=sinks[slot]?:return null
    if(state.delegate==null)return null
    state.baseline.providerEntered()
    if(state.providerRevision==9007199254740991L)return null
    state.providerRevision++
    state.settlement?.failed=true // Retain unexpected tracks, never inherit a prior clear.
    state.idleSettlement?.failed=true
    tracks[actual]?.let {return if(it.sink===slot)it else null}
    val initialized=try {actual.state==AudioTrack.STATE_INITIALIZED} catch(_:RuntimeException) {false}
    if(state.providerEpoch==9007199254740991L)return null
    state.providerEpoch++
    return TrackRecord(slot,actual,initialized,state.providerEpoch).also {tracks[actual]=it;state.latest=it}
  }
  /** Exact token and actual object, including retained old tracks needed by
   * an in-flight discard. A newer provider record cannot steal that identity.
   */
  @Synchronized fun ownsTrack(slot:SinkSlot,record:TrackRecord,actual:AudioTrack):Boolean =
    sinks.containsKey(slot) && record.sink===slot && record.actual===actual && tracks[actual]===record

  @Synchronized fun capturedTrack(slot:SinkSlot):TrackRecord?=sinks[slot]?.latest
  @Synchronized fun isTargeted(slot:SinkSlot):Boolean=sinks[slot]?.targeted==true
  @Synchronized fun soleSink():SinkSlot?=sinks.keys.singleOrNull()
  fun postOutput(work:()->Unit):Boolean=playbackHandler?.post(Runnable(work))==true

  /** Only a positive INITIALIZED capture followed by actual UNINITIALIZED.
   * This is track release evidence alone, not discard/delegate/readers ACK.
   * Ownership stays retained until the separate settlement transaction.
   */
  @Synchronized fun knownReleased(record:TrackRecord):Boolean {
    if(!isOutputThread() || tracks[record.actual]!==record || !record.capturedInitialized)return false
    return try {record.actual.state==AudioTrack.STATE_UNINITIALIZED} catch(_:RuntimeException) {false}
  }

  @Synchronized private fun ownsSettlement(witness:SinkSettlement):Boolean {
    val state=sinks[witness.prior.slot]?:return false
    val attempt=state.settlement?:return false
    return !attempt.failed && attempt.witness===witness && attempt.prior===witness.prior
      && state.enrollment===witness.prior && state.delegate===witness.delegate
      && state.providerRevision==witness.providerRevision && state.pending==null
  }
  @Synchronized private fun ownsIdleSettlement(witness:IdleSettlement):Boolean {
    val state=sinks[witness.slot]?:return false;val attempt=state.idleSettlement?:return false
    val owner=state.sourceOwner?:return false
    return !attempt.failed && attempt.witness===witness && attempt.closure===witness.closure
      && witness.closure.matches(owner) && state.providerRevision==witness.providerRevision
      && state.observation===witness.observation && state.enrollment==null && !state.targeted && state.pending==null
  }
  private fun idleOwnershipSettled(slot:SinkSlot,state:SinkState,attempt:IdleSettlementAttempt):Boolean {
    val owned=synchronized(this) {tracks.values.filter {it.sink===slot}}
    if(owned.isNotEmpty())return owned.all {knownReleased(it)}
    return attempt.pristine?.let {state.baseline.acceptsConstruction(it)}==true
  }
  /** Initial ordinary idle may contain silent AAC and have written a real
   * track. Its exact SourceOwner must already have retired the source and joined
   * every reader. Clear once on the output thread, then positively observe all
   * owned track releases, or retain the original pristine construction proof.
   * No continuous grant is fabricated for the old idle source.
   */
  fun settleInitialSource(slot:SinkSlot,closure:NCMuxedTrialSourceOwner.Retirement):IdleSettlement? {
    if(!isOutputThread())return null
    val state=synchronized(this) {sinks[slot]}?:return null
    if(state.permanentlyClosed)return null
    val owner=state.sourceOwner?:return null;val delegate=state.delegate?:return null
    if(!closure.matches(owner) || state.targeted || state.enrollment!=null || state.pending!=null)return null
    var attempt=state.idleSettlement
    if(attempt==null) {
      attempt=IdleSettlementAttempt(closure,delegate,state.providerRevision,state.baseline.constructionProof())
      state.idleSettlement=attempt
      try {delegate.flush()} catch(_:RuntimeException) {attempt.failed=true}
    }
    if(attempt.failed || attempt.closure!==closure || attempt.delegate!==delegate
      || attempt.providerRevision!=state.providerRevision || state.pending!=null || !closure.matches(owner)
      || !idleOwnershipSettled(slot,state,attempt))return null
    return attempt.witness?:IdleSettlement.create(this,slot,closure,state.observation?:return null,
      state.observation?.model,state.providerRevision,state.providerEpoch).also {attempt.witness=it}
  }
  fun enrollIdleSettled(settled:IdleSettlement,lease:NCContinuousMuxedAuthority.OutputLease,
    model:NCContinuousMuxedPresentation,observation:NCContinuousMuxedObservation):Enrollment? {
    if(!isOutputThread() || !lease.matchesPresentation(model) || model===settled.priorModel
      || observation!==settled.observation || settled.isConsumed || !ownsIdleSettlement(settled))return null
    val state=synchronized(this) {sinks[settled.slot]}?:return null
    if(state.permanentlyClosed)return null
    val attempt=state.idleSettlement?:return null
    if(!idleOwnershipSettled(settled.slot,state,attempt) || !lease.activeAt(SystemClock.elapsedRealtime())
      || !settled.consume(this))return null
    val baseline=NCContinuousMuxedSinkBaseline(::isOutputThread)
    if(!baseline.enroll(lease) || !observation.attachIdleSettledLiveModel(model,settled)) {lease.revoke();return null}
    val next=Enrollment(settled.slot,lease,model,observation)
    next.gate=NCContinuousMuxedOutputGate(lease,::isOutputThread,
      {playbackHandler?.post(Runnable(it))==true},
      {actual->next.record?.let {ownsTrack(settled.slot,it,actual)}==true},
      {state.delegate!!.flush()},baseline)
    state.baseline=baseline;state.targeted=true;state.enrollment=next;state.idleSettlement=null
    if(!next.gate.armExpiry({SystemClock.elapsedRealtime()},{delay,work->
      playbackHandler?.postDelayed(Runnable(work),delay)==true})) {invalidate(next,"expiry_work");return null}
    return next
  }
  private fun ownershipSettled(slot:SinkSlot,attempt:SettlementAttempt):Boolean {
    val owned=synchronized(this) {tracks.values.filter {it.sink===slot}}
    if(owned.isNotEmpty())return owned.all {knownReleased(it)}
    // An empty registry is not proof. The actor must retain its exact positive
    // construction/never-submitted witness through successful raw clearing.
    val ack=attempt.discard?:return false
    return attempt.prior.gate.provesNeverSubmitted(ack,attempt.prior.lease)
  }

  /** Native playback-thread settlement only, after the off-main reader join.
   * A raw flush returns before asynchronous AudioTrack release completes.
   * Retain the exact ownership and retry observation without clearing again;
   * only positive release of every originally initialized track can mint this
   * one-use witness. No Queue/Authority/Guard monitor is entered here.
   */
  fun settleUsedSink(enrolled:Enrollment,closure:NCContinuousMuxedQueue.RetirementWitness):SinkSettlement? {
    if(!isOutputThread())return null
    val queue=enrolled.queue?:return null
    if(!closure.matches(queue,enrolled.lease.run))return null
    val state=synchronized(this) {
      val candidate=sinks[enrolled.slot]?:return null
      if(candidate.enrollment!==enrolled || candidate.pending!=null)return null
      candidate
    }
    val delegate=state.delegate?:return null
    var attempt=state.settlement
    if(attempt==null) {
      val ack=enrolled.gate.discardAcknowledgement()
      val discarded=ack!=null && enrolled.gate.ownsDiscardAcknowledgement(ack,enrolled.lease)
      val natural=enrolled.lease.isNaturallyRetired && enrolled.gate.finishNaturally()
      if(!discarded && !natural)return null
      attempt=SettlementAttempt(enrolled,closure,delegate,state.providerRevision,ack.takeIf {discarded})
      state.settlement=attempt // Block output/provider before any raw clearing.
      if(!discarded)try {delegate.flush()} catch(_:RuntimeException) {attempt.failed=true}
    }
    if(attempt.failed || attempt.prior!==enrolled || attempt.closure!==closure || attempt.delegate!==delegate
      || attempt.providerRevision!=state.providerRevision || state.pending!=null)return null
    if(!ownershipSettled(enrolled.slot,attempt))return null
    return attempt.witness?:SinkSettlement.create(this,enrolled,delegate,state.providerRevision,state.providerEpoch)
      .also {attempt.witness=it}
  }
  internal fun settleQueue(slot:SinkSlot,queue:NCContinuousMuxedQueue,
    closure:NCContinuousMuxedQueue.RetirementWitness):SinkSettlement? {
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return null
    if(enrolled.queue!==queue)return null
    return settleUsedSink(enrolled,closure)
  }
  fun returnToOrdinaryIdle(settled:SinkSettlement):Boolean {
    if(!isOutputThread() || !settled.belongsTo(this) || settled.isConsumed || !ownsSettlement(settled))return false
    val state=synchronized(this) {sinks[settled.prior.slot]}?:return false
    if(state.permanentlyClosed)return false
    val attempt=state.settlement?:return false
    if(!ownershipSettled(settled.prior.slot,attempt) || !settled.consume(this)
      || !settled.prior.observation.returnToOrdinaryIdle(settled))return false
    state.baseline=NCContinuousMuxedSinkBaseline(::isOutputThread)
    state.enrollment=null;state.targeted=false;state.settlement=null
    return true
  }
  /** Same persistent delegate and observer, only after the exact positively
   * settled ownership transaction. The old records/model stay historical.
   * A new baseline belongs solely to this consumed native settlement; source
   * counters, flush returns and absence can never recreate it.
   */
  fun enrollSettled(settled:SinkSettlement,lease:NCContinuousMuxedAuthority.OutputLease,
    model:NCContinuousMuxedPresentation,observation:NCContinuousMuxedObservation):Enrollment? {
    if(!isOutputThread() || !settled.belongsTo(this) || !lease.matchesPresentation(model)
      || model===settled.prior.model || observation!==settled.prior.observation)return null
    val slot=settled.prior.slot
    val state=synchronized(this) {
      val candidate=sinks[slot]?:return null;val attempt=candidate.settlement?:return null
      if(candidate.permanentlyClosed)return null
      if(attempt.failed || attempt.witness!==settled || candidate.enrollment!==settled.prior
        || candidate.delegate!==settled.delegate || candidate.providerRevision!=settled.providerRevision
        || candidate.pending!=null || settled.isConsumed)return null
      candidate
    }
    if(!ownershipSettled(slot,state.settlement!!) || !lease.activeAt(SystemClock.elapsedRealtime())
      || !settled.consume(this))return null
    val baseline=NCContinuousMuxedSinkBaseline(::isOutputThread)
    if(!baseline.enroll(lease) || !observation.attachSettledLiveModel(model,settled)) {lease.revoke();return null}
    val next=Enrollment(slot,lease,model,observation)
    next.gate=NCContinuousMuxedOutputGate(lease,::isOutputThread,
      {playbackHandler?.post(Runnable(it))==true},
      {actual->next.record?.let {ownsTrack(slot,it,actual)}==true},
      {state.delegate!!.flush()},baseline)
    state.baseline=baseline;state.enrollment=next;state.settlement=null
    if(!next.gate.armExpiry({SystemClock.elapsedRealtime()},{delay,work->
      playbackHandler?.postDelayed(Runnable(work),delay)==true})) {invalidate(next,"expiry_work");return null}
    return next
  }

  /** First untouched sink only. Used-sink settlement remains a distinct positive
   * native transaction; a source generation or absent track cannot reset this.
   * Do not call Authority/Guard or the model while holding the registry lock.
   */
  fun enrollFresh(slot:SinkSlot,lease:NCContinuousMuxedAuthority.OutputLease,
    model:NCContinuousMuxedPresentation,observation:NCContinuousMuxedObservation):Enrollment? {
    if(!isOutputThread() || playbackHandler==null || !lease.matchesPresentation(model))return null
    val state=synchronized(this) {
      val candidate=sinks[slot]?:return null
      if(candidate.delegate==null || candidate.observation!==observation || candidate.targeted)return null
      candidate.targeted=true;candidate
    }
    if(state.latest!=null || !state.baseline.enroll(lease) || !observation.attachLiveModel(model,slot)) {
      lease.revoke();return null
    }
    val next=Enrollment(slot,lease,model,observation)
    next.gate=NCContinuousMuxedOutputGate(lease,::isOutputThread,
      {playbackHandler?.post(Runnable(it))==true},
      {actual->next.record?.let {ownsTrack(slot,it,actual)}==true},
      {state.delegate!!.flush()},state.baseline)
    state.enrollment=next
    if(!next.gate.armExpiry({SystemClock.elapsedRealtime()},{delay,work->
      playbackHandler?.postDelayed(Runnable(work),delay)==true})) {invalidate(next,"expiry_work");return null}
    return next
  }
  /** Permanent failed-before-enrollment shutdown only. Joined readers permit
   * closing files, never certify an output settlement or a reusable sink. */
  internal fun closeUnenrolled(slot:SinkSlot,queue:NCContinuousMuxedQueue,
    readers:NCContinuousMuxedQueue.DetachedReaders):Boolean {
    if(!isOutputThread() || !readers.matches(queue))return false
    val state=synchronized(this) {sinks[slot]}?:return false
    if(state.targeted || state.enrollment!=null || state.pending!=null)return false
    state.permanentlyClosed=true;state.targeted=true // No token is consumed or fresh baseline created.
    state.observation?.fence("unprepared_close")
    return try {state.delegate?.flush() ?: return false;true} catch(_:RuntimeException){false}
  }
  /** The actual provider must call this BEFORE returning its track. Capture
   * discard identity first even if revoke raced the initialization attempt.
   */
  fun providerReady(slot:SinkSlot,record:TrackRecord):Boolean {
    val state=synchronized(this) {sinks[slot]}?:return false
    if(state.settlement!=null || state.idleSettlement!=null)return false
    val enrolled=state.enrollment?:return !state.targeted
    if(!isOutputThread() || !ownsTrack(slot,record,record.actual)) {invalidate(enrolled,"provider_owner");return false}
    if(enrolled.record?.let {it!==record}==true) {invalidate(enrolled,"provider_replacement");return false}
    enrolled.record=record
    if(!enrolled.gate.bindTrack(record.actual,record.providerEpoch)) {invalidate(enrolled,"provider_permission");return false}
    val capture=enrolled.observation.observe(record.actual,record.providerEpoch)
    if(capture==null || capture.sinkEpoch!=record.providerEpoch || !enrolled.gate.bindTrack(capture)) {
      invalidate(enrolled,"provider_origin");return false
    }
    enrolled.capture=capture;return true
  }
  fun beforeBuffer(slot:SinkSlot,output:NCContinuousMuxedObservation.LiveOutput?):Admission {
    val state=synchronized(this) {sinks[slot]}
    fun denied()=Admission(slot,null,null,false,false)
    if(state==null || !isOutputThread() || state.settlement!=null || state.idleSettlement!=null)return denied()
    val enrolled=state.enrollment
    if(enrolled==null && state.targeted)return denied()
    val key=if(enrolled!=null) {
      if(output==null || output.model!==enrolled.model || enrolled.lease.hasTerminalSelection) {
        invalidate(enrolled,"output_context");return denied()
      }
      val now=SystemClock.elapsedRealtime()
      if(!enrolled.lease.activeAt(now)) {invalidate(enrolled,"output_authority");return denied()}
      // Read-ahead may precede the actual timeline ACK. Wait without submitting
      // or guessing that scheduling published output permission.
      if(!enrolled.lease.hasOutputKey(output.key))return denied()
      val allowed=if(output.epoch==0L)enrolled.gate.beforeInitialization(output.key,now)
        else enrolled.gate.beforeWrite(output.key,output.epoch,now)
      if(!allowed) {invalidate(enrolled,"output_admission");return denied()}
      output.key
    } else null
    if(!state.baseline.beginDelegatedWrite()) {
      enrolled?.let {invalidate(it,"delegated_entry")};return denied()
    }
    val admission=Admission(slot,enrolled,key,true,true)
    synchronized(this) {state.pending=admission}
    return admission
  }
  fun afterBuffer(slot:SinkSlot,admission:Admission,returnedNormally:Boolean):Boolean {
    val state=synchronized(this) {
      val current=sinks[slot]?:return false
      if(current.pending!==admission || admission.slot!==slot)return false
      current.pending=null;current
    }
    state.baseline.endDelegatedWrite()
    val enrolled=admission.enrollment?:return returnedNormally && !state.targeted
    if(!returnedNormally)invalidate(enrolled,"delegate_error")
    val valid=enrolled.gate.afterWrite(admission.key!!,enrolled.capture?.sinkEpoch?:0L,SystemClock.elapsedRealtime())
    if(!valid)invalidate(enrolled,"output_checkpoint")
    return returnedNormally && valid
  }
  fun canPlay(slot:SinkSlot):Boolean {
    val state=synchronized(this) {sinks[slot]}?:return false
    if(!isOutputThread() || state.settlement!=null || state.idleSettlement!=null)return false
    val enrolled=state.enrollment?:return !state.targeted
    if(!enrolled.lease.activeAt(SystemClock.elapsedRealtime())) {invalidate(enrolled,"play_authority");return false}
    return true
  }
  fun renderCheckpoint(slot:SinkSlot):Boolean {
    val state=synchronized(this) {sinks[slot]}?:return false
    if(state.settlement!=null || state.idleSettlement!=null)return false
    val enrolled=state.enrollment?:return !state.targeted && isOutputThread()
    if(!enrolled.gate.renderCheckpoint(SystemClock.elapsedRealtime())) {
      if(!enrolled.lease.isNaturallyRetired)invalidate(enrolled,"renderer_authority")
      return false
    }
    return true
  }
  internal fun beforeVideo(slot:SinkSlot,model:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey):Boolean {
    val state=synchronized(this) {sinks[slot]}?:return false
    if(!isOutputThread() ||state.settlement!=null ||state.idleSettlement!=null)return false
    val enrolled=state.enrollment?:return !state.targeted
    if(enrolled.model!==model ||!enrolled.gate.renderCheckpoint(SystemClock.elapsedRealtime())) {
      invalidate(enrolled,"video_authority");return false
    }
    return state.enrollment===enrolled &&enrolled.lease.permitsVideo(key,SystemClock.elapsedRealtime())
  }
  internal fun submitVideo(slot:SinkSlot,model:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey,
    delegate:()->Unit):Boolean {
    if(!beforeVideo(slot,model,key))return false
    val state=synchronized(this) {sinks[slot]}?:return false
    val enrolled=state.enrollment?:return !state.targeted &&run {delegate();true}
    if(!enrolled.lease.beginVideoSubmission(key,SystemClock.elapsedRealtime()))return false
    var returned=false
    try {delegate();returned=true} finally {
      val permitted=state.enrollment===enrolled &&enrolled.lease.permitsVideo(key,SystemClock.elapsedRealtime())
      val ended=enrolled.lease.endSubmission()
      if(!returned ||!permitted ||!ended)invalidate(enrolled,"video_submission")
    }
    return returned &&!enrolled.lease.isRevoked
  }
  /** Control/worker entry only. The exact real Queue supplies proof and actual
   * mutation acknowledgement; no callback or JS data can mint an attestation.
   */
  fun connectQueue(enrolled:Enrollment,queue:NCContinuousMuxedQueue,postWork:(()->Unit)->Boolean):Boolean {
    if(isOutputThread() || queue.authority.nativeOutputLease(enrolled.lease.run)!==enrolled.lease)return false
    return synchronized(this) {
      val state=sinks[enrolled.slot]?:return false
      if(state.enrollment!==enrolled || enrolled.queue!=null)return false
      enrolled.queue=queue;enrolled.postProofWork=postWork;true
    }
  }
  fun requestPresentation(slot:SinkSlot) {
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return
    if(enrolled.queue!=null && !enrolled.lease.hasTerminalSelection)requestProof(enrolled,null)
  }
  private fun requestProof(enrolled:Enrollment,witness:NCContinuousMuxedOutputGate.TrackWitness?):Boolean {
    val queue=enrolled.queue?:return false
    val post=enrolled.postProofWork?:return false
    if(!enrolled.proofBusy.compareAndSet(false,true))return true
    val scheduled=try {post {
      try {
        // Never take Queue/Authority/Guard monitors on the output thread.
        if(isOutputThread()) {invalidate(enrolled,"proof_worker_thread");return@post}
        if(synchronized(this) {sinks[enrolled.slot]?.enrollment!==enrolled})return@post
        logTerminalReadiness(enrolled)
        if(!queue.reconcileNativePresentation(enrolled.lease.run)) {invalidate(enrolled,"native_proof");return@post}
        if(witness!=null && enrolled.terminal==null && !enrolled.lease.isRevoked) {
          val snapshot=queue.snapshot();val tail=snapshot.tail
          if(tail!=null)enrolled.terminal=queue.attestTerminal(enrolled.lease.run,tail,snapshot.mutationRevision,witness)
        }
      } catch(_:RuntimeException) {invalidate(enrolled,"proof_worker_error")}
      finally {enrolled.proofBusy.set(false)}
    }} catch(_:RuntimeException) {false}
    if(!scheduled){enrolled.proofBusy.set(false);invalidate(enrolled,"proof_worker_post")}
    return scheduled
  }
  /** Called only by the actual sink's natural EOS path. No proof yet means a
   * nonblocking hold; the original fixed deadline still fences queued output.
   */
  fun terminalEos(slot:SinkSlot,
    retainedDrain:((NCContinuousMuxedPresentation,NCContinuousMuxedClipKey,()->Boolean)->Boolean?)?=null,
    delegate:()->Unit) {
    val state=synchronized(this) {sinks[slot]}?:return
    val enrolled=state.enrollment?:run {if(!state.targeted)delegate();return}
    if(!isOutputThread() || enrolled.queue==null) {invalidate(enrolled,"terminal_worker");return}
    enrolled.observation.sampleTrack()
    val attestation=enrolled.terminal
    if(attestation!=null) {
      if(!enrolled.gate.delegateTerminalEos(attestation,delegate))invalidate(enrolled,"terminal_eos")
      return
    }
    if(!enrolled.gate.renderCheckpoint(SystemClock.elapsedRealtime()))return
    // Worker publication may be between selectTerminal and storing its token.
    // Hold that interval without reopening PCM or treating it as failure.
    if(enrolled.lease.hasTerminalSelection)return
    // A seal applies to one exact acknowledged clip, not every earlier EOS.
    // Hold non-tail/incomplete input without denying the successor's PCM. Raw
    // input acceptance only makes the final wait eligible; endpoint proof and
    // actual receipts are still required by the worker before delegation.
    if(enrolled.queue?.sealedOutputTail?.let {it==enrolled.observation.terminalInputKey()}!=true) {
      if(!requestProof(enrolled,null))invalidate(enrolled,"terminal_worker")
      return
    }
    val witness=enrolled.gate.terminalTrackWitness(SystemClock.elapsedRealtime())
      ?:run {invalidate(enrolled,"terminal_track");return}
    // Retain diagnostic timing before an already-posted worker coalesces this
    // witness. Never post more work, poll a track, or renew the real deadline.
    if(enrolled.terminalDiagnosticWindow==null)
      enrolled.terminalDiagnosticWindow=witness.firstAttemptElapsedMs to witness.expiresElapsedMs
    var submitted=true
    if(retainedDrain!=null) {
      val key=enrolled.observation.terminalInputKey()?:run {invalidate(enrolled,"terminal_input");return}
      val capture=enrolled.capture?:run {invalidate(enrolled,"terminal_track");return}
      val record=enrolled.record?:run {invalidate(enrolled,"terminal_track");return}
      fun current()=synchronized(this) {sinks[slot]===state && state.enrollment===enrolled && state.pending==null
        && state.latest===record && enrolled.record===record && enrolled.capture===capture}
        && enrolled.queue?.sealedOutputTail==key && enrolled.observation.model===enrolled.model
        && enrolled.observation.terminalInputKey()==key && enrolled.model.matchesNativeTrack(capture)
        && enrolled.gate.retainedCheckpoint(key,capture.sinkEpoch,witness,SystemClock.elapsedRealtime())
      if(!current() || !enrolled.gate.beforeRetainedWrite(key,capture.sinkEpoch,witness,SystemClock.elapsedRealtime())) {
        invalidate(enrolled,"retained_admission");return
      }
      if(!state.baseline.beginDelegatedWrite()) {
        enrolled.lease.endSubmission();invalidate(enrolled,"retained_entry");return
      }
      val admission=Admission(slot,enrolled,key,true,true)
      synchronized(this) {state.pending=admission}
      fun checkpoint()=synchronized(this) {sinks[slot]===state && state.enrollment===enrolled && state.pending===admission
        && state.latest===record && enrolled.record===record && enrolled.capture===capture}
        && enrolled.queue?.sealedOutputTail==key && enrolled.observation.model===enrolled.model
        && enrolled.observation.terminalInputKey()==key && enrolled.model.matchesNativeTrack(capture)
        && enrolled.gate.retainedCheckpoint(key,capture.sinkEpoch,witness,SystemClock.elapsedRealtime())
      var result:Boolean?=null
      var settled=false
      try {if(checkpoint())result=retainedDrain(enrolled.model,key,::checkpoint)}
      catch(_:Exception) {invalidate(enrolled,"retained_delegate")} // Media3 configure/write failures are checked exceptions.
      finally {
        val valid=checkpoint()
        synchronized(this) {if(state.pending===admission)state.pending=null}
        state.baseline.endDelegatedWrite()
        settled=enrolled.gate.afterRetainedWrite(key,capture.sinkEpoch,witness,SystemClock.elapsedRealtime()) && valid
      }
      if(result==null || !settled) {invalidate(enrolled,"retained_checkpoint");return}
      submitted=result==true
      enrolled.observation.sampleTrack()
    }
    if(!requestProof(enrolled,if(submitted)witness else null))invalidate(enrolled,"terminal_worker")
  }
  /** At most two numeric rows on the existing proof worker. Logging is not
   * terminal selection; a missing late row means no qualifying worker ran.
   */
  private fun logTerminalReadiness(enrolled:Enrollment) {
    val window=enrolled.terminalDiagnosticWindow?:return
    val now=SystemClock.elapsedRealtime()
    val phase=if(enrolled.terminalDiagnosticPhase<0)0 else if(now-window.first>=1500)1 else return
    if(phase<=enrolled.terminalDiagnosticPhase)return
    enrolled.terminalDiagnosticPhase=phase
    try {
      val row=enrolled.model.terminalReadiness()
      val fields=linkedMapOf<String,Long>("phase" to phase.toLong(),"elapsedMs" to now,
        "firstMs" to window.first,"deadlineMs" to window.second,"known" to if(row.known)1L else 0L,
        "declaredSamples" to row.declaredSamples,"acceptedSamples" to row.acceptedSamples,
        "presentedSamples" to row.presentedSamples,"headFrames" to (row.headFrames?:-1),
        "timestampFrames" to (row.timestampFrames?:-1),"totalRanges" to row.totalRanges.toLong(),
        "registeredRanges" to row.registeredRanges.toLong(),"formatKnownRanges" to row.formatKnownRanges.toLong(),
        "rawConsumedRanges" to row.rawConsumedRanges.toLong(),"acceptedRanges" to row.acceptedRanges.toLong(),
        "readEndRanges" to row.readEndRanges.toLong(),"processedEndRanges" to row.processedEndRanges.toLong(),
        "lastOrdinal" to (row.lastOrdinal?:-1),"lastRawSamples" to (row.lastRawSamples?.toLong()?:-1),
        "lastValidSamples" to (row.lastValidSamples?:-1),"lastDelaySamples" to (row.lastDelaySamples?.toLong()?:-1),
        "lastPaddingSamples" to (row.lastPaddingSamples?.toLong()?:-1),"lastRawConsumed" to (row.lastRawConsumed?:-1),
        "lastAcceptedSamples" to (row.lastAcceptedSamples?:-1),"lastQueuedPtsUs" to (row.lastQueuedPtsUs?:-1),
        "lastProcessedPtsUs" to (row.lastProcessedPtsUs?:-1))
      Log.d("NCContinuousTerminal",fields.entries.joinToString(" ") {"${it.key}=${it.value}"})
    } catch(_:RuntimeException) {} // Diagnostic failure cannot invalidate playback.
  }
  /** Framework onStopped may pause after its exact witnessed EOS stop but
   * before application STATE_ENDED. Only that scoped path preserves the token.
   */
  fun beginNormalRendererStop(slot:SinkSlot,ended:Boolean):Boolean {
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return false
    if(!isOutputThread() || !ended || enrolled.terminal?.validEnded()!=true)return false
    enrolled.normalStopScope=true;return true
  }
  /** Exact synchronous native stop scope. The source proves held audio EOF,
   * not Internal's stop cause. Closed-build control and cleanup fences are
   * independently required; this grants no PCM, receipts or terminal proof. */
  fun beginBufferingRendererStop(slot:SinkSlot,witness:NCContinuousMuxedTailSource.HeldEof,
    ended:Boolean,streamFinal:Boolean):Boolean {
    if(ended || streamFinal || !isOutputThread())return false
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return false
    if(enrolled.normalStopScope || enrolled.bufferingStopWitness!=null
      || !bufferingContext(enrolled,witness))return false
    enrolled.bufferingStopWitness=witness;return true
  }
  private fun bufferingContext(enrolled:Enrollment,witness:NCContinuousMuxedTailSource.HeldEof):Boolean {
    return physicalPauseContext(enrolled) &&witness.matches(enrolled.model)
  }
  private fun physicalPauseContext(enrolled:Enrollment):Boolean {
    if(!isOutputThread())return false
    val state=synchronized(this) {
      val current=sinks[enrolled.slot]?:return false
      if(current.enrollment!==enrolled || !current.targeted || current.permanentlyClosed
        || current.pending!=null || current.settlement!=null || current.idleSettlement!=null)return false
      current
    }
    val capture=enrolled.capture?:return false;val record=enrolled.record?:return false
    return try {
      enrolled.queue!=null && enrolled.terminal==null && enrolled.observation.model===enrolled.model
        && state.latest===record && record.capturedInitialized && record.providerEpoch==capture.sinkEpoch
        && ownsTrack(enrolled.slot,record,record.actual)
        && capture.matchesContext(enrolled.observation,enrolled.slot,record.actual,record.providerEpoch)
        && enrolled.model.matchesNativeTrack(capture)
        && enrolled.model.protectedCursors().let {it.known && it.sinkEpoch==capture.sinkEpoch}
        && enrolled.gate.canPauseForBuffering(capture,SystemClock.elapsedRealtime())
    } catch(_:RuntimeException) {false}
  }
  fun endNormalRendererStop(slot:SinkSlot) {
    synchronized(this) {sinks[slot]?.enrollment}?.let {
      it.normalStopScope=false;it.bufferingStopWitness=null
    }
  }
  fun permitsNormalPause(slot:SinkSlot):Boolean {
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return false
    return isOutputThread() && (enrolled.normalStopScope && enrolled.terminal?.validEnded()==true
      || enrolled.bufferingStopWitness?.let {bufferingContext(enrolled,it)}==true
      || lockPauseScope?.let {
        if(lockPauseConsumed ||!enrolled.lease.acceptsLockPause(it)||!physicalPauseContext(enrolled))false
        else {lockPauseConsumed=true;true}
      }==true)
  }
  fun recordNativeEnd(slot:SinkSlot):Boolean {
    if(isOutputThread())return false
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return false
    val queue=enrolled.queue?:return false
    val terminal=enrolled.terminal?:return false
    if(!terminal.validEnded() || !queue.recordNativeTimelineEnd(terminal.mutationRevision))return false
    return enrolled.gate.finishNaturally()
  }
  private fun invalidate(enrolled:Enrollment,cause:String) {
    enrolled.observation.fenceModel(enrolled.model,cause);enrolled.gate.revoke()
  }
  fun invalidate(slot:SinkSlot,cause:String) {
    val enrolled=synchronized(this) {sinks[slot]?.enrollment}?:return
    invalidate(enrolled,cause)
  }
}
