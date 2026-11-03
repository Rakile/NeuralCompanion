package expo.modules.nclivecapture

/** One Android service, independently fenced native roles. No callbacks
 * run under this monitor; callers revalidate snapshots before delivering them. */
class ServiceOwnerRegistry<C:Any> {
  enum class Role { MICROPHONE, PLAYBACK, REPLY, SOUNDSCAPE, CONNECTION }
  data class Registration<C:Any>(val role:Role,val generation:Long,val controller:C,val ticket:String?,val action:String)
  private val owners=linkedMapOf<Role,Registration<C>>()
  private var nextGeneration=0L
  var revision=0L
    private set
  @Synchronized fun register(role:Role,controller:C,ticket:String?,action:String):Registration<C> {
    // Keep the original MIC/ordered PLAYBACK pairing; auxiliary activity
    // reasons cannot replace, authorize, or renew either of those roles.
    check(role !in setOf(Role.MICROPHONE,Role.PLAYBACK) ||
      owners.values.filter{it.role in setOf(Role.MICROPHONE,Role.PLAYBACK)}.all{it.ticket==ticket}) {"background_service_output_mismatch"}
    owners[role]?.let {
      check(it.controller===controller&&it.ticket==ticket){"background_service_role_owned"}
      return update(it,action)!!
    }
    return Registration(role,++nextGeneration,controller,ticket,action).also{owners[role]=it;revision++}
  }
  @Synchronized fun current(r:Registration<C>)=owners[r.role]?.let {
    it.generation==r.generation&&it.controller===r.controller&&it.ticket==r.ticket
  }==true
  @Synchronized fun update(r:Registration<C>,action:String):Registration<C>? {
    if(!current(r))return null
    val existing=owners.getValue(r.role)
    if(existing.action==action)return existing
    return existing.copy(action=action).also{owners[r.role]=it;revision++}
  }
  @Synchronized fun remove(r:Registration<C>):Boolean {
    if(!current(r))return false
    owners.remove(r.role);revision++;return true
  }
  @Synchronized fun snapshot()=owners.values.toList()
  @Synchronized fun forController(c:C)=owners.values.singleOrNull{it.controller===c}
}
