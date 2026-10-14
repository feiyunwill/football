#pragma once
#include "training/ppo_learner.hpp"
namespace football::training {
struct PpoEvaluationEpisode {
  uint32_t engine_seed = 0;
  size_t steps = 0;
  double reward = 0;
  int controlled_score_delta = 0;
  bool terminated = false, truncated = false;
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
PpoEvaluation EvaluatePpo(PpoLearner& learner, uint64_t evaluation_seed, size_t episodes, size_t horizon);
}  // namespace football::training
