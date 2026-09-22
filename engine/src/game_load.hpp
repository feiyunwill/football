// 2026-09-14: loading callbacks execute only on the resource/game owner.
#pragma once
#include <exception>
#include <functional>
#include <string_view>
#include <utility>
class GameLoadCancelled final : public std::exception {
 public:
  GameLoadCancelled() = default;
  ~GameLoadCancelled() override = default;
  GameLoadCancelled(const GameLoadCancelled&) = default;
  GameLoadCancelled& operator=(const GameLoadCancelled&) = default;
  GameLoadCancelled(GameLoadCancelled&&) = default;
  GameLoadCancelled& operator=(GameLoadCancelled&&) = default;
  const char* what() const noexcept override { return "Match loading cancelled"; }
};
class GameLoadScope final {
 public:
  using Callback = std::function<void(std::string_view)>;
  explicit GameLoadScope(Callback callback);
  ~GameLoadScope();
  GameLoadScope() = delete;
  GameLoadScope(const GameLoadScope&) = delete;
  GameLoadScope& operator=(const GameLoadScope&) = delete;
  GameLoadScope(GameLoadScope&&) = delete;
  GameLoadScope& operator=(GameLoadScope&&) = delete;
 private:
  friend void GameLoadCheckpoint(std::string_view stage);
  Callback callback_;
  GameLoadScope* previous_ = nullptr;
};
void GameLoadCheckpoint(std::string_view stage);
// Cleanup guards are released only after all resources have transferred ownership.
template<class Function>
class GameLoadCleanup final {
 public:
  explicit GameLoadCleanup(Function cleanup) : cleanup_(std::move(cleanup)) {}
  ~GameLoadCleanup() noexcept { if (active_) cleanup_(); }
  GameLoadCleanup() = delete;
  GameLoadCleanup(const GameLoadCleanup&) = delete;
  GameLoadCleanup& operator=(const GameLoadCleanup&) = delete;
  GameLoadCleanup(GameLoadCleanup&&) = delete;
  GameLoadCleanup& operator=(GameLoadCleanup&&) = delete;
  void release() noexcept { active_ = false; }
 private:
  Function cleanup_;
  bool active_ = true;
};
