package com.neuralcompanion.phonespeech

import android.Manifest
import android.content.Context
import android.os.PowerManager
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import com.facebook.react.ReactPackage
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.DeviceEventManagerModule
import com.facebook.react.uimanager.ViewManager
import java.io.File
import java.util.Locale
import java.util.UUID
import java.util.concurrent.*
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference

class PhoneSpeechPackage : ReactPackage {
    override fun createNativeModules(context: ReactApplicationContext): List<NativeModule> = listOf(PhoneSpeechModule(context))
    override fun createViewManagers(context: ReactApplicationContext): List<ViewManager<*, *>> = emptyList()
}

private class Reply(private val promise: Promise) {
    private val done = AtomicBoolean()
    fun resolve(value: Any? = null): Boolean { if (!done.compareAndSet(false, true)) return false; promise.resolve(value); return true }
    fun reject(code: String) { if (done.compareAndSet(false, true)) promise.reject(code, code.replace('_', ' ')) }
}

class PhoneSpeechModule(private val context: ReactApplicationContext) : ReactContextBaseJavaModule(context), LifecycleEventListener {
    private val main = Handler(Looper.getMainLooper())
    private val epochs = SpeechEpochs()
    private fun worker(name: String, queued: Int) = ThreadPoolExecutor(1, 1, 0, TimeUnit.MILLISECONDS,
        ArrayBlockingQueue<Runnable>(queued), ThreadFactory { task -> Thread(task, "nc-phone-$name").apply { isDaemon = true } })
    private val stt = worker("stt", 2)
    private val tts = worker("tts", 2)
    private val captureWorker = worker("capture", 1)
    private val installer = worker("install", 1)
    private val files = worker("files", 16)
    private val probes = worker("capabilities", 2)
    private val android = AndroidOfflineSpeech(context)
    private var lastProgress = 0L
    private val models = SpeechModels(context) { model, phase, bytes, total ->
        val now = SystemClock.elapsedRealtime()
        if (pendingInstall.get() != null && (phase != "downloading" || now - lastProgress >= 100 || bytes == total)) {
            lastProgress = now
            emit("onModelProgress", mapOf("model" to model, "phase" to phase, "bytes" to bytes.toDouble(), "totalBytes" to total.toDouble()))
        }
    }
    private val engines = SherpaEngines(models)
    private val audioRoot = File(context.cacheDir, "phone-native-audio").apply { mkdirs() }
    private val ownedAudio = ConcurrentHashMap.newKeySet<String>()
    private val pendingStart = AtomicReference<Reply?>()
    private val pendingSynthesis = AtomicReference<Reply?>()
    private val pendingInstall = AtomicReference<Reply?>()
    private val installing = AtomicBoolean()
    @Volatile private var capture: PhoneCapture? = null
    @Volatile private var session: String? = null
    @Volatile private var destroyed = false
    @Volatile private var foreground = true

    init {
        context.addLifecycleEventListener(this)
        val staleBefore = System.currentTimeMillis() - TimeUnit.DAYS.toMillis(1)
        files.execute {
            // Conservatively retain recent files across a React reload/player lifetime.
            audioRoot.listFiles()?.filter { it.isFile && it.lastModified() < staleBefore && it.name.startsWith("nc-") && it.name.endsWith(".wav") }
                ?.forEach { it.delete() }
        }
    }
    override fun getName() = "NcPhoneNativeAudio"
    @ReactMethod fun connectionPowerState(promise: Promise) {
        try {
            probes.execute {
                try {
                    val power = context.getSystemService(Context.POWER_SERVICE) as PowerManager
                    promise.resolve(Arguments.createMap().apply {
                        putBoolean("powerSave", power.isPowerSaveMode)
                        putBoolean("deviceIdle", power.isDeviceIdleMode)
                        putBoolean("interactive", power.isInteractive)
                    })
                } catch (_: Exception) { promise.reject("power_state_unavailable", "Power state unavailable") }
            }
        } catch (_: Exception) { promise.reject("power_state_unavailable", "Power state unavailable") }
    }
    @ReactMethod fun addListener(eventName: String) { }
    @ReactMethod fun removeListeners(count: Double) { }
    private fun emit(event: String, data: Map<String, Any?>) {
        if (!destroyed && context.hasActiveReactInstance()) context.getJSModule(DeviceEventManagerModule.RCTDeviceEventEmitter::class.java).emit(event, Arguments.makeNativeMap(data))
    }
    private fun error(code: String, id: String? = session) = emit("onError", mapOf("sessionId" to id, "code" to code, "message" to code.replace('_', ' ')))
    private fun listenState(id: String, state: String, db: Double?) = emit("onListeningState", mapOf("sessionId" to id, "state" to state, "meteringDb" to db))
    private fun transcript(id: String, text: String, provider: String, language: String) {
        if (text.isNotBlank()) emit("onTranscript", mapOf("sessionId" to id, "utteranceId" to UUID.randomUUID().toString(), "text" to text.trim(), "isFinal" to true, "provider" to provider, "language" to language))
    }
    private fun submit(worker: ThreadPoolExecutor, reply: Reply? = null, action: () -> Unit): Boolean {
        return try { worker.execute { try { action() } catch (_: Exception) { reply?.reject("native_operation_failed") } catch (_: LinkageError) { reply?.reject("native_engine_unavailable") } }; true }
        catch (_: RejectedExecutionException) { reply?.reject("native_busy"); false }
    }
    private fun resolvedLanguage(language: String, reply: Reply): String? = try { SpeechPolicy.language(language) } catch (_: IllegalArgumentException) { reply.reject("invalid_language"); null }
    private fun route(language: String, sherpa: Boolean, offline: Boolean, failed: Boolean): Map<String, Any?> {
        val provider = SpeechPolicy.provider(language, sherpa, offline)
        return mapOf("available" to (provider != null), "provider" to provider, "language" to language,
            "reason" to if (failed && provider == "android_offline") "model_failed_using_android_offline"
                else if (provider != null) null else if (failed) "model_failed_no_offline_fallback" else "offline_language_unavailable")
    }

    @ReactMethod fun getCapabilities(language: String, promise: Promise) {
        val reply = Reply(promise); val resolved = resolvedLanguage(language, reply) ?: return
        if (destroyed) { reply.reject("app_inactive"); return }
        submit(probes, reply) {
            val english = Locale.forLanguageTag(resolved).language == "en"
            val nativeStt = CompletableFuture.supplyAsync({ english && engines.readyStt() }, stt)
            val nativeTts = CompletableFuture.supplyAsync({ english && engines.readyTts() }, tts)
            val offlineStt = android.readyStt(resolved)
            val offlineTts = android.readyTts(resolved)
            val sttRoute = route(resolved, nativeStt.get(45, TimeUnit.SECONDS), offlineStt, english && engines.sttFailed)
            val ttsRoute = route(resolved, nativeTts.get(45, TimeUnit.SECONDS), offlineTts, english && engines.ttsFailed)
            val available = sttRoute["available"] == true && ttsRoute["available"] == true
            reply.resolve(Arguments.makeNativeMap(mapOf("available" to available, "reason" to if (available) null else "offline_audio_not_ready",
                "deviceLanguage" to Locale.getDefault().toLanguageTag(), "stt" to sttRoute, "tts" to ttsRoute,
                "models" to mapOf("sttInstalled" to models.installed(SpeechModels.STT), "ttsInstalled" to models.installed(SpeechModels.TTS)))))
        }
    }

    @ReactMethod fun installModels(promise: Promise) {
        val reply = Reply(promise)
        if (!installing.compareAndSet(false, true)) { reply.reject("model_install_busy"); return }
        pendingInstall.set(reply)
        val epoch = epochs.installer.get()
        val scheduled = submit(installer, reply) {
            try {
                models.installAll { epochs.installer.get() != epoch || destroyed }
                if (epochs.installer.get() == epoch && !destroyed) reply.resolve() else reply.reject("cancelled")
            } catch (_: Exception) { reply.reject(if (epochs.installer.get() != epoch) "cancelled" else "model_install_failed") }
            finally { pendingInstall.compareAndSet(reply, null); installing.set(false) }
        }
        if (!scheduled) { pendingInstall.compareAndSet(reply, null); installing.set(false) }
    }

    private fun stopCapture(commit: Boolean) {
        val canCommit = commit && pendingStart.get() == null
        capture?.stop(canCommit)
        android.stopRecognition(canCommit)
        if (!canCommit) {
            epochs.capture.incrementAndGet()
            pendingStart.getAndSet(null)?.reject("cancelled")
            session?.let { listenState(it, "off", null) }
            session = null
        }
    }

    @ReactMethod fun startListening(sessionId: String, language: String, live: Boolean, promise: Promise) {
        startListeningInternal(sessionId, language, live, 3, promise)
    }

    @ReactMethod fun startListeningWithSensitivity(sessionId: String, language: String, live: Boolean, sensitivity: Double, promise: Promise) {
        startListeningInternal(sessionId, language, live, SpeechPolicy.sensitivityLevel(sensitivity), promise)
    }

    private fun startListeningInternal(sessionId: String, language: String, live: Boolean, sensitivityLevel: Int, promise: Promise) {
        val reply = Reply(promise); val resolved = resolvedLanguage(language, reply) ?: return
        if (sessionId.isBlank() || sessionId.length > 128) { reply.reject("invalid_session"); return }
        if (!foreground || destroyed) { reply.reject("app_inactive"); return }
        if (context.checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) { reply.reject("microphone_permission_denied"); return }
        stopCapture(false)
        val epoch = epochs.capture.get()
        session = sessionId; pendingStart.set(reply)
        fun current() = epoch == epochs.capture.get() && !destroyed && foreground
        fun started() { if (current()) { reply.resolve(); pendingStart.compareAndSet(reply, null) } }
        fun fail(code: String) { if (current()) { error(code, sessionId); reply.reject(code); pendingStart.compareAndSet(reply, null) } }
        fun fallback() {
            if (!current()) return
            if (android.readyStt(resolved)) android.start(sessionId, resolved, live, ::current,
                { state, db -> if (current()) listenState(sessionId, state, db) },
                { text -> if (current()) transcript(sessionId, text, "android_offline", resolved) }, ::fail, ::started)
            else { fail("offline_stt_unavailable"); listenState(sessionId, "off", null) }
        }
        submit(stt, reply) {
            if (!current()) return@submit
            if (Locale.forLanguageTag(resolved).language != "en" || !engines.readyStt()) {
                if (engines.sttFailed) error("stt_model_failed", sessionId)
                fallback(); return@submit
            }
            val sherpaRouteActive = AtomicBoolean(true)
            fun failedSherpa() {
                engines.sttFailed = true
                if (current() && sherpaRouteActive.compareAndSet(true, false)) { error("stt_model_failed", sessionId); capture?.stop(false); fallback() }
            }
            val recording = PhoneCapture(live, ::current,
                { state, db -> if (current() && sherpaRouteActive.get()) listenState(sessionId, state, db) },
                { pcm ->
                    try { stt.execute {
                        if (current() && sherpaRouteActive.get()) {
                            try { val text = engines.decode(pcm); if (current()) transcript(sessionId, text, "sherpa_onnx", resolved) }
                            catch (_: Exception) { failedSherpa() }
                            catch (_: LinkageError) { failedSherpa() }
                        }
                    } } catch (_: RejectedExecutionException) { if (current()) error("stt_busy_utterance_discarded", sessionId) }
                }, ::started, { fail("microphone_capture_failed") }, sensitivityLevel)
            if (current()) { capture = recording; submit(captureWorker, reply) { recording.run() } }
        }
        main.postDelayed({ if (pendingStart.compareAndSet(reply, null)) { reply.reject("listening_start_timeout"); if (current()) stopCapture(false) } }, 60000)
    }

    @ReactMethod fun stopListening(commit: Boolean, promise: Promise) { stopCapture(commit); promise.resolve(null) }

    @ReactMethod fun synthesize(text: String, language: String, speakerId: Double, promise: Promise) {
        val reply = Reply(promise); val resolved = resolvedLanguage(language, reply) ?: return
        if (text.isBlank() || text.length > 3000 || !speakerId.isFinite() || speakerId != speakerId.toInt().toDouble() || speakerId !in 0.0..7.0) { reply.reject("invalid_synthesis_input"); return }
        if (!foreground || destroyed) { reply.reject("app_inactive"); return }
        if (!pendingSynthesis.compareAndSet(null, reply)) { reply.reject("tts_busy"); return }
        val epoch = epochs.synthesis.get()
        fun current() = epoch == epochs.synthesis.get() && !destroyed && foreground
        val scheduled = submit(tts, reply) {
            val file = File(audioRoot, "nc-${UUID.randomUUID()}.wav")
            var published = false
            try {
                if (!current()) { reply.reject("cancelled"); return@submit }
                var provider = "android_offline"
                var generated = false
                if (Locale.forLanguageTag(resolved).language == "en" && engines.readyTts()) {
                    try { engines.synthesize(text, speakerId.toInt(), file) { !current() }; generated = true; provider = "sherpa_onnx" }
                    catch (_: Exception) { if (current()) { engines.ttsFailed = true; error("tts_model_failed", null) } }
                    catch (_: LinkageError) { engines.ttsFailed = true; if (current()) error("tts_model_failed", null) }
                }
                if (!current()) { reply.reject("cancelled"); return@submit }
                if (!generated) {
                    if (engines.ttsFailed && Locale.forLanguageTag(resolved).language == "en") error("tts_model_failed", null)
                    if (!android.readyTts(resolved)) { reply.reject("offline_tts_unavailable"); return@submit }
                    android.synthesize(text, resolved, file, ::current)
                }
                if (current() && SpeechPolicy.validWav(file)) {
                    ownedAudio.add(file.canonicalPath)
                    published = reply.resolve(Arguments.makeNativeMap(mapOf("uri" to Uri.fromFile(file).toString(), "provider" to provider, "language" to resolved, "durationSeconds" to SpeechPolicy.wavDuration(file))))
                    if (!published) ownedAudio.remove(file.canonicalPath)
                } else reply.reject("cancelled")
            } catch (_: Exception) { reply.reject(if (current()) "local_tts_failed" else "cancelled") }
            finally { if (!published) file.delete(); pendingSynthesis.compareAndSet(reply, null) }
        }
        if (!scheduled) pendingSynthesis.compareAndSet(reply, null)
    }
    private fun cancelVoice() {
        epochs.cancelSynthesis()
        pendingSynthesis.getAndSet(null)?.reject("cancelled")
        android.cancelSynthesis()
    }
    @ReactMethod fun cancelSynthesis(promise: Promise) { cancelVoice(); promise.resolve(null) }
    private fun cancelAll() {
        stopCapture(false); cancelVoice(); epochs.installer.incrementAndGet()
        pendingInstall.getAndSet(null)?.reject("cancelled")
    }
    @ReactMethod fun cancel(promise: Promise) { cancelAll(); promise.resolve(null) }
    @ReactMethod fun deleteAudio(uri: String, promise: Promise) {
        val reply = Reply(promise)
        submit(files, reply) {
            try {
                val parsed = Uri.parse(uri)
                require(parsed.scheme == "file" && parsed.authority.isNullOrEmpty())
                val file = File(parsed.path ?: "").canonicalFile
                require(file.parentFile == audioRoot.canonicalFile && ownedAudio.contains(file.path))
                if (file.exists() && !file.delete()) { reply.reject("audio_delete_failed"); return@submit }
                ownedAudio.remove(file.path); reply.resolve()
            } catch (_: IllegalArgumentException) { reply.reject("audio_not_owned") }
        }
    }
    override fun onHostResume() { foreground = true }
    override fun onHostPause() { foreground = false; cancelAll() }
    override fun onHostDestroy() { foreground = false; cancelAll() }
    override fun invalidate() {
        destroyed = true; cancelAll(); android.shutdown(); context.removeLifecycleEventListener(this)
        // Release JNI pointers on the same worker after any in-flight native calls return.
        stt.queue.clear(); tts.queue.clear()
        stt.execute { engines.releaseStt() }; tts.execute { engines.releaseTts() }
        listOf(stt, tts, installer, files, captureWorker, probes).forEach { it.shutdown() }
        super.invalidate()
    }
}
