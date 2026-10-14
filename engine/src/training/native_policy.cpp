#include "training/native_policy.hpp"
#include <numeric>
#include <stdexcept>
#if defined(_WIN32)
#include <process.h>
#else
#include <unistd.h>
#endif

namespace football::training {
namespace {
PolicySpec checked(PolicySpec spec) { spec.validate(); return spec; }
uint64_t process_id() {
#if defined(_WIN32)
  return static_cast<uint64_t>(::_getpid());
#else
  return static_cast<uint64_t>(::getpid());
#endif
}
}
NativePolicyEnvironment::NativePolicyEnvironment(PolicySpec spec, bool checkpoints, int width, int height)
    : spec_(checked(spec)), env_(width, height, spec_.builtin_ai_action, spec_.fixed_positions,
                               checkpoints, spec_.features == 460),
      observation_(0, spec_.features), thread_(std::this_thread::get_id()), process_(process_id()) {}
void NativePolicyEnvironment::owner() const {
  if (thread_ != std::this_thread::get_id() || process_ != process_id())
    throw std::logic_error("Native policy environment requires its creating process/thread");
}
void NativePolicyEnvironment::open() const {
  owner();
  if (closed_) throw std::logic_error("Native policy environment is closed");
}
ObservationBuffer NativePolicyEnvironment::reset(ScenarioConfig& scenario, int cadence) {
  open();
  if (cadence < 1 || cadence > 1000 || scenario.control_all_players || scenario.real_time ||
      scenario.left_agents < 0 || scenario.right_agents < 0 ||
      (scenario.left_agents == 0) == (scenario.right_agents == 0) ||
      static_cast<size_t>(scenario.left_agents + scenario.right_agents) != spec_.players)
    throw std::invalid_argument("Policy scenario/controller count or cadence mismatch");
  try {
    auto result = env_.reset(scenario, cadence);
    observation_ = result;
    ready_ = true;
    return result;
  } catch (...) {
    close();
    throw;
  }
}
NativePolicyStep NativePolicyEnvironment::step(const CategoricalPolicy& policy, PolicyRng& rng,
                                             bool deterministic, bool horizon) {
  open();
  if (!ready_) throw std::logic_error("Reset native policy environment before stepping");
  if (!spec_.compatible_environment(policy.spec())) throw std::invalid_argument("Policy/environment identity mismatch");
  PolicyRng proposed = rng;
  // Inference/input errors occur before engine mutation and preserve this live env/RNG.
  auto decision = policy.decide(observation_, proposed, deterministic);
  NativePolicyStep result;
  result.observation = observation_;
  result.decision = std::move(decision);
  try {
    result.following = env_.step(result.decision.actions);
    result.reward = std::accumulate(result.following.rewards.begin(), result.following.rewards.end(), 0.0) /
                    result.following.rewards.size();
    result.truncated = horizon && !result.following.terminated;
    observation_ = result.following.observations;
    ready_ = !result.following.terminated && !result.truncated;
    rng = proposed;
    return result;
  } catch (...) {
    close();
    throw;
  }
}
const ObservationBuffer& NativePolicyEnvironment::observation() const {
  open();
  if (observation_.size() == 0) throw std::logic_error("Reset before reading policy observation");
  return observation_;
}
std::string NativePolicyEnvironment::kernel_state() { open(); return env_.get_state_digest(); }
bool NativePolicyEnvironment::needs_reset() const { owner(); return !ready_; }
void NativePolicyEnvironment::close() {
  owner();
  if (closed_) return;
  closed_ = true;
  ready_ = false;
  env_.close();
}
}  // namespace football::training
