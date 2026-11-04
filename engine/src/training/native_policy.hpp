#pragma once
#include "training/categorical_policy.hpp"
#include "training/native_training.hpp"
#include <thread>
#include <optional>

namespace football::training {
struct NativePolicyStep {
  ObservationBuffer observation;
  PolicyDecision decision;
  TrainingTransition following;
  double reward = 0;
  bool truncated = false;
};
struct NativePolicySnapshot {
  std::string native;
  ObservationBuffer observation;
  bool terminated = false, truncated = false;
};

// Policy and sampling RNG remain caller-owned; this adapter owns one engine.
class NativePolicyEnvironment {
 public:
  explicit NativePolicyEnvironment(PolicySpec spec, bool checkpoint_rewards = false,
                                   int width = 160, int height = 90, bool fixed_teammate = false);
  ObservationBuffer reset(ScenarioConfig& scenario, int cadence = 10);
  NativePolicyStep step(const CategoricalPolicy& policy, PolicyRng& rng,
                       bool deterministic = false, bool horizon = false,
                       std::optional<bool> cooperation_phase = std::nullopt);
  const ObservationBuffer& observation() const;
  std::string kernel_state();
  TrainingPossession possession() { open(); return env_.possession(); }
  std::array<uint8_t,10> sticky_actions() { open(); return env_.sticky_actions(); }
  void close();
  bool needs_reset() const;
  NativePolicySnapshot snapshot();
  // Used on a prepared staging owner. A failed restore closes this adapter.
  void restore(const NativePolicySnapshot& state);
 private:
  void owner() const;
  void open() const;
  PolicySpec spec_;
  bool fixed_teammate_ = false;
  NativeTrainingEnv env_;
  ObservationBuffer observation_;
  std::thread::id thread_;
  uint64_t process_;
  bool ready_ = false;
  bool closed_ = false;
  bool terminated_ = false, truncated_ = false;
};
}  // namespace football::training
