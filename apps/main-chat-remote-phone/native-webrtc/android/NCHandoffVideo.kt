package expo.modules.audio

import android.media.Image
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Handler
import android.os.Looper
import android.view.TextureView
import android.widget.FrameLayout
import java.io.File
import java.util.concurrent.ArrayBlockingQueue
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicBoolean
import org.webrtc.JavaI420Buffer
import org.webrtc.VideoFrame
import org.webrtc.YuvHelper

/** Silent ordered H.264 for cached cycles and retained chunks. Retained/RTP
 * transition capability stays disabled until its combined native gate passes.
 * Compressed files supply repeats; each of two sequential decoders has three
 * queued pictures plus at most one copy awaiting queue space. No reverse seek,
 * decoded-loop cache or audio authority.
 * Public operations and observer callbacks are main-thread only. */
class NCHandoffVideo(private val host: FrameLayout, private val observer: Observer) {
  interface Observer {
    fun presented(view: TextureView, segment: Int, positionMs: Int, atNs: Long)
    fun failed(reason: String)
    /** Failure-only primitives copied before clear destroys pending proof. */
    fun failureEvidence(reason: String, details: Map<String,Any>) {}
    /** Recoverable delay only; the owner forwards selected/visible slots. */
    fun cadenceEvidence(details: Map<String,Any>) {}
  }
  private val main = Handler(Looper.getMainLooper())
  private val io = Executors.newSingleThreadExecutor()
  private val decoders = Executors.newFixedThreadPool(2)
  private var revision = 0
  private var generation = ""
  private var plan = ""
  private var indices = intArrayOf()
  private var chunkTicks = 12
  private var chunkWindow: NCIdleChunkWindow? = null
  private val files = mutableMapOf<Int,File>()
  private val pending = mutableSetOf<Int>()
  private var current: Slot? = null
  private var next: Slot? = null
  private var view: NCTextureVideo? = null
  private var closed = false
  private var submitted: Picture? = null
  private var gpuReady = false
  private var textureReady = false
  private var submittedAt = 0L
  private var submittedNeedsResubmit = false
  private var heldPicture: Picture? = null
  private var reobserving = false
  private var dueAt = 0L
  private var clockAt = 0L
  private var elapsedTicks = 0L
  private var lastTick = -1
  private var observations = 0
  private var waitingAt = 0L
  private var exitTick = 0L
  private var exitAt = 0L
  private var exitState = "none"
  private var exitSourceTick = -1
  private var pausedAt = 0L
  private var initialTick = 0
  private var observedAt = 0L
  private var cachedId = ""
  private var maximumTick: Int? = null
  // One bounded timing record per presented picture. Capture worker callbacks
  // before posting to main so UI queue delay is not mislabeled as decode/GPU time.
  private var timing: Map<String,Long> = emptyMap()
  private var wakeLateNs = 0L
  private var frameDueAt = 0L
  private var textureAt = 0L
  private var textureHandledAt = 0L
  private var gpuHandledAt = 0L
  private var frameWaitNs = 0L
  private val cadence = NCCachedFrameCadence { observer.cadenceEvidence(it) }
  // One counter per lifetime. A new plan cannot delay or satisfy an older
  // plan's detach fence. Includes validation IO as well as codec workers.
  private var work = AtomicInteger()
  private var detachFailed = AtomicBoolean()
  private val retiringWork = mutableListOf<Pair<AtomicInteger,AtomicBoolean>>()
  var state = "ended"; private set
  private data class Picture(val buffer: JavaI420Buffer, val tick: Int, val step: Int,
    val decodedAt: Long = System.nanoTime(), @Volatile var gpuAt: Long = 0L)
  private fun checkMain() { check(Looper.myLooper() == Looper.getMainLooper()) }

  private inner class Slot(val index: Int, val file: File, val ticks: Int, val startTick: Int = 0) {
    private val lifetimeWork = work
    private val lifetimeFailure = detachFailed
    val pictures = ArrayBlockingQueue<Picture>(3)
    @Volatile var cancelled = false
    @Volatile var finished = false
    @Volatile var detached = false
    @Volatile var failure = ""
    fun start() {
      lifetimeWork.incrementAndGet()
      decoders.execute { try { decode() } finally { lifetimeWork.decrementAndGet() } }
    }
    fun dispose() {
      cancelled = true
      while (true) { val picture = pictures.poll() ?: break; picture.buffer.release() }
    }
    private fun decode() {
      val source = MediaExtractor(); var codec: MediaCodec? = null
      try {
        if (cancelled) return
        source.setDataSource(file.absolutePath); source.selectTrack(0)
        val format = source.getTrackFormat(0)
        val fps = format.getInteger(MediaFormat.KEY_FRAME_RATE)
        require(fps in listOf(6,8,12,24))
        val step = 24/fps
        if (startTick > 0) source.seekTo(startTick*1_000_000L/24,MediaExtractor.SEEK_TO_PREVIOUS_SYNC)
        format.setInteger(MediaFormat.KEY_COLOR_FORMAT,MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible)
        codec = MediaCodec.createDecoderByType("video/avc")
        codec.configure(format,null,null,0); codec.start()
        val info = MediaCodec.BufferInfo(); var eof = false; var previousTick = -1
        var progressAt = System.nanoTime()
        while (!cancelled) {
          if (!eof) {
            val slot = codec.dequeueInputBuffer(1000)
            if (slot >= 0) {
              val size = source.readSampleData(codec.getInputBuffer(slot)!!,0)
              if (size < 0) { codec.queueInputBuffer(slot,0,0,0,MediaCodec.BUFFER_FLAG_END_OF_STREAM); eof = true }
              else { codec.queueInputBuffer(slot,0,size,source.sampleTime,0); source.advance() }
            }
          }
          val slot = codec.dequeueOutputBuffer(info,1000)
          if (slot >= 0) {
            try {
              if (info.size > 0) {
                val tick = ((info.presentationTimeUs*24+500000)/1000000).toInt()
                require(tick in 0 until ticks && tick%step == 0 &&
                  (if (previousTick < 0) tick <= startTick else tick == previousTick+step))
                if (tick >= startTick) {
                  val image = codec.getOutputImage(slot) ?: error("missing_image")
                  val buffer = try { copy(image) } finally { image.close() }
                  val picture = Picture(buffer,tick,step)
                  var offered = false
                  try {
                    while (!cancelled && !offered) offered = pictures.offer(picture,20,TimeUnit.MILLISECONDS)
                  } finally { if (!offered) buffer.release() }
                }
                previousTick = tick; progressAt = System.nanoTime()
              }
            } finally { codec.releaseOutputBuffer(slot,false) }
            if ((info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
              require(previousTick == ((ticks-1)/step)*step); break
            }
          }
          check(System.nanoTime()-progressAt < 2_000_000_000L) { "decode_timeout" }
        }
      } catch (error: Exception) { if (!cancelled) failure = "decode_"+error.javaClass.simpleName }
      finally {
        try { codec?.stop() } catch (_:Exception) {}
        var safe = true
        try { codec?.release() } catch (_:Exception) { safe = false }
        try { source.release() } catch (_:Exception) { safe = false }
        if (!safe) { lifetimeFailure.set(true); if (!cancelled) failure = "decode_detach_failed" }
        detached = safe; finished = true; if (cancelled) dispose()
      }
    }
  }

  private fun copy(image: Image): JavaI420Buffer {
    val crop = image.cropRect; val width = crop.width(); val height = crop.height()
    require(width in 1..448 && height in 1..672 && image.planes.size == 3)
    val result = JavaI420Buffer.allocate(width,height)
    try {
      val targets = listOf(result.dataY,result.dataU,result.dataV)
      val strides = listOf(result.strideY,result.strideU,result.strideV)
      for (i in 0..2) {
        val div = if (i == 0) 1 else 2; val w = (width+div-1)/div; val h = (height+div-1)/div
        val plane = image.planes[i]; val input = plane.buffer.duplicate()
        val offset = input.position()+crop.top/div*plane.rowStride+crop.left/div*plane.pixelStride
        if (plane.pixelStride == 1) {
          input.position(offset); YuvHelper.copyPlane(input.slice(),plane.rowStride,targets[i],strides[i],w,h)
        } else {
          val row = ByteArray((w-1)*plane.pixelStride+1)
          for (y in 0 until h) {
            input.position(offset+y*plane.rowStride); input.get(row)
            targets[i].position(y*strides[i])
            for (x in 0 until w) targets[i].put(row[x*plane.pixelStride])
          }
          targets[i].rewind()
        }
      }
      return result
    } catch (error:Exception) { result.release(); throw error }
  }

  fun begin(owner: String, id: String, sequence: IntArray, sourceCount: Int): Boolean {
    checkMain()
    if (closed || !owner.matches(Regex("[a-f0-9]{32}")) || !id.matches(Regex("[a-f0-9]{32}"))
      || sourceCount !in 1..1440 || sequence.size !in 1..1440 || sequence.any { it !in 0 until sourceCount }) return false
    clear(); generation = owner; plan = id; indices = sequence.copyOf(); state = "waiting"
    val token = revision
    view = NCTextureVideo(host.context) {
      // Defer readback/removal outside TextureView's display-list traversal.
      val picture = submitted
      val at = System.nanoTime()
      main.post { if (token == revision && picture != null && submitted === picture && at >= submittedAt) {
        textureAt = at; textureHandledAt = System.nanoTime(); textureReady = true; confirm()
      } }
    }.also { host.addView(it,FrameLayout.LayoutParams(-1,-1)) }
    waitingAt = System.nanoTime(); schedule(token,0)
    return true
  }
  /** The complete cached cycle uses the same observed source clock. This is
   * sequential playback of its encoded forward/backward sequence, not seeks. */
  fun beginCycle(owner: String, id: String, sourceCount: Int): Boolean {
    return beginCycleAt(owner,id,sourceCount,0)
  }
  fun beginCycleAt(owner: String, id: String, sourceCount: Int, startTick: Int): Boolean {
    if (sourceCount !in 1..1440 || startTick !in 0 until sourceCount) return false
    if (!begin(owner,id,IntArray(sourceCount) { it },sourceCount)) return false
    chunkTicks = sourceCount; initialTick = startTick
    return true
  }
  /** Complete half-second files are appended ahead of playback. Only two
   * sequential decoders run; the six-file window is not a playback clock. */
  fun beginChunks(owner: String, id: String, sourceCount: Int, startFrame: Int): Boolean {
    if (sourceCount !in 1..1440 || startFrame !in 0 until sourceCount) return false
    if (!begin(owner,id,IntArray(12) { (startFrame+it)%sourceCount },sourceCount)) return false
    chunkWindow = NCIdleChunkWindow(sourceCount,startFrame)
    return true
  }
  fun setPaused(value: Boolean) {
    checkMain()
    if (value && pausedAt == 0L) {
      cadence.reset()
      pausedAt = System.nanoTime()
      if (submitted != null) submittedNeedsResubmit = true
    }
    else if (!value && pausedAt != 0L) {
      cadence.reset()
      val elapsed = System.nanoTime()-pausedAt
      if (clockAt != 0L) { clockAt += elapsed; dueAt += elapsed }
      if (waitingAt != 0L) waitingAt += elapsed
      if (submitted != null) submittedAt += elapsed
      pausedAt = 0L
    }
  }
  fun beginCachedCycle(owner: String, id: String, contentId: String, sourceCount: Int, startTick: Int): Boolean {
    if (!contentId.matches(Regex("[a-f0-9]{64}")) || !beginCycleAt(owner,id,sourceCount,startTick)) return false
    cachedId = contentId
    return true
  }
  fun layout() { view?.layoutVideo() }
  /** TextureView may recreate its surface while a prepared entry is paused.
   * Repaint the last exact picture; do not substitute an OnDraw for GPU proof
   * or advance the source clock a second time for the restored picture. */
  fun restoreSurface() {
    checkMain()
    cadence.reset()
    observedAt = 0L
    if (submitted == null) heldPicture?.let {
      it.buffer.retain(); submitted = it; reobserving = true
    }
    if (submitted != null) submittedNeedsResubmit = true
  }
  /** Re-observe a paused prepared image when its layer is selected. No decode
   * or clock advancement: wait for the native draw traversal before releasing
   * the next picture, so the selected opening isn't silently skipped. */
  fun observeSelected(done: ()->Unit) {
    checkMain()
    val output = view ?: return
    if (lastTick < 0 || pausedAt == 0L) return
    val token = revision
    val tree = host.viewTreeObserver
    var fired = false
    val listener = object: android.view.ViewTreeObserver.OnDrawListener {
      override fun onDraw() {
        if (fired || host.alpha <= 0f || !host.isShown) return
        fired = true
        main.post {
          if (tree.isAlive) tree.removeOnDrawListener(this)
          if (token == revision && !closed && view === output) {
            observedAt = System.nanoTime()
            observer.presented(output,lastTick/chunkTicks,(lastTick%chunkTicks)*1000/24,observedAt)
            if (token == revision && !closed) done()
          }
        }
      }
    }
    tree.addOnDrawListener(listener); host.invalidate()
    main.postDelayed({ if (tree.isAlive) tree.removeOnDrawListener(listener) },2000)
  }
  /** A speech opening follows hardware-heard samples and must never repeat.
   * This only limits silent pictures; it cannot start or acknowledge audio. */
  fun limitTo(tick: Int) { checkMain(); maximumTick = tick.coerceIn(0,(indices.size-1).coerceAtLeast(0)) }
  /** Reuse the prepared opening's surface; don't cold-start another renderer
   * at the speech boundary. Never overwrite a local picture still in flight. */
  fun streamFrame(frame: VideoFrame, presented: (TextureView,Long)->Unit): Boolean {
    checkMain()
    val target = view ?: return false
    if (closed || submitted != null || observedAt == 0L) return false
    val token = revision; setPaused(true)
    target.onFrameTracked(frame) { if (token == revision && !closed) presented(target,System.nanoTime()) }
    return true
  }
  /** Visual-only rendezvous on the existing encoded loop's next entry. The
   * returned monotonic time is scheduling metadata, never an audio receipt.
   * If no incoming surface takes over, continue the encoded loop without a
   * frozen picture. A missed appointment can be re-armed for the next cycle. */
  fun armExit(owner: String, id: String, minLeadMs: Int, maxLeadMs: Int): Long {
    return armTick(owner,id,0,minLeadMs,maxLeadMs)
  }
  /** A full cached cycle can leave at the desktop's chosen source frame,
   * not just at file wrap. This schedules an existing plan; it predicts nothing. */
  fun armSourceExit(owner: String, id: String, sourceFrame: Int, minLeadMs: Int, maxLeadMs: Int): Long {
    checkMain()
    if (chunkTicks != indices.size || indices.indices.any { indices[it] != it }
      || sourceFrame !in indices.indices) return 0
    return armTick(owner,id,sourceFrame,minLeadMs,maxLeadMs)
  }
  private fun armTick(owner: String, id: String, sourceTick: Int, minLeadMs: Int, maxLeadMs: Int): Long {
    checkMain()
    if (closed || chunkWindow != null || owner != generation || id != plan || clockAt == 0L || pausedAt != 0L || indices.isEmpty()
      || minLeadMs !in 0..2000 || maxLeadMs !in minLeadMs..2000
      || state !in listOf("prepared","presented","waiting")) return 0
    if (exitState != "none") {
      if (exitSourceTick != sourceTick) return 0
      if (exitState == "armed") return exitAt
      if (exitState != "missed") return 0
    }
    val now = System.nanoTime()
    val length = indices.size.toLong()
    // A previous decode/display stall can leave the sequential reader behind
    // its nominal clock. Arm from the observed picture, not a frame it should
    // have reached. Rebase only a full-frame lag, only on a successful arm.
    val shownTick = ((elapsedTicks-1).coerceAtLeast(0)/length)*length+lastTick
    val lag = (observedAt-(clockAt+shownTick*1_000_000_000L/24))
      .takeIf { lastTick >= 0 && it > 1_000_000_000L/24 } ?: 0L
    val reference = clockAt+lag
    val earliest = maxOf(elapsedTicks,((now+minLeadMs*1_000_000L-reference)*24+999_999_999L)/1_000_000_000L)
    val cycles = ((earliest-sourceTick+length-1)/length).coerceAtLeast(0)
    val boundary = sourceTick+cycles*length
    val at = reference+boundary*1_000_000_000L/24
    if (at-now > maxLeadMs*1_000_000L || at < now) return 0
    clockAt = reference; dueAt += lag
    exitTick = boundary; exitAt = at; exitState = "armed"; exitSourceTick = sourceTick
    return at
  }
  fun append(owner:String,id:String,index:Int,file:File,done:(Boolean)->Unit) {
    if (chunkWindow != null) { done(false); return }
    appendFile(owner,id,index,file,null,null,done)
  }
  fun appendChunk(owner:String,id:String,index:Int,file:File,sequence:IntArray,sha:String,done:(Boolean)->Unit) {
    if (chunkWindow?.canAppend(index,sequence) != true || !sha.matches(Regex("[a-f0-9]{64}"))) { done(false); return }
    appendFile(owner,id,index,file,sequence.copyOf(),sha,done)
  }
  private fun appendFile(owner:String,id:String,index:Int,file:File,sequence:IntArray?,sha:String?,done:(Boolean)->Unit) {
    checkMain()
    val window = chunkWindow
    val inRange = if (window == null) index in 0 until (indices.size+chunkTicks-1)/chunkTicks
      else sequence != null && window.canAppend(index,sequence) && pending.size+files.size < 6
    if (closed || owner != generation || id != plan || !inRange || !pending.add(index)) { done(false); return }
    val token = revision
    val allowedCacheId = cachedId
    val lifetimeWork = work
    val lifetimeFailure = detachFailed
    lifetimeWork.incrementAndGet()
    io.execute {
      var fileStage = "exception"
      val accepted = try {
        val root = host.context.cacheDir.canonicalFile; val local = file.canonicalFile
        val owned = if (window != null) NCIdleChunkFile.confined(root,file)
          else if (allowedCacheId.isEmpty()) local.parentFile == root && local.name.matches(Regex("nc_musetalk_idle_[A-Za-z0-9_.-]+\\.mp4"))
          else local == File(root,"nc-idle-v1/$allowedCacheId.mp4") && local == file.absoluteFile
        if (!owned
          || !local.isFile || local.length() !in 1..16L*1024*1024) {
          if (window != null && !owned) {
            val sameLexical = local == file.absoluteFile
            val knownParent = local.parentFile == root || local.parentFile == File(root,"nc-relay")
            val knownName = local.name.matches(Regex("[0-9]+-[0-9]+\\.mp4"))
              || local.name.matches(Regex("nc_musetalk_idle_[A-Za-z0-9_.-]+\\.mp4"))
            val applicationRoot = host.context.applicationContext?.cacheDir?.canonicalFile
            val applicationParent = applicationRoot != null && (local.parentFile == applicationRoot
              || local.parentFile == File(applicationRoot,"nc-relay"))
            android.util.Log.w("NCIdleChunks","confined_lexical=${sameLexical}_parent=${knownParent}_name=${knownName}_application=${applicationParent}")
          }
          fileStage = if (!owned) "confined" else "size"; false
        }
        else if (sha != null && local.inputStream().use { input ->
          val digest = java.security.MessageDigest.getInstance("SHA-256")
          val bytes = ByteArray(65536); var total = 0L
          while (true) {
            val count = input.read(bytes); if (count < 0) break
            total += count; require(total <= 16L*1024*1024); digest.update(bytes,0,count)
          }
          digest.digest().joinToString("") { "%02x".format(it) }
        } != sha) { fileStage = "sha"; false }
        else {
          val extractor = MediaExtractor()
          try {
            extractor.setDataSource(local.absolutePath)
            val format = if (extractor.trackCount == 1) extractor.getTrackFormat(0) else null
            fileStage = "format"
            format != null && format.getString(MediaFormat.KEY_MIME) == "video/avc"
              && format.getInteger(MediaFormat.KEY_WIDTH) in 1..448 && format.getInteger(MediaFormat.KEY_HEIGHT) in 1..672
              && (window == null || (format.getInteger(MediaFormat.KEY_FRAME_RATE) in listOf(6,8,12,24)
                && format.getLong(MediaFormat.KEY_DURATION) in 480000L..520000L))
          } finally { try { extractor.release() } catch (error:Exception) { lifetimeFailure.set(true); throw error } }
        }
      } catch (_:Exception) { fileStage = "exception"; false }
      finally { lifetimeWork.decrementAndGet() }
      if (window != null && !accepted) android.util.Log.w("NCIdleChunks","file_"+fileStage)
      main.post {
        if (token != revision || closed) { done(false); return@post }
        pending.remove(index)
        if (!accepted || files.containsKey(index) || files.values.sumOf { it.length() }+file.length()>128L*1024*1024
          || (window != null && (chunkWindow !== window || sequence == null || !window.append(index,sequence)))) { done(false); return@post }
        files[index] = file
        if (current == null && index == 0) current = slot(0,initialTick)
        prepareNext(); done(true)
      }
    }
  }
  private fun slot(index: Int, startTick: Int = 0): Slot? = files[index]?.let {
    val ticks = if (chunkWindow == null) minOf(chunkTicks,indices.size-index*chunkTicks) else 12
    Slot(index,it,ticks,startTick).also { decoder -> decoder.start() }
  }
  private fun prepareNext() {
    val active = current ?: return
    if (next == null) next = slot(if (chunkWindow == null) (active.index+1)%((indices.size+chunkTicks-1)/chunkTicks) else active.index+1)
  }
  private fun schedule(token: Int, delayMs: Long) {
    val at = System.nanoTime()+delayMs*1_000_000L
    main.postDelayed({ if (token == revision && !closed) {
      wakeLateNs = maxOf(wakeLateNs,System.nanoTime()-at); tick(token)
    } },delayMs)
  }
  private fun tick(token: Int) {
    if (pausedAt != 0L && !reobserving) { schedule(token,20); return }
    if (submitted != null) {
      if (submittedNeedsResubmit && view?.isAvailable == true) {
        submittedNeedsResubmit = false
        submit(requireNotNull(submitted),token)
      }
      if (System.nanoTime()-submittedAt > 2_000_000_000L) fail("presentation_timeout")
      else schedule(token,5)
      return
    }
    if (maximumTick != null && elapsedTicks > maximumTick!!) { schedule(token,5); return }
    val output = view
    if (output == null || !output.isAvailable) { waitForData(token); return }
    var active = current
    if (active == null) { waitForData(token); return }
    if (active.failure.isNotEmpty()) { fail(active.failure); return }
    if (System.nanoTime() < dueAt) { schedule(token,((dueAt-System.nanoTime())/1000000).coerceAtLeast(1)); return }
    if (exitTick > 0 && elapsedTicks >= exitTick) {
      // No ready incoming surface took over at this appointment. Playing
      // another cycle is the fallback, not holding the preceding frame.
      exitTick = 0; exitState = "missed"
    }
    if (active.finished && active.pictures.isEmpty()) {
      val ready = next
      if (ready == null) { prepareNext(); waitForData(token); return }
      chunkWindow?.let { window ->
        if (!window.retire(active.index,active.detached,active.pictures.size,submitted != null,pausedAt != 0L)) {
          fail("chunk_detach_unavailable"); return
        }
        // finished is set only after codec and extractor release. No caller
        // may remove this retained file merely because all bytes downloaded.
        files.remove(active.index)
      }
      active.dispose(); current = ready; next = null; active = ready; prepareNext()
    }
    val picture = active.pictures.poll()
    if (picture == null) { waitForData(token); return }
    frameWaitNs = if (waitingAt == 0L) 0L else (System.nanoTime()-waitingAt).coerceAtLeast(0)
    waitingAt = 0; submittedNeedsResubmit = false
    submit(picture,token)
    schedule(token,5)
  }
  private fun submit(picture: Picture, token: Int) {
    val output = view ?: return
    submitted = picture; gpuReady = false; textureReady = false
    frameDueAt = dueAt; textureAt = 0; textureHandledAt = 0; gpuHandledAt = 0
    submittedAt = System.nanoTime(); state = "prepared"
    // The pending picture owns one reference until actual confirmation/clear.
    // Each GPU attempt owns another, so surface resume can safely resubmit it.
    picture.buffer.retain()
    val frame = VideoFrame(picture.buffer,0,submittedAt)
    try { output.onFrameObserved(frame) {
      picture.gpuAt = System.nanoTime()
      main.post { if (token == revision && submitted === picture) {
        gpuHandledAt = System.nanoTime(); gpuReady = true; confirm()
      } }
    } } finally { frame.release() }
  }
  private fun waitForData(token: Int) {
    state = "waiting"
    if (waitingAt == 0L) waitingAt = System.nanoTime()
    if (System.nanoTime()-waitingAt > 2_000_000_000L) fail("segment_wait_timeout") else schedule(token,5)
  }
  private fun confirm() {
    if (pausedAt != 0L && !reobserving) return
    val picture = submitted ?: return
    if (!gpuReady || !textureReady) return
    val active = current ?: return; val output = view ?: return
    if (reobserving) {
      reobserving = false; submitted = null; picture.buffer.release()
      observedAt = System.nanoTime(); state = "presented"
      observer.presented(output,active.index,picture.tick*1000/24,observedAt)
      return
    }
    if (chunkWindow?.observed(active.index,picture.tick,picture.step) == false) { fail("chunk_observation_invalid"); return }
    heldPicture?.buffer?.release(); heldPicture = picture
    submitted = null; observations++; state = "presented"; lastTick = active.index*chunkTicks+picture.tick
    observedAt = System.nanoTime()
    timing = mapOf("decodedAtNs" to picture.decodedAt,"dueAtNs" to frameDueAt,
      "submittedAtNs" to submittedAt,"renderCallbackAtNs" to picture.gpuAt,"renderHandledAtNs" to gpuHandledAt,
      "textureAtNs" to textureAt,"textureHandledAtNs" to textureHandledAt,
      "confirmedAtNs" to observedAt,"maxMainWakeLateNs" to wakeLateNs)
    wakeLateNs = 0
    if (clockAt == 0L) { elapsedTicks = lastTick.toLong(); clockAt = observedAt-elapsedTicks*1_000_000_000L/24 }
    elapsedTicks += minOf(picture.step,active.ticks-picture.tick)
    // One source clock, not a new interval after every handler wakeup. Repeated
    // millisecond rounding/scheduler lateness must not slow the animation.
    dueAt = clockAt+elapsedTicks*1_000_000_000L/24
    cadence.presented(observedAt,picture.step*1_000_000_000L/24) {
      timing+mapOf("sourceTick" to lastTick,"sourceFrame" to (chunkWindow?.sourceFrame ?: indices.getOrNull(lastTick) ?: -1),
        "decodedAhead" to ((current?.pictures?.size ?: 0)+(next?.pictures?.size ?: 0)),
        "decoderFinished" to active.finished,"chunked" to (chunkWindow != null),"waitNs" to frameWaitNs)
    }
    observer.presented(output,active.index,picture.tick*1000/24,observedAt)
  }
  fun playerCount() = listOfNotNull(current,next).count { !it.cancelled }
  fun status(): Map<String,Any> = mapOf("state" to state,"players" to playerCount(),"files" to files.size,
    "segment" to (current?.index ?: -1),"sourceTick" to lastTick,"presented" to observations,
    "sourceFrame" to (chunkWindow?.sourceFrame ?: indices.getOrNull(lastTick) ?: -1),"observedAtNs" to observedAt,"paused" to (pausedAt != 0L),
    "chunked" to (chunkWindow != null),"releasedThrough" to (chunkWindow?.releasedThrough ?: 0),
    "exitState" to exitState,"exitAtNs" to exitAt,
    "gpuReady" to gpuReady,"textureReady" to textureReady,
    "timing" to timing,
    "decodedAhead" to ((current?.pictures?.size ?: 0)+(next?.pictures?.size ?: 0)))
  private fun fail(reason:String) {
    try {
      val now = System.nanoTime(); val picture = submitted
      observer.failureEvidence(reason,status()+mapOf(
        "pendingTick" to (picture?.tick ?: -1),"pendingAgeNs" to if (picture == null) 0L else (now-submittedAt).coerceAtLeast(0),
        "nowNs" to now,"submittedAtNs" to submittedAt,"decodedAtNs" to (picture?.decodedAt ?: 0L),
        "renderCallbackAtNs" to (picture?.gpuAt ?: 0L),"renderHandledAtNs" to gpuHandledAt,
        "textureAtNs" to textureAt,"textureHandledAtNs" to textureHandledAt,"dueAtNs" to frameDueAt,
        "sinceObservedNs" to if (observedAt == 0L) 0L else (now-observedAt).coerceAtLeast(0),
        "waitAgeNs" to if (waitingAt == 0L) 0L else (now-waitingAt).coerceAtLeast(0),
        "maxMainWakeLateNs" to wakeLateNs,"clockAtNs" to clockAt,"elapsedTicks" to elapsedTicks,
        "reobserving" to reobserving,"needsResubmit" to submittedNeedsResubmit,
        "decoderFinished" to (current?.finished == true),"decoderDetached" to (current?.detached == true),
        "decoderFailed" to (current?.failure?.isNotEmpty() == true),
        "viewAvailable" to (view?.isAvailable == true),"viewShown" to (view?.isShown == true),
        "viewWidth" to (view?.width ?: 0),"viewHeight" to (view?.height ?: 0),
        "hostShown" to host.isShown,"hostAlphaPercent" to (host.alpha*100).toInt(),
        "hostWidth" to host.width,"hostHeight" to host.height))
    } catch (_:Exception) { /* Failure evidence must not delay/replace cleanup. */ }
    clear(); state = "failed"; observer.failed(reason)
  }
  fun clear() { clearDetached {} }
  /** Completion is the file-release boundary, not clear() returning. Never
   * block main waiting on MediaCodec. A timeout retains files in the caller. */
  fun clearDetached(done: (Boolean) -> Unit) {
    checkMain(); revision++; generation = ""; plan = ""; indices = intArrayOf(); chunkTicks = 12; chunkWindow = null; pending.clear(); files.clear()
    retiringWork.removeAll { it.first.get() == 0 && !it.second.get() }
    retiringWork.add(work to detachFailed); work = AtomicInteger(); detachFailed = AtomicBoolean()
    // A view hide/close may clear before the download owner's later clear.
    // Both calls must fence the original readers, not just the empty new epoch.
    val retiredWork = retiringWork.toList()
    current?.dispose(); next?.dispose(); current = null; next = null
    view?.let { it.close(); host.removeView(it) }; view = null
    submitted?.buffer?.release(); submitted = null; submittedNeedsResubmit = false
    heldPicture?.buffer?.release(); heldPicture = null; reobserving = false
    dueAt = 0; clockAt = 0; elapsedTicks = 0; lastTick = -1; observations = 0; state = "ended"
    exitTick = 0; exitAt = 0; exitState = "none"; exitSourceTick = -1
    pausedAt = 0; initialTick = 0; observedAt = 0; cachedId = ""
    maximumTick = null
    timing = emptyMap(); wakeLateNs = 0
    frameWaitNs = 0; cadence.reset()
    val deadline = System.nanoTime()+5_000_000_000L
    fun observeDetach() {
      if (retiredWork.any { it.second.get() }) done(false)
      else if (retiredWork.all { it.first.get() == 0 }) done(true)
      else if (System.nanoTime() >= deadline) done(false)
      else main.postDelayed({ observeDetach() },5)
    }
    observeDetach()
  }
  fun close() { checkMain(); if (closed) return; clear(); closed = true; io.shutdown(); decoders.shutdown() }
}

/** No timer, polling, event allocation or renderer query on normal frames.
 * A gap exceeds the encoded frame interval by >15 ms. First frames after
 * prepare/pause/surface restoration are intentionally not gap observations.
 * Report at most once/five seconds; count intervening anomalies, not extra groups. */
internal class NCCachedFrameCadence(private val report:(Map<String,Any>)->Unit) {
  private var previousAt=0L
  private var reportedAt=0L
  private var suppressed=0L
  fun reset(){previousAt=0L;suppressed=0L}
  fun presented(atNs:Long,expectedNs:Long,read:()->Map<String,Any>) {
    val previous=previousAt;previousAt=atNs
    if(previous<=0 ||atNs<=previous ||expectedNs<=0 ||atNs-previous<=expectedNs+15_000_000L)return
    if(reportedAt!=0L &&atNs-reportedAt<5_000_000_000L){suppressed++;return}
    val skipped=suppressed;suppressed=0;reportedAt=atNs
    try {report(read()+mapOf("frameGapNs" to atNs-previous,"expectedIntervalNs" to expectedNs,"suppressedGaps" to skipped))}
    catch(_:Exception){} // Evidence cannot change playback or its ordinary callbacks.
  }
}
