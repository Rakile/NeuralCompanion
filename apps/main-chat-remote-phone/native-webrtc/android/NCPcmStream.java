// NeuralCompanion, MIT. One OS device per admitted stream, at most two chunks.
package expo.modules.audio;

import java.util.ArrayDeque;

/** Logical device leases serialize writes while preserving per-chunk native
 * ownership/receipts. Retiring a drained lease never flushes its successor.
 * Cancelling an undrained lease invalidates the WHOLE stream before OS flush.
 * This class grants no authorization and never resumes a cancelled stream.
 */
final class NCPcmStream implements AutoCloseable {
  private final Object lock = new Object();
  private final NCPcmOutput.Device hardware;
  private final ArrayDeque<Lease> leases = new ArrayDeque<>();
  private boolean prepared, playing, terminal, closed;
  private long written, played, lastHead;
  private String failureReason = "";

  NCPcmStream(NCPcmOutput.Device hardware) { this.hardware = hardware; }
  NCPcmOutput.Device next() {
    synchronized (lock) {
      if (terminal || leases.size() >= 2) throw new IllegalStateException("Stream admission closed or full");
      Lease lease = new Lease(); leases.add(lease); return lease;
    }
  }
  private boolean prepare() {
    synchronized (lock) {
      if (terminal) return false;
      if (prepared) return true;
      if (!hardware.prepare()) { stop(); return false; }
      lastHead = hardware.playbackHead();
      if (lastHead < 0 || lastHead > 0xffffffffL) { stop(); return false; }
      prepared = true; return true;
    }
  }
  private long head() {
    if (terminal) throw new IllegalStateException("Stream stopped");
    long value = hardware.playbackHead(), delta = (value - lastHead) & 0xffffffffL;
    if (value < 0 || value > 0xffffffffL || delta > written - played) {
      stop(); throw new IllegalStateException("Output head reset or invalid");
    }
    played += delta; lastHead = value; return played;
  }
  private void stop() {
    if (terminal) return;
    if (failureReason.isEmpty()) failureReason = "device_invalidated";
    terminal = true;
    hardware.stop();
  }
  public void close() {
    synchronized (lock) {
      if (closed) return;
      try { stop(); } finally { closed = true; hardware.close(); }
    }
  }
  private final class Lease implements NCPcmOutput.Device {
    private boolean started, stopped, inputFinished;
    private long base = -1, count;
    public boolean prepare() { return NCPcmStream.this.prepare(); }
    public void play() {
      synchronized (lock) {
        if (terminal || stopped || !prepared) return;
        if (!playing) { hardware.play(); playing = hardware.isPlaying(); }
        started = playing;
      }
    }
    public boolean isPlaying() {
      synchronized (lock) { return started && !stopped && !terminal && hardware.isPlaying(); }
    }
    public int write(short[] pcm, int offset, int size) {
      synchronized (lock) {
        if (terminal || stopped || !started || inputFinished) return -1;
        for (Lease preceding : leases) {
          if (preceding == this) break;
          if (!preceding.inputFinished) return 0;
        }
        if (base < 0) base = written;
        int n = hardware.write(pcm, offset, size);
        if (n < 0 || n > size) { NCPcmStream.this.stop(); return -1; }
        count += n; written += n; return n;
      }
    }
    public void finishInput() { synchronized (lock) { if (!terminal && !stopped && count > 0) inputFinished = true; } }
    public long playbackHead() {
      synchronized (lock) {
        long current = head();
        return base < 0 ? 0 : Math.min(count, Math.max(0, current - base)) & 0xffffffffL;
      }
    }
    public long streamProgress() { synchronized (lock) { return head(); } }
    public String failureReason() { synchronized (lock) { return failureReason; } }
    public void setVolume(float value) { synchronized (lock) { if (!terminal) hardware.setVolume(value); } }
    public void stop() { stopWithFailureReason(""); }
    public void stopWithFailureReason(String reason) {
      synchronized (lock) {
        if (stopped) return;
        boolean drained = !terminal && inputFinished && base >= 0 && head() >= base + count;
        stopped = true;
        if (!drained) {
          if (!terminal && !reason.isEmpty()) failureReason = reason;
          NCPcmStream.this.stop();
        }
        leases.remove(this);
      }
    }
    public void close() { stop(); } // The stream, never a chunk, owns the hardware.
  }
}
