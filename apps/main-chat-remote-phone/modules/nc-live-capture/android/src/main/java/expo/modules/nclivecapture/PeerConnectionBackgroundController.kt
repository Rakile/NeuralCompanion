package expo.modules.nclivecapture

import android.content.Context
import android.os.Handler
import android.os.Looper
import java.util.concurrent.CompletableFuture

/** Main-thread owner for an explicitly requested desktop connection.
 * It owns no audio player, microphone, or conversation authority. */
class PeerConnectionBackgroundController(
  private val context:Context,
  private val visible:()->Boolean,
  private val stopped:(String)->Unit,
) : LiveAudioService.Controller {
  private val handler=Handler(Looper.getMainLooper())
  private var ticket:String?=null
  private var pending:CompletableFuture<Boolean>?=null
  private var timeout:Runnable?=null

  fun begin(next:String):CompletableFuture<Boolean> {
    if(ticket==next)return pending?:CompletableFuture.completedFuture(true)
    if(!visible())return CompletableFuture.completedFuture(false)
    ticket?.let(::end)
    val result=CompletableFuture<Boolean>()
    ticket=next;pending=result
    timeout=Runnable{if(ticket==next)end(next)}.also{handler.postDelayed(it,10000)}
    try {LiveAudioService.startConnection(context,this,next)}
    catch(error:Throwable){result.completeExceptionally(error);end(next)}
    return result
  }

  fun end(expected:String) {
    if(ticket!=expected)return
    ticket=null
    timeout?.let(handler::removeCallbacks);timeout=null
    val result=pending;pending=null
    LiveAudioService.stop(context,this)
    result?.complete(false)
  }
  fun destroy(){ticket?.let(::end)}
  override fun serviceStarted(ticket:String?,generation:Long) {
    if(ticket==null||this.ticket!=ticket)return
    timeout?.let(handler::removeCallbacks);timeout=null
    val result=pending;pending=null;result?.complete(true)
  }
  override fun stopConversation() {
    val current=ticket?:return
    end(current);stopped(current)
  }
  override fun serviceDestroyed()=stopConversation()
  override fun authorizationExpired()=stopConversation()
  override fun serviceStartFailed(ticket:String?,generation:Long){if(ticket!=null)end(ticket)}
  override fun safetyTick() {}
}
