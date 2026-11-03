package expo.modules.audio

import android.media.AudioTimestamp
import android.media.AudioTrack
import android.os.SystemClock
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.PlaybackParameters
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.ForwardingAudioSink
import java.nio.ByteBuffer
import java.lang.ref.WeakReference

/** Static observer origins missing from the model's existing failure table.
 * Diagnostic only: unknown caller text is never emitted or used as authority.
 */
private fun ncContinuousMuxedFirstCauseOrigin(reason:String):Int=when(reason) {
  "settled_sink"->1; "settled_idle"->2; "idle_return"->3; "track_capture"->4
  "sink_pause_error"->5; "sink_discontinuity"->6; "sink_flush"->7
  "unprepared_close"->8; "expiry_work"->9; "provider_owner"->10
  "provider_replacement"->11; "provider_permission"->12; "provider_origin"->13
  "output_authority"->14; "output_admission"->15; "delegated_entry"->16
  "delegate_error"->17; "output_checkpoint"->18; "play_authority"->19
  "proof_worker_thread"->20; "proof_worker_error"->21; "proof_worker_post"->22
  "terminal_worker"->23; "terminal_eos"->24; "retained_admission"->25
  "retained_entry"->26; "retained_delegate"->27; "retained_checkpoint"->28
  "renderer_seek"->29; "renderer_disable"->30
  "video_origin"->31; "video_disable"->32; "video_reset"->33
  "video_release"->34; "queue_fence"->35
  else->255
}

/** Dormant outside an explicitly enrolled validated whole-source debug probe.
 * This owns no AudioTrack, audio focus, player or receipt authority.
 */
@UnstableApi
internal class NCContinuousMuxedObservation {
  internal data class Enrollment(val mediaId:String,val key:NCContinuousMuxedClipKey,
    val start:Long,val valid:Long,val delay:Int,val padding:Int,val raw:Int)
  @Volatile var model:NCContinuousMuxedPresentation?=null
    private set
  private var identities=emptyMap<String,NCContinuousMuxedClipKey>()
  private var sourceHandle:String?=null
  private var sourceHandles:List<String> = emptyList()
  private var sourceLogStates:List<Pair<Boolean,Boolean>> = emptyList()
  private var track=WeakReference<AudioTrack>(null)
  private var epoch=0L
  private var head=0L
  private var stamped:Long?=null
  private var timestampNanos:Long?=null
  private var timestampRejection:String?=null
  private var timestampRejectedSamples=0L
  private var firstReset=true
  private var initialResetScope=false
  private var naturalChangeScope=false
  private var lastLogBucket=-1L
  private var lastLogKnown=true
  private var lastLogStarted=false
  private var lastLogEnded=false
  var outputToken:Long?=null
    private set
  private var outputOffsetUs=0L
  private var context:Output?=null
  private var progress=NCContinuousMuxedBufferProgress()
  private data class Output(val token:Long,val ptsUs:Long,val decodeOnly:Boolean,val last:Boolean)
  internal data class LiveOutput(val model:NCContinuousMuxedPresentation,val key:NCContinuousMuxedClipKey,val epoch:Long,
    val token:Long=0)
  /** Copy under the observer lock, then release it BEFORE output actor work. */
  @Synchronized internal fun liveOutput():LiveOutput? {
    val observer=model?:return null;val output=context?:return null
    if(liveSinkIdentity==null || output.decodeOnly)return null
    val key=observer.processedKey(output.token)?:return null
    return LiveOutput(observer,key,nativeCapture?.sinkEpoch?:0L,output.token)
  }
  @Synchronized internal fun processedSinkIdentity():Pair<NCContinuousMuxedPresentation,Long>? {
    val observer=model?:return null;val token=outputToken?:return null
    return if(liveSinkIdentity!=null && observer.processedKey(token)!=null)observer to token else null
  }
  /** Content/origin check only, not a visual output grant. Absolute PCM reads
   * allocate nothing and leave the delegate's buffer unchanged. Existing
   * processed-token/configuration identities must match before the scan. */
  @Synchronized internal fun visualPcmValid(buffer:ByteBuffer,format:Format?,
    configured:Pair<NCContinuousMuxedPresentation,Long>?,supported:Boolean):Boolean? {
    val observer=model?:return null;val token=outputToken?:return null
    if(!observer.processedVisual(token))return null
    val output=context?:return false
    if(!supported ||format==null ||output.token!=token ||output.decodeOnly
      ||configured==null ||configured.first!==observer ||configured.second!=token)return false
    val raw=observer.visualRawSamples(token,format)
    if(raw<=0)return false
    return NCContinuousMuxedVisualPcm.isZero(buffer,format,raw)
  }
  /** Native input eligibility only, not downstream writing or presentation.
   * An earlier renderer EOS cannot close PCM admission for a sealed successor. */
  @Synchronized internal fun terminalInputKey():NCContinuousMuxedClipKey? {
    val observer=model?:return null
    if(liveSinkIdentity==null || !observer.terminalInputAccepted())return null
    return outputToken?.let {observer.processedKey(it)}
  }
  private data class Marker(val model:NCContinuousMuxedPresentation,val epoch:Long,val frames:Int,
    var status:Int?=null,var reached:Boolean=false)
  private var marker:Marker?=null
  private class TerminalProbe(val model:NCContinuousMuxedPresentation,val authority:()->Boolean) {
    var state="armed"
    var began:Long?=null
    var epoch:Long?=null
    var track=WeakReference<AudioTrack>(null)
    var endpoint:List<Map<String,Any>> = emptyList()
  }
  private var terminalProbe:TerminalProbe?=null
  private var liveSinkIdentity:Any?=null
  private var nativeCapture:NCContinuousMuxedPresentation.NativeTrackCapture?=null
  private var pendingLiveModel:NCContinuousMuxedPresentation?=null
  private var pendingLiveIdentities=emptyMap<String,NCContinuousMuxedClipKey>()
  private var settledProviderEpoch=0L
  private val rendererBoundaries=mutableListOf<Map<String,Any?>>()
  private var latestRendererStop:Map<String,Any?>?=null
  private var latestStopDecision:Map<String,Boolean>?=null
  private var rendererPositionContext:Pair<Long?,Long?>?=null

  /** Cache only the actual render argument and actual current-period end.
   * Neither is an AudioTrack sample, a playback clock or a completion proof. */
  @Synchronized internal fun rendererPosition(positionUs:Long,periodEndUs:Long?) {
    fun safe(value:Long?)=value?.takeIf {it in 0..9007199254740991L}
    rendererPositionContext=if(model==null)null else safe(positionUs) to safe(periodEndUs)
  }

  /** Passive context only: renderer EOS is not necessarily the final run EOS.
   * Keep input and processed output distinct; neither advances the model. */
  @Synchronized internal fun rendererBoundary(callback:Int,inputOrdinal:Long?,readEnd:Boolean,
    streamFinal:Boolean,ended:Boolean?,rendererState:Int,lastPtsUs:Long) {
    val observer=model?:return
    if(callback !in 1..2)return
    if(callback!=2 && rendererBoundaries.size>=8)return
    fun safe(value:Long?)=value?.takeIf {it in 0..9007199254740991L}
    val context=mapOf<String,Any?>("callback" to callback,"inputOrdinal" to safe(inputOrdinal),
      "outputOrdinal" to safe(outputToken?.let {observer.processedKey(it)?.ordinal}),
      "readEnd" to readEnd,"streamFinal" to streamFinal,"ended" to ended,
      "rendererState" to rendererState,"lastPtsUs" to safe(lastPtsUs),
      "rendererPositionUs" to rendererPositionContext?.first,"periodEndUs" to rendererPositionContext?.second)
    if(callback==2) {
      latestRendererStop=context+("elapsedMs" to SystemClock.elapsedRealtime())
      latestStopDecision=null
    }
    if(rendererBoundaries.size>=8)return
    if(rendererBoundaries.any {it.filterKeys {key->key!="elapsedMs"}==context})return
    val row=context+("elapsedMs" to SystemClock.elapsedRealtime())
    rendererBoundaries.add(row)
    try {Log.d("NCContinuousBoundary",row.entries.joinToString(" ") {"${it.key}=${it.value?:-1}"})}
    catch(_:RuntimeException) {} // Logging cannot grant output or prevent delegation.
  }

  /** Cache already evaluated stop decisions; no new track/authority queries. */
  @Synchronized internal fun rendererStopDecision(normal:Boolean,heldEof:Boolean,buffering:Boolean) {
    if(model!=null && latestRendererStop!=null)latestStopDecision=mapOf(
      "normalScope" to normal,"heldEof" to heldEof,"bufferingScope" to buffering)
  }

  /** Explicit live enrollment shares the Queue's model; it never allocates a
   * second mapping or adopts a used numeric origin. Reused sink settlement is
   * the concrete persistent controller's separate responsibility.
   */
  @Synchronized fun attachLiveModel(next:NCContinuousMuxedPresentation,sinkIdentity:Any):Boolean {
    if(model!=null || track.get()!=null || epoch!=0L || !next.canAttachNativeTrack()
      || pendingLiveModel?.let {it!==next}==true)return false
    model=next;liveSinkIdentity=sinkIdentity
    identities=pendingLiveIdentities
    sourceHandles=identities.values.map {it.sourceHandle}.distinct();sourceHandle=sourceHandles.firstOrNull()
    pendingLiveModel=null;pendingLiveIdentities=emptyMap()
    return true
  }
  /** Initial timeline registration precedes its first ACK and enrollment.
   * Retain only exact already-validated native keys for the same pending model.
   * This does not attach output, expose lookup, capture a track or grant PCM.
   * The actual player still cannot prepare until exact enrollment completes.
   */
  @Synchronized fun stageLiveIdentity(next:NCContinuousMuxedPresentation,mediaId:String,key:NCContinuousMuxedClipKey):Boolean {
    if(liveSinkIdentity!=null)return model===next && registerLiveIdentity(mediaId,key)
    if(model!=null || track.get()!=null || epoch!=0L || !next.canAttachNativeTrack()
      || pendingLiveModel?.let {it!==next}==true || mediaId.isBlank() || !next.hasRegisteredRange(key))return false
    pendingLiveIdentities[mediaId]?.let {return it==key}
    if(key in pendingLiveIdentities.values || pendingLiveIdentities.size>=60)return false
    pendingLiveModel=next;pendingLiveIdentities=pendingLiveIdentities+(mediaId to key)
    return true
  }
  @Synchronized fun attachSettledLiveModel(next:NCContinuousMuxedPresentation,
    settled:NCContinuousMuxedSinkController.SinkSettlement):Boolean {
    if(!next.canAttachNativeTrack() || pendingLiveModel?.let {it!==next}==true
      || !settled.claimObservation(this,model,liveSinkIdentity))return false
    model?.fence("settled_sink")
    identities=pendingLiveIdentities
    sourceHandles=identities.values.map {it.sourceHandle}.distinct();sourceHandle=sourceHandles.firstOrNull()
    sourceLogStates=emptyList();pendingLiveModel=null;pendingLiveIdentities=emptyMap()
    track=WeakReference(null);epoch=0;head=0;stamped=null;timestampNanos=null;nativeCapture=null
    outputToken=null;outputOffsetUs=0;context=null;progress=NCContinuousMuxedBufferProgress()
    firstReset=true;initialResetScope=false;naturalChangeScope=false;lastLogBucket=-1
    lastLogKnown=true;lastLogStarted=false;lastLogEnded=false;marker=null;terminalProbe=null
    settledProviderEpoch=settled.providerEpoch
    rendererBoundaries.clear();latestRendererStop=null;latestStopDecision=null
    rendererPositionContext=null
    model=next // The same factory observer; old mapping is never restored.
    return true
  }
  /** Reused startup retains next-model keys without replacing the old model or
   * lookup. Only the exact controller-issued, unconsumed settlement permits it;
   * attachment still happens on the output thread after the real layout ACK.
   */
  @Synchronized fun stageSettledLiveIdentity(next:NCContinuousMuxedPresentation,mediaId:String,
    key:NCContinuousMuxedClipKey,settled:NCContinuousMuxedSinkController.SinkSettlement):Boolean {
    if(!settled.canStageObservation(this,model,liveSinkIdentity) || !next.canAttachNativeTrack()
      || pendingLiveModel?.let {it!==next}==true || mediaId.isBlank() || !next.hasRegisteredRange(key))return false
    pendingLiveIdentities[mediaId]?.let {return it==key}
    if(key in pendingLiveIdentities.values || pendingLiveIdentities.size>=60)return false
    pendingLiveModel=next;pendingLiveIdentities=pendingLiveIdentities+(mediaId to key)
    return true
  }
  @Synchronized fun stageIdleSettledLiveIdentity(next:NCContinuousMuxedPresentation,mediaId:String,
    key:NCContinuousMuxedClipKey,settled:NCContinuousMuxedSinkController.IdleSettlement):Boolean {
    if(!settled.canStageObservation(this,model,liveSinkIdentity) || !next.canAttachNativeTrack()
      || pendingLiveModel?.let {it!==next}==true || mediaId.isBlank() || !next.hasRegisteredRange(key))return false
    pendingLiveIdentities[mediaId]?.let {return it==key}
    if(key in pendingLiveIdentities.values || pendingLiveIdentities.size>=60)return false
    pendingLiveModel=next;pendingLiveIdentities=pendingLiveIdentities+(mediaId to key)
    return true
  }
  @Synchronized fun attachIdleSettledLiveModel(next:NCContinuousMuxedPresentation,
    settled:NCContinuousMuxedSinkController.IdleSettlement):Boolean {
    if(!next.canAttachNativeTrack() || pendingLiveModel?.let {it!==next}==true
      || !settled.claimObservation(this,model,liveSinkIdentity))return false
    model?.fence("settled_idle")
    identities=pendingLiveIdentities
    sourceHandles=identities.values.map {it.sourceHandle}.distinct();sourceHandle=sourceHandles.firstOrNull()
    sourceLogStates=emptyList();pendingLiveModel=null;pendingLiveIdentities=emptyMap()
    track=WeakReference(null);epoch=0;head=0;stamped=null;timestampNanos=null;nativeCapture=null
    outputToken=null;outputOffsetUs=0;context=null;progress=NCContinuousMuxedBufferProgress()
    firstReset=true;initialResetScope=false;naturalChangeScope=false;lastLogBucket=-1
    lastLogKnown=true;lastLogStarted=false;lastLogEnded=false;marker=null;terminalProbe=null
    settledProviderEpoch=settled.providerEpoch;liveSinkIdentity=settled.slot;model=next
    rendererBoundaries.clear();latestRendererStop=null;latestStopDecision=null
    rendererPositionContext=null
    return true
  }
  /** Return to the established guarded ordinary idle path, not another output
   * owner. Only the exact consumed continuous settlement can clear the old live
   * mapping; its receipts/history remain in their retired Queue/Authority.
   */
  @Synchronized fun returnToOrdinaryIdle(settled:NCContinuousMuxedSinkController.SinkSettlement):Boolean {
    if(pendingLiveModel!=null || !settled.claimObservation(this,model,liveSinkIdentity))return false
    model?.fence("idle_return");model=null;liveSinkIdentity=null
    identities=emptyMap();sourceHandles=emptyList();sourceHandle=null;sourceLogStates=emptyList()
    track=WeakReference(null);epoch=0;head=0;stamped=null;timestampNanos=null;nativeCapture=null
    outputToken=null;outputOffsetUs=0;context=null;progress=NCContinuousMuxedBufferProgress()
    rendererBoundaries.clear();latestRendererStop=null;latestStopDecision=null
    rendererPositionContext=null
    firstReset=true;initialResetScope=false;naturalChangeScope=false;lastLogBucket=-1
    lastLogKnown=true;lastLogStarted=false;lastLogEnded=false;marker=null;terminalProbe=null
    settledProviderEpoch=settled.providerEpoch
    return true
  }
  /** Queue already registered the validated spans. This only maps the stable
   * child ID before Media3 exposure, not installation, output or proof.
   */
  @Synchronized fun registerLiveIdentity(mediaId:String,key:NCContinuousMuxedClipKey):Boolean {
    if(liveSinkIdentity==null || mediaId.isBlank() || model?.hasRegisteredRange(key)!=true)return false
    if(model!!.desktopOrdered) {
      // Native source release already required receipts, ACKed reader closure
      // and no protected origins. Remove only those exact forgotten mappings;
      // a queued/decoded-but-unpresented source is still registered in model.
      identities=identities.filterValues {model!!.hasRegisteredRange(it)}
      sourceHandles=identities.values.map{it.sourceHandle}.distinct();sourceHandle=sourceHandles.firstOrNull()
    }
    identities[mediaId]?.let {return it==key}
    if(key in identities.values)return false
    identities=identities+(mediaId to key)
    if(key.sourceHandle !in sourceHandles) {
      sourceHandles=sourceHandles+key.sourceHandle;sourceHandle=sourceHandles.first()
    }
    return true
  }

  @Synchronized fun enroll(handle:String,plan:NCMuxedTrialStreamRanges.Plan,entries:List<Enrollment>) {
    enroll(listOf(handle to plan),entries)
  }
  @Synchronized fun enroll(plans:List<Pair<String,NCMuxedTrialStreamRanges.Plan>>,entries:List<Enrollment>) {
    if(liveSinkIdentity!=null || pendingLiveModel!=null){fence("replacement");pendingLiveModel?.fence("replacement");return}
    require(plans.size in 1..64 && plans.map {it.first}.toSet().size==plans.size)
    model?.fence("replacement")
    val next=NCContinuousMuxedPresentation()
    plans.forEach {(handle,plan)->next.registerSource(handle,plan)}
    entries.forEach {next.registerRange(it.key,it.start,it.valid,it.delay,it.padding,it.raw)}
    identities=entries.associate {it.mediaId to it.key}
    if(identities.size!=entries.size)next.fence("media_identity")
    sourceHandles=plans.map {it.first};sourceHandle=sourceHandles.first();sourceLogStates=emptyList()
    outputToken=null;context=null;progress=NCContinuousMuxedBufferProgress();marker=null;terminalProbe=null
    firstReset=true;initialResetScope=false;naturalChangeScope=false;lastLogBucket=-1
    lastLogKnown=true;lastLogStarted=false;lastLogEnded=false
    model=next
    // A previously used track cannot inherit a fresh zero-origin proof.
    track.get()?.let {sampleTrack()}
  }
  @Synchronized fun key(mediaId:String)=identities[mediaId]
  @Synchronized fun processed(startUs:Long,offsetUs:Long) {
    outputToken=model?.recordProcessedStream(startUs,offsetUs)
    outputOffsetUs=offsetUs
  }
  @Synchronized fun processedOutput(ptsUs:Long) {
    outputToken?.let {model?.recordProcessedOutput(it,ptsUs-outputOffsetUs)}
  }
  @Synchronized fun beginOutput(ptsUs:Long,decodeOnly:Boolean,last:Boolean) {
    context=outputToken?.let {Output(it,ptsUs-outputOffsetUs,decodeOnly,last)}
  }
  @Synchronized fun endOutput() {context=null;sampleTrack()}
  @Synchronized fun beforeBuffer(buffer:ByteBuffer):NCContinuousMuxedBufferProgress.Stamp? {
    if(model==null)return null
    val output=context ?: run {fence("output_context");return null}
    if(output.decodeOnly)return null
    return progress.begin(buffer,output.token,output.ptsUs).also {
      if(it==null)fence("buffer_provenance")
    }
  }
  @Synchronized fun afterBuffer(stamp:NCContinuousMuxedBufferProgress.Stamp?,buffer:ByteBuffer) {
    val output=context
    if(stamp!=null && output!=null) {
      val bytes=progress.finish(stamp,buffer)
      if(bytes==null)fence("buffer_delta")
      else model?.recordAcceptedOutput(output.token,output.ptsUs,bytes,output.decodeOnly,output.last)
    }
    sampleTrack()
  }
  @Synchronized fun configured(format:Format,outputChannels:IntArray?,supported:Boolean) {
    model?.recordPcmFormat(format.sampleRate,format.channelCount,
      if(format.pcmEncoding==C.ENCODING_PCM_16BIT)format.channelCount*2 else -1,
      format.encoderDelay,format.encoderPadding,supported && outputChannels==null
        && format.sampleMimeType=="audio/raw")
  }
  @Synchronized fun observe(track:AudioTrack,providerEpoch:Long?=null):NCContinuousMuxedPresentation.NativeTrackCapture? {
    liveSinkIdentity?.let {sink->
      val observer=model?:return null
      if(track.state!=AudioTrack.STATE_INITIALIZED || track.sampleRate!=48000) {fence("track_capture");return null}
      nativeCapture?.let {if(!it.matchesContext(this,sink,track,epoch)){fence("track_capture");return null}}
      if(this.track.get()!==track) {
        val actualEpoch=providerEpoch?:if(settledProviderEpoch==0L)epoch+1 else null
        if(actualEpoch==null || actualEpoch !in 1..9007199254740991L || actualEpoch<=settledProviderEpoch) {
          fence("track_capture");return null
        }
        this.track=WeakReference(track);epoch=actualEpoch
      } else if(providerEpoch!=null && providerEpoch!=epoch){fence("track_capture");return null}
      val captured=observer.captureNativeTrack(this,sink,track,epoch)?:run {fence("track_capture");return null}
      nativeCapture=captured;sampleTrack();return captured
    }
    if(this.track.get()!==track) {
      if(this.track.get()!=null)abandonTerminalProbe("terminal_track")
      this.track=WeakReference(track);epoch++
    }
    sampleTrack()
    val observer=model ?: return null
    val target=observer.diagnosticEndMarkerFrames() ?: return null
    val probe=Marker(observer,epoch,target)
    marker=probe
    try {
      track.setPlaybackPositionUpdateListener(object:AudioTrack.OnPlaybackPositionUpdateListener {
        override fun onMarkerReached(track:AudioTrack) {recordDiagnosticMarker(probe,track)}
        override fun onPeriodicNotification(track:AudioTrack) {}
      })
      probe.status=track.setNotificationMarkerPosition(target)
    } catch(_:RuntimeException) {probe.status=-1}
    Log.d("NCContinuousProof","markerInstall=$target epoch=$epoch status=${probe.status?:-1}")
    return null
  }
  @Synchronized private fun recordDiagnosticMarker(probe:Marker,actual:AudioTrack) {
    if(marker!==probe || model!==probe.model || epoch!=probe.epoch || track.get()!==actual
      || probe.status!=0 || probe.reached)return
    probe.reached=true
    try {
      val raw=actual.playbackHeadPosition.toLong() and 0xffffffffL
      val timestamp=AudioTimestamp()
      val valid=actual.getTimestamp(timestamp)
      Log.d("NCContinuousProof","markerReached=${probe.frames} epoch=${probe.epoch} head=$raw " +
        "stamp=${if(valid)timestamp.framePosition else -1} " +
        "known=${if(probe.model.protectedCursors().known)1 else 0} failure=${probe.model.failureCode()}")
    } catch(_:RuntimeException) {
      Log.d("NCContinuousProof","markerReached=${probe.frames} epoch=${probe.epoch} trackUnavailable=1")
    }
    // A callback is a diagnostic observation, not a substitute for the proved
    // output-span mapping. It cannot restore known state or publish a receipt.
  }
  @Synchronized fun sampleTrack() {
    val observer=model ?: return
    val actual=track.get() ?: return
    try {
      if(actual.sampleRate!=48_000) {fence("track_rate");return}
      head=actual.playbackHeadPosition.toLong() and 0xffffffffL
      val timestamp=AudioTimestamp()
      val valid=actual.getTimestamp(timestamp)
      stamped=if(valid)timestamp.framePosition and 0xffffffffL else null
      timestampNanos=if(valid)timestamp.nanoTime else null
      // Some platform SCO switches return hours of frames (or a future clock)
      // before returning to the real position. Do not feed those samples into
      // the model's monotonic history. Like Media3 1.8's timestamp admission,
      // use a five-second plausibility window; never extrapolate or rescale.
      // Modular distance preserves a real unsigned 32-bit wrap. Plausible
      // counter/clock regressions still reach the model and fence normally.
      val distance=stamped?.let {((it-head+0x80000000L) and 0xffffffffL)-0x80000000L}
      val now=if(valid)System.nanoTime() else 0L
      timestampRejection=when {
        distance!=null && (distance < -240_000L || distance > 240_000L)->"position_mismatch"
        timestampNanos?.let {it>=0 && kotlin.math.abs(now-it)>5_000_000_000L}==true->"clock_mismatch"
        else->null
      }
      if(timestampRejection!=null && timestampRejectedSamples<Long.MAX_VALUE)timestampRejectedSamples++
      val admittedStamp=if(timestampRejection==null)stamped else null
      val admittedNanos=if(timestampRejection==null)timestampNanos else null
      if(liveSinkIdentity!=null) {
        val capture=nativeCapture?:run {fence("track_capture");return}
        if(!capture.matchesContext(this,liveSinkIdentity!!,actual,epoch)){fence("track_capture");return}
        observer.recordNativeTrackSample(capture,head,admittedStamp,admittedNanos)
      } else observer.recordTrackSample(epoch,head,admittedStamp,admittedNanos)
      val cursors=observer.protectedCursors()
      if(!cursors.known)abandonTerminalProbe("terminal_track")
      val bucket=head/24_000
      val evidence=sourceHandle?.let {observer.evidence(it)}
      val sourceEvidence=sourceHandles.map {observer.evidence(it)}
      val sourceStates=sourceEvidence.map {(it?.started==true) to (it?.naturalEnd==true)}
      val started=evidence?.started==true
      val ended=evidence?.naturalEnd==true
      if(bucket!=lastLogBucket || cursors.known!=lastLogKnown
        || started!=lastLogStarted || ended!=lastLogEnded || sourceStates!=sourceLogStates) {
        lastLogBucket=bucket;lastLogKnown=cursors.known
        lastLogStarted=started;lastLogEnded=ended
        sourceLogStates=sourceStates
        sourceEvidence.forEachIndexed {ordinal,row ->
          Log.d("NCContinuousProof","source=$ordinal epoch=$epoch head=$head stamp=${stamped?:-1} " +
            "timestampRejection=${timestampRejection?:"none"} rejectedSamples=$timestampRejectedSamples " +
            "known=${if(cursors.known)1 else 0} samples=${row?.presentedSamples?:-1} " +
            "start=${if(row?.started==true)1 else 0} end=${if(row?.naturalEnd==true)1 else 0} " +
            "failure=${observer.failureCode()}")
        }
      }
    } catch(_:RuntimeException) {fence("track_observation")}
  }
  @Synchronized fun beginPositionReset(positionUs:Long) {
    if(model!=null)Log.d("NCContinuousProof","reset=$positionUs offset=$outputOffsetUs processed=${if(outputToken!=null)1 else 0}")
    initialResetScope=firstReset && model?.permitsInitialPositionReset(outputToken,positionUs)==true
    firstReset=false
    if(!initialResetScope)fence("position_reset")
  }
  @Synchronized fun endPositionReset() {initialResetScope=false}
  @Synchronized fun beginNaturalChange() {naturalChangeScope=true}
  @Synchronized fun endNaturalChange() {naturalChangeScope=false}
  @Synchronized internal fun permitsInitialCleanup()=initialResetScope
    && model?.permitsInitialPositionReset(outputToken,outputOffsetUs)==true
  @Synchronized internal fun permitsStreamDiscontinuity()=naturalChangeScope || permitsInitialCleanup()
  @Synchronized fun discontinuity() {if(!naturalChangeScope && !initialResetScope)fence("discontinuity")}
  @Synchronized fun flushed() {if(!initialResetScope)fence("flush")}
  @Synchronized fun fence(reason:String) {
    val observer=model;val first=observer?.failureCode()==0
    observer?.fence(reason)
    if(first)try {Log.d("NCContinuousControl","event=3 failure=${observer?.failureCode()} origin=${ncContinuousMuxedFirstCauseOrigin(reason)} elapsedMs=${SystemClock.elapsedRealtime()}")}
      catch(_:RuntimeException) {}
    if(first)latestRendererStop?.let {stop->
      try {Log.d("NCContinuousStop",(stop+(latestStopDecision?:emptyMap())).entries.joinToString(" ") {"${it.key}=${it.value?:-1}"})}
      catch(_:RuntimeException) {} // Error-only context cannot prevent fencing/cleanup.
    }
    abandonTerminalProbe(reason)
  }
  @Synchronized internal fun fenceModel(expected:NCContinuousMuxedPresentation,reason:String) {
    if(model===expected)fence(reason)
  }

  /** Only the explicit multi-source fixture may select this lifecycle experiment.
   * The captured native binding supplies permission; this never opens/renews it.
   */
  @Synchronized fun enableTerminalDrainProbe(authority:()->Boolean):Boolean {
    val observer=model ?: return false
    if(terminalProbe!=null || sourceHandles.size<2 || !observer.protectedCursors().known)return false
    terminalProbe=TerminalProbe(observer,authority)
    return true
  }
  @Synchronized private fun abandonTerminalProbe(reason:String) {
    val probe=terminalProbe ?: return
    if(probe.state!="armed" && probe.state!="waiting")return
    probe.state="abandoned"
    probe.model.fence(reason)
    Log.d("NCContinuousProof","terminalAbandoned=1 epoch=$epoch failure=${probe.model.failureCode()}")
  }
  @Synchronized fun paused() {abandonTerminalProbe("terminal_pause")}

  /** Nonblocking, nonrenewable natural-EOS hold. The private delegate may retain
   * valid PCM, so only an actual endpoint can succeed; two seconds can only abort.
   * Cleanup never calls this method and always delegates immediately.
   */
  @Synchronized fun deferTerminalEos(now:Long):Boolean {
    val probe=terminalProbe ?: return false
    if(probe.state!="armed" && probe.state!="waiting")return false
    sampleTrack()
    if(probe.state=="abandoned")return false
    val actual=track.get()
    val permitted=try {probe.authority()} catch(_:RuntimeException) {false}
    if(!permitted) {abandonTerminalProbe("terminal_authority");return false}
    val playing=try {actual?.playState==AudioTrack.PLAYSTATE_PLAYING} catch(_:RuntimeException) {false}
    if(model!==probe.model || actual==null || !probe.model.protectedCursors().known
      || !playing
      || probe.epoch?.let {it!=epoch || probe.track.get()!==actual}==true) {
      abandonTerminalProbe("terminal_track");return false
    }
    if(!probe.model.terminalInputAccepted()) {abandonTerminalProbe("terminal_input");return false}
    val begin=probe.began
    if(now<0 || begin!=null && (now<begin || now-begin>=2000)) {
      abandonTerminalProbe("terminal_timeout");return false
    }
    val rows=sourceHandles.map {probe.model.evidence(it)}
    if(rows.all {it?.naturalEnd==true}) {
      probe.endpoint=rows.mapIndexed {ordinal,row ->
        mapOf("ordinal" to ordinal,"sinkEpoch" to row!!.sinkEpoch,
          "presentedSamples" to row.presentedSamples)
      }
      probe.state="presented"
      rows.forEachIndexed {ordinal,row ->
        Log.d("NCContinuousProof","terminalEndpoint=1 source=$ordinal epoch=$epoch " +
          "samples=${row!!.presentedSamples} head=$head stamp=${stamped?:-1}")
      }
      return false
    }
    if(begin==null) {
      probe.began=now;probe.epoch=epoch;probe.track=WeakReference(actual);probe.state="waiting"
      Log.d("NCContinuousProof","terminalWaiting=1 epoch=$epoch head=$head stamp=${stamped?:-1}")
    }
    return true
  }
  @Synchronized fun snapshot():Map<String,Any?> {
    val observer=model
    val cursors=observer?.protectedCursors()
    val evidence=sourceHandle?.let {observer?.evidence(it)}
    return mapOf("version" to 0,"enrolled" to (observer!=null),"known" to (cursors?.known==true),
      "rendererBoundaries" to rendererBoundaries.toList(),
      "failureCode" to observer?.failureCode(),
      "markerFrames" to marker?.frames,"markerReached" to (marker?.reached==true),
      "markerInstallStatus" to marker?.status,
      "terminalProbeState" to (terminalProbe?.state?:"disabled"),
      "terminalEndpointObserved" to (terminalProbe?.endpoint?.isNotEmpty()==true),
      "terminalEndpointSources" to (terminalProbe?.endpoint?:emptyList<Map<String,Any>>()),
      "sinkEpoch" to epoch,"headFrames" to head,"timestampFrames" to stamped,
      "timestampNanos" to timestampNanos,"presentedSamples" to evidence?.presentedSamples,
      "timestampRejection" to timestampRejection,"timestampRejectedSamples" to timestampRejectedSamples,
      "started" to (evidence?.started==true),"naturalEnd" to (evidence?.naturalEnd==true),
      "sources" to sourceHandles.mapIndexed {ordinal,handle ->
        val row=observer?.evidence(handle)
        mapOf("ordinal" to ordinal,"presentedSamples" to row?.presentedSamples,
          "started" to (row?.started==true),"naturalEnd" to (row?.naturalEnd==true))
      },
      "playingOrdinals" to cursors?.playing?.map {it.ordinal},
      "readingOrdinals" to cursors?.reading?.map {it.ordinal},
      "outputOrdinals" to cursors?.output?.map {it.ordinal})
  }
}

/** Normal sink observation; only the explicitly selected terminal diagnostic
 * may defer natural EOS. Pause, reset, flush and release always delegate.
 */
@UnstableApi
internal class NCContinuousMuxedAudioSink(delegate:AudioSink,
  private val observation:NCContinuousMuxedObservation,
  private val controller:NCContinuousMuxedSinkController?=null,
  private val slot:NCContinuousMuxedSinkController.SinkSlot?=null,
  private val compatibleBufferSize:(Int,Int,Int)->Int?={_,_,_->null},
  private val releaseBufferObserver:()->Unit={}):ForwardingAudioSink(delegate) {
  init {
    require((controller==null)==(slot==null))
    if(slot!=null)check(controller!!.bindObservation(slot,observation))
  }
  private var plainProcessing=true
  private data class SinkConfiguration(val format:Format,val size:Int,val channels:List<Int>?,
    val identity:Pair<NCContinuousMuxedPresentation,Long>?)
  private data class TailBinding(val model:NCContinuousMuxedPresentation,val token:Long,
    val configuration:SinkConfiguration,val firstPtsUs:Long)
  private class RetainedDrain(val binding:TailBinding,val tail:NCContinuousMuxedPresentation.AcceptedTail,val ptsUs:Long) {
    var configured=false
    var done=false
  }
  private var configuration:SinkConfiguration?=null
  private var consumedBinding:TailBinding?=null
  private var retainedDrain:RetainedDrain?=null
  private fun bufferSize(format:Format,requested:Int,channels:IntArray?):Int =
    if(requested==0 &&plainProcessing &&channels==null &&format.sampleMimeType=="audio/raw")
      compatibleBufferSize(format.sampleRate,format.channelCount,format.pcmEncoding)?:requested else requested
  override fun configure(format:Format,specifiedBufferSize:Int,outputChannels:IntArray?) {
    super.configure(format,bufferSize(format,specifiedBufferSize,outputChannels),outputChannels)
    configuration=SinkConfiguration(format,specifiedBufferSize,outputChannels?.toList(),observation.processedSinkIdentity())
    observation.configured(format,outputChannels,plainProcessing)
  }
  override fun handleBuffer(buffer:ByteBuffer,presentationTimeUs:Long,encodedAccessUnitCount:Int):Boolean {
    val configured=configuration
    val visual=observation.visualPcmValid(buffer,configured?.format,configured?.identity,
      plainProcessing &&configured?.channels==null)
    if(visual==false ||visual==true &&controller==null) {
      val reason=if(visual==false)"visual_pcm" else "visual_authority"
      observation.fence(reason)
      slot?.let {controller!!.invalidate(it,reason)}
      return false
    }
    val output=observation.liveOutput()
    val admission=slot?.let {controller!!.beforeBuffer(it,output)}
    if(admission!=null && !admission.allowed)return false
    val before=buffer.position()
    val stamp=observation.beforeBuffer(buffer)
    var returned=false
    var permitted=controller==null
    val result=try {
      super.handleBuffer(buffer,presentationTimeUs,encodedAccessUnitCount).also {returned=true}
    } finally {
      if(admission!=null)permitted=controller!!.afterBuffer(slot!!,admission,returned)
    }
    if(permitted) {
      observation.afterBuffer(stamp,buffer)
      if(output!=null && buffer.position()>before && consumedBinding?.let {it.model===output.model && it.token==output.token}!=true) {
        // A different model can reach normal PCM only after the controller's
        // consumed native settlement. Never reset this for the same sealed run.
        if(consumedBinding?.model!==output.model)retainedDrain=null
        val configured=configuration
        consumedBinding=if(configured?.identity?.let {it.first===output.model && it.second==output.token}==true)
          TailBinding(output.model,output.token,configured,presentationTimeUs) else null
      }
    }
    return result && permitted
  }
  override fun play() {if(slot==null || controller!!.canPlay(slot))super.play()}
  override fun getCurrentPositionUs(sourceEnded:Boolean):Long =
    super.getCurrentPositionUs(sourceEnded).also {observation.sampleTrack()}
  override fun isEnded():Boolean=super.isEnded().also {observation.sampleTrack()}
  override fun hasPendingData():Boolean=super.hasPendingData().also {observation.sampleTrack()}
  override fun playToEndOfStream() {
    if(slot!=null && controller!!.isTargeted(slot)) {
      controller.terminalEos(slot,::drainRetainedOutput) {super.playToEndOfStream();observation.sampleTrack()}
      return
    }
    if(observation.deferTerminalEos(SystemClock.elapsedRealtime()))return
    super.playToEndOfStream();observation.sampleTrack()
  }
  /** No renderer context is manufactured: only an empty public retry of the
   * exact sealed, fully consumed tail. Identical configure drains the old
   * processors before rearming trim, so the gate never admits PCM afterwards. */
  private fun drainRetainedOutput(model:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey,
    checkpoint:()->Boolean):Boolean? {
    val binding=consumedBinding?:return null
    val tail=model.acceptedTerminalTail(binding.token)?:return null
    val config=binding.configuration
    fun current()=binding===consumedBinding && binding.model===model && config===configuration
      && config.identity?.let {it.first===model && it.second==binding.token}==true
      && tail.key==key && model.acceptedTerminalTail(binding.token)==tail && plainProcessing
      && config.channels==null && config.format.sampleMimeType=="audio/raw"
      && config.format.sampleRate==48000 && config.format.channelCount==1 && config.format.pcmEncoding==C.ENCODING_PCM_16BIT
      && config.format.encoderDelay==tail.delay && config.format.encoderPadding==tail.padding && checkpoint()
    if(!current())return null
    val drain=retainedDrain?:RetainedDrain(binding,tail,tail.retryPts(binding.firstPtsUs)?:return null).also {retainedDrain=it}
    if(drain.binding!==binding || drain.tail!=tail)return null
    if(drain.done)return true
    if(!drain.configured) {
      drain.configured=true // A thrown/ambiguous configure cannot be repeated.
      val channels=config.channels?.toIntArray()
      super.configure(config.format,bufferSize(config.format,config.size,channels),channels)
      if(!current())return null
    }
    if(!current())return null
    val empty=ByteBuffer.allocateDirect(0).order(java.nio.ByteOrder.LITTLE_ENDIAN)
    val submitted=super.handleBuffer(empty,drain.ptsUs,1)
    if(empty.position()!=0 || !current())return null
    drain.done=submitted
    return submitted
  }
  private fun invalidate(cause:String) {slot?.let {controller!!.invalidate(it,cause)}}
  override fun pause() {
    if(slot==null || controller!!.permitsNormalPause(slot)!=true) {
      invalidate("sink_pause");observation.paused()
    }
    try {super.pause()} catch(error:RuntimeException) {
      // A permitted transient pause is not permission to survive failed raw
      // cleanup. Revoke this exact enrollment before the exception escapes.
      invalidate("sink_pause_error");throw error
    }
  }
  override fun handleDiscontinuity() {
    if(!observation.permitsStreamDiscontinuity())invalidate("sink_discontinuity")
    observation.discontinuity();super.handleDiscontinuity()
  }
  override fun setPlaybackParameters(parameters:PlaybackParameters) {
    if(parameters.speed!=1f || parameters.pitch!=1f) {plainProcessing=false;invalidate("speed");observation.fence("speed")}
    super.setPlaybackParameters(parameters)
  }
  override fun setSkipSilenceEnabled(enabled:Boolean) {
    if(enabled) {plainProcessing=false;invalidate("silence");observation.fence("silence")}
    super.setSkipSilenceEnabled(enabled)
  }
  override fun setOffloadMode(offloadMode:Int) {
    if(offloadMode!=0) {plainProcessing=false;invalidate("offload");observation.fence("offload")}
    super.setOffloadMode(offloadMode)
  }
  override fun enableTunnelingV21() {plainProcessing=false;invalidate("tunneling");observation.fence("tunneling");super.enableTunnelingV21()}
  override fun flush() {
    if(!observation.permitsInitialCleanup())invalidate("sink_flush")
    observation.flushed();super.flush()
  }
  override fun reset() {invalidate("sink_reset");observation.fence("sink_reset");super.reset()}
  override fun release() {
    invalidate("sink_release");observation.fence("sink_release")
    try {super.release()} finally {releaseBufferObserver()}
  }
}
