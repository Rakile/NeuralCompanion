package expo.modules.audio

/** Serialized by the visual source. No audio authorization or playback receipts. */
internal class NCIdleFrameState(val generation: String, val motionId: String, val sourceFrameCount: Int) {
  class Request internal constructor(val sourceFrame: Int)
  data class Presented(val generation: String, val motionId: String, val sourceFrame: Int,
    val pts: Long, val timescale: Int, val observedAtNanos: Long, val playing: Boolean)
  private var pending: Request? = null
  private var decoded: Pair<Long,Int>? = null
  private var observation: Presented? = null
  private var closed = false
  init {
    require(generation.isNotEmpty() && generation.length <= 128)
    require(Regex("[a-f0-9]{64}").matches(motionId) && sourceFrameCount in 1..1440)
  }
  fun request(sourceFrame: Int): Request? {
    if (closed || sourceFrame !in 0 until sourceFrameCount) return null
    decoded = null
    return Request(sourceFrame).also { pending = it }
  }
  fun current(request: Request): Boolean = !closed && pending === request
  fun decoded(request: Request, pts: Long, timescale: Int): Boolean {
    if (!current(request) || pts !in 0..(Long.MAX_VALUE/24) || timescale <= 0 ||
      sourceTick(pts,timescale) >= sourceFrameCount) return false
    decoded = Pair(pts,timescale); return true
  }
  fun present(request: Request, now: Long, visible: Boolean, playing: Boolean = false): Presented? {
    val value = decoded ?: return null
    if (!current(request) || !visible || now < 0) return null
    val result = Presented(generation,motionId,sourceTick(value.first,value.second).toInt(),
      value.first,value.second,now,playing)
    pending = null; decoded = null; observation = result; return result
  }
  fun observe(): Presented? = if (closed) null else observation
  private fun sourceTick(pts: Long, scale: Int): Long {
    val ticks = pts*24
    // MediaCodec exposes microseconds: e.g. 1/6 second becomes 166666us.
    return ticks/scale + if ((ticks%scale)*2 >= scale) 1 else 0
  }
  fun pause() { pending = null; decoded = null; observation = observation?.copy(playing=false) }
  fun close() { pause(); closed = true; observation = null }
}
