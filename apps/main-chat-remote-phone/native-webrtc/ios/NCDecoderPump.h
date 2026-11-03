// NeuralCompanion, MIT. Decoder scheduling only; never an output-progress clock.
#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <thread>

namespace nc {
// Pulls NetEq on one dedicated thread and discards its mixed output. Track sinks
// can copy decoded, timestamped PCM to a separately admitted native output path.
// No hardware/session API is called here. Callback must be bounded, nonthrowing,
// and must not invoke Start/Stop/destruction (which join the callback thread).
class DecoderPump final {
 public:
  using Pull = std::function<bool(int16_t*, size_t, int64_t)>;
  explicit DecoderPump(Pull pull) : pull_(std::move(pull)) {}
  ~DecoderPump() { Stop(); }
  DecoderPump(const DecoderPump&) = delete;
  DecoderPump& operator=(const DecoderPump&) = delete;

  bool Running() const { return running_.load(); }
  bool Start() {
    std::lock_guard<std::mutex> control(control_);
    if (running_.load()) return true;
    if (thread_.joinable() || !pull_) return false;
    running_ = true;
    try {
      thread_ = std::thread([this] { Run(); });
    } catch (...) {
      running_ = false;
      return false;
    }
    return true;
  }
  void Stop() {
    std::lock_guard<std::mutex> control(control_);
    {
      std::lock_guard<std::mutex> wait(wait_);
      running_ = false;
    }
    wake_.notify_all();
    if (thread_.joinable()) thread_.join();
  }

 private:
  void Run() {
    int64_t sample = 0;
    auto next = std::chrono::steady_clock::now();
    while (running_.load()) {
      next += std::chrono::milliseconds(10);
      std::array<int16_t, 480> pcm{};
      if (!pull_(pcm.data(), pcm.size(), sample)) {
        running_ = false;
        break;
      }
      sample += 480;
      // Keep the 48kHz consumer cadence anchored across normal scheduling jitter.
      // A relative sleep permanently accumulates every late wake/callback and
      // starves a separately clocked AVAudioEngine. Never burst after a long stall.
      const auto now = std::chrono::steady_clock::now();
      if (now - next > std::chrono::milliseconds(30)) next = now;
      std::unique_lock<std::mutex> wait(wait_);
      wake_.wait_until(wait, next, [this] { return !running_.load(); });
    }
  }
  const Pull pull_;
  std::atomic<bool> running_{false};
  std::mutex control_, wait_;
  std::condition_variable wake_;
  std::thread thread_;
};
}  // namespace nc
