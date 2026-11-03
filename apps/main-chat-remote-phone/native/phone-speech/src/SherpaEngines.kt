package com.neuralcompanion.phonespeech

import com.k2fsa.sherpa.onnx.*
import java.io.File
import java.io.IOException

/** sherpa JNI resolves invoke(float[]): Integer; Kotlin indy lambdas erase that signature. */
internal class SherpaTtsCallback(private val cancelled: () -> Boolean) : (FloatArray) -> Int {
    override fun invoke(samples: FloatArray): Int = if (cancelled()) 0 else 1
}

/** Each engine is accessed/released only on its owning serial inference worker. */
internal class SherpaEngines(private val models: SpeechModels) {
    private var recognizer: OfflineRecognizer? = null
    private var tts: OfflineTts? = null
    @Volatile var sttFailed = false
    @Volatile var ttsFailed = false
    fun readyStt(): Boolean {
        if (sttFailed || !models.installed(SpeechModels.STT)) return false
        return try {
            if (recognizer == null) {
                val dir = models.directory(SpeechModels.STT).absolutePath
                recognizer = OfflineRecognizer(config = OfflineRecognizerConfig(modelConfig = OfflineModelConfig(
                    moonshine = OfflineMoonshineModelConfig(encoder = "$dir/encoder_model.ort", mergedDecoder = "$dir/decoder_model_merged.ort"),
                    tokens = "$dir/tokens.txt", numThreads = 2, provider = "cpu", debug = false)))
            }
            true
        } catch (_: Exception) { sttFailed = true; false } catch (_: LinkageError) { sttFailed = true; false }
    }
    fun readyTts(): Boolean {
        if (ttsFailed || !models.installed(SpeechModels.TTS)) return false
        return try {
            if (tts == null) {
                val dir = models.directory(SpeechModels.TTS).absolutePath
                tts = OfflineTts(config = OfflineTtsConfig(model = OfflineTtsModelConfig(
                    kitten = OfflineTtsKittenModelConfig(model = "$dir/model.int8.onnx", voices = "$dir/voices.bin", tokens = "$dir/tokens.txt", dataDir = "$dir/espeak-ng-data"),
                    numThreads = 2, provider = "cpu", debug = false)))
            }
            true
        } catch (_: Exception) { ttsFailed = true; false } catch (_: LinkageError) { ttsFailed = true; false }
    }
    fun decode(pcm: FloatArray): String {
        if (!readyStt()) throw IOException("stt_model_unavailable")
        val engine = recognizer!!
        val stream = engine.createStream()
        try { stream.acceptWaveform(pcm, 16000); engine.decode(stream); return engine.getResult(stream).text }
        finally { stream.release() }
    }
    fun synthesize(text: String, speaker: Int, file: File, cancelled: () -> Boolean) {
        if (!readyTts()) throw IOException("tts_model_unavailable")
        val audio = tts!!.generateWithCallback(text, sid = speaker, speed = 1.0f, callback = SherpaTtsCallback(cancelled))
        if (cancelled()) throw IOException("cancelled")
        if (!audio.save(file.absolutePath) || !SpeechPolicy.validWav(file)) throw IOException("tts_output_failed")
    }
    fun releaseStt() { recognizer?.release(); recognizer = null }
    fun releaseTts() { tts?.release(); tts = null }
}
