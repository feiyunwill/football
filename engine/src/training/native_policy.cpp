#include "training/native_policy.hpp"
#include "training/training_snapshot.hpp"
#include "training/cooperation_metrics.hpp"
#include <cmath>
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
NativePolicyEnvironment::NativePolicyEnvironment(PolicySpec spec, bool checkpoints, int width, int height,bool fixed_teammate)
    : spec_(checked(spec)),fixed_teammate_(fixed_teammate), env_(width, height, spec_.builtin_ai_action || fixed_teammate, spec_.fixed_positions,
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
      static_cast<size_t>(scenario.left_agents + scenario.right_agents) != spec_.players+size_t(fixed_teammate_))
    throw std::invalid_argument("Policy scenario/controller count or cadence mismatch");
  if(fixed_teammate_ && (spec_.players!=1 || spec_.builtin_ai_action || scenario.left_agents!=2 || scenario.right_agents!=0 ||
      scenario.left_team.size()!=3 || scenario.left_team[0].controllable ||
      !scenario.left_team[1].controllable || !scenario.left_team[2].controllable))
    throw std::invalid_argument("Fixed teammate requires learner1/AI2 slots and one19-action learner");
  try {
    auto result = env_.reset(scenario, cadence);
    if(fixed_teammate_) result=PrimaryCooperationObservation(result);
    observation_ = result;
    ready_ = true;
    terminated_ = truncated_ = false;
    return result;
  } catch (...) {
    close();
    throw;
  }
}
NativePolicyStep NativePolicyEnvironment::step(const CategoricalPolicy& policy, PolicyRng& rng,
                                             bool deterministic, bool horizon, std::optional<bool> cooperation_phase) {
  open();
  if (!ready_) throw std::logic_error("Reset native policy environment before stepping");
  if (!spec_.compatible_environment(policy.spec())) throw std::invalid_argument("Policy/environment identity mismatch");
  PolicyRng proposed = rng;
  // Inference/input errors occur before engine mutation and preserve this live env/RNG.
  auto observed=cooperation_phase ? CooperationObservation(observation_,*cooperation_phase,env_.sticky_actions()) : observation_;
  auto decision = policy.decide(observed, proposed, deterministic);
  NativePolicyStep result;
  result.observation = std::move(observed);
  result.decision = std::move(decision);
  try {
    if(fixed_teammate_) {
      auto joint=result.decision.actions;joint.push_back(19);
      result.following=env_.step(joint);
    } else result.following=env_.step(result.decision.actions);
    if(fixed_teammate_) {
      result.following.observations=PrimaryCooperationObservation(result.following.observations);
      result.following.rewards.resize(1);
    }
    result.reward = std::accumulate(result.following.rewards.begin(), result.following.rewards.end(), 0.0) /
                    result.following.rewards.size();
    result.truncated = horizon && !result.following.terminated;
    observation_ = result.following.observations;
    ready_ = !result.following.terminated && !result.truncated;
    terminated_ = result.following.terminated;
    truncated_ = result.truncated;
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
NativePolicySnapshot NativePolicyEnvironment::snapshot() {
  open();
  if (observation_.size() == 0) throw std::logic_error("Reset before saving policy environment");
  return {env_.get_state(), observation_, terminated_, truncated_};
}
void NativePolicyEnvironment::restore(const NativePolicySnapshot& state) {
  open();
  try {
    if (state.observation.size() != spec_.players || state.observation.columns() != spec_.features ||
        (state.terminated && state.truncated)) throw std::invalid_argument("Policy snapshot shape/lifecycle mismatch");
    for (float value : state.observation.buffer())
      if (!std::isfinite(value)) throw std::invalid_argument("Nonfinite policy snapshot observation");
    auto prepared = state.observation;
    const auto decoded = football::training::snapshot::Decode(state.native);
    if (decoded.ready == state.terminated) throw std::invalid_argument("Policy snapshot/native lifecycle mismatch");
    env_.set_state(state.native);
    auto current=env_.current_observation();if(fixed_teammate_) current=PrimaryCooperationObservation(current);
    if (current != prepared) throw std::invalid_argument("Policy snapshot observation disagrees with engine");
    observation_ = std::move(prepared);
    terminated_ = state.terminated; truncated_ = state.truncated;
    ready_ = !terminated_ && !truncated_;
  } catch (...) { close(); throw; }
}
void NativePolicyEnvironment::close() {
  owner();
  if (closed_) return;
  closed_ = true;
  ready_ = false;
  env_.close();
}
}  // namespace football::training
