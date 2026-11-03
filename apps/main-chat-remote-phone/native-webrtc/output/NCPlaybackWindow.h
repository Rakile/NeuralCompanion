// NeuralCompanion, MIT. One admitted chunk's source-to-OS-output accounting.
#pragma once
#include <algorithm>
#include <cstdint>
#include <deque>
#include <optional>

namespace nc {
// Caller serializes this object with the EXISTING native playback guard. This
// class does not authenticate/admit requests on its own. A fresh object and
// generation are required for every chunk/output lifetime; stopped is terminal.
// Input PCM and RTP clocks are both 48kHz. The platform adapter must reject any
// other format before using these offsets. No duration timer calls Played().
class PlaybackWindow final {
 public:
  struct Slice { uint64_t token; uint32_t skip; uint32_t frames; };
  PlaybackWindow(uint64_t generation, uint32_t first, uint32_t samples)
      : generation_(generation), first_(first), samples_(samples) {}
  bool Admit(uint64_t generation) {
    if (admitted_ || terminal_ || !generation || generation != generation_ ||
        !samples_ || samples_ >= 0x40000000U) return false;
    admitted_ = true;
    return true;
  }
  std::optional<Slice> Reserve(uint64_t generation, uint32_t timestamp,
                               uint32_t frames, bool valid, bool concealed) {
    if (!admitted_ || terminal_ || generation != generation_ || !valid) return {};
    if (!frames || frames > 960) return Fail("invalid_frame_size");
    int64_t begin = static_cast<uint32_t>(timestamp - first_);
    if (begin > 0x7fffffffLL) begin -= 0x100000000LL;
    const int64_t end = begin + frames;
    if (end <= submitted_ || begin >= samples_) return {};
    const int64_t from = std::max<int64_t>(begin, submitted_);
    const int64_t to = std::min<int64_t>(end, samples_);
    // NetEq can shorten normal speech to control jitter; its source clock then
    // advances farther than the PCM count. Preserve that source endpoint, but
    // never invent PCM for the gap. Pinned NetEq Accelerate::CheckCriteriaAndStretch
    // removes at most 15ms (120 * fs_mult = 720 at 48kHz), including fast mode.
    // Require an established beginning; larger discontinuities remain failures.
    const bool normal_adjustment = submitted_ > 0 && from > submitted_ && from - submitted_ <= 720;
    if (from != submitted_ && (!normal_adjustment || concealed)) return Fail("stream_discontinuity");
    if (pending_.size() >= 50) return Fail("queue_overflow");
    const auto count = static_cast<uint32_t>(to - from);
    if (pending_samples_ + count > 24000) return Fail("queue_overflow");
    // NetEq may reconstruct a short interior loss. These real PCM samples still
    // require OS playback callbacks; decoding alone never confirms playback.
    // Reject a missing beginning/end, >60ms consecutive loss, or excessive total
    // concealment (5%, with a 60ms floor and 250ms ceiling per admitted chunk).
    const auto concealment_budget = std::min<uint32_t>(12000, std::max<uint32_t>(2880, samples_ / 20));
    if (concealed && (!submitted_ || to == samples_ || concealed_run_ + count > 2880 ||
                      concealed_total_ + count > concealment_budget)) return Fail("concealment_limit");
    concealed_run_ = concealed ? concealed_run_ + count : 0;
    if (concealed) concealed_total_ += count;
    const auto token = ++next_token_;
    pending_.push_back({token, static_cast<uint32_t>(to), count, false});
    pending_samples_ += count;
    submitted_ = static_cast<uint32_t>(to);
    return Slice{token, static_cast<uint32_t>(from - begin), count};
  }
  // iOS: dataPlayedBack callback. Android: passed hardware playback-head range.
  // A packet, decoded frame, scheduled buffer or successful write is NOT played.
  bool Played(uint64_t generation, uint64_t token) {
    if (!admitted_ || terminal_ || generation != generation_) return false;
    auto found = std::find_if(pending_.begin(), pending_.end(),
                              [token](const Pending& p) { return p.token == token; });
    if (found == pending_.end() || found->played) return false;
    found->played = true;
    while (!pending_.empty() && pending_.front().played) {
      confirmed_ = pending_.front().end;
      pending_samples_ -= pending_.front().frames;
      pending_.pop_front();
    }
    return true;
  }
  void Stop() { terminal_ = true; pending_.clear(); pending_samples_ = 0; }
  bool Drained() const { return admitted_ && !terminal_ && confirmed_ == samples_ && pending_.empty(); }
  bool InputComplete() const { return admitted_ && !terminal_ && submitted_ == samples_; }
  bool Failed() const { return failed_; }
  const char* FailureReason() const { return failure_reason_; }
  uint32_t ConfirmedSamples() const { return confirmed_; }

 private:
  struct Pending { uint64_t token; uint32_t end; uint32_t frames; bool played; };
  std::optional<Slice> Fail(const char* reason) { failed_ = true; failure_reason_ = reason; Stop(); return {}; }
  const char* failure_reason_ = "";
  const uint64_t generation_;
  const uint32_t first_, samples_;
  bool admitted_ = false, terminal_ = false, failed_ = false;
  uint32_t submitted_ = 0, confirmed_ = 0, pending_samples_ = 0;
  uint32_t concealed_run_ = 0, concealed_total_ = 0;
  uint64_t next_token_ = 0;
  std::deque<Pending> pending_;
};
}  // namespace nc
