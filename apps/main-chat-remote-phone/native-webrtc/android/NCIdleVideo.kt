package expo.modules.audio

import android.view.TextureView
import android.widget.FrameLayout
import java.io.File
import java.util.UUID

/** Silent cached H.264 with an observed source clock. Bounded sequential
 * decoding is shared with retained handoffs; no audio or network ownership. */
internal class NCIdleVideo(private val host: FrameLayout,
  private val observed: (TextureView,Int,Long) -> Unit = { _,_,_ -> }) {
  private inner class Slot(val generation: String, val id: String, val sourceCount: Int, val file: File,
    val chunkStart: Int? = null, media: String? = null) {
    val container = FrameLayout(host.context)
    val owner = UUID.randomUUID().toString().replace("-","")
    val plan = media ?: UUID.randomUUID().toString().replace("-","")
    var ready = false
    var closed = false
    var selecting = false
    val renderer: NCHandoffVideo = NCHandoffVideo(container,object: NCHandoffVideo.Observer {
      override fun presented(view: TextureView, segment: Int, positionMs: Int, atNs: Long) {
        if (closed || (next !== this@Slot && current !== this@Slot)) return
        if (!ready) {
          ready = true; renderer.setPaused(true)
          val callback = completion; completion = null; callback?.invoke(true)
        }
        if (closed || (next !== this@Slot && current !== this@Slot)) return
        val source = renderer.status()["sourceFrame"] as? Int ?: return
        if (current === this@Slot) observed(view,source,atNs)
      }
      override fun failed(reason: String) {
        if (closed) return
        if (chunkStart != null) {
          val category = when {
            reason == "presentation_timeout" -> "presentation_timeout"
            reason == "chunk_detach_unavailable" -> "chunk_detach"
            reason.startsWith("decode_") -> "decode"
            else -> "renderer"
          }
          android.util.Log.w("NCIdleChunks","prepare_"+category)
        }
        if (next === this@Slot) { next = null; val callback = completion; completion = null; callback?.invoke(false) }
        if (current === this@Slot) { current = null; visible = false }
        retire(this@Slot)
        try { failureObserver?.invoke(reason) } catch (_:Exception) {}
      }
      override fun failureEvidence(reason: String, details: Map<String,Any>) {
        if (closed) return
        try { failureEvidenceObserver?.invoke(reason,details+mapOf(
          "slotReady" to ready,"slotSelected" to (current === this@Slot),"slotSelecting" to selecting,
          "visible" to visible,"allowed" to allowed,"speech" to speech,"surfaceSuspended" to surfaceSuspended)) }
        catch (_:Exception) {} // Evidence cannot prevent the ordinary failure callback.
      }
      override fun cadenceEvidence(details: Map<String,Any>) {
        if (closed || current !== this@Slot || !visible || !allowed || speech || surfaceSuspended || selecting) return
        try { cadenceEvidenceObserver?.invoke(details+mapOf("loopId" to id)) } catch (_:Exception) {}
      }
    })
  }
  private var current: Slot? = null
  var failureObserver:((String)->Unit)?=null
  var failureEvidenceObserver:((String,Map<String,Any>)->Unit)?=null
  var cadenceEvidenceObserver:((Map<String,Any>)->Unit)?=null
  private var next: Slot? = null
  private var retiring: Slot? = null
  private val detaching = mutableSetOf<Slot>()
  private var completion: ((Boolean) -> Unit)? = null
  private var fadeMs = 0L
  private var allowed = false
  private var speech = false
  private var surfaceSuspended = false
  var visible = false; private set
  fun layout() { listOfNotNull(current,next,retiring).forEach { it.renderer.layout() } }

  fun prepareAt(generation: String, id: String, file: File, fade: Int, sourceCount: Int,
    startFrame: Int, done: (Boolean) -> Unit) {
    prepare(generation,id,file,fade,sourceCount,startFrame,true,done)
  }
  fun prepareChunks(generation: String, id: String, media: String, file: File, fade: Int,
    sourceCount: Int, startFrame: Int, sequence: IntArray, sha: String, done: (Boolean)->Unit) {
    if (detaching.isNotEmpty() || !generation.matches(Regex("[a-f0-9]{32}")) || !id.matches(Regex("[a-f0-9]{64}"))
      || !media.matches(Regex("[a-f0-9]{32}")) || sourceCount !in 1..1440 || startFrame !in 0 until sourceCount
      || fade !in 0..5000 || !NCIdleChunkWindow(sourceCount,startFrame).canAppend(0,sequence)) { done(false); return }
    completion?.invoke(false); completion = null
    next?.let { retire(it) }; next = null
    retiring?.let { retire(it) }; retiring = null
    val slot = Slot(generation,id,sourceCount,file,startFrame,media); next = slot; completion = done
    fadeMs = fade.toLong(); host.addView(slot.container,0,FrameLayout.LayoutParams(-1,-1))
    if (!slot.renderer.beginChunks(slot.owner,slot.plan,sourceCount,startFrame)) {
      next = null; completion = null; retire(slot); done(false); return
    }
    slot.renderer.appendChunk(slot.owner,slot.plan,0,file,sequence,sha) { accepted ->
      if (!accepted && next === slot) {
        android.util.Log.w("NCIdleChunks","prepare_file")
        next = null; val callback = completion; completion = null; retire(slot); callback?.invoke(false)
      }
    }
  }
  fun prepareChunkContinuation(files: List<NCIdleChunkFile>, done: (Boolean)->Unit) {
    if (files.size!=6) { done(false); return }
    val first=files.first()
    if (files.indices.any { index -> val file=files[index]
        file.index!=index || file.generation!=first.generation || file.motion!=first.motion
          || file.media!=first.media || file.sourceCount!=first.sourceCount || file.start!=first.start || file.fade!=first.fade }) {
      done(false); return
    }
    var remaining=6;var safe=true
    fun accepted(ready: Boolean) { safe=safe && ready;remaining--;if (remaining==0) done(safe) }
    prepareChunks(first.generation,first.motion,first.media,first.file,first.fade,first.sourceCount,first.start,
      first.sequence,first.sha) { accepted(it) }
    val slot=next
    if (slot==null || slot.generation!=first.generation || slot.id!=first.motion || slot.plan!=first.media) {
      repeat(5) { accepted(false) };return
    }
    files.drop(1).forEach { appendChunk(it) { ready -> accepted(ready && next===slot && !slot.closed) } }
  }
  fun appendChunk(value: NCIdleChunkFile, done: (Boolean)->Unit) {
    val slot = listOfNotNull(current,next).find { !it.closed && it.chunkStart != null
      && it.generation == value.generation && it.id == value.motion && it.plan == value.media
      && it.sourceCount == value.sourceCount && it.chunkStart == value.start }
    if (slot == null) { done(false); return }
    slot.renderer.appendChunk(slot.owner,slot.plan,value.index,value.file,value.sequence,value.sha,done)
  }
  private fun prepare(generation: String, id: String, file: File, fade: Int, sourceCount: Int,
    startFrame: Int, reuseCurrent: Boolean, done: (Boolean) -> Unit) {
    if (sourceCount !in 1..1440 || startFrame !in 0 until sourceCount) { done(false); return }
    val active = current
    if (reuseCurrent && active?.generation == generation && active.id == id && active.chunkStart == null && active.sourceCount == sourceCount && active.ready && !active.closed && startFrame == 0) { done(true); return }
    if (reuseCurrent && active != null && active.generation != generation) clear()
    completion?.invoke(false); completion = null
    next?.let { retire(it) }; next = null
    retiring?.let { retire(it) }; retiring = null
    val slot = Slot(generation,id,sourceCount,file); next = slot; completion = done
    fadeMs = fade.coerceIn(0,5000).toLong()
    host.addView(slot.container,0,FrameLayout.LayoutParams(-1,-1))
    // Temporary active loops use the existing confined transient-file reader;
    // persistent inventory files retain their exact content-ID path check.
    val began = if (file.name.startsWith("nc_musetalk_idle_"))
      slot.renderer.beginCycleAt(slot.owner,slot.plan,sourceCount,startFrame)
      else slot.renderer.beginCachedCycle(slot.owner,slot.plan,id,sourceCount,startFrame)
    if (!began) {
      next = null; completion = null; retire(slot); done(false); return
    }
    slot.renderer.append(slot.owner,slot.plan,0,file) { accepted ->
      if (!accepted && next === slot) { next = null; val callback = completion; completion = null; retire(slot); callback?.invoke(false) }
    }
  }
  fun selectChunks(generation: String, id: String, media: String): Boolean {
    val target = next ?: current ?: return false
    if (target.chunkStart == null || target.plan != media) return false
    return select(generation,id)
  }
  fun select(generation: String, id: String): Boolean {
    val active = current
    if (active?.generation == generation && active.id == id && active.ready && !active.closed && next == null) return true
    val slot = next ?: return false
    if (slot.generation != generation || slot.id != id || !slot.ready || slot.closed) return false
    retiring?.let { retire(it) }
    val old = current; retiring = old; current = slot; next = null
    old?.renderer?.setPaused(true)
    val duration = if (visible && old != null && old.id != id) fadeMs else 0L
    slot.container.alpha = 0f; slot.container.bringToFront()
    visible = allowed && !speech
    slot.renderer.setPaused(!visible || slot.selecting)
    slot.container.animate().alpha(if (visible) 1f else 0f).setDuration(duration).withEndAction {
      old?.let { retire(it) }; if (retiring === old) retiring = null
    }.start()
    return true
  }
  fun display(allowed: Boolean, speech: Boolean) {
    this.allowed = allowed; this.speech = speech
    val show = allowed && !speech && !surfaceSuspended && current?.ready == true && current?.closed == false
    if (visible != show) {
      visible = show; current?.container?.animate()?.cancel(); current?.container?.alpha = if (show) 1f else 0f
      retiring?.let { retire(it) }; retiring = null
    }
    current?.let { it.renderer.setPaused(!show || it.selecting) }
  }
  fun position(): Map<String,Any>? = current?.takeIf { it.ready && !it.closed }?.let {
    it.renderer.status()+mapOf("generation" to it.generation,"id" to it.id,"mediaId" to it.plan,"sourceCount" to it.sourceCount,"visible" to visible)
  }
  fun suspendSurface(value: Boolean) {
    surfaceSuspended = value
    if (!value) listOfNotNull(current,next,retiring).forEach { it.renderer.restoreSurface() }
    display(allowed,speech)
    next?.let { it.renderer.setPaused(value || it.ready) }
  }
  fun continueAt(source: Int, done: (Boolean)->Unit) {
    prepareContinuation(source) { ready -> done(ready && selectContinuation(source)) }
  }
  fun prepareContinuation(source: Int, done: (Boolean)->Unit) {
    val slot = current
    if (slot == null || slot.closed || slot.chunkStart != null || source !in 0 until slot.sourceCount) { done(false); return }
    prepare(slot.generation,slot.id,slot.file,0,slot.sourceCount,source,false,done)
  }
  fun prepareContinuation(generation: String, id: String, file: File, sourceCount: Int, source: Int, done: (Boolean)->Unit) {
    prepare(generation,id,file,0,sourceCount,source,false,done)
  }
  fun selectContinuation(source: Int): Boolean {
    val slot = next ?: return false
    val status = slot.renderer.status()
    if (status["sourceFrame"] != source || (status["observedAtNs"] as? Long ?: 0L) <= 0L) return false
    slot.selecting = true
    if (!select(slot.generation,slot.id)) { slot.selecting = false; return false }
    slot.renderer.observeSelected {
      if (current === slot && !slot.closed) { slot.selecting = false; slot.renderer.setPaused(!visible) }
    }
    return true
  }
  fun cancelContinuation() {
    val callback = completion; completion = null
    next?.let { retire(it) }; next = null; callback?.invoke(false)
  }
  private fun retire(slot: Slot) {
    if (slot.closed) return
    slot.closed = true; slot.container.animate().cancel(); detaching.add(slot)
    slot.renderer.clearDetached { safe ->
      if (safe) { slot.renderer.close(); host.removeView(slot.container); detaching.remove(slot) }
    }
  }
  fun clear() { clearDetached {} }
  /** Caller has revoked/joined its offers. Fence only this chunk owner: an
   * older queue's cleanup must not clear a newer displayed/return reader. */
  fun clearChunksDetached(generation: String, media: String, done: (Boolean)->Unit) {
    if (!generation.matches(Regex("[a-f0-9]{32}")) || !media.matches(Regex("[a-f0-9]{32}"))) { done(false); return }
    val slots = (listOfNotNull(current,next,retiring)+detaching).distinct().filter {
      it.chunkStart != null && it.generation == generation && it.plan == media
    }
    val callback = if (next in slots) completion else null
    if (next in slots) { next = null; completion = null }
    if (current in slots) { current = null; visible = false }
    if (retiring in slots) retiring = null
    slots.forEach { retire(it) }; callback?.invoke(false)
    if (slots.isEmpty()) { done(true); return }
    var remaining = slots.size; var safe = true
    slots.forEach { slot -> slot.renderer.clearDetached { detached ->
      safe = safe && detached; remaining--; if (remaining == 0) done(safe)
    } }
  }
  fun clearDetached(done: (Boolean) -> Unit) {
    val callback = completion; completion = null
    val slots = (listOfNotNull(current,next,retiring)+detaching).distinct()
    current = null; next = null; retiring = null; visible = false
    slots.forEach { retire(it) }; callback?.invoke(false)
    if (slots.isEmpty()) { done(true); return }
    var remaining = slots.size; var safe = true
    slots.forEach { slot -> slot.renderer.clearDetached { detached ->
      safe = safe && detached; remaining--; if (remaining == 0) done(safe)
    } }
  }
}
