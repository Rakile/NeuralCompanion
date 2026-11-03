package expo.modules.nclivecapture

import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min

sealed class SegmentEvent {
  data class Onset(val id: Long) : SegmentEvent()
  data class Completed(val id: Long, val samples: ShortArray) : SegmentEvent()
}

class LiveSegmenter {
  private val window = ShortArray(WINDOW_SIZE)
  private var windowCount = 0
  private var windowPlayback = false
  private var inputPlayback: Boolean? = null
  private var previousWindowPlayback: Boolean? = null
  private val history = ShortArray(HISTORY_SIZE)
  private var historyCount = 0
  private var historyNext = 0
  private var position = 0
  private var noiseFloorDb = -60.0
  private var ambientWindows = 0
  private var initialAmbientDb = 0.0
  private var sensitivity = 4
  private var candidateStart: Int? = null
  private var candidateWindows = 0
  private var speaking = false
  private var speechReleaseDb = -90.0
  private var quietSamples = 0
  private val currentSamples = ShortArray(SEGMENT_LIMIT)
  private var currentCount = 0
  private var currentId: Long? = null
  private var nextId = 1L
  var meteringDb: Double? = null
    private set
  val phase get() = if (speaking) "speech" else "listening"
  val durationMs get() = currentCount / 16.0

  fun setSensitivity(level: Int) {
    require(level in 1..5) { "Live Mic sensitivity must be 1-5" }
    sensitivity = level
  }

  fun consume(samples: ShortArray, playbackActive: Boolean): List<SegmentEvent> {
    if (samples.isEmpty()) return emptyList()
    if (inputPlayback != null && inputPlayback != playbackActive && !speaking) clearCandidate()
    inputPlayback = playbackActive
    val events = mutableListOf<SegmentEvent>()
    for (sample in samples) {
      windowPlayback = if (windowCount == 0) playbackActive else windowPlayback || playbackActive
      window[windowCount++] = sample
      if (windowCount == WINDOW_SIZE) {
        analyze(events)
        windowCount = 0
      }
    }
    return events
  }

  fun reset() {
    windowCount = 0; windowPlayback = false; inputPlayback = null; previousWindowPlayback = null
    historyCount = 0; historyNext = 0; position = 0; noiseFloorDb = -60.0
    ambientWindows = 0; initialAmbientDb = 0.0
    clearCandidate(); speaking = false; quietSamples = 0; currentCount = 0; currentId = null; meteringDb = null
    speechReleaseDb = -90.0
  }

  private fun analyze(events: MutableList<SegmentEvent>) {
    var energy = 0.0
    val start = position
    for (sample in window) {
      val normalized = sample / 32768.0
      energy += normalized * normalized
      history[historyNext] = sample
      historyNext = (historyNext + 1) % HISTORY_SIZE
    }
    position += WINDOW_SIZE
    historyCount = min(HISTORY_SIZE, historyCount + WINDOW_SIZE)
    val db = max(-90.0, 10 * log10(max(energy / WINDOW_SIZE, 1e-9)))
    meteringDb = db
    // Learn the environment before admitting foreground speech. Previously a
    // running car was above the initial gate immediately and could never update
    // the noise floor: only below-gate windows were allowed to teach it.
    // Keep PCM in preroll; this affects detection only, not the recorded signal.
    // Do not learn the companion's voice as ambient noise during playback.
    if (!windowPlayback && !speaking && ambientWindows < 5) {
      initialAmbientDb = if (ambientWindows == 0) db else min(initialAmbientDb, db)
      ambientWindows++
      noiseFloorDb = initialAmbientDb.coerceIn(-90.0, -20.0)
      clearCandidate()
      return
    }
    // The saved sensitivity changes only foreground onset. The adaptive
    // ambient margin and stricter playback echo gate remain in force.
    val activation = if (windowPlayback) max(-35.0, noiseFloorDb + 12.0)
      else max(FOREGROUND_FLOORS_DB[sensitivity - 1], noiseFloorDb + 8.0)
    if (speaking) {
      append(window, events)
      quietSamples = if (db >= speechReleaseDb) 0 else quietSamples + WINDOW_SIZE
      if (quietSamples >= 16_000) {
        complete(events); speaking = false; quietSamples = 0; clearCandidate()
      }
    } else if (db >= activation) {
      if (candidateStart == null) candidateStart = start
      candidateWindows += 1
      if (candidateWindows >= if (windowPlayback) 5 else 3) {
        val candidate = candidateStart ?: return
        speaking = true; quietSamples = 0; currentId = nextId++
        // Barge-in stops playback. Keep this utterance's release threshold
        // stable so that the lower foreground gate cannot turn room noise
        // into continuous speech while waiting to submit the interruption.
        speechReleaseDb = activation - 4
        events += SegmentEvent.Onset(currentId!!)
        val retainedStart = max(position - historyCount, candidate - LEAD_IN_SIZE)
        for (offset in retainedStart until position) {
          val back = position - offset
          currentSamples[currentCount++] = history[(historyNext - back + HISTORY_SIZE) % HISTORY_SIZE]
        }
      }
    } else {
      if (!windowPlayback) noiseFloorDb = max(-90.0, min(-20.0, noiseFloorDb + (db - noiseFloorDb) * 0.05))
      clearCandidate()
    }
    previousWindowPlayback = windowPlayback
  }

  private fun clearCandidate() { candidateStart = null; candidateWindows = 0 }
  private fun append(samples: ShortArray, events: MutableList<SegmentEvent>) {
    var offset = 0
    while (offset < samples.size) {
      if (currentId == null) currentId = nextId++
      val count = min(samples.size - offset, SEGMENT_LIMIT - currentCount)
      samples.copyInto(currentSamples, currentCount, offset, offset + count)
      currentCount += count
      offset += count
      if (currentCount == SEGMENT_LIMIT) complete(events)
    }
  }
  private fun complete(events: MutableList<SegmentEvent>) {
    val id = currentId
    if (id != null && currentCount > 0) events += SegmentEvent.Completed(id, currentSamples.copyOf(currentCount))
    currentCount = 0; currentId = null
  }

  companion object {
    private val FOREGROUND_FLOORS_DB = doubleArrayOf(-50.0, -59.0, -68.0, -74.0, -80.0)
    private const val WINDOW_SIZE = 1_600
    private const val HISTORY_SIZE = 16_000
    private const val LEAD_IN_SIZE = 5_600
    private const val SEGMENT_LIMIT = 960_000
  }
}
