package expo.modules.nclivecapture

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CompletableFuture

/** Ordinary-output policy using the same service/registration fence as Live.
 * No capture driver, microphone lease, reply admission or lifetime renewal. */
class PlaybackBackgroundController(
  private val context:Context,
  private val foreground:()->Boolean,
  private val unlocked:()->Boolean,
  private val resolve:(String,String)->Owner?,
  private val work:PlaybackJsWork,
  private val diagnostic:(String)->Unit = {}
) {
  interface Owner {
    fun current():Boolean
    fun confirm():Boolean
    fun ready():Boolean
    fun pauseForLock()
    fun resumeForeground()
    fun release()
    fun retire()
  }
  private val handler=Handler(Looper.getMainLooper())
  private var active:Session?=null
  private fun note(reason:String){try{diagnostic(reason)}catch(_:Throwable){/* Diagnostics confer no lifecycle authority. */}}
  private inner class Session(val ticket:String,val playerId:String,val owner:Owner):LiveAudioService.Controller {
    var generation:Long?=null
    var confirmed=false
    val result=CompletableFuture<Map<String,Any?>>()
    val timeout=Runnable { synchronized(this@PlaybackBackgroundController) {
      if(active===this && !confirmed)finish(this,"service_confirmation_timeout",false)
    } }
    override fun serviceStarted(ticket:String?,generation:Long)=synchronized(this@PlaybackBackgroundController) {
      if(active!==this||this.ticket!=ticket)return@synchronized
      if(!confirmed) {
        if(!foreground()||!unlocked()||!owner.confirm()) {
          finish(this,"service_confirmation_owner_unavailable",false);return@synchronized
        }
        this.generation=generation
        try{work.start(ticket!!,generation)}catch(_:Throwable){
          finish(this,"background_work_start_failed",false);return@synchronized
        }
        confirmed=true;handler.removeCallbacks(timeout)
        note("service_confirmed");result.complete(state())
      }
    }
    override fun stopConversation()=synchronized(this@PlaybackBackgroundController){finish(this,"notification_stop",true)}
    override fun authorizationExpired()=synchronized(this@PlaybackBackgroundController){finish(this,"service_expired",true)}
    override fun serviceDestroyed()=synchronized(this@PlaybackBackgroundController){finish(this,"service_destroyed",confirmed)}
    override fun serviceStartFailed(ticket:String?,generation:Long)=synchronized(this@PlaybackBackgroundController){
      if(this.ticket==ticket&&(this.generation==null||this.generation==generation))finish(this,"service_start_failed",confirmed)
    }
    override fun safetyTick()=synchronized(this@PlaybackBackgroundController){
      if(active!==this)return@synchronized
      if(!owner.current())finish(this,"output_owner_ended",false)
      else if(confirmed && !work.running(ticket,generation!!))finish(this,"background_work_ended",true)
      else if(!unlocked())owner.pauseForLock()
      // Activity resume can precede keyguard dismissal. Reconcile on the
      // existing service tick; the owner resumes only its own lock pause.
      else if(confirmed&&foreground())owner.resumeForeground()
    }
  }
  @Synchronized fun begin(ticket:String,playerId:String):CompletableFuture<Map<String,Any?>> {
    active?.let {
      return if(it.ticket==ticket&&it.playerId==playerId)it.result
      else CompletableFuture.completedFuture(rejected("background_service_owner_active"))
    }
    if(!foreground()||!unlocked())return CompletableFuture.completedFuture(rejected("foreground_required"))
    val owner=resolve(ticket,playerId) ?: return CompletableFuture.completedFuture(rejected("ordered_player_required"))
    val session=Session(ticket,playerId,owner);active=session
    note("service_requested")
    handler.postDelayed(session.timeout,5000)
    try{LiveAudioService.startPlayback(context,session,ticket)}
    catch(_:Throwable){finish(session,"service_start_rejected",false)}
    return session.result
  }
  @Synchronized fun state():Map<String,Any?> {
    val session=active
    return mapOf("ticket" to session?.ticket,"playerId" to session?.playerId,
      "generation" to session?.generation,"ready" to (session?.let{it.confirmed&&it.owner.ready()}==true),"reason" to null)
  }
  @Synchronized fun end(ticket:String,generation:Long) {
    active?.takeIf{it.ticket==ticket&&it.generation==generation}?.let{finish(it,"service_released",false)}
  }
  @Synchronized fun locked(){active?.owner?.pauseForLock()}
  @Synchronized fun foregrounded(){if(foreground()&&unlocked())active?.owner?.resumeForeground()}
  @Synchronized fun destroy(){active?.let{finish(it,"module_destroyed",it.confirmed)}}
  private fun rejected(reason:String):Map<String,Any?> = mapOf("ready" to false,"generation" to null,"reason" to reason)
  private fun finish(session:Session,reason:String,retire:Boolean) {
    if(active!==session)return
    active=null;handler.removeCallbacks(session.timeout)
    session.generation?.let{work.stop(session.ticket,it)}
    if(retire)session.owner.retire()
    session.owner.release();LiveAudioService.stop(context,session)
    note(reason);session.result.complete(rejected(reason))
  }
}
