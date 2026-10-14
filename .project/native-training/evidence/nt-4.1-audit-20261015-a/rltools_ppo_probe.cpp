// Probe the vendored PPO's actual Gaussian and GAE semantics, not a reimplementation.
#include <rl_tools/operations/cpu_mux.h>
#include <rl_tools/numeric_types/policy.h>
#include <rl_tools/nn/optimizers/adam/instance/operations_generic.h>
#include <rl_tools/nn/layers/standardize/operations_generic.h>
#include <rl_tools/nn_models/mlp_unconditional_stddev/operations_generic.h>
#include <rl_tools/nn_models/sequential/operations_generic.h>
#include <rl_tools/nn/optimizers/adam/operations_generic.h>
#include <rl_tools/rl/algorithms/ppo/loop/core/config.h>
#include <rl_tools/rl/algorithms/ppo/loop/core/operations_generic.h>
#include <cmath>
#include <cstdio>

namespace rlt = rl_tools;
using Device = rlt::devices::DEVICE_FACTORY<>;
using TI = Device::index_t;
using Policy = rlt::numeric_types::Policy<double>;
struct Env {
  struct Observation { static constexpr TI DIM = 1; };
  using ObservationPrivileged = Observation;
  static constexpr TI ACTION_DIM = 1;
};
using Runner = rlt::rl::components::on_policy_runner::Specification<Policy, TI, Env, int, 1>;
using DatasetSpec = rlt::rl::components::on_policy_runner::DatasetSpecification<Runner, 1>;
using Parameters = rlt::rl::algorithms::ppo::DefaultParameters<Policy, TI, 1>;

int main() {
  Device device;
  rlt::rl::components::on_policy_runner::Dataset<DatasetSpec> dataset;
  rlt::malloc(device, dataset);
  rlt::set_all(device, dataset.data, 0.0);
  rlt::set(dataset.rewards, 0, 0, 1.0);
  rlt::set(dataset.all_values, 0, 0, 2.0);
  rlt::set(dataset.all_values, 1, 0, 3.0);
  double measured[3];
  const bool terminations[] = {false, false, true};
  const bool truncations[] = {false, true, true};
  for (int i = 0; i < 3; ++i) {
    rlt::set(dataset.terminated, 0, 0, double(terminations[i]));
    rlt::set(dataset.truncated, 0, 0, double(truncations[i]));
    rlt::estimate_generalized_advantages(device, dataset, Parameters{});
    measured[i] = rlt::get(dataset.advantages, 0, 0);
  }
  const double gaussian_log_prob = rlt::random::normal_distribution::log_prob(device.random, 0.0, 0.0, 0.0);
  const double expected[] = {1.97, 0.0, -1.0};
  bool passed = std::abs(gaussian_log_prob + .5 * std::log(2 * std::acos(-1.0))) < 1e-12;
  for (int i = 0; i < 3; ++i) passed &= std::abs(measured[i] - expected[i]) < 1e-12;
  std::printf("{\"gaussian_log_prob_zero\":%.17g,\"gae_live\":%.17g,\"gae_truncated\":%.17g,\"gae_terminal\":%.17g,\"passed\":%s}\n",
              gaussian_log_prob, measured[0], measured[1], measured[2], passed ? "true" : "false");
  rlt::free(device, dataset);
  return passed ? 0 : 1;
}
