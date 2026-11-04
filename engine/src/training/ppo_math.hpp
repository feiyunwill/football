#pragma once
#include "training/categorical_policy.hpp"

namespace football::training {
inline constexpr size_t kMaxPpoRollout = 256;
inline constexpr uint64_t kMaxPpoCounter = UINT64_C(1000000000000);
struct PpoParameters {
  double gamma = .99, lambda = .95, clip = .2, value_coefficient = .5, entropy_coefficient = .01;
  double learning_rate = .0003, beta1 = .9, beta2 = .999, adam_epsilon = 1e-8, max_gradient_norm = .5;
  size_t epochs = 4, minibatch = 64;
  bool normalize_advantage = true;
  void validate() const;
  friend bool operator==(const PpoParameters&, const PpoParameters&) = default;
};
struct PpoSample {
  ObservationBuffer observation;
  std::vector<int> actions;
  double old_log_probability = 0, old_value = 0, reward = 0, next_value = 0, entropy_multiplier = 1;
  bool terminated = false, truncated = false;
  uint64_t policy_version = 0;
  double advantage = 0, target = 0;
};
struct PpoGradient {
  std::vector<double> gradient;
  double loss = 0, policy_loss = 0, value_loss = 0, entropy = 0, ratio = 0;
  bool clipped = false;
};
struct AdamState {
  std::vector<double> first, second;
  uint64_t step = 0;
  explicit AdamState(size_t count = 0) : first(count), second(count) {}
  void swap(AdamState& other) noexcept;
};
struct PpoUpdate {
  double loss = 0, entropy = 0, clip_fraction = 0, gradient_norm = 0, parameter_delta = 0;
  uint64_t optimizer_steps = 0;
};
std::vector<PpoSample> PrepareAdvantages(std::span<const PpoSample> samples, const PpoParameters& parameters);
PpoGradient LossGradient(const CategoricalPolicy& policy, const PpoSample& sample, const PpoParameters& parameters);
void AdamStep(CategoricalPolicy& policy, AdamState& state, std::span<const double> gradient,
              const PpoParameters& parameters);
// Full update commits model, optimizer and shuffle RNG together, or preserves all three.
PpoUpdate UpdatePpo(CategoricalPolicy& policy, AdamState& optimizer, PolicyRng& shuffle,
                    std::span<const PpoSample> samples, uint64_t version, const PpoParameters& parameters);
}  // namespace football::training
