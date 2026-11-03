package expo.modules.audio

import android.view.TextureView
import android.widget.FrameLayout
import java.io.File
import org.webrtc.VideoFrame

internal data class NCBufferedVisualSource(val motion: String, val count: Int, val indices: IntArray,
  val generation: String, val id: String, val file: File, val start: Int, val fade: Int,
  val chunks: List<NCIdleChunkFile>? = null) {
  companion object {
    fun parse(value: Map<String,Any>): NCBufferedVisualSource? {
      fun integer(name: String): Int? = (value[name] as? Number)?.toDouble()?.takeIf { it.isFinite() && it==kotlin.math.floor(it) && it in 0.0..2147483647.0 }?.toInt()
      val motion=value["motionId"] as? String ?: return null
      val count=integer("sourceFrameCount") ?: return null
      val start=integer("startFrame") ?: return null
      val fade=integer("fadeMs") ?: return null
      val generation=value["idleGeneration"] as? String ?: return null
      val id=value["idleId"] as? String ?: return null
      val rows=value["sourceIndices"] as? List<*> ?: return null
      if (!motion.matches(Regex("[a-f0-9]{64}")) || !id.matches(Regex("[a-f0-9]{64}")) || generation.length !in 1..1024
        || count !in 1..1440 || start !in 0 until count || fade !in 0..5000 || rows.size !in 1..720) return null
      val indices=rows.map { row -> (row as? Number)?.toDouble()?.takeIf { it.isFinite() && it==kotlin.math.floor(it) && it>=0 && it<count }?.toInt() ?: return null }.toIntArray()
      val file=try { File(java.net.URI(value["idleUri"] as? String ?: return null)) } catch (_:Exception) { return null }
      val chunks=if (value.containsKey("idleChunks")) NCIdleChunkReturn.parse(value) ?: return null else null
      return NCBufferedVisualSource(motion,count,indices,generation,id,file,start,fade,chunks)
    }
  }
}

/** Main-thread compositor shared by the product view and SDK probe. Retained
 * files and decoded openings are silent. Only observations from NCAVPlayback's
 * hardware clock can enter speech/return; this class has no receipt API. */
internal class NCVisualTransition(private val host: FrameLayout,
  private val observed: (TextureView,String,Int,Long)->Unit = { _,_,_,_ -> }) {
  val idle: NCIdleVideo = NCIdleVideo(host) { view,source,at ->
    observed(view,if (returning) "returned" else "idle",source,at)
    if (phase == "preparing" && ready && source == sequence.firstOrNull()) {
      retainedHost.bringToFront(); phase = "retained"
      idle.display(allowed,true); retained?.setPaused(false)
    }
  }
  private val opening = NCSpeechOpening(host) { view,source,at ->
    if (phase == "speech") { lastSpeech = source; observed(view,"opening",source,at) }
  }
  private val retainedHost = FrameLayout(host.context)
  private var retained: NCHandoffVideo? = null
  private val retiring = mutableSetOf<NCHandoffVideo>()
  private fun createRetained() = NCHandoffVideo(retainedHost,object: NCHandoffVideo.Observer {
    override fun presented(view: TextureView, segment: Int, positionMs: Int, atNs: Long) {
      if (phase == "ended") return
      if (!ready) { ready = true; retained?.setPaused(true); return }
      if (phase == "retained") observed(view,"retained",retained!!.status()["sourceFrame"] as Int,atNs)
    }
    override fun failed(reason: String) { phase = "degraded"; failure = reason; idle.display(allowed,false) }
  })
  @Volatile private var key = 0L
  private var openingKey = 0L
  private var owner = ""
  private var plan = ""
  private var sequence = intArrayOf()
  private var timeline = intArrayOf()
  private val successors = sortedMapOf<Long,IntArray>()
  private var source: NCBufferedVisualSource? = null
  private val sourceSuccessors = mutableMapOf<Long,NCBufferedVisualSource>()
  private var returnRevision = 0
  private var count = 0
  private var ready = false
  private var allowed = false
  private var returning = false
  private var lastSpeech = -1
  private var preparedReturn = -1
  private var returnReady = false
  private var appointment = 0L
  private var failure = ""
  @Volatile var phase = "ended"; private set
  private var revision = 0
  init { host.addView(retainedHost,0,FrameLayout.LayoutParams(-1,-1)) }
  fun layout() { idle.layout(); retained?.layout(); opening.layout() }
  fun begin(generation: String, nextKey: Long, media: String, indices: IntArray, sourceCount: Int): Boolean {
    if (phase != "ended" || retiring.isNotEmpty() || nextKey !in 1..2147483647L || !allowed || idle.position()?.get("sourceCount") != sourceCount) return false
    val reader = createRetained()
    if (!reader.begin(generation,media,indices,sourceCount)) { reader.close(); return false }
    retained = reader
    revision++; owner = generation; key = nextKey; openingKey = nextKey; plan = media; sequence = indices.copyOf(); count = sourceCount
    ready = false; returning = false; lastSpeech = -1; appointment = 0; failure = ""; phase = "preparing"
    return true
  }
  fun append(value: Long, index: Int, file: File, done: (Boolean)->Unit) {
    if (value != key || phase == "ended") { done(false); return }
    val reader = retained ?: run { done(false); return }
    reader.append(owner,plan,index,file,done)
  }
  fun prepareOpening(generation: String, value: Long, media: String, file: File, indices: IntArray, sourceCount: Int, done: (Boolean)->Unit) {
    if (value != key || generation != owner || sourceCount != count || indices.isEmpty() || indices.size > 720
      || indices.any { it !in 0 until count } || indices.first() != sequence.firstOrNull()) { done(false); return }
    timeline = indices.copyOf()
    if (source == null) prepareReturn((indices.last()+1)%count)
    opening.prepare(generation,value,media,file,indices.take(12).toIntArray(),sourceCount,done)
  }
  fun arm(value: Long, minimumMs: Int, maximumMs: Int): Long {
    if (value != key || phase != "retained" || !opening.ready(key) || !allowed) return 0
    val at = retained?.armExit(owner,plan,minimumMs,maximumMs) ?: return 0
    if (at > 0) appointment = at
    return at
  }
  fun heard(value: Long, samples: Int, completed: Boolean, successor: Boolean) {
    // The caller has a real guarded native start. Position zero is its valid
    // first observation, not a merely downloaded/prepared audio file.
    if (phase == "ended" || !allowed || samples < 0 || value < key) return
    if (value > key && !advance(value)) return
    if (phase in listOf("retained","preparing","degraded") && opening.ready(key)) {
      val source = if (phase == "retained") retained?.status()?.get("sourceFrame") as? Int else idle.position()?.get("sourceFrame") as? Int
      val delta = source?.let { kotlin.math.abs(it-timeline.first()) }
      val matching = delta != null && minOf(delta,count-delta) <= 1
      // Audio is never held to rescue a missed visual appointment. Preserve
      // truthful diagnostics under bad transfer rather than claim alignment.
      if (!matching || appointment == 0L || kotlin.math.abs(System.nanoTime()-appointment)>125_000_000L) failure = "alignment_missed"
      phase = "speech"; lastSpeech = timeline.first(); retained?.setPaused(true); idle.display(allowed,true)
    }
    if (phase == "speech") opening.heard(key,samples)
    if (completed && !successor && successors.isEmpty() && phase in listOf("speech","stream") && lastSpeech >= 0) {
      phase = "returning"; returning = true; val token = revision
      // Natural completion is the end of the declared audio/video timeline,
      // even if the display omitted its final picture. Reusing lastSpeech can
      // discard an already prepared continuation and decode the wrong one.
      val source = this.source?.start ?: ((timeline.last()+1)%count)
      fun finish(accepted: Boolean) {
        if (token == revision && phase == "returning") {
          if (accepted) { phase = "returned"; opening.cover(); idle.display(allowed,false) }
          else { phase = "degraded"; failure = "return_unavailable" }
          if (!accepted) returning = false
        }
      }
      if (returnReady && preparedReturn == source) finish(idle.selectContinuation(source))
      else {
        val configured=this.source
        if (configured==null) idle.continueAt(source) { finish(it) }
        else prepareConfiguredReturn(configured) { finish(it && idle.selectContinuation(source)) }
      }
    }
  }
  /** Called only after a tracked surface observation, never on download. */
  fun streamed(value: Long, sourceTick: Int): Boolean {
    if (value < key || phase !in listOf("speech","stream")) return false
    if (value > key && !advance(value)) return false
    if (sourceTick !in timeline.indices) return false
    // A file player can omit intermediate pictures (and encoded quality may
    // be below 24 fps). That is display cadence, not a changed source mapping.
    // Validate continuity at the declared chunk boundary in advance instead.
    lastSpeech = timeline[sourceTick]; phase = "stream"; retained?.setPaused(true); return true
  }
  fun streamFrame(value: Long, sourceTick: Int, frame: VideoFrame): Boolean {
    val mapping = if (value == key) timeline else successors[value]
    if (phase !in listOf("speech","stream") || mapping == null || sourceTick !in mapping.indices) return false
    val token = revision
    return opening.stream(openingKey,frame) { view,at ->
      if (token == revision && streamed(value,sourceTick)) observed(view,"rtp",lastSpeech,at)
    }
  }
  /** Reserve a visual successor before its asynchronous preparation. Empty
   * mapping holds the last picture, never audio; the real mapping replaces it. */
  fun next(value: Long, sourceCount: Int, indices: IntArray): Boolean {
    if (phase in listOf("ended","returned","returning") || value <= key || value > 2147483647L || sourceCount != count
      || indices.size > 720 || indices.any { it !in 0 until count } || (successors.size >= 1 && !successors.containsKey(value))) return false
    if (successors[value]?.isNotEmpty() == true) return successors[value]!!.contentEquals(indices)
    successors[value] = indices.copyOf()
    if (indices.isNotEmpty()) prepareReturn((indices.last()+1)%count)
    return true
  }
  fun configure(value: Long, next: NCBufferedVisualSource, done: (Boolean)->Unit) {
    if (phase in listOf("ended","returned","returning") || value<key || value>2147483647L
      || (value==key && (source!=null || next.count!=count))
      || (value>key && successors.isNotEmpty() && !successors.containsKey(value))) { done(false); return }
    if(value==key) source=next
    else { successors[value]=next.indices.copyOf();sourceSuccessors[value]=next }
    val token=revision;val preparing=++returnRevision;preparedReturn=next.start;returnReady=false
    prepareConfiguredReturn(next) { ready ->
      val current=token==revision && preparing==returnRevision && phase!="ended"
      if(current)returnReady=ready
      done(current && ready)
    }
  }
  private fun prepareConfiguredReturn(value: NCBufferedVisualSource, done: (Boolean)->Unit) {
    val chunks=value.chunks
    if (chunks==null) idle.prepareContinuation(value.generation,value.id,value.file,value.count,value.start,done)
    else idle.prepareChunkContinuation(chunks,done)
  }
  private fun prepareReturn(source: Int) {
    val token = revision; val preparing=++returnRevision; preparedReturn = source; returnReady = false
    idle.prepareContinuation(source) { ready ->
      if (token == revision && preparing==returnRevision && preparedReturn == source) returnReady = ready
    }
  }
  private fun advance(value: Long): Boolean {
    val next = successors[value]?.takeIf { it.isNotEmpty() } ?: return false
    val configured=sourceSuccessors[value]
    val changed=configured!=null && source?.motion!=configured.motion
    if (timeline.isNotEmpty() && !changed) {
      val difference = kotlin.math.abs(next.first()-timeline.last())
      if (minOf(difference,count-difference)>1 && failure.isEmpty()) failure = "stream_alignment_missed"
    }
    if(changed)opening.beginFade(configured!!.fade)
    if(configured!=null){source=configured;count=configured.count}
    sourceSuccessors.keys.filter { it<=value }.forEach { sourceSuccessors.remove(it) }
    key = value; timeline = next; successors.headMap(value+1).clear(); phase = "stream"; return true
  }
  fun display(visible: Boolean, ordinarySpeech: Boolean) {
    allowed = visible
    idle.display(visible,ordinarySpeech || phase in listOf("retained","speech","stream","returning"))
    retained?.setPaused(!visible || (ready && phase != "retained"))
  }
  fun status(): Map<String,Any> = mapOf("key" to key,"state" to phase,"failure" to failure,
    "fadeCount" to opening.fadeCount,"motionId" to (source?.motion ?: ""),"sourceFrameCount" to count,
    "ready" to ready,"openingReady" to opening.ready(openingKey),"sourceFrame" to when (phase) {
      "speech","stream","returning" -> lastSpeech
      "preparing","returned","degraded" -> (idle.position()?.get("sourceFrame") ?: -1)
      "retained" -> (retained?.status()?.get("sourceFrame") ?: -1)
      else -> -1
    })
  fun activeKey(): Long = if (phase == "ended") 0 else key
  fun clearDetached(done: (Boolean)->Unit) {
    revision++; returnRevision++; phase = "ended"; ready = false; returning = false; key = 0; timeline = intArrayOf(); successors.clear();source=null;sourceSuccessors.clear()
    returnReady = false; preparedReturn = -1; idle.cancelContinuation()
    retained?.let { retiring.add(it) }; retained = null
    val pending = retiring.toList()
    var remaining = pending.size+1; var safe = true
    fun finish(value: Boolean) { safe = safe && value; remaining--; if (remaining == 0) { idle.display(allowed,false); done(safe) } }
    pending.forEach { reader -> reader.clearDetached { detached ->
      if (detached) { reader.close(); retiring.remove(reader) }
      finish(detached)
    } }
    opening.clearAll { finish(it) }
  }
}
