// NeuralCompanion, MIT. ExpoAudio adapter, not a separate playback owner.
package expo.modules.audio

import java.lang.ref.WeakReference
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong
import android.os.Handler
import android.os.Looper
import android.media.MediaExtractor
import android.media.MediaFormat
import java.io.File
import java.net.URI
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.CompletableFuture

internal class NCAVBridge {
  internal class Entry {
    val bufferedVideo=mutableMapOf<String,Pair<Long,NCBufferedVideoSource>>() // main-thread only
    val bufferedClock = NCBufferedAudioClock { value ->
      if (ready()) idleView?.get()?.bufferedHeard(value)
    }
    val terminal = AtomicBoolean()
    private val bufferedVisible = AtomicBoolean()
    private val localShown = AtomicBoolean()
    val buffered: Boolean get() = true
    fun localVisualAllowed() = ready() && bufferedVisible.get()
    fun setLocalVisible(value: Boolean) { localShown.set(value) }
    fun localVisible() = localVisualAllowed() && localShown.get()
    fun presentBuffered(enabled: Boolean): Boolean {
      if (!buffered || !ready()) return false
      bufferedVisible.set(enabled)
      if (!enabled) setLocalVisible(false)
      return true
    }
    private val viewLock = Any()
    private var view: Any? = null
    var idleView: WeakReference<NCAVView>? = null
    val idleRevision = AtomicLong()
    @Volatile var idlePrepared: Triple<Long,String,String>? = null
    @Volatile var idlePreparedChunk: Triple<Long,String,String>? = null
    @Volatile var idlePosition: Map<String,Any>? = null
    @Volatile var handoffStatus: Map<String,Any>? = null
    private var idleDetached = CompletableFuture.completedFuture(true)
    private val openingRevision = AtomicLong()
    private var openingKey = 0L
    private var lastOpeningKey = 0L
    private var openingDetached = CompletableFuture.completedFuture(true)
    fun beginOpening(key: Long): Long = synchronized(viewLock) {
      if (!ready() || openingKey != 0L || key <= lastOpeningKey || !openingDetached.isDone || !openingDetached.getNow(false)) 0L
      else { openingKey = key; lastOpeningKey = key; openingRevision.incrementAndGet() }
    }
    fun openingCurrent(key: Long, revision: Long): Boolean = synchronized(viewLock) {
      ready() && openingKey == key && revision > 0 && openingRevision.get() == revision
    }
    fun clearOpeningReaders(key: Long? = null): CompletableFuture<Boolean>? = synchronized(viewLock) {
      if (key != null && key != lastOpeningKey) return@synchronized null
      openingKey = 0; openingRevision.incrementAndGet()
      val target = idleView?.get(); val cleared = CompletableFuture<Boolean>()
      openingDetached = openingDetached.thenCombine(cleared) { before, after -> before && after }
      Handler(Looper.getMainLooper()).post {
        if (target == null) cleared.complete(true) else target.clearOpeningDetached { cleared.complete(it) }
      }
      openingDetached
    }
    fun clearIdleReaders(): CompletableFuture<Boolean> = synchronized(viewLock) {
      val target = idleView?.get()
      val cleared = CompletableFuture<Boolean>()
      val previous = idleDetached
      idleDetached = previous.thenCombine(cleared) { before, after -> before && after }
      Handler(Looper.getMainLooper()).post {
        if (target == null) cleared.complete(true)
        else target.clearIdleDetached { cleared.complete(it) }
      }
      idleDetached
    }
    fun clearIdleChunkReaders(generation: String, media: String): CompletableFuture<Boolean> = synchronized(viewLock) {
      val target = idleView?.get()
      if (target == null) return@synchronized idleDetached
      val cleared = CompletableFuture<Boolean>()
      Handler(Looper.getMainLooper()).post {
        val prepared = idlePreparedChunk
        if (prepared?.second == generation && prepared.third == media) { idlePreparedChunk = null; idlePrepared = null }
        target.clearIdleChunksDetached(generation,media) { cleared.complete(it) }
      }
      cleared
    }
    fun ready() = !terminal.get()
    fun stop() {
      if (!terminal.compareAndSet(false, true)) return
      idleRevision.incrementAndGet(); idlePrepared = null; idlePreparedChunk = null
      bufferedVisible.set(false); localShown.set(false)
      Handler(Looper.getMainLooper()).post {
        bufferedClock.close();bufferedVideo.values.forEach { it.second.close() };bufferedVideo.clear()
      }
      clearIdleReaders()
      clearOpeningReaders()
      synchronized(viewLock) { view = null }
    }
    fun setView(token: NCAVView) = synchronized(viewLock) {
      if (!terminal.get()) { view = token; idleView = WeakReference(token) }
    }
    fun removeView(token: Any) = synchronized(viewLock) {
      if (view === token) { clearIdleReaders(); clearOpeningReaders(); idleRevision.incrementAndGet(); idlePrepared = null; idlePreparedChunk = null; view = null; idleView = null; setLocalVisible(false) }
    }
  }
  companion object {
    private val views = ConcurrentHashMap<String, WeakReference<Entry>>()
    fun viewEntry(handle: String) = views[handle]?.get()
  }
  private val lock = Any()
  private val entries = ConcurrentHashMap<String, Entry>()
  private val idleDetaches = ConcurrentHashMap<String, CompletableFuture<Boolean>>()
  private var destroyed = false

  fun ready(handle: String) = entries[handle]?.ready() == true
  fun openBuffered(): String? = synchronized(lock) {
    if (destroyed || entries.isNotEmpty()) return null
    val entry = Entry(); val handle = UUID.randomUUID().toString()
    entries[handle] = entry; views[handle] = WeakReference(entry)
    handle
  }
  fun presentBuffered(handle: String, enabled: Boolean) = entries[handle]?.presentBuffered(enabled) == true
  fun bindBufferedAudio(handle:String,value:Double,player:AudioPlayer,ticket:String,request:String,chunk:String,samples:Int):Boolean {
    if (Looper.myLooper()!=Looper.getMainLooper()) return false
    val key=key(value)?:return false
    val entry=entries[handle]?.takeIf { it.ready()&&it.buffered }?:return false
    return entry.bufferedClock.bind(key,player.ncPlaybackBinding,ticket,request,chunk,samples)
  }
  fun retireBufferedAudio(handle:String,value:Double) {
    val key=key(value)?:return
    val entry=entries[handle]?.takeIf { it.buffered }?:return
    Handler(Looper.getMainLooper()).post {
      entry.bufferedClock.remove(key)
      entry.bufferedVideo.filterValues { it.first==key }.keys.toList().forEach { entry.bufferedVideo.remove(it)?.second?.close() }
    }
  }
  fun bindBufferedVideo(handle:String,value:Double,player:expo.modules.video.player.VideoPlayer,
    uri:String,start:Int,frames:Int):String? {
    if(Looper.myLooper()!=Looper.getMainLooper() || !uri.startsWith("file://"))return null
    val key=key(value)?:return null
    val entry=entries[handle]?.takeIf { it.ready()&&it.buffered }?:return null
    if(entry.bufferedVideo.size>=8 || entry.bufferedClock.sample(key)?.stopped!=false
      || player.player.currentMediaItem?.localConfiguration?.uri?.toString()!=uri)return null
    val token=UUID.randomUUID().toString()
    val source=try { NCBufferedVideoSource(player.player,start,frames,com.oney.WebRTCModule.EglUtils.getRootEglBaseContext()) { tick,frame ->
      val state=entry.bufferedClock.sample(key)
      if(entry.ready()&&entry.localVisualAllowed()&&entry.bufferedVideo.containsKey(token)
        &&state?.started==true&&state.playing&&!state.stopped&&!state.completed)
        entry.idleView?.get()?.bufferedFrame(key,tick,frame)
    } } catch(_:RuntimeException) { return null }
    entry.bufferedVideo[token]=key to source;return token
  }
  fun retireBufferedVideo(handle:String,token:String) {
    check(Looper.myLooper()==Looper.getMainLooper())
    entries[handle]?.bufferedVideo?.remove(token)?.second?.close()
  }
  fun bufferedVideoReady(handle:String,token:String):Boolean {
    check(Looper.myLooper()==Looper.getMainLooper())
    return entries[handle]?.bufferedVideo?.get(token)?.second?.decoded==true
  }
  fun visible(handle: String): Boolean {
    val entry = entries[handle] ?: return false
    return entry.localVisible()
  }
  fun idleBegin(handle: String): Long = entries[handle]?.let {
    if (!it.ready()) 0L else { it.idlePrepared = null; it.idlePreparedChunk = null; it.idleRevision.incrementAndGet() }
  } ?: 0L
  fun idleClear(handle: String) {
    val entry = entries[handle] ?: return
    idleBegin(handle)
    entry.setLocalVisible(false)
    entry.clearIdleReaders()
  }
  fun idlePosition(handle: String): Map<String,Any>? {
    val entry = entries[handle]?.takeIf { it.ready() } ?: return null
    val value = entry.idlePosition ?: return null
    val observed = value["observedAtNs"] as? Long ?: return null
    if (observed <= 0) return null
    return value+mapOf("ageMs" to (System.nanoTime()-observed)/1_000_000.0)
  }
  fun idleDetachBegin(handle: String): String? = synchronized(lock) {
    val entry = entries[handle] ?: return null
    if (idleDetaches.size >= 32) return null
    idleBegin(handle); entry.setLocalVisible(false)
    val ticket = UUID.randomUUID().toString()
    idleDetaches[ticket] = entry.clearIdleReaders()
    ticket
  }
  fun idleDetachWait(ticket: String): Boolean {
    if (Looper.myLooper() == Looper.getMainLooper()) return false
    val fence = idleDetaches[ticket] ?: return false
    return try { fence.get(6,TimeUnit.SECONDS) } catch (_:Exception) { false }
      finally { idleDetaches.remove(ticket,fence) }
  }
  /** The caller revokes and joins its offered work before requesting this fence. */
  fun idleChunkDetachBegin(handle: String, generation: String, media: String): String? = synchronized(lock) {
    if (!generation.matches(Regex("[a-f0-9]{32}")) || !media.matches(Regex("[a-f0-9]{32}"))) return null
    val entry = entries[handle] ?: return null
    if (idleDetaches.size >= 32) return null
    val ticket = UUID.randomUUID().toString()
    idleDetaches[ticket] = entry.clearIdleChunkReaders(generation,media)
    ticket
  }
  fun openingBegin(handle: String, value: Double): Long {
    val key = key(value) ?: return 0L
    return entries[handle]?.beginOpening(key) ?: 0L
  }
  fun openingDetachBegin(handle: String, value: Double): String? = synchronized(lock) {
    val key = key(value) ?: return null
    val entry = entries[handle] ?: return null
    if (idleDetaches.size >= 32) return null
    val fence = entry.clearOpeningReaders(key) ?: return null
    val ticket = UUID.randomUUID().toString(); idleDetaches[ticket] = fence; ticket
  }
  fun openingPrepare(handle: String, value: Double, revision: Long, owner: String, media: String, uri: String, sourceCount: Int, indices: List<Int>): Boolean {
    if (Looper.myLooper() == Looper.getMainLooper()) return false
    val key = key(value) ?: return false
    val entry = entries[handle] ?: return false
    if (!entry.openingCurrent(key,revision) || indices.size !in 1..720 || sourceCount !in 1..1440 || indices.any { it !in 0 until sourceCount }) return false
    val file = try { File(URI(uri)) } catch (_:Exception) { return false }
    val gate = CountDownLatch(1); val accepted = AtomicBoolean(); val expired = AtomicBoolean()
    Handler(Looper.getMainLooper()).post {
      val view = entry.idleView?.get()
      if (!entry.openingCurrent(key,revision) || view == null || expired.get()) gate.countDown()
      else view.prepareOpening(owner,key,media,file,indices.toIntArray(),sourceCount) { ready ->
        accepted.set(ready && !expired.get() && entry.openingCurrent(key,revision)); gate.countDown()
      }
    }
    val finished = gate.await(8,TimeUnit.SECONDS); expired.set(!finished)
    if (!finished) entry.clearOpeningReaders(key)
    return finished && accepted.get() && entry.openingCurrent(key,revision)
  }
  private fun handoffWork(handle: String, value: Double, revision: Long,
    action: (NCAVView,(Double)->Unit)->Unit): Double {
    if (Looper.myLooper() == Looper.getMainLooper()) return 0.0
    val key = key(value) ?: return 0.0
    val entry = entries[handle] ?: return 0.0
    if (!entry.openingCurrent(key,revision)) return 0.0
    val gate = CountDownLatch(1); val expired = AtomicBoolean(); var result = 0.0
    Handler(Looper.getMainLooper()).post {
      val view = entry.idleView?.get()
      if (view == null || expired.get() || !entry.openingCurrent(key,revision)) gate.countDown()
      else action(view) { accepted ->
        if (!expired.get() && entry.openingCurrent(key,revision)) result = accepted
        gate.countDown()
      }
    }
    val finished = gate.await(8,TimeUnit.SECONDS); expired.set(!finished)
    if (!finished) entry.clearOpeningReaders(key)
    return if (finished && entry.openingCurrent(key,revision)) result else 0.0
  }
  fun handoffBegin(handle: String, value: Double, revision: Long, owner: String, plan: String, count: Int, indices: List<Int>): Boolean =
    handoffWork(handle,value,revision) { view,done ->
      done(if (view.beginHandoff(owner,value.toLong(),plan,count,indices.toIntArray())) 1.0 else 0.0)
    } == 1.0
  fun handoffAppend(handle: String, value: Double, revision: Long, index: Int, uri: String): Boolean {
    val file = try { File(URI(uri)) } catch (_:Exception) { return false }
    return handoffWork(handle,value,revision) { view,done ->
      view.appendHandoff(value.toLong(),index,file) { done(if (it) 1.0 else 0.0) }
    } == 1.0
  }
  fun handoffArm(handle: String, value: Double, revision: Long): Double =
    handoffWork(handle,value,revision) { view,done -> done(view.armHandoff(value.toLong())) }
  fun handoffNext(handle: String, value: Double, revision: Long, next: Double, count: Int, indices: List<Int>): Boolean {
    val nextKey = key(next) ?: return false
    return handoffWork(handle,value,revision) { view,done -> done(if (view.nextHandoff(nextKey,count,indices.toIntArray())) 1.0 else 0.0) } == 1.0
  }
  fun handoffStatus(handle: String): Map<String,Any>? = entries[handle]?.takeIf { it.ready() }?.handoffStatus
  fun bufferedSource(handle: String, value: Double, revision: Long, next: Double, data: Map<String,Any>): Boolean {
    val nextKey=key(next) ?: return false
    val source=NCBufferedVisualSource.parse(data) ?: return false
    if(entries[handle]?.buffered!=true)return false
    return handoffWork(handle,value,revision) { view,done -> view.bufferedSource(nextKey,source) { done(if(it)1.0 else 0.0) } }==1.0
  }
  fun idlePrepare(handle: String, file: Map<String, Any>, fade: Int, revision: Long, sourceTicks: Int = 0): Boolean {
    if (Looper.myLooper() == Looper.getMainLooper()) return false
    val entry = entries[handle] ?: return false
    if (!entry.ready() || revision <= 0 || entry.idleRevision.get() != revision) return false
    val generation = file["generation"] as? String ?: return false
    val id = file["id"] as? String ?: return false
    val source = File(URI(file["uri"] as? String ?: return false))
    val extractor = MediaExtractor()
    var sourceCount = 0
    try {
      extractor.setDataSource(source.absolutePath)
      if (extractor.trackCount != 1 || extractor.getTrackFormat(0).getString(MediaFormat.KEY_MIME) != "video/avc") return false
      val format = extractor.getTrackFormat(0)
      sourceCount = ((format.getLong(MediaFormat.KEY_DURATION)*24+500000)/1000000).toInt()
      if (sourceTicks != 0) {
        val fps = format.getInteger(MediaFormat.KEY_FRAME_RATE)
        if (sourceTicks !in 1..1440 || fps !in listOf(6,8,12,24)) return false
        val step = 24/fps
        if ((sourceTicks+step-1)/step != (sourceCount+step-1)/step) return false
        sourceCount = sourceTicks
      }
      if (sourceCount !in 1..1440) return false
    } finally { extractor.release() }
    val gate = CountDownLatch(1); val accepted = AtomicBoolean(); val expired = AtomicBoolean()
    Handler(Looper.getMainLooper()).post {
      val view = entry.idleView?.get()
      if (entry.terminal.get() || view == null || entry.idleRevision.get() != revision) gate.countDown()
      else view.prepareIdle(generation,id,source,fade,sourceCount) { ready ->
        val valid = ready && !expired.get() && !entry.terminal.get() && entry.idleRevision.get() == revision
        if (valid) entry.idlePrepared = Triple(revision,generation,id)
        accepted.set(valid); gate.countDown()
      }
    }
    val finished = gate.await(8,TimeUnit.SECONDS); expired.set(!finished)
    return finished && accepted.get()
  }
  fun idleSelect(handle: String, generation: String, id: String): Boolean {
    val entry = entries[handle] ?: return false
    return entry.ready() && entry.idlePrepared == Triple(entry.idleRevision.get(),generation,id) &&
      entry.idleView?.get()?.selectIdle(generation,id) == true
  }
  fun idleChunkPrepare(handle: String, revision: Long, data: Map<String,Any>): Boolean = idleChunkWork(handle,revision,data,true)
  fun idleChunkAppend(handle: String, revision: Long, data: Map<String,Any>): Boolean = idleChunkWork(handle,revision,data,false)
  fun idleChunkSelect(handle: String, revision: Long, generation: String, motion: String, media: String): Boolean {
    check(Looper.myLooper() == Looper.getMainLooper())
    val entry = entries[handle] ?: return false
    return entry.ready() && revision > 0 && entry.idleRevision.get() == revision
      && entry.idlePrepared == Triple(revision,generation,motion)
      && entry.idlePreparedChunk == Triple(revision,generation,media)
      && entry.idleView?.get()?.selectIdleChunks(generation,motion,media) == true
  }
  private fun idleChunkWork(handle: String, revision: Long, data: Map<String,Any>, prepare: Boolean): Boolean {
    // Only fixed local stage names, never descriptors, handles or exceptions.
    fun rejected(stage: String): Boolean {
      android.util.Log.w("NCIdleChunks",(if (prepare) "prepare_" else "append_")+stage)
      return false
    }
    if (Looper.myLooper() == Looper.getMainLooper()) return rejected("main_queue")
    val entry = entries[handle]?.takeIf { it.buffered && it.ready() && revision > 0 && it.idleRevision.get() == revision }
      ?: return rejected("entry_revision")
    val chunk = NCIdleChunkFile.parse(data) ?: return rejected("descriptor")
    if (prepare && chunk.index != 0) return rejected("prepare_index")
    val gate = CountDownLatch(1); val accepted = AtomicBoolean(); val expired = AtomicBoolean()
    var stage = "view_owner"
    Handler(Looper.getMainLooper()).post {
      val view = entry.idleView?.get()
      if (!entry.ready() || view == null || expired.get() || entry.idleRevision.get() != revision) gate.countDown()
      else {
        val done: (Boolean)->Unit = { ready ->
          val valid = ready && !expired.get() && entry.ready() && entry.idleRevision.get() == revision
          stage = if (!ready) "native_rejected" else "owner_changed"
          if (valid && prepare) {
            entry.idlePrepared = Triple(revision,chunk.generation,chunk.motion)
            entry.idlePreparedChunk = Triple(revision,chunk.generation,chunk.media)
          }
          accepted.set(valid); gate.countDown()
        }
        if (prepare) view.prepareIdleChunks(chunk,done) else view.appendIdleChunk(chunk,done)
      }
    }
    val finished = gate.await(8,TimeUnit.SECONDS); expired.set(!finished)
    return if (finished && accepted.get()) true else rejected(if (!finished) "timeout" else stage)
  }
  private fun key(value: Double): Long? = value.takeIf {
    it.isFinite() && it in 1.0..2147483647.0 && it == kotlin.math.floor(it)
  }?.toLong()
  fun close(handle: String) = synchronized(lock) {
    val entry = entries.remove(handle) ?: return
    views.remove(handle)
    entry.stop() // Fence now; worker joins/resource destruction are asynchronous.
  }
  fun destroy() = synchronized(lock) {
    if (destroyed) return
    destroyed = true
    entries.keys.toList().forEach { close(it) }
  }
}
