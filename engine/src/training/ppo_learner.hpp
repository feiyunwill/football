#pragma once
#include "training/native_policy.hpp"
#include "training/ppo_math.hpp"
#include <filesystem>
#include <memory>

namespace football::training {
inline constexpr uint32_t kPpoCheckpointVersion = 1;
inline constexpr size_t kMaxPpoCheckpointBytes = 32u * 1024u * 1024u;
struct PpoLearnerConfig {
  PolicySpec policy;
  PpoParameters parameters;
  std::shared_ptr<ScenarioConfig> scenario;
  uint64_t seed = 42;
  uint32_t cadence = 10, episode_limit = 256;
  bool checkpoint_rewards = false;
};
struct PpoIteration {
  PpoUpdate update;
  size_t transitions = 0, completed_episodes = 0;
  double reward = 0;
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
  std::thread::id owner_thread_;
  uint64_t owner_process_;
  bool busy_ = false, failed_ = false;
};
}  // namespace football::training
