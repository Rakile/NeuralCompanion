package expo.modules.audio

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.net.URI
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.ExecutionException

/** Byte custody only. A pin is NOT an output grant or a native reader receipt.
 * All filesystem/hash work is serialized off the playback/UI thread. Clear's
 * epoch announcement is immediate so an in-flight copy cannot resurrect it.
 */
internal class NCOrderedIdleCache(directory:File, sourceDirectory:File,
    private val maxBytes:Long=128L*1024*1024, private val maxEntries:Int=1024) {
  private val root=directory.canonicalFile
  private val sources=sourceDirectory.canonicalFile
  private val executor=Executors.newSingleThreadExecutor { r -> Thread(r,"nc-ordered-idle-io").apply{isDaemon=true} }
  private val epochs=ConcurrentHashMap<String,Long>()
  private val clears=ConcurrentHashMap<String,Long>()
  private val hex=Regex("[a-f0-9]{64}")
  private val mediaName=Regex("([a-f0-9]{64})\\.([0-9]{1,16})\\.([a-f0-9]{64})\\.([a-f0-9]{32})\\.mp4")
  private val markerName=Regex("[a-f0-9]{64}\\.epoch")
  private val partialName=Regex("[a-f0-9]{32}\\.part")
  private data class Entry(val file:File,val scope:String,val epoch:Long,val digest:String,
    var pins:Int=0,var retired:Boolean=false)
  private val entries=mutableMapOf<String,Entry>()
  private val pins=mutableMapOf<String,Entry>()
  private var loaded=false
  private var closed=false
  private var lastReason="miss"

  init {
    require(maxBytes in 1..128L*1024*1024 && maxEntries in 1..1024){"ordered_idle_cache_limits"}
    require(root.path.startsWith(sources.path+File.separator)){"ordered_idle_cache_root"}
  }
  private fun <T> io(work:()->T):T=try {
    executor.submit<T>{check(!closed){"ordered_idle_cache_closed"};work()}.get()
  }catch(error:ExecutionException){
    val cause=error.cause?:error
    if(cause is IOException)throw IllegalStateException("ordered_idle_cache_storage",cause)
    throw cause
  }
  private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it)}
  private fun scope(value:String):String {
    require(value.isNotEmpty()&&value.length<=1024){"ordered_idle_cache_scope"}
    return hash(value.toByteArray(Charsets.UTF_8))
  }
  private fun epochValue(value:Long){require(value in 0..9007199254740991L){"ordered_idle_cache_epoch"}}
  private fun validate(digest:String,bytes:Long){require(hex.matches(digest)&&bytes in 1..16L*1024*1024){"ordered_idle_cache_descriptor"}}
  private fun file(name:String):File {
    require(mediaName.matches(name)||markerName.matches(name)||partialName.matches(name)
      ||name.endsWith(".retired")&&mediaName.matches(name.removeSuffix(".retired"))){"ordered_idle_cache_path"}
    val result=File(root,name)
    require(root==root.canonicalFile&&result==result.canonicalFile){"ordered_idle_cache_path"}
    return result
  }
  private fun ensureLoaded(){
    check(root.mkdirs()||root.isDirectory){"ordered_idle_cache_storage"}
    if(loaded)return
    for(child in root.listFiles().orEmpty()){
      val match=mediaName.matchEntire(child.name)
      if(match!=null){
        val path=file(child.name)
        val retired=file(child.name+".retired")
        if(retired.exists()){
          check(retired.isFile&&(!path.exists()||path.isFile&&path.delete())&&retired.delete()){"ordered_idle_cache_cleanup"}
          continue
        }
        if(path.isFile){
          val epoch=match.groupValues[2].toLong()
          if(epoch in 0..9007199254740991L)entries[child.name]=Entry(path,match.groupValues[1],epoch,match.groupValues[3])
        }
      }else if(partialName.matches(child.name)){
        val path=file(child.name);check(path.isFile&&path.delete()){"ordered_idle_cache_partial_cleanup"}
      }else if(child.name.endsWith(".retired")&&mediaName.matches(child.name.removeSuffix(".retired"))){
        val marker=file(child.name)
        if(!file(child.name.removeSuffix(".retired")).exists())
          check(!marker.exists()||marker.isFile&&marker.delete()){"ordered_idle_cache_cleanup"}
      }
    }
    loaded=true
  }
  private fun atomicMarker(key:String,value:Long){
    val temporary=file(UUID.randomUUID().toString().replace("-","")+".part")
    try{
      temporary.writeText(value.toString(),Charsets.US_ASCII)
      val marker=file("$key.epoch")
      if(!temporary.renameTo(marker)){
        // Some JVM filesystems cannot replace a target with renameTo. A missing
        // marker conservatively retires old assets on reopen; it cannot revive
        // them. Media publication itself always renames to a new unique name.
        check(!marker.exists()||marker.isFile&&marker.delete()){"ordered_idle_cache_finalize"}
        check(temporary.renameTo(marker)){"ordered_idle_cache_finalize"}
      }
    }finally{temporary.delete()}
  }
  private fun currentEpoch(key:String,requested:Long):Long {
    ensureLoaded()
    val marker=file("$key.epoch")
    val saved=if(marker.isFile&&marker.length()<=16)marker.readText(Charsets.US_ASCII).toLongOrNull() else null
    val validSaved=saved?.takeIf{it in 0..9007199254740991L}
    if(validSaved==null&&!marker.exists()){
      // Bound scope metadata as well as video files. Optional cache rejection is
      // handled by the caller using its already available ordinary media path.
      check(root.listFiles().orEmpty().count{markerName.matches(it.name)}<64){"ordered_idle_cache_scope_capacity"}
    }
    val effective=epochs.compute(key){_,prior->maxOf(prior?:0,validSaved?:requested,requested)}!!
    if(validSaved==null){
      // No trustworthy persisted epoch: never revive unidentified prior files.
      entries.values.filter{it.scope==key}.toList().forEach{retire(it)}
    }
    if(validSaved!=effective)atomicMarker(key,effective)
    entries.values.filter{it.scope==key&&it.epoch<effective}.toList().forEach{retire(it)}
    return effective
  }
  private fun retire(entry:Entry){
    val marker=file(entry.file.name+".retired")
    // Keep a reader's pathname intact, but never revive a cleared pinned object
    // after process death. A new instance has no surviving reader pins.
    if(entry.pins>0&&!marker.exists())FileOutputStream(marker).use{it.fd.sync()}
    entry.retired=true
    if(entry.pins==0){
      check(!entry.file.exists()||entry.file.isFile&&entry.file.delete()){"ordered_idle_cache_cleanup"}
      check(!marker.exists()||marker.isFile&&marker.delete()){"ordered_idle_cache_cleanup"}
      entries.remove(entry.file.name)
    }
  }
  private fun used():Long=root.listFiles().orEmpty().filter{
    mediaName.matches(it.name)||partialName.matches(it.name)
  }.sumOf{file(it.name).length()}
  private fun matches(entry:Entry,bytes:Long):Boolean {
    if(!entry.file.isFile||entry.file.length()!=bytes)return false
    val digest=MessageDigest.getInstance("SHA-256");var size=0L
    entry.file.inputStream().use { input ->
      val buffer=ByteArray(24576)
      while(true){val n=input.read(buffer);if(n<0)break;size+=n;if(size>bytes)return false;digest.update(buffer,0,n)}
    }
    return size==bytes&&digest.digest().joinToString(""){"%02x".format(it)}==entry.digest
  }
  fun acquire(scope:String,digest:String,bytes:Long,epoch:Long):Map<String,Any>? {
    val key=scope(scope);validate(digest,bytes);epochValue(epoch)
    val clear=clears[key]?:0
    return io {
      if((clears[key]?:0)!=clear){lastReason="cleared";return@io null}
      if(currentEpoch(key,epoch)!=epoch){lastReason="epoch_changed";return@io null}
      val entry=entries.values.firstOrNull{!it.retired&&it.scope==key&&it.epoch==epoch&&it.digest==digest}
      if(entry==null){lastReason="miss";return@io null}
      if(!matches(entry,bytes)){retire(entry);lastReason="corrupt";return@io null}
      if(epochs[key]!=epoch||(clears[key]?:0)!=clear){lastReason="epoch_changed";return@io null}
      if(pins.size>=64){lastReason="pin_capacity";return@io null}
      val pin=UUID.randomUUID().toString();entry.pins++;pins[pin]=entry
      entry.file.setLastModified(System.currentTimeMillis());lastReason="hit"
      mapOf("pin" to pin,"uri" to entry.file.toURI().toString(),"bytes" to bytes)
    }
  }
  fun importFile(scope:String,digest:String,bytes:Long,epoch:Long,uri:String):Boolean {
    val key=scope(scope);validate(digest,bytes);epochValue(epoch)
    val clear=clears[key]?:0
    val parsed=URI(uri);require(parsed.scheme=="file"&&parsed.query==null&&parsed.fragment==null){"ordered_idle_cache_source"}
    val source=File(parsed).absoluteFile
    val canonical=source.canonicalFile
    require((source==canonical||NCIdleChunkFile.confined(sources,source))&&canonical.path.startsWith(sources.path+File.separator)
      &&!canonical.path.startsWith(root.path+File.separator)){"ordered_idle_cache_source"}
    return io {
      if((clears[key]?:0)!=clear){lastReason="cleared";return@io false}
      if(currentEpoch(key,epoch)!=epoch){lastReason="epoch_changed";return@io false}
      require(canonical==source.canonicalFile&&source.isFile&&source.length()==bytes){"ordered_idle_cache_source"}
      val existing=entries.values.firstOrNull{!it.retired&&it.scope==key&&it.epoch==epoch&&it.digest==digest}
      if(existing!=null){
        if(matches(existing,bytes)){lastReason="already_stored";return@io true}
        retire(existing)
      }
      if(bytes>maxBytes){lastReason="capacity";return@io false}
      while(used()+bytes>maxBytes||entries.size>=maxEntries){
        val victim=entries.values.filter{it.pins==0}.minByOrNull{it.file.lastModified()}
        if(victim==null){lastReason="capacity";return@io false}
        retire(victim)
      }
      val temporary=file(UUID.randomUUID().toString().replace("-","")+".part")
      try{
        val hash=MessageDigest.getInstance("SHA-256");var count=0L
        source.inputStream().use{input->FileOutputStream(temporary).use{output->
          val buffer=ByteArray(24576)
          while(true){
            if(epochs[key]!=epoch||(clears[key]?:0)!=clear){lastReason="epoch_changed";return@io false}
            val n=input.read(buffer);if(n<0)break;count+=n
            require(count<=bytes){"ordered_idle_cache_source_changed"}
            hash.update(buffer,0,n);output.write(buffer,0,n)
          }
          output.fd.sync()
        }}
        require(count==bytes&&source.length()==bytes&&hash.digest().joinToString(""){"%02x".format(it)}==digest){"ordered_idle_cache_integrity"}
        if(epochs[key]!=epoch||(clears[key]?:0)!=clear){lastReason="epoch_changed";return@io false}
        val target=file("$key.$epoch.$digest.${UUID.randomUUID().toString().replace("-","")}.mp4")
        check(temporary.renameTo(target)){"ordered_idle_cache_finalize"}
        entries[target.name]=Entry(target,key,epoch,digest);lastReason="stored";true
      }finally{temporary.delete()}
    }
  }
  fun release(pin:String)=io {
    val entry=pins.remove(pin)
    if(entry!=null){entry.pins--;if(entry.retired&&entry.pins==0)retire(entry)}
    Unit
  }
  fun clear(scope:String,epoch:Long,force:Boolean=false){
    val key=scope(scope);epochValue(epoch)
    if(force)clears.compute(key){_,old->(old?:0)+1}
    epochs.compute(key){_,old->maxOf(old?:0,epoch)} // Cancel copy before waiting for the IO queue.
    io { currentEpoch(key,epoch);if(force)entries.values.filter{it.scope==key}.toList().forEach{retire(it)};lastReason="cleared" }
  }
  fun usage():Map<String,Any> = io {
    ensureLoaded();mapOf("bytes" to used(),"limit" to maxBytes,"files" to entries.size,
      "pins" to pins.size,"reason" to lastReason)
  }
  fun close(){io { closed=true };executor.shutdown()} // Never unlink files under surviving readers.
}
