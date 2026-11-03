package expo.modules.audio

/** Immutable in-memory diagnostic selection, never playback authority. */
internal class NCDiagnosticPolicy {
  private val levels=ncPolicyContract["levels"] as List<*>
  private val categories=ncPolicyContract["categories"] as List<*>
  private val prefixes=(ncPolicySites["prefixes"] as List<*>).map {it as List<*>}
  private val failures=Regex("(?:^|[._])(reject(?:ed|ion)?|fail(?:ed|ure)?|error|overflow|unavailable)(?:$|[._])")
  private val mandatoryPrefixes=ncPolicySites["mandatory_prefixes"] as List<*>
  @Suppress("UNCHECKED_CAST")
  @Volatile private var selected=ncPolicyContract["default"] as Map<String,Any?>
  @Synchronized fun applyPolicy(raw:Map<*,*>):String {
    require(raw.keys==setOf("version","revision","default_level","categories"))
    require(raw["version"] is Number && (raw["version"] as Number).toDouble()==1.0)
    val revision=raw["revision"] as? String
    require(revision!=null && Regex(ncPolicyContract["revision_pattern"] as String).matches(revision))
    require(raw["default_level"] in levels)
    val overrides=raw["categories"] as? Map<*,*>;require(overrides!=null)
    require(overrides.all {(k,v)->k in categories && v in levels})
    val copy=mapOf<String,Any?>("version" to 1L,"revision" to revision,"default_level" to raw["default_level"],"categories" to overrides.toMap())
    require(revision!=selected["revision"] || copy==selected) {"diagnostic_policy_revision_conflict"}
    selected=copy;return revision
  }
  fun snapshot():Map<String,Any?> {val p=selected;return p+mapOf("categories" to (p["categories"] as Map<*,*>).toMap())}
  fun enabled(category:String,verbosity:String="trace",mandatory:Boolean=false):Boolean {
    if(mandatory)return true
    val p=selected;val c=if(category in categories)category else "uncategorized"
    val level=(p["categories"] as Map<*,*>)[c]?:p["default_level"]
    return level!="off" && levels.indexOf(verbosity)>0 && levels.indexOf(level)>=levels.indexOf(verbosity)
  }
  fun siteEnabled(site:String,level:String="debug",outcome:String="observed",data:Map<*,*> = emptyMap<String,Any?>()):Boolean {
    val mandatory=site.startsWith("native.playback.") || level=="warning" || level=="error" || outcome=="failed" || outcome=="rejected" ||
      data["begin_recorded"]==true ||
      failures.containsMatchIn(site) || mandatoryPrefixes.any {site.startsWith(it as String)} ||
      data["failure_kind"]!=null || data["state_after"]=="failed" || data["state_after"]=="rejected" ||
      (data["expected"]!=null && data.containsKey("actual") && data["expected"]!=data["actual"] &&
        data["condition"] !in (ncPolicySites["nonfailure_conditions"] as List<*>))
    val row=prefixes.firstOrNull {site.startsWith(it[0] as String)}
    return enabled(row?.get(1) as? String?:"uncategorized",row?.get(2) as? String?:"trace",mandatory)
  }
}
internal val ncDiagnosticPolicy=NCDiagnosticPolicy()
