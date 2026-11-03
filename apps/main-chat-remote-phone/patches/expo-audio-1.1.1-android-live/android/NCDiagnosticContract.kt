package expo.modules.audio

import java.time.Instant
import java.time.format.DateTimeFormatterBuilder
import java.util.IdentityHashMap

/** Pinned v1 schema interpreter, not a general JSON Schema implementation. */
internal object NCDiagnosticContract {
  private val privateText=Regex("Bearer\\s|(?:password|token|secret|authorization|code|api_key)\\s*[=:]|[A-Za-z]:[\\\\/]|file://",RegexOption.IGNORE_CASE)
  fun snapshot(value:Any?,depth:Int=0,seen:IdentityHashMap<Any,Boolean> = IdentityHashMap()):Any? {
    require(depth<=12)
    return when(value){
      null,is Boolean->value
      is String->{require(!value.startsWith("/")&&!privateText.containsMatchIn(value)&&value.none {it.code<32});value}
      is Byte,is Short,is Int,is Long,is Float,is Double->{require((value as Number).toDouble().isFinite());value}
      is Map<*,*>->{require(seen.put(value,true)==null);try{value.entries.associate {require(it.key is String);it.key as String to snapshot(it.value,depth+1,seen)}}finally{seen.remove(value)}}
      is List<*>->{require(seen.put(value,true)==null);try{value.map {snapshot(it,depth+1,seen)}}finally{seen.remove(value)}}
      else->throw IllegalArgumentException()
    }
  }
  fun json(value:Any?):String=when(value){
    null->"null"
    is String->"\""+buildString {value.forEach {c->when(c){'"'->append("\\\"");'\\'->append("\\\\");else->if(c.code<32)append("\\u%04x".format(c.code))else append(c)}}}+"\""
    is Number,is Boolean->value.toString()
    is Map<*,*>->value.entries.joinToString(",","{","}"){json(it.key)+":"+json(it.value)}
    is List<*>->value.joinToString(",","[","]"){json(it)}
    else->throw IllegalArgumentException()
  }
  @Suppress("UNCHECKED_CAST")
  fun validate(value:Map<String,Any?>):List<Map<String,String>> = try {
    snapshot(value)
    if(json(value).toByteArray(Charsets.UTF_8).size>16384)listOf(mapOf("path" to "$","rule" to "size"))
    else {
      val issues=mutableListOf<Map<String,String>>()
      walk(value,ncDiagnosticSchema,"$",issues)
      if(issues.isEmpty()){
        if(value["event_id"]!="${value["producer_id"]}:${(value["sequence"] as Number).toLong()}")issues.add(mapOf("path" to "$.event_id","rule" to "identity"))
        val data=value["data"] as Map<String,Any?>
        if(value["phase"]=="wait"&&(data["deadline_ms"] as Number).toDouble()<(data["wait_started_ms"] as Number).toDouble())issues.add(mapOf("path" to "$.data.deadline_ms","rule" to "deadline"))
        if((value["links"] as List<Map<String,Any?>>).any {it["event_id"]==null&&it["operation_id"]==null})issues.add(mapOf("path" to "$.links","rule" to "target"))
      };issues
    }
  }catch(_:Exception){listOf(mapOf("path" to "$","rule" to "unsafe_or_non_json"))}

  @Suppress("UNCHECKED_CAST")
  private fun walk(v:Any?,s:Map<String,Any?>,path:String,issues:MutableList<Map<String,String>>){
    fun bad(rule:String){if(issues.size<32)issues.add(mapOf("path" to path,"rule" to rule))}
    fun equal(a:Any?,b:Any?)=if(a is Number&&b is Number)a.toDouble()==b.toDouble() else a==b
    val choices=s["anyOf"] as? List<Map<String,Any?>>
    if(choices!=null&&!choices.any {val next=mutableListOf<Map<String,String>>();walk(v,it,path,next);next.isEmpty()}){bad("anyOf");return}
    val valid=when(s["type"]){
      "object"->v is Map<*,*>;"array"->v is List<*>;"string"->v is String;"null"->v==null;"boolean"->v is Boolean
      "number"->v is Number&&v.toDouble().isFinite();"integer"->v is Number&&v.toDouble().isFinite()&&v.toDouble()%1.0==0.0
      else->true
    }
    if(!valid){bad("type");return}
    if(s.containsKey("const")&&!equal(v,s["const"]))bad("const")
    (s["enum"] as? List<*>)?.let {if(it.none {x->equal(v,x)})bad("enum")}
    if(v is Number && (v.toDouble()<(s["minimum"] as? Number)?.toDouble()?:Double.NEGATIVE_INFINITY || v.toDouble()>(s["maximum"] as? Number)?.toDouble()?:Double.POSITIVE_INFINITY))bad("range")
    if(v is String){
      val size=v.codePointCount(0,v.length)
      if(size<((s["minLength"] as? Number)?.toInt()?:0)||size>((s["maxLength"] as? Number)?.toInt()?:100000))bad("length")
      (s["pattern"] as? String)?.let {if(!Regex(it).containsMatchIn(v))bad("pattern")}
      if(s["format"]=="date-time")try{
        if(DateTimeFormatterBuilder().appendInstant(3).toFormatter().format(Instant.parse(v))!=v)bad("format")
      }catch(_:Exception){bad("format")}
    }
    if(v is Map<*,*>){
      (s["required"] as? List<String>)?.forEach {if(!v.containsKey(it))bad("required.$it")}
      val properties=s["properties"] as? Map<String,Map<String,Any?>>?:emptyMap()
      v.forEach {(k,child)->if(properties.containsKey(k))walk(child,properties[k]!!,"$path.$k",issues)else if(s["additionalProperties"]==false)bad("unknown_field")}
    }
    if(v is List<*>){
      if(v.size<((s["minItems"] as? Number)?.toInt()?:0)||v.size>((s["maxItems"] as? Number)?.toInt()?:100000))bad("items")
      (s["items"] as? Map<String,Any?>)?.let {child->v.forEachIndexed {i,x->walk(x,child,"$path[$i]",issues)}}
    }
    (s["allOf"] as? List<Map<String,Any?>>)?.forEach {walk(v,it,path,issues)}
    (s["if"] as? Map<String,Any?>)?.let {val next=mutableListOf<Map<String,String>>();walk(v,it,path,next);if(next.isEmpty())walk(v,s["then"] as Map<String,Any?>,path,issues)}
  }
}
