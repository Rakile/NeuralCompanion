package expo.modules.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack

// Shared pure recovery policy.
/** Quiet mono PCM on the existing route. Echo is baked in, never a delayed player. */
object NCConnectionCueSamples {
  const val SAMPLE_RATE = 16_000
  const val RECOVERED_DURATION_MS = 860L
  fun samples(recovered: Boolean): ShortArray {
    fun tone(t: Double, length: Double, from: Double, to: Double): Double {
      if (t < 0 || t >= length) return 0.0
      val envelope = kotlin.math.sin(Math.PI * t / length).let { it * it }
      val phase = 2 * Math.PI * (from * t + (to - from) * t * t / (2 * length))
      return kotlin.math.sin(phase) * envelope
    }
    fun dry(t: Double): Double = if (recovered)
      tone(t, 0.24, 440.0, 440.0) + tone(t - 0.28, 0.24, 554.37, 554.37)
    else tone(t, 0.36, 420.0, 360.0)
    return ShortArray(if (recovered) 13760 else 11200) { index ->
      val t = index.toDouble() / SAMPLE_RATE
      val wet = dry(t) + 0.25 * dry(t - 0.17) + 0.10 * dry(t - 0.34)
      (wet * 1120).toInt().coerceIn(-1600, 1600).toShort()
    }
  }
}

/** Monotonic recovery gate; the legacy capture adapter retains its input policy. */
class NCConnectionRecoveryClock {
  var epoch = 0L
    private set
  private var waiting = false
  private var nextCue = Long.MAX_VALUE
  private var reopenAt = 0L
  fun pause(epoch: Long, now: Long) {
    this.epoch = epoch; waiting = true; nextCue = now; reopenAt = Long.MAX_VALUE
  }
  fun takeWaitingCue(now: Long): Boolean {
    if (!waiting || now < nextCue) return false
    nextCue = now + 5_000
    return true
  }
  fun resume(epoch: Long, now: Long): Boolean {
    if (!waiting || epoch != this.epoch) return false
    waiting = false; nextCue = Long.MAX_VALUE; reopenAt = now + RESUME_SUPPRESSION_MS
    return true
  }
  fun acceptsInput(epoch: Long, capturedAt: Long): Boolean =
    epoch == this.epoch && !waiting && capturedAt >= reopenAt
  fun cancel() { waiting = false; nextCue = Long.MAX_VALUE; reopenAt = Long.MAX_VALUE }
  companion object { const val RESUME_SUPPRESSION_MS = NCConnectionCueSamples.RECOVERED_DURATION_MS + 250L }
}

/** Local PCM output on the caller's existing route, without focus or input.
 * Track construction policy remains with each existing native owner. */
class NCConnectionCueOutput(private val authorize:(stop:()->Unit,play:()->Boolean)->Boolean,
  private val createTrack:(bytes:Int)->AudioTrack={bytes->
    AudioTrack.Builder().setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
      .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build())
      .setAudioFormat(AudioFormat.Builder().setSampleRate(NCConnectionCueSamples.SAMPLE_RATE)
        .setEncoding(AudioFormat.ENCODING_PCM_16BIT).setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build())
      .setBufferSizeInBytes(bytes).setTransferMode(AudioTrack.MODE_STATIC).build()
  }) {
  private var track:AudioTrack?=null
  @Synchronized fun stop() {
    val previous=track;track=null
    previous?.let{try{it.stop()}catch(_:Throwable){};it.release()}
  }
  @Synchronized fun play(recovered:Boolean):Boolean {
    stop()
    val pcm=NCConnectionCueSamples.samples(recovered)
    val candidate=createTrack(pcm.size*2);track=candidate
    try {
      check(candidate.write(pcm,0,pcm.size)==pcm.size)
      val accepted=authorize({try{candidate.stop()}catch(_:Throwable){}},{candidate.play();true})
      if(!accepted)stop()
      return accepted
    } catch(error:Throwable) {stop();throw error}
  }
}
