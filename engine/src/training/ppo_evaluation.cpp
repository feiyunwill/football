#include "training/ppo_evaluation.hpp"
#include <algorithm>
#include <numeric>
#include <stdexcept>
namespace football::training {
PpoEvaluation EvaluatePpo(PpoLearner& learner, uint64_t seed, size_t episodes, size_t horizon, StartPartition partition) {
  if (uint32_t(partition)>uint32_t(StartPartition::Holdout) || episodes > 64 || horizon < 1 || horizon > 4096) throw std::invalid_argument("Evaluation budget exceeded");
  const auto before = learner.get_state();
  const auto config = learner.config();
  const bool cooperative=IsCooperativeVariation(config.scenario_variation);
  PolicyRng scenario_rng(seed ^ UINT64_C(0x243f6a8885a308d3));
  std::vector<uint32_t> seeds;
  for (size_t i = 0; i < episodes; ++i) seeds.push_back(scenario_rng.index(2000000001));
  PpoEvaluation result;
  for (const auto& name : {"sample", "argmax", "uniform_random", "builtin_ai"}) {
    PpoEvaluationStrategy strategy; strategy.name = name;
    // K=20 admits builtin-AI index19 for the baseline. Other indices preserve
    // default/v2 semantics; the model/random modes still use their configured K.
    NativeTrainingEnv env(160, 90, true, config.policy.fixed_positions, config.checkpoint_rewards,
                          config.policy.features == 460);
    for (size_t episode = 0; episode < episodes; ++episode) {
      auto scene = *config.scenario; scene.game_engine_random_seed = seeds[episode];
      const auto start_index=ApplyPpoStart(scene,config.scenario_variation,seeds[episode],partition);
      auto observation = env.reset(scene, config.cadence);
      PolicyRng actions(seed ^ UINT64_C(0x13198a2e03707344) ^ (episode * UINT64_C(0x9e3779b97f4a7c15)));
      PpoEvaluationEpisode metric; metric.engine_seed = seeds[episode];
      metric.start_index=start_index; metric.start_x=scene.ball_position.coords[0]; metric.start_y=scene.ball_position.coords[1];
      if(cooperative) metric.cooperation.observe(env.possession());
      while (metric.steps < horizon) {
        std::vector<int> joint(config.policy.players);
        if (strategy.name == "builtin_ai") std::fill(joint.begin(), joint.end(), 19);
        else if (strategy.name == "uniform_random")
          for (int& action : joint) action = actions.index(config.policy.actions());
        else joint = learner.policy().decide(cooperative ? CooperationObservation(observation,metric.cooperation.completed_passes>0,env.sticky_actions()) : observation,
                                             actions, strategy.name == "argmax").actions;
        if(cooperative) metric.cooperation.action(env.possession(),joint.front());
        if(cooperative) joint.push_back(19); // Fixed teammate, excluded from learned logits/log-probability.
        auto transition = env.step(joint);
        if(cooperative) metric.cooperation.observe(env.possession());
        metric.reward += cooperative ? transition.rewards.front() : std::accumulate(transition.rewards.begin(), transition.rewards.end(), 0.0) / transition.rewards.size();
        metric.controlled_score_delta += (scene.right_agents ? -1 : 1) * transition.score_reward;
        ++metric.steps; metric.terminated = transition.terminated;
        observation = std::move(transition.observations);
        if (metric.terminated) break;
      }
      metric.truncated = !metric.terminated && metric.steps == horizon;
      strategy.mean_reward += metric.reward; strategy.mean_score_delta += metric.controlled_score_delta;
      strategy.episodes.push_back(metric);
    }
    if (episodes) { strategy.mean_reward /= episodes; strategy.mean_score_delta /= episodes; }
    env.close(); result.strategies.push_back(std::move(strategy));
  }
  result.isolated = before == learner.get_state();
  if (!result.isolated) throw std::runtime_error("Evaluation changed training state");
  return result;
}
}  // namespace football::training
