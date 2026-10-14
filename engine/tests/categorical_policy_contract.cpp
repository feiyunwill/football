#include "training/categorical_policy.hpp"
#include <array>
#include <cmath>
#include <cstdio>
#include <limits>
#include <stdexcept>

using namespace football::training;
void require(bool value) { if (!value) throw std::runtime_error("Categorical policy contract failed"); }
template<class F> void rejects(F action) {
  try { action(); } catch (const std::invalid_argument&) { return; }
  throw std::runtime_error("Invalid policy input was accepted");
}
void array(std::span<const double> values) {
  std::printf("[");
  for (size_t i = 0; i < values.size(); ++i) std::printf("%s%.17g", i ? "," : "", values[i]);
  std::printf("]");
}
int main() {
  try {
    PolicyRng gold(0);
    require(gold.next() == UINT64_C(0xe220a8397b1dcdaf));
    require(gold.next() == UINT64_C(0x6e789e6aa1b965f4));
    const auto saved = gold.state();
    const double sample = gold.uniform();
    gold.set_state(saved);
    require(gold.uniform() == sample && sample >= 0 && sample < 1);
    const std::array<double, 3> logits{0, std::log(2.0), std::log(3.0)};
    CategoricalDistribution categorical(logits, 1, 3);
    double total = 0, entropy = 0;
    for (size_t i = 0; i < 3; ++i) {
      const double expected = (i + 1.0) / 6;
      require(std::abs(categorical.probabilities()[i] - expected) < 1e-14);
      total += categorical.probabilities()[i];
      entropy -= expected * std::log(expected);
    }
    require(std::abs(total - 1) < 1e-14 && std::abs(categorical.entropy() - entropy) < 1e-14);
    auto shifted = logits;
    for (double& value : shifted) value += 1000;
    CategoricalDistribution other(shifted, 1, 3);
    for (size_t i = 0; i < 3; ++i)
      require(std::abs(categorical.probabilities()[i] - other.probabilities()[i]) < 1e-13);
    const std::array<double, 6> joint_logits{0, std::log(2.0), std::log(3.0), 0, 0, 0};
    CategoricalDistribution joint(joint_logits, 2, 3);
    require(std::abs(joint.log_probability(std::array<int, 2>{2, 1}) - std::log(0.5 / 3)) < 1e-14);
    require(std::abs(joint.entropy() - entropy - std::log(3.0)) < 1e-14);
    require(joint.argmax() == std::vector<int>({2, 0}));
    PolicyRng draws(42), repeat(42);
    std::array<int, 3> counts{};
    for (int i = 0; i < 20000; ++i) {
      auto actions = categorical.sample(draws);
      require(actions == categorical.sample(repeat));
      ++counts[actions[0]];
    }
    for (size_t i = 0; i < 3; ++i)
      require(std::abs(counts[i] / 20000.0 - (i + 1.0) / 6) < .02);
    CategoricalDistribution underflow(std::array<double, 3>{0, -10000, -10000}, 1, 3);
    require(underflow.entropy() == 0 && underflow.sample(draws)[0] == 0);
    rejects([&] { CategoricalDistribution invalid(std::array<double, 1>{NAN}, 1, 1); });
    rejects([&] { CategoricalDistribution invalid(std::array<double, 1>{INFINITY}, 1, 1); });
    rejects([&] { categorical.log_probability(std::array<int, 1>{3}); });
    rejects([&] { categorical.log_probability(std::array<int, 2>{0, 0}); });
    rejects([&] { CategoricalPolicy invalid(PolicySpec{12}, 0); });
    auto wide = PolicySpec{}; wide.hidden = 65;
    rejects([&] { CategoricalPolicy invalid(wide, 0); });
    PolicySpec spec; spec.hidden = 2;
    CategoricalPolicy policy(spec, 7), identical(spec, 7);
    require(policy.parameters() == identical.parameters());
    std::vector<double> parameters(policy.parameters().size());
    for (size_t i = 0; i < parameters.size(); ++i) parameters[i] = (int(i % 7) - 3) * .01;
    policy.set_parameters(parameters);
    ObservationBuffer input(1);
    for (size_t i = 0; i < 115; ++i) input[0][i] = (int(i % 11) - 5) * .05f;
    auto output = policy.forward(input);
    const auto state = draws.state();
    auto decision = policy.decide(input, draws, true);
    require(draws.state() == state);
    auto malformed = parameters; malformed[0] = NAN;
    rejects([&] { policy.set_parameters(malformed); });
    require(policy.parameters() == parameters);
    rejects([&] { policy.forward(ObservationBuffer(2)); });
    input[0][0] = NAN;
    rejects([&] { policy.decide(input, draws); });
    require(draws.state() == state);
    input[0][0] = -.25f;
    PolicySpec maximum{11, 460, 64, true, true};
    CategoricalPolicy full(maximum, 19);
    ObservationBuffer max_input(11, 460);
    auto max_decision = full.decide(max_input, draws);
    require(max_decision.actions.size() == 11 && std::isfinite(max_decision.log_probability));
    std::printf("{\"passed\":true,\"parameters\":"); array(parameters);
    std::printf(",\"input\":[");
    for (size_t i = 0; i < 115; ++i) std::printf("%s%.9g", i ? "," : "", double(input[0][i]));
    std::printf("],\"hidden\":"); array(output.hidden);
    std::printf(",\"logits\":"); array(output.logits);
    std::printf(",\"value\":%.17g,\"argmax\":%d,\"log_probability\":%.17g,\"entropy\":%.17g}\n",
                output.value, decision.actions[0], decision.log_probability, decision.entropy);
    return 0;
  } catch (const std::exception& error) {
    std::fprintf(stderr, "%s\n", error.what());
    return 1;
  }
}
