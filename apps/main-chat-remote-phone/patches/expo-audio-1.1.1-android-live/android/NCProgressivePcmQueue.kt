package expo.modules.audio

import java.io.IOException
import java.io.InterruptedIOException
import java.util.ArrayDeque
import java.util.UUID

/** Destructive, single-reader PCM queue. No player, audio focus or output owner. */
internal class NCProgressivePcmQueue {
  companion object {
    const val SAMPLE_RATE = 24000
    const val MAX_APPEND_FRAMES = 12000
    const val MAX_TOTAL_FRAMES = 1440000L
  }

  private val lock = Object()
  private val blocks = ArrayDeque<ByteArray>()
  private var headOffset = 0
  private var appendedFrames = 0L
  private var finishedFrames: Long? = null
  private var closed = false
  private var readerClaimed = false

  fun append(cursor: Long, pcm: ByteArray): Long = synchronized(lock) {
    check(!closed && finishedFrames == null) { "progressive_pcm_closed" }
    require(cursor == appendedFrames) { "progressive_pcm_cursor" }
    require(pcm.isNotEmpty() && pcm.size % 2 == 0 && pcm.size <= MAX_APPEND_FRAMES * 2) {
      "progressive_pcm_append_size"
    }
    val next = cursor + pcm.size / 2
    require(next <= MAX_TOTAL_FRAMES) { "progressive_pcm_capacity" }
    // At most 2,880,000 queued bytes/source, further bounded by the eight-source store.
    blocks.addLast(pcm.copyOf())
    appendedFrames = next
    lock.notifyAll()
    next
  }

  fun finish(totalFrames: Long): Boolean = synchronized(lock) {
    check(!closed) { "progressive_pcm_closed" }
    require(totalFrames == appendedFrames) { "progressive_pcm_final_cursor" }
    finishedFrames = totalFrames
    lock.notifyAll()
    true
  }

  fun finalFrames(): Long? = synchronized(lock) { finishedFrames }

  fun claimReader() = synchronized(lock) {
    if (closed || readerClaimed) throw IOException("progressive_pcm_single_reader")
    readerClaimed = true
  }

  /** Called only by the Media3 loader. Interrupt/close is a failure, never EOS. */
  fun read(target: ByteArray, offset: Int, length: Int): Int = synchronized(lock) {
    require(offset >= 0 && length >= 0 && offset <= target.size - length)
    if (length == 0) return@synchronized 0
    while (blocks.isEmpty() && !closed && finishedFrames == null) {
      try { lock.wait() }
      catch (_: InterruptedException) {
        Thread.currentThread().interrupt()
        throw InterruptedIOException("progressive_pcm_interrupted")
      }
    }
    if (closed) throw IOException("progressive_pcm_closed")
    val block = blocks.peekFirst() ?: return@synchronized -1
    val count = minOf(length, block.size - headOffset)
    block.copyInto(target, offset, headOffset, headOffset + count)
    headOffset += count
    if (headOffset == block.size) { blocks.removeFirst(); headOffset = 0 }
    count
  }

  fun close() = synchronized(lock) {
    closed = true
    blocks.clear()
    headOffset = 0
    lock.notifyAll()
  }
}

/** Module-local opaque IDs. A later module/JS session cannot adopt an old queue. */
internal class NCProgressivePcmStore {
  private val sources = mutableMapOf<String, NCProgressivePcmQueue>()

  @Synchronized fun open(): String {
    check(sources.size < 8) { "progressive_pcm_source_limit" }
    val id = UUID.randomUUID().toString()
    sources[id] = NCProgressivePcmQueue()
    return id
  }

  @Synchronized fun requireSource(id: String): NCProgressivePcmQueue =
    sources[id] ?: throw IllegalArgumentException("progressive_pcm_source_missing")

  @Synchronized fun close(id: String): Boolean {
    val queue = sources.remove(id) ?: return false
    queue.close()
    return true
  }

  @Synchronized fun closeAll() {
    sources.values.forEach { it.close() }
    sources.clear()
  }
}
