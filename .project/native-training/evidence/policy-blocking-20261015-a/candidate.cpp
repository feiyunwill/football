#include "training/categorical_policy.hpp"
#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace football::training {
namespace {
void finite(double value, const char* message) {
  if (!std::isfinite(value)) throw std::invalid_argument(message);
}
}
uint64_t PolicyRng::next() {
  uint64_t value = (state_ += UINT64_C(0x9e3779b97f4a7c15));
  value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
  value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
  return value ^ (value >> 31);
}
double PolicyRng::uniform() { return static_cast<double>(next() >> 11) * 0x1.0p-53; }
uint64_t PolicyRng::index(uint64_t bound) {
  if (!bound) throw std::invalid_argument("Random index bound must be positive");
  const uint64_t threshold = (uint64_t{0} - bound) % bound;
  for (;;) { const uint64_t draw = next(); if (draw >= threshold) return draw % bound; }
}

void PolicySpec::validate() const {
  if (players < 1 || players > kMaxTrainingAgents ||
      (features != kSimple115Features && features != kSimple115Features * kFrameStackFrames) ||
      hidden < 1 || hidden > 64)
    throw std::invalid_argument("Policy requires 1..11 players, 115/460 features and 1..64 hidden units");
}
bool PolicySpec::compatible_environment(const PolicySpec& other) const {
  return players == other.players && features == other.features &&
         fixed_positions == other.fixed_positions && builtin_ai_action == other.builtin_ai_action;
}

CategoricalDistribution::CategoricalDistribution(std::span<const double> logits,
                                               size_t players, size_t actions)
    : players_(players), actions_(actions) {
  if (players < 1 || players > kMaxTrainingAgents || actions < 1 || actions > 20 ||
      logits.size() != players * actions)
    throw std::invalid_argument("Invalid categorical dimensions");
  for (double value : logits) finite(value, "Categorical logits must be finite");
  probabilities_.resize(logits.size());
  log_probabilities_.resize(logits.size());
  for (size_t player = 0; player < players; ++player) {
    auto row = logits.subspan(player * actions, actions);
    const double maximum = *std::max_element(row.begin(), row.end());
    double total = 0;
    for (size_t action = 0; action < actions; ++action) {
      const double shifted = row[action] - maximum;
      finite(shifted, "Categorical shifted logits overflowed");
      total += std::exp(shifted);
    }
    const double log_total = std::log(total);
    for (size_t action = 0; action < actions; ++action) {
      const size_t index = player * actions + action;
      const double log_probability = row[action] - maximum - log_total;
      finite(log_probability, "Categorical log probability overflowed");
      log_probabilities_[index] = log_probability;
      const double probability = probabilities_[index] = std::exp(log_probability);
      if (probability > 0) entropy_ -= probability * log_probability;
    }
  }
  finite(entropy_, "Categorical entropy must be finite");
}
double CategoricalDistribution::log_probability(std::span<const int> actions) const {
  if (actions.size() != players_) throw std::invalid_argument("One categorical action per player is required");
  double result = 0;
  for (size_t player = 0; player < players_; ++player) {
    if (actions[player] < 0 || static_cast<size_t>(actions[player]) >= actions_)
      throw std::invalid_argument("Categorical action is out of range");
    result += log_probabilities_[player * actions_ + actions[player]];
  }
  finite(result, "Joint categorical log probability overflowed");
  return result;
}
std::vector<int> CategoricalDistribution::sample(PolicyRng& rng) const {
  std::vector<int> result(players_);
  for (size_t player = 0; player < players_; ++player) {
    const double draw = rng.uniform();
    double total = 0;
    int last_positive = 0;
    bool selected = false;
    for (size_t action = 0; action < actions_; ++action) {
      const double probability = probabilities_[player * actions_ + action];
      if (probability > 0) last_positive = static_cast<int>(action);
      total += probability;
      if (draw < total) {
        result[player] = static_cast<int>(action);
        selected = true;
        break;
      }
    }
    // Round-off in the CDF must never select an underflowed zero-probability bin.
    if (!selected) result[player] = last_positive;
  }
  return result;
}
std::vector<int> CategoricalDistribution::argmax() const {
  std::vector<int> result(players_);
  for (size_t player = 0; player < players_; ++player) {
    auto first = log_probabilities_.begin() + player * actions_;
    result[player] = static_cast<int>(std::max_element(first, first + actions_) - first);
  }
  return result;
}

CategoricalPolicy::CategoricalPolicy(PolicySpec spec, uint64_t seed) : spec_(spec) {
  spec_.validate();
  parameters_.assign(output_bias_offset() + spec_.outputs(), 0);
  PolicyRng rng(seed);
  const double input_scale = std::sqrt(6.0 / (spec_.inputs() + spec_.hidden));
  const double output_scale = std::sqrt(6.0 / (spec_.hidden + spec_.outputs()));
  for (size_t i = 0; i < hidden_bias_offset(); ++i)
    parameters_[i] = (2 * rng.uniform() - 1) * input_scale;
  for (size_t i = output_weights_offset(); i < output_bias_offset(); ++i)
    parameters_[i] = (2 * rng.uniform() - 1) * output_scale;
}
void CategoricalPolicy::set_parameters(std::span<const double> parameters) {
  if (parameters.size() != parameters_.size()) throw std::invalid_argument("Policy parameter count mismatch");
  for (double value : parameters) finite(value, "Policy parameters must be finite");
  // Prepare the complete replacement before commit, including aliased input spans.
  std::vector<double> prepared(parameters.begin(), parameters.end());
  parameters_.swap(prepared);
}
PolicyOutput CategoricalPolicy::forward(const ObservationBuffer& observation) const {
  if (observation.size() != spec_.players || observation.columns() != spec_.features)
    throw std::invalid_argument("Policy observation shape mismatch");
  const auto input = observation.buffer();
  for (float value : input) finite(value, "Policy observation must be finite");
  PolicyOutput output;
  output.hidden.resize(spec_.hidden);
  output.logits.resize(spec_.players * spec_.actions());
  // Independent accumulators expose parallel work without reassociating any
  // neuron's input sum. Keep the scalar tail for widths not divisible by four.
  size_t hidden = 0;
  for (; hidden + 4 <= spec_.hidden; hidden += 4) {
    double a = parameters_[hidden_bias_offset() + hidden];
    double b = parameters_[hidden_bias_offset() + hidden + 1];
    double c = parameters_[hidden_bias_offset() + hidden + 2];
    double d = parameters_[hidden_bias_offset() + hidden + 3];
    const double* weights = parameters_.data() + hidden * input.size();
    for (size_t i = 0; i < input.size(); ++i) {
      const double x = input[i];
      a += weights[i] * x;
      b += weights[input.size() + i] * x;
      c += weights[2 * input.size() + i] * x;
      d += weights[3 * input.size() + i] * x;
    }
    finite(a, "Policy hidden preactivation overflowed");
    finite(b, "Policy hidden preactivation overflowed");
    finite(c, "Policy hidden preactivation overflowed");
    finite(d, "Policy hidden preactivation overflowed");
    output.hidden[hidden] = std::tanh(a);
    output.hidden[hidden + 1] = std::tanh(b);
    output.hidden[hidden + 2] = std::tanh(c);
    output.hidden[hidden + 3] = std::tanh(d);
  }
  for (; hidden < spec_.hidden; ++hidden) {
    double value = parameters_[hidden_bias_offset() + hidden];
    for (size_t i = 0; i < input.size(); ++i)
      value += parameters_[hidden * input.size() + i] * input[i];
    finite(value, "Policy hidden preactivation overflowed");
    output.hidden[hidden] = std::tanh(value);
  }
  for (size_t row = 0; row < spec_.outputs(); ++row) {
    double value = parameters_[output_bias_offset() + row];
    for (size_t hidden = 0; hidden < spec_.hidden; ++hidden)
      value += parameters_[output_weights_offset() + row * spec_.hidden + hidden] * output.hidden[hidden];
    finite(value, "Policy output overflowed");
    if (row < output.logits.size()) output.logits[row] = value;
    else output.value = value;
  }
  return output;
}
PolicyDecision CategoricalPolicy::decide(const ObservationBuffer& observation, PolicyRng& rng,
                                       bool deterministic) const {
  auto output = forward(observation);
  CategoricalDistribution distribution(output.logits, spec_.players, spec_.actions());
  PolicyRng proposed = rng;
  auto actions = deterministic ? distribution.argmax() : distribution.sample(proposed);
  const double log_probability = distribution.log_probability(actions);
  PolicyDecision result{std::move(actions), log_probability, distribution.entropy(), output.value};
  rng = proposed;
  return result;
}
}  // namespace football::training
