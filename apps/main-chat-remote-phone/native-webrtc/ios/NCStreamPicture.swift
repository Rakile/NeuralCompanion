import UIKit
import WebRTC

/// Worker-only conversion for the negotiated handoff surface. NC's desktop
/// encodes limited-range BT.601, like the cached H.264 segments. No second
/// transfer-function conversion, new decoder, audio session or network path.
enum NCStreamPicture {
  static func image(_ frame:RTCVideoFrame)->CGImage? {
    guard !Thread.isMainThread,frame.rotation.rawValue == 0,
      (1...448).contains(Int(frame.width)),(1...672).contains(Int(frame.height)) else { return nil }
    let buffer=frame.buffer.toI420(),width=Int(buffer.width),height=Int(buffer.height)
    guard width==Int(frame.width),height==Int(frame.height),
      Int(buffer.strideY)>=width,Int(buffer.strideU)>=(width+1)/2,Int(buffer.strideV)>=(width+1)/2 else { return nil }
    var data=Data(count:width*height*4)
    data.withUnsafeMutableBytes { raw in
      let pixels=raw.bindMemory(to:UInt8.self)
      for y in 0..<height { for x in 0..<width {
        let luma=Int(buffer.dataY[y*Int(buffer.strideY)+x])-16
        let u=Int(buffer.dataU[(y/2)*Int(buffer.strideU)+x/2])-128
        let v=Int(buffer.dataV[(y/2)*Int(buffer.strideV)+x/2])-128
        let offset=(y*width+x)*4
        pixels[offset]=UInt8(clamping:(298*luma+516*u+128)>>8)
        pixels[offset+1]=UInt8(clamping:(298*luma-100*u-208*v+128)>>8)
        pixels[offset+2]=UInt8(clamping:(298*luma+409*v+128)>>8)
        pixels[offset+3]=255
      } }
    }
    guard let provider=CGDataProvider(data:data as CFData) else { return nil }
    return CGImage(width:width,height:height,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:width*4,
      space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:CGBitmapInfo(rawValue:
        CGBitmapInfo.byteOrder32Little.rawValue | CGImageAlphaInfo.premultipliedFirst.rawValue),
      provider:provider,decode:nil,shouldInterpolate:true,intent:.defaultIntent)
  }
}
