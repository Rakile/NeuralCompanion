// NeuralCompanion, MIT. Android counterpart of output/NCPlaybackWindow.h.
package expo.modules.audio;

import java.util.ArrayDeque;

/** Caller serializes with the output owner. This class does not authenticate.
 * Clocks are 48kHz; the adapter validates format before passing PCM offsets.
 * played() is called only when the OS playback head passes the submitted range.
 */
final class NCPcmWindow {
  static final class Slice {
    final long token;
    final int skip, frames;
    Slice(long token, int skip, int frames) { this.token = token; this.skip = skip; this.frames = frames; }
  }
  private static final class Pending {
    final long token;
    final int end, frames;
    boolean played;
    Pending(long token, int end, int frames) { this.token = token; this.end = end; this.frames = frames; }
  }
  private final long generation, first;
  private final int samples;
  private final ArrayDeque<Pending> pending = new ArrayDeque<>();
  private boolean admitted, terminal, failed;
  private String failureReason = "";
  private int submitted, confirmed, pendingSamples;
  private int concealedRun, concealedTotal;
  private long nextToken;

  NCPcmWindow(long generation, long first, int samples) {
    this.generation = generation; this.first = first; this.samples = samples;
  }
  boolean admit(long value) {
    if (admitted || terminal || value <= 0 || value != generation || samples <= 0
        || samples >= 0x40000000 || first < 0 || first > 0xffffffffL) return false;
    admitted = true; return true;
  }
  Slice reserve(long value, long timestamp, int frames, boolean valid, boolean concealed) {
    if (!admitted || terminal || value != generation || !valid) return null;
    if (frames <= 0 || frames > 960 || timestamp < 0 || timestamp > 0xffffffffL) return fail("invalid_frame_size");
    // Convert the unsigned modulo-32-bit delta to signed source-relative time.
    long begin = (int)(timestamp - first);
    long end = begin + frames;
    if (end <= submitted || begin >= samples) return null;
    long from = Math.max(begin, submitted), to = Math.min(end, samples);
    // Pinned NetEq can accelerate normal speech: source time then advances more
    // than PCM count. Never invent PCM or accept a missing beginning.
    // Accelerate::CheckCriteriaAndStretch caps removal at 15ms = 720/48k.
    boolean normalAdjustment = submitted > 0 && from > submitted && from - submitted <= 720;
    if (from != submitted && (!normalAdjustment || concealed)) return fail("stream_discontinuity");
    if (pending.size() >= 50) return fail("queue_overflow");
    int count = (int)(to - from);
    if (pendingSamples + count > 24000) return fail("queue_overflow");
    // Match iOS: bounded NetEq reconstruction inside an established window,
    // never a concealed beginning/end. Only OS consumption confirms this PCM.
    int concealmentBudget = Math.min(12000, Math.max(2880, samples / 20));
    if (concealed && (submitted == 0 || to == samples || concealedRun + count > 2880
        || concealedTotal + count > concealmentBudget)) return fail("concealment_limit");
    concealedRun = concealed ? concealedRun + count : 0;
    if (concealed) concealedTotal += count;
    long token = ++nextToken;
    pending.add(new Pending(token, (int)to, count));
    pendingSamples += count; submitted = (int)to;
    return new Slice(token, (int)(from - begin), count);
  }
  boolean played(long value, long token) {
    if (!admitted || terminal || value != generation) return false;
    Pending found = null;
    for (Pending item : pending) if (item.token == token) { found = item; break; }
    if (found == null || found.played) return false;
    found.played = true;
    while (!pending.isEmpty() && pending.peek().played) {
      Pending item = pending.remove();
      confirmed = item.end; pendingSamples -= item.frames;
    }
    return true;
  }
  void stop() { terminal = true; pending.clear(); pendingSamples = 0; }
  boolean drained() { return admitted && !terminal && confirmed == samples && pending.isEmpty(); }
  boolean inputComplete() { return admitted && !terminal && submitted == samples; }
  boolean failed() { return failed; }
  int confirmedSamples() { return confirmed; }
  String failureReason() { return failureReason; }
  private Slice fail(String reason) { failed = true; failureReason = reason; stop(); return null; }
}
