package expo.modules.audio

import java.time.Instant
import java.time.format.DateTimeFormatterBuilder
import java.util.UUID

/** Failure-only source evidence. Never retain messages, file paths or arguments. */
private fun nativeRpcExceptionChain(error:Throwable,playerFailure:Boolean=false):List<Map<String,Any>> {
  val result=mutableListOf<Map<String,Any>>()
  try {
    val classes=setOf("NCContinuousMuxedRpc","NCContinuousMuxedRequests","NCContinuousMuxedQueue",
      "NCContinuousMuxedAuthority","NCContinuousMuxedSinkController","NCContinuousMuxedAudioSink",
      "NCContinuousMuxedTailSource","NCOrderedContinuation","NCPlaybackGuard","AudioModule","AudioPlayer")
    val kinds=setOf("IllegalStateException","IllegalArgumentException","NullPointerException",
      "RuntimeException","UnsupportedOperationException","IndexOutOfBoundsException","SecurityException")+
      if(playerFailure)setOf("PlaybackException","ExoPlaybackException","ExoTimeoutException",
        "IOException","FileNotFoundException","CodecException","DecoderInitializationException",
        "InitializationException","WriteException","AudioSinkException")else emptySet()
    val seen=java.util.IdentityHashMap<Throwable,Boolean>()
    var current:Throwable?=error
    repeat(if(playerFailure)6 else 3) {
      val cause=current?:return result
      if(seen.put(cause,true)!=null)return result
      val kind=cause.javaClass.simpleName.takeIf {it in kinds}?:"other"
      val reason=when(cause.message) {
        "Ordered output run unavailable"->"ordered_run_unavailable"
        "Ordered journal cursor unavailable"->"ordered_journal_unavailable"
        "Ordered timeline mutation unconfirmed"->"ordered_mutation_unconfirmed"
        else->"unclassified"
      }
      val frames=cause.stackTrace.take(32).mapNotNull {frame->
        val root=frame.className.substringBefore('$')
        val name=root.removePrefix("expo.modules.audio.")
        val method=frame.methodName.substringBefore('$')
        val local=root=="expo.modules.audio.$name" &&(name in classes ||
          playerFailure&&Regex("NC[A-Za-z0-9_]{1,96}").matches(name))
        val media=playerFailure &&(root.startsWith("androidx.media3.") ||root.startsWith("android.media."))
          &&Regex("[A-Za-z0-9_.]{1,128}").matches(root)
        if((!local&&!media) ||frame.lineNumber<0 ||!Regex("[A-Za-z0-9_]{1,64}").matches(method))null
        else mapOf("module" to if(local)name else root,"function" to method,"line" to frame.lineNumber)
      }.distinct().take(8)
      result.add(mapOf("exception_type" to kind,"actual" to reason,"frames" to frames))
      current=cause.cause
    }
  }catch(_:Exception) { /* Logging cannot replace the original failure. */ }
  return result
}

/** Diagnostic-only bounded memory. No player objects, disk IO or authority. */
internal class NCDiagnosticRecorder(
  private val wall:()->String={DateTimeFormatterBuilder().appendInstant(3).toFormatter().format(Instant.now())},
  private val mono:()->Double={System.nanoTime()/1_000_000.0},
  private val emergency:(String)->Unit={System.err.println(it)}
){
  private val lock=Any()
  private val producer=UUID.randomUUID().toString()
  private var sequence=0L
  private val queue=ArrayDeque<Map<String,Any?>>()
  private var loss:Map<String,Any?>?=null
  private var dropped=0L
  private val busy=ThreadLocal.withInitial {false}
  private val owned=setOf("schema_version","event_id","producer_id","sequence","component","build_id","build_unavailable_reason","wall_time_utc","monotonic_ms","clock_id")
  private fun envelope(fields:Map<String,Any?>,utc:String,ms:Double):Map<String,Any?> {
    check(sequence<9007199254740991L)
    val next=++sequence
    return fields+mapOf("schema_version" to 1L,"event_id" to "$producer:$next","producer_id" to producer,"sequence" to next,
      "component" to "phone.native","build_id" to null,"build_unavailable_reason" to "not_available",
      "wall_time_utc" to utc,"monotonic_ms" to ms,"clock_id" to "native-$producer")
  }
  @Suppress("UNCHECKED_CAST")
  fun emit(fields:Map<String,Any?>):String? {
    if(busy.get())return null
    busy.set(true)
    return try{
      require(fields.keys.none {it in owned})
      val data=fields["data"] as? Map<*,*>?:emptyMap<String,Any?>()
      if(!ncDiagnosticPolicy.siteEnabled(data["site"] as? String?:fields["event_name"] as? String?:"",
        fields["level"] as? String?:"debug",fields["outcome"] as? String?:"observed",data))return null
      val safe=NCDiagnosticContract.snapshot(fields) as Map<String,Any?>
      val utc=wall();val ms=mono()
      synchronized(lock){
        val event=envelope(safe,utc,ms)
        require(NCDiagnosticContract.validate(event).isEmpty())
        if(queue.size>=511){queue.removeFirst();dropped++
          loss=envelope(mapOf("level" to "warning","event_name" to "diagnostics.capture_state","trace_id" to producer,
            "operation_id" to "native-backlog","parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed",
            "basis" to "observed","links" to emptyList<Any>(),"context" to emptyMap<String,Any>(),
            "data" to mapOf("site" to "native.backlog","state" to "incomplete","reason" to "queue_overflow","dropped_count" to dropped)),utc,ms)
        }
        queue.addLast(event);event["event_id"] as String
      }
    }catch(_:Exception){try{emergency("[NC diagnostics] native event rejected or recorder unavailable")}catch(_:Exception){};null}
    finally{busy.set(false)}
  }
  @Suppress("UNCHECKED_CAST")
  fun peek(limit:Int):List<Map<String,Any?>> = synchronized(lock){
    val rows=(queue.toList()+listOfNotNull(loss)).sortedBy {(it["sequence"] as Number).toLong()}.take(limit.coerceIn(0,64))
    rows.map {NCDiagnosticContract.snapshot(it) as Map<String,Any?>}
  }
  fun ack(ids:List<String>){val accepted=ids.take(64).toSet();synchronized(lock){
    queue.removeAll {it["event_id"] in accepted};if(loss?.get("event_id") in accepted)loss=null
  }}
  fun configurePolicy(raw:Map<*,*>):Map<String,Any?> {
    val status=try{ncDiagnosticPolicy.applyPolicy(raw);"applied"}catch(_:Exception){"rejected"}
    val selected=ncDiagnosticPolicy.snapshot()
    val effective=(ncPolicyContract["categories"] as List<*>).associate {it as String to ((selected["categories"] as Map<*,*>)[it]?:selected["default_level"])}
    emit(mapOf("level" to if(status=="applied")"info" else "warning","event_name" to "diagnostics.policy",
      "trace_id" to "diagnostics-policy","operation_id" to "policy-${selected["revision"]}","parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),"context" to emptyMap<String,Any>(),
      "data" to (mapOf("site" to "diagnostics.policy","status" to status,"revision" to selected["revision"],"effective" to effective)+
        if(status=="rejected")mapOf("reason" to "invalid_policy")else emptyMap())))
    return mapOf("status" to status,"policy" to selected)
  }
}

internal val ncDiagnostics=NCDiagnosticRecorder()

/** Callback batches contain copied primitive facts only. Formatting/schema
 * validation must not occupy the player looper. RPC begin/end stays synchronous
 * because callers use its returned event IDs for causal links. */
internal class NCDiagnosticCallbackQueue(capacity:Int=64,
  private val reportLoss:(Long)->Unit={lost->ncDiagnostics.emit(mapOf(
    "level" to "warning","event_name" to "diagnostics.capture_state","trace_id" to "native-callbacks",
    "operation_id" to "native-callback-backlog","parent_operation_id" to null,"phase" to "snapshot",
    "outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),"context" to emptyMap<String,Any>(),
    "data" to mapOf("site" to "native.backlog","state" to "incomplete",
      "reason" to "callback_queue_overflow","dropped_count" to lost)))}) {
  private val dropped=java.util.concurrent.atomic.AtomicLong()
  private val worker=java.util.concurrent.ThreadPoolExecutor(1,1,0L,java.util.concurrent.TimeUnit.MILLISECONDS,
    java.util.concurrent.ArrayBlockingQueue<Runnable>(capacity.also{require(it in 1..128)}),
    java.util.concurrent.ThreadFactory {task->Thread(task,"nc-diagnostic-callbacks").apply{isDaemon=true}})
  private fun losses(){val lost=dropped.getAndSet(0);if(lost>0)try{reportLoss(lost)}catch(_:Exception){dropped.addAndGet(lost)}}
  fun dispatch(work:()->Unit):Boolean=try {
    worker.execute {try{work()}catch(_:Exception){dropped.incrementAndGet()}finally{losses()}}
    true
  }catch(_:java.util.concurrent.RejectedExecutionException){dropped.incrementAndGet();false}
  fun close(timeoutMs:Long=5000):Boolean {
    worker.shutdown()
    return worker.awaitTermination(timeoutMs,java.util.concurrent.TimeUnit.MILLISECONDS)
  }
}
internal val ncDiagnosticCallbacks=NCDiagnosticCallbackQueue()

/** Shared Live/manual route evidence. Primitive categories only, never routing authority. */
class NCMicrophoneRouteEvidence(private val mode:String,
  private val emit:(Map<String,Any?>)->String? = ncDiagnostics::emit) {
  private val trace=UUID.randomUUID().toString()
  private var previous:List<Int?>?=null
  /** Decision-only evidence, using the values already read by the route owner. */
  fun retentionDecision(origin:String,condition:String,actual:Any?,exceptionType:String?) {try {
    if(origin !in setOf("stop","reuse","maintenance") || condition !in setOf("foreground",
      "foreground_epoch_current","route_token_present","sco_route","retention_enabled","output_open",
      "route_selected","route_owner_current","microphone_verified","bluetooth_permission",
      "communication_mode","communication_device_read","communication_device_present",
      "communication_device_id_matches","communication_device_type_matches","device_available"))return
    val site="phone.mic.route.shared.retention_$origin"
    if(!ncDiagnosticPolicy.siteEnabled(site,"info"))return
    val data=mutableMapOf<String,Any?>("site" to site,"condition" to condition,
      "actual" to actual.takeIf {it is Boolean || it is Int},
      "expected" to if(condition=="communication_mode")3 else true)
    if(exceptionType!=null)data["exception_type"]=exceptionType.takeIf{
      it in setOf("SecurityException","IllegalStateException","IllegalArgumentException") }?:"other"
    emit(mapOf("level" to "info","event_name" to "transaction.operation","trace_id" to trace,
      "operation_id" to UUID.randomUUID().toString(),"parent_operation_id" to null,
      "phase" to "decision","outcome" to "observed","basis" to "observed",
      "links" to emptyList<Any>(),"context" to emptyMap<String,Any>(),"data" to data))
  }catch(_:Throwable){ /* A logging failure must not change route cleanup. */ }}
  /** Worker-thread route calls only; never instrument each negotiation poll.
   * The shared route helper serves Live and Talk. No ticket/device identity is logged.
   */
  fun <T> routeStep(step:String,work:()->T):T {
    val site="phone.mic.route.$mode.$step"
    if(step !in setOf("set_mode","select_device","confirm_microphone","release_route","clear_device","restore_mode",
      "retain_route","reuse_route") ||
      !ncDiagnosticPolicy.siteEnabled(site,"info"))return work()
    val operation=UUID.randomUUID().toString()
    val started=System.nanoTime()
    var begin:String?=null
    fun record(phase:String,outcome:String,actual:Boolean?):String?=try {
      val details=mapOf("site" to site,"condition" to "boolean_result","actual" to actual)+
        (if(phase=="end")mapOf("duration_ms" to (System.nanoTime()-started).coerceAtLeast(0)/1_000_000.0,
          "begin_recorded" to (begin!=null))else emptyMap())+
        (if(outcome=="failed")mapOf("condition" to "call_returned","expected" to true,"actual" to false,
          "failure_kind" to "native_route_call_failed","origin_event_id" to (begin?:"diagnostic-origin-unavailable"))else emptyMap())
      emit(mapOf("level" to if(outcome=="failed")"warning" else "info","event_name" to "transaction.operation",
        "trace_id" to trace,"operation_id" to operation,"parent_operation_id" to null,
        "phase" to phase,"outcome" to outcome,"basis" to "observed","links" to emptyList<Any>(),
        "context" to emptyMap<String,Any>(),"data" to details))
    }catch(_:Throwable){null}
    begin=record("begin","pending",null)
    try {val result=work();record("end","success",result as? Boolean);return result}
    catch(error:Throwable){record("end","failed",null);throw error}
  }
  @Synchronized fun observe(reason:String,input:Int?,requested:Int?,output:Int?=null,outputObserved:Boolean=true) {try {
    if(mode !in setOf("manual","live") || reason !in setOf("started","route_changed","failed","bind_accepted","bind_rejected","selection_rejected"))return
    // Input-only callbacks have not sampled output. Do not turn that omission
    // into an output change, or overwrite a separately observed output route.
    val values=listOf(input,requested,if(outputObserved)output else previous?.get(2))
    if(reason=="route_changed" && previous==values)return
    previous=values
    val failed=reason=="failed" || reason=="bind_rejected" || reason=="selection_rejected"
    val site="phone.mic.route.$mode.$reason"
    if(!ncDiagnosticPolicy.siteEnabled(site,if(failed)"warning" else "info"))return
    val operation=UUID.randomUUID().toString()
    listOf("actual_input",if(mode=="manual")"preferred_input" else "requested_input","communication_output")
      .zip(values).take(if(outputObserved)3 else 2).forEach {(field,type)->
      emit(mapOf("level" to if(failed)"warning" else "info","event_name" to "transaction.operation",
        "trace_id" to trace,"operation_id" to operation,"parent_operation_id" to null,
        "phase" to "snapshot","outcome" to "observed","basis" to "observed",
        "links" to emptyList<Any>(),"context" to emptyMap<String,Any>(),
        "data" to mapOf("site" to site,"condition" to field,"actual" to category(type))))
    }
  }catch(_:Throwable){ /* Diagnostics must not interrupt recording. */ }}
  /** Failure-only primitive evidence; no route queries, PCM, or exception messages. */
  fun captureFailure(origin:String,phase:String,values:Map<String,Number>) {try {
    if(origin !in setOf("queue_rejected","queue_evicted","queue_overflow_observed","audio_record_read",
      "recovery_timeout","recovery_control_rejected","control_rejected","clip_overflow"))return
    val fields=linkedMapOf<String,Any?>("origin" to origin,"owner_phase" to
      phase.takeIf {it in setOf("capture_start","foreground_arm","background_arm","steady","audio_read")}.orEmpty())
    values.filterKeys {it in setOf("queue_depth","queue_capacity","drop_count","evicted_count","read_result","buffer_age_ms","phase_elapsed_ms")}
      .filterValues {it is Int || it is Long}.forEach {(key,value)->fields[key]=value}
    val operation=UUID.randomUUID().toString()
    fields.forEach {(field,value)->emit(mapOf("level" to "warning","event_name" to "transaction.operation",
      "trace_id" to trace,"operation_id" to operation,"parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),
      "context" to emptyMap<String,Any>(),
      "data" to mapOf("site" to "phone.mic.capture.failure","condition" to field,"actual" to value)))}
  }catch(_:Throwable){ /* Preserve the original failure and cleanup even if the sink fails. */ }}
  companion object {
    // Android AudioDeviceInfo type constants. No device identifiers cross this boundary.
    fun category(type:Int?):String=when(type) {
      null,-1->"unavailable";15->"builtInMic";2->"builtInSpeaker";1->"earpiece"
      3->"wiredHeadset";4->"wiredHeadphones";7->"bluetoothSco";8->"bluetoothA2dp"
      26,27->"bluetoothLE";11->"usbDevice";12->"usbAccessory";22->"usbHeadset"
      else->"unknown"
    }
  }
}

/** Explicit handoff only: an unrelated later callback must never inherit the last RPC. */
internal object NCDiagnosticOperationContext {
  data class Link(val session:String,val operation:String,val event:String?,val parentOperation:String?=null)
  private val active=ThreadLocal<Link?>()
  fun current(session:String):Link?=active.get()?.takeIf {it.session==session}
  fun <T> within(link:Link?,work:()->T):T {
    val previous=active.get();active.set(link)
    try{return work()}finally{if(previous==null)active.remove() else active.set(previous)}
  }
  fun <T> capture(work:()->T):()->T {
    val link=active.get()
    return {within(link,work)}
  }
}

/** Copies only callback arguments. Never queries a player or an authority. */
internal class NCDiagnosticPlayerObserver(private val id:String=UUID.randomUUID().toString(),
  private val emit:(Map<String,Any?>)->String? = ncDiagnostics::emit){
  private class OrderedHistory {
    val rows=ArrayDeque<Map<String,Any?>>()
    var dropped=0L
  }
  companion object {
    // Shared by observers for the same player, including a replacement RPC instance.
    // Primitive evidence only; no player, queue, capability, file or Throwable references.
    private val orderedHistories=LinkedHashMap<String,OrderedHistory>()
    private var orderedHistoriesEvicted=0L
  }
  @Suppress("UNCHECKED_CAST","DEPRECATION") // Thread.id remains available on supported Android versions.
  fun orderedLifecycle(event:String,details:Map<String,Any?>){try{
    val active=NCDiagnosticOperationContext.current(id)
    val operation=active?.operation?:UUID.randomUUID().toString()
    val safe=NCDiagnosticContract.snapshot(details) as Map<String,Any?>
    val row=safe+mapOf("lifecycle_event" to event,"origin_operation_id" to operation,
      "origin_event_id" to active?.event,"origin_parent_operation_id" to active?.parentOperation,
      "monotonic_ms" to System.nanoTime()/1_000_000.0,
      "thread_id" to Thread.currentThread().id)
    val failed=event=="lookup_failed"
    val snapshot=synchronized(orderedHistories) {
      val history=orderedHistories.remove(id)?:OrderedHistory()
      orderedHistories[id]=history
      while(orderedHistories.size>16){orderedHistories.remove(orderedHistories.keys.first());orderedHistoriesEvicted++}
      if(!failed){
        if(history.rows.size==16){history.rows.removeFirst();history.dropped++}
        history.rows.addLast(row)
      }
      Triple(if(failed)history.rows.toList() else emptyList(),history.dropped,orderedHistoriesEvicted)
    }
    if(!failed)return // Retain cheap boundaries even when optional diagnostics are off.
    // Use the existing scalar condition/actual contract, so backend/JS/schema need no upgrade.
    val fields=linkedMapOf<String,Any?>()
    fun flatten(prefix:String,value:Any?) {when(value){
      is Map<*,*>->value.forEach{(key,item)->flatten(if(prefix.isEmpty())key as String else "$prefix.$key",item)}
      is List<*>->value.forEachIndexed{index,item->flatten("$prefix.$index",item)}
      else->fields[prefix]=value
    }}
    flatten("",row+mapOf("history_count" to snapshot.first.size,"history_dropped" to snapshot.second,
      "player_histories_evicted" to snapshot.third,"history" to snapshot.first))
    fields.entries.forEachIndexed {index,(condition,actual)->emit(mapOf(
      "level" to "error","event_name" to "transaction.operation","trace_id" to id,"operation_id" to operation,
      "parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed","basis" to "observed",
      "links" to (active?.let{listOf(mapOf("relation" to "part_of","event_id" to it.event,
        "operation_id" to it.operation))}?:emptyList<Any>()),"context" to mapOf("session_id" to id),
      "data" to mapOf("site" to "native.ordered.lookup_failed","condition" to condition,"actual" to actual,
        "expected" to null,"part_index" to index,"part_count" to fields.size))) }
  }catch(_:Exception){ /* Evidence must never change the original RPC outcome. */ }}
  private data class Source(val operation:String,val event:String?)
  private val sources=LinkedHashMap<String,Source>()
  fun withSnapshot(force:Boolean=false,read:()->Unit){
    if(force||ncDiagnosticPolicy.siteEnabled("native.player.snapshot"))read()
  }
  fun withBoundary(force:Boolean=false,read:()->Unit){
    if(force||ncDiagnosticPolicy.siteEnabled("native.player.boundary"))try{read()}catch(_:Exception){}
  }
  /** Application-thread boundary only, not a per-frame/full-state snapshot.
   * queue_depth is timeline items (not decoded frames); actual is buffered ms.
   * The ordered media ID supplies run revision/ordinal, never playback authority.
   */
  fun playbackBoundary(mediaId:String?,positionMs:Long,bufferedMs:Long,itemCount:Int,
    state:Int,playing:Boolean,ready:Boolean,suppression:Int){try{
    val stalled=state==2 &&ready &&!playing
    if(!stalled &&!ncDiagnosticPolicy.siteEnabled("native.player.boundary"))return
    val ordered=mediaId?.let{Regex("nc-ordered-([0-9]{1,16})-([0-9]{1,16})").matchEntire(it)}
    val revision=ordered?.groupValues?.get(1)?.toLongOrNull()?.takeIf{it<=9007199254740991L}
    val ordinal=ordered?.groupValues?.get(2)?.toLongOrNull()?.takeIf{it<=9007199254740991L}
    val data=mapOf<String,Any?>("site" to "native.player.boundary","condition" to "buffered_duration_ms",
      "actual" to bufferedMs,"cursor" to positionMs,"queue_depth" to itemCount,
      "state_after" to "state_${state}_playing_${playing}_ready_${ready}_suppression_$suppression")+
      if(revision!=null &&ordinal!=null)mapOf("expected" to revision,"part_index" to ordinal)else emptyMap()
    emit(mapOf("level" to if(stalled)"warning" else "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to UUID.randomUUID().toString(),"parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),
      "context" to (mapOf("session_id" to id)+(mediaId?.let{mapOf("chunk_id" to sourceKey(it))}?:emptyMap())),
      "data" to data))
  }catch(_:Exception){}}
  /** Media3's aggregate callbacks, not frame callbacks. Offset is a sum in us,
   * with sample count in expected; dropped-frame interval is ms in duration_ms.
   * These describe the player's reporting interval, not one attributed chunk.
   */
  fun videoCadence(kind:String,value:Long,extent:Long){try{
    val dropped=kind=="dropped_frames" &&value>0
    if(kind !in setOf("dropped_frames","processing_offset_us") ||extent<=0
      ||!dropped &&!ncDiagnosticPolicy.siteEnabled("native.player.cadence"))return
    cadenceEvent(kind,value,if(kind=="dropped_frames")mapOf("duration_ms" to extent)else mapOf("expected" to extent),dropped)
  }catch(_:Exception){}}
  /** The custom cached decoder does not generate Media3 video callbacks.
   * Reuse the cadence event, not another snapshot logger. Scalar parts share
   * one operation ID; the renderer limits this group to once/five seconds. */
  fun cachedCadence(details:Map<String,Any>){try{
    val gap=details["frameGapNs"] as? Long ?:return
    val expected=details["expectedIntervalNs"] as? Long ?:return
    if(gap<=0 ||expected<=0 ||gap>9007199254740991L ||expected>9007199254740991L)return
    val numbers=setOf("frameGapNs","expectedIntervalNs","suppressedGaps","sourceFrame","sourceTick","decodedAhead",
      "decodedAtNs","dueAtNs","submittedAtNs","renderCallbackAtNs","renderHandledAtNs","textureAtNs",
      "textureHandledAtNs","confirmedAtNs","maxMainWakeLateNs","waitNs")
    val safe=details.filter { (key,value)->
      key in numbers &&value is Number &&value.toDouble().isFinite() &&kotlin.math.abs(value.toDouble())<=9007199254740991.0
        ||key in setOf("decoderFinished","chunked") &&value is Boolean
    }
    val loop=details["loopId"] as? String
    val operation=UUID.randomUUID().toString()
    safe.entries.forEachIndexed {index,(field,value)->
      cadenceEvent("cached_gap.$field",value,mapOf("part_index" to index,"part_count" to safe.size),true,
        loop?.takeIf{it.matches(Regex("[a-f0-9]{64}"))},operation)
    }
  }catch(_:Exception){}}
  fun postCachedCadence(details:Map<String,Any>,queue:NCDiagnosticCallbackQueue=ncDiagnosticCallbacks){
    if(details.size>32 ||details.values.any{it !is Number &&it !is Boolean &&it !is String})return
    val copied=details.toMap()
    queue.dispatch {cachedCadence(copied)}
  }
  /** Once per stalled native activation, on the existing proof worker. Not a
   * polling snapshot, synthetic completion or another frame-gap event. */
  fun cachedBoundaryWaiting(details:Map<String,Any?>){try{
    val allowed=setOf("after_ordinal","expected_frames","tail_retained","actual_frames","run_present","run_open",
      "generation_matches","run_failed","rendered_known","rendered_ordinal","rendered_frame_offset","codec_surface",
      "unfinished_speech","first_unfinished_ordinal","first_unfinished_started","first_unfinished_completed",
      "activation_revision","waiting_ms","selection_requested","stream_matches","rendered_reason",
      "selected","paused","closed","surface_available","view_eligible","queue_current","proof_queue_delay_ms",
      "rejected_pts_us","rejected_duration_us","rejected_frame_offset","rejected_ordinal")
    val reasons=setOf("render_callback_capacity","frame_pts_unmapped","render_callback_unmapped",
      "render_callback_ambiguous","render_callback_pending","no_rendered_frame","render_source_released")
    val operation=UUID.randomUUID().toString()
    details.filterKeys{it in allowed}.forEach{(field,value)->
      if(value==null ||value is Boolean ||field=="rendered_reason" &&value in reasons ||value is Number &&value.toDouble().isFinite()
        &&kotlin.math.abs(value.toDouble())<=9007199254740991.0)
        emit(mapOf("level" to "warning","event_name" to "transaction.operation","trace_id" to id,
          "operation_id" to operation,"parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed",
          "basis" to "observed","links" to emptyList<Any>(),"context" to mapOf("session_id" to id),
          "data" to mapOf("site" to "native.ordered.cached.boundary_wait","condition" to field,"actual" to value)))
    }
  }catch(_:Exception){}}
  fun postCachedBoundaryWaiting(details:Map<String,Any?>,queue:NCDiagnosticCallbackQueue=ncDiagnosticCallbacks){
    if(details.size>32 ||details.values.any{it!=null &&it !is Number &&it !is Boolean &&it !is String})return
    val copied=details.toMap();queue.dispatch {cachedBoundaryWaiting(copied)}
  }
  private fun cadenceEvent(kind:String,actual:Any,extra:Map<String,Any>,warning:Boolean,loopId:String?=null,
    operation:String=UUID.randomUUID().toString()){
    emit(mapOf("level" to if(warning)"warning" else "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to operation,"parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),
      "context" to (mapOf("session_id" to id)+(loopId?.let{mapOf("chunk_id" to it)}?:emptyMap())),
      "data" to (mapOf("site" to "native.player.cadence","condition" to kind,"actual" to actual)+extra)))
  }
  /** EventTime values are copied from Media3, not read from a player/device.
   * event_realtime_ms is Android elapsedRealtime, not the envelope's nanoTime clock.
   * Track callbacks describe Media3 tracks; Android-internal restores still need logcat.
   */
  fun audioOutput(kind:String,realtimeMs:Long,positionMs:Long,bufferedMs:Long,values:Map<String,Long>,mediaId:String?=null){try{
    val underrun=kind=="underrun"
    if(kind !in setOf("track_initialized","track_released","position_advancing","underrun") ||
      !underrun &&!ncDiagnosticPolicy.siteEnabled("native.player.audio_output"))return
    val key=mediaId?.takeIf{it.isNotBlank()}?.let(::sourceKey)
    val fields=linkedMapOf<String,Any>("event_realtime_ms" to realtimeMs,"position_ms" to positionMs,"buffered_duration_ms" to bufferedMs,
      "callback_source_identified" to (key!=null))
    values.filterKeys {it in setOf("buffer_size_bytes","buffer_size_ms","elapsed_since_feed_ms","sample_rate_hz","start_system_time_ms")}
      .forEach {(key,value)->fields[key]=value}
    val operation=UUID.randomUUID().toString()
    fields.filterValues {it is Boolean ||it is Long &&it in 0..9007199254740991L}.forEach {(field,value)->emit(mapOf(
      "level" to if(underrun)"warning" else "debug","event_name" to "transaction.operation","trace_id" to id,"operation_id" to operation,
      "parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed","basis" to "observed",
      "links" to emptyList<Any>(),"context" to (mapOf("session_id" to id)+(key?.let{mapOf("chunk_id" to it)}?:emptyMap())),
      "data" to mapOf("site" to "native.player.audio_output.$kind","condition" to field,"actual" to value)))}
  }catch(_:Throwable){}}
  fun postAudioOutput(kind:String,realtimeMs:Long,positionMs:Long,bufferedMs:Long,values:Map<String,Long>,mediaId:String?=null,
    queue:NCDiagnosticCallbackQueue=ncDiagnosticCallbacks){
    if(kind!="underrun" &&!ncDiagnosticPolicy.siteEnabled("native.player.audio_output"))return
    if(values.size>16)return
    val copied=values.toMap()
    val source=mediaId?.takeIf{it.length<=2048}
    queue.dispatch {audioOutput(kind,realtimeMs,positionMs,bufferedMs,copied,source)}
  }
  private fun sourceKey(value:String)=java.security.MessageDigest.getInstance("SHA-256")
    .digest(value.toByteArray(Charsets.UTF_8)).joinToString("") {"%02x".format(it)}
  /** Passive source milestones. actual is Android elapsedRealtime ms, not the
   * envelope clock. First sample read is renderer consumption, NOT presentation
   * or proof that a codec accepted input. Null identity stays unattributed.
   */
  fun chunkPreparation(mediaId:String?,stage:String,realtimeMs:Long,loadTaskId:Long?,durationMs:Long?,bytes:Long?){try{
    if(stage !in setOf("load_started","load_completed","load_cancelled","load_error","period_created",
      "prepare_started","prepared","tracks_selected","first_audio_sample_read","first_video_sample_read") ||
      !ncDiagnosticPolicy.siteEnabled("native.player.preparation") || realtimeMs !in 0..9007199254740991L)return
    val key=mediaId?.takeIf{it.isNotBlank()}?.let(::sourceKey)
    val source=synchronized(sources){sources[key]}
    val data=mapOf<String,Any?>("site" to "native.player.preparation.$stage",
      "condition" to "event_realtime_ms","actual" to realtimeMs)+
      (loadTaskId?.takeIf{it in 0..9007199254740991L}?.let{mapOf("dependency_id" to "load_$it")}?:emptyMap())+
      (durationMs?.takeIf{it in 0..9007199254740991L}?.let{mapOf("duration_ms" to it)}?:emptyMap())
    val row=mapOf<String,Any?>("level" to "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to UUID.randomUUID().toString(),"parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed",
      "links" to (source?.event?.let{listOf(mapOf("relation" to "part_of","event_id" to it,"operation_id" to source.operation))}?:emptyList<Any>()),
      "context" to (mapOf("session_id" to id)+(key?.let{mapOf("chunk_id" to it)}?:emptyMap())),"data" to data)
    emit(row)
    if(stage in setOf("load_completed","load_cancelled","load_error") && bytes!=null && bytes in 0..9007199254740991L)
      emit(row+mapOf("data" to (data+mapOf("condition" to "bytes_loaded","actual" to bytes))))
  }catch(_:Throwable){}}
  fun sourceStaged(mediaId:String,accepted:Boolean){try{
    val key=sourceKey(mediaId)
    val active=NCDiagnosticOperationContext.current(id)
    val operation=active?.operation?:UUID.randomUUID().toString()
    val event=if(accepted&&!ncDiagnosticPolicy.siteEnabled("native.player.source_staged"))null else emit(mapOf("level" to "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to operation,"parent_operation_id" to null,"phase" to "decision","outcome" to "observed",
      "basis" to "observed","links" to (active?.let {listOf(mapOf("relation" to "part_of","event_id" to it.event,"operation_id" to it.operation))}?:emptyList<Any>()),
      "context" to mapOf("session_id" to id,"chunk_id" to key),
      "data" to mapOf("site" to "native.player.source_staged","condition" to "identity_accepted","expected" to true,"actual" to accepted)))
    synchronized(sources){
      // Rejected re-registration must not claim that a new owner was installed.
      if(accepted){sources.remove(key);sources[key]=Source(operation,event)
        while(sources.size>256)sources.remove(sources.keys.first())}
    }
  }catch(_:Exception){}}
  fun mediaTransition(mediaId:String?,reason:Int){try{
    if(!ncDiagnosticPolicy.siteEnabled("native.player.media_transition"))return
    val key=mediaId?.let(::sourceKey)
    val source=synchronized(sources){sources[key]}
    emit(mapOf("level" to "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to UUID.randomUUID().toString(),"parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed",
      "basis" to "observed","links" to (source?.takeIf {it.event!=null}?.let {listOf(mapOf("relation" to "part_of","event_id" to it.event,"operation_id" to it.operation))}?:emptyList<Any>()),
      "context" to (mapOf("session_id" to id)+(key?.let {mapOf("chunk_id" to it)}?:emptyMap())),
      "data" to mapOf("site" to "native.player.media_transition","state_after" to "reason_$reason",
        "condition" to "source_registration_known","expected" to true,"actual" to (source!=null))))
  }catch(_:Exception){}}
  fun playing(value:Boolean)=observe("native.player.playing",if(value)"playing" else "not_playing")
  fun state(value:Int)=observe("native.player.state","state_$value")
  fun playWhenReady(value:Boolean,reason:Int)=observe("native.player.play_when_ready","${value}_reason_$reason")
  fun lifecycle(value:String)=observe("native.module.lifecycle",value)
  /** Individual error callback: preserve the exception before onEvents/cleanup
   * can replace player state. No player queries, retained Throwables or stale RPC links. */
  fun playerFailure(errorCode:Int,generation:Long,error:Throwable){try{
    val operation=UUID.randomUUID().toString()
    val causes=nativeRpcExceptionChain(error,playerFailure=true)
    causes.forEachIndexed {index,cause->emit(mapOf(
      "level" to "error","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to operation,"parent_operation_id" to null,"phase" to "snapshot",
      "outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),
      "context" to mapOf("session_id" to id),
      "data" to (cause+mapOf("site" to "native.player.failure","condition" to "player_exception_cause",
        "expected" to errorCode,"cursor" to generation,"part_index" to index,"part_count" to causes.size))))}
  }catch(_:Exception){ /* Diagnostics must not interfere with Media3 error handling. */ }}
  /** One app-thread snapshot, not attribution of earlier source-less callbacks.
   * Indices are native timeline/source indices, never retained-file counts.
   * All fields share an operation ID so consumers cannot combine different samples.
   */
  fun playbackSnapshot(mediaId:String?,generation:Long,itemIndex:Int,itemCount:Int,
    chunkIndex:Int?,lastChunkIndex:Int?,positionMs:Long,bufferedMs:Long,
    playbackState:Int,playing:Boolean,playWhenReady:Boolean,suppression:Int,errorCode:Int?) {try{
    if(errorCode==null&&!ncDiagnosticPolicy.siteEnabled("native.player.snapshot"))return
    val key=mediaId?.let(::sourceKey)
    val source=synchronized(sources){sources[key]}
    val operation=UUID.randomUUID().toString()
    val values=linkedMapOf<String,Any?>(
      "source_generation" to generation,"media_item_index" to itemIndex,"media_item_count" to itemCount,
      "chunk_index" to chunkIndex,"timeline_last_chunk_index" to lastChunkIndex,
      "position_ms" to positionMs,"buffered_duration_ms" to bufferedMs,
      "playback_state" to when(playbackState){1->"idle";2->"buffering";3->"ready";4->"ended";else->"unknown"},
      "is_playing" to playing,"play_when_ready" to playWhenReady,
      "suppression_reason" to suppression,"player_error_code" to errorCode,
      "source_registration_known" to (source!=null))
    for((condition,actual) in values)emit(mapOf(
      "level" to if(errorCode==null)"debug" else "error","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to operation,"parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed",
      "basis" to "observed","links" to (source?.takeIf {it.event!=null}?.let {listOf(mapOf("relation" to "part_of","event_id" to it.event,"operation_id" to it.operation))}?:emptyList<Any>()),
      "context" to (mapOf("session_id" to id)+(key?.let {mapOf("chunk_id" to it)}?:emptyMap())),
      "data" to mapOf("site" to "native.player.snapshot","condition" to condition,"expected" to null,"actual" to actual)))
  }catch(_:Exception){}}
  fun <T> rpc(value:Map<String,Any>,site:String,work:(Map<String,Any>)->T):T {
    val link=value["diagnosticLink"] as? Map<*,*>
    val parent=link?.get("operation_id") as? String
    val event=link?.get("event_id") as? String
    val match=parent?.takeIf {it.length<=128}?.let {Regex("(js-[a-z0-9]+-[0-9]+-[a-z0-9]+):native:[0-9]+").matchEntire(it)}
    val valid=(link?.keys==setOf("trace_id","operation_id") ||link?.keys==setOf("trace_id","operation_id","event_id")) && link["trace_id"]==id && match!=null &&
      (link["event_id"]==null || (event!=null &&event.length<=128 &&Regex(Regex.escape(match.groupValues[1])+ ":[0-9]+").matches(event)))
    val operation=UUID.randomUUID().toString()
    val links=if(valid &&event!=null)listOf(mapOf("relation" to "part_of","event_id" to event,"operation_id" to parent)) else emptyList()
    val beginSuppressed=!ncDiagnosticPolicy.siteEnabled(site,"debug","pending",mapOf("expected" to true,"actual" to valid))
    var begin:String?=null
    fun record(phase:String,outcome:String,data:Map<String,Any?>):String?=try{
      val details=data+(if(phase=="end"&&begin!=null)mapOf("begin_recorded" to true)else emptyMap())
      if(!ncDiagnosticPolicy.siteEnabled(site,if(outcome=="failed")"error" else "debug",outcome,details))null else emit(mapOf("level" to if(outcome=="failed")"error" else "debug","event_name" to "transaction.operation",
        "trace_id" to id,"operation_id" to operation,"parent_operation_id" to if(valid)parent else null,
        "phase" to phase,"outcome" to outcome,"basis" to "observed","links" to links,
        "context" to mapOf("session_id" to id),"data" to (mapOf("site" to site)+details+
          if(phase=="end"&&beginSuppressed)mapOf("begin_suppressed" to true)else emptyMap())))
    }catch(_:Exception){null}
    begin=record("begin","pending",mapOf("condition" to "remote_link_valid","expected" to true,"actual" to valid))
    try {
      val result=NCDiagnosticOperationContext.within(NCDiagnosticOperationContext.Link(id,operation,begin,if(valid)parent else null)) {
        work(value.filterKeys {it!="diagnosticLink"})
      }
      record("end","success",emptyMap());return result
    }catch(error:Throwable){
      val failure=mapOf("condition" to "call_returned","expected" to true,"actual" to false,"failure_kind" to "native_call_failed")
      var origin=record("decision","observed",failure)?:"diagnostic-origin-unavailable"
      val causes=nativeRpcExceptionChain(error)
      causes.forEachIndexed {index,cause->
        origin=record("decision","observed",cause+mapOf("condition" to "native_exception_cause",
          "expected" to null,"failure_kind" to "native_call_failed","part_index" to index,
          "part_count" to causes.size,"cause_event_id" to origin))?:origin
      }
      record("end","failed",failure+mapOf("origin_event_id" to origin));throw error
    }
  }
  fun decision(condition:String,value:Boolean){try{
    if(value&&!ncDiagnosticPolicy.siteEnabled("native.rpc"))return
    val active=NCDiagnosticOperationContext.current(id)
    emit(mapOf("level" to "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to (active?.operation?:"$id:rpc"),"parent_operation_id" to null,"phase" to "decision","outcome" to "observed",
      "basis" to "observed","links" to (active?.let {listOf(mapOf("relation" to "part_of","operation_id" to it.operation,"event_id" to it.event))}?:emptyList<Any>()),"context" to mapOf("session_id" to id),
      "data" to mapOf("site" to "native.rpc","condition" to condition,"expected" to true,"actual" to value)))
  }catch(_:Exception){}}
  /** Optional local cue failure, not playback failure or new authorization.
   * Reuse native RPC exception sanitization; never retain raw error messages. */
  fun continuationCueFailure(stage:String,epoch:Long,error:Throwable){
    if(stage in setOf("waiting","recovered"))continuationFailure("cue.$stage",epoch,error)
  }
  fun continuationFailure(stage:String,epoch:Long,error:Throwable){try{
    if(stage !in setOf("advance","cue.waiting","cue.recovered") ||epoch !in 1..9007199254740991L)return
    val operation=UUID.randomUUID().toString()
    val causes=nativeRpcExceptionChain(error)
    causes.forEachIndexed {index,cause->emit(mapOf(
      "level" to "error","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to operation,"parent_operation_id" to null,"phase" to "snapshot",
      "outcome" to "observed","basis" to "observed","links" to emptyList<Any>(),
      "context" to mapOf("session_id" to id),
      "data" to (cause+mapOf("site" to "native.rpc","condition" to "ordered.continuation.$stage",
        "expected" to true,"actual" to false,"cursor" to epoch,"part_index" to index,"part_count" to causes.size))))}
  }catch(_:Exception){}}
  /** One failure snapshot, no polling/player queries. Use existing scalar fields
   * so the shared contract and backend require no schema/version change. */
  fun cachedRendererFailure(reason:String,details:Map<String,Any>){try{
    val safeReason=when {
      reason in setOf("presentation_timeout","segment_wait_timeout","chunk_detach_unavailable","chunk_observation_invalid")->reason
      reason.startsWith("decode_")->"decode"
      else->"renderer"
    }
    val numbers=setOf("players","files","segment","sourceTick","presented","sourceFrame","observedAtNs",
      "releasedThrough","exitAtNs","decodedAhead","pendingTick","pendingAgeNs","nowNs","submittedAtNs",
      "decodedAtNs","renderCallbackAtNs","renderHandledAtNs","textureAtNs","textureHandledAtNs","dueAtNs",
      "sinceObservedNs","waitAgeNs","maxMainWakeLateNs","clockAtNs","elapsedTicks","viewWidth","viewHeight",
      "hostAlphaPercent","hostWidth","hostHeight")
    val flags=setOf("paused","chunked","gpuReady","textureReady","reobserving","needsResubmit","decoderFinished",
      "decoderDetached","decoderFailed","viewAvailable","viewShown","hostShown","slotReady","slotSelected",
      "slotSelecting","visible","allowed","speech","surfaceSuspended")
    val timing=setOf("decodedAtNs","dueAtNs","submittedAtNs","renderCallbackAtNs","renderHandledAtNs",
      "textureAtNs","textureHandledAtNs","confirmedAtNs","maxMainWakeLateNs")
    val fields=linkedMapOf<String,Any>("failureReason" to safeReason)
    for((key,value) in details){
      if(key in flags &&value is Boolean)fields[key]=value
      else if(key in numbers &&value is Number &&value.toDouble().isFinite() &&kotlin.math.abs(value.toDouble())<=9007199254740991.0)fields[key]=value
      else if(key=="state" &&value in setOf("prepared","presented","waiting","ended","failed"))fields[key]=value
      else if(key=="timing" &&value is Map<*,*>)for((name,stamp) in value)
        if(name in timing &&stamp is Long &&stamp in 0..9007199254740991L)fields["lastConfirmed.$name"]=stamp
    }
    val operation=UUID.randomUUID().toString()
    fields.entries.take(64).forEachIndexed {index,(condition,actual)->emit(mapOf(
      "level" to "warning","event_name" to "transaction.operation","trace_id" to id,"operation_id" to operation,
      "parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed","basis" to "observed",
      "links" to emptyList<Any>(),"context" to mapOf("session_id" to id),
      "data" to mapOf("site" to "native.ordered.cached.renderer_failed","condition" to condition,"actual" to actual,
        "part_index" to index,"part_count" to minOf(fields.size,64)))) }
  }catch(_:Exception){ /* Logging cannot prevent native reader cleanup. */ }}
  private fun observe(site:String,state:String){try{
    if(!ncDiagnosticPolicy.siteEnabled(site))return
    emit(mapOf("level" to "debug","event_name" to "transaction.operation","trace_id" to id,
      "operation_id" to "$id:$site","parent_operation_id" to null,"phase" to "snapshot","outcome" to "observed",
      "basis" to "observed","links" to emptyList<Any>(),"context" to mapOf("session_id" to id),
      "data" to (mapOf("site" to site,"state_after" to state)+
        if(site.startsWith("native.player."))mapOf("condition" to "callback_source_identified","expected" to true,"actual" to false) else emptyMap())))
  }catch(_:Exception){}}
}

/** Low-frequency recovery decisions only. No paths, device addresses or speech. */
internal object NCPlaybackEvidence {
  fun record(reason:String,change:Int?=null) { try {
    val state=NCPlaybackGuard.shared.outputState()
    val operation=UUID.randomUUID().toString()
    val trace=state.ticket?.let { UUID.nameUUIDFromBytes(it.toByteArray(Charsets.UTF_8)).toString() }?:"foreground-playback"
    ncDiagnostics.emit(mapOf("level" to "info","event_name" to "transaction.operation",
      "trace_id" to trace,"operation_id" to operation,"parent_operation_id" to null,
      "phase" to "snapshot","outcome" to "observed","basis" to "observed",
      "links" to emptyList<Any>(),"context" to mapOf("session_id" to trace),
      "data" to mapOf("site" to "native.playback.$reason","condition" to "focus_change",
        "expected" to null,"actual" to change)))
  } catch(_:Exception) { /* Evidence cannot interfere with playback. */ } }
}
