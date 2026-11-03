import Foundation

/// Main-thread observations of the already guarded Expo file players. This
/// adapter owns no audio device, permission, or playback acknowledgement.
final class NCBufferedAudioClock {
  struct State {
    let key:UInt64,samples:Int,started:Bool,playing:Bool,completed:Bool,stopped:Bool,successor:Bool
  }
  private final class Item {
    let binding:NCPlaybackBinding,ticket:String,request:String,chunk:String,samples:Int
    init(_ binding:NCPlaybackBinding,_ ticket:String,_ request:String,_ chunk:String,_ samples:Int) {
      self.binding=binding;self.ticket=ticket;self.request=request;self.chunk=chunk;self.samples=samples
    }
    func read()->NCPlaybackObservation? { binding.observePhoneReply(ticket:ticket,requestId:request,chunkId:chunk) }
  }
  private var items:[UInt64:Item]=[:]
  private var closed=false
  private let completed:(State)->Void
  init(_ completed:@escaping (State)->Void) { self.completed=completed }
  func bind(_ key:UInt64,binding:NCPlaybackBinding,ticket:String,request:String,chunk:String,samples:Int)->Bool {
    guard !closed,(1...2147483647).contains(key),(1...28800000).contains(samples),items[key]==nil,items.count<2,
      !items.values.contains(where:{$0.binding === binding}),binding.observePhoneReply(ticket:ticket,requestId:request,chunkId:chunk) != nil else { return false }
    let item=Item(binding,ticket,request,chunk,samples);items[key]=item
    binding.setCompletionObserver { [weak self,weak item] in
      guard let self,let item,self.items[key] === item,let value=self.sample(key),value.completed && !value.stopped else { return }
      self.completed(value)
    }
    return true
  }
  func sample(_ key:UInt64)->State? {
    guard let item=items[key] else { return nil }
    let successor=items.contains { $0.key>key && $0.value.ticket==item.ticket && $0.value.request==item.request && $0.value.read() != nil }
    guard let value=item.read() else { return State(key:key,samples:0,started:false,playing:false,completed:false,stopped:true,successor:successor) }
    let samples=value.completed ? item.samples : Int(min(Double(item.samples),max(0,(value.positionSeconds ?? 0)*48000)))
    return State(key:key,samples:samples,started:value.started,playing:value.playing,completed:value.completed,stopped:false,successor:successor)
  }
  var states:[State] { items.keys.sorted().compactMap { sample($0) } }
  func remove(_ key:UInt64) { items.removeValue(forKey:key)?.binding.setCompletionObserver(nil) }
  func close() { closed=true;Array(items.keys).forEach { remove($0) } }
}
