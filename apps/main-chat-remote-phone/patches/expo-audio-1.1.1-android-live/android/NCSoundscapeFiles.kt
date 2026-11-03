package expo.modules.audio

import java.io.File
import java.io.RandomAccessFile
import java.security.MessageDigest
import java.util.UUID

data class NCSoundscapeMedia(val sha256: String, val byteLength: Long)
data class NCSoundscapeDownload(val token: String, val ready: Boolean)
class ValidatedSoundFile internal constructor(val file: File, internal val pin: String)

/** Hashing/parts run on workers. Player admission takes only the metadata lock. */
class NCSoundscapeFiles(root: File, private val maxBytes: Long=250L*1024*1024) {
  private class Slot(val token: String, val target: File, val part: File, val media: NCSoundscapeMedia) {
    @Volatile var ready=false
    @Volatile var removed=false
    var received=0L
  }
  private val root=root.canonicalFile.also { it.mkdirs() }
  private val lock=Any()
  private val slots=mutableMapOf<String,Slot>()
  private val pins=mutableMapOf<String,File>()
  private var closed=false
  private var swept=false
  private fun digest(bytes: ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
  private fun checksum(file: File): String {
    val digest=MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
      val buffer=ByteArray(256*1024)
      while(true) { val n=input.read(buffer); if(n<0)break; digest.update(buffer,0,n) }
    }
    return digest.digest().joinToString(""){"%02x".format(it)}
  }
  private fun files(): List<File> = root.listFiles()?.filter { it.isDirectory && it.canonicalFile.parentFile==root }
    ?.flatMap { it.listFiles()?.filter { f -> f.isFile && f.name.matches(Regex("[0-9a-f]{64}\\.ogg")) && f.canonicalFile.parentFile==it } ?: emptyList() } ?: emptyList()

  // Called only on a worker, never by player admission.
  private fun reserve(bytes: Long) {
    val candidates=files().sortedBy { it.lastModified() }
    var used=candidates.sumOf { it.length() } + slots.values.filter { !it.ready }.sumOf { it.media.byteLength }
    var count=candidates.size
    val held=(slots.values.map { it.target }+pins.values).toSet()
    for(file in candidates) {
      if(used+bytes<=maxBytes && count<256) break
      if(file in held) continue
      val size=file.length()
      if(file.delete()) { used-=size; count-- }
    }
    require(used+bytes<=maxBytes && count<256) { "Sound cache is full with active sounds" }
  }
  fun begin(scope: String, media: NCSoundscapeMedia): NCSoundscapeDownload {
    require(scope.isNotBlank() && scope.length<=2048 && media.sha256.matches(Regex("[0-9a-f]{64}"))
      && media.byteLength in 1..(100L*1024*1024))
    val slot=synchronized(lock) {
      check(!closed); require(slots.size<16) { "Too many active sound transfers" }
      if(!swept) {
        // First worker request after module creation: only our private, canonical
        // scoped folders and UUID partials. No UI-thread I/O or external paths.
        root.listFiles()?.filter { it.isDirectory && it.name.matches(Regex("[0-9a-f]{64}")) && it.canonicalFile.parentFile==root }
          ?.forEach { folder -> folder.listFiles()?.filter { it.name.matches(Regex("[0-9a-f-]{36}\\.part")) && it.canonicalFile.parentFile==folder }
            ?.forEach { require(it.delete()) { "Could not clean interrupted sound download" } } }
        swept=true
      }
      val folder=File(root,digest(scope.toByteArray(Charsets.UTF_8)))
      folder.mkdirs(); require(folder.canonicalFile.parentFile==root && folder.canonicalFile==folder)
      val target=File(folder,media.sha256+".ogg")
      require(target.canonicalFile.parentFile==folder)
      if (!target.exists()) reserve(media.byteLength)
      val token=UUID.randomUUID().toString()
      Slot(token,target,File(folder,token+".part"),media).also { slots[token]=it }
    }
    synchronized(slot) {
      try {
        if(slot.target.isFile && slot.target.length()==media.byteLength && checksum(slot.target)==media.sha256) {
          synchronized(lock) { check(!slot.removed && !closed); slot.ready=true; slot.target.setLastModified(System.currentTimeMillis()) }
        } else {
          synchronized(lock) {
            require(slot.target !in pins.values) { "Active cached sound failed verification" }
            if (slot.target.exists()) { require(slot.target.delete()); reserve(0) }
          }
          check(slot.part.createNewFile())
        }
      } catch(error: Throwable) { forget(slot.token); throw error }
    }
    return NCSoundscapeDownload(slot.token,slot.ready)
  }
  fun write(token: String, offset: Long, bytes: ByteArray) {
    require(bytes.isNotEmpty() && bytes.size<=256*1024)
    val slot=synchronized(lock) { slots[token] ?: throw IllegalArgumentException("Unknown sound transfer") }
    synchronized(slot) {
      require(!slot.removed && !slot.ready && offset==slot.received && offset+bytes.size<=slot.media.byteLength)
      RandomAccessFile(slot.part,"rw").use { file ->
        file.seek(offset)
        try { file.write(bytes) } catch(error: Throwable) { file.setLength(offset); throw error }
      }
      slot.received+=bytes.size
    }
  }
  fun finish(token: String): Boolean {
    val slot=synchronized(lock) { slots[token] ?: throw IllegalArgumentException("Unknown sound transfer") }
    synchronized(slot) {
      if(slot.ready) return true
      if(slot.removed || slot.received!=slot.media.byteLength || checksum(slot.part)!=slot.media.sha256) {
        forget(token); return false
      }
      // Expensive verification stays outside the player-admission lock.
      if(slot.target.exists()) require(slot.target.length()==slot.media.byteLength && checksum(slot.target)==slot.media.sha256)
      synchronized(lock) {
        if(slot.removed || closed) return false
        if(slot.target.exists()) {
          // A concurrent identical download published first. Never replace a decoder's file.
          // A target appearing since verification was published by another
          // verified slot; published files are immutable while slots hold them.
          require(slot.target.length()==slot.media.byteLength)
          slot.part.delete()
        } else require(slot.part.renameTo(slot.target)) { "Could not publish cached sound" }
        slot.ready=true; slot.target.setLastModified(System.currentTimeMillis()); return true
      }
    }
  }
  fun acquire(token: String): ValidatedSoundFile = synchronized(lock) {
    val slot=slots[token]
    require(!closed && slot!=null && slot.ready && !slot.removed) { "Sound file is not verified" }
    val pin=UUID.randomUUID().toString(); pins[pin]=slot.target
    ValidatedSoundFile(slot.target,pin)
  }
  fun release(file: ValidatedSoundFile) = synchronized(lock) { pins.remove(file.pin); Unit }
  fun retain(file: ValidatedSoundFile): ValidatedSoundFile = synchronized(lock) {
    require(!closed && pins[file.pin]==file.file) { "Sound source is no longer pinned" }
    val pin=UUID.randomUUID().toString(); pins[pin]=file.file; ValidatedSoundFile(file.file,pin)
  }
  fun forget(token: String) {
    val slot=synchronized(lock) { slots.remove(token)?.also { it.removed=true } } ?: return
    synchronized(slot) { slot.part.delete() }
  }
  fun close() {
    val tokens=synchronized(lock) { closed=true; slots.keys.toList() }
    tokens.forEach { forget(it) }
  }
}
