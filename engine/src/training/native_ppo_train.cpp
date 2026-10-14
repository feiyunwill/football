#include "training/ppo_evaluation.hpp"
#include "frame_sync/default_scenario.hpp"
#include "frame_sync/state_hash.hpp"
#include <charconv>
#include <chrono>
#include <cstdio>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>

using namespace football::training;
namespace {
uint64_t number(std::string_view text, uint64_t maximum) {
  uint64_t value = 0;
  auto parsed = std::from_chars(text.data(), text.data()+text.size(), value);
  if (parsed.ec != std::errc{} || parsed.ptr != text.data()+text.size() || value > maximum)
    throw std::invalid_argument("Invalid numeric option");
  return value;
}
std::string sha(std::string_view bytes) {
  frame_sync::SHA256 hash; hash.update(reinterpret_cast<const uint8_t*>(bytes.data()),bytes.size());
  uint8_t value[32]; hash.finalize(value); std::string result;
  const char* alphabet="0123456789abcdef";
  for (auto byte : value) {result+=alphabet[byte>>4];result+=alphabet[byte&15];} return result;
}
std::string evaluations(const PpoEvaluation& result) {
  std::ostringstream out; out << std::setprecision(17) << "{\"isolated\":" << (result.isolated?"true":"false") << ",\"strategies\":[";
  for (size_t i=0; i<result.strategies.size(); ++i) {
    const auto& strategy=result.strategies[i];
    out << (i?",":"") << "{\"name\":\"" << strategy.name << "\",\"mean_reward\":" << strategy.mean_reward
        << ",\"mean_score_delta\":" << strategy.mean_score_delta << ",\"episodes\":[";
    for (size_t j=0; j<strategy.episodes.size(); ++j) {
      const auto& episode=strategy.episodes[j];
      out << (j?",":"") << "{\"engine_seed\":" << episode.engine_seed << ",\"steps\":" << episode.steps
          << ",\"reward\":" << episode.reward << ",\"controlled_score_delta\":" << episode.controlled_score_delta
          << ",\"terminated\":" << (episode.terminated?"true":"false")
          << ",\"truncated\":" << (episode.truncated?"true":"false") << "}";
    }
    out << "]}";
  }
  out << "]}"; return out.str();
}
}
int main(int argc, char** argv) {
  try {
    PpoLearnerConfig config;
    size_t updates=4,rollout=128,eval_episodes=4,eval_steps=128;
    uint64_t evaluation_seed=12345;
    std::string scenario="empty_goal",load,save;
    bool right=false,initial_eval=true;
    std::set<std::string> seen;
    for (int i=1; i<argc; ++i) {
      std::string option=argv[i];
      if (option=="--help") {
        std::puts("native_ppo_train [--scenario empty_goal|11v11] [--seed N] [--updates 0..1024] [--rollout 1..256] [--players 1..11] [--hidden 1..64] [--cadence 1..1000] [--episode-limit 1..4096] [--epochs 1..16] [--minibatch 1..256] [--eval-seed N] [--eval-episodes 0..64] [--eval-steps 1..4096] [--right] [--v2] [--compact] [--stacked] [--checkpoints] [--no-initial-eval] [--load FILE] [--save FILE]");
        return 0;
      }
      if (!seen.insert(option).second) throw std::invalid_argument("Duplicate option");
      if (option=="--right") {right=true;continue;}
      if (option=="--v2") {config.policy.builtin_ai_action=true;continue;}
      if (option=="--compact") {config.policy.fixed_positions=false;continue;}
      if (option=="--stacked") {config.policy.features=460;continue;}
      if (option=="--checkpoints") {config.checkpoint_rewards=true;continue;}
      if (option=="--no-initial-eval") {initial_eval=false;continue;}
      if (i+1==argc) throw std::invalid_argument("Missing option value");
      const std::string value=argv[++i];
      if (option=="--scenario") scenario=value;
      else if (option=="--load") load=value;
      else if (option=="--save") save=value;
      else if (option=="--seed") config.seed=number(value,UINT64_MAX);
      else if (option=="--eval-seed") evaluation_seed=number(value,UINT64_MAX);
      else if (option=="--updates") updates=number(value,1024);
      else if (option=="--rollout") rollout=number(value,256);
      else if (option=="--players") config.policy.players=number(value,11);
      else if (option=="--hidden") config.policy.hidden=number(value,64);
      else if (option=="--cadence") config.cadence=number(value,1000);
      else if (option=="--episode-limit") config.episode_limit=number(value,4096);
      else if (option=="--epochs") config.parameters.epochs=number(value,16);
      else if (option=="--minibatch") config.parameters.minibatch=number(value,256);
      else if (option=="--eval-episodes") eval_episodes=number(value,64);
      else if (option=="--eval-steps") eval_steps=number(value,4096);
      else throw std::invalid_argument("Unknown option");
    }
    if (!rollout || !eval_steps || !config.cadence || !config.episode_limit)
      throw std::invalid_argument("Step budgets and cadence must be positive");
    config.policy.validate(); config.parameters.validate();
    config.scenario=frame_sync::MakeDefaultScenario(right?0:config.policy.players,right?config.policy.players:0,42);
    if (scenario=="empty_goal") {
      if ((!right && config.policy.players>2) || (right && config.policy.players>1))
        throw std::invalid_argument("Empty-goal roster has at most two left/one right players");
      config.scenario->left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,true),FormationEntry(.75f,0,e_PlayerRole_CB,false,true)};
      config.scenario->right_team={FormationEntry(1,0,e_PlayerRole_GK,false,true)};
      config.scenario->ball_position=blunted::Vector3(.77f,0,0);
      config.scenario->game_duration=400; config.scenario->offsides=false;
      config.scenario->end_episode_on_score=true; config.scenario->end_episode_on_out_of_play=true;
      config.scenario->end_episode_on_possession_change=true;
    } else if (scenario!="11v11") throw std::invalid_argument("Unknown builtin scenario");
    // Both named scenarios are project-owned deterministic C++ templates.
    config.scenario->deterministic=true;
    const auto start=std::chrono::steady_clock::now();
    PpoLearner learner(config);
    if (!load.empty()) learner.load(load);
    const auto start_version=learner.version();
    std::string initial="null";
    if (initial_eval && eval_episodes) initial=evaluations(EvaluatePpo(learner,evaluation_seed,eval_episodes,eval_steps));
    std::ostringstream iterations; iterations << std::setprecision(17) << "[";
    for (size_t i=0; i<updates; ++i) {
      auto result=learner.train(rollout);
      iterations << (i?",":"") << "{\"version\":" << learner.version() << ",\"transitions\":" << result.transitions
        << ",\"completed_episodes\":" << result.completed_episodes << ",\"reward\":" << result.reward
        << ",\"trajectory_sha256\":\"" << result.trajectory_sha256 << "\",\"loss\":" << result.update.loss
        << ",\"entropy\":" << result.update.entropy << ",\"clip_fraction\":" << result.update.clip_fraction
        << ",\"gradient_norm\":" << result.update.gradient_norm << ",\"parameter_delta\":" << result.update.parameter_delta
        << ",\"optimizer_steps\":" << result.update.optimizer_steps << "}";
    }
    iterations << "]";
    const auto before=learner.get_state();
    auto evaluation=EvaluatePpo(learner,evaluation_seed,eval_episodes,eval_steps);
    const auto after=learner.get_state();
    if (before!=after) throw std::runtime_error("Final evaluation changed learner state");
    if (!save.empty()) learner.save(save);
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ostringstream out; out << std::setprecision(17);
    out << "{\"mode\":\"native_categorical_ppo\",\"scenario\":\"" << scenario << "\",\"seed\":" << config.seed
        << ",\"players\":" << config.policy.players << ",\"features\":" << config.policy.features
        << ",\"actions\":" << config.policy.actions() << ",\"hidden\":" << config.policy.hidden
        << ",\"right_team\":" << (right?"true":"false")
        << ",\"fixed_positions\":" << (config.policy.fixed_positions?"true":"false")
        << ",\"checkpoint_rewards\":" << (config.checkpoint_rewards?"true":"false")
        << ",\"ppo\":{\"gamma\":" << config.parameters.gamma << ",\"lambda\":" << config.parameters.lambda
        << ",\"clip\":" << config.parameters.clip << ",\"value_coefficient\":" << config.parameters.value_coefficient
        << ",\"entropy_coefficient\":" << config.parameters.entropy_coefficient
        << ",\"learning_rate\":" << config.parameters.learning_rate << ",\"beta1\":" << config.parameters.beta1
        << ",\"beta2\":" << config.parameters.beta2 << ",\"epsilon\":" << config.parameters.adam_epsilon
        << ",\"max_gradient_norm\":" << config.parameters.max_gradient_norm << ",\"epochs\":" << config.parameters.epochs
        << ",\"minibatch\":" << config.parameters.minibatch << ",\"normalize_advantage\":"
        << (config.parameters.normalize_advantage?"true":"false") << "}"
        << ",\"cadence\":" << config.cadence << ",\"episode_limit\":" << config.episode_limit
        << ",\"evaluation_seed\":" << evaluation_seed << ",\"evaluation_horizon\":" << eval_steps
        << ",\"start_version\":" << start_version << ",\"version\":" << learner.version()
        << ",\"total_transitions\":" << learner.transitions() << ",\"iterations\":" << iterations.str()
        << ",\"initial_evaluation\":" << initial << ",\"evaluation\":" << evaluations(evaluation)
        << ",\"state_before_evaluation_sha256\":\"" << sha(before) << "\",\"state_sha256\":\"" << sha(after)
        << "\",\"checkpoint_bytes\":" << after.size() << ",\"wall_seconds\":" << seconds << "}";
    std::puts(out.str().c_str()); return 0;
  } catch (const std::exception& error) {std::fprintf(stderr,"%s\n",error.what());return 1;}
}
