#pragma once
#include "training/categorical_policy.hpp"
#include "training/native_training.hpp"
#include <thread>

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
                                   int width = 160, int height = 90);
  ObservationBuffer reset(ScenarioConfig& scenario, int cadence = 10);
  NativePolicyStep step(const CategoricalPolicy& policy, PolicyRng& rng,
                       bool deterministic = false, bool horizon = false);
  const ObservationBuffer& observation() const;
  std::string kernel_state();
  void close();
  bool needs_reset() const;
  NativePolicySnapshot snapshot();
  // Used on a prepared staging owner. A failed restore closes this adapter.
  void restore(const NativePolicySnapshot& state);
 private:
  void owner() const;
  void open() const;
  PolicySpec spec_;
  NativeTrainingEnv env_;
  ObservationBuffer observation_;
  std::thread::id thread_;
  uint64_t process_;
  bool ready_ = false;
  bool closed_ = false;
  bool terminated_ = false, truncated_ = false;
};
}  // namespace football::training
