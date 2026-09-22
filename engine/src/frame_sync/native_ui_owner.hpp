// 2026-09-13: the creating thread services UI while one joined worker owns the game.
#pragma once
#include <atomic>
#include <chrono>
#include <exception>
#include <stdexcept>
#include <stop_token>
#include <thread>
#include <utility>
namespace frame_sync {
class NativeUIOwner {
 public:
  NativeUIOwner() : owner_(std::this_thread::get_id()) {}
  ~NativeUIOwner() = default;
  NativeUIOwner(const NativeUIOwner&) = delete;
  NativeUIOwner& operator=(const NativeUIOwner&) = delete;
  NativeUIOwner(NativeUIOwner&&) = delete;
  NativeUIOwner& operator=(NativeUIOwner&&) = delete;

  bool IsOwnerThread() const noexcept { return std::this_thread::get_id() == owner_; }
  // Only this run's worker can pass. A third thread must not become a device or game owner.
  void CheckWorker() const {
    if (worker_owner_ != this) throw std::logic_error("Native game worker owner mismatch");
    if (worker_stop_.stop_requested()) throw std::runtime_error("Native UI service stopped");
  }
  template<class Work, class Service> void Run(Work&& work, Service&& service) {
    if (!IsOwnerThread()) throw std::logic_error("Native UI must run on its creating thread");
    if (running_) throw std::logic_error("Native UI loop already running");
    running_ = true;
    try {
      std::atomic<bool> finished{false};
      std::exception_ptr error;
      std::jthread worker([&](std::stop_token stop) {
        worker_owner_ = this;
        worker_stop_ = stop;
        try { std::forward<Work>(work)(); }
        catch (...) { error = std::current_exception(); }
        worker_stop_ = {};
        worker_owner_ = nullptr;
        finished.store(true, std::memory_order_release);
      });
      try {
        while (!finished.load(std::memory_order_acquire)) {
          service();
          std::this_thread::sleep_for(std::chrono::milliseconds(4));
        }
      } catch (...) {
        // The work loop observes cancellation at its next safe input/pacing boundary.
        // Join before UI state, captures, SDL resources or the GameEnv can be destroyed.
        worker.request_stop();
        worker.join();
        throw;
      }
      worker.join();
      if (error) std::rethrow_exception(error);
    } catch (...) {
      running_ = false;
      throw;
    }
    running_ = false;
  }
 private:
  const std::thread::id owner_;
  bool running_ = false;  // Only the creating thread accesses this flag.
  inline static thread_local const NativeUIOwner* worker_owner_ = nullptr;
  inline static thread_local std::stop_token worker_stop_;
};
}  // namespace frame_sync
