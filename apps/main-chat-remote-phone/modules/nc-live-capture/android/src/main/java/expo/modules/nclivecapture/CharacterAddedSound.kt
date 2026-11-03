package expo.modules.nclivecapture

import android.app.NotificationManager
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import expo.modules.audio.NCCommunicationRoute
import expo.modules.audio.NCPlaybackGuard
import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.sin

/** A short local sound on the current route. No focus, service or playback mutations. */
internal class CharacterAddedSound(private val context: Context) {
  private val handler = Handler(Looper.getMainLooper())
  private var track: AudioTrack? = null
  private var check: Runnable? = null
  private var closed = false

  fun play() { handler.post {
    if (closed || track != null) return@post
    val guard = NCPlaybackGuard.shared
    val ticket = guard.characterCueTicket() ?: return@post
    val manager = context.getSystemService(AudioManager::class.java)
    val notifications = context.getSystemService(NotificationManager::class.java)
    if (manager.ringerMode != AudioManager.RINGER_MODE_NORMAL ||
        notifications.currentInterruptionFilter != NotificationManager.INTERRUPTION_FILTER_ALL ||
        manager.mode == AudioManager.MODE_IN_CALL) return@post
    val route = NCCommunicationRoute.shared.forTicket(ticket)
    if (manager.mode == AudioManager.MODE_IN_COMMUNICATION && route == null) return@post
    try {
      val rate = 24000
      val samples = ShortArray(rate * 180 / 1000) { index ->
        val seconds = index.toDouble() / rate
        val attack = (index / (rate * .006)).coerceAtMost(1.0)
        (1600 * attack * exp(-seconds * 25) * sin(2 * PI * 880 * seconds)).toInt().toShort()
      }
      val candidate = AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder()
        .setUsage(if (route == null) AudioAttributes.USAGE_MEDIA else AudioAttributes.USAGE_VOICE_COMMUNICATION)
        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
        .setAudioFormat(AudioFormat.Builder().setSampleRate(rate).setEncoding(AudioFormat.ENCODING_PCM_16BIT)
          .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
        .setTransferMode(AudioTrack.MODE_STATIC).setBufferSizeInBytes(samples.size * 2).build()
      track = candidate
      if (route != null) {
        val device = manager.getDevices(AudioManager.GET_DEVICES_OUTPUTS)
          .firstOrNull { it.id == route.deviceId && it.type == route.deviceType }
        if (device == null || !candidate.setPreferredDevice(device)) { stop(); return@post }
      }
      if (candidate.write(samples, 0, samples.size) != samples.size || guard.characterCueTicket() != ticket) {
        stop(); return@post
      }
      candidate.play()
      val until = SystemClock.elapsedRealtime() + 190
      val monitor = object : Runnable {
        override fun run() {
          if (closed || guard.characterCueTicket() != ticket || SystemClock.elapsedRealtime() >= until) stop()
          else handler.postDelayed(this, 15)
        }
      }
      check = monitor
      handler.postDelayed(monitor, 15)
    } catch (_: Exception) { stop() }
  } }

  private fun stop() {
    check?.let { handler.removeCallbacks(it) }; check = null
    track?.let { try { it.stop() } catch (_: Exception) {}; it.release() }; track = null
  }
  fun close() { handler.post { closed = true; stop() } }
}
