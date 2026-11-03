// NeuralCompanion, MIT. Android counterpart of output/NCVideoWindow.h.
package expo.modules.audio;

final class NCVideoWindow {
  enum Decision { DROP, WAIT, SHOW }
  private final long generation, first;
  private final int samples;
  private final boolean idle;
  private boolean admitted, terminal;
  private int confirmed;
  private long lastShown = -1;
  NCVideoWindow(long generation, long first, int samples, boolean idle) {
    this.generation = generation; this.first = first; this.samples = samples; this.idle = idle;
  }
  boolean admit(long value) {
    if (admitted || terminal || value <= 0 || value != generation || samples <= 0 || samples >= 0x40000000
        || first < 0 || first > 0xffffffffL || (long)samples * 90000 / 48000 >= 0x80000000L) return false;
    admitted = true; return true;
  }
  void played(long value, int count) {
    if (admitted && !terminal && value == generation && count >= 0 && count <= samples)
      confirmed = Math.max(confirmed, count);
  }
  Decision frame(long value, long timestamp) {
    if (!admitted || terminal || value != generation || timestamp < 0 || timestamp > 0xffffffffL) return Decision.DROP;
    long relative = (int)(timestamp - first);
    if (relative < 0 || relative <= lastShown || relative * 48000 >= (long)samples * 90000) return Decision.DROP;
    if (!idle) {
      long played = (long)confirmed * 90000;
      if (confirmed == 0 || relative * 48000 > played) return Decision.WAIT;
      if (played - relative * 48000 > 9000L * 48000) return Decision.DROP;
    }
    lastShown = relative; return Decision.SHOW;
  }
  void stop() { terminal = true; }
}
