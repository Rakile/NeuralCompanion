package expo.modules.audio

import java.io.File
import java.net.URI

internal data class NCIdleChunkFile(val generation: String, val motion: String, val media: String,
  val file: File, val sha: String, val sourceCount: Int, val start: Int, val index: Int,
  val sequence: IntArray, val fade: Int) {
  companion object {
    internal fun androidCacheAlias(canonical: String, lexical: String): Boolean {
      val primary = Regex("^/data/user/0/([A-Za-z0-9_.]+)/cache$")
      val legacy = Regex("^/data/data/([A-Za-z0-9_.]+)/cache$")
      val first = primary.matchEntire(canonical)?.groupValues?.get(1)
      val second = legacy.matchEntire(canonical)?.groupValues?.get(1)
      return (first != null && legacy.matchEntire(lexical)?.groupValues?.get(1) == first)
        || (second != null && primary.matchEntire(lexical)?.groupValues?.get(1) == second)
    }
    /** Only existing canonical app-private families. Android's exact primary
     * private-cache root alias is permitted; unrelated lexical aliases, nested
     * directories, different basenames and symlink escapes remain rejected. */
    fun confined(root: File, file: File): Boolean = try {
      val cache=root.canonicalFile;val local=file.canonicalFile;val absolute=file.absoluteFile
      val relay=local.parentFile==File(cache,"nc-relay") && local.name.matches(Regex("[0-9]+-[0-9]+\\.mp4"))
      val reusable=local.parentFile==File(cache,"nc-ordered-idle-v1")
        &&local.name.matches(Regex("[a-f0-9]{64}\\.[0-9]{1,16}\\.[a-f0-9]{64}\\.[a-f0-9]{32}\\.mp4"))
      val temporary=local.parentFile==cache && local.name.matches(Regex("nc_musetalk_idle_[A-Za-z0-9_.-]+\\.mp4"))
      val family=if(reusable)"nc-ordered-idle-v1" else "nc-relay"
      val lexicalCache=if(relay||reusable) absolute.parentFile?.takeIf { it.name==family }?.parentFile else absolute.parentFile
      (relay || reusable || temporary) && (local==absolute || (absolute.name==local.name && lexicalCache!=null
        && androidCacheAlias(cache.path,lexicalCache.path)))
    } catch (_:Exception) { false }
    fun parse(value: Map<String,Any>): NCIdleChunkFile? {
      fun integer(name: String): Int? = (value[name] as? Number)?.toDouble()?.takeIf {
        it.isFinite() && it == kotlin.math.floor(it) && it in 0.0..2147483647.0
      }?.toInt()
      val generation = value["generation"] as? String ?: return null
      val motion = value["motionId"] as? String ?: return null
      val media = value["mediaId"] as? String ?: return null
      val sha = value["sha256"] as? String ?: return null
      val count = integer("sourceFrameCount") ?: return null
      val start = integer("startFrame") ?: return null
      val index = integer("index") ?: return null
      val fade = integer("fadeMs") ?: return null
      if (!generation.matches(Regex("[a-f0-9]{32}")) || !media.matches(Regex("[a-f0-9]{32}"))
        || !motion.matches(Regex("[a-f0-9]{64}")) || !sha.matches(Regex("[a-f0-9]{64}"))
        || count !in 1..1440 || start !in 0 until count || index !in 0..10005 || fade !in 0..5000) return null
      val rows = value["sourceIndices"] as? List<*> ?: return null
      if (rows.size != 12) return null
      val sequence = rows.map { row -> (row as? Number)?.toDouble()?.takeIf {
        it.isFinite() && it == kotlin.math.floor(it) && it >= 0 && it < count
      }?.toInt() ?: return null }.toIntArray()
      if (sequence.indices.any { sequence[it] != (start+index*12+it)%count }) return null
      val file = try { File(URI(value["uri"] as? String ?: return null)) } catch (_:Exception) { return null }
      return NCIdleChunkFile(generation,motion,media,file,sha,count,start,index,sequence,fade)
    }
  }
}
