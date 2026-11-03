package expo.modules.audio

import android.content.Context
import android.content.pm.ApplicationInfo
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.Looper
import android.os.Handler
import androidx.media3.common.MediaItem
import androidx.media3.common.Timeline
import androidx.media3.exoplayer.analytics.AnalyticsListener
import androidx.media3.datasource.DefaultDataSource
import androidx.media3.exoplayer.source.ConcatenatingMediaSource
import androidx.media3.exoplayer.source.ClippingMediaSource
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import java.io.File
import java.net.URI
import java.util.UUID

/** Global stream descriptors are checked before the existing Android extractor
 * validates the actual local files. Only the final declared range may be short.
 */
internal object NCMuxedTrialStreamRanges {
  data class Plan(val frames:Int,val samples:Long) {
    val totalRanges=(frames+11)/12
    init {require(frames in 1..720 && samples in 1..1441999
      && kotlin.math.abs(samples-frames*2000L)<2000 && totalRanges in 1..60)}
  }
  data class Batch(val rows:List<Map<String,Any>>,val frames:Int,val samples:Long,val totalRanges:Int)
  fun stagePrefix(values:List<Map<String,Any>>,plan:Plan):Batch {
    require(values.size>=minOf(2,plan.totalRanges))
    return normalize(values,0,plan)
  }
  fun normalize(values:List<Map<String,Any>>,first:Int,plan:Plan):Batch {
    require(values.size in 1..6 && first in 0 until plan.totalRanges
      && first+values.size<=plan.totalRanges)
    fun integer(row:Map<String,Any>,key:String):Long {
      val n=(row[key] as? Number)?.toDouble()?:throw IllegalArgumentException("Invalid muxed integer")
      require(n.isFinite()&&n==kotlin.math.floor(n)&&n in 0.0..2147483647.0)
      return n.toLong()
    }
    var frames=0
    var samples=0L
    val local=values.mapIndexed { offset,row ->
      val global=first+offset
      val count=minOf(12,plan.frames-global*12)
      val valid=if(global==plan.totalRanges-1)plan.samples-global*24000L else 24000L
      require(integer(row,"index")==global.toLong()
        &&integer(row,"startFrame")==global*12L
        &&integer(row,"frameCount")==count.toLong()
        &&integer(row,"validSamples")==valid
        &&integer(row,"sampleRate")==48000L &&integer(row,"fps")==24L)
      frames+=count;samples+=valid
      row+mapOf("index" to offset,"startFrame" to frames-count)
    }
    return Batch(local,frames,samples,plan.totalRanges)
  }
}

/** Development-only complete-TTS playlist on the registered audio owner.
 * It owns neither another ExoPlayer nor focus. Caller retains every file until
 * close has detached the source, and uses the existing AudioPlayer.play API.
 */
@androidx.annotation.OptIn(androidx.media3.common.util.UnstableApi::class)
internal class NCMuxedTrialPlayer private constructor(
  private val player:AudioPlayer, private val clips:MutableList<Clip>,
  private val source:ConcatenatingMediaSource, private val prefix:String,
  private val readerFence:NCMuxedTrialReaderFence,
  private val childFences:MutableList<NCMuxedTrialReaderFence.Child>,
  private val idle:NCMuxedTrialIdleWindow?=null,
  private val stream:NCMuxedTrialStreamRanges.Plan?=null,
  private val ticket:String?=null,private val request:String?=null,private val chunk:String?=null
) {
  private var closed=false
  private var sealed=false
  private var joinPrefix:String?=null
  private var joinStart=0
  private val sourceRevision=player.ncMuxedTrialRevision
  private var installedRanges=clips.size
  private var installedBytes=clips.sumOf {it.bytes}
  private var appendPending=false
  private var continuationPending=false
  private fun mediaSources(context:Context,clips:List<Clip>,first:Int,prefix:String)=
    mediaSources(context,clips,first,prefix,readerFence,childFences)
  internal val streamPlan get()=stream
  val durationSeconds get()=(stream?.samples?:clips.sumOf { it.samples.toLong() })/48000.0
  internal data class Trim(val delay:Int,val padding:Int,val raw:Int)
  internal data class Clip(val file:File,val bytes:Long,val samples:Int,val frames:Int,val startSamples:Long,
    val validatedTrim:Trim?=null)
  internal data class Prepared(val clips:List<Clip>,val ticket:String,val request:String,val chunk:String,
    val stream:NCMuxedTrialStreamRanges.Plan?=null)
  private fun index(item:String)=joinPrefix?.let {NCMuxedTrialItems.index(item,it,joinStart,
    clips.size-joinStart+(idle?.first?:0))}?:NCMuxedTrialItems.index(item,prefix,idle?.first?:0,clips.size)
  // Pure identity decoding for diagnostic snapshots; does not grant playback authority.
  internal fun diagnosticChunkIndex(mediaId:String?):Int?=mediaId?.let {index(it)}
  val acceptsDrain get()=!closed&&!continuationPending&&idle==null&&(stream==null||installedRanges==stream.totalRanges&&!appendPending)
    &&player.ref.currentMediaItem?.mediaId?.let {index(it)}==clips.lastIndex
  val waitingForStream get()=!closed&&(continuationPending||(stream!=null
    &&player.ref.playbackState==androidx.media3.common.Player.STATE_ENDED
    &&player.ncMuxedTrialReceipt?.observe()!=null
    &&player.ref.currentMediaItem?.mediaId?.let {index(it)}?.let {it in 0 until stream.totalRanges-1}==true))
  val silentEnded get()=!closed&&idle!=null&&sealed&&player.ref.playbackState==androidx.media3.common.Player.STATE_ENDED
    &&!player.ref.isPlaying&&player.ref.currentMediaItem?.mediaId=="$joinPrefix-${idle.first+clips.lastIndex}"
  fun ownsEvent(event:AnalyticsListener.EventTime):Boolean = try {
    !closed&&index(event.timeline.getWindow(event.windowIndex,Timeline.Window()).mediaItem.mediaId)!=null
  }catch(_:RuntimeException){false}

  fun positionSeconds():Double? {
    if(closed || Looper.myLooper()!=player.ref.applicationLooper)return null
    val item=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return null
    val clip=clips.getOrNull(item-(idle?.first?:0))?:return null
    return (clip.startSamples+(player.ref.currentPosition*48).coerceIn(0,clip.samples.toLong()))/48000.0
  }
  fun idlePosition():Map<String,Any>? {
    if(closed||idle==null||Looper.myLooper()!=player.ref.applicationLooper)return null
    val index=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return null
    if(index !in idle.first until idle.first+idle.size)return null
    return mapOf("index" to index,"seconds" to player.ref.currentPosition.coerceIn(0,500)/1000.0)
  }
  /** A temporary empty tail is not a sealed desktop boundary. Media3 retains
   * ENDED after later source extension; recover its exact current cursor,
   * without selecting a new avatar frame or resetting to a clip's start. */
  internal fun resumeIdle():Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    if(closed||sealed||idle==null||player.ncMuxedTrialOwner!==this||player.ncMuxedTrialRetired
      ||player.ncMuxedTrialRevision!=sourceRevision||!player.ncMuxedTrialSessionEnabled||player.ncMuxedTrialReceipt!=null
      ||player.ref.playbackState!=androidx.media3.common.Player.STATE_ENDED||!player.ref.playWhenReady)return false
    val current=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return false
    val window=player.ref.currentMediaItemIndex
    if(current !in idle.first until idle.first+idle.size-1||window<0||window+1>=player.ref.mediaItemCount
      ||index(player.ref.getMediaItemAt(window+1).mediaId)!=current+1)return false
    val position=player.ref.currentPosition
    // All output still passes the same registered guard binding. A cancelled
    // or paused owner must not even mutate the decoder cursor.
    if(!player.ncGuardedPlay())return false
    player.ref.seekTo(window,position)
    return true
  }
  /** Source extension cannot restart an exhausted prefix at its first item. */
  internal fun resumeStream():Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    val plan=stream?:return false
    if(closed||player.ncMuxedTrialOwner!==this||player.ncMuxedTrialRetired
      ||player.ncMuxedTrialRevision!=sourceRevision||!player.ncMuxedTrialSessionEnabled
      ||NCPlaybackGuard.shared.currentTicket()!=ticket
      ||player.ncPlaybackBinding.ticket!=ticket||player.ncPlaybackBinding.requestId!=request
      ||player.ncPlaybackBinding.chunkId!=chunk||player.ncMuxedTrialReceipt?.observe()==null
      ||player.ref.playbackState!=androidx.media3.common.Player.STATE_ENDED||!player.ref.playWhenReady
      ||installedRanges>plan.totalRanges)return false
    val current=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return false
    val window=player.ref.currentMediaItemIndex
    if(current !in 0 until installedRanges-1||window<0||window+1>=player.ref.mediaItemCount
      ||index(player.ref.getMediaItemAt(window+1).mediaId)!=current+1)return false
    val position=player.ref.currentPosition
    if(!player.ncGuardedPlay())return false
    player.ref.seekTo(window,position)
    return true
  }
  /** Completion of the Media3 source update is the append receipt. */
  fun appendStream(context:Context,values:List<Clip>,first:Int,done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    val plan=stream?:return false
    val addedBytes=values.sumOf {it.bytes}
    if(closed||appendPending||first!=installedRanges||values.isEmpty()
      ||first+values.size>plan.totalRanges||installedBytes+addedBytes>128*1024*1024L
      ||values.any { !it.file.isFile||it.file.length()!=it.bytes })return false
    appendPending=true
    try {
      source.addMediaSources(mediaSources(context,values,first,prefix),
        Handler(player.ref.applicationLooper),Runnable {
          appendPending=false
          val accepted=!closed&&player.ncMuxedTrialOwner===this&&!player.ncMuxedTrialRetired
            &&player.ncMuxedTrialRevision==sourceRevision&&player.ncMuxedTrialSessionEnabled
            &&NCPlaybackGuard.shared.currentTicket()==ticket
            &&player.ncPlaybackBinding.ticket==ticket&&player.ncPlaybackBinding.requestId==request
            &&player.ncPlaybackBinding.chunkId==chunk&&player.ncMuxedTrialReceipt?.observe()!=null
            &&values.all {it.file.isFile&&it.file.length()==it.bytes}
          if(accepted){
            clips+=values;installedRanges+=values.size;installedBytes+=addedBytes
            resumeStream()
          }
          done(accepted)
        })
      return true
    }catch(error:RuntimeException){appendPending=false;close();throw error}
  }
  fun appendIdle(context:Context,values:List<Clip>,first:Int):Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    if(closed||sealed||idle==null||values.any { !it.file.isFile||it.file.length()!=it.bytes })return false
    if(!idle.append(first,values.size))return false
    val next=values.mapIndexed {index,clip->clip.copy(startSamples=(first+index)*24000L)}
    try {
      source.addMediaSources(mediaSources(context,next,first,prefix),
        Handler(player.ref.applicationLooper),Runnable {resumeIdle()})
      clips+=next
      return true
    }catch(error:RuntimeException){close();throw error}
  }
  /** Removal callback confirms the timeline, not delegated file closure.
   * Removed child readers are retired before mutation; the module waits for
   * those exact children off-main before acknowledging JavaScript cleanup.
   */
  fun pruneIdle(cursor:Int,done:(Boolean,List<NCMuxedTrialReaderFence.Child>)->Unit):Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    if(closed||idle==null)return false
    val playing=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return false
    val token=idle.beginPrune(cursor,playing)?:return false
    if(token.remove==0){done(idle.completePrune(token),emptyList());return true}
    val removed=childFences.take(token.remove)
    if(removed.size!=token.remove)return false
    removed.forEach {it.retire()}
    source.removeMediaSourceRange(0,token.remove,Handler(player.ref.applicationLooper),Runnable {
      val confirmed=!closed&&idle.completePrune(token)
      if(confirmed)repeat(token.remove){clips.removeAt(0);childFences.removeAt(0)}
      done(confirmed,removed)
    })
    return true
  }
  /** Seal only a future, retained idle clip. The current decoder source is
   * never replaced. Its planned end and every anticipation frame are baked
   * into the subsequent native playlist, not timed by a JavaScript poll.
   * All old and new leases stay pinned until the whole source detaches. */
  fun sealIdle(context:Context,target:Int,frames:Int,following:List<Clip>,done:(Boolean)->Unit):Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    if(closed||sealed||idle==null
      ||following.any {!it.file.isFile||it.file.length()!=it.bytes})return false
    val playing=player.ref.currentMediaItem?.mediaId?.let {index(it)}?:return false
    val cut=idle.seal(target,playing,frames,following.size)?:return false
    val original=clips.getOrNull(cut.offset)?:return false
    sealed=true
    childFences.drop(cut.offset).forEach {it.retire()}
    source.removeMediaSourceRange(cut.offset,clips.size,Handler(player.ref.applicationLooper),Runnable {
      val current=player.ref.currentMediaItem?.mediaId?.let {index(it)}
      if(closed||current==null||current>=target){done(false);return@Runnable}
      val clipped=original.copy(frames=frames,samples=frames*2000)
      while(clips.size>cut.offset){clips.removeAt(clips.lastIndex);childFences.removeAt(childFences.lastIndex)}
      val start=clipped.startSamples+clipped.samples
      val next=following.map {it.copy(startSamples=start+it.startSamples)}
      val joined=UUID.randomUUID().toString().replace("-","")
      joinPrefix=joined;joinStart=target
      val trimmed=ClippingMediaSource.Builder(mediaSources(context,listOf(clipped),target,joined).single()).setEndPositionUs(cut.endUs).build()
      clips+=clipped;clips+=next
      source.addMediaSources(listOf(trimmed)+mediaSources(context,next,target+1,joined),
        Handler(player.ref.applicationLooper),Runnable {done(!closed)})
    })
    return true
  }
  /** Late, authorized handoff only after the outgoing audio sink's final END.
   * Extend the same concatenation, select the successor paused, then remove
   * the old children. The module joins the outgoing reader fence off-main.
   */
  fun continueEpoch(context:Context,prepared:Prepared,registered:()->Boolean,
                    done:(Boolean,NCMuxedTrialPlayer,NCMuxedTrialReaderFence)->Unit):Boolean {
    check(Looper.myLooper()==player.ref.applicationLooper)
    val ended=player.ncMuxedTrialReceipt?.observe()
    if(!registered()||closed||idle!=null||appendPending||!acceptsDrain
      ||player.ncMuxedTrialOwner!==this||player.ncMuxedTrialRetired
      ||!player.ncMuxedTrialSessionEnabled||player.ncMuxedTrialRevision!=sourceRevision
      ||player.ref.playbackState!=androidx.media3.common.Player.STATE_ENDED||player.ref.isPlaying
      ||ended?.started!=true||ended.completed!=true||ended.playing
      ||NCPlaybackGuard.shared.currentTicket()!=prepared.ticket
      ||player.ncPlaybackBinding.ticket!=prepared.ticket
      ||player.ncPlaybackBinding.requestId!=prepared.request
      ||player.ncPlaybackBinding.chunkId==prepared.chunk
      ||prepared.clips.isEmpty()||prepared.clips.any {!it.file.isFile||it.file.length()!=it.bytes})return false
    val samples=prepared.stream?.samples?:prepared.clips.sumOf {it.samples.toLong()}
    if(!player.ncRotateMuxedSource(this,prepared.ticket,prepared.request,prepared.chunk,samples))return false
    val nextPrefix=UUID.randomUUID().toString().replace("-","")
    val nextFence=NCMuxedTrialReaderFence()
    val nextChildren=mutableListOf<NCMuxedTrialReaderFence.Child>()
    player.ncTrackMuxedReaderFence(nextFence)
    val next=NCMuxedTrialPlayer(player,prepared.clips.toMutableList(),source,nextPrefix,nextFence,
      nextChildren,stream=prepared.stream,ticket=prepared.ticket,request=prepared.request,chunk=prepared.chunk)
    next.continuationPending=true
    player.ncMuxedTrialOwner=next;player.ncMuxedTrialPosition=next::positionSeconds
    fun current()=registered()&&!next.closed&&player.ncMuxedTrialOwner===next&&!player.ncMuxedTrialRetired
      &&player.ncMuxedTrialSessionEnabled&&player.ncMuxedTrialRevision==sourceRevision+1
      &&NCPlaybackGuard.shared.currentTicket()==prepared.ticket
      &&player.ncPlaybackBinding.ticket==prepared.ticket&&player.ncPlaybackBinding.requestId==prepared.request
      &&player.ncPlaybackBinding.chunkId==prepared.chunk&&player.ncMuxedTrialReceipt?.observe()!=null
      &&!player.ref.isPlaying&&!player.ref.playWhenReady
      &&prepared.clips.all {it.file.isFile&&it.file.length()==it.bytes}
    fun failed(){player.ncCloseMuxedTrial();done(false,next,readerFence)}
    try {
      source.addMediaSources(mediaSources(context,prepared.clips,0,nextPrefix,nextFence,nextChildren),
        Handler(player.ref.applicationLooper),Runnable {
          if(!current()){failed();return@Runnable}
          try {
            // A seek out of natural END reuses the already prepared player;
            // it does not authorize output or rewind any Desktop avatar frame.
            player.ref.seekTo(clips.size,0)
            source.removeMediaSourceRange(0,clips.size,Handler(player.ref.applicationLooper),Runnable {
              if(current()){next.continuationPending=false;done(true,next,readerFence)} else failed()
            })
          }catch(_:RuntimeException){failed()}
        })
    }catch(_:RuntimeException){failed()}
    return true
  }
  internal fun retireForContinuation() {
    check(Looper.myLooper()==player.ref.applicationLooper)
    closed=true;readerFence.retire();idle?.close()
  }
  fun close() {
    check(Looper.myLooper()==player.ref.applicationLooper)
    readerFence.retire()
    if(closed)return
    closed=true
    idle?.close()
    player.ncMuxedTrialReceipt?.close()
    // A session keeps the same texture's valid pixels between source epochs.
    // Whole-player disposal still detaches the view/surface in the caller.
    if(!player.ncMuxedTrialSessionEnabled)player.ref.clearVideoSurface()
    player.ref.stop()
    player.ref.clearMediaItems()
    player.ncMuxedTrialPosition=null
  }

  companion object {
    private fun mediaSources(context:Context,clips:List<Clip>,first:Int,prefix:String,readerFence:NCMuxedTrialReaderFence,
      childFences:MutableList<NCMuxedTrialReaderFence.Child>) =
      clips.mapIndexed {index,clip->val child=readerFence.child();childFences+=child
        mediaSource(context,clip,"$prefix-${first+index}",child)}
    /** Reuse the validated clip and exact native child identity without
     * creating a reader owner or deriving identity from a mutable index.
     */
    internal fun mediaSource(context:Context,clip:Clip,mediaId:String,child:NCMuxedTrialReaderFence.Child):ProgressiveMediaSource=
      ProgressiveMediaSource.Factory(child.wrap(DefaultDataSource.Factory(context)))
        .createMediaSource(MediaItem.Builder().setMediaId(mediaId).setUri(clip.file.toURI().toString()).build())
    /** Off-main validation. Files must be completed scoped relay leases, not
     * server URLs. Confinement is necessary, not a substitute for ticket scope.
     */
    fun validate(context:Context,values:List<Map<String,Any>>,frames:Int,samples:Long):List<Clip> {
      require(Looper.myLooper()!=Looper.getMainLooper())
      require(frames in 1..720 && samples in 1..1441999 && kotlin.math.abs(samples-frames*2000L)<2000)
      require(values.size==(frames+11)/12 && values.size in 1..60)
      fun integer(row:Map<String,Any>,key:String):Long {
        val value=(row[key] as? Number)?.toDouble()?:throw IllegalArgumentException("Invalid muxed integer")
        require(value.isFinite() && value==kotlin.math.floor(value) && value in 0.0..2147483647.0)
        return value.toLong()
      }
      var totalBytes=0L
      return values.mapIndexed { index,row ->
        require(row.keys==setOf("uri","bytes","index","startFrame","frameCount","validSamples",
          "delaySamples","paddingSamples","rawSamples","sampleRate","fps"))
        val count=minOf(12,frames-index*12)
        val valid=if(index==values.lastIndex)samples-index*24000L else 24000L
        require(integer(row,"index")==index.toLong() && integer(row,"startFrame")==index*12L
          && integer(row,"frameCount")==count.toLong() && integer(row,"validSamples")==valid
          && integer(row,"sampleRate")==48000L && integer(row,"fps")==24L)
        val file=File(URI(row["uri"] as? String?:throw IllegalArgumentException("Invalid muxed URI")))
        val bytes=integer(row,"bytes")
        require(NCIdleChunkFile.confined(context.cacheDir,file) && file.isFile && bytes in 1..16*1024*1024
          && file.length()==bytes)
        totalBytes+=bytes;require(totalBytes<=128*1024*1024)
        val extractor=MediaExtractor()
        try {
          extractor.setDataSource(file.canonicalPath)
          require(extractor.trackCount==2)
          val video=extractor.getTrackFormat(0);val audio=extractor.getTrackFormat(1)
          require(video.getString(MediaFormat.KEY_MIME)=="video/avc"
            && audio.getString(MediaFormat.KEY_MIME)=="audio/mp4a-latm"
            && audio.getInteger(MediaFormat.KEY_SAMPLE_RATE)==48000
            && audio.getInteger(MediaFormat.KEY_CHANNEL_COUNT)==1)
          val observed=if(audio.containsKey(MediaFormat.KEY_ENCODER_DELAY))audio.getInteger(MediaFormat.KEY_ENCODER_DELAY) else 0
          val observedPadding=if(audio.containsKey(MediaFormat.KEY_ENCODER_PADDING))audio.getInteger(MediaFormat.KEY_ENCODER_PADDING) else null
          require(NCMuxedTrialSamples.matches(valid.toInt(),integer(row,"delaySamples").toInt(),
            integer(row,"paddingSamples").toInt(),integer(row,"rawSamples").toInt(),observed,
            audio.getLong(MediaFormat.KEY_DURATION),observedPadding))
          extractor.selectTrack(0)
          var ordinal=0
          while(extractor.sampleTime>=0) {
            require(ordinal<count && kotlin.math.abs(extractor.sampleTime-ordinal*1000000L/24)<=2)
            ordinal++;extractor.advance()
          }
          require(ordinal==count && file.length()==bytes)
        } finally { extractor.release() }
        Clip(file.canonicalFile,bytes,valid.toInt(),count,index*24000L,
          Trim(integer(row,"delaySamples").toInt(),integer(row,"paddingSamples").toInt(),integer(row,"rawSamples").toInt()))
      }
    }
    fun validateStream(context:Context,values:List<Map<String,Any>>,first:Int,
      plan:NCMuxedTrialStreamRanges.Plan,prefix:Boolean=false):List<Clip> {
      val batch=if(prefix){require(first==0);NCMuxedTrialStreamRanges.stagePrefix(values,plan)}
        else NCMuxedTrialStreamRanges.normalize(values,first,plan)
      return validate(context,batch.rows,batch.frames,batch.samples).mapIndexed {offset,clip ->
        clip.copy(startSamples=(first+offset)*24000L)
      }
    }

    /** Main-thread install only after scope and file lease ownership recheck. */
    fun prepare(context:Context,player:AudioPlayer,clips:List<Clip>,ticket:String,request:String,chunk:String,
      probeGroups:List<Int>?=null):NCMuxedTrialPlayer? {
      check(Looper.myLooper()==player.ref.applicationLooper)
      require(clips.isNotEmpty() && clips.all { it.file.isFile && it.file.length()==it.bytes })
      val prefix=UUID.randomUUID().toString().replace("-","")
      val readerFence=NCMuxedTrialReaderFence()
      val childFences=mutableListOf<NCMuxedTrialReaderFence.Child>()
      val source=ConcatenatingMediaSource(*mediaSources(context,clips,0,prefix,readerFence,childFences).toTypedArray())
      player.ncTrackMuxedReaderFence(readerFence)
      // Inert whole-source fixture observation only. Progressive live sources
      // are not silently routed through this diagnostic preparation path.
      if(probeGroups!=null) {
        require(clips.all {it.validatedTrim!=null})
        val groups=NCContinuousMuxedFixtureLayout.split(probeGroups,clips.map {it.frames},clips.map {it.samples})
        val plans=groups.mapIndexed {ordinal,group -> "$prefix-source-$ordinal" to group.plan}
        val entries=groups.flatMapIndexed {ordinal,group ->
          val handle=plans[ordinal].first
          (0 until group.rangeCount).map {local ->
            val index=group.firstRange+local;val clip=clips[index];val trim=clip.validatedTrim!!
            NCContinuousMuxedObservation.Enrollment("$prefix-$index",NCContinuousMuxedClipKey(handle,local,index.toLong()),
              clip.startSamples-clips[group.firstRange].startSamples,clip.samples.toLong(),trim.delay,trim.padding,trim.raw)
          }
        }
        player.ncContinuousPresentation.enroll(plans,entries)
      } else if(clips.all {it.validatedTrim!=null}) {
        val plan=NCMuxedTrialStreamRanges.Plan(clips.sumOf {it.frames},clips.sumOf {it.samples.toLong()})
        player.ncContinuousPresentation.enroll(prefix,plan,clips.mapIndexed {index,clip ->
          val trim=clip.validatedTrim!!
          NCContinuousMuxedObservation.Enrollment("$prefix-$index",NCContinuousMuxedClipKey(prefix,index,index.toLong()),
            clip.startSamples,clip.samples.toLong(),trim.delay,trim.padding,trim.raw)
        })
      }
      if(!player.ncPrepareMuxedTrial(source,ticket,request,chunk,clips.sumOf { it.samples.toLong() })){
        player.ncContinuousPresentation.fence("prepare_rejected")
        readerFence.retire();return null
      }
      if(probeGroups!=null) {
        // Preparation installs a new item generation. Capture only that exact
        // existing binding; later EOS checks cannot bind, play or renew output.
        val binding=player.ncPlaybackBinding
        val item=player.ncItemIdentity
        player.ncContinuousPresentation.enableTerminalDrainProbe {
          player.ncIsAliveSnapshot && player.ncItemIdentity==item
            && binding.observePhoneReply(ticket,request,chunk)?.playing==true
        }
      }
      val trial=NCMuxedTrialPlayer(player,clips.toMutableList(),source,prefix,readerFence,childFences)
      player.ncMuxedTrialPosition=trial::positionSeconds
      return trial
    }
    fun prepareStream(context:Context,player:AudioPlayer,clips:List<Clip>,ticket:String,
      request:String,chunk:String,plan:NCMuxedTrialStreamRanges.Plan):NCMuxedTrialPlayer? {
      check(Looper.myLooper()==player.ref.applicationLooper)
      require(clips.size in minOf(2,plan.totalRanges)..plan.totalRanges
        &&clips.all {it.file.isFile&&it.file.length()==it.bytes})
      val prefix=UUID.randomUUID().toString().replace("-","")
      val readerFence=NCMuxedTrialReaderFence()
      val childFences=mutableListOf<NCMuxedTrialReaderFence.Child>()
      val source=ConcatenatingMediaSource(*mediaSources(context,clips,0,prefix,readerFence,childFences).toTypedArray())
      player.ncTrackMuxedReaderFence(readerFence)
      if(!player.ncPrepareMuxedTrial(source,ticket,request,chunk,plan.samples)){
        readerFence.retire();return null
      }
      val trial=NCMuxedTrialPlayer(player,clips.toMutableList(),source,prefix,readerFence,childFences,
        stream=plan,ticket=ticket,request=request,chunk=chunk)
      player.ncMuxedTrialPosition=trial::positionSeconds
      return trial
    }
    fun prepareIdle(context:Context,player:AudioPlayer,clips:List<Clip>,ticket:String,first:Int):NCMuxedTrialPlayer? {
      check(Looper.myLooper()==player.ref.applicationLooper)
      require(clips.isNotEmpty()&&clips.all {it.file.isFile&&it.file.length()==it.bytes})
      val window=NCMuxedTrialIdleWindow(first,clips.size)
      val prefix=UUID.randomUUID().toString().replace("-","")
      val readerFence=NCMuxedTrialReaderFence()
      val childFences=mutableListOf<NCMuxedTrialReaderFence.Child>()
      val source=ConcatenatingMediaSource(*mediaSources(context,clips,first,prefix,readerFence,childFences).toTypedArray())
      player.ncTrackMuxedReaderFence(readerFence)
      if(!player.ncPrepareMuxedIdle(source,ticket)){
        readerFence.retire();return null
      }
      return NCMuxedTrialPlayer(player,clips.mapIndexed {index,clip->clip.copy(startSamples=(first+index)*24000L)}.toMutableList(),source,prefix,readerFence,childFences,window)
    }
  }
}
