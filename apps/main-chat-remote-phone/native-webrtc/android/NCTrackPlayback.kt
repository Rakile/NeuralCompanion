// NeuralCompanion, MIT. Candidate; compiled beside the EXISTING playback guard.
package expo.modules.audio

import java.util.UUID

internal class NCTrackPlayback(
  private val output: NCPcmOutput,
  owner: NCPlaybackGuard = NCPlaybackGuard.shared,
  private val offsetSeconds: Double = 0.0,
  private val progress: (Int, Boolean) -> Unit = { _, _ -> }
) : NCPlaybackActions, NCPlaybackCheckpointActions, AutoCloseable {
  data class Snapshot(val started: Boolean, val completed: Boolean, val positionSeconds: Double, val failed: Boolean,
                      val stopped: Boolean, val failureReason: String, val failureAtMs: Long)
  private val identity = UUID.randomUUID().toString()
  private val binding = owner.newBinding(this)
  @Volatile private var bound = false
  @Volatile private var started = false
  @Volatile private var completed = false
  @Volatile private var closed = false
  @Volatile private var stopped = false

  init {
    require(offsetSeconds.isFinite() && offsetSeconds >= 0 && offsetSeconds <= 600)
    output.setChanged { refreshReceipts() }
  }
  fun bind(ticket: String, requestId: String, chunkId: String, rejected: (String) -> Unit = {}): Boolean =
    binding.bindPhoneReplyChunk(ticket, requestId, chunkId, rejected).also { bound = it }
  fun play(): Boolean = bound && !closed && binding.play() && output.isPlaying()
  fun stop() { binding.remove(); ncPause() }
  fun snapshot() = Snapshot(started, completed, offsetSeconds + output.confirmedSamples() / 48000.0,
    output.failed(), stopped, output.failureReason(), output.failureAtMs())
  private fun refreshReceipts() {
    // The output calls this outside its lock; guard actions may reenter output.
    // Keep the binding's last actual device position available until the
    // continuation owner checkpoints it. Removing it here lost the active
    // chunk/position before JS could request authenticated stream recovery.
    if (output.failed()) { ncPause(); return }
    if (closed || output.confirmedSamples() == 0) return
    if (binding.acknowledgeStarted()) started = true
    if (output.drained() && binding.acknowledgeCompleted()) completed = true
    progress(output.confirmedSamples(), stopped)
  }
  override val ncIsPlayingSnapshot: Boolean get() = output.isPlaying() && output.confirmedSamples() > 0
  override val ncIsAliveSnapshot: Boolean get() = !closed
  override val ncItemIdentity: String get() = identity
  // Unlike ExoPlayer, this driver has its own synchronized native worker and no
  // application-looper affinity. No waits for JS, main thread or worker joins.
  override fun ncDispatch(effect: () -> Unit) = effect()
  override fun ncPlay() { output.start() }
  override fun ncPause() { stopped = true; output.stop(); progress(output.confirmedSamples(), true) }
  override fun ncStopAndCheckpoint(): Double {
    ncPause()
    return offsetSeconds + output.confirmedSamples() / 48000.0
  }
  override fun close() {
    closed = true
    output.setChanged(null)
    stop()
    output.close()
  }
}
