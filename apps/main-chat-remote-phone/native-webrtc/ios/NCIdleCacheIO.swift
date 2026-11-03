import Foundation
import CryptoKit

/// Disposable app-private video bytes. No AVAudioSession or playback authority.
final class NCIdleCacheIO {
  private let root: URL
  private let queue = DispatchQueue(label: "nc.idle.cache.io", qos: .utility)
  private let fm = FileManager.default
  private var closed = false
  private var owner = ""
  private var generation = ""
  private let limit = 128 * 1024 * 1024
  private final class Write {
    let generation: String, id: String, sha: String, file: URL, output: FileHandle
    let bytes: Int
    var offset = 0
    var digest = SHA256()
    init(generation:String,id:String,sha:String,file:URL,output:FileHandle,bytes:Int) {
      self.generation=generation; self.id=id; self.sha=sha; self.file=file; self.output=output; self.bytes=bytes
    }
  }
  private var writes: [String:Write] = [:]
  init(directory: URL) { root = directory.standardizedFileURL.resolvingSymlinksInPath() }
  private func error(_ reason:String) -> NSError {
    NSError(domain:"NCIdleCache", code:1, userInfo:[NSLocalizedDescriptionKey:reason])
  }
  private func io<T>(_ action:() throws -> T) throws -> T {
    try queue.sync { guard !closed else { throw error("Idle cache closed") }; return try action() }
  }
  private func hex(_ text:String) -> Bool { text.range(of:"^[a-f0-9]{64}$", options:.regularExpression) != nil }
  private func owned(_ name:String) -> Bool {
    name.range(of:"^(?:[a-f0-9]{64}\\.(?:mp4|meta)|[a-f0-9-]{36}\\.part|\\.owner|\\.meta-part)$",options:.regularExpression) != nil
  }
  private func file(_ name:String) throws -> URL {
    guard owned(name) else { throw error("Invalid idle file") }
    let target=root.appendingPathComponent(name)
    guard target.resolvingSymlinksInPath().path == target.path else { throw error("Unsafe idle file") }
    return target
  }
  private func live(_ value:String) throws {
    guard !value.isEmpty && value==generation else { throw error("Idle generation ended") }
  }
  private func entries() throws -> [URL] {
    guard fm.fileExists(atPath:root.path) else { return [] }
    return try fm.contentsOfDirectory(at:root,includingPropertiesForKeys:nil).filter { owned($0.lastPathComponent) }
  }
  private func size(_ url:URL) throws -> Int {
    let values=try fm.attributesOfItem(atPath:url.path)
    guard values[.type] as? FileAttributeType == .typeRegular, let count=values[.size] as? NSNumber else { throw error("Invalid idle file") }
    return count.intValue
  }
  private func used() throws -> Int {
    try entries().filter { $0.pathExtension=="mp4" || $0.pathExtension=="part" }.reduce(0) { total,url in
      total + (try size(file(url.lastPathComponent)))
    }
  }
  private func abortAll() {
    for write in writes.values { try? write.output.close(); try? fm.removeItem(at:write.file) }
    writes.removeAll()
  }
  private func ensureRoot() throws {
    guard root.resolvingSymlinksInPath().path == root.path else { throw error("Unsafe idle directory") }
    try fm.createDirectory(at:root,withIntermediateDirectories:true)
  }
  private func purge() throws {
    abortAll()
    for url in try entries() {
      let target=try file(url.lastPathComponent)
      _ = try size(target) // regular owned files only; never recurse into a directory
      try fm.removeItem(at:target)
    }
  }
  func select(scope:String,avatar:String) throws -> String {
    try io {
      guard !scope.isEmpty && scope.count<=1024 && hex(avatar) else { throw error("Invalid idle scope") }
      try ensureRoot()
      let key=SHA256.hash(data:Data((scope+"\u{0}"+avatar).utf8)).map { String(format:"%02x",$0) }.joined()
      if key != owner {
        abortAll()
        let marker=try file(".owner")
        let previous=(try? size(marker)) == 64 ? (try? String(contentsOf:marker,encoding:.utf8)) : nil
        if previous != key { try purge() }
        for url in try entries() where url.pathExtension=="part" || url.lastPathComponent==".meta-part" {
          try fm.removeItem(at:file(url.lastPathComponent))
        }
        try Data(key.utf8).write(to:marker,options:.atomic)
        owner=key; generation=UUID().uuidString.lowercased()
      }
      return generation
    }
  }
  func begin(generation value:String,id:String,bytes:Int,sha256:String) throws -> String {
    try io {
      try live(value)
      try ensureRoot()
      let marker=try file(".owner")
      if !fm.fileExists(atPath:marker.path) { try Data(owner.utf8).write(to:marker,options:.atomic) }
      guard hex(id), hex(sha256), (1...16*1024*1024).contains(bytes), writes.isEmpty else { throw error("Invalid idle entry or writer busy") }
      guard try used()+bytes<=limit else { throw error("Idle storage limited") }
      guard try !fm.fileExists(atPath:file(id+".mp4").path) else { throw error("Idle entry exists") }
      let handle=UUID().uuidString.lowercased(), temporary=try file(UUID().uuidString.lowercased()+".part")
      guard fm.createFile(atPath:temporary.path,contents:nil) else { throw error("Idle write unavailable") }
      let output=try FileHandle(forWritingTo:temporary)
      writes[handle]=Write(generation:value,id:id,sha:sha256,file:temporary,output:output,bytes:bytes)
      return handle
    }
  }
  func append(handle:String,offset:Int,chunk:Data) throws {
    try io {
      guard let write=writes[handle] else { throw error("Idle write ended") }
      try live(write.generation)
      guard (1...262144).contains(chunk.count), offset==write.offset, offset+chunk.count<=write.bytes else { throw error("Invalid idle chunk") }
      try write.output.write(contentsOf:chunk); write.digest.update(data:chunk); write.offset+=chunk.count
    }
  }
  private func result(_ value:String,_ id:String,_ bytes:Int,_ sha:String) throws -> [String:Any] {
    ["generation":value,"id":id,"bytes":bytes,"sha256":sha,"uri":try file(id+".mp4").absoluteString]
  }
  func finish(handle:String) throws -> [String:Any] {
    try io {
      guard let write=writes.removeValue(forKey:handle) else { throw error("Idle write ended") }
      defer { try? write.output.close(); try? fm.removeItem(at:write.file) }
      try live(write.generation); try write.output.synchronize(); try write.output.close()
      let sha=write.digest.finalize().map { String(format:"%02x",$0) }.joined()
      guard write.offset==write.bytes, sha==write.sha, try used()<=limit else { throw error("Idle integrity failure") }
      let target=try file(write.id+".mp4")
      try fm.moveItem(at:write.file,to:target)
      do { try Data("\(sha)\n\(write.bytes)".utf8).write(to:file(write.id+".meta"),options:.atomic) }
      catch { try? fm.removeItem(at:target); throw error }
      return try result(generation,write.id,write.bytes,sha)
    }
  }
  func get(generation value:String,id:String) throws -> [String:Any]? {
    try io {
      try live(value); guard hex(id) else { throw error("Invalid idle id") }
      let target=try file(id+".mp4"), meta=try file(id+".meta")
      do {
        guard try size(meta)<=100 else { throw error("Invalid idle metadata") }
        let parts=try String(contentsOf:meta,encoding:.utf8).components(separatedBy:"\n")
        guard parts.count==2, hex(parts[0]), let count=Int(parts[1]), (1...16*1024*1024).contains(count), try size(target)==count else { throw error("Invalid idle metadata") }
        let input=try FileHandle(forReadingFrom:target); defer { try? input.close() }
        var digest=SHA256()
        while let chunk=try input.read(upToCount:24576), !chunk.isEmpty { digest.update(data:chunk) }
        guard digest.finalize().map({String(format:"%02x",$0)}).joined()==parts[0] else { throw error("Idle integrity failure") }
        return try result(value,id,count,parts[0])
      } catch { try? fm.removeItem(at:target); try? fm.removeItem(at:meta); return nil }
    }
  }
  func abort(handle:String) throws {
    try io { if let write=writes.removeValue(forKey:handle) { try? write.output.close(); try? fm.removeItem(at:write.file) } }
  }
  func invalidate(generation value:String) throws {
    try io { try live(value); try purge(); generation=""; owner="" }
  }
  func usage() throws -> [String:Any] { try io { ["bytes":try used(),"limit":limit] } }
  func close() { queue.sync { abortAll(); closed=true } }
}
