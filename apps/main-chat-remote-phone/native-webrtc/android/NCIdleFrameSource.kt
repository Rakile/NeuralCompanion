package expo.modules.audio

import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.Image
import org.webrtc.EglBase
import org.webrtc.EglRenderer
import org.webrtc.GlRectDrawer
import org.webrtc.JavaI420Buffer
import org.webrtc.VideoFrame
import org.webrtc.YuvHelper
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.view.Surface
import java.io.File
import java.util.concurrent.atomic.AtomicLong

/** One held decoder output, not a decoded-loop cache. Never owns audio/focus.
 * Public operations run on main; file IO/decode/release run on a private worker.
 * Decoded readiness cannot produce a presentation observation: only the actual
 * codec render callback for the still-current request may do so.
 */
internal class NCIdleFrameSource @JvmOverloads constructor(private val file: File, generation: String, motionId: String,
  sourceFrameCount: Int, private val fps: Int, private val surface: Surface,
  private val presented: (NCIdleFrameState.Presented) -> Unit, private val retainedFrames: Int = 0) {
  // Validate before allocating the worker; a rejected source has no owner to
  // close it and must not leave a thread behind.
  init { require(fps in listOf(6,8,12,24) && retainedFrames in 0..12); checkMain() }
  class Frame internal constructor(internal val request: NCIdleFrameState.Request,
    internal val epoch: Long, val sourceFrame: Int, val pts: Long, internal val codecPts: Long)
  private val state = NCIdleFrameState(generation,motionId,sourceFrameCount)
  private val step = 24/fps
  private val loopTicks = ((sourceFrameCount+step-1)/step)*step
  private val main = Handler(Looper.getMainLooper())
  private val thread = HandlerThread("nc-idle-frame").apply { start() }
  private val worker = Handler(thread.looper)
  private val serial = AtomicLong()
  @Volatile private var closed = false
  @Volatile var failureReason = ""; private set
  var renderCallbackPts = -1L; private set
  private var candidate: Frame? = null
  private var renderedFrame: Frame? = null
  private var renderedAt = 0L
  private var completion: ((Frame?) -> Unit)? = null
  private var closeFinished = false
  private val closeCallbacks = mutableListOf<() -> Unit>()
  // Worker-owned only.
  private var extractor: MediaExtractor? = null
  private var decoder: MediaCodec? = null
  private var decoderPrimed = false
  private var inputCycle = 0L
  private var lastDecodedTick = -1L
  private var heldIndex = -1
  private var heldEpoch = -1L
  private data class Cached(val pts: Long, val buffer: JavaI420Buffer) {
    val bytes: Long get() = buffer.width.toLong()*buffer.height + 2L*((buffer.width+1)/2)*((buffer.height+1)/2)
  }
  private val window = LinkedHashMap<Int,Cached>()
  @Volatile var retainedCount = 0; private set
  @Volatile var retainedBytes = 0L; private set
  private var gpu: EglRenderer? = null
  private var gpuListener: EglRenderer.FrameListener? = null
  private var planeRow = ByteArray(0)
  private fun checkMain() { check(Looper.myLooper() == Looper.getMainLooper()) }
  private fun live(epoch: Long) = !closed && serial.get() == epoch
  fun prepareFrame(sourceFrame: Int, done: (Frame?) -> Unit) {
    checkMain()
    val request = state.request(sourceFrame)
    if (request == null) { done(null); return }
    val epoch = serial.incrementAndGet()
    renderCallbackPts = -1
    val previous = completion; completion = done; candidate = null; renderedFrame = null; previous?.invoke(null)
    val deadline = System.nanoTime()+1_800_000_000L
    worker.post { decode(request,epoch,deadline) }
  }
  private fun open() {
    if (decoder != null) return
    val source = MediaExtractor(); extractor = source
    source.setDataSource(file.absolutePath)
    require(source.trackCount == 1)
    val format = source.getTrackFormat(0)
    require(format.getString("mime") == "video/avc")
    source.selectTrack(0)
    val codec = MediaCodec.createDecoderByType("video/avc"); decoder = codec
    if (retainedFrames > 0) format.setInteger(MediaFormat.KEY_COLOR_FORMAT,
      MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
    codec.configure(format,if (retainedFrames > 0) null else surface,null,0); codec.start()
  }
  private fun releaseHeld() {
    if (heldIndex >= 0) decoder?.releaseOutputBuffer(heldIndex,false)
    heldIndex = -1; heldEpoch = -1
  }
  private fun decode(request: NCIdleFrameState.Request, epoch: Long, deadline: Long) {
    if (!live(epoch)) return
    try {
      val targetFrame = request.sourceFrame/step*step
      window[targetFrame]?.let { cached ->
        deliver(request,epoch,cached.pts,cached.pts); return
      }
      val sequential = decoder != null && lastDecodedTick >= 0 &&
        targetFrame.toLong() == (lastDecodedTick+step)%loopTicks
      releaseHeld()
      // An early flush can discard the H.264 codec configuration submitted by
      // start(). Recreate a cancelled, unprimed decoder instead; only a decoder
      // that has produced its format/output is safe to flush for another seek.
      if (decoder != null && !decoderPrimed) cleanupDecoder()
      if (decoder != null && !sequential) decoder?.flush()
      open()
      val codec = decoder ?: return; val source = extractor ?: return
      val targetTick = if (sequential) lastDecodedTick+step else targetFrame.toLong()
      val targetUs = targetTick*1_000_000/24
      if (!sequential) {
        source.seekTo(targetUs,MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
        inputCycle = 0; lastDecodedTick = -1
      }
      val info = MediaCodec.BufferInfo()
      while (live(epoch) && System.nanoTime() < deadline) {
        val input = codec.dequeueInputBuffer(1000)
        if (input >= 0) {
          val buffer = codec.getInputBuffer(input)!!
          var size = source.readSampleData(buffer,0)
          if (size < 0) {
            // Each cache loop begins with an IDR. Feed the next compressed
            // cycle on a monotonic codec clock instead of flushing at every
            // visible wrap. Codec buffers stay bounded; no decoded-loop cache.
            source.seekTo(0,MediaExtractor.SEEK_TO_PREVIOUS_SYNC); inputCycle++
            size = source.readSampleData(buffer,0)
          }
          check(size > 0)
          codec.queueInputBuffer(input,0,size,source.sampleTime+inputCycle*loopTicks*1_000_000/24,0)
          source.advance()
        }
        val output = codec.dequeueOutputBuffer(info,1000)
        if (output == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) decoderPrimed = true
        if (output >= 0) {
          decoderPrimed = true
          val codecPts = info.presentationTimeUs
          val tick = (codecPts*24+500_000)/1_000_000
          val pts = codecPts-(tick/loopTicks)*loopTicks*1_000_000/24
          if (retainedFrames > 0 && info.size > 0) {
            // Decode a bounded window on the worker, including preroll. Reverse
            // anticipation then reads exact decoded frames without codec seeks.
            val decoded = codec.getOutputImage(output) ?: error("missing_yuv_image")
            try { remember(((pts*24+500_000)/1_000_000).toInt(),pts,decoded) }
            finally { decoded.close() }
          }
          if (info.size > 0 && info.presentationTimeUs >= targetUs-1) {
            if (retainedFrames > 0) codec.releaseOutputBuffer(output,false)
            else { heldIndex = output; heldEpoch = epoch }
            lastDecodedTick = tick
            deliver(request,epoch,pts,codecPts)
            return
          }
          codec.releaseOutputBuffer(output,false)
        }
      }
      main.post { fail(request,epoch) }
    } catch (error: Exception) {
      // A decoder failure invalidates only visual preparation, never speech.
      failureReason = "decoder_" + error.javaClass.simpleName
      cleanupDecoder(); main.post { fail(request,epoch) }
    }
  }
  private fun deliver(request: NCIdleFrameState.Request, epoch: Long, pts: Long, codecPts: Long) {
    main.post {
      if (live(epoch) && state.decoded(request,pts,1_000_000)) {
        candidate = Frame(request,epoch,((pts*24+500_000)/1_000_000).toInt(),pts,codecPts)
        val callback = completion; completion = null; callback?.invoke(candidate)
      } else if (live(epoch)) fail(request,epoch)
    }
  }
  private fun remember(index: Int, pts: Long, image: Image) {
    val crop = image.cropRect
    val width = crop.width(); val height = crop.height()
    // Independent byte cap as well as frame cap; reject unexpected oversized
    // media rather than allocate a whole loop or silently lower its quality.
    require(width > 0 && height > 0 && width.toLong()*height <= 1920L*1080)
    val planes = image.planes; require(planes.size == 3)
    val size = width.toLong()*height + 2L*((width+1)/2)*((height+1)/2)
    window.remove(index)?.buffer?.release()
    while (window.size >= retainedFrames || window.values.sumOf { it.bytes }+size > 48L*1024*1024) {
      val oldest = window.entries.first(); window.remove(oldest.key); oldest.value.buffer.release()
    }
    val frame = JavaI420Buffer.allocate(width,height)
    try {
      val targets = listOf(frame.dataY,frame.dataU,frame.dataV)
      val strides = listOf(frame.strideY,frame.strideU,frame.strideV)
      for (i in 0..2) {
        val div = if (i == 0) 1 else 2
        val w = (width+div-1)/div; val h = (height+div-1)/div
        val plane = planes[i]; val input = plane.buffer.duplicate()
        val offset = input.position()+crop.top/div*plane.rowStride+crop.left/div*plane.pixelStride
        if (plane.pixelStride == 1) {
          input.position(offset)
          YuvHelper.copyPlane(input.slice(),plane.rowStride,targets[i],strides[i],w,h)
        } else {
          if (planeRow.size < w*plane.pixelStride) planeRow = ByteArray(w*plane.pixelStride)
          val output = targets[i]
          for (y in 0 until h) {
            input.position(offset+y*plane.rowStride)
            input.get(planeRow,0,(w-1)*plane.pixelStride+1)
            output.position(y*strides[i])
            for (x in 0 until w) output.put(planeRow[x*plane.pixelStride])
          }
          output.rewind()
        }
      }
      window[index] = Cached(pts,frame)
      retainedCount = window.size; retainedBytes = window.values.sumOf { it.bytes }
    } catch (error: Exception) { frame.release(); throw error }
  }
  private fun fail(request: NCIdleFrameState.Request, epoch: Long) {
    if (!live(epoch) || !state.current(request)) return
    if (failureReason.isEmpty()) failureReason = "decoder_timeout_or_invalid_pts"
    candidate = null; val callback = completion; completion = null; callback?.invoke(null)
  }
  fun submit(frame: Frame, rendered: (Frame, Long) -> Unit): Boolean {
    checkMain()
    if (candidate !== frame || !state.current(frame.request) || !live(frame.epoch)) return false
    candidate = null
    worker.post {
      if (retainedFrames > 0) {
        if (!live(frame.epoch)) return@post
        try {
          val cached = window[frame.sourceFrame] ?: error("evicted_frame")
          val renderer = gpu ?: EglRenderer("nc-idle-window").also {
            it.init(null,EglBase.CONFIG_PLAIN,GlRectDrawer()); it.createEglSurface(surface); gpu = it
          }
          val nanos = System.nanoTime()
          // The synchronous removal also fences previous queued GL work when
          // a decode/presentation was cancelled. Only one render is in flight.
          gpuListener?.let { renderer.removeFrameListener(it) }
          val listener = EglRenderer.FrameListener {
            main.post { if (live(frame.epoch)) {
              renderCallbackPts = frame.pts; renderedFrame = frame; renderedAt = nanos; rendered(frame,nanos)
            } }
          }
          gpuListener = listener
          renderer.addFrameListener(listener,0f)
          cached.buffer.retain()
          val picture = VideoFrame(cached.buffer,0,nanos)
          try {
            renderer.setLayoutAspectRatio(cached.buffer.width.toFloat()/cached.buffer.height)
            renderer.onFrame(picture)
          } finally { picture.release() }
          // Neither queueing nor the GL callback alone is presentation. The
          // owner also requires a current TextureView update; native probes
          // independently inspect pixels. Surface timestamps can remain zero.
        } catch (_: Exception) { main.post { fail(frame.request,frame.epoch) } }
        return@post
      }
      if (!live(frame.epoch) || heldEpoch != frame.epoch || heldIndex < 0) return@post
      try {
        val codec = decoder ?: return@post
        codec.setOnFrameRenderedListener({ _, pts, nanos ->
          renderCallbackPts = pts
          if (live(frame.epoch) && pts == frame.codecPts) {
            renderedFrame = frame; renderedAt = nanos; rendered(frame,nanos)
          }
        },main)
        val index = heldIndex; heldIndex = -1; heldEpoch = -1
        codec.releaseOutputBuffer(index,frame.codecPts*1000)
      } catch (_: Exception) { cleanupDecoder(); main.post { fail(frame.request,frame.epoch) } }
    }
    return true
  }
  fun confirmPresented(frame: Frame, observedAtNanos: Long, visible: Boolean): Boolean {
    checkMain()
    if (!visible || renderedFrame !== frame || !live(frame.epoch) || observedAtNanos < renderedAt) return false
    val observation = state.present(frame.request,observedAtNanos,true) ?: return false
    renderedFrame = null; presented(observation); return true
  }
  fun observe(): NCIdleFrameState.Presented? { checkMain(); return state.observe() }
  fun pause() {
    checkMain(); serial.incrementAndGet(); state.pause(); candidate = null; renderedFrame = null
    val callback = completion; completion = null; callback?.invoke(null)
    worker.post { try { releaseHeld() } catch (_: Exception) { cleanupDecoder() } }
  }
  private fun cleanupDecoder() {
    decoderPrimed = false
    inputCycle = 0; lastDecodedTick = -1
    heldIndex = -1; heldEpoch = -1
    try { decoder?.stop() } catch (_: Exception) {}
    try { decoder?.release() } catch (_: Exception) {}
    decoder = null; extractor?.release(); extractor = null
  }
  @JvmOverloads fun close(done: () -> Unit = {}) {
    checkMain()
    if (closeFinished) { done(); return }
    closeCallbacks.add(done)
    if (closed) return
    closed = true; serial.incrementAndGet(); state.close(); candidate = null; renderedFrame = null
    val callback = completion; completion = null; callback?.invoke(null)
    worker.post {
      cleanupDecoder(); gpu?.release(); gpu = null; gpuListener = null
      window.values.forEach { it.buffer.release() }; window.clear(); planeRow = ByteArray(0)
      retainedCount = 0; retainedBytes = 0; thread.quitSafely()
      main.post {
        closeFinished = true
        val callbacks = closeCallbacks.toList(); closeCallbacks.clear()
        callbacks.forEach { it() }
      }
    }
  }
}
