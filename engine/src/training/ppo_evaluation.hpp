#pragma once
#include "training/ppo_learner.hpp"
#include "training/cooperation_metrics.hpp"
namespace football::training {
struct PpoEvaluationEpisode {
  uint32_t engine_seed = 0,start_index=0;
  float start_x=0,start_y=0;
  size_t steps = 0;
  double reward = 0;
  int controlled_score_delta = 0;
  bool terminated = false, truncated = false;
  CooperationMetrics cooperation;
};
struct PpoEvaluationStrategy {
  std::string name;
  std::vector<PpoEvaluationEpisode> episodes;
  double mean_reward = 0, mean_score_delta = 0;
};
struct PpoEvaluation {
  std::vector<PpoEvaluationStrategy> strategies;
  bool isolated = false;
};
// Separate environments/RNGs; verifies that every byte of the training state stays unchanged.
PpoEvaluation EvaluatePpo(PpoLearner& learner, uint64_t evaluation_seed, size_t episodes, size_t horizon,
                          StartPartition partition=StartPartition::Train);
}  // namespace football::training
