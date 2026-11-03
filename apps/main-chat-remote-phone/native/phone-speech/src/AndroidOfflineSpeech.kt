package com.neuralcompanion.phonespeech

import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.*
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.speech.tts.Voice
import java.io.File
import java.util.UUID
import java.util.concurrent.CompletableFuture
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/** Small platform boundary; lifecycle remains in AndroidOfflineSpeech. */
internal interface OfflineRecognitionService {
    fun setRecognitionListener(listener: RecognitionListener)
    fun startListening(intent: Intent)
    fun stopListening()
    fun cancel()
    fun destroy()
}

private class PlatformOfflineRecognitionService(context: Context) : OfflineRecognitionService {
    private val service = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
    override fun setRecognitionListener(listener: RecognitionListener) = service.setRecognitionListener(listener)
    override fun startListening(intent: Intent) = service.startListening(intent)
    override fun stopListening() = service.stopListening()
    override fun cancel() = service.cancel()
    override fun destroy() = service.destroy()
}

internal class AndroidOfflineSpeech(private val context: Context,
    private val createRecognizer: () -> OfflineRecognitionService = { PlatformOfflineRecognitionService(context) },
) {
    private val main = Handler(Looper.getMainLooper())
    private val mainExecutor = Executor { main.post(it) }
    private var tts: TextToSpeech? = null
    private var ttsInit: CompletableFuture<TextToSpeech>? = null
    private var recognizer: OfflineRecognitionService? = null
    private var recognitionGeneration = 0L
    private var recognitionAwaitingResult = false
    private var recognitionRestart: Runnable? = null
    private var finishRecognition: (() -> Unit)? = null
    private var synthesis: CompletableFuture<Unit>? = null
    private var utteranceId: String? = null
    private var continueLive = false
    private fun intent(language: String) = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
        putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
        putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
        putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
    }
    /** Called off-main; readiness cannot be inferred from recognition service presence. */
    fun readyStt(language: String): Boolean {
        if (Build.VERSION.SDK_INT < 33) return false
        val result = CompletableFuture<Boolean>()
        main.post {
            var probe: SpeechRecognizer? = null
            try {
                if (!SpeechRecognizer.isOnDeviceRecognitionAvailable(context)) { result.complete(false); return@post }
                probe = SpeechRecognizer.createOnDeviceSpeechRecognizer(context)
                val service = probe
                service.checkRecognitionSupport(intent(language), mainExecutor, object : RecognitionSupportCallback {
                    override fun onSupportResult(support: RecognitionSupport) {
                        result.complete(support.installedOnDeviceLanguages.any { SpeechPolicy.matches(language, it) })
                        service.destroy()
                    }
                    override fun onError(error: Int) { result.complete(false); service.destroy() }
                })
                main.postDelayed({ if (result.complete(false)) service.destroy() }, 5000)
            } catch (_: Exception) { probe?.destroy(); result.complete(false) }
        }
        return try { result.get(6, TimeUnit.SECONDS) } catch (_: Exception) { false }
    }

    private fun initialized(): CompletableFuture<TextToSpeech> {
        val result = CompletableFuture<TextToSpeech>()
        main.post {
            val existing = ttsInit
            if (existing != null) { existing.whenComplete { value, error -> if (error != null) result.completeExceptionally(error) else result.complete(value) }; return@post }
            ttsInit = result
            try {
                tts = TextToSpeech(context) { status -> main.post {
                    val engine = tts
                    if (status == TextToSpeech.SUCCESS && engine != null) result.complete(engine)
                    else result.completeExceptionally(IllegalStateException("offline_tts_unavailable"))
                } }
                main.postDelayed({ result.completeExceptionally(IllegalStateException("offline_tts_timeout")) }, 5000)
            } catch (_: Exception) { result.completeExceptionally(IllegalStateException("offline_tts_unavailable")) }
        }
        return result
    }
    private fun voice(engine: TextToSpeech, language: String): Voice? = engine.voices?.filter {
        !it.isNetworkConnectionRequired && !it.features.orEmpty().contains(TextToSpeech.Engine.KEY_FEATURE_NOT_INSTALLED) && SpeechPolicy.matches(language, it.locale.toLanguageTag())
    }?.sortedWith(compareByDescending<Voice> { it.locale.toLanguageTag().equals(language, true) }.thenBy { it.name })?.firstOrNull()

    fun readyTts(language: String): Boolean {
        return try {
            val engine = initialized().get(6, TimeUnit.SECONDS)
            val result = CompletableFuture<Boolean>()
            main.post { try { result.complete(voice(engine, language) != null) } catch (_: Exception) { result.complete(false) } }
            result.get(2, TimeUnit.SECONDS)
        } catch (_: Exception) { false }
    }

    fun start(session: String, language: String, live: Boolean, current: () -> Boolean,
              state: (String, Double?) -> Unit, transcript: (String) -> Unit, error: (String) -> Unit, started: () -> Unit) {
        main.post {
            cancelRecognition()
            val generation = recognitionGeneration
            continueLive = live
            var retries = 0
            var busyErrors = 0
            fun valid() = generation == recognitionGeneration && current()
            fun finish() {
                if (generation != recognitionGeneration) return
                recognitionGeneration++
                continueLive = false
                recognitionAwaitingResult = false
                clearRecognitionRestart()
                finishRecognition = null
                val service = recognizer
                recognizer = null
                service?.destroy()
                if (current()) state("off", null)
            }
            finishRecognition = ::finish
            lateinit var listen: () -> Unit
            fun restart() {
                if (!valid()) return
                if (!continueLive) { finish(); return }
                retries = minOf(8, retries + 1)
                clearRecognitionRestart()
                val restart = object : Runnable {
                    override fun run() {
                        if (recognitionRestart !== this) return
                        recognitionRestart = null
                        if (valid()) { if (continueLive) listen() else finish() }
                    }
                }
                recognitionRestart = restart
                main.postDelayed(restart, minOf(2000L, 250L * retries))
            }
            listen = listen@{
                if (!valid()) return@listen
                try {
                    recognizer?.destroy()
                    val service = createRecognizer()
                    recognizer = service
                    recognitionAwaitingResult = true
                    var completed = false
                    var listeningState = "listening"
                    fun currentCycle() = valid() && recognizer === service && !completed
                    service.setRecognitionListener(object : RecognitionListener {
                        override fun onReadyForSpeech(params: Bundle?) { if (currentCycle()) { state("listening", null); started() } }
                        override fun onBeginningOfSpeech() { if (currentCycle()) { listeningState = "speech"; state("speech", null) } }
                        private var lastMeter = 0L
                        override fun onRmsChanged(rmsdB: Float) { val now = android.os.SystemClock.elapsedRealtime(); if (currentCycle() && now - lastMeter >= 100) { lastMeter = now; state(listeningState, rmsdB.toDouble()) } }
                        override fun onBufferReceived(buffer: ByteArray?) { }
                        override fun onEndOfSpeech() { if (currentCycle()) { listeningState = "processing"; state("processing", null) } }
                        override fun onError(code: Int) {
                            if (!currentCycle()) return
                            completed = true
                            recognitionAwaitingResult = false
                            if (code == SpeechRecognizer.ERROR_NO_MATCH || code == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) { busyErrors = 0; restart() }
                            else if (code == SpeechRecognizer.ERROR_RECOGNIZER_BUSY && ++busyErrors <= 5) restart()
                            else { error("offline_recognition_$code"); finish() }
                        }
                        override fun onResults(results: Bundle?) {
                            if (!currentCycle()) return
                            completed = true
                            recognitionAwaitingResult = false
                            val text = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull().orEmpty().trim()
                            if (text.isNotEmpty()) { retries = 0; busyErrors = 0; transcript(text) }
                            restart()
                        }
                        override fun onPartialResults(partialResults: Bundle?) { }
                        override fun onEvent(eventType: Int, params: Bundle?) { }
                    })
                    service.startListening(intent(language))
                    main.postDelayed({ if (currentCycle()) service.stopListening() }, 60000)
                    main.postDelayed({ if (currentCycle()) { error("offline_recognition_timeout"); finish() } }, 70000)
                } catch (_: Exception) { error("offline_recognition_unavailable"); finish() }
            }
            listen()
        }
    }

    fun stopRecognition(commit: Boolean) { main.post {
        continueLive = false
        clearRecognitionRestart()
        if (!commit) cancelRecognition()
        else if (recognitionAwaitingResult) recognizer?.stopListening()
        else finishRecognition?.invoke()
    } }
    private fun clearRecognitionRestart() {
        recognitionRestart?.let { main.removeCallbacks(it) }
        recognitionRestart = null
    }
    private fun cancelRecognition() {
        recognitionGeneration++
        continueLive = false
        recognitionAwaitingResult = false
        clearRecognitionRestart()
        finishRecognition = null
        val service = recognizer
        recognizer = null
        service?.cancel()
        service?.destroy()
    }

    /** Returns only after onDone and valid WAV. No speak()/playback calls. */
    fun synthesize(text: String, language: String, file: File, current: () -> Boolean) {
        val engine = initialized().get(6, TimeUnit.SECONDS)
        val result = CompletableFuture<Unit>()
        val id = UUID.randomUUID().toString()
        main.post {
            if (!current()) { result.completeExceptionally(IllegalStateException("cancelled")); return@post }
            try {
                val selected = voice(engine, language) ?: throw IllegalStateException("offline_voice_unavailable")
                if (engine.setVoice(selected) != TextToSpeech.SUCCESS) throw IllegalStateException("offline_voice_unavailable")
                synthesis = result; utteranceId = id
                engine.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                    override fun onStart(utterance: String?) { }
                    override fun onDone(utterance: String?) {
                        if (utterance == id) {
                            if (current() && SpeechPolicy.validWav(file)) result.complete(Unit)
                            else result.completeExceptionally(IllegalStateException("tts_output_failed"))
                        }
                    }
                    @Deprecated("Android callback") override fun onError(utterance: String?) { if (utterance == id) result.completeExceptionally(IllegalStateException("offline_tts_failed")) }
                    override fun onStop(utterance: String?, interrupted: Boolean) { if (utterance == id) result.completeExceptionally(IllegalStateException("cancelled")) }
                })
                if (text.length > TextToSpeech.getMaxSpeechInputLength() || engine.synthesizeToFile(text, Bundle(), file, id) != TextToSpeech.SUCCESS) throw IllegalStateException("offline_tts_failed")
                main.postDelayed({ if (utteranceId == id && result.completeExceptionally(IllegalStateException("offline_tts_timeout"))) engine.stop() }, 60000)
            } catch (_: Exception) { result.completeExceptionally(IllegalStateException("offline_tts_failed")) }
        }
        try { result.get(65, TimeUnit.SECONDS) } finally { main.post { if (utteranceId == id) { synthesis = null; utteranceId = null } } }
    }
    fun cancelSynthesis() { main.post { synthesis?.completeExceptionally(IllegalStateException("cancelled")); synthesis = null; utteranceId = null; tts?.stop() } }
    fun cancel() { main.post { cancelRecognition() }; cancelSynthesis() }
    fun shutdown() { cancel(); main.post { tts?.shutdown(); tts = null; ttsInit = null } }
}
