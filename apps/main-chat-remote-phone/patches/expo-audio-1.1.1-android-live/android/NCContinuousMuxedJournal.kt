package expo.modules.audio

/** Reports native authority's events; it grants no permission and does not
 * replace the guard's started/completed history. Only the native authority may
 * publish after its ledger commit. ACK frees journal storage, not source state.
 */
internal class NCContinuousMuxedJournal(val runRevision:Long,
  private val maxSources:Int=64,private val maxEvents:Int=256,internal val desktopOrdered:Boolean=false) {
  enum class Kind(val wire:String) {
    STARTED("source_started"), COMPLETED("source_completed"), READERS_CLOSED("source_readers_closed"),
    VISUAL_STARTED("visual_started"), VISUAL_READERS_CLOSED("visual_readers_closed"),
    VISUAL_RETIRED("visual_retired"), SPEECH_MEMBERSHIP_COMPLETED("speech_membership_completed")
  }
  data class Event(val cursor:Long,val sourceHandle:String,val kind:Kind,val elapsedRealtimeMs:Long)
  data class Snapshot(val runRevision:Long,val publishedCursor:Long,val acknowledgedCursor:Long,
    val events:List<Event>,val sourceCount:Int,val reservedEvents:Int,val failure:String?)
  private val published=linkedMapOf<String,MutableSet<Kind>>()
  private val orderedVisual=linkedMapOf<String,Boolean>()
  private data class VisualEpoch(val handle:String,val parent:String,val published:MutableSet<Kind>)
  private var visual:VisualEpoch?=null
  private val events=ArrayDeque<Event>()
  private var reserved=0
  private var tail=0L
  private var acknowledged=0L
  private var failure:String?=null
  init {require(runRevision>0 && maxSources in 1..64 && maxEvents in 3..256)}

  @Synchronized fun reserveSource(sourceHandle:String):Boolean {
    if(desktopOrdered ||failure!=null || visual!=null || sourceHandle.isBlank() || published.containsKey(sourceHandle)
      || published.size>=maxSources || events.size+reserved+3>maxEvents)return false
    published[sourceHandle]=mutableSetOf()
    reserved+=3
    return true
  }
  @Synchronized internal fun reserveOrderedSource(handle:String,silent:Boolean):Boolean {
    if(!desktopOrdered ||failure!=null ||handle.isBlank() ||handle.length>128 ||handle in published
      ||published.size>=maxSources ||events.size+reserved+3>maxEvents)return false
    published[handle]=mutableSetOf();orderedVisual[handle]=silent;reserved+=3
    return true
  }
  @Synchronized internal fun releaseOrderedSource(handle:String):Boolean {
    val silent=orderedVisual[handle]?:return false;val kinds=published[handle]?:return false
    val closed=if(silent)Kind.VISUAL_RETIRED else Kind.READERS_CLOSED
    if(closed !in kinds ||events.any{it.sourceHandle==handle})return false
    reserved-=3-kinds.size;published.remove(handle);orderedVisual.remove(handle)
    return true
  }

  /** One separately typed epoch. Reservation is not presentation or permission;
   * native Authority must validate the exact RETURN before exposing any output. */
  @Synchronized fun reserveVisualEpoch(handle:String,parent:String):Boolean {
    if(desktopOrdered ||failure!=null ||visual!=null ||handle.isBlank() ||handle.length>128
      ||handle in published ||parent!=published.keys.lastOrNull()
      ||events.size+reserved+4>maxEvents)return false
    visual=VisualEpoch(handle,parent,mutableSetOf());reserved+=4
    return true
  }

  @Synchronized fun publish(sourceHandle:String,kind:Kind,elapsedRealtimeMs:Long):Boolean {
    // Output receipts stay fenced; already-reserved ownership housekeeping
    // can still reconcile a cancelled run. It cannot grant or restore output.
    if(failure!=null &&kind !in listOf(Kind.READERS_CLOSED,Kind.VISUAL_READERS_CLOSED,Kind.VISUAL_RETIRED))return false
    val epoch=visual
    val isVisual=kind in listOf(Kind.VISUAL_STARTED,Kind.VISUAL_READERS_CLOSED,Kind.VISUAL_RETIRED)
    val source=if(desktopOrdered)published[sourceHandle]
      else if(isVisual)epoch?.takeIf {it.handle==sourceHandle}?.published else published[sourceHandle]
    if(source==null || elapsedRealtimeMs<0) {latchTerminalFailure("event_identity");return false}
    if(desktopOrdered &&(orderedVisual[sourceHandle]!=isVisual ||kind==Kind.SPEECH_MEMBERSHIP_COMPLETED)) {
      latchTerminalFailure("event_kind");return false
    }
    if(kind in source)return true
    if(kind==Kind.SPEECH_MEMBERSHIP_COMPLETED &&(epoch?.parent!=sourceHandle ||Kind.COMPLETED !in source)
      ||kind==Kind.VISUAL_STARTED &&Kind.VISUAL_READERS_CLOSED in source
      ||kind==Kind.VISUAL_RETIRED &&Kind.VISUAL_READERS_CLOSED !in source) {
      latchTerminalFailure("event_order");return false
    }
    if(kind==Kind.COMPLETED && Kind.STARTED !in source) {
      latchTerminalFailure("event_order");return false
    }
    if(reserved<=0 || events.size>=maxEvents || tail==Long.MAX_VALUE) {
      latchTerminalFailure("journal_capacity");return false
    }
    events.addLast(Event(++tail,sourceHandle,kind,elapsedRealtimeMs))
    source.add(kind);reserved--
    return true
  }

  @Synchronized fun acknowledge(runRevision:Long,cursor:Long):Boolean {
    if(runRevision!=this.runRevision || cursor<0 || cursor>tail)return false
    if(cursor<=acknowledged)return true
    // Every published cursor is contiguous; no caller can ACK a future event.
    while(events.firstOrNull()?.let {it.cursor<=cursor}==true)events.removeFirst()
    acknowledged=cursor
    return true
  }

  @Synchronized fun latchTerminalFailure(cause:String) {
    if(failure==null)failure=cause
  }
  @Synchronized fun snapshot():Snapshot=Snapshot(runRevision,tail,acknowledged,
    events.toList(),published.size,reserved,failure)
  /** Bounded lifecycle history survives event storage reclamation by ACK. */
  @Synchronized fun hasPublished(handle:String,kind:Kind):Boolean =
    kind in (visual?.takeIf {it.handle==handle}?.published?:published[handle]?:emptySet())
}
