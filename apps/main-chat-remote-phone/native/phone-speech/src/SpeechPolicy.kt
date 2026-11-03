package com.neuralcompanion.phonespeech

import java.io.File
import java.io.RandomAccessFile
import java.util.Locale
import java.util.concurrent.atomic.AtomicLong
import kotlin.math.roundToInt

internal object SpeechPolicy {
    private val sensitivityFloors = doubleArrayOf(-42.0, -46.0, -50.0, -54.0, -58.0)

    fun sensitivityLevel(value: Double): Int =
        if (value.isFinite()) value.coerceIn(1.0, 5.0).roundToInt() else 3

    fun sensitivityFloor(level: Int): Double = sensitivityFloors[level.coerceIn(1, 5) - 1]

    fun language(requested: String, device: String = Locale.getDefault().toLanguageTag()): String {
        val value = requested.ifBlank { device }
        require(value.length <= 64 && Regex("[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*").matches(value)) { "invalid_language" }
        return Locale.forLanguageTag(value).toLanguageTag()
    }
    fun provider(language: String, sherpaReady: Boolean, androidReady: Boolean): String? = when {
        Locale.forLanguageTag(language).language == "en" && sherpaReady -> "sherpa_onnx"
        androidReady -> "android_offline"
        else -> null
    }
    fun matches(requested: String, installed: String): Boolean =
        Locale.forLanguageTag(requested).language == Locale.forLanguageTag(installed).language

    fun child(root: File, name: String): File {
        require(name.isNotBlank() && !name.startsWith('/') && !File(name).isAbsolute && !name.contains('\\') && !name.contains(':')) { "invalid_path" }
        val result = File(root, name).canonicalFile
        require(result.path.startsWith(root.canonicalPath + File.separator)) { "invalid_path" }
        return result
    }
    fun validWav(file: File): Boolean = wavDuration(file) != null
    fun wavDuration(file: File): Double? {
        if (!file.isFile || file.length() <= 44 || file.length() > 128L * 1024 * 1024) return null
        return try { RandomAccessFile(file, "r").use { input ->
            fun tag(): String { val bytes = ByteArray(4); input.readFully(bytes); return String(bytes, Charsets.US_ASCII) }
            fun uint(): Long = Integer.reverseBytes(input.readInt()).toLong() and 0xffffffffL
            if (tag() != "RIFF") return null
            val riffSize = uint() + 8
            if (riffSize > file.length() || tag() != "WAVE") return null
            var sampleRate = 0L; var blockAlign = 0; var dataBytes = 0L
            while (input.filePointer + 8 <= riffSize) {
                val kind = tag(); val size = uint(); val start = input.filePointer
                if (start + size > riffSize) return null
                if (kind == "fmt ") {
                    if (size < 16) return null
                    val format = java.lang.Short.reverseBytes(input.readShort()).toInt() and 0xffff
                    val channels = java.lang.Short.reverseBytes(input.readShort()).toInt() and 0xffff
                    sampleRate = uint(); uint()
                    blockAlign = java.lang.Short.reverseBytes(input.readShort()).toInt() and 0xffff
                    val bits = java.lang.Short.reverseBytes(input.readShort()).toInt() and 0xffff
                    if (format !in listOf(1, 3) || channels !in 1..2 || sampleRate !in 8000..192000 || bits !in listOf(8, 16, 24, 32) || blockAlign != channels * bits / 8) return null
                } else if (kind == "data") dataBytes += size
                input.seek(start + size + size % 2)
            }
            if (sampleRate == 0L || blockAlign == 0 || dataBytes == 0L || dataBytes % blockAlign != 0L) null
            else dataBytes.toDouble() / blockAlign / sampleRate
        } } catch (_: Exception) { null }
    }
}

internal class SpeechEpochs {
    val capture = AtomicLong()
    val synthesis = AtomicLong()
    val installer = AtomicLong()
    fun cancelSynthesis() { synthesis.incrementAndGet() }
    fun cancelAll() { capture.incrementAndGet(); cancelSynthesis(); installer.incrementAndGet() }
}

/** 20 ms frames, 180 ms sustained speech, 900 ms silence, maximum 60 seconds. */
internal class SpeechEndpoint(sensitivityLevel: Int = 3) {
    data class Decision(val started: Boolean, val ended: Boolean, val speaking: Boolean)
    private val absoluteFloor = SpeechPolicy.sensitivityFloor(sensitivityLevel)
    private var floor = -60.0
    private var voiced = 0
    private var silent = 0
    private var frames = 0
    private var active = false
    fun accept(db: Double): Decision {
        frames++
        val loud = db > maxOf(absoluteFloor, floor + 12.0)
        if (!active && !loud) floor = 0.98 * floor + 0.02 * db.coerceIn(-80.0, -35.0)
        voiced = if (loud) voiced + 1 else 0
        val started = !active && voiced >= 9
        if (started) active = true
        silent = if (loud) 0 else silent + 1
        val ended = (active && silent >= 45) || frames >= 3000
        return Decision(started, ended, active)
    }
}
