// NeuralCompanion, MIT. One native peer/output lifetime; JS is not its clock.
package expo.modules.audio

import java.nio.ByteBuffer
import org.webrtc.AudioTrack
import org.webrtc.VideoFrame
import org.webrtc.VideoSink

/** SDK callbacks only copy bounded admitted PCM / retain bounded video. Hardware
 * prepare and close belong on the module worker. stop fences synchronously.
 * Factory attachment, focus, session configuration and network remain external.
 */
internal class NCAVPlayback(
  private val generation: Long,
  device: NCPcmOutput.Device,
  owner: NCPlaybackGuard = NCPlaybackGuard.shared
) : AudioTrack.RtpAudioSink, VideoSink, AutoCloseable {
  private val lock = Any()
  private val videos = LinkedHashMap<Long, NCRtpVideoSink>()
  private val speechRanges = LinkedHashMap<Long, Pair<Long, Long>>()
  private val sampleCounts = HashMap<Long, Int>()
  private val audible = HashSet<Long>()
  private val pendingSpeech = HashSet<Long>()
  private var idle: NCRtpVideoSink? = null
  private var presenting = false
  private var localShown = false
  private var visualDeadline = 0L
  private var lastFrameNanos = 0L
  private var completedHandoff = false
  private var terminal = false
  private var ticket: String? = null
  private var renderer: VideoSink? = null
  private var clear: (() -> Unit)? = null
  private var visibleKey: Long? = null
  private var progressObserver: ((Long,Int,Boolean,Boolean)->Unit)? = null
  private val audio = NCTrackQueue(generation, device, owner) { key, count, stopped ->
    var completed = false
    var observer: ((Long,Int,Boolean,Boolean)->Unit)? = null
    val video = synchronized(lock) {
      completed = !stopped && count >= (sampleCounts[key] ?: Int.MAX_VALUE)
      observer = progressObserver
      if (stopped || count >= (sampleCounts[key] ?: 0)) { audible.remove(key); pendingSpeech.remove(key) }
      else if (count > 0) audible.add(key)
      videos[key]
    }
    // Read-only observation after the real queue's hardware progress. A view
    // failure must never break audio/drained receipts or the playback owner.
    try { observer?.invoke(key,count,stopped,completed) } catch (_:RuntimeException) {}
    if (stopped) video?.stop() else video?.played(generation, count)
  }
  fun setProgressObserver(value: ((Long,Int,Boolean,Boolean)->Unit)?) { synchronized(lock) { progressObserver = value } }

  fun setRenderer(value: VideoSink?, clearImage: (() -> Unit)?) {
    val previous = synchronized(lock) {
      val old = clear
      renderer = if (terminal) null else value
      clear = if (terminal) null else clearImage
      visibleKey = null
      localShown = false
      lastFrameNanos = 0
      completedHandoff = false
      old
    }
    previous?.invoke()
  }

  fun visible(): Boolean = synchronized(lock) {
    !terminal && presenting && renderer != null && visibleKey != null &&
      (completedHandoff || System.nanoTime() - lastFrameNanos < 750_000_000L)
  }

  fun localVisualAllowed(): Boolean = synchronized(lock) {
    !terminal && presenting && renderer != null && System.nanoTime() < visualDeadline
  }
  fun speaking(): Boolean = synchronized(lock) { !terminal && audible.isNotEmpty() }
  // Silence between queued chunks is not the end of the reply's visual range.
  // Do not consult JS polling or data delivery to release the cached surface.
  fun idleReturnAllowed(): Boolean = synchronized(lock) { !terminal && pendingSpeech.isEmpty() && audible.isEmpty() }
  fun hasSuccessor(key: Long): Boolean = synchronized(lock) { pendingSpeech.any { it != key } }
  fun frameIdentity(timestamp: Long): Pair<Long,Int>? = synchronized(lock) {
    speechRanges.entries.firstNotNullOfOrNull { (key,range) ->
      val delta = (timestamp-range.first).toInt().toLong()
      if (delta in 0 until range.second) key to (delta/3750).toInt() else null
    }
  }
  fun setLocalVisible(value: Boolean) = synchronized(lock) { localShown = value }
  fun localVisible(): Boolean = synchronized(lock) { localShown && localVisualAllowed() }

  fun visual(first: Long, count: Int, enabled: Boolean): Boolean {
    val previous = synchronized(lock) {
      if (terminal || (enabled && (first !in 0..0xffffffffL || count !in 1..28_800_000))) return false
      val old = idle
      // Detach the previous idle owner before stopping it: its clear callback
      // must not erase a newer speech or renewed idle presentation.
      idle = null
      presenting = enabled
      visualDeadline = if (enabled) System.nanoTime() + count.toLong() * 1_000_000_000L / 48000 else 0
      if (!enabled) { localShown = false; visibleKey = null; lastFrameNanos = 0; completedHandoff = false; clear?.invoke() }
      if (enabled) {
        lateinit var candidate: NCRtpVideoSink
        candidate = NCRtpVideoSink(generation, first, count, true, { frame ->
          synchronized(lock) {
            val holdSpeech = pendingSpeech.isNotEmpty() && ((visibleKey ?: 0) > 0 || completedHandoff)
            if (!terminal && presenting && audible.isEmpty() && !holdSpeech && idle === candidate) {
              renderer?.let { it.onFrame(frame); visibleKey = 0; lastFrameNanos = System.nanoTime(); completedHandoff = false }
            }
          }
        }, {
          synchronized(lock) {
            if (idle === candidate && visibleKey == 0L) { visibleKey = null; lastFrameNanos = 0; clear?.invoke() }
          }
        })
        candidate.admit(generation)
        idle = candidate
      }
      old
    }
    previous?.stop()
    return true
  }

  fun prepare(key: Long, ticket: String, requestId: String, chunkId: String,
              firstAudio: Long, firstVideo: Long, count: Int, offsetSeconds: Double, rejected: (String) -> Unit = {}): Boolean {
    if (firstVideo !in 0..0xffffffffL) { rejected("invalid_descriptor"); return false }
    val candidate = synchronized(lock) {
      if (terminal) { rejected("output_terminal"); return false }
      if (videos.size >= 2) { rejected("video_queue_capacity"); return false }
      if (videos.containsKey(key)) { rejected("duplicate_key"); return false }
      if (this.ticket != null && this.ticket != ticket) { rejected("owner_mismatch"); return false }
      NCRtpVideoSink(generation, firstVideo, count, false, { frame ->
        synchronized(lock) {
          if (!terminal && presenting && (visibleKey == null || key >= visibleKey!!)) {
            renderer?.let { it.onFrame(frame); visibleKey = key; lastFrameNanos = System.nanoTime(); completedHandoff = false }
          }
        }
      }, {
        synchronized(lock) {
          if (visibleKey == key) { visibleKey = null; clear?.invoke() }
        }
      }).also { videos[key] = it }
    }
    val ready = audio.prepare(key, ticket, requestId, chunkId, firstAudio, count, offsetSeconds, rejected)
    val accepted = synchronized(lock) {
      if (ready && !terminal && videos[key] === candidate) {
        speechRanges[key] = firstVideo to count.toLong() * 90000 / 48000
        sampleCounts[key] = count
        pendingSpeech.add(key)
        while (speechRanges.size > 64) speechRanges.remove(speechRanges.keys.first())
        this.ticket = ticket; true
      } else { videos.remove(key, candidate); false }
    }
    if (!accepted) { if (ready) rejected("prepare_superseded"); candidate.stop(); audio.retire(key) }
    return accepted
  }

  fun play(key: Long): Boolean {
    val video = synchronized(lock) { if (terminal) null else videos[key] } ?: return false
    // Video admission does not display anything until confirmed audio advances.
    video.admit(generation)
    val playing = audio.play(key)
    if (!playing) { synchronized(lock) { pendingSpeech.remove(key) }; video.stop() }
    return playing
  }

  override fun onData(pcm: ByteBuffer, bits: Int, rate: Int, channels: Int, frames: Int,
                      timestamp: Long, clockRate: Int, valid: Boolean, concealed: Boolean) =
    audio.receive(pcm, bits, rate, channels, frames, timestamp, clockRate, valid, concealed)

  override fun onFrame(frame: VideoFrame) {
    val current = synchronized(lock) {
      if (terminal) emptyList() else {
        val speech = !frame.hasRtpTimestamp() || speechRanges.values.any { (first, size) ->
          val delta = (frame.rtpTimestamp - first).toInt().toLong()
          delta >= 0 && delta < size
        }
        videos.values.toList() + if (speech) emptyList() else listOfNotNull(idle)
      }
    }
    current.forEach { it.onFrame(frame) }
  }
  fun snapshot(key: Long) = audio.snapshot(key)
  fun samples(key: Long) = audio.samples(key)
  fun setVolume(value: Float) = audio.setVolume(value)
  fun setDucked(value: Boolean) = audio.setDucked(value)
  fun retire(key: Long) {
    val state = audio.snapshot(key)
    val video = synchronized(lock) {
      // Only natural, hardware-confirmed completion may hand its still image to
      // the independently authorized idle presentation. Failure/Stop never does.
      if (!terminal && presenting && idle != null && visibleKey == key &&
          state?.completed == true && !state.failed && !state.stopped) {
        visibleKey = 0; completedHandoff = true
      }
      audible.remove(key); pendingSpeech.remove(key); sampleCounts.remove(key)
      val removed = videos.remove(key)
      // A new ticket must still pass the existing native owner admission.
      if (videos.isEmpty() && state?.completed == true && !state.failed && !state.stopped) ticket = null
      removed
    }
    video?.stop()
    audio.retire(key)
  }
  fun stop() {
    val current = synchronized(lock) {
      if (terminal) return
      terminal = true
      progressObserver = null
      pendingSpeech.clear()
      videos.values.toList() + listOfNotNull(idle)
    }
    audio.stop()
    current.forEach { it.stop() }
    setRenderer(null, null)
  }
  override fun close() {
    stop()
    synchronized(lock) { videos.clear() }
    audio.close()
  }
}
