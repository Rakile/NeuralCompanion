package expo.modules.audio

import android.media.AudioTrack
import android.util.Log
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import java.nio.ByteBuffer
import androidx.media3.common.C
import androidx.media3.common.Format

/** Content validation only, never output permission or presentation proof.
 * The sink must separately bind this slice to its exact processed token, trim,
 * configuration and visual grant before delegating. Empty/private-drain input
 * cannot certify PCM already retained by the delegate.
 */
internal object NCContinuousMuxedVisualPcm {
  fun isZero(buffer:ByteBuffer,format:Format,rawSamples:Int):Boolean {
    if(format.sampleMimeType!="audio/raw" ||format.sampleRate!=48000 ||format.channelCount!=1
      ||format.pcmEncoding!=C.ENCODING_PCM_16BIT ||rawSamples !in 1..28672 ||rawSamples%1024!=0)return false
    val start=buffer.position();val end=buffer.limit();val size=end-start
    if(start%2!=0 ||size<=0 ||size%2!=0 ||size>rawSamples*2)return false
    var index=start
    while(index<end) {
      if(buffer.get(index).toInt()!=0)return false
      index++
    }
    return true
  }
}

/** Construct exactly once alongside the normal sink, BEFORE it escapes.
 * This is a positive pristine-construction witness, not a source-generation
 * counter. Every delegated attempt (including failed/partial/empty input) and
 * provider entry destroys it. No source replacement/reset can recreate it.
 * Reused-sink settlement requires the concrete ownership controller, not this
 * deliberately narrower never-submitted path.
 */
internal class NCContinuousMuxedSinkBaseline(private val isOutputThread:()->Boolean) {
  class ConstructionProof private constructor() {
    companion object {internal fun create()=ConstructionProof()}
  }
  private val construction=ConstructionProof.create()
  class NeverSubmittedProof private constructor() {
    companion object {internal fun create()=NeverSubmittedProof()}
  }
  private val valid=java.util.concurrent.atomic.AtomicBoolean(true)
  private var enrollment:NCContinuousMuxedAuthority.OutputLease?=null
  private var proof:NeverSubmittedProof?=null
  private var attempted=false
  private var inFlight=false
  private var providerEntered=false
  private fun onThread():Boolean {
    if(isOutputThread())return valid.get()
    valid.set(false);return false
  }
  fun enroll(lease:NCContinuousMuxedAuthority.OutputLease):Boolean {
    if(!onThread() || enrollment!=null || attempted || inFlight || providerEntered)return false
    enrollment=lease;proof=NeverSubmittedProof.create();return true
  }
  fun beginDelegatedWrite():Boolean {
    if(!onThread())return false
    attempted=true
    if(inFlight){valid.set(false);return false}
    inFlight=true;return true
  }
  fun endDelegatedWrite() {
    if(!onThread())return
    if(!inFlight){valid.set(false);return}
    inFlight=false
  }
  fun providerEntered() {if(onThread())providerEntered=true}
  internal fun constructionProof():ConstructionProof? = construction.takeIf {
    onThread() && enrollment==null && !attempted && !inFlight && !providerEntered
  }
  internal fun acceptsConstruction(candidate:ConstructionProof)=constructionProof()===candidate
  fun neverSubmittedProof(lease:NCContinuousMuxedAuthority.OutputLease):NeverSubmittedProof? {
    if(!onThread() || enrollment!==lease || attempted || inFlight || providerEntered)return null
    return proof
  }
  internal fun accepts(candidate:NeverSubmittedProof,lease:NCContinuousMuxedAuthority.OutputLease):Boolean =
    neverSubmittedProof(lease)===candidate
}

/** Native-only termination actor for the exact normal sink enrollment.
 * Dormant until installed in the actual provider/sink/playback-thread hooks.
 * It grants no receipt and owns no new track/player/focus. The real module must
 * retain ownership until this discard ACK AND delegated reader joins succeed.
 */
internal class NCContinuousMuxedOutputGate(
  private val lease:NCContinuousMuxedAuthority.OutputLease,
  private val isOutputThread:()->Boolean,
  private val postOutputWork:(()->Unit)->Boolean,
  private val ownsTrack:(AudioTrack)->Boolean,
  private val clearDelegate:()->Unit,
  private val sinkBaseline:NCContinuousMuxedSinkBaseline?=null
) {
  private enum class State { LIVE,TERMINAL,REVOKED_PENDING,FLUSHING,DISCARDED,NATURAL,FAILED }
  class TrackWitness private constructor(private val origin:NCContinuousMuxedOutputGate,
    private val actual:AudioTrack,val sinkEpoch:Long,private val nonce:String,
    private val capture:NCContinuousMuxedPresentation.NativeTrackCapture,
    internal val firstAttemptElapsedMs:Long,internal val expiresElapsedMs:Long) {
    private fun owned(lease:NCContinuousMuxedAuthority.OutputLease)=origin.lease===lease && lease.ownsOutputActor(origin)
      && !lease.isRevoked && origin.track===actual && origin.trackEpoch==sinkEpoch
      && origin.trackNonce==nonce && origin.trackCapture===capture && lease.acceptsCapture(capture)
      && capture.actual===actual && capture.sinkEpoch==sinkEpoch
      && origin.ownsTrack(actual) && actual.state==AudioTrack.STATE_INITIALIZED
    internal fun matchesLive(lease:NCContinuousMuxedAuthority.OutputLease,epoch:Long)=
      epoch==sinkEpoch && origin.state.get()==State.LIVE && owned(lease) && actual.playState==AudioTrack.PLAYSTATE_PLAYING
    internal fun matchesPending(owner:NCContinuousMuxedOutputGate?,lease:NCContinuousMuxedAuthority.OutputLease)=
      (owner==null || owner===origin) && origin.state.get() in listOf(State.LIVE,State.TERMINAL)
        && owned(lease) && actual.playState==AudioTrack.PLAYSTATE_PLAYING
    internal fun matchesStopped(lease:NCContinuousMuxedAuthority.OutputLease)=
      origin.state.get()==State.TERMINAL && owned(lease) && actual.playState==AudioTrack.PLAYSTATE_STOPPED
    internal fun belongsTo(owner:NCContinuousMuxedOutputGate,lease:NCContinuousMuxedAuthority.OutputLease)=
      origin===owner && origin.lease===lease
    internal fun matchesDelegating(lease:NCContinuousMuxedAuthority.OutputLease)=
      origin.state.get()==State.TERMINAL && owned(lease)
        && actual.playState in listOf(AudioTrack.PLAYSTATE_PLAYING,AudioTrack.PLAYSTATE_STOPPED)
    internal fun rawHeadIsReset()=(actual.playbackHeadPosition.toLong() and 0xffffffffL)==0L
    companion object {
      internal fun create(owner:NCContinuousMuxedOutputGate,actual:AudioTrack,epoch:Long,nonce:String,
        capture:NCContinuousMuxedPresentation.NativeTrackCapture,first:Long,end:Long)=
        TrackWitness(owner,actual,epoch,nonce,capture,first,end)
    }
  }
  class NormalEosStopProof private constructor(private val witness:TrackWitness) {
    internal fun matches(expected:TrackWitness,lease:NCContinuousMuxedAuthority.OutputLease)=
      witness===expected && witness.matchesStopped(lease)
    companion object {internal fun create(witness:TrackWitness)=NormalEosStopProof(witness)}
  }
  class DiscardAck private constructor(private val origin:NCContinuousMuxedOutputGate,
    private val lease:NCContinuousMuxedAuthority.OutputLease,val id:String,
    internal val neverSubmitted:NCContinuousMuxedSinkBaseline.NeverSubmittedProof?) {
    val run get()=lease.run
    internal fun matches(owner:NCContinuousMuxedOutputGate,expected:NCContinuousMuxedAuthority.OutputLease)=
      origin===owner && lease===expected
    companion object {internal fun create(owner:NCContinuousMuxedOutputGate,lease:NCContinuousMuxedAuthority.OutputLease,
      pristine:NCContinuousMuxedSinkBaseline.NeverSubmittedProof?=null)=
      DiscardAck(owner,lease,UUID.randomUUID().toString(),pristine)}
  }
  private val state=AtomicReference(State.LIVE)
  private val acknowledged=AtomicReference<DiscardAck?>(null)
  private val expiryArmed=java.util.concurrent.atomic.AtomicBoolean()
  @Volatile private var requestExpirySchedule:(()->Boolean)?=null
  @Volatile private var firstTerminalAttempt:Long?=null
  private fun terminalDeadline():Long = firstTerminalAttempt?.let {
    minOf(lease.expiresElapsedMs,if(it>Long.MAX_VALUE-2000)Long.MAX_VALUE else it+2000)
  }?:lease.expiresElapsedMs
  @Volatile private var track:AudioTrack?=null
  @Volatile private var trackEpoch:Long?=null
  @Volatile private var trackNonce:String?=null
  @Volatile private var trackCapture:NCContinuousMuxedPresentation.NativeTrackCapture?=null
  @Volatile private var failure:String?=null
  // Publish only after the actor's fields exist. A duplicate enrollment is
  // rejected locally; none of its callbacks may revoke the primary actor.
  private val enrolled=lease.enrollOutputActor(this)
  init {if(!enrolled){state.set(State.FAILED);failure="duplicate_actor"}}

  /** Provider callback on the playback thread only. A first track initialized
   * inside an in-flight write must still be captured after concurrent revoke,
   * before the posted discard executes on that same thread.
   */
  fun bindTrack(actual:AudioTrack,epoch:Long):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    sinkBaseline?.providerEntered()
    if(state.get() !in listOf(State.LIVE,State.REVOKED_PENDING))return false
    if(epoch !in 1..9007199254740991L || !ownsTrack(actual) || actual.state!=AudioTrack.STATE_INITIALIZED
      || track?.let {it!==actual || trackEpoch!=epoch}==true) {fail("track_owner");return false}
    if(track==null)trackNonce=UUID.randomUUID().toString()
    track=actual;trackEpoch=epoch
    return state.get()==State.LIVE && !lease.isRevoked
  }
  /** Live terminal proof requires the exact opaque provider capture shared
   * with the Presentation sampler; the numeric overload only captures discard.
   */
  fun bindTrack(capture:NCContinuousMuxedPresentation.NativeTrackCapture):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    val actual=capture.actual as? AudioTrack
    if(actual==null || !lease.acceptsCapture(capture) || trackCapture?.let {it!==capture}==true) {
      fail("track_capture");return false
    }
    val firstCapture=trackCapture==null
    val bound=bindTrack(actual,capture.sinkEpoch)
    trackCapture=capture
    if(!bound)return false
    // Provider is inside the first delegated handleBuffer. Retain the exact
    // capture for discard, but reject before it may return a writable track if
    // origin sampling was absent/fenced or the physical head already moved.
    val valid=try {
      (!firstCapture || actual.sampleRate==48000 && (actual.playbackHeadPosition.toLong() and 0xffffffffL)==0L
        && lease.acceptsInitialCapture(capture)) && lease.controlNow()?.let {lease.activeAt(it)}==true
    } catch(_:RuntimeException) {false}
    if(!valid){revoke();return false}
    return true
  }
  fun beforeWrite(key:NCContinuousMuxedClipKey,epoch:Long,elapsedNowMs:Long):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    if(lease.hasTerminalSelection || firstTerminalAttempt!=null){revoke();discardOnOutputThread();return false}
    if(state.get()!=State.LIVE)return false
    if(!lease.activeAt(elapsedNowMs)){revoke();discardOnOutputThread();return false}
    return ownsInitializedTrack(epoch) && lease.beginSubmission(key,epoch,elapsedNowMs)
  }
  /** This is permission to ENTER the first delegated handleBuffer, not a
   * synthetic track epoch or output receipt. The caller marks baseline entry
   * before delegation; the real provider must capture/bind its actual track
   * before returning, and afterWrite still rechecks in-flight cancellation.
   */
  fun beforeInitialization(key:NCContinuousMuxedClipKey,elapsedNowMs:Long):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    if(lease.hasTerminalSelection || firstTerminalAttempt!=null){revoke();discardOnOutputThread();return false}
    if(state.get()!=State.LIVE || track!=null)return false
    if(!lease.activeAt(elapsedNowMs)){revoke();discardOnOutputThread();return false}
    return sinkBaseline?.neverSubmittedProof(lease)!=null && lease.beginSubmission(key,null,elapsedNowMs)
  }
  private fun ownsInitializedTrack(epoch:Long):Boolean = track?.let {
    trackEpoch==epoch && ownsTrack(it) && it.state==AudioTrack.STATE_INITIALIZED
  }==true
  /** Read-only pause admission; never samples the head, renews expiry or
   * changes the output state. Resume still needs ordinary write admission. */
  internal fun canPauseForBuffering(capture:NCContinuousMuxedPresentation.NativeTrackCapture,
    elapsedNowMs:Long):Boolean = enrolled && isOutputThread() && state.get()==State.LIVE
      && firstTerminalAttempt==null && !lease.hasTerminalSelection && expiryArmed.get()
      && trackCapture===capture && capture.actual===track && capture.sinkEpoch==trackEpoch
      && lease.acceptsCapture(capture) && ownsInitializedTrack(capture.sinkEpoch)
      && lease.activeAt(elapsedNowMs)
  /** Renderer checkpoint before ordinary decode work. Terminal selection blocks
   * new PCM, but the normal renderer must still reach its guarded EOS bridge.
   * Do not call activeAt after that selection: its normal mapping may already
   * have been causally fenced by the witnessed delegate stop.
   */
  fun renderCheckpoint(elapsedNowMs:Long):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    if(lease.isNaturallyRetired){finishNaturally();return false}
    val prior=state.get()
    val withinTerminalWindow=firstTerminalAttempt==null || lease.controlNow()?.let {it<terminalDeadline()}==true
    val permitted=withinTerminalWindow && if(lease.hasTerminalSelection)
      prior in listOf(State.LIVE,State.TERMINAL) && lease.controlAt(elapsedNowMs)
        && lease.controlNow()?.let {it<terminalDeadline()}==true
      else prior==State.LIVE && lease.activeAt(elapsedNowMs)
    if(!permitted){revoke();discardOnOutputThread()}
    return permitted
  }
  fun terminalTrackWitness(elapsedNowMs:Long):TrackWitness? {
    if(!isOutputThread() || state.get()!=State.LIVE || lease.isRevoked)return null
    val reschedule=requestExpirySchedule?:return null
    if(!expiryArmed.get() || !lease.activeAt(elapsedNowMs))return null
    val now=lease.controlNow()?:return null
    val actual=track?:return null;val epoch=trackEpoch?:return null;val nonce=trackNonce?:return null
    val capture=trackCapture?:return null
    if(firstTerminalAttempt==null) {
      firstTerminalAttempt=now
      diagnostic(1)
      val scheduled=try {reschedule()} catch(_:RuntimeException) {false}
      if(!scheduled){revoke();return null}
    }
    if(now>=terminalDeadline()){revoke();return null}
    val witness=TrackWitness.create(this,actual,epoch,nonce,capture,firstTerminalAttempt!!,terminalDeadline())
    return witness.takeIf {it.matchesLive(lease,epoch)}
  }
  /** Only previously accepted PCM inside the already latched terminal window.
   * Ordinary beforeWrite remains closed. The shared lease CAS excludes terminal
   * selection throughout configure AND every empty-input delegate call. */
  internal fun retainedCheckpoint(key:NCContinuousMuxedClipKey,epoch:Long,witness:TrackWitness,
    elapsedNowMs:Long):Boolean = enrolled && isOutputThread() && state.get()==State.LIVE
      && firstTerminalAttempt==witness.firstAttemptElapsedMs && terminalDeadline()==witness.expiresElapsedMs
      && witness.belongsTo(this,lease) && witness.matchesLive(lease,epoch)
      && lease.controlNow()?.let {it<terminalDeadline()}==true && lease.permits(key,epoch,elapsedNowMs)
  internal fun beforeRetainedWrite(key:NCContinuousMuxedClipKey,epoch:Long,witness:TrackWitness,
    elapsedNowMs:Long):Boolean = retainedCheckpoint(key,epoch,witness,elapsedNowMs)
      && lease.beginSubmission(key,epoch,elapsedNowMs)
  internal fun afterRetainedWrite(key:NCContinuousMuxedClipKey,epoch:Long,witness:TrackWitness,
    elapsedNowMs:Long):Boolean {
    val permitted=retainedCheckpoint(key,epoch,witness,elapsedNowMs)
    val settled=lease.endSubmission()
    if(permitted && settled)return true
    revoke();discardOnOutputThread();return false
  }
  /** Exact normal sink EOS only, on the output thread; never Authority/Guard.
   * Input/presentation proof was already validated by the native worker. A
   * partial delegate drain may retry while the known endpoint is unchanged.
   */
  fun delegateTerminalEos(attestation:NCContinuousMuxedAuthority.TerminalAttestation,delegate:()->Unit):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    if(!attestation.witness.belongsTo(this,lease))return false
    if(attestation.hasWitnessedStop())return attestation.validEnded()
    if(!attestation.beforeDelegate(this))return false
    if(state.get()==State.LIVE && !state.compareAndSet(State.LIVE,State.TERMINAL))return false
    if(state.get()!=State.TERMINAL)return false
    attestation.beginDelegation()
    return try {
      delegate()
      if(attestation.witness.matchesStopped(lease)) {
        if(!attestation.publishStop(NormalEosStopProof.create(attestation.witness))) {
          revoke();discardOnOutputThread();false
        } else true
      } else attestation.validPending()
    }catch(_:RuntimeException){revoke();discardOnOutputThread();false}
    finally {attestation.endDelegation()}
  }
  /** A revoke can race the delegate's write. Check again before attribution or
   * another submission; discard here on the output thread, without awaiting
   * the already-posted work or any Authority/control monitor.
   */
  fun afterWrite(key:NCContinuousMuxedClipKey,epoch:Long,elapsedNowMs:Long):Boolean {
    if(!enrolled)return false
    if(!isOutputThread()){fail("wrong_thread");return false}
    val permitted=state.get()==State.LIVE && ownsInitializedTrack(epoch) && lease.permits(key,epoch,elapsedNowMs)
    val settled=lease.endSubmission()
    if(permitted && settled)return true
    revoke();discardOnOutputThread();return false
  }
  /** Install once through the native playback Handler. Expiry is independent
   * of new writes/JS activity. An early callback schedules only the remaining
   * part of the same captured deadline; it never renews source authority.
   */
  fun armExpiry(elapsedNowMs:()->Long,postDelayedWork:(Long,()->Unit)->Boolean):Boolean {
    if(state.get()!=State.LIVE || !expiryArmed.compareAndSet(false,true))return false
    fun schedule():Boolean {
      if(!lease.controlAt(elapsedNowMs())){revoke();return false}
      val now=lease.controlNow()?:return false
      val permitted=lease.hasTerminalSelection || lease.activeAt(now)
      if(!permitted || now>=terminalDeadline()){revoke();return false}
      return postDelayedWork(terminalDeadline()-now) {
        if(state.get() !in listOf(State.LIVE,State.TERMINAL))return@postDelayedWork
        if(lease.isNaturallyRetired){finishNaturally();return@postDelayedWork}
        if(!isOutputThread()){fail("wrong_thread");return@postDelayedWork}
        val current=lease.controlNow()
        if(current==null || current>=terminalDeadline() || !(lease.hasTerminalSelection || lease.activeAt(current))) {
          revoke();discardOnOutputThread()
        }
        else try {if(!schedule())revoke()} catch(_:RuntimeException){revoke()}
      }
    }
    requestExpirySchedule={schedule()}
    return try {schedule().also {if(!it)revoke()}}
    catch(_:RuntimeException){revoke();false}
  }
  /** Callable on any thread; no sink, track or Authority monitor is acquired.
   * Post failure remains terminal and cannot manufacture a discard ACK.
   */
  fun revoke() {
    if(!enrolled)return
    if(!lease.revoke()){finishNaturally();return}
    while(true) {
      val prior=state.get()
      if(prior !in listOf(State.LIVE,State.TERMINAL))return
      if(state.compareAndSet(prior,State.REVOKED_PENDING))break
    }
    diagnostic(2)
    try {if(!postOutputWork {discardOnOutputThread()})fail("post_failed")}
    catch(_:RuntimeException){fail("post_failed")}
  }
  /** Only Authority's exact sealed native-END transaction can set this lease
   * state. Disarm old callbacks without flushing a later player generation;
   * natural retirement is not an output-discard ACK or a reader-close proof.
   */
  fun finishNaturally():Boolean {
    if(!lease.isNaturallyRetired)return false
    if(state.get()==State.NATURAL)return true
    val prior=state.get()
    if(prior !in listOf(State.LIVE,State.TERMINAL) || !state.compareAndSet(prior,State.NATURAL))return false
    track=null;trackEpoch=null;return true
  }
  private fun discardOnOutputThread() {
    if(state.get()!=State.REVOKED_PENDING)return
    if(!isOutputThread()){fail("wrong_thread");return}
    if(!state.compareAndSet(State.REVOKED_PENDING,State.FLUSHING))return
    val actual=track
    // Absence is unknown. Only the separately retained pristine-sink witness
    // can prove that no submission/provider entry has ever occurred here.
    val neverSubmitted=if(actual==null)sinkBaseline?.neverSubmittedProof(lease) else null
    if(actual==null && neverSubmitted==null || actual!=null && !ownsTrack(actual)) {fail("track_owner");return}
    try {
      // This exact track was positively INITIALIZED at provider capture.
      // Framework release completes native_release before publishing the
      // UNINITIALIZED state. That later state is known release, not absence
      // or an asynchronous release callback. Delegate buffers still need clear.
      if(actual!=null && actual.state!=AudioTrack.STATE_UNINITIALIZED) {actual.pause();actual.flush()}
      clearDelegate()
      // Track/owner loss during delegate clearing is not confirmed discard.
      if(actual!=null && (track!==actual || !ownsTrack(actual))
        || actual==null && (track!=null || !sinkBaseline!!.accepts(neverSubmitted!!,lease))) {
        fail("track_owner");return
      }
      acknowledged.set(DiscardAck.create(this,lease,neverSubmitted));state.set(State.DISCARDED)
    }catch(_:RuntimeException){fail("discard_failed")}
  }
  private fun fail(code:String) {
    if(enrolled && !lease.revoke()){finishNaturally();return}
    if(failure==null)failure=code;state.set(State.FAILED)
  }
  private fun diagnostic(event:Int) {
    try {Log.d("NCContinuousControl","event=$event terminalAttempt=${if(firstTerminalAttempt!=null)1 else 0} " +
      "terminalSelected=${if(lease.hasTerminalSelection)1 else 0} firstMs=${firstTerminalAttempt?:-1} deadlineMs=${terminalDeadline()}")}
    catch(_:RuntimeException) {} // Diagnostic failure cannot alter the actor's state or ACK.
  }
  fun discardAcknowledgement():DiscardAck? = acknowledged.get().takeIf {state.get()==State.DISCARDED}
  internal fun ownsDiscardAcknowledgement(ack:DiscardAck,expected:NCContinuousMuxedAuthority.OutputLease):Boolean =
    state.get()==State.DISCARDED && acknowledged.get()===ack && ack.matches(this,expected)
  internal fun provesNeverSubmitted(ack:DiscardAck,expected:NCContinuousMuxedAuthority.OutputLease):Boolean =
    isOutputThread() && ownsDiscardAcknowledgement(ack,expected) && track==null
      && ack.neverSubmitted?.let {sinkBaseline?.accepts(it,expected)}==true
  fun failureCode():String?=failure
}
