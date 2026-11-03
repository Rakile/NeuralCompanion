package expo.modules.audio

/** Main-serialized visual policy. Decisions never authorize audio, manipulate
 * samples or produce playback receipts. The playback owner consumes them. */
internal class NCFrameHandoff(private val generation: String, private val nowMs: () -> Long) {
  class Timeline(val motionId: String, val sourceFrameCount: Int, sourceIndices: List<Int>) {
    val sourceIndices = sourceIndices.toList()
    init {
      require(Regex("[a-f0-9]{64}").matches(motionId) && sourceFrameCount in 1..1440)
      require(this.sourceIndices.size in 1..1440 && this.sourceIndices.all { it in 0 until sourceFrameCount })
    }
  }
  class Return internal constructor(internal val revision: Long, internal val key: Long,
    val motionId: String, val sourceFrame: Int)
  var state = "idle"; private set
  var deadlineMs = 0L; private set
  private var key = 0L
  private var highestKey = 0L
  private var revision = 0L
  private var timeline: Timeline? = null
  private var openingReady = false
  private var pending: String? = null
  private var observation: NCIdleFrameState.Presented? = null
  private var outgoing: NCIdleFrameState.Presented? = null
  private var lastSpeechFrame: Int? = null
  private var heardSamples = 0L
  private var returnLease: Return? = null
  private fun fresh(frame: NCIdleFrameState.Presented): Boolean {
    val now = nowMs()
    if (now < 0 || frame.observedAtNanos < 0) return false
    val at = frame.observedAtNanos/1_000_000
    return frame.generation == generation && at <= now && now-at <= 750
  }
  fun begin(ownerGeneration: String, nextKey: Long, value: Timeline, readyAtMs: Long): Boolean {
    if (state == "closed" || ownerGeneration != generation || nextKey !in 1..9_007_199_254_740_991L ||
      readyAtMs < 0 || readyAtMs > nowMs() || readyAtMs > Long.MAX_VALUE-2000) return false
    if (nextKey == key && state in listOf("preparing","armed","speech")) {
      val old = timeline
      return old?.motionId == value.motionId && old.sourceFrameCount == value.sourceFrameCount &&
        old.sourceIndices == value.sourceIndices
    }
    if (nextKey <= highestKey) return false
    revision++; key = nextKey; highestKey = nextKey; timeline = value
    deadlineMs = readyAtMs+2000; openingReady = false; pending = null
    outgoing = null; lastSpeechFrame = null; heardSamples = 0; returnLease = null
    state = "preparing"; return true
  }
  fun observe(frame: NCIdleFrameState.Presented) {
    if (state != "closed" && frame.sourceFrame in 0..1439 && fresh(frame) &&
      frame.observedAtNanos >= (observation?.observedAtNanos ?: 0)) observation = frame
  }
  fun speechReady(value: Long): Boolean {
    if (value != key || state != "preparing") return false
    openingReady = true; return true
  }
  private fun adjacent(frame: NCIdleFrameState.Presented, incoming: Int, value: Timeline): Boolean {
    if (frame.motionId != value.motionId || frame.sourceFrame !in 0 until value.sourceFrameCount) return false
    val delta = (incoming-frame.sourceFrame+value.sourceFrameCount)%value.sourceFrameCount
    // Producer anticipation is ping-pong: its final step into speech may be
    // backwards. The spatial tolerance is still strictly one source frame.
    return minOf(delta,value.sourceFrameCount-delta) <= 1
  }
  fun decision(): String {
    pending?.let { pending = null; return it }
    if (state != "preparing") return "wait"
    // Elapsed time is not readiness. Keep the visual loop running until the
    // opening and matching pose exist; cancellation/hidden own their exits.
    val value = timeline ?: return "unmapped"
    val frame = observation
    if (openingReady && frame != null && fresh(frame) &&
      (frame.motionId != value.motionId || adjacent(frame,value.sourceIndices.first(),value))) {
      outgoing = frame; state = "armed"; return "arm"
    }
    return "wait"
  }
  fun presentedSpeech(value: Long, sourceTick: Int): Boolean {
    val mapping = timeline ?: return false
    if (value != key || state !in listOf("armed","speech") || sourceTick !in mapping.sourceIndices.indices) return false
    val frame = mapping.sourceIndices[sourceTick]
    if (state == "armed") {
      val previous = observation
      if (outgoing != null && outgoing?.motionId == mapping.motionId) {
        if (previous == null || !fresh(previous) || sourceTick != 0 || !adjacent(previous,frame,mapping)) {
          pending = "alignment_mismatch"; state = "preparing"; outgoing = null
          return false
        }
        pending = "aligned"
      }
    }
    state = "speech"; lastSpeechFrame = frame; return true
  }
  fun heard(value: Long, samples: Long) {
    if (value == key && state in listOf("armed","speech") && samples >= heardSamples) heardSamples = samples
  }
  fun completed(value: Long) {
    val mapping = timeline ?: return
    if (value != key || state != "speech") return
    val last = lastSpeechFrame ?: return
    state = "returning"; revision++
    returnLease = Return(revision,key,mapping.motionId,(last+1)%mapping.sourceFrameCount)
  }
  fun returnFrame(value: Long): Return? = if (state == "returning" && value == key) returnLease else null
  fun returnPresented(lease: Return, frame: NCIdleFrameState.Presented): Boolean {
    if (state != "returning" || lease !== returnLease || lease.revision != revision || lease.key != key ||
      !fresh(frame) || frame.motionId != lease.motionId || frame.sourceFrame != lease.sourceFrame) return false
    observation = frame; returnLease = null; state = "idle"; return true
  }
  fun hidden() {
    observation = null; outgoing = null
    if (state == "preparing") { state = "armed"; pending = "hidden" }
    if (state == "returning") { revision++; returnLease = null; state = "idle" }
  }
  fun cancel(value: Long) {
    if (value != key || state in listOf("closed","idle")) return
    revision++; returnLease = null; pending = "cancelled"; openingReady = false
    lastSpeechFrame = null; outgoing = null; state = "idle"
  }
  fun fadeMs(from: String, to: String, configured: Int): Int = if (from == to) 0 else configured.coerceIn(0,5000)
  fun close() {
    revision++; returnLease = null; pending = null; observation = null; outgoing = null
    timeline = null; state = "closed"
  }
}
