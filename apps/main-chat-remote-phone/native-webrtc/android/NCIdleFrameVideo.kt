package expo.modules.audio

import android.graphics.SurfaceTexture
import android.os.SystemClock
import android.view.Gravity
import android.view.Surface
import android.view.TextureView
import android.widget.FrameLayout
import java.io.File

/** Frame-backed silent cache surface. One decoder per active/incoming motion.
 * The presentation lease belongs to NCAVView, never to this visual helper. */
internal class NCIdleFrameVideo(private val host: FrameLayout) {
  private inner class Slot(val generation: String, val id: String, val motion: String,
    val count: Int, val fps: Int, val file: File, val width: Int, val height: Int) : TextureView.SurfaceTextureListener {
    val view = TextureView(host.context).apply { isOpaque = false }
    var source: NCIdleFrameSource? = null
    var surface: Surface? = null
    var frame: NCIdleFrameSource.Frame? = null
    var renderedAt = 0L
    var renderConfirmed = false
    var updatedAt = 0L
    var ready = false
    var submitted = false
    var closed = false
    var revision = 0
    var due = 0L
    var decodeNanos = 0L
    var pendingPresent: Runnable? = null
    var completion: ((Boolean) -> Unit)? = null
    var observation: NCIdleFrameState.Presented? = null
    var sequence: List<Int>? = null
    var sequenceIndex = 0
    var sequenceDone: ((Boolean) -> Unit)? = null
    val tick = Runnable {
      if (!closed && visible && current === this) load(sequence?.getOrNull(sequenceIndex) ?: nextFrame(),due)
    }
    fun nextFrame() = ((observation?.sourceFrame ?: frame?.sourceFrame ?: 0) + 24/fps).let { if (it >= count) 0 else it }
    override fun onSurfaceTextureAvailable(texture: SurfaceTexture, w: Int, h: Int) {
      if (closed) return
      surface = Surface(texture)
      source = NCIdleFrameSource(file,generation,motion,count,fps,surface!!,{ observation = it },12)
      load(0)
    }
    override fun onSurfaceTextureSizeChanged(texture: SurfaceTexture, w: Int, h: Int) {}
    override fun onSurfaceTextureUpdated(texture: SurfaceTexture) {
      updatedAt = System.nanoTime(); rendered()
    }
    override fun onSurfaceTextureDestroyed(texture: SurfaceTexture): Boolean { close(false); return true }
    fun load(index: Int, presentAt: Long = 0) {
      val epoch = ++revision
      pendingPresent?.let { host.removeCallbacks(it) }; pendingPresent = null
      renderedAt = 0; renderConfirmed = false; updatedAt = 0
      val decodeStarted = System.nanoTime()
      source?.prepareFrame(index) { value ->
        if (closed || revision != epoch) return@prepareFrame
        decodeNanos = System.nanoTime()-decodeStarted
        if (value == null) { failureReason = source?.failureReason ?: "decode_unavailable"; val done = completion; completion = null; done?.invoke(false); return@prepareFrame }
        frame = value
        val present = Runnable {
          if (!closed && revision == epoch) {
            pendingPresent = null
            submitted = source?.submit(value) { _, nanos ->
              if (!closed && revision == epoch) { renderedAt = nanos; renderConfirmed = true; rendered() }
            } == true
          }
        }
        pendingPresent = present
        // Decode ahead while the current surface remains visible. Starting the
        // decoder only at the display deadline adds decode latency every frame.
        host.postDelayed(present,(presentAt-SystemClock.uptimeMillis()).coerceAtLeast(0))
      }
    }
    fun rendered() {
      // A codec may report zero for the first rendered timestamp. Presence of
      // its callback, not a nonzero numeric sentinel, establishes readiness.
      if (closed || !renderConfirmed || updatedAt == 0L || updatedAt < renderedAt) return
      val renderedRevision = revision
      renderConfirmed = false; ready = true
      if (visible && current === this) confirm()
      val done = completion; completion = null; done?.invoke(true)
      if (closed || revision != renderedRevision) return
      sequence?.let { indices ->
        if (frame?.sourceFrame != indices.getOrNull(sequenceIndex)) { cancelSequence(false); return }
        sequenceIndex++
        if (sequenceIndex == indices.size) cancelSequence(true)
      }
      schedule()
    }
    fun confirm() {
      val value = frame ?: return
      if (source?.confirmPresented(value,System.nanoTime(),visible && current === this) == true) {
        observation = observation?.copy(playing = true)
        observation?.let { onPresented?.invoke(it,view) }
      }
    }
    fun schedule() {
      host.removeCallbacks(tick)
      if (!visible || current !== this || closed) return
      val now = SystemClock.uptimeMillis()
      due = maxOf(due + 1000L/fps, now)
      host.post(tick)
    }
    fun pause() {
      revision++; host.removeCallbacks(tick)
      pendingPresent?.let { host.removeCallbacks(it) }; pendingPresent = null
      cancelSequence(false)
      source?.pause(); observation = observation?.copy(playing=false); due = 0
    }
    fun cancelSequence(completed: Boolean) {
      sequence = null; sequenceIndex = 0
      val done = sequenceDone; sequenceDone = null; done?.invoke(completed)
    }
    fun layout() {
      val scale = minOf(host.width.toFloat()/width,host.height.toFloat()/height)
      if (scale > 0) view.layoutParams = FrameLayout.LayoutParams((width*scale).toInt().coerceAtLeast(1),
        (height*scale).toInt().coerceAtLeast(1),Gravity.CENTER)
    }
    fun close(removeView: Boolean = true) {
      if (closed) return
      closed = true; pause(); view.animate().cancel()
      val target = surface; surface = null
      source?.close { target?.release() }; source = null
      // TextureView is already detaching during its destruction callback.
      // Removing it recursively there can release its SurfaceTexture twice.
      // Completion may run inside TextureView.draw/onSurfaceTextureUpdated.
      // Fence immediately, but detach after traversal rather than destroying
      // the TextureLayer underneath the draw that's currently using it.
      if (removeView) host.post { host.removeView(view) }
      val done = completion; completion = null; done?.invoke(false)
    }
  }
  private var current: Slot? = null
  private var next: Slot? = null
  private var retiring: Slot? = null
  private var fade = 0L
  var failureReason = ""; private set
  var visible = false; private set
  var onPresented: ((NCIdleFrameState.Presented,TextureView) -> Unit)? = null
  fun retainedFrames(): Int = listOfNotNull(current,next,retiring).sumOf { it.source?.retainedCount ?: 0 }
  fun decodeMillis(): Double = (current?.decodeNanos ?: 0)/1_000_000.0
  fun layout() { current?.layout(); next?.layout(); retiring?.layout() }
  fun prepare(generation: String, id: String, file: File, motion: String, count: Int,
    fps: Int, width: Int, height: Int, fadeMs: Int, done: (Boolean) -> Unit) {
    if (count !in 1..1440 || fps !in listOf(6,8,12,24) || width <= 0 || height <= 0 ||
      !Regex("[a-f0-9]{64}").matches(motion)) { done(false); return }
    current?.let { if (!it.closed && it.ready && it.generation == generation && it.id == id && it.motion == motion) { done(true); return } }
    if (current?.generation != generation) clear()
    next?.close(); retiring?.close(); retiring = null
    val slot = Slot(generation,id,motion,count,fps,file,width,height)
    next = slot; fade = fadeMs.coerceIn(0,5000).toLong(); slot.completion = done
    slot.view.surfaceTextureListener = slot
    host.addView(slot.view,0,FrameLayout.LayoutParams(-1,-1)); slot.layout()
    host.postDelayed({ if (next === slot && !slot.ready) {
      failureReason = if (slot.source == null) "surface_unavailable" else if (slot.frame == null)
        "frame_unavailable" else if (!slot.submitted) "submit_rejected" else if (!slot.renderConfirmed)
        "render_unavailable_texture_"+(if (slot.updatedAt>0) "updated" else "pending")+
          "_pts_"+(slot.source?.renderCallbackPts ?: -2) else "texture_unavailable"
      next = null; slot.close()
    } },2000)
  }
  fun select(generation: String, id: String): Boolean {
    current?.let { if (it.generation == generation && it.id == id && it.ready && !it.closed) return true }
    val slot = next ?: return false
    if (slot.generation != generation || slot.id != id || !slot.ready || slot.closed) return false
    val old = current; retiring?.close(); retiring = old; old?.pause()
    current = slot; next = null; slot.view.bringToFront(); slot.view.alpha = 0f
    slot.view.animate().alpha(if (visible) 1f else 0f)
      .setDuration(if (visible && old != null && old.motion != slot.motion) fade else 0)
      .withEndAction { old?.close(); if (retiring === old) retiring = null; if (visible) { slot.confirm(); slot.schedule() } }.start()
    return true
  }
  fun display(allowed: Boolean, speech: Boolean) {
    val show = allowed && !speech && current?.ready == true && current?.closed == false
    if (show == visible) return
    visible = show
    current?.let {
      it.view.animate().cancel(); it.view.alpha = if (show) 1f else 0f
      if (show) { it.confirm(); it.schedule() } else it.pause()
    }
    retiring?.close(); retiring = null
  }
  fun position(): NCIdleFrameState.Presented? = if (visible) current?.observation else null
  fun sequence(motion: String, indices: IntArray, done: (Boolean) -> Unit) {
    val slot = current
    if (slot == null || slot.closed || !visible || slot.motion != motion || indices.size !in 1..1440 ||
      indices.any { it !in 0 until slot.count || it % (24/slot.fps) != 0 }) { done(false); return }
    slot.pause(); slot.sequence = indices.toList(); slot.sequenceDone = done
    slot.due = SystemClock.uptimeMillis(); slot.schedule()
  }
  fun continuation(motion: String, frame: Int, done: (Boolean) -> Unit) {
    val slot = current
    if (slot == null || slot.motion != motion || frame !in 0 until slot.count || slot.closed) { done(false); return }
    slot.pause(); slot.completion?.invoke(false); slot.completion = done; slot.load(frame)
  }
  fun clear() {
    visible = false
    val slots = listOfNotNull(current,next,retiring); current = null; next = null; retiring = null
    slots.forEach { it.close() }
  }
}
