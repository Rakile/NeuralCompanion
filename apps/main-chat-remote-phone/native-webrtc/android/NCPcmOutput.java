// NeuralCompanion, MIT. Candidate only; not enrolled in the phone module.
package expo.modules.audio;

import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayDeque;

/** Bounded native PCM queue. start/stop are called by the EXISTING playback
 * guard. All writes must be nonblocking; only the OS head advances receipts.
 * No network, session/focus acquisition, permission or automatic resume policy.
 */
final class NCPcmOutput implements AutoCloseable {
  interface Device {
    boolean prepare();
    void play();
    boolean isPlaying();
    void stop(); // Pause + flush; never drain queued sound on cancellation.
    int write(short[] pcm, int offset, int count); // Frames, nonblocking.
    default void finishInput() {} // Every valid source sample has been written.
    long playbackHead(); // Unsigned 32-bit OS frame counter.
    // Liveness only: a shared device may still be playing the preceding lease.
    // NEVER use this counter for this chunk's playback receipts.
    default long streamProgress() { return playbackHead(); }
    default String failureReason() { return ""; }
    default void stopWithFailureReason(String reason) { stop(); }
    void setVolume(float volume);
    void close();
  }
  private static final class Write {
    final long token;
    final short[] pcm;
    int offset;
    Write(long token, short[] pcm) { this.token = token; this.pcm = pcm; }
  }
  private static final class Pending {
    final long token, end;
    final float[] sample;
    Pending(long token, long end, short[] pcm) {
      this.token = token; this.end = end;
      int count = Math.min(64, pcm.length);
      sample = new float[count];
      for (int i = 0; i < count; ++i)
        sample[i] = pcm[count == 1 ? 0 : i * (pcm.length - 1) / (count - 1)] / 32768.0f;
    }
  }
  private final Object lock = new Object();
  private final Device device;
  private final NCPcmWindow window;
  private final long generation;
  private final ArrayDeque<Write> writes = new ArrayDeque<>();
  private final ArrayDeque<Pending> pending = new ArrayDeque<>();
  private boolean prepared, started, terminal, failed, closed, dirty;
  private String failureReason = "";
  private long failureAtMs;
  private long written, played, lastHead, lastStreamProgress, lastProgress;
  private Thread worker;
  private volatile Runnable changed;
  private float[] latestSample;

  NCPcmOutput(Device device, long generation, long firstSample, int samples) {
    this.device = device; this.generation = generation;
    window = new NCPcmWindow(generation, firstSample, samples);
  }
  boolean prepare() {
    synchronized (lock) { if (terminal || prepared) return prepared && !terminal; }
    boolean ready;
    try { ready = device.prepare(); } catch (RuntimeException error) { ready = false; }
    synchronized (lock) {
      if (!ready || terminal) { if (!ready) failLocked("device_prepare_failed"); else stopLocked(); return false; }
      prepared = true; return true;
    }
  }
  boolean belongsToGeneration(long value) { return generation == value; }
  boolean start() {
    synchronized (lock) {
      if (terminal || !prepared) return false;
      if (started) return device.isPlaying();
      if (!window.admit(generation)) return false;
      try {
        lastHead = device.playbackHead();
        lastStreamProgress = device.streamProgress();
        if (lastHead < 0 || lastHead > 0xffffffffL) { failLocked("device_invalidated"); return false; }
        device.play();
        if (!device.isPlaying() || terminal) { failLocked("device_stopped"); return false; }
      } catch (RuntimeException error) { failLocked("device_invalidated"); return false; }
      started = true; lastProgress = System.nanoTime();
      worker = new Thread(this::run, "nc-pcm-output"); worker.setDaemon(true); worker.start();
      return true;
    }
  }
  void offer(ByteBuffer pcm, int bits, int rate, int channels, int frames,
             long timestamp, int clockRate, boolean valid, boolean concealed) {
    synchronized (lock) {
      if (!started || terminal) return;
      if (pcm == null || bits != 16 || rate != 48000 || clockRate != 48000 || channels != 1
          || frames <= 0 || frames > 960 || pcm.remaining() < frames * 2) { failLocked("invalid_pcm_format"); return; }
      NCPcmWindow.Slice slice = window.reserve(generation, timestamp, frames, valid, concealed);
      if (window.failed()) { failLocked(window.failureReason()); return; }
      if (slice != null) {
        short[] copy = new short[slice.frames];
        ByteBuffer view = pcm.duplicate().order(ByteOrder.nativeOrder());
        view.position(view.position() + slice.skip * 2);
        view.asShortBuffer().get(copy);
        writes.add(new Write(slice.token, copy)); lock.notifyAll();
      }
    }
  }
  private void pumpLocked() {
    while (!writes.isEmpty() && !terminal) {
      Write item = writes.peek();
      int count = device.write(item.pcm, item.offset, item.pcm.length - item.offset);
      if (count < 0 || count > item.pcm.length - item.offset) { failLocked("device_invalidated"); return; }
      if (count == 0) break;
      item.offset += count; written += count;
      if (item.offset == item.pcm.length) { writes.remove(); pending.add(new Pending(item.token, written, item.pcm)); }
    }
    if (writes.isEmpty() && window.inputComplete()) device.finishInput();
    long head = device.playbackHead();
    if (head < 0 || head > 0xffffffffL) { failLocked("device_invalidated"); return; }
    long delta = (head - lastHead) & 0xffffffffL;
    if (delta > written - played) { failLocked("device_invalidated"); return; } // Reset/route change, not wrap progress.
    played += delta; lastHead = head;
    long streamProgress = device.streamProgress();
    if (delta > 0 || streamProgress != lastStreamProgress) lastProgress = System.nanoTime();
    lastStreamProgress = streamProgress;
    while (!pending.isEmpty() && pending.peek().end <= played) {
      Pending item = pending.remove();
      if (window.played(generation, item.token)) { dirty = true; latestSample = item.sample; }
    }
    // A stalled device/absent final packet is a bounded failure, NEVER success.
    if (!window.drained() && System.nanoTime() - lastProgress > 15_000_000_000L) failLocked("media_stall");
  }
  private void run() {
    while (true) {
      boolean finished, notify;
      synchronized (lock) {
        if (!terminal) {
          try { pumpLocked(); } catch (RuntimeException error) { failLocked(); }
        }
        finished = terminal || window.drained(); notify = dirty; dirty = false;
      }
      Runnable callback = changed;
      if (notify && callback != null) {
        try { callback.run(); }
        catch (RuntimeException error) { synchronized (lock) { failLocked(); } return; }
      }
      if (finished) return;
      synchronized (lock) {
        if (!terminal) try { lock.wait(10); } catch (InterruptedException error) { failLocked(); return; }
      }
    }
  }
  void stop() { synchronized (lock) { stopLocked(); } }
  private void stopLocked() {
    if (terminal) return;
    terminal = true; window.stop(); writes.clear(); pending.clear(); dirty = true;
    latestSample = null;
    try {
      if (failureReason.isEmpty()) device.stop();
      else device.stopWithFailureReason(failureReason);
    } catch (RuntimeException error) { failed = true; }
    lock.notifyAll();
  }
  private void failLocked() { failLocked("device_invalidated"); }
  private void failLocked(String reason) {
    if (terminal) return;
    String sharedReason = device.failureReason();
    if (!failed) { failureReason = sharedReason.isEmpty() ? reason : sharedReason; failureAtMs = System.currentTimeMillis(); }
    failed = true; stopLocked();
  }
  int confirmedSamples() { synchronized (lock) { return window.confirmedSamples(); } }
  // Visualization only. A receipt still comes exclusively from the guard/OS head.
  float[] latestSample() { synchronized (lock) { return latestSample == null ? null : latestSample.clone(); } }
  boolean drained() { synchronized (lock) { return window.drained(); } }
  boolean failed() { synchronized (lock) { return failed; } }
  String failureReason() { synchronized (lock) { return failureReason; } }
  long failureAtMs() { synchronized (lock) { return failureAtMs; } }
  boolean isPlaying() { synchronized (lock) { return started && !terminal && device.isPlaying(); } }
  void setChanged(Runnable callback) { changed = callback; }
  void setVolume(float volume) {
    if (!Float.isFinite(volume)) return;
    synchronized (lock) { if (!closed) device.setVolume(Math.max(0, Math.min(1, volume))); }
  }
  /** Dispose outside the ownership lock; never wait for the worker from a guard action. */
  public void close() {
    stop();
    Thread current;
    synchronized (lock) { current = worker; }
    if (current != null && current != Thread.currentThread()) {
      try { current.join(1000); }
      catch (InterruptedException error) { Thread.currentThread().interrupt(); throw new IllegalStateException("Output cleanup interrupted", error); }
      if (current.isAlive()) throw new IllegalStateException("Output worker did not stop; device retained");
    }
    synchronized (lock) { if (!closed) { closed = true; device.close(); } }
  }
}
