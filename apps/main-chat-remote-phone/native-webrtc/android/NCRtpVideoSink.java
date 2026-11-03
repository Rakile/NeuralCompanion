// NeuralCompanion, MIT. SDK renderer bridge; audio remains the only master clock.
package expo.modules.audio;

import java.util.ArrayDeque;
import org.webrtc.VideoFrame;
import org.webrtc.VideoSink;

/** Bounded frame ownership between decoder and the native SurfaceViewRenderer.
 * Attach/detach on WebRTC's executor. Stop/hide permanently fences this instance;
 * a resumed view needs a newly admitted window/keyframe. No audio receipt API.
 */
final class NCRtpVideoSink implements VideoSink {
  private final Object lock = new Object();
  private final long generation;
  private final NCVideoWindow window;
  private final VideoSink renderer;
  private final Runnable clear;
  private final ArrayDeque<VideoFrame> pending = new ArrayDeque<>();
  // 24fps needs 12 frames to cover the output's bounded 500ms PCM backlog.
  // Four more cover callback jitter. Two frames can starve a delayed speaker.
  private static final int MAX_PENDING_FRAMES = 16;
  private boolean closed;
  NCRtpVideoSink(long generation, long first, int samples, boolean idle, VideoSink renderer, Runnable clear) {
    this.generation = generation; this.renderer = renderer; this.clear = clear;
    window = new NCVideoWindow(generation, first, samples, idle);
  }
  boolean admit(long value) { synchronized (lock) { return !closed && window.admit(value); } }
  void played(long value, int count) {
    synchronized (lock) {
      window.played(value, count);
      try { flush(); } catch (RuntimeException error) { stop(); }
    }
  }
  @Override public void onFrame(VideoFrame frame) {
    synchronized (lock) {
      if (closed || !frame.hasRtpTimestamp() || frame.getBuffer().getWidth() <= 0 || frame.getBuffer().getWidth() > 448
          || frame.getBuffer().getHeight() <= 0 || frame.getBuffer().getHeight() > 672) return;
      try {
        flush();
        if (closed) return;
        NCVideoWindow.Decision decision = window.frame(generation, frame.getRtpTimestamp());
        if (decision == NCVideoWindow.Decision.SHOW) renderer.onFrame(frame);
        else if (decision == NCVideoWindow.Decision.WAIT) {
          for (VideoFrame queued : pending) if (queued.getRtpTimestamp() == frame.getRtpTimestamp()) return;
          if (pending.size() == MAX_PENDING_FRAMES) pending.removeFirst().release();
          frame.retain(); pending.addLast(frame);
        }
      } catch (RuntimeException error) { stop(); }
    }
  }
  private void flush() {
    int count = pending.size();
    for (int i = 0; i < count && !closed; ++i) {
      VideoFrame frame = pending.removeFirst();
      boolean retained = false;
      try {
        NCVideoWindow.Decision decision = window.frame(generation, frame.getRtpTimestamp());
        if (decision == NCVideoWindow.Decision.SHOW) renderer.onFrame(frame);
        else if (decision == NCVideoWindow.Decision.WAIT) { pending.addLast(frame); retained = true; }
      } finally { if (!retained) frame.release(); }
    }
  }
  void stop() {
    synchronized (lock) {
      if (closed) return;
      closed = true; window.stop();
      while (!pending.isEmpty()) pending.removeFirst().release();
      // SurfaceViewRenderer.clearImage enqueues after earlier onFrame work. No
      // later frame can enter it through this closed generation.
      try { clear.run(); } catch (RuntimeException ignored) { /* Remains terminal. */ }
    }
  }
}
