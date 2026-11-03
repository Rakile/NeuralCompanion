package com.neuralcompanion.phonespeech

import android.content.Context
import java.io.File
import java.io.IOException
import java.net.URL
import javax.net.ssl.HttpsURLConnection
import java.security.MessageDigest
import java.util.UUID
import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.bzip2.BZip2CompressorInputStream

internal class SpeechModels(context: Context, private val progress: (String, String, Long, Long) -> Unit) {
    data class Pack(val id: String, val root: String, val release: String, val bytes: Long, val sha: String, val required: List<String>) {
        val url get() = "https://github.com/k2-fsa/sherpa-onnx/releases/download/$release/$root.tar.bz2"
    }
    companion object {
        val STT = Pack("stt", "sherpa-onnx-moonshine-tiny-en-quantized-2026-02-27", "asr-models", 29858559,
            "9ec31b342d8fa3240c3b81b8f82e1cf7e3ac467c93ca5a999b741d5887164f8d", listOf("encoder_model.ort", "decoder_model_merged.ort", "tokens.txt", "LICENSE"))
        val TTS = Pack("tts", "kitten-nano-en-v0_8-int8", "tts-models", 31220690,
            "6fa5be852612ce761094ba74ee6123b4fc4acfefa79bf64dc63acae4a83af2fd", listOf("model.int8.onnx", "voices.bin", "tokens.txt", "espeak-ng-data/phontab", "LICENSE"))
    }
    private val root = File(context.noBackupFilesDir, "phone-native-audio/models").apply { mkdirs() }
    fun directory(pack: Pack) = File(root, pack.root)
    fun installed(pack: Pack): Boolean = File(directory(pack), ".verified").isFile && pack.required.all { File(directory(pack), it).isFile }
    private fun check(cancelled: () -> Boolean) { if (cancelled()) throw IOException("cancelled") }

    fun installAll(cancelled: () -> Boolean) {
        for (pack in listOf(STT, TTS)) {
            check(cancelled)
            if (installed(pack)) { progress(pack.id, "ready", pack.bytes, pack.bytes); continue }
            val archive = File(root, "${UUID.randomUUID()}.part")
            try { download(pack, archive, cancelled); installArchive(pack, archive, cancelled) }
            finally { archive.delete() }
        }
    }

    private fun download(pack: Pack, target: File, cancelled: () -> Boolean) {
        var url = URL(pack.url)
        repeat(6) {
            check(cancelled)
            require(url.protocol == "https" && (url.host == "github.com" || url.host == "release-assets.githubusercontent.com" || url.host == "objects.githubusercontent.com")) { "invalid_download_host" }
            val connection = url.openConnection() as HttpsURLConnection
            connection.instanceFollowRedirects = false
            connection.connectTimeout = 15000
            connection.readTimeout = 15000
            try {
                val status = connection.responseCode
                if (status in listOf(301, 302, 303, 307, 308)) {
                    url = URL(url, connection.getHeaderField("Location") ?: throw IOException("download_failed"))
                } else {
                    if (status != 200) throw IOException("download_failed")
                    var count = 0L
                    connection.inputStream.buffered().use { input -> target.outputStream().use { output ->
                        val buffer = ByteArray(65536)
                        while (true) {
                            check(cancelled)
                            val n = input.read(buffer); if (n < 0) break
                            count += n; if (count > pack.bytes) throw IOException("download_too_large")
                            output.write(buffer, 0, n)
                            progress(pack.id, "downloading", count, pack.bytes)
                        }
                    } }
                    if (count != pack.bytes) throw IOException("download_incomplete")
                    return
                }
            } finally { connection.disconnect() }
        }
        throw IOException("download_redirect_limit")
    }

    fun installArchive(pack: Pack, archive: File, cancelled: () -> Boolean) {
        progress(pack.id, "verifying", 0, pack.bytes)
        if (archive.length() != pack.bytes) throw IOException("model_checksum_failed")
        val digest = MessageDigest.getInstance("SHA-256")
        archive.inputStream().buffered().use { input ->
            val buffer = ByteArray(65536)
            while (true) { check(cancelled); val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) }
        }
        if (digest.digest().joinToString("") { "%02x".format(it) } != pack.sha) throw IOException("model_checksum_failed")
        val stage = File(root, "${pack.id}-${UUID.randomUUID()}.stage").apply { mkdirs() }
        try {
            var entries = 0; var expanded = 0L
            TarArchiveInputStream(BZip2CompressorInputStream(archive.inputStream().buffered())).use { tar ->
                while (true) {
                    check(cancelled)
                    val entry = tar.nextTarEntry ?: break
                    if (++entries > 4096 || (!entry.isFile && !entry.isDirectory) || entry.isSymbolicLink || entry.isLink || entry.size < 0) throw IOException("unsafe_archive")
                    val name = entry.name.trimEnd('/')
                    if (name != pack.root && !name.startsWith(pack.root + "/")) throw IOException("unsafe_archive")
                    val target = SpeechPolicy.child(stage, name)
                    if (entry.isDirectory) { target.mkdirs(); continue }
                    expanded += entry.size
                    if (expanded > 256L * 1024 * 1024) throw IOException("archive_too_large")
                    target.parentFile!!.mkdirs()
                    target.outputStream().use { output ->
                        val buffer = ByteArray(65536); var written = 0L
                        while (true) {
                            check(cancelled); val n = tar.read(buffer); if (n < 0) break
                            written += n; if (written > entry.size) throw IOException("unsafe_archive")
                            output.write(buffer, 0, n)
                        }
                        if (written != entry.size) throw IOException("incomplete_archive")
                    }
                    progress(pack.id, "extracting", expanded, 0)
                }
            }
            val extracted = File(stage, pack.root)
            if (!pack.required.all { File(extracted, it).isFile }) throw IOException("incomplete_model")
            File(extracted, ".verified").writeText(pack.sha)
            check(cancelled)
            val destination = directory(pack)
            if (installed(pack)) return
            // The path is module-owned; retain an old incomplete copy until publication succeeds.
            val previous = File(root, "${UUID.randomUUID()}.old")
            if (destination.exists() && !destination.renameTo(previous)) throw IOException("model_publish_failed")
            if (!extracted.renameTo(destination)) {
                if (previous.exists()) previous.renameTo(destination)
                throw IOException("model_publish_failed")
            }
            previous.deleteRecursively()
            progress(pack.id, "ready", pack.bytes, pack.bytes)
        } finally { stage.deleteRecursively() }
    }
}
