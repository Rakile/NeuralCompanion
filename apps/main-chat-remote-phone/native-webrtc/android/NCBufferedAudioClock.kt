package expo.modules.audio

/** Main-thread read-only adapter for the existing file players. Owns neither
 * audio output nor permission, and cannot create start/completion receipts. */
internal class NCBufferedAudioClock(private val completed: (State)->Unit) {
  data class State(val key:Long,val samples:Int,val started:Boolean,val playing:Boolean,
    val completed:Boolean,val stopped:Boolean,val successor:Boolean)
  private data class Item(val binding:NCPlaybackBinding,val ticket:String,val request:String,val chunk:String,val samples:Int) {
    fun read()=binding.observePhoneReply(ticket,request,chunk)
  }
  private val items=sortedMapOf<Long,Item>()
  private var closed=false
  fun bind(key:Long,binding:NCPlaybackBinding,ticket:String,request:String,chunk:String,samples:Int):Boolean {
    if(closed||key !in 1..2147483647L||samples !in 1..28800000||items.containsKey(key)||items.size>=2
      ||items.values.any { it.binding===binding }||binding.observePhoneReply(ticket,request,chunk)==null)return false
    val item=Item(binding,ticket,request,chunk,samples);items[key]=item
    binding.setCompletionObserver {
      if(items[key]===item)sample(key)?.takeIf { it.completed&&!it.stopped }?.let(completed)
    }
    return true
  }
  fun sample(key:Long):State? {
    val item=items[key]?:return null
    val value=item.read()
    val successor=items.tailMap(key+1).values.any { it.ticket==item.ticket&&it.request==item.request&&it.read()!=null }
    if(value==null)return State(key,0,false,false,false,true,successor)
    val samples=if(value.completed)item.samples else ((value.positionSeconds?:0.0)*48000).toInt().coerceIn(0,item.samples)
    return State(key,samples,value.started,value.playing,value.completed,false,successor)
  }
  fun states()=items.keys.toList().mapNotNull { sample(it) }
  fun remove(key:Long) { items.remove(key)?.binding?.setCompletionObserver(null) }
  fun close() { closed=true;items.keys.toList().forEach(::remove) }
}
