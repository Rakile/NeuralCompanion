package expo.modules.audio

import android.os.Handler
import android.os.Looper
import androidx.media3.exoplayer.source.ConcatenatingMediaSource
import androidx.media3.exoplayer.source.MediaSource

/** Continuous mutation/reader coordinator. Timeline is the application-thread
 * Media3 boundary, not another player or an authority. The concrete adapter and
 * RPCs are still pending; live capability remains zero.
 */
internal class NCContinuousMuxedQueue(private val guard:NCPlaybackGuard,private val binding:NCPlaybackBinding,
  private val presentation:NCContinuousMuxedPresentation,val runRevision:Long,
  wallNowMs:()->Double,elapsedNowMs:()->Long,private val timeline:Timeline) {
  data class Child(val key:NCContinuousMuxedClipKey,val mediaId:String,
    val clip:NCMuxedTrialPlayer.Clip,val reader:NCMuxedTrialReaderFence.Child)
  data class StagingResult(val status:NCContinuousMuxedQueueState.StageStatus,val token:String?=null,val reason:String?=null) {
    init {require((status==NCContinuousMuxedQueueState.StageStatus.STAGED)==(token!=null))}
  }
  /** Native-only closure identity. Neither detach ACK nor caller booleans can
   * mint it; the worker must have joined every delegated reader first.
   */
  class RetirementWitness private constructor(private val owner:NCContinuousMuxedQueue,
    private val run:NCContinuousMuxedAuthority.RunHandle,val mutationRevision:Long) {
    internal fun matches(queue:NCContinuousMuxedQueue,expected:NCContinuousMuxedAuthority.RunHandle)=
      owner===queue && run===expected && owner.closedWitness===this
    companion object {internal fun create(queue:NCContinuousMuxedQueue,run:NCContinuousMuxedAuthority.RunHandle,revision:Long)=
      RetirementWitness(queue,run,revision)}
  }
  /** Reader-only terminal ownership, also for failure before beginRun. This
   * never proves enrollment, output settlement or permission to reuse a sink. */
  class DetachedReaders private constructor(private val owner:NCContinuousMuxedQueue) {
    internal fun matches(queue:NCContinuousMuxedQueue)=owner===queue && owner.detachedReaderWitness()===this
    companion object {internal fun create(queue:NCContinuousMuxedQueue)=DetachedReaders(queue)}
  }
  /** Whole mixed-owner retirement only: real reader join plus exact positive
   * sink settlement. Speech completion cannot construct this certificate. */
  class MixedRetirement private constructor(private val owner:NCContinuousMuxedQueue,
    internal val run:NCContinuousMuxedAuthority.RunHandle,internal val visual:NCContinuousMuxedAuthority.VisualGrant,
    internal val closure:RetirementWitness,internal val settlement:NCContinuousMuxedSinkController.SinkSettlement,
    private val lease:NCContinuousMuxedAuthority.OutputLease,val natural:Boolean) {
    internal fun matches(authority:NCContinuousMuxedAuthority):Boolean = owner.authority===authority
      &&closure.matches(owner,run) &&settlement.matchesRetirement(owner,closure,lease)
      &&lease.isRevoked &&lease.isNaturallyRetired==natural
    companion object {internal fun create(queue:NCContinuousMuxedQueue,run:NCContinuousMuxedAuthority.RunHandle,
      visual:NCContinuousMuxedAuthority.VisualGrant,closure:RetirementWitness,
      settlement:NCContinuousMuxedSinkController.SinkSettlement,lease:NCContinuousMuxedAuthority.OutputLease)=
      MixedRetirement(queue,run,visual,closure,settlement,lease,lease.isNaturallyRetired)}
  }
  interface Timeline {
    // A true return schedules only; callback confirms the actual mutation.
    fun append(children:List<Child>,done:(Boolean)->Unit):Boolean
    fun seal(done:(Boolean)->Unit):Boolean
    fun remove(keys:List<NCContinuousMuxedClipKey>,done:(Boolean)->Unit):Boolean
    // Unknown actual Media3 period ownership retains the prefix; never guess
    // that advanced decoder/output cursors mean the playing period was released.
    fun pruneLimitOrdinal():Long=0
    fun detach(done:(Boolean)->Unit):Boolean
    fun stopAndFlush()
  }
  private data class Stage(val id:String,val descriptor:NCContinuousMuxedSourceDescriptor?,
    val reservation:NCContinuousMuxedQueueState.Token,val children:List<Child>,var attempted:Boolean=false,
    val visualDescriptor:NCContinuousMuxedReturnDescriptor?=null,
    val orderedDescriptor:NCOrderedMuxedSourceDescriptor?=null)
  private val state=NCContinuousMuxedQueueState(runRevision,desktopOrdered=presentation.desktopOrdered)
  private val journal=NCContinuousMuxedJournal(runRevision,desktopOrdered=presentation.desktopOrdered)
  private val readerFence=NCMuxedTrialReaderFence()
  // Authority may resolve a stage on a renderer/worker thread. Lookup must not
  // acquire this queue's monitor (mutations enter authority in the other order).
  private val stages=java.util.concurrent.ConcurrentHashMap<String,Stage>()
  private val retained=linkedMapOf<Long,Child>()
  private val grants=linkedMapOf<String,NCContinuousMuxedAuthority.SourceGrant>()
  private var visualGrant:NCContinuousMuxedAuthority.VisualGrant?=null
  private var visualClosedThrough=-1
  private val removed=mutableSetOf<NCContinuousMuxedClipKey>()
  private val closureEligible=mutableSetOf<NCContinuousMuxedClipKey>()
  private val usedStageIds=mutableSetOf<String>()
  private var pending:String?=null
  private var sealing=false
  private var activeRun:NCContinuousMuxedAuthority.RunHandle?=null
  private var detached=false
  @Volatile private var closedWitness:RetirementWitness?=null
  @Volatile private var closedReaders:DetachedReaders?=null
  private var mixedRetirement:MixedRetirement?=null
  // Output-thread hint only. This can start a bounded EOS proof request, never
  // attest tail/mutation/output; the worker rechecks the exact native gate.
  @Volatile internal var sealedOutputTail:NCContinuousMuxedClipKey?=null
    private set
  internal val sealedOutputHint get()=sealedOutputTail!=null
  val authority=NCContinuousMuxedAuthority(guard,presentation,state,journal,wallNowMs,elapsedNowMs,
    {id->stages[id]?.reservation},
    {readerFence.retire();timeline.stopAndFlush()})
  internal fun matchesBinding(expected:NCPlaybackBinding)=binding===expected
  internal fun continuationBuffered()=presentation.orderedBufferedMedia()
  @Synchronized internal fun continuationCurrent(run:NCContinuousMuxedAuthority.RunHandle):Boolean =
    activeRun===run &&!detached &&binding.orderedCarrier?.let{guard.orderedCarrierEligible(it)}==true
      &&authority.nativeOutputLease(run)?.isRevoked==false
  @Synchronized internal fun continuationPause(run:NCContinuousMuxedAuthority.RunHandle,epoch:Long):NCPlaybackGuard.LockPausePermit? {
    if(!continuationCurrent(run))return null
    return binding.orderedCarrier?.let{guard.pauseOrderedTransport(it,epoch)}
  }
  @Synchronized internal fun continuationResume(run:NCContinuousMuxedAuthority.RunHandle,epoch:Long):Boolean {
    if(!continuationCurrent(run))return false
    return binding.orderedCarrier?.let{guard.resumeOrderedTransport(it,epoch)}==true
  }
  @Synchronized internal fun continuationCue(run:NCContinuousMuxedAuthority.RunHandle,epoch:Long,
    stop:()->Unit,play:()->Boolean):Boolean {
    if(!continuationCurrent(run))return false
    return binding.orderedCarrier?.let{guard.performOrderedConnectionCue(it,epoch,stop,play)}==true
  }
  @Synchronized internal fun nativeEnrollment():Pair<NCContinuousMuxedAuthority.OutputLease,NCContinuousMuxedPresentation>? {
    val run=activeRun?:return null
    if(pending!=null || detached || state.snapshot().tail==null)return null
    val lease=authority.nativeOutputLease(run)?:return null
    return lease to presentation
  }

  @Synchronized fun beginRun(d:NCContinuousMuxedSourceDescriptor):NCContinuousMuxedAuthority.RunHandle? {
    if(activeRun!=null || pending!=null)return null
    return authority.beginRun(d,binding)?.also {activeRun=it}
  }
  @Synchronized internal fun beginOrderedRun(d:NCOrderedMuxedSessionDescriptor):NCContinuousMuxedAuthority.RunHandle? {
    if(activeRun!=null ||pending!=null ||!state.desktopOrdered)return null
    return authority.beginOrderedRun(d,binding)?.also{activeRun=it}
  }
  /** Same validated files, timeline and delegated-reader fences. Desktop metadata
   * fixes each ordinal; neither staging nor scheduling enables decoder output. */
  internal fun stageOrdered(d:NCOrderedMuxedSourceDescriptor,output:List<NCOrderedOutputChunk>,
    clips:List<NCMuxedTrialPlayer.Clip>,expectedRunRevision:Long):String? =
    stageOrderedResult(d,output,clips,expectedRunRevision).token
  @Synchronized internal fun stageOrderedResult(d:NCOrderedMuxedSourceDescriptor,output:List<NCOrderedOutputChunk>,
    clips:List<NCMuxedTrialPlayer.Clip>,expectedRunRevision:Long):StagingResult {
    fun reject(reason:String)=StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED,reason=reason)
    if(!state.desktopOrdered)return reject("ordered_mode")
    if(activeRun==null)return reject("run_missing")
    if(pending!=null)return reject("mutation_pending")
    if(sealing)return reject("sealing")
    if(expectedRunRevision!=runRevision)return reject("run_revision")
    if(clips.size !in 1..6 ||output.size!=clips.size)return reject("batch_count")
    val first=(output.first().sourceRange.start/12).toInt()
    if(first !in 0 until d.plan.totalRanges ||first+clips.size>d.plan.totalRanges)return reject("range_bounds")
    for((offset,clip) in clips.withIndex()) {
      val chunk=output[offset];val trim=clip.validatedTrim
      if(!d.matches(chunk))return reject("clip.$offset.descriptor")
      if(chunk.sourceRange.start!=(first+offset)*12L)return reject("clip.$offset.range")
      if(chunk.frameCount!=clip.frames)return reject("clip.$offset.frames")
      if(chunk.sampleCount!=clip.samples ||clip.startSamples!=(first+offset)*24000L)return reject("clip.$offset.samples")
      if(chunk.byteLength!=clip.bytes)return reject("clip.$offset.bytes")
      if(trim==null ||trim.delay<0 ||trim.padding<0 ||trim.raw.toLong()!=clip.samples.toLong()+trim.delay+trim.padding)
        return reject("clip.$offset.trim")
      if(clip.file!=clip.file.canonicalFile ||!clip.file.isFile ||clip.file.length()!=clip.bytes)return reject("clip.$offset.custody")
    }
    val id=if(first==0)d.validatedStagingIdentity else java.util.UUID.randomUUID().toString()
    if(id in usedStageIds)return reject("stage_identity")
    val revision=state.snapshot().mutationRevision
    val rows=clips.indices.map{offset->NCContinuousMuxedQueueState.Range(
      NCContinuousMuxedClipKey(d.validatedStagingIdentity,first+offset,output[offset].ordinal),d.plan.totalRanges,clips[offset].bytes,
      if(d.silent)NCContinuousMuxedQueueState.RangeKind.VISUAL else NCContinuousMuxedQueueState.RangeKind.SPEECH)}
    val staged=state.stageResult(rows,runRevision,revision)
    val reservation=staged.token?:return StagingResult(staged.status,reason=if(staged.status==NCContinuousMuxedQueueState.StageStatus.CAPACITY)
      "retained_capacity" else "ordered_reservation")
    val children=clips.mapIndexed{offset,clip->Child(rows[offset].key,"nc-ordered-$runRevision-${rows[offset].key.ordinal}",
      clip.copy(),readerFence.child())}
    stages[id]=Stage(id,null,reservation,children,orderedDescriptor=d.copy());usedStageIds+=id
    return StagingResult(NCContinuousMuxedQueueState.StageStatus.STAGED,id)
  }
  @Synchronized internal fun appendOrdered(token:String,g:NCContinuousMuxedAuthority.OrderedGrant,
    revision:Long,done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    val stage=stages[token]?:return false
    if(pending!=null ||stage.attempted ||stage.orderedDescriptor!=g.descriptor ||g.run!==activeRun
      ||!authority.allowsOrderedTimelineCommit(g,revision))return false
    return mutateStage(stage,done){authority.acknowledgeOrderedTimeline(g,stage.reservation,revision)}
  }
  @Synchronized internal fun releaseOrderedSource(g:NCContinuousMuxedAuthority.OrderedGrant):Boolean {
    if(pending!=null ||!state.desktopOrdered ||g.run!==activeRun ||!authority.releaseOrderedSource(g))return false
    val keys=retained.values.filter{it.key.sourceHandle==g.id}.map{it.key}.toSet()
    retained.entries.removeAll{it.value.key in keys};removed.removeAll(keys);closureEligible.removeAll(keys)
    usedStageIds.remove(g.id)
    return true
  }

  /** Called only with clips returned by off-main validateStream. This repeats
   * immutable span/file checks, not codec validation or relay authentication.
   */
  fun stage(d:NCContinuousMuxedSourceDescriptor,firstRange:Int,
    clips:List<NCMuxedTrialPlayer.Clip>,expectedRunRevision:Long):String? = stageResult(d,firstRange,clips,expectedRunRevision).token
  @Synchronized fun stageResult(d:NCContinuousMuxedSourceDescriptor,firstRange:Int,
    clips:List<NCMuxedTrialPlayer.Clip>,expectedRunRevision:Long):StagingResult {
    if(sealing || expectedRunRevision!=runRevision || state.snapshot().state!=NCContinuousMuxedQueueState.State.OPEN
      || clips.size !in 1..6 || firstRange !in 0 until d.plan.totalRanges
      || firstRange+clips.size>d.plan.totalRanges)return StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED)
    if(clips.withIndex().any {(offset,clip)->
      val index=firstRange+offset
      val valid=if(index==d.plan.totalRanges-1)d.plan.samples-index*24000L else 24000L
      val frames=minOf(12,d.plan.frames-index*12)
      val trim=clip.validatedTrim
      clip.samples.toLong()!=valid || clip.frames!=frames || clip.startSamples!=index*24000L
        || trim==null || trim.delay<0 || trim.padding<0 || trim.raw.toLong()!=valid+trim.delay+trim.padding
        || clip.file!=clip.file.canonicalFile || !clip.file.isFile || clip.file.length()!=clip.bytes
    })return StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED)
    val id=if(firstRange==0)d.validatedStagingIdentity else java.util.UUID.randomUUID().toString()
    if(id in usedStageIds)return StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED)
    val snapshot=state.snapshot()
    val ordinal=snapshot.tail?.ordinal?.let {
      if(it==Long.MAX_VALUE)return StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED);it+1}?:0L
    val rows=clips.indices.map {offset->NCContinuousMuxedQueueState.Range(
      NCContinuousMuxedClipKey(d.validatedStagingIdentity,firstRange+offset,ordinal+offset),d.plan.totalRanges,clips[offset].bytes)}
    val result=state.stageResult(rows,runRevision,snapshot.mutationRevision)
    val reservation=result.token?:return StagingResult(result.status)
    val children=clips.mapIndexed {offset,clip->Child(rows[offset].key,
      "nc-continuous-${java.util.UUID.randomUUID()}",clip.copy(),readerFence.child())}
    stages[id]=Stage(id,d.copy(),reservation,children.toList());usedStageIds+=id
    return StagingResult(NCContinuousMuxedQueueState.StageStatus.STAGED,id)
  }
  @Synchronized fun open(token:String,grant:NCContinuousMuxedAuthority.SourceGrant,
    expectedMutationRevision:Long,done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    if(state.snapshot().tail!=null)return false
    return mutate(token,grant,expectedMutationRevision,done)
  }
  /** Uses the same off-main extractor-validated files and reader fence as speech,
   * but reserves a rolling visual epoch rather than a finite speech layout. */
  @Synchronized fun stageReturnResult(d:NCContinuousMuxedReturnDescriptor,tail:NCContinuousMuxedQueueState.Tail,
    revision:Long,clips:List<NCMuxedTrialPlayer.Clip>):StagingResult = stageVisualFiles(d,0,tail,revision,clips,true)
  @Synchronized fun stageVisualResult(grant:NCContinuousMuxedAuthority.VisualGrant,firstRange:Int,
    revision:Long,clips:List<NCMuxedTrialPlayer.Clip>):StagingResult {
    val tail=state.snapshot().tail
    if(tail==null ||tail.sourceHandle!=grant.id ||firstRange<=0 ||!authority.allowsReturnTimelineCommit(grant,revision))
      return StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED)
    return stageVisualFiles(grant.descriptor,firstRange,tail,revision,clips,false)
  }
  private fun stageVisualFiles(d:NCContinuousMuxedReturnDescriptor,firstRange:Int,tail:NCContinuousMuxedQueueState.Tail,
    revision:Long,clips:List<NCMuxedTrialPlayer.Clip>,opening:Boolean):StagingResult {
    fun rejected()=StagingResult(NCContinuousMuxedQueueState.StageStatus.REJECTED)
    val snapshot=state.snapshot()
    if(activeRun==null ||sealing ||pending!=null ||snapshot.state!=NCContinuousMuxedQueueState.State.OPEN
      ||snapshot.tail!=tail ||opening &&snapshot.speechTail!=tail
      ||snapshot.mutationRevision!=revision ||!d.matches(d.parent) ||clips.size !in (if(opening)2..6 else 1..6)
      ||firstRange !in 0..10005 ||firstRange+clips.size>10006
      ||opening &&d.validatedStagingIdentity in usedStageIds ||tail.ordinal>Long.MAX_VALUE-clips.size)return rejected()
    if(clips.withIndex().any {(index,clip)->
      val trim=clip.validatedTrim
      clip.samples!=24000 ||clip.frames!=12 ||clip.startSamples!=(firstRange+index)*24000L
        ||trim==null ||trim.delay<0 ||trim.padding<0 ||trim.raw !in 1024..28672 ||trim.raw%1024!=0
        ||trim.raw.toLong()!=24000L+trim.delay+trim.padding
        ||clip.file!=clip.file.canonicalFile ||!clip.file.isFile ||clip.file.length()!=clip.bytes
    })return rejected()
    val pendingVisual=stages.values.filter {it.visualDescriptor!=null}.sumOf {it.children.size}
    if(snapshot.retainedVisualRanges+pendingVisual+clips.size>6)
      return StagingResult(NCContinuousMuxedQueueState.StageStatus.CAPACITY)
    val rows=clips.indices.map {index->NCContinuousMuxedQueueState.Range(
      NCContinuousMuxedClipKey(d.validatedStagingIdentity,firstRange+index,tail.ordinal+1+index),0,clips[index].bytes,
      NCContinuousMuxedQueueState.RangeKind.VISUAL)}
    val staged=if(opening)state.stageReturn(rows,runRevision,tail,revision) else state.stageResult(rows,runRevision,revision)
    val reservation=staged.token?:return StagingResult(staged.status)
    val children=clips.mapIndexed {index,clip->Child(rows[index].key,
      "nc-continuous-${java.util.UUID.randomUUID()}",clip.copy(),readerFence.child())}
    val id=if(opening)d.validatedStagingIdentity else java.util.UUID.randomUUID().toString()
    stages[id]=Stage(id,d.parent.copy(),reservation,children.toList(),visualDescriptor=d.copy());usedStageIds+=id
    return StagingResult(NCContinuousMuxedQueueState.StageStatus.STAGED,id)
  }
  @Synchronized fun appendReturn(token:String,grant:NCContinuousMuxedAuthority.VisualGrant,revision:Long,
    done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    val stage=stages[token]?:return false
    if(pending!=null ||stage.attempted ||stage.visualDescriptor!=grant.descriptor
      ||!authority.allowsReturnTimelineCommit(grant,revision))return false
    visualGrant=grant
    return mutateStage(stage,done) {authority.acknowledgeReturn(grant,stage.reservation,revision)}
  }
  @Synchronized fun append(token:String,grant:NCContinuousMuxedAuthority.SourceGrant,
    expectedMutationRevision:Long,done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    if(state.snapshot().tail==null)return false
    return mutate(token,grant,expectedMutationRevision,done)
  }
  private fun ack(outcome:NCContinuousMuxedQueueState.Outcome):NCContinuousMuxedQueueState.Ack {
    val snapshot=state.snapshot()
    return NCContinuousMuxedQueueState.Ack(runRevision,snapshot.mutationRevision,snapshot.tail,outcome)
  }
  private fun mutate(token:String,grant:NCContinuousMuxedAuthority.SourceGrant,revision:Long,
    done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    val stage=stages[token]?:return false
    if(pending!=null || stage.attempted || grant.origin!==authority
      ||stage.visualDescriptor!=null || stage.descriptor!=authority.sourceDescriptor(grant) || !authority.allowsTimelineCommit(grant,revision))return false
    activeRun=grant.run;grants[grant.id]=grant
    return mutateStage(stage,done) {authority.acknowledgeTimeline(grant,stage.reservation,revision)}
  }
  private fun mutateStage(stage:Stage,done:(NCContinuousMuxedQueueState.Ack)->Unit,
    commit:()->NCContinuousMuxedQueueState.Ack):Boolean {
    val token=stage.id;stage.attempted=true;pending=token
    // Exact ranges are known before a decoder can read them. Installation is
    // still unacknowledged, so the authority cannot accept their output yet.
    stage.children.forEach {child->val trim=child.clip.validatedTrim!!
      presentation.registerRange(child.key,child.clip.startSamples,child.clip.samples.toLong(),trim.delay,trim.padding,trim.raw)}
    var called=false
    try {
      val scheduled=timeline.append(stage.children) {accepted->synchronized(this) {
        if(called)return@synchronized
        called=true
        if(pending==token)pending=null
        val committed=if(accepted && stage.children.all {it.clip.file.isFile && it.clip.file.length()==it.clip.bytes})
          commit() else null
        if(committed?.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED) {
          // Only the source identity survives until reader closure. Continuation
          // tokens cannot be replayed after removal from stages; ordinals provide
          // the permanent high-water fence without a tombstone per half-second.
          if(stage.orderedDescriptor!=null &&stage.children.first().key.rangeIndex>0)usedStageIds.remove(token)
          stage.children.forEach {retained[it.key.ordinal]=it};stages.remove(token);done(committed)
        } else {
          fence("mutation_ack");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED))
        }
      }}
      val acknowledged=called
      if(!scheduled && !called) {
        called=true;pending=null;stage.attempted=false
        // No mutation happened, but registered proof spans cannot be retried
        // under another decoder identity. Keep ownership and fail closed.
        fence("mutation_schedule")
        done(ack(NCContinuousMuxedQueueState.Outcome.REJECTED_BEFORE_MUTATION))
      }
      return scheduled || acknowledged
    }catch(error:RuntimeException) {
      if(called)throw error // The resolved native ACK cannot be rewritten by its consumer.
      called=true;pending=null;fence("mutation_ambiguous");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED));return true
    }
  }
  @Synchronized fun seal(tail:NCContinuousMuxedQueueState.Tail,expectedMutationRevision:Long,
    done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    val grant=grants[tail.sourceHandle]
    val returning=visualGrant?.takeIf {it.id==tail.sourceHandle}
    fun eligible()=if(grant!=null)authority.allowsTimelineCommit(grant,expectedMutationRevision)
      else returning?.let {authority.allowsReturnTimelineCommit(it,expectedMutationRevision)}==true
    if(pending!=null || !state.canSeal(tail,expectedMutationRevision) ||!eligible())return false
    val operation=java.util.UUID.randomUUID().toString();pending=operation;sealing=true
    var called=false
    try {
      val scheduled=timeline.seal {accepted->synchronized(this) {
        if(called)return@synchronized
        called=true;if(pending==operation)pending=null;sealing=false
        val committed=if(accepted &&eligible())
          state.seal(tail,expectedMutationRevision) else null
        if(committed?.outcome==NCContinuousMuxedQueueState.Outcome.COMMITTED
          &&(returning==null ||presentation.sealVisualTail(NCContinuousMuxedClipKey(tail.sourceHandle,tail.lastRange,tail.ordinal)))
          && authority.allowsNativeControl(committed.mutationRevision)) {
          sealedOutputTail=NCContinuousMuxedClipKey(tail.sourceHandle,tail.lastRange,tail.ordinal);done(committed)
        } else {fence("seal_ack");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED))}
      }}
      val acknowledged=called
      if(!scheduled && !called) {
        called=true;pending=null;sealing=false;fence("seal_schedule")
        done(ack(NCContinuousMuxedQueueState.Outcome.REJECTED_BEFORE_MUTATION))
      }
      return scheduled || acknowledged
    }catch(error:RuntimeException) {
      if(called)throw error
      called=true;pending=null;sealing=false;fence("seal_ambiguous")
      done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED));return true
    }
  }
  /** Worker-only; a logical prune revision is not its actual Media3 ACK.
   * The Queue monitor serializes selection with all pending native mutations.
   */
  @Synchronized fun attestTerminal(run:NCContinuousMuxedAuthority.RunHandle,tail:NCContinuousMuxedQueueState.Tail,
    expectedMutationRevision:Long,witness:NCContinuousMuxedOutputGate.TrackWitness):NCContinuousMuxedAuthority.TerminalAttestation? {
    if(pending!=null || detached || run!=activeRun)return null
    return authority.attestTerminal(run,tail,expectedMutationRevision,witness)
  }
  /** Native worker only; output hooks post this work without taking our gate. */
  @Volatile internal var onCachedPresentation:(()->Unit)?=null
  @Volatile internal var onContinuationPresentation:(()->Unit)?=null
  @Synchronized fun reconcileNativePresentation(run:NCContinuousMuxedAuthority.RunHandle):Boolean {
    val accepted=run==activeRun &&authority.reconcileNativePresentation(run)
    if(accepted)onCachedPresentation?.invoke() // Post only; never wait on main here.
    if(accepted)onContinuationPresentation?.invoke() // Same post-only rule; no nested queue/Guard waits.
    return accepted
  }
  @Synchronized internal fun cachedScope(c:NCOrderedCachedIdle.Candidate):Boolean {
    val run=activeRun?:return false
    val snapshot=authority.orderedSnapshot(run)?:return false
    return !detached &&snapshot["failure"]==null &&snapshot["state"]=="open"
      &&snapshot["streamId"]==c.streamId &&snapshot["generation"]==c.generation
  }
  @Synchronized internal fun cachedTailSettled(c:NCOrderedCachedIdle.Candidate):Boolean {
    val run=activeRun?:return false
    val snapshot=authority.orderedSnapshot(run)?:return false
    val frames=retained[c.afterOrdinal]?.clip?.frames?:return false
    return !detached &&NCOrderedCachedIdle.tailSettled(c,snapshot,presentation.renderedVideo?.snapshot()?:return false,frames)
  }
  internal fun cachedPresentedFrame():Map<String,Any>? = presentation.renderedVideo?.snapshot()
  @Synchronized internal fun cachedBoundaryEvidence(c:NCOrderedCachedIdle.Candidate):Map<String,Any?> =
    NCOrderedCachedIdle.boundaryEvidence(c,activeRun?.let{authority.orderedSnapshot(it)},
      presentation.renderedVideo?.snapshot(),retained[c.afterOrdinal]?.clip?.frames)+
      (presentation.renderedVideo?.rejectionEvidence()?:emptyMap())
  internal fun observeCachedFrames(observer:(()->Unit)?) {presentation.renderedVideo?.onChanged=observer}
  @Synchronized fun dropStage(token:String):Boolean {
    val stage=stages[token]?:return false
    if(stage.attempted || pending==token)return false
    val dropped=state.drop(stage.reservation) {
      stage.children.forEach {it.reader.retire()}
      stage.children.map {it.reader.awaitClosed(0)}.all {it}
    }
    if(dropped) {
      stages.remove(token)
      if(stage.orderedDescriptor!=null)usedStageIds.remove(token)
    }
    return dropped
  }
  /** Derive a source's boundary only from this native Queue's exact issued
   * grant and retained complete layout. A wire ordinal is never retirement
   * evidence; the normal protected-cursor prune still clamps this cutoff.
   */
  @Synchronized internal fun sourceRetirementCutoff(grant:NCContinuousMuxedAuthority.SourceGrant):Long? {
    val owned=authority.sourceState(grant)?:return null
    if(!owned.completed || !owned.layoutInstalled || grant.run!==activeRun || grant.origin!==authority)return null
    val rows=retained.values.filter {it.key.sourceHandle==grant.id}
    if(rows.size!=grant.descriptor.plan.totalRanges || rows.map {it.key.rangeIndex}.toSet()!=
      (0 until grant.descriptor.plan.totalRanges).toSet())return null
    return rows.maxOf {it.key.ordinal}.takeIf {it<Long.MAX_VALUE}?.plus(1)
  }
  @Synchronized fun prune(beforeOrdinal:Long,expectedMutationRevision:Long,
    done:(NCContinuousMuxedQueueState.Ack)->Unit):Boolean {
    if(pending!=null || !authority.allowsNativeControl(expectedMutationRevision))return false
    val cutoff=if(state.desktopOrdered)minOf(beforeOrdinal,timeline.pruneLimitOrdinal().coerceAtLeast(0)) else beforeOrdinal
    val keys=state.prune(cutoff,expectedMutationRevision,presentation.protectedCursors())?:return false
    authority.refreshNativeOutputLease()
    if(keys.isEmpty()){done(ack(NCContinuousMuxedQueueState.Outcome.COMMITTED));return true}
    removed+=keys
    keys.forEach {retained[it.ordinal]!!.reader.retire()}
    val operation=java.util.UUID.randomUUID().toString();pending=operation
    var called=false
    try {
      val scheduled=timeline.remove(keys){accepted->synchronized(this){
        if(called)return@synchronized
        called=true;if(pending==operation)pending=null
        if(accepted && authority.allowsNativeControl(state.snapshot().mutationRevision)) {
          closureEligible+=keys;done(ack(NCContinuousMuxedQueueState.Outcome.COMMITTED))
        } else {fence("prune_ack");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED))}
      }}
      val acknowledged=called
      if(!scheduled && !called) {
        called=true;pending=null;fence("prune_schedule");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED))
      }
      return scheduled || acknowledged
    }catch(error:RuntimeException) {
      if(called)throw error
      called=true;pending=null;fence("prune_ambiguous");done(ack(NCContinuousMuxedQueueState.Outcome.FAILED_CLOSED));return true
    }
  }
  /** A requested idle index is only a ceiling: native output protection still
   * clamps removal, and capacity/file release awaits the delegated reader join. */
  @Synchronized internal fun visualRetirementCutoff(grant:NCContinuousMuxedAuthority.VisualGrant,beforeIndex:Int):Long? {
    val tail=state.snapshot().tail?:return null
    if(grant!==visualGrant ||grant.run!==activeRun ||tail.sourceHandle!=grant.id
      ||beforeIndex !in 0..tail.lastRange+1)return null
    return grant.tail.ordinal+1+beforeIndex
  }
  @Synchronized internal fun visualReleasedThrough(grant:NCContinuousMuxedAuthority.VisualGrant):Int? =
    (visualClosedThrough+1).takeIf {grant===visualGrant &&grant.run===activeRun}
  @Synchronized fun fence(cause:String) {
    val run=activeRun
    if(run!=null)authority.fenceRun(run,cause)
    else {state.fence(cause);readerFence.retire();presentation.fence("authority");timeline.stopAndFlush()}
  }
  /** RPC invokes this only after physical output settlement, before discarding
   * the native record. Reader closure alone is not physical settlement. */
  @Synchronized internal fun sealStoppedVideo():Map<String,Any> {
    check(retirementWitness()!=null &&state.desktopOrdered)
    return presentation.renderedVideo!!.seal()
  }
  @Synchronized fun detachFailedRun(done:(Boolean)->Unit):Boolean {
    if(state.snapshot().state!=NCContinuousMuxedQueueState.State.FAILED || pending!=null || detached)return false
    return detach(done)
  }
  /** Invoked only by the exact native application-thread timeline-END hook.
   * This checks proof/ledger drain; it does not turn global END into receipts.
   */
  @Synchronized fun recordNativeTimelineEnd(expectedMutationRevision:Long):Boolean {
    val run=activeRun?:return false;val tail=state.snapshot().tail?:return false
    return pending==null && authority.recordNativeRunEnd(run,tail,expectedMutationRevision)
  }
  /** done acknowledges actual timeline detachment ONLY. The module worker
   * must then join awaitDetachedReaders before returning a retirement ACK.
   * No player release, session close or reply-tail settlement occurs here.
   */
  @Synchronized fun retireRun(expectedMutationRevision:Long,done:(Boolean)->Unit):Boolean {
    val snapshot=state.snapshot()
    if(snapshot.state!=NCContinuousMuxedQueueState.State.DRAINED || snapshot.mutationRevision!=expectedMutationRevision
      || pending!=null || detached)return false
    return detach(done)
  }
  private fun detach(done:(Boolean)->Unit):Boolean {
    readerFence.retire()
    val keys=state.markDetached();removed+=keys
    (retained.values+stages.values.flatMap {it.children}).forEach {it.reader.retire()}
    val operation=java.util.UUID.randomUUID().toString();pending=operation
    var called=false
    try {
      val scheduled=timeline.detach {accepted->synchronized(this){
        if(called)return@synchronized
        called=true;if(pending==operation)pending=null
        detached=accepted;if(accepted)closureEligible+=removed;done(accepted)}}
      val acknowledged=called
      if(!scheduled && !called){called=true;pending=null;done(false)}
      return scheduled || acknowledged
    }catch(error:RuntimeException){if(called)throw error;called=true;pending=null;done(false);return true}
  }
  @Synchronized fun confirmReaderClosure(keys:List<NCContinuousMuxedClipKey>):Boolean {
    if(keys.isEmpty() ||keys.toSet().size!=keys.size)return false
    val fresh=keys.filterNot {releasedVisualKey(it)}
    if(fresh.any {it !in closureEligible || retained[it.ordinal]?.key!=it})return false
    // Nonblocking check only. The native worker joins delegated closes first.
    val closed=fresh.map {retained[it.ordinal]!!.reader.awaitClosed(0)}
    if(closed.any {!it})return false
    for(key in fresh.sortedBy {it.ordinal}) {
      val visual=key.sourceHandle==visualGrant?.id
      if(visual &&!presentation.forgetClosedVisualRange(key))return false
      if(!state.confirmReaderClosure(listOf(key))){fence("reader_closure");return false}
      if(visual) {
        visualClosedThrough=key.rangeIndex
        retained.remove(key.ordinal);removed.remove(key);closureEligible.remove(key)
      }
    }
    return publishReaderClosures()
  }
  /** Bounded native closure history, not a caller-supplied free-file proof. */
  private fun releasedVisualKey(key:NCContinuousMuxedClipKey):Boolean {
    val visual=visualGrant?:return false
    return key.sourceHandle==visual.id &&key.rangeIndex in 0..visualClosedThrough
      &&key.ordinal==visual.tail.ordinal+1+key.rangeIndex
  }
  /** Worker-only join of this Queue's acknowledged removals. No caller list,
   * timeline removal or source completion can stand in for delegated closure.
   * Pending removal keeps the entire reservation charged. All selected readers
   * are visited under one deadline, outside the Queue monitor.
   */
  fun awaitPrunedReaders(timeoutMillis:Long):Boolean {
    val children=synchronized(this) {
      if(detached || pending!=null || removed.any {it !in closureEligible})return false
      removed.map {key->retained[key.ordinal]?.takeIf {it.key==key}?:return false}
    }
    if(children.isEmpty())return true
    val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,5000))
    var closed=true
    for(child in children) {
      val remaining=java.util.concurrent.TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0))
      if(!child.reader.awaitClosed(remaining))closed=false
    }
    return closed && confirmReaderClosure(children.map {it.key})
  }
  private fun publishReaderClosures():Boolean = authority.reconcileReaderClosures()
  @Synchronized fun confirmAllDetachedReaders():Boolean {
    if(!detached || pending!=null)return false
    val owned=retained.values+stages.values.flatMap {it.children}
    // Evaluate every child, even if an earlier close failed.
    if(owned.map {it.reader.awaitClosed(0)}.any {!it})return false
    if(removed.isNotEmpty() && !state.confirmReaderClosure(removed.toList()))return false
    stages.values.forEach {state.releaseDetachedReservation(it.reservation)};stages.clear()
    if(!publishReaderClosures())return false
    val retired=state.snapshot().state==NCContinuousMuxedQueueState.State.RETIRED || state.finishRetirement()
    if(retired && closedReaders==null)closedReaders=DetachedReaders.create(this)
    if(retired && closedWitness==null)activeRun?.let {
      closedWitness=RetirementWitness.create(this,it,state.snapshot().mutationRevision)
    }
    return retired
  }
  @Synchronized internal fun retirementWitness():RetirementWitness? = closedWitness.takeIf {
    detached && pending==null && state.snapshot().state==NCContinuousMuxedQueueState.State.RETIRED
  }
  @Synchronized internal fun detachedReaderWitness():DetachedReaders? = closedReaders.takeIf {
    detached && pending==null && state.snapshot().state==NCContinuousMuxedQueueState.State.RETIRED
  }
  @Synchronized internal fun hasVisualMembership():Boolean =
    activeRun?.let {authority.nativeVisualGrant(it)}!=null
  internal fun certifyMixedRetirement(settled:NCContinuousMuxedSinkController.SinkSettlement?):MixedRetirement? {
    if(settled?.canInspectRetirement()!=true)return null
    val facts=synchronized(this) {
      val closure=retirementWitness()?:return null
      val run=activeRun?:return null;val visual=authority.nativeVisualGrant(run)?:return null
      val lease=authority.nativeOutputLease(run)?:return null
      Triple(closure,visual,lease)
    }
    if(!settled.matchesRetirement(this,facts.first,facts.third))return null
    return synchronized(this) {
      if(retirementWitness()!==facts.first ||authority.nativeVisualGrant(facts.third.run)!==facts.second)return@synchronized null
      mixedRetirement?.let {return@synchronized it.takeIf {value->value.settlement===settled}}
      val certificate=MixedRetirement.create(this,facts.third.run,facts.second,facts.first,settled,facts.third)
      if(!authority.recordMixedRetirement(certificate))return@synchronized null
      mixedRetirement=certificate;certificate
    }
  }
  /** Native module worker only: never hold the queue monitor or player looper
   * while waiting. One bounded monotonic window visits every exact delegated
   * child, even after an earlier failure; failure retains the entire ownership.
   */
  fun awaitDetachedReaders(timeoutMillis:Long):Boolean {
    val children=synchronized(this) {
      if(!detached || pending!=null)return false
      (retained.values+stages.values.flatMap {it.children}).map {it.reader}
    }
    val deadline=System.nanoTime()+java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(timeoutMillis.coerceIn(0,5000))
    var closed=true
    for(child in children) {
      val remaining=java.util.concurrent.TimeUnit.NANOSECONDS.toMillis((deadline-System.nanoTime()).coerceAtLeast(0))
      if(!child.awaitClosed(remaining))closed=false
    }
    return closed && confirmAllDetachedReaders()
  }
  @Synchronized fun snapshot():NCContinuousMuxedQueueState.Snapshot=state.snapshot()
  @Synchronized fun journalSnapshot():NCContinuousMuxedJournal.Snapshot=journal.snapshot()
}

/** One persistent Media3 child timeline, installed before guard enrollment.
 * Mutations run on the player's application looper. Their callback is a child
 * timeline ACK, never output presentation or delegated reader closure.
 * The captured output controller must revoke/flush its exact enrollment; a
 * posted player stop alone does not satisfy that boundary. Live wiring is inert.
 */
@androidx.media3.common.util.UnstableApi
internal class NCContinuousMuxedTimeline(
  private val source:ConcatenatingMediaSource,private val handler:Handler,
  private val isCurrent:()->Boolean,
  private val mediaSource:(NCContinuousMuxedQueue.Child)->MediaSource,
  private val registerIdentity:(NCContinuousMuxedQueue.Child)->Unit,
  private val revokeOutput:()->Unit,
  private val sealTail:((Boolean)->Unit)->Boolean,
  private val orderedRunRevision:Long?=null,
  private val protectedPeriodMediaIds:()->Set<String>?={null}
):NCContinuousMuxedQueue.Timeline {
  private val rows=mutableListOf<NCContinuousMuxedQueue.Child>()
  private val usedKeys=mutableSetOf<NCContinuousMuxedClipKey>()
  private val usedIds=mutableSetOf<String>()
  private var nextOrderedOrdinal=0L
  @Volatile private var busy=false
  private var attached=true
  private fun available()=Looper.myLooper()===handler.looper && attached && !busy && isCurrent()
  override fun pruneLimitOrdinal():Long {
    if(!available())return 0
    val protected=protectedPeriodMediaIds()?:return 0
    if(protected.isEmpty())return 0
    val active=rows.filter{it.mediaId in protected}
    if(active.map{it.mediaId}.toSet()!=protected)return 0
    return active.minOf{it.key.ordinal}
  }
  private fun mutation(effect:(Runnable)->Unit,commit:()->Unit,accepted:()->Boolean,done:(Boolean)->Unit):Boolean {
    busy=true
    var called=false
    // An exception before a real callback leaves the mutation ambiguous and
    // the adapter unavailable. Queue ownership cannot be released on a guess.
    effect(Runnable {
      if(called)return@Runnable
      called=true;busy=false;commit();done(accepted())
    })
    return true
  }
  override fun append(children:List<NCContinuousMuxedQueue.Child>,done:(Boolean)->Unit):Boolean {
    if(!available() || children.isEmpty() || children.size>6
      || orderedRunRevision!=null && (children.first().key.ordinal!=nextOrderedOrdinal
        ||children.any{it.key.ordinal !in 0..9007199254740991L ||it.mediaId!="nc-ordered-$orderedRunRevision-${it.key.ordinal}"})
      || children.map {it.key}.toSet().size!=children.size || children.map {it.mediaId}.toSet().size!=children.size
      || children.any {it.key in usedKeys || it.mediaId.isBlank() || it.mediaId in usedIds}
      || children.zipWithNext().any {(a,b)->b.key.ordinal!=a.key.ordinal+1}
      || rows.lastOrNull()?.let {children.first().key.ordinal!=it.key.ordinal+1}==true)return false
    val copied=children.toList()
    // Injected registration/construction callbacks are synchronous and have
    // no nonreentrancy contract. Latch before invoking either; a throw stays
    // ambiguous/unavailable just like a failed timeline scheduling operation.
    busy=true
    // Register before decoder exposure, using the very same native child key.
    val sources=copied.map {registerIdentity(it);mediaSource(it)}
    copied.forEach {usedKeys+=it.key;usedIds+=it.mediaId}
    if(orderedRunRevision!=null)nextOrderedOrdinal=copied.last().key.ordinal+1
    return mutation({callback->source.addMediaSources(sources,handler,callback)},
      {rows+=copied},{attached && isCurrent()},done)
  }
  override fun remove(keys:List<NCContinuousMuxedClipKey>,done:(Boolean)->Unit):Boolean {
    if(!available() || keys.isEmpty() || keys.size>rows.size || rows.take(keys.size).map {it.key}!=keys)return false
    return mutation({callback->source.removeMediaSourceRange(0,keys.size,handler,callback)},
      {repeat(keys.size){val row=rows.removeAt(0)
        if(orderedRunRevision!=null){usedKeys.remove(row.key);usedIds.remove(row.mediaId)}
      }},{attached && isCurrent()},done)
  }
  override fun seal(done:(Boolean)->Unit):Boolean {
    if(!available() || rows.isEmpty())return false
    busy=true
    val called=java.util.concurrent.atomic.AtomicBoolean(false)
    val scheduled=sealTail {accepted->
      if(called.compareAndSet(false,true)) {
        val finished=java.util.concurrent.atomic.AtomicBoolean(false)
        val finish={if(finished.compareAndSet(false,true)){busy=false;done(accepted && attached && isCurrent())}}
        if(Looper.myLooper()===handler.looper)finish()
        else {
          val posted=try {handler.post {finish()}}catch(_:RuntimeException){false}
          if(!posted && finished.compareAndSet(false,true)){busy=false;revokeOutput();done(false)}
        }
      }
    }
    if(!scheduled && !called.get())busy=false
    return scheduled || called.get()
  }
  override fun detach(done:(Boolean)->Unit):Boolean {
    if(Looper.myLooper()!==handler.looper || !attached || busy)return false
    // Clear only this captured concat, even if an external owner replaced the
    // player. The outer player/session generation is deliberately untouched.
    attached=false
    return mutation({callback->source.clear(handler,callback)},
      {rows.clear();if(orderedRunRevision!=null){usedKeys.clear();usedIds.clear()}},{true},done)
  }
  override fun stopAndFlush()=revokeOutput()
}
