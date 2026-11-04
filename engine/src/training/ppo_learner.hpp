#pragma once
#include "training/native_policy.hpp"
#include "training/ppo_math.hpp"
#include "training/scenario_sampling.hpp"
#include "training/cooperation_metrics.hpp"
#include <filesystem>
#include <memory>
#include <algorithm>
#include <cmath>

namespace football::training {
inline constexpr uint32_t kPpoCheckpointVersion = 1;
inline constexpr size_t kMaxPpoCheckpointBytes = 32u * 1024u * 1024u;
inline uint32_t PpoPayloadSchema(PpoScenarioVariation variation) {
  return variation==PpoScenarioVariation::Fixed ? 1u :
    variation==PpoScenarioVariation::TwoOnOne ? 3u :
    variation==PpoScenarioVariation::TwoOnOneBroad ? 4u :
    variation==PpoScenarioVariation::TwoOnOneBroadAnnealed ? 5u :
    variation==PpoScenarioVariation::TwoOnOneBroadReweighted ? 6u :
    variation==PpoScenarioVariation::TwoOnOneBroadReweightedLowLr ? 7u :
    variation==PpoScenarioVariation::TwoOnOneBroadReweightedMidLr ? 8u : variation==PpoScenarioVariation::TwoOnOneBroadReweightedFinisher ? 9u : variation==PpoScenarioVariation::TwoOnOneBroadBalancedFinisher ? 10u : variation==PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher ? 11u : variation==PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher ? 12u : variation==PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher ? 13u : variation==PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher ? 14u : variation==PpoScenarioVariation::TwoOnOneBroadFirstStepEntropyFinisher ? 15u : 2u;
}
// The task/schema versions this fixed schedule. Full global update version is
// checkpointed; process/chunk boundaries never restart the annealing clock.
inline double PpoEffectiveLearningRate(PpoScenarioVariation variation,uint64_t version,double base) {
  if(uint32_t(variation)>15 || version>kMaxPpoCounter || !std::isfinite(base) || base<=0 || base>1)
    throw std::invalid_argument("Invalid PPO learning-rate schedule input");
  if(!IsAnnealedVariation(variation))return base;
  return base*std::max(.1,1.0-static_cast<double>(version)/8192.0);
}
struct PpoLearnerConfig {
  PolicySpec policy;
  PpoParameters parameters;
  std::shared_ptr<ScenarioConfig> scenario;
  uint64_t seed = 42;
  uint32_t cadence = 10, episode_limit = 256;
  bool checkpoint_rewards = false;
  PpoScenarioVariation scenario_variation = PpoScenarioVariation::Fixed;
};
struct PpoIteration {
  PpoUpdate update;
  size_t transitions = 0, completed_episodes = 0;
  size_t finishing_practice_episodes = 0, cooperative_episodes = 0;
  double reward = 0, learning_rate = 0;
  std::string trajectory_sha256;
};
class PpoLearner {
 public:
  explicit PpoLearner(PpoLearnerConfig config);
  ~PpoLearner() = default;
  PpoLearner(const PpoLearner&) = delete;
  PpoLearner& operator=(const PpoLearner&) = delete;
  PpoIteration train(size_t steps);
  const CategoricalPolicy& policy() const { check_owner(); return policy_; }
  const AdamState& optimizer() const { check_owner(); return optimizer_; }
  PpoLearnerConfig config() const;
  uint64_t version() const { check_owner(); return version_; }
  uint64_t transitions() const { check_owner(); return transitions_; }
  std::string get_state();
  void set_state(std::string_view bytes);
  void save(const std::filesystem::path& path);
  void load(const std::filesystem::path& path);
 private:
  void check_owner() const;
  void reset_episode();
  PpoLearnerConfig config_;
  CategoricalPolicy policy_;
  AdamState optimizer_;
  PolicyRng sampling_, shuffle_, episodes_;
  std::unique_ptr<NativePolicyEnvironment> env_;
  std::shared_ptr<ScenarioConfig> current_scene_;
  uint64_t version_ = 0, transitions_ = 0, current_episode_ = 0, next_episode_ = 0;
  uint32_t episode_steps_ = 0;
  double episode_reward_ = 0;
  CooperationMetrics cooperation_;
  std::thread::id owner_thread_;
  uint64_t owner_process_;
  bool busy_ = false, failed_ = false;
};
}  // namespace football::training
