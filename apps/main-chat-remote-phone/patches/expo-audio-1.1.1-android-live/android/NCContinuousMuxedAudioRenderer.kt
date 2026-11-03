package expo.modules.audio

import android.content.Context
import android.os.Handler
import androidx.media3.common.Format
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.exoplayer.audio.AudioRendererEventListener
import androidx.media3.exoplayer.audio.AudioSink
import androidx.media3.exoplayer.audio.MediaCodecAudioRenderer
import androidx.media3.exoplayer.mediacodec.MediaCodecAdapter
import androidx.media3.exoplayer.mediacodec.MediaCodecSelector
import androidx.media3.exoplayer.source.MediaSource
import java.nio.ByteBuffer

@UnstableApi
internal class NCContinuousMuxedAudioRenderer(context:Context,factory:MediaCodecAdapter.Factory,
  selector:MediaCodecSelector,fallback:Boolean,handler:Handler,listener:AudioRendererEventListener,
  sink:AudioSink,private val observation:NCContinuousMuxedObservation,
  private val controller:NCContinuousMuxedSinkController?=null,
  private val slot:NCContinuousMuxedSinkController.SinkSlot?=null):
  MediaCodecAudioRenderer(context,factory,selector,fallback,handler,listener,sink) {
  init {require((controller==null)==(slot==null))}
  private var inputToken:Long?=null
  private var inputModel:NCContinuousMuxedPresentation?=null
  private var inputOffsetUs=0L
  private var inputOrdinal:Long?=null
  private var inputPeriodEndUs:Long?=null
  private var inputPeriodUid:Any?=null
  override fun onStreamChanged(formats:Array<Format>,startPositionUs:Long,offsetUs:Long,
    mediaPeriodId:MediaSource.MediaPeriodId) {
    val model=observation.model
    inputModel=model;inputToken=null;inputOffsetUs=offsetUs;inputOrdinal=null;inputPeriodEndUs=null
    inputPeriodUid=mediaPeriodId.periodUid
    if(model!=null) {
      val period=Timeline.Period()
      val window=Timeline.Window()
      val index=timeline.getIndexOfPeriod(mediaPeriodId.periodUid)
      val key=if(index>=0) {
        timeline.getPeriod(index,period)
        timeline.getWindow(period.windowIndex,window)
        if(period.durationUs>=0 && offsetUs in 0..9007199254740991L
          && period.durationUs<=9007199254740991L-offsetUs)inputPeriodEndUs=offsetUs+period.durationUs
        observation.key(window.mediaItem.mediaId)
      } else null
      if(key==null || formats.size!=1)model.fence("period_identity")
      else {inputOrdinal=key.ordinal;inputToken=model.recordInputStream(mediaPeriodId,startPositionUs,offsetUs,key,formats[0])}
    }
    // Parent can synchronously publish the first processed offset.
    super.onStreamChanged(formats,startPositionUs,offsetUs,mediaPeriodId)
  }
  override fun render(positionUs:Long,elapsedRealtimeUs:Long) {
    if(slot!=null && controller?.renderCheckpoint(slot)!=true)return
    observation.rendererPosition(positionUs,inputPeriodEndUs)
    super.render(positionUs,elapsedRealtimeUs)
    if(slot!=null && controller?.renderCheckpoint(slot)!=true)return
    if(hasReadStreamToEnd())inputToken?.let {token ->
      inputModel?.recordReadEnd(token,lastBufferInStreamPresentationTimeUs-inputOffsetUs)
    }
    observation.sampleTrack()
    slot?.let {controller?.requestPresentation(it)}
  }
  override fun onOutputStreamOffsetUsChanged(offsetUs:Long) {
    observation.processed(outputStreamStartPositionUs,offsetUs)
    super.onOutputStreamOffsetUsChanged(offsetUs)
  }
  override fun onProcessedOutputBuffer(presentationTimeUs:Long) {
    // Attribute old output before parent advances its private stream queue.
    observation.processedOutput(presentationTimeUs)
    super.onProcessedOutputBuffer(presentationTimeUs)
  }
  override fun onProcessedStreamChange() {
    observation.beginNaturalChange()
    try {super.onProcessedStreamChange()} finally {observation.endNaturalChange()}
  }
  override fun processOutputBuffer(positionUs:Long,elapsedRealtimeUs:Long,codec:MediaCodecAdapter?,
    buffer:ByteBuffer?,bufferIndex:Int,bufferFlags:Int,sampleCount:Int,
    bufferPresentationTimeUs:Long,isDecodeOnlyBuffer:Boolean,isLastBuffer:Boolean,format:Format):Boolean {
    observation.beginOutput(bufferPresentationTimeUs,isDecodeOnlyBuffer,isLastBuffer)
    return try {super.processOutputBuffer(positionUs,elapsedRealtimeUs,codec,buffer,bufferIndex,
      bufferFlags,sampleCount,bufferPresentationTimeUs,isDecodeOnlyBuffer,isLastBuffer,format)}
      finally {observation.endOutput()}
  }
  override fun onPositionReset(positionUs:Long,joining:Boolean) {
    observation.beginPositionReset(positionUs)
    if(!observation.permitsInitialCleanup())slot?.let {controller?.invalidate(it,"renderer_seek")}
    try {super.onPositionReset(positionUs,joining)} finally {observation.endPositionReset()}
  }
  override fun onReset() {
    slot?.let {controller?.invalidate(it,"renderer_reset")}
    observation.fence("renderer_reset");super.onReset()
  }
  override fun onDisabled() {
    // The enrolled lane must be denied before parent cleanup can throw.
    // Untouched ordinary renderers keep their original disable behavior.
    slot?.let {if(controller?.isTargeted(it)==true)controller.invalidate(it,"renderer_disable")}
    super.onDisabled()
  }
  override fun onStopped() {
    // Reuse only the original controller evaluation; never sample for attribution.
    val ended=if(slot!=null && controller!=null)super.isEnded() else null
    recordBoundary(2,ended)
    var normal=false;var heldEof=false;var buffering=false
    slot?.let {
      val actualEnded=ended!!
      normal=controller?.beginNormalRendererStop(it,actualEnded)==true
      if(!normal && !actualEnded && !isCurrentStreamFinal) {
        NCContinuousMuxedTailSource.HeldEof.observePlaylist(stream,inputModel,inputPeriodUid)?.let {witness->
          heldEof=true
          buffering=controller?.beginBufferingRendererStop(it,witness,actualEnded,isCurrentStreamFinal)==true
        }
      }
    }
    observation.rendererStopDecision(normal,heldEof,buffering)
    try {super.onStopped()} finally {slot?.let {controller?.endNormalRendererStop(it)}}
  }
  override fun renderToEndOfStream() {
    recordBoundary(1,null)
    super.renderToEndOfStream()
  }
  private fun recordBoundary(callback:Int,ended:Boolean?) {
    if(observation.model==null)return
    try {observation.rendererBoundary(callback,inputOrdinal,hasReadStreamToEnd(),isCurrentStreamFinal,
      ended,state,lastBufferInStreamPresentationTimeUs-inputOffsetUs)}
    catch(_:RuntimeException) {} // Attribution never replaces the normal renderer operation.
  }
  override fun onRelease() {
    slot?.let {controller?.invalidate(it,"renderer_release")}
    observation.fence("renderer_release");super.onRelease()
  }
}
