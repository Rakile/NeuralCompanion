package expo.modules.audio

import android.content.Context
import android.os.Handler
import android.util.Log
import androidx.media3.common.C
import androidx.media3.common.Format
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.mediacodec.MediaCodecAdapter
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.video.MediaCodecVideoRenderer
import androidx.media3.exoplayer.video.VideoRendererEventListener
import java.nio.ByteBuffer

/** Preserve Media3's listener and codec operations. This tap is installed only
 * for Desktop-ordered output; it neither schedules frames nor grants output. */
@UnstableApi
internal class NCOrderedVideoCodec(private val delegate:MediaCodecAdapter,private val handler:Handler):
  MediaCodecAdapter by delegate {
  private var evidence:NCOrderedVideoEvidence?=null
  private var epoch=Any()
  private var installed=false
  private val pending=linkedMapOf<Long,Any>()
  private var upstream:MediaCodecAdapter.OnFrameRenderedListener?=null
  private var upstreamHandler:Handler?=null
  private fun install() {
    val captured:Any;val next:MediaCodecAdapter.OnFrameRenderedListener?;val target:Handler
    synchronized(this){captured=epoch;next=upstream;target=upstreamHandler?:handler}
    try {
      delegate.setOnFrameRenderedListener({_,pts,nanos->
        val update=synchronized(this) {
          if(captured!==epoch)null else evidence?.let{it to pending.remove(pts)}
        }
        update?.let{(proof,token)->if(token==null)proof.unavailable("render_callback_unmapped") else proof.rendered(token,nanos)}
        // Do not call MediaCodec from inside its callback; retain Media3's own
        // handling (including its old-Android callback deadlock workaround).
        next?.onFrameRendered(this,pts,nanos)
      },target)
      synchronized(this){if(captured===epoch)installed=true}
    } catch(_:RuntimeException) {synchronized(this){evidence?.unavailable("render_listener_unavailable")}}
  }
  override fun setOnFrameRenderedListener(listener:MediaCodecAdapter.OnFrameRenderedListener,handler:Handler) {
    val tapped=synchronized(this){upstream=listener;upstreamHandler=handler;evidence!=null}
    if(tapped)install() else delegate.setOnFrameRenderedListener(listener,handler)
  }
  fun output(model:NCContinuousMuxedPresentation,key:NCContinuousMuxedClipKey,rawPts:Long,localPts:Long,
    duration:Long,release:()->Unit) {
    val proof=model.renderedVideo
    if(proof==null){release();return}
    val needsListener=synchronized(this) {
      if(evidence!==proof) {
        if(pending.isNotEmpty())evidence?.unavailable("codec_owner_changed_pending")
        evidence=proof;pending.clear();epoch=Any();installed=false
      }
      !installed
    }
    if(needsListener)install()
    synchronized(this) {
      val token=proof.submitted(key,localPts,duration)
      if(token!=null) {
        if(pending.put(rawPts,token)!=null){proof.unavailable("render_pts_reused");pending.clear()}
      } else pending.clear()
    }
    try {release()} catch(error:Throwable) {proof.unavailable("render_release_failed");throw error}
  }
  private fun resetEvidence()=synchronized(this) {
    if(pending.isNotEmpty())evidence?.unavailable("codec_reset_pending")
    pending.clear();epoch=Any();installed=false
  }
  override fun flush() {resetEvidence();delegate.flush()}
  override fun release() {resetEvidence();delegate.release()}
}

@UnstableApi
private fun orderedVideoCodecFactory(factory:MediaCodecAdapter.Factory,handler:Handler)=
  object:MediaCodecAdapter.Factory {
    override fun createAdapter(configuration:MediaCodecAdapter.Configuration):MediaCodecAdapter =
      NCOrderedVideoCodec(factory.createAdapter(configuration),handler)
  }

/** Exact processed video-stream provenance, separate from audio receipt tokens.
 * No timestamps, frames, pacing or surface selection are changed here. */
@UnstableApi
internal class NCContinuousMuxedVideoRenderer(context:Context,factory:MediaCodecAdapter.Factory,
  selector:MediaCodecSelector,joiningMs:Long,fallback:Boolean,handler:Handler,
  listener:VideoRendererEventListener,dropped:Int,private val observation:NCContinuousMuxedObservation,
  private val controller:NCContinuousMuxedSinkController,
  private val outputSlot:()->NCContinuousMuxedSinkController.SinkSlot?):
  MediaCodecVideoRenderer(context,orderedVideoCodecFactory(factory,handler),selector,joiningMs,fallback,handler,listener,dropped) {
  private data class Origin(val model:NCContinuousMuxedPresentation,val key:NCContinuousMuxedClipKey,
    val start:Long,val offset:Long,val duration:Long)
  private val pending=java.util.ArrayDeque<Origin>()
  private var processed:Origin?=null
  private data class Output(val origin:Origin,val index:Int,val pts:Long)
  private var context:Output?=null
  private var capturedSlot:NCContinuousMuxedSinkController.SinkSlot?=null
  private fun targeted():NCContinuousMuxedSinkController.SinkSlot? {
    val current=outputSlot()?:fail()
    val captured=capturedSlot
    if(captured!=null &&captured!==current)fail()
    if(captured==null)capturedSlot=current
    return current.takeIf {controller.isTargeted(it)}
  }
  private fun fail():Nothing {
    (capturedSlot?:outputSlot())?.let {controller.invalidate(it,"video_origin")}
    throw IllegalStateException("NC native video output origin rejected")
  }
  private fun protect(model:NCContinuousMuxedPresentation) {
    if(!model.observeVideoProtection(this,pending.map {it.key}.toSet()+listOfNotNull(processed?.key)))fail()
  }
  override fun onStreamChanged(formats:Array<Format>,startPositionUs:Long,offsetUs:Long,
    mediaPeriodId:MediaSource.MediaPeriodId) {
    if(targeted()!=null) {
      val model=observation.model?:fail()
      val index=timeline.getIndexOfPeriod(mediaPeriodId.periodUid)
      if(index<0 ||mediaPeriodId.isAd ||formats.size!=1 ||formats[0].sampleMimeType!="video/avc")fail()
      val period=Timeline.Period();val window=Timeline.Window()
      timeline.getPeriod(index,period);timeline.getWindow(period.windowIndex,window)
      val key=observation.key(window.mediaItem.mediaId)?:fail()
      val previous=pending.peekLast()?:processed
      // An A/V period may include the AAC tail (observed 540000us for a
      // <=500000us video). Video provenance must use the registered, native-
      // validated frame layout, not the combined audio/video period duration.
      // Retain period validity/overflow checks; TIME_UNSET is normal while
      // progressive Media3 metadata is still loading.
      val duration=model.registeredVideoDurationUs(key)?:fail()
      val periodDuration=if(period.durationUs==C.TIME_UNSET)duration else period.durationUs
      val rejection=when {
        startPositionUs<0 ->1
        offsetUs !in 0..9007199254740991L ->2
        duration<=0 ||periodDuration<=0 ->3
        duration>9007199254740991L-offsetUs ||periodDuration>9007199254740991L-offsetUs ->4
        !model.hasRegisteredRange(key) ->5
        pending.size>=60 ->6
        previous?.let {it.model!==model ||key.ordinal!=it.key.ordinal+1 ||offsetUs<=it.offset}==true ->7
        previous==null &&key.ordinal!=0L ->8
        else ->0
      }
      if(rejection!=0) {
        // Terminal-only numeric provenance: no source identity, URI or chat.
        // Logging cannot weaken or replace the original fail-closed decision.
        try {Log.d("NCContinuousVideo","event=1 reason=$rejection ordinal=${key.ordinal} startUs=$startPositionUs "+
          "offsetUs=$offsetUs durationUs=${period.durationUs} pending=${pending.size} "+
          "previousOrdinal=${previous?.key?.ordinal?:-1} previousOffsetUs=${previous?.offset?:-1}")}
        catch(_:RuntimeException) {}
        fail()
      }
      pending.add(Origin(model,key,startPositionUs,offsetUs,duration));protect(model)
    } else {pending.clear();processed=null}
    super.onStreamChanged(formats,startPositionUs,offsetUs,mediaPeriodId)
  }
  override fun onOutputStreamOffsetUsChanged(offsetUs:Long) {
    if(targeted()!=null) {
      val next=pending.pollFirst()?:fail()
      if(next.model!==observation.model ||next.offset!=offsetUs ||next.start!=outputStreamStartPositionUs)fail()
      processed=next;protect(next.model)
    }
    super.onOutputStreamOffsetUsChanged(offsetUs)
  }
  override fun processOutputBuffer(positionUs:Long,elapsedRealtimeUs:Long,codec:MediaCodecAdapter?,buffer:ByteBuffer?,
    bufferIndex:Int,bufferFlags:Int,sampleCount:Int,bufferPresentationTimeUs:Long,isDecodeOnlyBuffer:Boolean,
    isLastBuffer:Boolean,format:Format):Boolean {
    val slot=targeted()?:return super.processOutputBuffer(positionUs,elapsedRealtimeUs,codec,buffer,bufferIndex,
      bufferFlags,sampleCount,bufferPresentationTimeUs,isDecodeOnlyBuffer,isLastBuffer,format)
    val origin=processed?:fail()
    if(origin.model!==observation.model ||origin.offset!=outputStreamOffsetUs
      ||origin.start!=outputStreamStartPositionUs ||bufferPresentationTimeUs<origin.offset
      ||bufferPresentationTimeUs-origin.offset>=origin.duration ||context!=null)fail()
    // A real input can precede timeline ACK. Leave that buffer outstanding,
    // rather than granting output or revoking a legitimate owner.
    if(!controller.beforeVideo(slot,origin.model,origin.key))return false
    context=Output(origin,bufferIndex,bufferPresentationTimeUs-origin.offset)
    return try {super.processOutputBuffer(positionUs,elapsedRealtimeUs,codec,buffer,bufferIndex,
      bufferFlags,sampleCount,bufferPresentationTimeUs,isDecodeOnlyBuffer,isLastBuffer,format)}
      finally {context=null}
  }
  private fun release(codec:MediaCodecAdapter,index:Int,pts:Long,delegate:()->Unit) {
    val slot=targeted()
    if(slot==null) {if(context!=null)fail();delegate();return}
    val output=context?:fail();val origin=output.origin
    if(index!=output.index ||pts!=output.pts ||origin!==processed ||origin.model!==observation.model)fail()
    if(!controller.submitVideo(slot,origin.model,origin.key) {
      if(codec is NCOrderedVideoCodec)codec.output(origin.model,origin.key,pts+origin.offset,pts,origin.duration,delegate)
      else {
        origin.model.renderedVideo?.unavailable("render_listener_missing")
        delegate()
      }
    })fail()
  }
  override fun renderOutputBuffer(codec:MediaCodecAdapter,bufferIndex:Int,presentationTimeUs:Long) =
    release(codec,bufferIndex,presentationTimeUs) {super.renderOutputBuffer(codec,bufferIndex,presentationTimeUs)}
  override fun renderOutputBufferV21(codec:MediaCodecAdapter,bufferIndex:Int,presentationTimeUs:Long,releaseTimeNs:Long) =
    release(codec,bufferIndex,presentationTimeUs) {super.renderOutputBufferV21(codec,bufferIndex,presentationTimeUs,releaseTimeNs)}
  private fun clearOrigins() {pending.clear();processed=null;context=null}
  override fun onDisabled() {targeted()?.let {controller.invalidate(it,"video_disable")};super.onDisabled();clearOrigins()}
  override fun onReset() {targeted()?.let {controller.invalidate(it,"video_reset")};super.onReset();clearOrigins()}
  override fun onRelease() {targeted()?.let {controller.invalidate(it,"video_release")};super.onRelease();clearOrigins()}
}
