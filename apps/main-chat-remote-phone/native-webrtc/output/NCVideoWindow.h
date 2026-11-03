// NeuralCompanion, MIT. Presentation eligibility, NOT playback completion.
#pragma once
#include <algorithm>
#include <cstdint>

namespace nc {
// One admitted, visible segment. Speech frames use native-confirmed audio as
// master; idle segments require separate explicit admission. No wall clock can
// advance speech here. A hide/stop permanently closes this object; resumption
// needs a fresh segment/keyframe from its current peer, never an old queue.
class VideoWindow {
 public:
  enum class Decision { Drop, Wait, Show };
  VideoWindow(uint64_t generation, uint32_t first_video, uint32_t audio_samples, bool idle)
      : generation_(generation), first_(first_video), samples_(audio_samples), idle_(idle) {}
  bool Admit(uint64_t generation) {
    if (admitted_ || terminal_ || !generation || generation != generation_ || !samples_ || samples_ >= 0x40000000)
      return false;
    // The 90kHz interval must remain shorter than half an RTP wrap.
    if (static_cast<uint64_t>(samples_) * 90000 / 48000 >= 0x80000000ULL) return false;
    admitted_ = true; return true;
  }
  void Played(uint64_t generation, uint32_t samples) {
    if (admitted_ && !terminal_ && generation == generation_ && samples <= samples_)
      confirmed_ = std::max(confirmed_, samples);
  }
  Decision Frame(uint64_t generation, uint32_t timestamp) {
    if (!admitted_ || terminal_ || generation != generation_) return Decision::Drop;
    const uint32_t delta = timestamp - first_;
    const int64_t relative = delta <= 0x7fffffffU ? delta : static_cast<int64_t>(delta) - 0x100000000LL;
    if (relative < 0 || relative <= last_shown_ || relative * 48000 >= static_cast<int64_t>(samples_) * 90000)
      return Decision::Drop;
    if (!idle_) {
      const int64_t played = static_cast<int64_t>(confirmed_) * 90000;
      if (!confirmed_ || relative * 48000 > played) return Decision::Wait;
      if (played - relative * 48000 > 9000LL * 48000) return Decision::Drop;
    }
    last_shown_ = relative;
    return Decision::Show;
  }
  void Stop() { terminal_ = true; }
 private:
  const uint64_t generation_;
  const uint32_t first_, samples_;
  const bool idle_;
  bool admitted_ = false, terminal_ = false;
  uint32_t confirmed_ = 0;
  int64_t last_shown_ = -1;
};
} // namespace nc
