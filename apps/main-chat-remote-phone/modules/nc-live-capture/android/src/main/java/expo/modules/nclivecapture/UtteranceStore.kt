package expo.modules.nclivecapture

import java.io.File
import java.io.FileOutputStream
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

data class OwnedClip(val sessionId: String, val utteranceId: String, val uri: String, val byteLength: Long, val durationMs: Double)
class UtteranceStoreException(val failure: CaptureFailure, cause: Throwable? = null) : RuntimeException(failure.wireValue, cause)

class UtteranceStore(root: File) {
  private data class Key(val session: String, val utterance: String)
  private data class Entry(val clip: OwnedClip, val file: File, var leased: Boolean = false, var retired: Boolean = false)
  private val directory = File(root, "nc-live-capture")
  private val entries = mutableMapOf<Key, Entry>()

  init {
    synchronized(lock) {
      if ((!directory.exists() && !directory.mkdirs()) || !directory.isDirectory) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    }
  }

  fun write(sessionId: String, utteranceId: String, samples: ShortArray): OwnedClip = synchronized(lock) {
    validate(sessionId, utteranceId)
    if (samples.isEmpty() || samples.size > 960_000) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    val files = directory.listFiles()?.toList() ?: throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    val existing = files.map { it.canonicalPath }.toSet()
    entries.entries.removeIf { it.value.file.canonicalPath !in existing }
    val key = Key(sessionId, utteranceId)
    if (entries.containsKey(key)) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    if (files.size >= 2) throw UtteranceStoreException(CaptureFailure.BACKLOG_FULL)
    val file = File(directory, "${UUID.randomUUID()}.wav")
    var created = false
    try {
      check(file.createNewFile()) { "owned file already exists" }
      created = true
      FileOutputStream(file).use { output ->
        output.write(wavHeader(samples.size))
        val bytes = ByteBuffer.allocate(8192).order(ByteOrder.LITTLE_ENDIAN)
        var index = 0
        while (index < samples.size) {
          bytes.clear()
          repeat(minOf(4096, samples.size - index)) { bytes.putShort(samples[index++]) }
          output.write(bytes.array(), 0, bytes.position())
        }
      }
      val clip = OwnedClip(sessionId, utteranceId, file.toURI().toString(), 44L + samples.size * 2L, samples.size / 16.0)
      entries[key] = Entry(clip, file)
      clip
    } catch (error: Throwable) {
      if (created) file.delete()
      throw UtteranceStoreException(CaptureFailure.FILE_FAILED, error)
    }
  }

  fun acquire(sessionId: String, utteranceId: String): OwnedClip = synchronized(lock) {
    validate(sessionId, utteranceId)
    val entry = entries[Key(sessionId, utteranceId)]?.takeIf { !it.retired }
      ?: throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    if (!entry.file.isFile || entry.file.length() != entry.clip.byteLength) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    entry.leased = true
    leasedPaths += entry.file.canonicalPath
    entry.clip
  }

  fun release(sessionId: String, utteranceId: String) = synchronized(lock) {
    validate(sessionId, utteranceId)
    val key = Key(sessionId, utteranceId)
    val entry = entries[key] ?: return@synchronized
    entry.leased = false; entry.retired = true; leasedPaths -= entry.file.canonicalPath
    delete(key, entry)
  }

  fun stop(sessionId: String) = synchronized(lock) {
    if (!LiveCapturePolicy.validId(sessionId)) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    var failed = false
    entries.filterKeys { it.session == sessionId }.toList().forEach { (key, entry) ->
      entry.retired = true
      if (!entry.leased) try { delete(key, entry) } catch (_: UtteranceStoreException) { failed = true }
    }
    if (failed) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
  }

  fun cleanup(nowMillis: Long = System.currentTimeMillis()) = synchronized(lock) {
    var failed = false
    directory.listFiles()?.forEach { file ->
      if (file.extension == "wav" && file.canonicalPath !in leasedPaths && nowMillis - file.lastModified() >= 600_000) {
        if (!file.delete()) failed = true else entries.entries.removeIf { it.value.file.canonicalPath == file.canonicalPath }
      }
    }
    if (failed) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
  }

  private fun delete(key: Key, entry: Entry) {
    if (entry.file.exists() && !entry.file.delete()) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
    entries.remove(key)
  }
  private fun validate(session: String, utterance: String) {
    if (!LiveCapturePolicy.validId(session) || !LiveCapturePolicy.validId(utterance)) throw UtteranceStoreException(CaptureFailure.FILE_FAILED)
  }
  private fun wavHeader(sampleCount: Int): ByteArray = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
    put("RIFF".toByteArray()); putInt(36 + sampleCount * 2); put("WAVE".toByteArray())
    put("fmt ".toByteArray()); putInt(16); putShort(1); putShort(1); putInt(16_000); putInt(32_000); putShort(2); putShort(16)
    put("data".toByteArray()); putInt(sampleCount * 2)
  }.array()

  companion object { private val lock = Any(); private val leasedPaths = mutableSetOf<String>() }
}
