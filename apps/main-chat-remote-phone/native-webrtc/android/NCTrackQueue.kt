// NeuralCompanion, MIT. Bounded product queue using the existing playback owner.
package expo.modules.audio

import java.nio.ByteBuffer

/** One peer/output lifetime. prepare/retire/close run on the module worker.
 * stop is an immediate fence; no decoder callback waits for JS or worker joins.
 * No route, focus, capture, ticket issuance or network authority is owned here.
 */
internal class NCTrackQueue(
  private val generation: Long,
  device: NCPcmOutput.Device,
  private val owner: NCPlaybackGuard = NCPlaybackGuard.shared,
  private val progress: (Long, Int, Boolean) -> Unit = { _, _, _ -> }
) : AutoCloseable {
  private class Entry(val output: NCPcmOutput, val playback: NCTrackPlayback,
                      val requestId: String, val chunkId: String, val first: Long, val count: Int) {
    @Volatile var ready = false
  }
  private val lock = Any()
  private val stream = NCPcmStream(device)
  private val entries = LinkedHashMap<Long, Entry>()
  private var lastKey = 0L
  private var terminal = false
  private var volume = 1f
  private var ducked = false

  init { require(generation > 0) }

  fun prepare(key: Long, ticket: String, requestId: String, chunkId: String,
              first: Long, count: Int, offsetSeconds: Double, rejected: (String) -> Unit = {}): Boolean {
    if (key <= 0 || first !in 0..0xffffffffL || count !in 1..28_800_000 ||
        !offsetSeconds.isFinite() || offsetSeconds < 0 || offsetSeconds + count / 48000.0 > 600 ||
        listOf(ticket, requestId, chunkId).any { it.isEmpty() || it.length > 128 }) { rejected("invalid_descriptor"); return false }
    if (!owner.isOpen(ticket)) { rejected("owner_not_open"); return false }
    val entry = synchronized(lock) {
      if (terminal) { rejected("queue_terminal"); return false }
      if (key <= lastKey) { rejected("stale_key"); return false }
      if (entries.size >= 2) { rejected("queue_capacity"); return false }
      if (entries.values.any { it.requestId == requestId && it.chunkId == chunkId }) { rejected("duplicate_chunk"); return false }
      if (entries.values.any { ((first - it.first) and 0xffffffffL) < it.count ||
          ((it.first - first) and 0xffffffffL) < count }) { rejected("overlapping_range"); return false }
      val output = try { NCPcmOutput(stream.next(), generation, first, count) }
                   catch (_: IllegalStateException) { rejected("stream_lease_unavailable"); return false }
      output.setVolume(volume * if (ducked) 0.5f else 1f)
      val playback = NCTrackPlayback(output, owner, offsetSeconds) { samples, stopped -> progress(key, samples, stopped) }
      Entry(output, playback, requestId, chunkId, first, count).also { entries[key] = it; lastKey = key }
    }
    val bound = entry.playback.bind(ticket, requestId, chunkId, rejected)
    val prepared = bound && entry.output.prepare()
    if (bound && !prepared) rejected("device_prepare_failed")
    synchronized(lock) {
      if (prepared && !terminal && entries[key] === entry) {
        entry.ready = true
        return true
      }
      entries.remove(key, entry)
    }
    if (prepared) rejected("prepare_superseded")
    entry.playback.close()
    return false
  }

  fun play(key: Long): Boolean {
    val entry = synchronized(lock) { if (terminal) null else entries[key]?.takeIf { it.ready } }
    return entry?.playback?.play() == true
  }

  fun receive(pcm: ByteBuffer, bits: Int, rate: Int, channels: Int, frames: Int,
              timestamp: Long, clockRate: Int, valid: Boolean, concealed: Boolean) {
    val current = synchronized(lock) { if (terminal) emptyList() else entries.values.filter { it.ready } }
    for (entry in current) entry.output.offer(pcm, bits, rate, channels, frames, timestamp, clockRate, valid, concealed)
  }

  fun snapshot(key: Long): NCTrackPlayback.Snapshot? =
    synchronized(lock) { entries[key] }?.playback?.snapshot()

  fun samples(key: Long): FloatArray? = synchronized(lock) { entries[key] }?.output?.latestSample()

  fun setVolume(value: Float) {
    if (!value.isFinite()) return
    synchronized(lock) {
      volume = value.coerceIn(0f, 1f)
      applyVolume()
    }
  }

  fun setDucked(value: Boolean) = synchronized(lock) { ducked = value; applyVolume() }

  private fun applyVolume() {
    if (!terminal) for (entry in entries.values) entry.output.setVolume(volume * if (ducked) 0.5f else 1f)
  }

  fun retire(key: Long) {
    val entry = synchronized(lock) { entries.remove(key) } ?: return
    entry.playback.close()
  }

  fun stop() {
    val current = synchronized(lock) {
      if (terminal) return
      terminal = true
      entries.values.toList()
    }
    for (entry in current) entry.playback.stop()
  }

  override fun close() {
    stop()
    val current = synchronized(lock) { entries.values.toList().also { entries.clear() } }
    for (entry in current) entry.playback.close()
    stream.close()
  }
}
