package expo.modules.audio

/** Exact version-1 Desktop metadata. It describes order, never authorizes output. */
internal data class NCOrderedOutputChunk(val streamId:String,val generation:Long,val ordinal:Long,
  val predecessor:Long?,val kind:String,val sourceId:String,val sourceRange:SourceRange,
  val mediaId:String,val frameCount:Int,val fps:Int,val sampleCount:Int,val replyId:String?,
  val sequenceIndex:Long?,val sha256:String,val byteLength:Long) {
  data class Frame(val sourceId:String,val frame:Long,val sourceFrameCount:Long) {
    init {require(identity(sourceId) &&sourceFrameCount in 1..SAFE &&frame in 0 until sourceFrameCount)}
  }
  class SourceRange(val start:Long,val totalFrames:Long,frames:List<Frame>) {
    val frames:List<Frame> = java.util.Collections.unmodifiableList(frames.toList())
    val end get()=start+this.frames.size
    init {require(totalFrames in 1..SAFE &&start in 0 until totalFrames &&frames.size in 1..12
      &&frames.size.toLong()==minOf(12L,totalFrames-start))}
    override fun equals(other:Any?)=other is SourceRange &&start==other.start
      &&totalFrames==other.totalFrames &&frames==other.frames
    override fun hashCode()=31*(31*start.hashCode()+totalFrames.hashCode())+frames.hashCode()
  }
  init {
    require(streamId.matches(Regex("[a-f0-9]{32}")) &&generation in 0..SAFE &&ordinal in 0..SAFE
      &&predecessor==(if(ordinal==0L)null else ordinal-1) &&kind in listOf("idle","transition","speech")
      &&identity(sourceId) &&mediaId.matches(Regex("[a-f0-9]{32}")) &&frameCount in 1..12
      &&frameCount==sourceRange.frames.size &&fps==24 &&sampleCount in 1..25999
      &&sha256.matches(Regex("[a-f0-9]{64}")) &&byteLength in 1..16L*1024*1024)
    if(kind=="speech")require(replyId!=null &&identity(replyId) &&sequenceIndex!=null
      &&sequenceIndex in 0..SAFE &&kotlin.math.abs(sampleCount-frameCount*2000)<2000
      &&(sourceRange.end==sourceRange.totalFrames ||sampleCount==frameCount*2000))
    else require(replyId==null &&sequenceIndex==null &&sampleCount==frameCount*2000)
  }
  companion object {
    private const val SAFE=9007199254740991L
    private fun identity(value:String)=value.matches(Regex("[A-Za-z0-9_-]{1,160}"))
  }
}

/** Bounded native mutation/ownership model, not output permission or receipts.
 * Queue integration commits this only after the actual timeline ACK. Removed
 * children retain their capacity until delegated reader closure is confirmed.
 */
internal class NCContinuousMuxedQueueState(val runRevision:Long,
  private val maxRanges:Int=60,private val maxBytes:Long=128L*1024*1024,
  internal val desktopOrdered:Boolean=false) {
  enum class State {OPEN,SEALED,DRAINED,RETIRED,INVALIDATED,FAILED}
  enum class Outcome {COMMITTED,REJECTED_BEFORE_MUTATION,FAILED_CLOSED}
  enum class StageStatus {STAGED,REJECTED,CAPACITY}
  enum class RangeKind {SPEECH,VISUAL}
  data class StageResult(val status:StageStatus,val token:Token?=null) {
    init {require((status==StageStatus.STAGED)==(token!=null))}
  }
  data class Range(val key:NCContinuousMuxedClipKey,val totalRanges:Int,val bytes:Long,
    val kind:RangeKind=RangeKind.SPEECH)
  data class Tail(val sourceHandle:String,val lastRange:Int,val ordinal:Long)
  data class Ack(val runRevision:Long,val mutationRevision:Long,val tail:Tail?,val outcome:Outcome)
  data class Snapshot(val runRevision:Long,val mutationRevision:Long,val state:State,val tail:Tail?,
    val liveRanges:Int,val liveBytes:Long,val pendingStages:Int,val failure:String?,val speechTail:Tail?,
    val retainedVisualRanges:Int,val orderedReadersClosedThrough:Long?=null)
  class Token private constructor(internal val runRevision:Long,internal val ranges:List<Range>,
    internal val returnParent:Tail?) {
    internal var grantClaimed=false
    companion object {internal fun create(run:Long,rows:List<Range>,parent:Tail?)=Token(run,rows.toList(),parent)}
  }
  private data class Child(val range:Range,var removed:Boolean=false,var readersClosed:Boolean=false)
  private val stages=mutableSetOf<Token>()
  private val children=linkedMapOf<Long,Child>()
  private val layouts=linkedMapOf<String,Int>()
  private val orderedKinds=linkedMapOf<String,RangeKind>()
  private val admittedSources=mutableSetOf<String>()
  private var state=State.OPEN
  private var revision=0L
  private var tail:Tail?=null
  private var speechTail:Tail?=null
  private var visualSource:String?=null
  private var visualFirstOrdinal:Long?=null
  private var failure:String?=null
  private var orderedReadersClosedThrough=-1L
  init {require(runRevision>0 && maxRanges in 1..60 && maxBytes in 1..128L*1024*1024)}

  private fun ownedRows()=children.values.filter {!it.readersClosed}.map {it.range}+stages.flatMap {it.ranges}
  private fun validNext(rows:List<Range>,returnParent:Tail?=null):Boolean {
    if(desktopOrdered)return returnParent==null &&validOrderedNext(rows)
    if(rows.size !in 1..6)return false
    val source=rows.first().key.sourceHandle
    val total=rows.first().totalRanges
    val kind=rows.first().kind
    if(source.isBlank()||source.length>128
      ||(if(kind==RangeKind.SPEECH)total !in 1..60 else total!=0)
      ||rows.any {it.key.sourceHandle!=source||it.totalRanges!=total||it.kind!=kind||it.bytes !in 1..16L*1024*1024})return false
    val prior=tail
    val continuing=prior?.sourceHandle==source
    if(kind==RangeKind.VISUAL) {
      if(continuing) {
        if(visualSource!=source || returnParent!=null)return false
      } else if(returnParent==null || visualSource!=null || prior!=returnParent
        ||source in layouts || prior.lastRange!=layouts[prior.sourceHandle]?.minus(1)
        ||rows.size<2)return false
    } else {
      if(visualSource!=null || returnParent!=null)return false
      if(!continuing && (source in layouts || layouts.size>=64
        ||prior?.let {it.lastRange!=layouts[it.sourceHandle]!!-1}==true
        ||rows.size<minOf(2,total)))return false
      if(continuing && layouts[source]!=total)return false
    }
    if(continuing && prior!!.lastRange==Int.MAX_VALUE)return false
    val first=if(continuing)prior!!.lastRange+1 else 0
    val ordinal=prior?.let {if(it.ordinal==Long.MAX_VALUE)return false;it.ordinal+1}?:0
    if(first.toLong()+rows.size>Int.MAX_VALUE.toLong()+1)return false
    if(kind==RangeKind.SPEECH && first.toLong()+rows.size>total)return false
    if(ordinal>Long.MAX_VALUE-(rows.size-1))return false
    return rows.withIndex().all {(offset,row)->
      row.key.rangeIndex==first+offset && row.key.ordinal==ordinal+offset
        && row.key.ordinal>=0 && row.key.ordinal !in children}
  }
  /** Desktop fixes frame order. Native still checks contiguous immutable source
   * ranges and global ordinals; this model confers no speech/output permission.
   * Ordered visuals are finite sources, not a special final-speech tail. */
  private fun validOrderedNext(rows:List<Range>):Boolean {
    if(rows.size !in 1..6)return false
    val first=rows.first();val source=first.key.sourceHandle;val prior=tail
    if(source.isBlank() ||source.length>128 ||first.totalRanges !in 1..60
      ||rows.any{it.key.sourceHandle!=source ||it.totalRanges!=first.totalRanges
        ||it.kind!=first.kind ||it.bytes !in 1..16L*1024*1024})return false
    val continuing=prior?.sourceHandle==source
    if(continuing) {
      if(layouts[source]!=first.totalRanges ||orderedKinds[source]!=first.kind)return false
    } else if(source in layouts ||layouts.size>=64
      ||prior?.let{it.lastRange!=layouts[it.sourceHandle]?.minus(1)}==true)return false
    val index=if(continuing)prior!!.lastRange+1 else 0
    val ordinal=prior?.ordinal?.plus(1)?:0L
    if(index+rows.size>first.totalRanges ||ordinal>9007199254740991L-(rows.size-1))return false
    return rows.withIndex().all{(offset,row)->row.key.rangeIndex==index+offset
      &&row.key.ordinal==ordinal+offset &&row.key.ordinal !in children}
  }
  fun stage(rows:List<Range>,expectedRun:Long,expectedMutation:Long):Token? =
    stageResult(rows,expectedRun,expectedMutation).token
  @Synchronized fun stageResult(rows:List<Range>,expectedRun:Long,expectedMutation:Long):StageResult {
    if(state!=State.OPEN||expectedRun!=runRevision||expectedMutation!=revision||!validNext(rows))return StageResult(StageStatus.REJECTED)
    return reserve(rows,null)
  }
  /** Visual prefix reservation only. Authority must separately validate finality,
   * metadata and output permission before the concrete timeline may expose it.
   */
  @Synchronized fun stageReturn(rows:List<Range>,expectedRun:Long,expectedSpeechTail:Tail,expectedMutation:Long):StageResult {
    if(desktopOrdered ||state!=State.OPEN || expectedRun!=runRevision ||expectedMutation!=revision || stages.isNotEmpty()
      ||rows.firstOrNull()?.kind!=RangeKind.VISUAL ||!validNext(rows,expectedSpeechTail))
      return StageResult(StageStatus.REJECTED)
    return reserve(rows,expectedSpeechTail)
  }
  private fun reserve(rows:List<Range>,parent:Tail?):StageResult {
    val current=ownedRows()
    if(current.any {old->rows.any {it.key.ordinal==old.key.ordinal}})return StageResult(StageStatus.REJECTED)
    if(current.size+rows.size>maxRanges || rows.sumOf {it.bytes}>maxBytes-current.sumOf {it.bytes})return StageResult(StageStatus.CAPACITY)
    return StageResult(StageStatus.STAGED,Token.create(runRevision,rows,parent).also {stages+=it})
  }
  private fun ack(outcome:Outcome)=Ack(runRevision,revision,tail,outcome)
  @Synchronized fun commit(token:Token,expectedMutation:Long):Ack {
    if(token !in stages)return ack(Outcome.REJECTED_BEFORE_MUTATION)
    // The concrete queue owns the token's files until this exact ACK is known.
    stages-=token
    if(state!=State.OPEN||token.runRevision!=runRevision||expectedMutation!=revision||!validNext(token.ranges,token.returnParent))
      return ack(Outcome.REJECTED_BEFORE_MUTATION)
    if(revision==Long.MAX_VALUE){fence("mutation_revision");return ack(Outcome.FAILED_CLOSED)}
    val first=token.ranges.first()
    if(desktopOrdered) {
      layouts.putIfAbsent(first.key.sourceHandle,first.totalRanges)
      orderedKinds.putIfAbsent(first.key.sourceHandle,first.kind)
    } else if(first.kind==RangeKind.SPEECH)layouts.putIfAbsent(first.key.sourceHandle,first.totalRanges)
    else if(token.returnParent!=null) {
      visualSource=first.key.sourceHandle;visualFirstOrdinal=first.key.ordinal
    }
    token.ranges.forEach {children[it.key.ordinal]=Child(it)}
    val last=token.ranges.last().key;tail=Tail(last.sourceHandle,last.rangeIndex,last.ordinal);revision++
    if(first.kind==RangeKind.SPEECH)speechTail=tail
    return ack(Outcome.COMMITTED)
  }
  @Synchronized fun claimReservation(token:Token):Boolean {
    if(token !in stages || token.grantClaimed || token.runRevision!=runRevision || state!=State.OPEN)return false
    token.grantClaimed=true;admittedSources+=token.ranges.first().key.sourceHandle;return true
  }
  /** Queue-owned unopened children are retired/checked inside this reservation
   * lock so a source grant cannot race the discard. No authority/guard reentry.
   */
  @Synchronized fun drop(token:Token,beforeRelease:()->Boolean={true}):Boolean {
    if(token !in stages || token.grantClaimed || !beforeRelease())return false
    return stages.remove(token)
  }
  @Synchronized internal fun releaseDetachedReservation(token:Token):Boolean =
    state==State.FAILED && stages.remove(token)
  /** Native authority reads actual reservations/ACKed layout, never caller
   * Boolean readiness. Removed readers stay owned until confirmed closure.
   */
  @Synchronized fun reservation(token:Token):List<Range>? = token.ranges.toList().takeIf {
    token in stages && token.runRevision==runRevision && state==State.OPEN
  }
  @Synchronized fun installed(key:NCContinuousMuxedClipKey):Boolean =
    children[key.ordinal]?.let {it.range.key==key}==true
  @Synchronized internal fun outputKeys():Set<NCContinuousMuxedClipKey> = children.values
    .filter {!it.removed && !it.readersClosed}.map {it.range.key}.toSet()
  @Synchronized fun layoutInstalled(source:String,totalRanges:Int):Boolean =
    layouts[source]==totalRanges && (0 until totalRanges).all {index ->
      children.values.any {it.range.key.sourceHandle==source && it.range.key.rangeIndex==index}
    }
  @Synchronized fun sourceReadersClosed(source:String):Boolean = (source in layouts || source in admittedSources ||source==visualSource)
    && (source!=visualSource ||state!=State.OPEN)
    && (!desktopOrdered ||state!=State.OPEN ||layouts[source]?.let{layoutInstalled(source,it)}==true)
    && stages.none {token->token.ranges.any {it.key.sourceHandle==source}}
    && children.values.filter {it.range.key.sourceHandle==source}.all {it.readersClosed}
  @Synchronized fun canSeal(expectedTail:Tail,expectedMutation:Long):Boolean {
    val current=tail?:return false
    return state==State.OPEN && expectedMutation==revision && current==expectedTail && stages.none {it.grantClaimed}
      && (current.sourceHandle==visualSource ||current.lastRange==layouts[current.sourceHandle]!!-1)
  }
  @Synchronized fun seal(expectedTail:Tail,expectedMutation:Long):Ack {
    if(!canSeal(expectedTail,expectedMutation))return ack(Outcome.REJECTED_BEFORE_MUTATION)
    if(revision==Long.MAX_VALUE){fence("mutation_revision");return ack(Outcome.FAILED_CLOSED)}
    state=State.SEALED;revision++;return ack(Outcome.COMMITTED)
  }
  @Synchronized fun prune(beforeOrdinal:Long,expectedMutation:Long,
    protected:NCContinuousMuxedProtectedCursors):List<NCContinuousMuxedClipKey>? {
    if(state !in listOf(State.OPEN,State.SEALED)||expectedMutation!=revision||beforeOrdinal<0
      ||!protected.known||protected.runRevision!=runRevision||protected.sinkEpoch<=0)return null
    val keys=protected.playing+protected.reading+protected.output
    if(keys.any {key->children[key.ordinal]?.let {it.range.key!=key||it.removed||it.readersClosed}!=false})return null
    val cutoff=minOf(beforeOrdinal,keys.minOfOrNull {it.ordinal}?:Long.MAX_VALUE)
    val retiring=children.values.filter {!it.removed&&!it.readersClosed&&it.range.key.ordinal<cutoff}
    if(retiring.isEmpty())return emptyList()
    if(revision==Long.MAX_VALUE){fence("mutation_revision");return null}
    retiring.forEach {it.removed=true};revision++
    return retiring.map {it.range.key}
  }
  @Synchronized fun confirmReaderClosure(keys:List<NCContinuousMuxedClipKey>):Boolean {
    if(keys.toSet().size!=keys.size||keys.any {key->
      val child=children[key.ordinal]
      if(child!=null)child.range.key!=key ||!child.removed
      else {
        // Continuous indices make a released visual key reconcilable without
        // storing an ever-growing tombstone per clip. Unknown/future keys fail.
        val base=visualFirstOrdinal;val last=tail
        base==null ||last==null ||key.sourceHandle!=visualSource ||last.sourceHandle!=visualSource
          ||key.rangeIndex<0 ||key.ordinal<base ||key.ordinal>last.ordinal
          ||key.ordinal-base!=key.rangeIndex.toLong()
      }
    })return false
    keys.forEach {key->
      val child=children[key.ordinal]?:return@forEach
      child.readersClosed=true
      // Speech retains its finite-layout history. A rolling visual epoch keeps
      // only live/unclosed children; the immutable tail preserves append order.
      if(!desktopOrdered &&child.range.kind==RangeKind.VISUAL)children.remove(key.ordinal)
    }
    if(desktopOrdered)while(orderedReadersClosedThrough<Long.MAX_VALUE
      &&children[orderedReadersClosedThrough+1]?.readersClosed==true)orderedReadersClosedThrough++
    return true
  }
  /** Native authority calls this only after reconciling reader-closure receipts.
   * Keep the current tail source so its immutable predecessor cannot be lost. */
  @Synchronized internal fun releaseOrderedSource(source:String):Boolean {
    if(!desktopOrdered ||source==tail?.sourceHandle ||!sourceReadersClosed(source))return false
    if(children.values.any {it.range.key.sourceHandle==source &&it.range.key.ordinal>orderedReadersClosedThrough})return false
    children.entries.removeAll{it.value.range.key.sourceHandle==source}
    layouts.remove(source);orderedKinds.remove(source);admittedSources.remove(source)
    return true
  }
  @Synchronized fun markDetached():List<NCContinuousMuxedClipKey> {
    if(state !in listOf(State.INVALIDATED,State.FAILED,State.DRAINED))return emptyList()
    return children.values.filter {!it.readersClosed}.map {it.removed=true;it.range.key}
  }
  /** Native authority invokes this only after actual sealed timeline END and
   * all source natural-completion proofs have committed to the guard ledger.
   */
  @Synchronized internal fun markDrained(expectedTail:Tail,expectedMutation:Long,commit:()->Boolean={true}):Boolean {
    if(state!=State.SEALED || tail!=expectedTail || revision!=expectedMutation || stages.isNotEmpty())return false
    if(!commit())return false
    state=State.DRAINED;return true
  }
  @Synchronized fun finishRetirement():Boolean {
    if(state !in listOf(State.INVALIDATED,State.FAILED,State.DRAINED)||stages.isNotEmpty()
      ||children.values.any {!it.readersClosed})return false
    state=State.RETIRED;return true
  }
  @Synchronized fun fence(cause:String) {
    if(state==State.RETIRED)return
    state=State.FAILED;if(failure==null)failure=cause
  }
  @Synchronized fun snapshot():Snapshot {
    val live=ownedRows();return Snapshot(runRevision,revision,state,tail,live.size,live.sumOf {it.bytes},stages.size,failure,speechTail,
      children.values.count {it.range.kind==RangeKind.VISUAL},if(desktopOrdered)orderedReadersClosedThrough else null)
  }
}
