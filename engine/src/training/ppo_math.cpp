#include "training/ppo_math.hpp"
#include <algorithm>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <type_traits>

namespace football::training {
namespace {
void check(bool condition, const char* message) { if (!condition) throw std::invalid_argument(message); }
void finite(double value) { check(std::isfinite(value), "Nonfinite PPO arithmetic"); }
void sample_values(const PpoSample& sample) {
  for (double value : {sample.old_log_probability, sample.old_value, sample.reward,
                       sample.next_value, sample.entropy_multiplier, sample.advantage, sample.target}) finite(value);
  check(sample.old_log_probability <= 0, "Old categorical log probability must be nonpositive");
  check(sample.entropy_multiplier > 0 && sample.entropy_multiplier <= 10, "Invalid PPO entropy multiplier");
  check(!sample.terminated || !sample.truncated, "Terminal takes precedence over truncation");
}
void optimizer_values(const AdamState& state, size_t count) {
  check(state.first.size() == count && state.second.size() == count && state.step <= kMaxPpoCounter,
        "Adam shape/step mismatch");
  for (size_t i = 0; i < count; ++i) {
    finite(state.first[i]); finite(state.second[i]);
    check(state.second[i] >= 0, "Negative Adam second moment");
  }
}
}
void PpoParameters::validate() const {
  for (double value : {gamma, lambda, clip, value_coefficient, entropy_coefficient, learning_rate,
                       beta1, beta2, adam_epsilon, max_gradient_norm}) finite(value);
  check(gamma >= 0 && gamma <= 1 && lambda >= 0 && lambda <= 1 && clip > 0 && clip < 1 &&
        value_coefficient >= 0 && value_coefficient <= 10 && entropy_coefficient >= 0 && entropy_coefficient <= 1 &&
        learning_rate > 0 && learning_rate <= 1 && beta1 >= 0 && beta1 < 1 && beta2 >= 0 && beta2 < 1 &&
        adam_epsilon > 0 && adam_epsilon <= 1 && max_gradient_norm > 0 && max_gradient_norm <= 1e6 &&
        epochs >= 1 && epochs <= 16 && minibatch >= 1 && minibatch <= kMaxPpoRollout, "Invalid PPO parameters");
}
void AdamState::swap(AdamState& other) noexcept {
  first.swap(other.first); second.swap(other.second); std::swap(step, other.step);
}
std::vector<PpoSample> PrepareAdvantages(std::span<const PpoSample> samples, const PpoParameters& parameters) {
  parameters.validate();
  check(!samples.empty() && samples.size() <= kMaxPpoRollout, "PPO rollout budget exceeded");
  std::vector<PpoSample> result(samples.begin(), samples.end());
  double previous = 0;
  for (size_t i = result.size(); i-- > 0;) {
    auto& sample = result[i]; sample_values(sample);
    const double delta = sample.reward + parameters.gamma * (sample.terminated ? 0 : sample.next_value) - sample.old_value;
    sample.advantage = delta + parameters.gamma * parameters.lambda *
                              (sample.terminated || sample.truncated ? 0 : previous);
    sample.target = sample.advantage + sample.old_value;
    finite(sample.advantage); finite(sample.target);
    previous = sample.advantage;
  }
  if (parameters.normalize_advantage) {
    double mean = 0, sum_squares = 0;
    size_t count = 0;
    for (const auto& sample : result) {
      const double delta = sample.advantage - mean;
      mean += delta / ++count;
      sum_squares += delta * (sample.advantage - mean);
    }
    finite(mean); finite(sum_squares);
    const double denominator = std::sqrt(std::max(0.0, sum_squares / result.size())) + 1e-8;
    for (auto& sample : result) { sample.advantage = (sample.advantage - mean) / denominator; finite(sample.advantage); }
  }
  return result;
}
namespace {
// Scratch storage belongs to one update; no shared or checkpointed state.
void loss_gradient(const CategoricalPolicy& policy, const PpoSample& sample,
                   const PpoParameters& parameters, PpoGradient& result,
                   std::vector<double>& derivative, std::vector<double>& hidden_derivative) {
  parameters.validate(); sample_values(sample);
  auto output = policy.forward(sample.observation);
  const auto& spec = policy.spec();
  CategoricalDistribution distribution(output.logits, spec.players, spec.actions());
  const double log_probability = distribution.log_probability(sample.actions);
  result.ratio = std::exp(log_probability - sample.old_log_probability); finite(result.ratio);
  const double clipped_ratio = std::clamp(result.ratio, 1 - parameters.clip, 1 + parameters.clip);
  result.clipped = result.ratio != clipped_ratio;
  const bool saturated = (sample.advantage >= 0 && result.ratio > 1 + parameters.clip) ||
                         (sample.advantage < 0 && result.ratio < 1 - parameters.clip);
  result.policy_loss = -(saturated ? clipped_ratio : result.ratio) * sample.advantage;
  const double error = output.value - sample.target;
  result.value_loss = .5 * error * error;
  result.entropy = distribution.entropy();
  const double entropy_coefficient = parameters.entropy_coefficient * sample.entropy_multiplier;
  result.loss = result.policy_loss + parameters.value_coefficient * result.value_loss - entropy_coefficient * result.entropy;
  finite(result.loss); finite(result.policy_loss); finite(result.value_loss);
  const double coefficient = saturated ? 0 : -sample.advantage * result.ratio;
  finite(coefficient);
  derivative.resize(spec.outputs());
  for (size_t player = 0; player < spec.players; ++player) {
    double entropy = 0;
    for (size_t action = 0; action < spec.actions(); ++action) {
      const size_t index = player * spec.actions() + action;
      entropy -= distribution.probabilities()[index] * distribution.log_probabilities()[index];
    }
    for (size_t action = 0; action < spec.actions(); ++action) {
      const size_t index = player * spec.actions() + action;
      const double probability = distribution.probabilities()[index];
      derivative[index] = coefficient * ((static_cast<int>(action) == sample.actions[player] ? 1.0 : 0.0) - probability) +
                          entropy_coefficient * probability * (distribution.log_probabilities()[index] + entropy);
    }
  }
  derivative.back() = parameters.value_coefficient * error;
  // All parameter entries are overwritten below; retain capacity across samples.
  result.gradient.resize(policy.parameters().size());
  hidden_derivative.assign(spec.hidden, 0);
  for (size_t row = 0; row < spec.outputs(); ++row) {
    result.gradient[policy.output_bias_offset() + row] = derivative[row];
    for (size_t hidden = 0; hidden < spec.hidden; ++hidden) {
      const size_t index = policy.output_weights_offset() + row * spec.hidden + hidden;
      result.gradient[index] = derivative[row] * output.hidden[hidden];
      hidden_derivative[hidden] += policy.parameters()[index] * derivative[row];
    }
  }
  const auto input = sample.observation.buffer();
  for (size_t hidden = 0; hidden < spec.hidden; ++hidden) {
    const double delta = hidden_derivative[hidden] * (1 - output.hidden[hidden] * output.hidden[hidden]);
    result.gradient[policy.hidden_bias_offset() + hidden] = delta;
    for (size_t i = 0; i < input.size(); ++i) result.gradient[hidden * input.size() + i] = delta * input[i];
  }
  for (double value : result.gradient) finite(value);
}
}  // namespace
PpoGradient LossGradient(const CategoricalPolicy& policy, const PpoSample& sample, const PpoParameters& parameters) {
  PpoGradient result;
  std::vector<double> derivative, hidden_derivative;
  loss_gradient(policy, sample, parameters, result, derivative, hidden_derivative);
  return result;
}
void AdamStep(CategoricalPolicy& policy, AdamState& state, std::span<const double> gradient,
              const PpoParameters& parameters) {
  parameters.validate(); optimizer_values(state, policy.parameters().size());
  check(gradient.size() == policy.parameters().size() && state.step < kMaxPpoCounter, "Adam gradient/step mismatch");
  AdamState proposed = state;
  auto weights = policy.parameters();
  ++proposed.step;
  const double first_correction = 1 - std::pow(parameters.beta1, static_cast<double>(proposed.step));
  const double second_correction = 1 - std::pow(parameters.beta2, static_cast<double>(proposed.step));
  for (size_t i = 0; i < gradient.size(); ++i) {
    finite(gradient[i]);
    proposed.first[i] = parameters.beta1 * proposed.first[i] + (1 - parameters.beta1) * gradient[i];
    proposed.second[i] = parameters.beta2 * proposed.second[i] + (1 - parameters.beta2) * gradient[i] * gradient[i];
    weights[i] -= parameters.learning_rate * (proposed.first[i] / first_correction) /
                  (std::sqrt(proposed.second[i] / second_correction) + parameters.adam_epsilon);
    finite(proposed.first[i]); finite(proposed.second[i]); finite(weights[i]);
  }
  policy.set_parameters(weights); state.swap(proposed);
}
PpoUpdate UpdatePpo(CategoricalPolicy& policy, AdamState& optimizer, PolicyRng& shuffle,
                    std::span<const PpoSample> samples, uint64_t version, const PpoParameters& parameters) {
  parameters.validate(); optimizer_values(optimizer, policy.parameters().size());
  check(version < kMaxPpoCounter, "PPO version counter exceeded");
  auto prepared = PrepareAdvantages(samples, parameters);
  for (const auto& sample : prepared) {
    check(sample.policy_version == version, "PPO rollout mixes policy versions");
    auto current = policy.forward(sample.observation);
    CategoricalDistribution distribution(current.logits, policy.spec().players, policy.spec().actions());
    check(distribution.log_probability(sample.actions) == sample.old_log_probability && current.value == sample.old_value,
          "PPO rollout was not collected from the current frozen policy");
  }
  auto proposed_policy = policy;
  auto proposed_optimizer = optimizer;
  auto proposed_rng = shuffle;
  std::vector<size_t> order(samples.size()); std::iota(order.begin(), order.end(), 0);
  PpoUpdate result;
  size_t evaluated = 0, batches = 0;
  PpoGradient value;
  std::vector<double> derivative, hidden_derivative;
  std::vector<double> gradient(policy.parameters().size());
  for (size_t epoch = 0; epoch < parameters.epochs; ++epoch) {
    for (size_t i = order.size(); i > 1; --i) std::swap(order[i - 1], order[proposed_rng.index(i)]);
    for (size_t offset = 0; offset < order.size(); offset += parameters.minibatch) {
      const size_t count = std::min(parameters.minibatch, order.size() - offset);
      std::fill(gradient.begin(), gradient.end(), 0);
      for (size_t i = 0; i < count; ++i) {
        loss_gradient(proposed_policy, prepared[order[offset + i]], parameters,
                      value, derivative, hidden_derivative);
        result.loss += value.loss; result.entropy += value.entropy; result.clip_fraction += value.clipped;
        for (size_t j = 0; j < gradient.size(); ++j) gradient[j] += value.gradient[j] / count;
        ++evaluated;
      }
      double norm = 0; for (double value : gradient) { finite(value); norm = std::hypot(norm, value); }
      finite(norm); result.gradient_norm += norm; ++batches;
      if (norm > parameters.max_gradient_norm)
        for (double& value : gradient) value *= parameters.max_gradient_norm / norm;
      AdamStep(proposed_policy, proposed_optimizer, gradient, parameters);
    }
  }
  result.loss /= evaluated; result.entropy /= evaluated; result.clip_fraction /= evaluated;
  result.gradient_norm /= batches;
  for (size_t i = 0; i < policy.parameters().size(); ++i)
    result.parameter_delta = std::hypot(result.parameter_delta, proposed_policy.parameters()[i] - policy.parameters()[i]);
  for (double value : {result.loss, result.entropy, result.gradient_norm, result.parameter_delta}) finite(value);
  result.optimizer_steps = proposed_optimizer.step - optimizer.step;
  static_assert(std::is_nothrow_move_assignable_v<CategoricalPolicy>);
  policy = std::move(proposed_policy); optimizer.swap(proposed_optimizer); shuffle = proposed_rng;
  return result;
}
}  // namespace football::training
