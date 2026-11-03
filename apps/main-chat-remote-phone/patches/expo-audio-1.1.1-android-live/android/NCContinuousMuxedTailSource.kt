package expo.modules.audio

import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Log
import android.util.Pair
import androidx.media3.common.C
import androidx.media3.common.Timeline
import androidx.media3.common.util.UnstableApi
import androidx.media3.decoder.DecoderInputBuffer
import androidx.media3.exoplayer.FormatHolder
import androidx.media3.exoplayer.AbstractConcatenatedTimeline
import androidx.media3.exoplayer.source.ForwardingTimeline
import androidx.media3.exoplayer.source.MediaSource
import androidx.media3.exoplayer.source.MediaPeriod
import androidx.media3.exoplayer.source.SampleStream
import androidx.media3.exoplayer.source.WrappingMediaSource
import androidx.media3.exoplayer.trackselection.ExoTrackSelection
import androidx.media3.exoplayer.upstream.Allocator

/** Keeps the true last clip nonfinal while this exact continuous run is open.
 * Media3 otherwise finalizes a temporarily exhausted finite concat, preventing
 * normal renderer replaceStream when another already-validated clip arrives.
 * Genuine EOF also waits for an actually selected adjacent same-renderer stream,
 * so an unprepared successor cannot permanently finalize the old renderer.
 * No clips, IDs, times, samples, seeks or epochs are invented or changed.
 * The authoritative Queue owns serialization and its exact seal revision.
 */
@UnstableApi
internal class NCContinuousMuxedTailSource(source:MediaSource,private val ownership:Any?=null,
  private val isCurrent:()->Boolean):WrappingMediaSource(source) {
  private enum class State {NEW,OPEN,SEALED,FAILED,RELEASED}
  @Volatile private var state=State.NEW
  private var sourceHandler:Handler?=null
  private var latest:Timeline?=null
  private var pending:((Boolean)->Unit)?=null
  private var periodTraceCount=0
  // Installed before source preparation; observer exceptions never affect Media3.
  internal var preparationObserver:((String?,String)->Unit)?=null
  private fun preparation(mediaId:String?,stage:String) {
    try {preparationObserver?.invoke(mediaId,stage)}catch(_:Throwable){}
  }
  private val periods=mutableMapOf<Any,TracedPeriod>()

  /** Retention only, never playback authority. Output/decoder cursors can pass
   * a period before Media3's playing queue releases it. Removing that period
   * from the playlist forces an internal seek even though PCM was presented. */
  @Synchronized internal fun protectedPeriodMediaIds():Set<String>? {
    if((state!=State.OPEN && state!=State.SEALED) || !isCurrent())return null
    val timeline=latest?:return null
    val period=Timeline.Period();val window=Timeline.Window()
    val ids=mutableSetOf<String>()
    for(uid in periods.keys) {
      val index=timeline.getIndexOfPeriod(uid)
      if(index<0)return null
      timeline.getPeriod(index,period)
      val id=timeline.getWindow(period.windowIndex,window).mediaItem.mediaId
      if(id.isBlank())return null
      ids+=id
    }
    return ids
  }

  /** Provenance only: this cannot pause, grant output, sample a clock or prove
   * presentation. Only a genuinely withheld selected audio EOF can create it. */
  class HeldEof private constructor(private val ownership:Any,private val live:()->Boolean) {
    private var invalid=false
    @Synchronized fun matches(ownership:Any):Boolean {
      if(this.ownership!==ownership || invalid)return false
      if(!live()) {invalid=true;return false}
      return true
    }
    companion object {
      /** Actual renderer bridge for the pinned single outer playlist source.
       * The source-local observer below remains exact; never flatten recursively.
       * Native renderer/model/current-source fences establish the outer origin. */
      @JvmStatic fun observePlaylist(stream:SampleStream?,ownership:Any?,periodUid:Any?):HeldEof? {
        if(periodUid !is Pair<*,*>)return null
        return observe(stream,ownership,
          AbstractConcatenatedTimeline.getChildPeriodUidFromConcatenatedUid(periodUid))
      }
      @JvmStatic fun observe(stream:SampleStream?,ownership:Any?,periodUid:Any?):HeldEof? {
        val tail=stream as? TailStream?:return null
        val revision=tail.heldRevision(ownership,periodUid)?:return null
        return HeldEof(checkNotNull(ownership)) {tail.heldRevision(ownership,periodUid)===revision}
      }
    }
  }

  /** Passive, bounded source preparation ordering. periodIndex is the captured
   * native timeline index, NOT a stable global clip ordinal or output proof. */
  private fun tracePeriod(event:Int,index:Int,discontinuityUs:Long?=null) {
    synchronized(this) {if(periodTraceCount>=16)return;periodTraceCount++}
    try {
      val row="event=$event periodIndex=$index elapsedMs=${SystemClock.elapsedRealtime()}"+
        if(discontinuityUs==null)"" else " discontinuityUs=$discontinuityUs"
      Log.d("NCContinuousPeriod",row)
    }catch(_:RuntimeException) {} // Logging cannot intercept any normal child operation.
  }
  private inner class TracedPeriod(val child:MediaPeriod,val uid:Any,val index:Int,val mediaId:String?):MediaPeriod by child {
    val origin= this@NCContinuousMuxedTailSource
    val selected=mutableMapOf<Int,TailStream>()
    private var selectionObserved=false
    private var audioSampleObserved=false
    private var videoSampleObserved=false
    fun firstSample(type:Int) {
      when(type) {
        C.TRACK_TYPE_AUDIO->if(!audioSampleObserved) {
          audioSampleObserved=true;preparation(mediaId,"first_audio_sample_read")
        }
        C.TRACK_TYPE_VIDEO->if(!videoSampleObserved) {
          videoSampleObserved=true;preparation(mediaId,"first_video_sample_read")
        }
      }
    }
    override fun prepare(callback:MediaPeriod.Callback,positionUs:Long) {
      preparation(mediaId,"prepare_started")
      child.prepare(object:MediaPeriod.Callback {
        override fun onPrepared(mediaPeriod:MediaPeriod) {
          tracePeriod(2,index);preparation(mediaId,"prepared");callback.onPrepared(this@TracedPeriod)
        }
        override fun onContinueLoadingRequested(source:MediaPeriod) =
          callback.onContinueLoadingRequested(this@TracedPeriod)
      },positionUs)
    }
    override fun readDiscontinuity():Long = child.readDiscontinuity().also {
      if(it!=C.TIME_UNSET)tracePeriod(3,index,it)
    }
    override fun selectTracks(selections:Array<out ExoTrackSelection?>,retain:BooleanArray,
      streams:Array<SampleStream?>,reset:BooleanArray,positionUs:Long):Long {
      val previous=streams.copyOf()
      val childStreams=Array<SampleStream?>(streams.size) {slot->
        val stream=streams[slot]
        if(stream is TailStream) {
          check(stream.period===this && stream.slot==slot)
          stream.child
        } else stream
      }
      // Selection is not evidence until the real child operation has returned.
      // A throw/deselection must not retain a previous readiness marker.
      synchronized(this@NCContinuousMuxedTailSource) {invalidateSelection()}
      val result=child.selectTracks(selections,retain,childStreams,reset,positionUs)
      synchronized(this@NCContinuousMuxedTailSource) {
        for(slot in streams.indices) {
          val childStream=childStreams[slot]
          val old=previous[slot] as? TailStream
          val wrapped=if(childStream==null)null else if(old?.child===childStream)old
            else TailStream(this,slot,childStream)
          if(reset[slot])wrapped?.onChildReset()
          streams[slot]=wrapped
          if(wrapped!=null && selections[slot]!=null && periods[uid]===this
            && (state==State.OPEN || state==State.SEALED) && isCurrent()) {
            wrapped.selectionType=selections[slot]!!.trackGroup.type
            selected[slot]=wrapped
          }
        }
        invalidateExposableWitnesses()
      }
      if(!selectionObserved && streams.any{it!=null}) {
        selectionObserved=true;preparation(mediaId,"tracks_selected")
      }
      return result
    }
    fun invalidateSelection() {
      selected.values.forEach {it.invalidateHeldRevision();it.selectionType=C.TRACK_TYPE_UNKNOWN}
      selected.clear()
    }
  }
  private inner class TailStream(val period:TracedPeriod,val slot:Int,val child:SampleStream):SampleStream by child {
    private var firstSampleObserved=false
    @Volatile private var heldEof=false
    @Volatile private var revision:Any?=null
    var selectionType=C.TRACK_TYPE_UNKNOWN
    fun invalidateHeldRevision() {revision=null}
    fun heldRevision(context:Any?,uid:Any?):Any? = synchronized(this@NCContinuousMuxedTailSource) {
      if(context==null || context!==ownership || uid==null || uid!=period.uid
        || selectionType!=C.TRACK_TYPE_AUDIO || !heldEof)return@synchronized null
      val index=livePeriodIndex(this)
      if(index<0 || eofExposable(index,slot))null else revision
    }
    // Reflect only the reset already reported by the real child selection.
    // The retained wrapper remains stable; no source/player reset is issued.
    fun onChildReset() {heldEof=false;invalidateHeldRevision()}
    override fun isReady():Boolean = if(heldEof && !canExposeEof(this))false else child.isReady
    override fun readData(holder:FormatHolder,buffer:DecoderInputBuffer,flags:Int):Int {
      val result=child.readData(holder,buffer,flags)
      if(result!=C.RESULT_BUFFER_READ) {invalidateHeldRevision();return result}
      if(!buffer.isEndOfStream) {
        if(!firstSampleObserved && flags and (SampleStream.FLAG_PEEK or SampleStream.FLAG_OMIT_SAMPLE_DATA)==0) {
          firstSampleObserved=true
          period.firstSample(selectionType)
        }
        onChildReset();return result
      }
      synchronized(this@NCContinuousMuxedTailSource) {
        heldEof=!canExposeEof(this)
        revision=if(heldEof)Any() else null
      }
      if(!heldEof)return result
      // NOTHING_READ carries no sample. Remove the withheld EOF flag so reuse
      // of the caller's buffer cannot leak it into an ordinary later result.
      buffer.clear()
      return C.RESULT_NOTHING_READ
    }
  }
  private fun livePeriodIndex(stream:TailStream):Int {
    val period=stream.period
    if((state!=State.OPEN && state!=State.SEALED) || !isCurrent()
      || periods[period.uid]!==period || period.selected[stream.slot]!==stream)return -1
    return latest?.getIndexOfPeriod(period.uid)?:-1
  }
  private fun eofExposable(index:Int,slot:Int):Boolean {
    val timeline=latest?:return false
    if(index==timeline.periodCount-1)return state==State.SEALED
    // The fixed player renderer slot, not any selected track or onPrepared,
    // must exist in the exact adjacent native period's successful selection.
    val successor=periods[timeline.getUidOfPeriod(index+1)]?:return false
    return successor.selected[slot]!=null
  }
  @Synchronized private fun canExposeEof(stream:TailStream):Boolean {
    val index=livePeriodIndex(stream)
    return index>=0 && eofExposable(index,stream.slot)
  }
  /** Forget evidence when adjacency/seal makes EOF exposable, even if no one
   * observes during that interval. Later deselection cannot resurrect it. UID
   * pruning that preserves the exact current held stream leaves it truthful. */
  private fun invalidateExposableWitnesses() {
    periods.values.forEach {period->period.selected.values.forEach {stream->
      val index=latest?.getIndexOfPeriod(period.uid)?:-1
      if(index<0 || eofExposable(index,stream.slot))stream.invalidateHeldRevision()
    }}
  }
  override fun createPeriod(id:MediaSource.MediaPeriodId,allocator:Allocator,startPositionUs:Long):MediaPeriod {
    val index=synchronized(this) {latest?.getIndexOfPeriod(id.periodUid)?:-1}
    val mediaId=synchronized(this) {
      latest?.takeIf{index>=0}?.let {timeline->
        val period=timeline.getPeriod(index,Timeline.Period())
        timeline.getWindow(period.windowIndex,Timeline.Window()).mediaItem.mediaId.takeIf{it.isNotBlank()}
      }
    }
    val child=super.createPeriod(id,allocator,startPositionUs)
    tracePeriod(1,index)
    preparation(mediaId,"period_created")
    return TracedPeriod(child,id.periodUid,index,mediaId).also {period->
      synchronized(this) {
        periods[id.periodUid]?.invalidateSelection()
        periods[id.periodUid]=period
      }
    }
  }
  override fun releasePeriod(mediaPeriod:MediaPeriod) {
    check(mediaPeriod is TracedPeriod && mediaPeriod.origin===this)
    synchronized(this) {
      mediaPeriod.invalidateSelection()
      if(periods[mediaPeriod.uid]===mediaPeriod)periods.remove(mediaPeriod.uid)
    }
    super.releasePeriod(mediaPeriod.child)
  }

  /** Each published snapshot captures terminality. Sealing must not retroactively
   * turn an older open snapshot into a finite one in another Media3 component. */
  private class TailTimeline(timeline:Timeline,private val open:Boolean):ForwardingTimeline(timeline) {
    override fun getWindow(index:Int,window:Window,projectionUs:Long):Window =
      super.getWindow(index,window,projectionUs).also {
        if(open && index==windowCount-1)it.isDynamic=true
      }
  }

  override fun getInitialTimeline():Timeline? = super.getInitialTimeline()?.let {
    TailTimeline(it,state!=State.SEALED)
  }

  override fun prepareSourceInternal() {
    synchronized(this) {
      check(state==State.NEW && isCurrent()) {"Continuous tail source is not current"}
      sourceHandler=Handler(checkNotNull(Looper.myLooper()))
      state=State.OPEN
    }
    try {super.prepareSourceInternal()} catch(error:RuntimeException) {
      synchronized(this){state=State.FAILED}
      throw error
    }
  }

  override fun onChildSourceInfoRefreshed(timeline:Timeline) {
    val snapshot=synchronized(this) {
      // Output is permanently fenced, but removing the real children must
      // still publish its empty timeline so their mutation/reader joins can
      // finish. Nonempty refreshes cannot revive a failed source.
      if(Looper.myLooper()===sourceHandler?.looper && timeline.isEmpty
        && (state==State.FAILED || ((state==State.OPEN || state==State.SEALED) && !isCurrent()))) {
        state=State.FAILED
        latest=timeline
        return@synchronized TailTimeline(timeline,true)
      }
      if(state==State.FAILED && Looper.myLooper()===sourceHandler?.looper)return
      if(Looper.myLooper()!==sourceHandler?.looper || !isCurrent()
        || (state!=State.OPEN && state!=State.SEALED)) {
        if(state!=State.RELEASED)state=State.FAILED
        error("Continuous tail refresh is not current")
      }
      latest=timeline
      invalidateExposableWitnesses()
      TailTimeline(timeline,state!=State.SEALED)
    }
    try {refreshSourceInfo(snapshot)}catch(error:RuntimeException) {
      synchronized(this){if(state!=State.RELEASED)state=State.FAILED}
      throw error
    }
  }

  /** Scheduling is not an ACK. The one-shot callback runs on the real source
   * playback looper only after the sealed timeline refresh has returned. A
   * false scheduling result has no callback; ambiguity prohibits retry. */
  @Synchronized fun seal(done:(Boolean)->Unit):Boolean {
    val handler=sourceHandler?:return false
    if(state!=State.OPEN || pending!=null || !isCurrent())return false
    pending=done
    val scheduled=try {handler.post(Runnable {publishSeal()})}catch(_:RuntimeException) {
      // publishSeal takes its work only from pending. Clearing it proves that
      // even a queued runnable cannot later mutate terminality after rejection.
      pending=null;state=State.FAILED;return false
    }
    if(!scheduled){pending=null;state=State.FAILED}
    return scheduled
  }

  private fun publishSeal() {
    val work=synchronized(this) {
      val done=pending?:return
      pending=null
      val timeline=latest
      if(state!=State.OPEN || Looper.myLooper()!==sourceHandler?.looper || !isCurrent()
        || timeline==null || timeline.isEmpty) {
        if(state!=State.RELEASED)state=State.FAILED
        null to done
      } else {
        state=State.SEALED
        invalidateExposableWitnesses()
        TailTimeline(timeline,false) to done
      }
    }
    val snapshot=work.first
    val accepted=if(snapshot==null)false else try {
      refreshSourceInfo(snapshot)
      synchronized(this){state==State.SEALED && isCurrent()}
    }catch(_:RuntimeException){false}
    if(!accepted)synchronized(this){if(state!=State.RELEASED)state=State.FAILED}
    work.second(accepted)
  }

  override fun releaseSourceInternal() {
    // A queued seal still resolves false on its captured source looper. Never
    // cancel its callback or turn release into a successful terminal ACK.
    synchronized(this){
      state=State.RELEASED;latest=null
      periods.values.forEach {it.invalidateSelection()};periods.clear()
    }
    super.releaseSourceInternal()
  }
}
