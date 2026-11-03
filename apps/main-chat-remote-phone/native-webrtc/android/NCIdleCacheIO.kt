package expo.modules.audio

import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.Executors

/** App-private disposable video bytes, never an audio/presentation capability.
 * All disk/hashing work runs on this single IO worker, not the UI/audio thread.
 */
internal class NCIdleCacheIO(directory: File) {
  private val root = directory.canonicalFile
  private val executor = Executors.newSingleThreadExecutor { task -> Thread(task, "nc-idle-cache-io").apply { isDaemon = true } }
  private var closed = false
  private var owner = ""
  private var generation = ""
  private val hex = Regex("[a-f0-9]{64}")
  private val owned = Regex("(?:[a-f0-9]{64}\\.(?:mp4|meta)|[a-f0-9-]{36}\\.part|\\.owner|\\.meta-part)")
  private val limit = 128L * 1024 * 1024
  private data class Write(val generation: String, val id: String, val size: Long, val sha: String,
                           val file: File, val output: FileOutputStream, val digest: MessageDigest, var offset: Long = 0)
  private val writes = mutableMapOf<String, Write>()

  private fun <T> io(action: () -> T): T = executor.submit<T> { check(!closed) { "Idle cache closed" }; action() }.get()
  private fun file(name: String): File {
    require(owned.matches(name)) { "Invalid idle file" }
    val result = File(root, name)
    require(result.canonicalFile == result.absoluteFile && result.parentFile == root) { "Unsafe idle file" }
    return result
  }
  private fun hash(data: ByteArray) = MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it) }
  private fun live(value: String) { require(value.isNotEmpty() && value == generation) { "Idle generation ended" } }
  private fun entries() = root.listFiles()?.filter { owned.matches(it.name) } ?: emptyList()
  private fun abortAll() { writes.values.forEach { it.output.close(); it.file.delete() }; writes.clear() }
  private fun purge() {
    abortAll()
    entries().forEach {
      val target = file(it.name)
      require(target.isFile && target.delete()) { "Idle cache removal failed" }
    }
  }
  private fun used() = entries().filter { it.name.endsWith(".mp4") || it.name.endsWith(".part") }.sumOf { file(it.name).length() }
  private fun ensureRoot() {
    require(root.canonicalFile == root) { "Unsafe idle directory" }
    check(root.mkdirs() || root.isDirectory) { "Idle storage unavailable" }
  }

  fun select(scope: String, avatar: String): String = io {
    require(scope.isNotEmpty() && scope.length <= 1024 && hex.matches(avatar)) { "Invalid idle scope" }
    ensureRoot()
    val key = hash((scope + "\u0000" + avatar).toByteArray(Charsets.UTF_8))
    if (owner != key) {
      abortAll()
      val previous = file(".owner").let { if (it.isFile && it.length() == 64L) it.readText() else "" }
      if (previous != key) purge()
      // An interrupted process never leaves playable partial files.
      entries().filter { it.name.endsWith(".part") || it.name == ".meta-part" }.forEach { file(it.name).delete() }
      file(".owner").writeText(key)
      owner = key; generation = UUID.randomUUID().toString()
    }
    generation
  }

  fun begin(value: String, id: String, bytes: Long, sha256: String): String = io {
    live(value)
    ensureRoot()
    if (!file(".owner").exists()) file(".owner").writeText(owner)
    require(hex.matches(id) && hex.matches(sha256) && bytes in 1..(16L*1024*1024)) { "Invalid idle entry" }
    require(writes.isEmpty()) { "Idle writer busy" }
    require(used()+bytes <= limit) { "Idle storage limited" }
    require(!file("$id.mp4").exists()) { "Idle entry exists" }
    val handle = UUID.randomUUID().toString()
    val temporary = file("$handle.part")
    writes[handle] = Write(value,id,bytes,sha256,temporary,FileOutputStream(temporary),MessageDigest.getInstance("SHA-256"))
    handle
  }

  fun append(handle: String, offset: Long, bytes: ByteArray) = io {
    val write = requireNotNull(writes[handle]) { "Idle write ended" }; live(write.generation)
    require(bytes.size in 1..262144 && offset == write.offset && offset+bytes.size <= write.size) { "Invalid idle chunk" }
    write.output.write(bytes); write.digest.update(bytes); write.offset += bytes.size
  }

  private fun result(value: String, id: String, bytes: Long, sha: String): Map<String, Any> =
    mapOf("generation" to value, "id" to id, "bytes" to bytes, "sha256" to sha, "uri" to file("$id.mp4").toURI().toString())

  fun finish(handle: String): Map<String, Any> = io {
    val write = requireNotNull(writes.remove(handle)) { "Idle write ended" }
    try {
      live(write.generation)
      write.output.fd.sync(); write.output.close()
      val sha = write.digest.digest().joinToString("") { "%02x".format(it) }
      require(write.offset == write.size && sha == write.sha && used() <= limit) { "Idle integrity failure" }
      val target = file("${write.id}.mp4")
      require(!target.exists() && write.file.renameTo(target)) { "Idle finalize failed" }
      try {
        val meta = file(".meta-part"); meta.writeText("$sha\n${write.size}")
        check(meta.renameTo(file("${write.id}.meta")))
      } catch (error: Exception) { target.delete(); throw error }
      result(generation,write.id,write.size,sha)
    } finally { write.output.close(); write.file.delete() }
  }

  fun get(value: String, id: String): Map<String, Any>? = io {
    live(value); require(hex.matches(id)) { "Invalid idle id" }
    val target = file("$id.mp4"); val meta = file("$id.meta")
    try {
      require(meta.isFile && meta.length() <= 100)
      val parts = meta.readLines(); require(parts.size == 2 && hex.matches(parts[0]))
      val size = parts[1].toLong(); require(size in 1..16L*1024*1024 && target.isFile && target.length() == size)
      val digest = MessageDigest.getInstance("SHA-256")
      target.inputStream().use { input ->
        val buffer = ByteArray(24576)
        while (true) { val count = input.read(buffer); if (count < 0) break; digest.update(buffer,0,count) }
      }
      require(digest.digest().joinToString("") { "%02x".format(it) } == parts[0])
      result(value,id,size,parts[0])
    } catch (_: Exception) { target.delete(); meta.delete(); null }
  }

  fun abort(handle: String) = io { writes.remove(handle)?.let { it.output.close(); it.file.delete() }; Unit }
  fun invalidate(value: String) = io { live(value); purge(); generation = ""; owner = "" }
  fun usage(): Map<String, Any> = io { mapOf("bytes" to used(), "limit" to limit) }
  fun close() { io { abortAll(); closed = true }; executor.shutdown() }
}
