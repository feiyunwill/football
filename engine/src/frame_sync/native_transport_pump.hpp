// 2026-09-13: owned transport work continues during rendering; no SDL or GameEnv calls.
#pragma once
#include <chrono>
#include <condition_variable>
#include <exception>
#include <functional>
#include <mutex>
#include <stdexcept>
#include <thread>
namespace frame_sync {
class NativeTransportPump {
 public:
  explicit NativeTransportPump(std::function<void()> work,bool enabled=true) {
    if (!work) throw std::invalid_argument("Transport pump needs work");
    if (!enabled) return;
    worker_=std::jthread([this,work=std::move(work)](std::stop_token stop) {
      try {
        auto deadline=std::chrono::steady_clock::now();
        constexpr auto period=std::chrono::milliseconds(4);
        while (!stop.stop_requested()) {
          work();
          const auto now=std::chrono::steady_clock::now();
          // Transport opportunities may expire; authority frame IDs do not.
          deadline=now+period-(now-deadline)%period;
          std::unique_lock lock(mu_);
          wake_.wait_until(lock,deadline,[&]{return stop.stop_requested();});
        }
      } catch (...) {
        std::lock_guard lock(mu_);error_=std::current_exception();
      }
    });
  }
  ~NativeTransportPump() { Stop(); }
  NativeTransportPump(const NativeTransportPump&) = delete;
  NativeTransportPump& operator=(const NativeTransportPump&) = delete;
  NativeTransportPump(NativeTransportPump&&) = delete;
  NativeTransportPump& operator=(NativeTransportPump&&) = delete;
  // Only the owner stops/joins. Destruction precedes client and input destruction.
  void Stop() {
    if (!worker_.joinable()) return;
    if (worker_.get_id()==std::this_thread::get_id())
      throw std::logic_error("Transport worker cannot join itself");
    worker_.request_stop();wake_.notify_all();worker_.join();
  }
  void Check() {
    std::lock_guard lock(mu_);if (error_) std::rethrow_exception(error_);
  }
 private:
  std::mutex mu_;
  std::condition_variable wake_;
  std::exception_ptr error_;
  std::jthread worker_;
};
} // namespace frame_sync
