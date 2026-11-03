package com.neuralcompanion.phonespeech

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import java.io.IOException
import kotlin.math.log10
import kotlin.math.sqrt

/** AudioRecord/effect lifetime belongs to this dedicated capture thread, never an inference worker. */
internal class PhoneCapture(
    private val live: Boolean,
    private val current: () -> Boolean,
    private val state: (String, Double?) -> Unit,
    private val utterance: (FloatArray) -> Unit,
    private val started: () -> Unit,
    private val failed: () -> Unit,
    private val sensitivityLevel: Int = 3,
) {
    @Volatile private var running = true
    @Volatile private var commit = false
    @Volatile private var recorder: AudioRecord? = null
    fun stop(shouldCommit: Boolean) {
        commit = shouldCommit; running = false
        try { recorder?.stop() } catch (_: IllegalStateException) { }
    }
    @Suppress("MissingPermission")
    fun run() {
        var effect: AcousticEchoCanceler? = null
        var audio: AudioRecord? = null
        val pcm = FloatArray(16000 * 60)
        var count = 0; var speech = false
        try {
            if (!running || !current()) return
            val min = AudioRecord.getMinBufferSize(16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
            if (min <= 0) throw IOException("capture_unavailable")
            audio = AudioRecord(if (live) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.VOICE_RECOGNITION,
                16000, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(min * 2, 6400))
            recorder = audio
            if (audio.state != AudioRecord.STATE_INITIALIZED) throw IOException("capture_unavailable")
            if (live && AcousticEchoCanceler.isAvailable()) {
                try { effect = AcousticEchoCanceler.create(audio.audioSessionId); effect?.enabled = true } catch (_: Exception) { }
            }
            if (!running || !current()) return
            audio.startRecording()
            if (audio.recordingState != AudioRecord.RECORDSTATE_RECORDING) throw IOException("capture_unavailable")
            started(); state("listening", null)
            var endpoint = SpeechEndpoint(sensitivityLevel)
            val frame = ShortArray(320)
            var frames = 0
            while (running && current()) {
                val n = audio.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (n <= 0) { if (!running) break; throw IOException("capture_failed") }
                var energy = 0.0
                for (i in 0 until n) { val sample = frame[i] / 32768f; energy += sample * sample; if (count < pcm.size) pcm[count++] = sample }
                val db = (20.0 * log10(maxOf(sqrt(energy / n), 0.00001))).coerceIn(-100.0, 0.0)
                val decision = endpoint.accept(db)
                if (decision.started) { speech = true; state("speech", db) }
                else if (++frames % 5 == 0) state(if (speech) "speech" else "listening", db)
                if (decision.ended || count == pcm.size) {
                    if (speech && count > 0 && current()) { state("processing", db); utterance(pcm.copyOf(count)) }
                    count = 0; speech = false; endpoint = SpeechEndpoint(sensitivityLevel)
                    if (!live) { running = false; break }
                    state("listening", db)
                } else if (!speech && count > 6400) {
                    System.arraycopy(pcm, count - 6400, pcm, 0, 6400); count = 6400
                }
            }
            if (commit && current() && count > 0 && speech) { state("processing", null); utterance(pcm.copyOf(count)) }
        } catch (_: Exception) { if (running && current()) failed() }
        finally {
            recorder = null
            try { audio?.stop() } catch (_: IllegalStateException) { }
            effect?.release(); audio?.release()
            if (current()) state("off", null)
        }
    }
}
