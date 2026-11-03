package expo.modules.nclivecapture

import com.facebook.react.bridge.Arguments
import com.facebook.react.bridge.ReactContext
import com.facebook.react.bridge.UiThreadUtil
import com.facebook.react.jstasks.HeadlessJsTaskConfig
import com.facebook.react.jstasks.HeadlessJsTaskContext
import java.util.concurrent.CompletableFuture

/** Keeps RN's existing timer/network pipeline scheduled, not a second player.
 * Only the confirmed playback service may own this lease. It grants no output,
 * capture or reply authority, and never starts a new React instance. */
class PlaybackJsWork(private val context:ReactContext) {
  private class Work(val ticket:String,val generation:Long) {
    var taskId:Int?=null
    val ended=CompletableFuture<Boolean>()
  }
  private var active:Work?=null
  private val settling=mutableSetOf<Int>()

  @Synchronized fun start(ticket:String,generation:Long) {
    UiThreadUtil.assertOnUiThread()
    check(context.hasActiveReactInstance()){ "playback_js_instance_unavailable" }
    active?.let {
      check(it.ticket==ticket && it.generation==generation){"playback_js_owner_active"}
      return
    }
    val work=Work(ticket,generation);active=work
    val data=Arguments.createMap().apply{putString("ticket",ticket);putDouble("generation",generation.toDouble())}
    try {
      work.taskId=HeadlessJsTaskContext.getInstance(context).startTask(
        HeadlessJsTaskConfig("NCOrderedPlayback",data,0,true))
    } catch(error:Throwable) {active=null;work.ended.complete(true);throw error}
  }

  @Synchronized fun awaitEnd(ticket:String,generation:Long):CompletableFuture<Boolean> =
    active?.takeIf{it.ticket==ticket && it.generation==generation}?.ended
      ?: CompletableFuture.completedFuture(true)

  @Synchronized fun running(ticket:String,generation:Long):Boolean =
    active?.takeIf{it.ticket==ticket && it.generation==generation}?.taskId
      ?.let{HeadlessJsTaskContext.getInstance(context).isTaskRunning(it)}==true

  @Synchronized fun stop(ticket:String,generation:Long) {
    val work=active?.takeIf{it.ticket==ticket && it.generation==generation} ?: return
    active=null
    work.taskId?.let { id ->
      settling.add(id)
      // Normally the resolved task notifies RN immediately. Native fallback
      // bounds cleanup even if JS is blocked or destroyed; IDs are never reused.
      UiThreadUtil.runOnUiThread(Runnable{synchronized(this){finish(id)}},1000)
    }
    work.ended.complete(true)
  }

  private fun finish(id:Int) {
    settling.remove(id)
    HeadlessJsTaskContext.getInstance(context).let{if(it.isTaskRunning(id))it.finishTask(id)}
  }

  @Synchronized fun destroy() {
    active?.let{stop(it.ticket,it.generation)}
    settling.toList().forEach{finish(it)}
  }
}
