#pragma once
#include "training/observation_buffer.hpp"
#include <cstdint>
#include <span>
#include <vector>

namespace football::training {
inline constexpr uint32_t kCategoricalPolicyVersion = 1;
inline constexpr uint32_t kPolicyRngVersion = 1;

// SplitMix64 and a 53-bit uniform mapping, versioned independently of stdlib RNGs.
class PolicyRng {
 public:
  explicit PolicyRng(uint64_t seed = 0) : state_(seed) {}
  uint64_t next();
  double uniform();
  uint64_t index(uint64_t bound);
  uint64_t state() const { return state_; }
  void set_state(uint64_t state) { state_ = state; }
 private:
  uint64_t state_;
};

struct PolicySpec {
  size_t players = 1;
  size_t features = 115;
  size_t hidden = 64;
  bool fixed_positions = true;
  bool builtin_ai_action = false;
  size_t actions() const { return builtin_ai_action ? 20 : 19; }
  size_t inputs() const { return players * features; }
  size_t outputs() const { return players * actions() + 1; }
  void validate() const;
  bool compatible_environment(const PolicySpec& other) const;
  friend bool operator==(const PolicySpec&, const PolicySpec&) = default;
};

class CategoricalDistribution {
 public:
  CategoricalDistribution(std::span<const double> logits, size_t players, size_t actions);
  const std::vector<double>& probabilities() const { return probabilities_; }
  const std::vector<double>& log_probabilities() const { return log_probabilities_; }
  double entropy() const { return entropy_; }
  double log_probability(std::span<const int> actions) const;
  std::vector<int> sample(PolicyRng& rng) const;
  std::vector<int> argmax() const;
 private:
  size_t players_, actions_;
  std::vector<double> probabilities_, log_probabilities_;
  double entropy_ = 0;
};

struct PolicyOutput {
  std::vector<double> hidden;
  std::vector<double> logits;
  double value = 0;
};
struct PolicyDecision {
  std::vector<int> actions;
  double log_probability = 0;
  double entropy = 0;
  double value = 0;
};

// Flattened joint observation -> tanh hidden -> per-player logits and team value.
// Parameter order: input weights [hidden,input], hidden bias, output weights
// [players*actions+1,hidden], output bias. The last output is the scalar value.
class CategoricalPolicy {
 public:
  explicit CategoricalPolicy(PolicySpec spec, uint64_t initialization_seed);
  const PolicySpec& spec() const { return spec_; }
  const std::vector<double>& parameters() const { return parameters_; }
  void set_parameters(std::span<const double> parameters);
  PolicyOutput forward(const ObservationBuffer& observation) const;
  PolicyDecision decide(const ObservationBuffer& observation, PolicyRng& rng,
                        bool deterministic = false) const;
  size_t hidden_bias_offset() const { return spec_.hidden * spec_.inputs(); }
  size_t output_weights_offset() const { return hidden_bias_offset() + spec_.hidden; }
  size_t output_bias_offset() const { return output_weights_offset() + spec_.outputs() * spec_.hidden; }
 private:
  PolicySpec spec_;
  std::vector<double> parameters_;
};
}  // namespace football::training
