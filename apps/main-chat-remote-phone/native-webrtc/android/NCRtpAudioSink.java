// NeuralCompanion, MIT. Decoder callback adapter; never a playback authority.
package expo.modules.audio;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import org.webrtc.AudioTrack;

/** Attach/detach on the WebRTC executor, never from onData. The SDK owns callback
 * PCM; NCPcmOutput copies only bounded, already admitted ranges before returning.
 * Default WebRTC output MUST be muted before peer creation independently of this
 * sink. Receiving a track or attaching this object cannot authorize sound.
 */
final class NCRtpAudioSink implements AudioTrack.RtpAudioSink {
  private final Object lock = new Object();
  private final long generation;
  private final ArrayList<NCPcmOutput> outputs = new ArrayList<>();
  private boolean closed;
  NCRtpAudioSink(long generation) {
    if (generation <= 0) throw new IllegalArgumentException("Invalid stream generation");
    this.generation = generation;
  }
  boolean add(long value, NCPcmOutput output) {
    synchronized (lock) {
      if (closed || value != generation || output == null || !output.belongsToGeneration(value)) return false;
      if (outputs.contains(output)) return true;
      if (outputs.size() >= 2) return false;
      outputs.add(output); return true;
    }
  }
  void remove(NCPcmOutput output) {
    boolean removed;
    synchronized (lock) { removed = outputs.remove(output); }
    if (removed) output.stop();
  }
  void stop() {
    ArrayList<NCPcmOutput> previous;
    synchronized (lock) {
      if (closed) return;
      closed = true; previous = new ArrayList<>(outputs); outputs.clear();
    }
    for (NCPcmOutput output : previous) output.stop();
  }
  @Override public void onData(ByteBuffer pcm, int bits, int rate, int channels,
      int frames, long timestamp, int clockRate, boolean valid, boolean concealed) {
    ArrayList<NCPcmOutput> current;
    synchronized (lock) { if (closed) return; current = new ArrayList<>(outputs); }
    for (NCPcmOutput output : current)
      output.offer(pcm, bits, rate, channels, frames, timestamp, clockRate, valid, concealed);
  }
}
