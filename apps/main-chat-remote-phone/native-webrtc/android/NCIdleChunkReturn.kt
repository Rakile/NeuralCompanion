package expo.modules.audio

/** Exact six-file visual return description. No audio or receipt authority. */
internal object NCIdleChunkReturn {
  fun parse(value: Map<String,Any>): List<NCIdleChunkFile>? {
    fun integer(name: String): Int? = (value[name] as? Number)?.toDouble()?.takeIf {
      it.isFinite() && it==kotlin.math.floor(it) && it in 0.0..2147483647.0
    }?.toInt()
    val generation=value["idleGeneration"] as? String ?: return null
    val motion=value["motionId"] as? String ?: return null
    val count=integer("sourceFrameCount") ?: return null
    val start=integer("startFrame") ?: return null
    val fade=integer("fadeMs") ?: return null
    val timeline=value["sourceIndices"] as? List<*> ?: return null
    if (!generation.matches(Regex("[a-f0-9]{32}")) || !motion.matches(Regex("[a-f0-9]{64}"))
      || value["idleId"]!=motion || count !in 1..1440 || start !in 0 until count || fade !in 0..5000
      || timeline.size !in 1..720) return null
    val indices=timeline.map { row -> (row as? Number)?.toDouble()?.takeIf {
      it.isFinite() && it==kotlin.math.floor(it) && it>=0 && it<count
    }?.toInt() ?: return null }
    if (start!=(indices.last()+1)%count) return null
    val chunked=value["idleChunks"] as? Map<*,*> ?: return null
    if (chunked.keys!=setOf("mediaId","files")) return null
    val media=chunked["mediaId"] as? String ?: return null
    val rows=chunked["files"] as? List<*> ?: return null
    if (!media.matches(Regex("[a-f0-9]{32}")) || rows.size!=6) return null
    val files=rows.mapIndexed { index,row ->
      if (row !is Map<*,*> || row.keys.any { it !is String }) return null
      @Suppress("UNCHECKED_CAST")
      val file=NCIdleChunkFile.parse(row as Map<String,Any>) ?: return null
      if (file.generation!=generation || file.motion!=motion || file.media!=media || file.sourceCount!=count
        || file.start!=start || file.fade!=fade || file.index!=index) return null
      file
    }
    val first=try { java.io.File(java.net.URI(value["idleUri"] as? String ?: return null)) } catch (_:Exception) { return null }
    if (files.first().file!=first || value["idleSha"]!=files.first().sha || files.map { it.file }.distinct().size!=6) return null
    return files
  }
}
