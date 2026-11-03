package expo.modules.audio

import androidx.media3.common.Format
import androidx.media3.exoplayer.source.MediaSource
import java.nio.ByteBuffer

/** Provenance for handleBuffer's position delta. Repeated PTS is legitimate
 * only while the very same partially consumed buffer remains outstanding.
 */
internal class NCContinuousMuxedBufferProgress {
  internal data class Stamp(val buffer:ByteBuffer,val token:Long,val pts:Long,val position:Int,val limit:Int)
  private var outstanding:Stamp?=null
  private var lastToken:Long?=null
  private var lastPts:Long?=null
  private var valid=true
  fun begin(buffer:ByteBuffer,token:Long,pts:Long):Stamp? {
    if(!valid)return null
    val prior=outstanding
    if(prior!=null && (prior.buffer!==buffer || prior.token!=token || prior.pts!=pts
      || prior.limit!=buffer.limit() || prior.position!=buffer.position())
      || prior==null && lastToken==token && lastPts?.let {pts<=it}==true) {
      valid=false;return null
    }
    return Stamp(buffer,token,pts,buffer.position(),buffer.limit()).also {outstanding=it}
  }
  fun finish(stamp:Stamp,buffer:ByteBuffer):Int? {
    if(!valid || outstanding!==stamp || buffer!==stamp.buffer || buffer.limit()!=stamp.limit
      || buffer.position()<stamp.position) {valid=false;return null}
    val consumed=buffer.position()-stamp.position
    lastToken=stamp.token;lastPts=stamp.pts
    outstanding=if(buffer.hasRemaining())stamp.copy(position=buffer.position()) else null
    return consumed
  }
}

internal data class NCContinuousMuxedClipKey(val sourceHandle:String, val rangeIndex:Int, val ordinal:Long)

/** Observed codec-surface frames, never audio receipts or permission. Releases
 * merely become pending: Android can delay/batch or omit rendered callbacks.
 * Missing callbacks therefore cannot be replaced by release time/audio position.
 */
internal class NCOrderedVideoEvidence {
  @Volatile internal var onChanged:(()->Unit)?=null
  private data class Frame(val key:NCContinuousMuxedClipKey,val offset:Int)
  private val pending=linkedMapOf<Any,Frame>()
  private var last:Frame?=null
  private var lastNanos:Long?=null
  private var ambiguousTime=false
  private var failure:String?=null
  private var rejectedFrame:Map<String,Any?> = emptyMap()
  private var sealed:Map<String,Any>?=null
  @Synchronized fun submitted(key:NCContinuousMuxedClipKey,pts:Long,duration:Long):Any? {
    if(sealed!=null ||failure!=null)return null
    if(pending.size>=64){unavailable("render_callback_capacity");return null}
    // Exact 24fps lattice, allowing only the encoder's integer-us rounding.
    val frame=if(pts in 0..499999)(pts*24+500000)/1000000 else -1
    if(frame !in 0..11 ||duration !in 41666..500000 ||pts>=duration
      ||kotlin.math.abs(pts-frame*1000000/24)>1 ||key.ordinal !in 0..9007199254740991L) {
      rejectedFrame=mapOf("rejected_pts_us" to pts,"rejected_duration_us" to duration,
        "rejected_frame_offset" to frame,"rejected_ordinal" to key.ordinal)
      unavailable("frame_pts_unmapped");return null
    }
    return Any().also {pending[it]=Frame(key,frame.toInt())}
  }
  @Synchronized fun rendered(token:Any,nanos:Long) {
    if(sealed!=null ||failure!=null)return
    val frame=pending.remove(token)
    if(frame==null){unavailable("render_callback_unmapped");return}
    val previous=lastNanos
    // Batched codec callbacks may share render time. Do not choose between
    // tied frames, but do not poison future independently observed frames.
    // Structural provenance failures still use the terminal failure path.
    if(previous==nanos &&frame!=last){ambiguousTime=true;return}
    if(previous==null ||nanos>previous){last=frame;lastNanos=nanos;ambiguousTime=false;onChanged?.invoke()}
  }
  @Synchronized fun unavailable(reason:String) {
    if(sealed!=null)return
    if(failure==null)failure=reason
    pending.clear()
  }
  @Synchronized internal fun rejectionEvidence():Map<String,Any?> = rejectedFrame.toMap()
  @Synchronized fun snapshot():Map<String,Any> {
    sealed?.let{return it}
    val reason=failure?:if(ambiguousTime)"render_callback_ambiguous" else if(pending.isNotEmpty())"render_callback_pending" else if(last==null)"no_rendered_frame" else null
    return if(reason!=null)mapOf("known" to false,"reason" to reason)
      else mapOf("known" to true,"ordinal" to last!!.key.ordinal,"frameOffset" to last!!.offset,"provenance" to "codec_surface")
  }
  // Only a presently exact witness needs a retained descriptor. Missing callback
  // evidence must not pin old ordinals forever and stall ordinary playback.
  @Synchronized fun protectedKeys():Set<NCContinuousMuxedClipKey> =
    if(failure==null &&!ambiguousTime &&pending.isEmpty())setOfNotNull(last?.key) else emptySet()
  @Synchronized fun forgotten(keys:Set<NCContinuousMuxedClipKey>) {
    if(pending.values.any{it.key in keys} ||last?.key in keys)unavailable("render_source_released")
  }
  /** Call only after native output is fenced and physical stop has settled. */
  @Synchronized fun seal():Map<String,Any> = sealed?:snapshot().also{sealed=it}
}
internal data class NCContinuousMuxedProtectedCursors(
  val runRevision:Long, val sinkEpoch:Long, val known:Boolean,
  val playing:Set<NCContinuousMuxedClipKey>, val reading:Set<NCContinuousMuxedClipKey>,
  val output:Set<NCContinuousMuxedClipKey>
)
internal data class NCContinuousMuxedPresentationEvidence(
  val sourceHandle:String, val sinkEpoch:Long, val presentedSamples:Long,
  val started:Boolean, val naturalEnd:Boolean
)

/** Diagnostic grouping of already validated complete fixture clips. No file,
 * authority or receipt state; the whole-source guard retains output ownership.
 */
internal object NCContinuousMuxedFixtureLayout {
  data class Group(val firstRange:Int,val rangeCount:Int,val plan:NCMuxedTrialStreamRanges.Plan)
  fun split(counts:List<Int>,frames:List<Int>,samples:List<Int>):List<Group> {
    require(counts.size in 2..64 && counts.all {it in 1..60}
      && frames.size in 2..60 && samples.size==frames.size && counts.sum()==frames.size
      && frames.all {it in 1..12} && frames.dropLast(1).all {it==12})
    var first=0
    return counts.map {count ->
      val begin=first;first+=count
      val part=frames.subList(begin,first)
      val valid=samples.subList(begin,first)
      require(valid.all {it>0} && valid.dropLast(1).all {it==24000}
        && kotlin.math.abs(valid.last()-part.last()*2000)<2000)
      Group(begin,count,NCMuxedTrialStreamRanges.Plan(part.sum(),valid.sumOf {it.toLong()}))
    }
  }
}

/** A raw unsigned AudioTrack counter, not a clock extrapolated from wall time. */
internal class NCContinuousMuxedHeadCounter {
  private var previous:Long?=null
  private var wraps=0L
  private var valid=true
  fun observe(raw:Long):Long? {
    if (!valid || raw !in 0..0xffffffffL) {valid=false;return null}
    previous?.let { old ->
      if (raw<old) {
        if (old>=0xf0000000L && raw<=0x0fffffffL) wraps++
        else {valid=false;return null}
      }
    }
    previous=raw
    return wraps*0x100000000L+raw
  }
}

/** Shadow evidence only. Registration/enqueue/decoder read-ahead never grants
 * output permission or publishes an authoritative playback receipt.
 * All entry points are synchronized because renderer and query threads differ.
 */
internal class NCContinuousMuxedPresentation(private val runRevision:Long=1L,
  internal val desktopOrdered:Boolean=false) {
  internal val renderedVideo=if(desktopOrdered)NCOrderedVideoEvidence() else null
  /** Native provider-origin identity, never a wire nonce or epoch assertion.
   * Only the provider observation creates it, before any track-origin evidence.
   * Actual is platform-opaque here so the pure mapping stays OS-independent.
   */
  class NativeTrackCapture private constructor(private val model:NCContinuousMuxedPresentation,
    private val observer:Any,private val sink:Any,internal val actual:Any,val sinkEpoch:Long) {
    internal fun belongsTo(expected:NCContinuousMuxedPresentation)=model===expected
    internal fun matchesContext(observer:Any,sink:Any,actual:Any,epoch:Long)=
      this.observer===observer && this.sink===sink && this.actual===actual && sinkEpoch==epoch
    companion object {
      internal fun create(model:NCContinuousMuxedPresentation,observer:Any,sink:Any,actual:Any,epoch:Long)=
        NativeTrackCapture(model,observer,sink,actual,epoch)
    }
  }
  /** Native model-origin capabilities, not output grants. Task 2 must also
   * match the live descriptor, grant, guarded output and installation ledger.
   * No JS snapshot or caller-supplied sample count can construct one.
   */
  class SourceStartProof private constructor(private val origin:NCContinuousMuxedPresentation,
    val sourceHandle:String,val runRevision:Long,val sinkEpoch:Long,val presentedSamples:Long) {
    fun matches(model:NCContinuousMuxedPresentation,handle:String,run:Long,epoch:Long):Boolean =
      model===origin && handle==sourceHandle && run==runRevision && epoch==sinkEpoch
        && origin.proofCurrent(handle,run,epoch,presentedSamples,false)
    companion object {
      internal fun observe(origin:NCContinuousMuxedPresentation,handle:String,run:Long,epoch:Long):SourceStartProof? =
        synchronized(origin) {
          val samples=origin.proofSamples(handle,run,epoch,false) ?: return@synchronized null
          SourceStartProof(origin,handle,run,epoch,samples)
        }
    }
  }
  class SourceNaturalCompletionProof private constructor(private val origin:NCContinuousMuxedPresentation,
    val sourceHandle:String,val runRevision:Long,val sinkEpoch:Long,val presentedSamples:Long) {
    fun matches(model:NCContinuousMuxedPresentation,handle:String,run:Long,epoch:Long):Boolean =
      model===origin && handle==sourceHandle && run==runRevision && epoch==sinkEpoch
        && origin.proofCurrent(handle,run,epoch,presentedSamples,true)
    companion object {
      internal fun observe(origin:NCContinuousMuxedPresentation,handle:String,run:Long,epoch:Long):SourceNaturalCompletionProof? =
        synchronized(origin) {
          val samples=origin.proofSamples(handle,run,epoch,true) ?: return@synchronized null
          SourceNaturalCompletionProof(origin,handle,run,epoch,samples)
        }
    }
  }
  private data class Source(val plan:NCMuxedTrialStreamRanges.Plan,val visual:Boolean=false,val firstOrdinal:Long?=null)
  private data class VisualSource(val handle:String,val parent:NCContinuousMuxedClipKey,
    var nextRange:Int=0,var closedRanges:Int=0,var sealedTail:NCContinuousMuxedClipKey?=null,var trackStart:Long?=null)
  /** Native physical visual watermark only. It cannot enter speech receipts. */
  class VisualStartProof private constructor(private val origin:NCContinuousMuxedPresentation,
    val sourceHandle:String,val runRevision:Long,val sinkEpoch:Long,val presentedSamples:Long) {
    fun matches(model:NCContinuousMuxedPresentation,handle:String,run:Long,sink:Long):Boolean =
      model===origin &&handle==sourceHandle &&run==runRevision &&sink==sinkEpoch
        &&origin.visualProofSamples(handle,run,sink)?.let {it>=presentedSamples &&presentedSamples>0}==true
    companion object {
      internal fun observe(origin:NCContinuousMuxedPresentation,handle:String,run:Long,sink:Long):VisualStartProof? =
        synchronized(origin) {
          val samples=origin.visualProofSamples(handle,run,sink)?:return@synchronized null
          VisualStartProof(origin,handle,run,sink,samples)
        }
    }
  }
  class VisualNaturalCompletionProof private constructor(private val origin:NCContinuousMuxedPresentation,
    val tail:NCContinuousMuxedClipKey,val runRevision:Long,val sinkEpoch:Long,val presentedSamples:Long) {
    fun matches(model:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey,run:Long,sink:Long):Boolean =
      model===origin &&key==tail &&run==runRevision &&sink==sinkEpoch
        &&origin.visualEndSamples(key,run,sink)==presentedSamples
    companion object {
      internal fun observe(origin:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey,run:Long,sink:Long):VisualNaturalCompletionProof? =
        synchronized(origin) {
          val samples=origin.visualEndSamples(key,run,sink)?:return@synchronized null
          VisualNaturalCompletionProof(origin,key,run,sink,samples)
        }
    }
  }
  private data class Range(
    val key:NCContinuousMuxedClipKey, val start:Long, val valid:Long,
    val delay:Int, val padding:Int, val raw:Int,
    var trackStart:Long?=null, var accepted:Long=0, var rawConsumed:Long=0,
    var readEnd:Boolean=false, var formatKnown:Boolean=false, var lastPts:Long?=null,
    var lastQueuedPts:Long?=null, var processedThroughPts:Long?=null
  )
  private data class Input(val token:Long, val key:NCContinuousMuxedClipKey,
    val startUs:Long, val offsetUs:Long, var processed:Boolean=false)
  private val sources=linkedMapOf<String,Source>()
  private var nextOrderedOrdinal=0L
  private var releasedOrderedSamples=0L
  private var releasedOrderedRanges=0
  private var visual:VisualSource?=null
  private val ranges=linkedMapOf<NCContinuousMuxedClipKey,Range>()
  private val inputs=mutableListOf<Input>()
  private var nextToken=1L
  private var processed:Input?=null
  private var known=true
  private var firstFailure=0
  private var epoch=0L
  private var headCounter=NCContinuousMuxedHeadCounter()
  private var timestampCounter=NCContinuousMuxedHeadCounter()
  private var timestampNanos:Long?=null
  private var diagnosticHeadFrames:Long?=null
  private var diagnosticTimestampFrames:Long?=null
  private var presented=0L
  private var accepted=0L
  private var nativeCapture:NativeTrackCapture?=null
  private var videoObserver:Any?=null
  private var videoProtected:Set<NCContinuousMuxedClipKey> = emptySet()
  /** Protection only, not output permission or a receipt. Only this renderer's
   * actual processed-stream change releases its previous decoded origin. */
  @Synchronized internal fun observeVideoProtection(observer:Any,keys:Set<NCContinuousMuxedClipKey>):Boolean {
    if(!known ||videoObserver?.let {it!==observer}==true ||keys.size>60 ||keys.any {it !in ranges})return false
    videoObserver=observer;videoProtected=keys.toSet();return true
  }
  init {require(runRevision in 1..9007199254740991L)}

  @Synchronized internal fun canAttachNativeTrack()=known && epoch==0L && accepted==0L && presented==0L && nativeCapture==null
  @Synchronized internal fun captureNativeTrack(observer:Any,sink:Any,actual:Any,epoch:Long):NativeTrackCapture? {
    nativeCapture?.let {
      if(it.matchesContext(observer,sink,actual,epoch))return it
      fence("track_capture");return null
    }
    if(!canAttachNativeTrack() || epoch !in 1..9007199254740991L)return null
    return NativeTrackCapture.create(this,observer,sink,actual,epoch).also {nativeCapture=it}
  }
  @Synchronized internal fun nativeTrackCapture()=nativeCapture
  @Synchronized internal fun matchesNativeTrack(capture:NativeTrackCapture)=capture===nativeCapture && capture.belongsTo(this)
  @Synchronized internal fun canInitializeCapturedTrack(capture:NativeTrackCapture)=matchesNativeTrack(capture)
    && known && epoch==capture.sinkEpoch && accepted==0L && presented==0L
  @Synchronized internal fun hasRegisteredRange(key:NCContinuousMuxedClipKey)=known && ranges.containsKey(key)
  @Synchronized internal fun orderedSourceIsVisual(handle:String):Boolean? =
    sources[handle]?.visual.takeIf{desktopOrdered &&known}
  /** Duration bound from this exact registered clip's 24fps layout. Native
   * staging checks the actual extracted frame count against this same plan;
   * this is provenance only, never output permission or a presentation receipt. */
  @Synchronized internal fun registeredVideoDurationUs(key:NCContinuousMuxedClipKey):Long? {
    if(!known ||key !in ranges)return null
    val frames=sources[key.sourceHandle]?.let {minOf(12,it.plan.frames-key.rangeIndex*12)}
      ?:visual?.takeIf {it.handle==key.sourceHandle}?.let {12}?:return null
    return if(frames in 1..12)frames*1000000L/24 else null
  }

  @Synchronized fun registerSource(handle:String, plan:NCMuxedTrialStreamRanges.Plan) {
    if (!known) return
    if (desktopOrdered ||handle.isBlank() || sources.containsKey(handle) || sources.size>=64 || visual!=null) {fence("source");return}
    sources[handle]=Source(plan)
  }

  @Synchronized internal fun registerOrderedSource(handle:String,plan:NCMuxedTrialStreamRanges.Plan,
    firstOrdinal:Long,silent:Boolean):Boolean {
    if(!desktopOrdered ||!known ||handle.isBlank() ||handle.length>128 ||handle in sources
      ||sources.size>=64 ||firstOrdinal!=nextOrderedOrdinal
      ||firstOrdinal>9007199254740991L-plan.totalRanges
      ||silent &&plan.samples!=plan.frames*2000L)return false
    sources[handle]=Source(plan,silent,firstOrdinal)
    nextOrderedOrdinal+=plan.totalRanges
    return true
  }

  /** Reader closure is established by Queue before this call. Independently
   * require actual presentation/decoder drain and absence from protected origins.
   * Removing a source cannot manufacture a receipt or reset the physical clock. */
  @Synchronized internal fun forgetClosedOrderedSource(handle:String):Boolean {
    val source=sources[handle]?:return false
    if(!desktopOrdered ||!known ||sourceEvidence(handle)?.naturalEnd!=true)return false
    val owned=ranges.keys.filter{it.sourceHandle==handle}.toSet()
    val protection=protectedCursors()
    if(!protection.known ||(protection.playing+protection.reading+protection.output).any{it in owned})return false
    renderedVideo?.forgotten(owned)
    ranges.keys.removeAll(owned);inputs.removeAll{it.key in owned};sources.remove(handle)
    releasedOrderedSamples+=source.plan.samples;releasedOrderedRanges+=source.plan.totalRanges
    return true
  }

  /** Shadow origin mapping only. Admission/output permission belongs to the
   * separate native visual grant. A visual source never enters speech evidence. */
  @Synchronized fun registerVisualSource(handle:String,parent:NCContinuousMuxedClipKey):Boolean {
    val speech=sources[parent.sourceHandle]?:return false
    if(desktopOrdered ||!known || visual!=null || handle.isBlank() || handle.length>128 || handle in sources
      ||sources.keys.lastOrNull()!=parent.sourceHandle ||parent.rangeIndex!=speech.plan.totalRanges-1
      ||ranges.keys.maxByOrNull {it.ordinal}!=parent
      ||ranges.keys.count {it.sourceHandle==parent.sourceHandle}!=speech.plan.totalRanges)return false
    visual=VisualSource(handle,parent);return true
  }

  /** Queue must first obtain the actual delegated reader closure. This additional
   * origin check refuses any still reading/processed/presenting protected key. */
  @Synchronized fun forgetClosedVisualRange(key:NCContinuousMuxedClipKey):Boolean {
    val epoch=visual?:return false;val row=ranges[key]?:return false
    if(!known ||key.sourceHandle!=epoch.handle ||key.rangeIndex!=epoch.closedRanges
      ||!row.readEnd ||!row.formatKnown ||row.rawConsumed!=row.raw.toLong() ||row.accepted!=row.valid
      ||row.lastQueuedPts?.let {queued->row.processedThroughPts?.let {it>=queued}==true}!=true
      ||row.trackStart?.let {presented>=it+row.valid}!=true)return false
    val protection=protectedCursors()
    if(!protection.known ||key in protection.playing ||key in protection.reading ||key in protection.output)return false
    ranges.remove(key);inputs.removeAll {it.key==key};epoch.closedRanges++;return true
  }

  @Synchronized fun sealVisualTail(key:NCContinuousMuxedClipKey):Boolean {
    val epoch=visual?:return false
    if(!known ||epoch.sealedTail!=null ||key.sourceHandle!=epoch.handle ||key.rangeIndex!=epoch.nextRange-1
      ||ranges.keys.maxByOrNull {it.ordinal}!=key)return false
    epoch.sealedTail=key;return true
  }

  @Synchronized fun registerRange(key:NCContinuousMuxedClipKey, validStartSample:Long,
    validSamples:Long, delaySamples:Int, paddingSamples:Int, rawSamples:Int) {
    if (!known) return
    val source=sources[key.sourceHandle]
    val idle=visual?.takeIf {it.handle==key.sourceHandle}
    val expectedStart=key.rangeIndex*24_000L
    val expected=source?.let {if(key.rangeIndex==it.plan.totalRanges-1)it.plan.samples-expectedStart else 24_000L}
      ?:idle?.let {24000L}
    val layout=if(source!=null)key.rangeIndex in 0 until source.plan.totalRanges
        // Queue caps live/unjoined files at 60. Receipt history remains until
        // whole-source completion and is separately bounded by 64 sources x
        // 60 ranges; treating that history as live capacity blocks a successor
        // after a long source even when its earlier file readers have joined.
        &&(!desktopOrdered ||key.ordinal==source.firstOrdinal!!+key.rangeIndex &&ranges.size<64*60)
      else idle!=null &&idle.sealedTail==null &&key.rangeIndex==idle.nextRange &&key.rangeIndex in 0..10005
        &&idle.nextRange-idle.closedRanges<6 &&key.ordinal==idle.parent.ordinal+1+key.rangeIndex
        &&rawSamples in 1024..28672 &&rawSamples%1024==0
    if (!layout || key.ordinal<0
      || ranges.containsKey(key) || ranges.keys.any {it.ordinal==key.ordinal}
      || ranges.keys.any {it.sourceHandle==key.sourceHandle && it.rangeIndex==key.rangeIndex}
      || validStartSample!=expectedStart || validSamples!=expected || validSamples<=0
      || delaySamples<0 || paddingSamples<0 || rawSamples<=0
      || rawSamples.toLong()!=delaySamples.toLong()+validSamples+paddingSamples) {
      fence("range");return
    }
    ranges[key]=Range(key,validStartSample,validSamples,delaySamples,paddingSamples,rawSamples)
    if(idle!=null)idle.nextRange++
  }

  /** The period and encoded format are native inputs; never accept JS proof. */
  @Synchronized fun recordInputStream(periodId:MediaSource.MediaPeriodId, startUs:Long,
    offsetUs:Long, clipKey:NCContinuousMuxedClipKey, format:Format):Long {
    val range=ranges[clipKey]
    if (periodId.isAd || range==null || format.sampleRate!=48_000 || format.channelCount!=1
      || format.encoderDelay!=range.delay || format.encoderPadding!=range.padding) {
      fence("encoded_format");return -1
    }
    return recordInput(clipKey,startUs,offsetUs)
  }

  @Synchronized fun recordInput(key:NCContinuousMuxedClipKey, startUs:Long, offsetUs:Long):Long {
    if (!known) return -1
    val previous=inputs.lastOrNull()?.key
    val ordered=if(previous==null) key.ordinal==0L && key.rangeIndex==0
      else if(previous.sourceHandle==key.sourceHandle) key.rangeIndex==previous.rangeIndex+1
      else key.rangeIndex==0 && previous.rangeIndex==sources[previous.sourceHandle]?.plan?.totalRanges?.minus(1)
        &&(visual?.handle!=key.sourceHandle ||visual?.parent==previous)
    if (!ranges.containsKey(key) || startUs<0 || inputs.any {it.key==key}
      || !ordered || previous?.ordinal?.let {key.ordinal!=it+1}==true) {
      fence("input");return -1
    }
    val input=Input(nextToken++,key,startUs,offsetUs)
    inputs.add(input)
    return input.token
  }

  @Synchronized fun recordProcessedStream(startUs:Long, offsetUs:Long):Long? {
    if (!known) return null
    val next=inputs.firstOrNull {!it.processed}
    if (next==null || next.startUs!=startUs || next.offsetUs!=offsetUs) {
      fence("processed_identity");return null
    }
    val previous=processed?.let {ranges[it.key]}
    if (previous!=null && (!previous.readEnd || previous.rawConsumed!=previous.raw.toLong())) {
      fence("processed_gap");return null
    }
    next.processed=true
    processed=next
    return next.token
  }
  @Synchronized internal fun processedKey(token:Long):NCContinuousMuxedClipKey? =
    processed?.takeIf {known && it.token==token}?.key
  /** Kind detection remains available after a fence solely to deny submission. */
  @Synchronized internal fun processedVisual(token:Long):Boolean = processed?.let {
    it.token==token &&(it.key.sourceHandle==visual?.handle ||sources[it.key.sourceHandle]?.visual==true)
  }==true
  @Synchronized internal fun visualRawSamples(token:Long,format:Format):Int {
    val input=processed?.takeIf {known &&processedVisual(token)}?:return -1
    val range=ranges[input.key]?:return -1
    if(!range.formatKnown ||format.sampleMimeType!="audio/raw" ||format.sampleRate!=48000 ||format.channelCount!=1
      ||format.pcmEncoding!=androidx.media3.common.C.ENCODING_PCM_16BIT
      ||format.encoderDelay!=range.delay ||format.encoderPadding!=range.padding)return -1
    return range.raw
  }

  /** BaseRenderer initializes at the first stream's renderer-time start, not
   * source-time zero. This permits only an untouched, exact zero-source start.
   * The observation consumes its separate one-shot reset scope.
   */
  @Synchronized fun permitsInitialPositionReset(outputToken:Long?,positionUs:Long):Boolean {
    val first=inputs.firstOrNull() ?: return false
    return known && outputToken!=null && outputToken>0 && processed===first
      && first.token==outputToken && first.key.ordinal==0L && first.key.rangeIndex==0
      && first.startUs==first.offsetUs && positionUs==first.startUs
      && accepted==0L && presented==0L && ranges.values.all {it.rawConsumed==0L}
  }

  /** Passive terminal-marker diagnostic only; never advances presentation. */
  @Synchronized fun diagnosticEndMarkerFrames():Int? {
    if(desktopOrdered)return null // An open stream's last available chunk is not END.
    if(!known || sources.isEmpty() || ranges.isEmpty())return null
    if(visual?.let {it.sealedTail==null ||it.nextRange!=it.closedRanges+ranges.keys.count {key->key.sourceHandle==it.handle}}==true)return null
    if(sources.any {(handle,source)->
      ranges.keys.count {it.sourceHandle==handle}!=source.plan.totalRanges})return null
    val speechRanges=sources.values.sumOf {it.plan.totalRanges}
    val expectedOrdinals=(0 until speechRanges).map {it.toLong()}+
      (visual?.let {idle->(idle.closedRanges until idle.nextRange).map {idle.parent.ordinal+1+it}}?:emptyList())
    if(ranges.keys.map {it.ordinal}.sorted()!=expectedOrdinals)return null
    val frames=sources.values.sumOf {it.plan.samples}+(visual?.nextRange?:0)*24000L
    return if(frames in 1..Int.MAX_VALUE.toLong())frames.toInt() else null
  }

  /** Final-wait input eligibility only. The sink may still retain unwritten PCM;
   * accepting every raw sample is not an output or presentation guarantee.
   */
  @Synchronized fun terminalInputAccepted():Boolean {
    val endpoint=diagnosticEndMarkerFrames() ?: return false
    return epoch>0 && inputs.size==ranges.size && processed===inputs.lastOrNull()
      && accepted==endpoint.toLong() && ranges.values.all {
        it.formatKnown && it.rawConsumed==it.raw.toLong() && it.accepted==it.valid
      }
  }

  /** Native-only immutable accepted tail. The prefix is the valid one-to-one
   * track span at its first positive raw consumption, never a media offset or
   * sampled head. A sink must additionally bind the actual per-range configure
   * and first consumed PCM PTS before using this for retained output. */
  internal data class AcceptedTail(val token:Long,val key:NCContinuousMuxedClipKey,
    val sinkEpoch:Long,val validSamples:Long,val validPrefix:Long,val delay:Int,val padding:Int) {
    internal fun retryPts(firstPcmPtsUs:Long):Long? {
      if(firstPcmPtsUs<0 || validPrefix<0 || validSamples<=0)return null
      val phase=validPrefix%6 // 48kHz's floor clock repeats every six frames.
      if(validSamples>Long.MAX_VALUE-phase || validSamples+phase>Long.MAX_VALUE/1_000_000)return null
      val duration=(validSamples+phase)*1_000_000/48_000-phase*1_000_000/48_000
      return if(firstPcmPtsUs>Long.MAX_VALUE-duration)null else firstPcmPtsUs+duration
    }
  }
  @Synchronized internal fun acceptedTerminalTail(token:Long):AcceptedTail? {
    if(!terminalInputAccepted())return null
    val input=processed?.takeIf {it.token==token}?:return null
    val range=ranges[input.key]?:return null
    val prefix=range.trackStart?:return null
    return AcceptedTail(token,input.key,epoch,range.valid,prefix,range.delay,range.padding)
  }

  @Synchronized fun recordPcmFormat(sampleRate:Int, channels:Int, bytesPerFrame:Int,
    delay:Int, padding:Int, processingSupported:Boolean) {
    if (!known) return
    val range=processed?.let {ranges[it.key]}
    if (range==null || sampleRate!=48_000 || channels!=1 || bytesPerFrame!=2
      || !processingSupported || delay!=range.delay || padding!=range.padding) {
      fence("pcm_format");return
    }
    range.formatKnown=true
  }

  @Synchronized fun recordReadEnd(inputToken:Long, lastQueuedPtsUs:Long) {
    if (!known) return
    val input=inputs.firstOrNull {it.token==inputToken}
    val range=input?.let {ranges[it.key]}
    if (range==null || lastQueuedPtsUs<0 || lastQueuedPtsUs>range.raw*1_000_000L/48_000) {
      fence("read_end");return
    }
    range.readEnd=true
    range.lastQueuedPts=lastQueuedPtsUs
  }

  @Synchronized fun recordProcessedOutput(outputToken:Long, ptsUs:Long) {
    if(!known)return
    val input=processed
    val range=input?.let {ranges[it.key]}
    if(input?.token!=outputToken || range==null || ptsUs<0
      || ptsUs>range.raw*1_000_000L/48_000
      || range.processedThroughPts?.let {ptsUs<it}==true) {fence("processed_pts");return}
    range.processedThroughPts=ptsUs
  }

  @Synchronized fun recordAcceptedOutput(outputToken:Long, ptsUs:Long, consumedPcmBytes:Int,
    decodeOnly:Boolean, lastBuffer:Boolean) {
    if (!known || decodeOnly || consumedPcmBytes==0) return
    val input=processed
    val range=input?.let {ranges[it.key]}
    if (input==null || input.token!=outputToken || range==null || !range.formatKnown
      || epoch==0L || ptsUs<0 || consumedPcmBytes<0 || consumedPcmBytes%2!=0) {
      fence("accepted_identity");return
    }
    val ptsSample=(ptsUs*48_000L+500_000L)/1_000_000L
    if (ptsUs>range.raw*1_000_000L/48_000 || range.lastPts!=ptsUs
      && kotlin.math.abs(ptsSample-range.rawConsumed)>1) {fence("output_pts");return}
    val nextRaw=range.rawConsumed+consumedPcmBytes/2
    if (nextRaw>range.raw) {fence("accepted_span");return}
    if (range.trackStart==null) range.trackStart=accepted
    visual?.takeIf {it.handle==range.key.sourceHandle &&range.key.rangeIndex==0 &&it.trackStart==null}
      ?.trackStart=range.trackStart
    val valid=(nextRaw-range.delay).coerceIn(0,range.valid)
    accepted+=valid-range.accepted
    range.accepted=valid
    range.rawConsumed=nextRaw
    range.lastPts=ptsUs
    // lastBuffer is not output EOS and deliberately cannot complete a source.
  }

  @Synchronized fun recordTrackSample(trackEpoch:Long, rawHeadFrames:Long,
    timestampFrames:Long?, timestampNanos:Long?) {
    if(nativeCapture!=null){fence("track_capture");return}
    recordTrackSampleCore(trackEpoch,rawHeadFrames,timestampFrames,timestampNanos)
  }
  @Synchronized fun recordNativeTrackSample(capture:NativeTrackCapture,rawHeadFrames:Long,
    timestampFrames:Long?,timestampNanos:Long?) {
    if(!matchesNativeTrack(capture)){fence("track_capture");return}
    recordTrackSampleCore(capture.sinkEpoch,rawHeadFrames,timestampFrames,timestampNanos)
  }
  private fun recordTrackSampleCore(trackEpoch:Long,rawHeadFrames:Long,timestampFrames:Long?,timestampNanos:Long?) {
    if (!known) return
    if (trackEpoch<=0 || epoch!=0L && trackEpoch!=epoch) {fence("track_epoch");return}
    if (epoch==0L) {
      if (rawHeadFrames!=0L || accepted!=0L) {fence("track_origin");return}
      epoch=trackEpoch
    }
    val head=headCounter.observe(rawHeadFrames) ?: run {fence("track_head");return}
    diagnosticHeadFrames=head
    diagnosticTimestampFrames=null
    var watermark=head
    if ((timestampFrames==null)!=(timestampNanos==null)) {fence("timestamp");return}
    if (timestampFrames!=null && timestampNanos!=null) {
      if (timestampNanos<0 || this.timestampNanos?.let {timestampNanos<it}==true) {
        fence("timestamp_backwards");return
      }
      val stamped=timestampCounter.observe(timestampFrames) ?: run {fence("timestamp_head");return}
      diagnosticTimestampFrames=stamped
      watermark=minOf(head,stamped)
      this.timestampNanos=timestampNanos
    }
    if (head>accepted) {fence("unaccounted_head");return}
    // A newly available timestamp may describe older output than an earlier
    // head observation. Preserve that proof, but grant no additional progress
    // until the conservative watermark catches up. Both counter regressions
    // and timestamp-clock regressions were independently rejected above.
    presented=maxOf(presented,watermark)
  }

  /** Bounded diagnostic only. Retain the first loss, not later cleanup noise;
   * never expose arbitrary caller strings or turn this into receipt authority.
   */
  @Synchronized fun failureCode():Int=firstFailure
  /** Passive copied measurements only, including when fenced. These fields
   * cannot attest an endpoint, restore mapping or publish any receipt. Head
   * and timestamp are the last real model observations, not fresh polling.
   */
  internal data class TerminalReadiness(val known:Boolean,val declaredSamples:Long,
    val acceptedSamples:Long,val presentedSamples:Long,val totalRanges:Int,val registeredRanges:Int,
    val formatKnownRanges:Int,val rawConsumedRanges:Int,val acceptedRanges:Int,
    val readEndRanges:Int,val processedEndRanges:Int,val lastOrdinal:Long?,val lastRawSamples:Int?,
    val lastValidSamples:Long?,val lastDelaySamples:Int?,val lastPaddingSamples:Int?,
    val lastRawConsumed:Long?,val lastAcceptedSamples:Long?,val lastQueuedPtsUs:Long?,
    val lastProcessedPtsUs:Long?,val headFrames:Long?,val timestampFrames:Long?)
  @Synchronized internal fun terminalReadiness():TerminalReadiness {
    val last=ranges.values.maxByOrNull {it.key.ordinal}
    return TerminalReadiness(known,releasedOrderedSamples+sources.values.sumOf {it.plan.samples}+(visual?.nextRange?:0)*24000L,accepted,presented,
      releasedOrderedRanges+sources.values.sumOf {it.plan.totalRanges}+(visual?.nextRange?:0),ranges.size,ranges.values.count {it.formatKnown},
      ranges.values.count {it.rawConsumed==it.raw.toLong()},ranges.values.count {it.accepted==it.valid},
      ranges.values.count {it.readEnd},ranges.values.count {range->
        range.lastQueuedPts?.let {queued->range.processedThroughPts?.let {it>=queued}==true}==true
      },last?.key?.ordinal,last?.raw,last?.valid,last?.delay,last?.padding,last?.rawConsumed,
      last?.accepted,last?.lastQueuedPts,last?.processedThroughPts,diagnosticHeadFrames,diagnosticTimestampFrames)
  }
  private var invalidation=0L
  @Synchronized internal fun invalidationRevision():Long=invalidation
  @Synchronized fun fence(reason:String) {
    if(invalidation<Long.MAX_VALUE)invalidation++
    if(firstFailure==0)firstFailure=when(reason) {
      "position_reset"->1; "unaccounted_head"->2; "encoded_format"->3
      "pcm_format"->4; "processed_identity"->5; "processed_gap"->6
      "output_context"->7; "period_identity"->8; "track_epoch"->9
      "track_origin"->10; "track_head"->11; "timestamp"->12
      "timestamp_backwards"->13; "timestamp_head"->14; "read_end"->15
      "processed_pts"->16; "accepted_identity"->17; "output_pts"->18
      "accepted_span"->19; "flush"->20; "discontinuity"->21
      "buffer_provenance"->22; "buffer_delta"->23; "track_rate"->24
      "track_observation"->25; "sink_reset"->26; "sink_release"->27
      "renderer_reset"->28; "renderer_release"->29; "source_retired"->30
      "public_seek"->31; "media_identity"->32; "source"->33
      "range"->34; "input"->35; "replacement"->36; "speed"->37
      "silence"->38; "offload"->39; "tunneling"->40; "extension_renderer"->41
      "terminal_timeout"->42; "terminal_authority"->43; "terminal_input"->44
      "terminal_pause"->45; "terminal_track"->46
      "sink_pause"->47; "renderer_authority"->48; "native_proof"->49; "authority"->50
      "visual_pcm"->51; "visual_authority"->52
      else->255
    }
    known=false
  }

  @Synchronized fun evidence(sourceHandle:String):NCContinuousMuxedPresentationEvidence? {
    if(sources[sourceHandle]?.visual==true)return null
    return sourceEvidence(sourceHandle)
  }
  private fun sourceEvidence(sourceHandle:String):NCContinuousMuxedPresentationEvidence? {
    val source=sources[sourceHandle] ?: return null
    if (!known || epoch==0L) return null
    val owned=ranges.values.filter {it.key.sourceHandle==sourceHandle}.sortedBy {it.key.rangeIndex}
    var samples=0L
    for (range in owned) range.trackStart?.let {start ->
      samples+=(presented-start).coerceIn(0,range.accepted)
    }
    val exactEnd=owned.size==source.plan.totalRanges && owned.all {
      it.readEnd && it.formatKnown && it.rawConsumed==it.raw.toLong()
        && it.accepted==it.valid && it.trackStart!=null && presented>=it.trackStart!!+it.valid
        && it.lastQueuedPts?.let {end -> it.processedThroughPts?.let {pts ->pts>=end}==true}==true
    }
    return NCContinuousMuxedPresentationEvidence(sourceHandle,epoch,samples,samples>0,
      samples==source.plan.samples && samples>0 && exactEnd)
  }

  @Synchronized private fun proofSamples(handle:String,run:Long,sink:Long,completion:Boolean):Long? {
    if(!known || run!=runRevision || sink<=0 || sink!=epoch)return null
    val row=evidence(handle) ?: return null
    if(!row.started || completion && !row.naturalEnd)return null
    return row.presentedSamples
  }
  @Synchronized private fun proofCurrent(handle:String,run:Long,sink:Long,samples:Long,completion:Boolean):Boolean =
    proofSamples(handle,run,sink,completion)?.let {it>=samples && samples>0}==true
  fun sourceStartProof(handle:String,run:Long,sink:Long):SourceStartProof? =
    SourceStartProof.observe(this,handle,run,sink)
  fun sourceCompletionProof(handle:String,run:Long,sink:Long):SourceNaturalCompletionProof? =
    SourceNaturalCompletionProof.observe(this,handle,run,sink)
  @Synchronized private fun visualProofSamples(handle:String,run:Long,sink:Long):Long? {
    if(desktopOrdered) {
      if(!known ||run!=runRevision ||sink<=0 ||sink!=epoch ||sources[handle]?.visual!=true)return null
      return sourceEvidence(handle)?.presentedSamples?.takeIf{it>0}
    }
    val start=visual?.takeIf {it.handle==handle}?.trackStart?:return null
    if(!known ||run!=runRevision ||sink<=0 ||sink!=epoch)return null
    return (minOf(presented,accepted)-start).takeIf {it>0}
  }
  fun visualStartProof(handle:String,run:Long,sink:Long):VisualStartProof? =
    VisualStartProof.observe(this,handle,run,sink)
  @Synchronized private fun visualEndSamples(key:NCContinuousMuxedClipKey,run:Long,sink:Long):Long? {
    if(desktopOrdered) {
      val source=sources[key.sourceHandle]?:return null
      if(!known ||run!=runRevision ||sink<=0 ||sink!=epoch ||!source.visual
        ||key.rangeIndex!=source.plan.totalRanges-1 ||key !in ranges)return null
      return sourceEvidence(key.sourceHandle)?.takeIf{it.naturalEnd}?.presentedSamples
    }
    val idle=visual?:return null
    val start=idle.trackStart?:return null
    if(!known ||run!=runRevision ||sink<=0 ||sink!=epoch ||idle.sealedTail!=key)return null
    val owned=ranges.values.filter {it.key.sourceHandle==idle.handle}.sortedBy {it.key.rangeIndex}
    if(owned.size+idle.closedRanges!=idle.nextRange ||owned.withIndex().any {(offset,row)->
      row.key.rangeIndex!=idle.closedRanges+offset ||!row.readEnd ||!row.formatKnown
        ||row.rawConsumed!=row.raw.toLong() ||row.accepted!=row.valid ||row.trackStart==null
        ||presented<row.trackStart!!+row.valid
        ||row.lastQueuedPts?.let {queued->row.processedThroughPts?.let {it>=queued}==true}!=true
    })return null
    val samples=idle.nextRange*24000L
    return samples.takeIf {it>0 &&accepted>=start+it &&presented>=start+it}
  }
  fun visualCompletionProof(key:NCContinuousMuxedClipKey,run:Long,sink:Long):VisualNaturalCompletionProof? =
    VisualNaturalCompletionProof.observe(this,key,run,sink)

  @Synchronized fun protectedCursors():NCContinuousMuxedProtectedCursors {
    if (!known) return NCContinuousMuxedProtectedCursors(runRevision,epoch,false,emptySet(),emptySet(),emptySet())
    val playing=ranges.values.filter {it.trackStart?.let {start ->
      presented>=start && presented<start+it.valid}==true}.map {it.key}.toSet()
    val reading=inputs.filter {ranges[it.key]?.readEnd!=true}.map {it.key}.toSet()
    val output=ranges.values.filter {it.trackStart?.let {start ->presented<start+it.accepted}==true}
      .map {it.key}.toSet()+listOfNotNull(processed?.key)+videoProtected+(renderedVideo?.protectedKeys()?:emptySet())
    return NCContinuousMuxedProtectedCursors(runRevision,epoch,true,playing,reading,output)
  }
  /** Output-thread pause evidence only. Keep the decoder origin and measured
   * physical sample head independent; never infer a frame from audio progress.
   * The caller must first stop output with its exact temporary pause permit. */
  /** Last observed OS-consumed source position, never decoder/player time.
   * Read-ahead cannot choose the source; a silent range returns unknown. */
  @Synchronized internal fun orderedPlaybackClock():Map<String,Any>? {
    if(!desktopOrdered ||!known ||epoch<=0)return null
    val range=ranges.values.singleOrNull {row->row.trackStart?.let {start->
      presented>start &&presented<=start+row.valid &&presented<=start+row.accepted
    }==true}?:return null
    val source=sources[range.key.sourceHandle]?:return null
    if(source.visual)return null
    val consumed=presented-range.trackStart!!
    val samples=range.start+consumed
    if(consumed !in 1..range.valid ||samples !in 1..source.plan.samples)return null
    return mapOf("sourceHandle" to range.key.sourceHandle,"samples" to samples)
  }
  @Synchronized internal fun orderedContinuationPosition():Map<String,Long>? {
    if(!desktopOrdered ||!known ||epoch<=0)return null
    val frame=renderedVideo?.snapshot()?:return null
    if(frame["known"]!=true)return null
    val ordinal=(frame["ordinal"] as? Number)?.toLong()?:return null
    val offset=(frame["frameOffset"] as? Number)?.toLong()?:return null
    val range=ranges.values.singleOrNull{it.key.ordinal==ordinal}?:return null
    val start=range.trackStart?:return null
    val consumed=presented-start
    if(consumed !in 0..range.valid ||consumed>range.accepted ||offset !in 0..11)return null
    return mapOf("ordinal" to ordinal,"frameOffset" to offset,"consumedSamples" to consumed)
  }
  @Synchronized internal fun orderedBufferedMedia():Boolean = desktopOrdered &&known &&ranges.values.any {
    val start=it.trackStart
    start==null ||presented<start+it.valid
  }
}
