package expo.modules.audio

/** Visual/file retention only; never grants audio or completion authority. */
internal class NCIdleChunkWindow(val sourceCount: Int, val startFrame: Int) {
  init { require(sourceCount in 1..1440 && startFrame in 0 until sourceCount) }
  var current = 0; private set
  var releasedThrough = 0; private set
  var sourceFrame = -1; private set
  private val retained = mutableSetOf<Int>()
  private var shownTick = -1
  private var shownStep = 0
  val size: Int get() = retained.size
  fun canAppend(index: Int, sequence: IntArray): Boolean = index in current until current+6
    && index in 0..10005 && index !in retained && sequence.size == 12
    && sequence.indices.all { sequence[it] == (startFrame+index*12+it)%sourceCount }
  fun append(index: Int, sequence: IntArray): Boolean {
    if (!canAppend(index,sequence)) return false
    retained.add(index); return true
  }
  /** Called only after both GPU and TextureView confirmation for this picture. */
  fun observed(index: Int, tick: Int, step: Int): Boolean {
    if (index != current || index !in retained || tick !in 0..11 || step !in listOf(1,2,3,4)
      || tick%step != 0 || (shownTick < 0 && tick != 0)
      || (shownTick >= 0 && (step != shownStep || tick != shownTick+step))) return false
    shownTick = tick; shownStep = step; sourceFrame = (startFrame+index*12+tick)%sourceCount
    return true
  }
  /** Decoder EOS, no queued/in-flight picture, and observed final tick are all
   * required. The last displayed source remains valid after the file retires. */
  fun retire(index: Int, decoderDetached: Boolean, queued: Int, submitted: Boolean, paused: Boolean): Boolean {
    if (index != current || index !in retained || !decoderDetached || queued != 0 || submitted || paused
      || shownStep == 0 || shownTick != (11/shownStep)*shownStep) return false
    retained.remove(index); current++; releasedThrough = current
    shownTick = -1; shownStep = 0; return true
  }
}
