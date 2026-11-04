#include "training/ppo_evaluation.hpp"
#include "training/native_inference.hpp"
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
          << ",\"start_index\":" << episode.start_index << ",\"start_x\":" << episode.start_x << ",\"start_y\":" << episode.start_y
          << ",\"reward\":" << episode.reward << ",\"controlled_score_delta\":" << episode.controlled_score_delta
          << ",\"pass_requests\":" << episode.cooperation.pass_requests
          << ",\"completed_passes\":" << episode.cooperation.completed_passes
          << ",\"teammate_transfers\":" << episode.cooperation.teammate_transfers
          << ",\"turnovers\":" << episode.cooperation.turnovers
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
    for(int i=1;i<argc;++i)
      if(std::string_view(argv[i])=="--inference-mode")return inference::Run(argc,argv);
    PpoLearnerConfig config;
    size_t updates=4,rollout=128,eval_episodes=4,eval_steps=128;
    uint64_t evaluation_seed=12345;
    std::string scenario="empty_goal",load,save,export_policy;
    bool right=false,initial_eval=true;
    StartPartition partition=StartPartition::Train;
    std::set<std::string> seen;
    for (int i=1; i<argc; ++i) {
      std::string option=argv[i];
      if (option=="--help") {
        std::puts("Inference: native_ppo_train --inference-mode balanced|argmax|sample|uniform_random|builtin_ai --policy FILE.fpol --inference-cases FILE [--inference-decisions N --inference-state-out FILE] [--inference-state-in FILE]. Export a current compatible 2v1 model using --export-policy FILE.fpol.");
        std::puts("native_ppo_train [--scenario empty_goal|varied_empty_goal|varied_keeper|2v1|2v1_broad|2v1_broad_annealed|2v1_broad_reweighted|2v1_broad_reweighted_lowlr|2v1_broad_reweighted_midl|2v1_broad_reweighted_finisher|2v1_broad_balanced_finisher|2v1_broad_edge_balanced_finisher|2v1_broad_entropy_stable_finisher|2v1_broad_entropy_midpoint_finisher|2v1_broad_entropy_high_finisher|2v1_broad_firststep_entropy_finisher|11v11] [--seed N] [--updates 0..2048] [--rollout 1..256] [--players 1..11] [--hidden 1..64] [--cadence 1..1000] [--episode-limit 1..4096] [--epochs 1..16] [--minibatch 1..256] [--eval-partition train|validation|test|confirmation|replication|prospective|holdout] [--eval-seed N] [--eval-episodes 0..64] [--eval-steps 1..4096] [--right] [--v2] [--compact] [--stacked] [--checkpoints] [--no-initial-eval] [--load FILE] [--save FILE]");
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
      else if (option=="--eval-partition") {
        if(value=="train") partition=StartPartition::Train;
        else if(value=="validation") partition=StartPartition::Validation;
        else if(value=="test") partition=StartPartition::Test;
        else if(value=="confirmation") partition=StartPartition::Confirmation;
        else if(value=="replication") partition=StartPartition::Replication;
        else if(value=="prospective") partition=StartPartition::Prospective;
        else if(value=="holdout") partition=StartPartition::Holdout;
        else throw std::invalid_argument("Unknown evaluation partition");
      }
      else if (option=="--load") load=value;
      else if (option=="--save") save=value;
      else if (option=="--export-policy") export_policy=value;
      else if (option=="--seed") config.seed=number(value,UINT64_MAX);
      else if (option=="--eval-seed") evaluation_seed=number(value,UINT64_MAX);
      else if (option=="--updates") updates=number(value,2048);
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
    if (scenario=="empty_goal" || scenario=="varied_empty_goal" || scenario=="varied_keeper") {
      if ((!right && config.policy.players>2) || (right && config.policy.players>1))
        throw std::invalid_argument("Empty-goal roster has at most two left/one right players");
      config.scenario->left_team={FormationEntry(-1,0,e_PlayerRole_GK,false,true),FormationEntry(.75f,0,e_PlayerRole_CB,false,true)};
      config.scenario->right_team={FormationEntry(1,0,e_PlayerRole_GK,false,true)};
      config.scenario->ball_position=blunted::Vector3(.77f,0,0);
      if(scenario!="empty_goal") {
        if(right || config.policy.players!=1) throw std::invalid_argument("Variable shooting requires one left agent");
        config.scenario_variation=scenario=="varied_keeper" ? PpoScenarioVariation::Keeper : PpoScenarioVariation::EmptyGoal;
        config.scenario->right_team[0]=FormationEntry(1,scenario=="varied_empty_goal" ? .6f : 0.f,
                                                     e_PlayerRole_GK,scenario!="varied_keeper",true);
      }
      config.scenario->game_duration=400; config.scenario->offsides=false;
      config.scenario->end_episode_on_score=true; config.scenario->end_episode_on_out_of_play=true;
      config.scenario->end_episode_on_possession_change=true;
    } else if (scenario=="2v1" || scenario=="2v1_broad" || scenario=="2v1_broad_annealed" || scenario=="2v1_broad_reweighted" || scenario=="2v1_broad_reweighted_lowlr" || scenario=="2v1_broad_reweighted_midl" || scenario=="2v1_broad_reweighted_finisher" || scenario=="2v1_broad_balanced_finisher" || scenario=="2v1_broad_edge_balanced_finisher" || scenario=="2v1_broad_entropy_stable_finisher" || scenario=="2v1_broad_entropy_midpoint_finisher" || scenario=="2v1_broad_entropy_high_finisher" || scenario=="2v1_broad_firststep_entropy_finisher") {
      if(right || config.policy.players!=1 || config.policy.builtin_ai_action) throw std::invalid_argument("2v1 requires one19-action left learner");
      ConfigureTwoOnOne(*config.scenario);
      config.scenario_variation=scenario=="2v1" ? PpoScenarioVariation::TwoOnOne :
        scenario=="2v1_broad" ? PpoScenarioVariation::TwoOnOneBroad :
        scenario=="2v1_broad_annealed" ? PpoScenarioVariation::TwoOnOneBroadAnnealed :
        scenario=="2v1_broad_reweighted" ? PpoScenarioVariation::TwoOnOneBroadReweighted :
        scenario=="2v1_broad_reweighted_lowlr" ? PpoScenarioVariation::TwoOnOneBroadReweightedLowLr : scenario=="2v1_broad_reweighted_midl" ? PpoScenarioVariation::TwoOnOneBroadReweightedMidLr : scenario=="2v1_broad_reweighted_finisher" ? PpoScenarioVariation::TwoOnOneBroadReweightedFinisher : scenario=="2v1_broad_balanced_finisher" ? PpoScenarioVariation::TwoOnOneBroadBalancedFinisher : scenario=="2v1_broad_edge_balanced_finisher" ? PpoScenarioVariation::TwoOnOneBroadEdgeBalancedFinisher : scenario=="2v1_broad_entropy_stable_finisher" ? PpoScenarioVariation::TwoOnOneBroadEntropyStableFinisher : scenario=="2v1_broad_entropy_midpoint_finisher" ? PpoScenarioVariation::TwoOnOneBroadEntropyMidpointFinisher : scenario=="2v1_broad_entropy_high_finisher" ? PpoScenarioVariation::TwoOnOneBroadEntropyHighFinisher : PpoScenarioVariation::TwoOnOneBroadFirstStepEntropyFinisher;
      if(scenario=="2v1_broad_reweighted_lowlr") config.parameters.learning_rate=.0002;
      if(scenario=="2v1_broad_reweighted_midl") config.parameters.learning_rate=.00025;
      if(scenario=="2v1_broad_entropy_stable_finisher") config.parameters.entropy_coefficient=.02;
      if(scenario=="2v1_broad_entropy_midpoint_finisher") config.parameters.entropy_coefficient=.015;
      if(scenario=="2v1_broad_entropy_high_finisher") config.parameters.entropy_coefficient=.025;
      if(scenario=="2v1_broad_firststep_entropy_finisher") config.parameters.entropy_coefficient=.02;
    } else if (scenario!="11v11") throw std::invalid_argument("Unknown builtin scenario");
    // Named scenarios are project-owned deterministic C++ templates.
    config.scenario->deterministic=true;
    if(!export_policy.empty()&&(!IsCooperativeVariation(config.scenario_variation)||config.policy.features!=115||!config.policy.fixed_positions||export_policy==load||export_policy==save))
      throw std::invalid_argument("Policy export requires fixed simple115 2v1 and a distinct output path");
    const auto start=std::chrono::steady_clock::now();
    PpoLearner learner(config);
    if (!load.empty()) learner.load(load);
    const auto start_version=learner.version();
    std::string initial="null";
    if (initial_eval && eval_episodes) initial=evaluations(EvaluatePpo(learner,evaluation_seed,eval_episodes,eval_steps,partition));
    std::ostringstream iterations; iterations << std::setprecision(17) << "[";
    for (size_t i=0; i<updates; ++i) {
      auto result=learner.train(rollout);
      iterations << (i?",":"") << "{\"version\":" << learner.version() << ",\"transitions\":" << result.transitions
        << ",\"completed_episodes\":" << result.completed_episodes << ",\"reward\":" << result.reward
        << ",\"finishing_practice_episodes\":" << result.finishing_practice_episodes
        << ",\"cooperative_episodes\":" << result.cooperative_episodes
        << ",\"trajectory_sha256\":\"" << result.trajectory_sha256 << "\",\"loss\":" << result.update.loss
        << ",\"entropy\":" << result.update.entropy << ",\"clip_fraction\":" << result.update.clip_fraction
        << ",\"gradient_norm\":" << result.update.gradient_norm << ",\"parameter_delta\":" << result.update.parameter_delta
        << ",\"learning_rate\":" << result.learning_rate
        << ",\"optimizer_steps\":" << result.update.optimizer_steps << "}";
    }
    iterations << "]";
    const auto before=learner.get_state();
    auto evaluation=EvaluatePpo(learner,evaluation_seed,eval_episodes,eval_steps,partition);
    const auto after=learner.get_state();
    if (before!=after) throw std::runtime_error("Final evaluation changed learner state");
    if (!save.empty()) learner.save(save);
    if (!export_policy.empty()) inference::ExportPolicy(learner.policy(),config.seed,after,export_policy);
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::ostringstream out; out << std::setprecision(17);
    out << "{\"mode\":\"native_categorical_ppo\",\"scenario\":\"" << scenario << "\",\"seed\":" << config.seed
        << ",\"players\":" << config.policy.players << ",\"features\":" << config.policy.features
        << ",\"native_agents\":" << config.scenario->left_agents+config.scenario->right_agents
        << ",\"fixed_teammate_builtin_ai\":" << (IsCooperativeVariation(config.scenario_variation) ? "true" : "false")
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
        << ",\"evaluation_partition\":" << uint32_t(partition)
        << ",\"evaluation_seed\":" << evaluation_seed << ",\"evaluation_horizon\":" << eval_steps
        << ",\"start_version\":" << start_version << ",\"version\":" << learner.version()
        << ",\"total_transitions\":" << learner.transitions() << ",\"iterations\":" << iterations.str()
        << ",\"initial_evaluation\":" << initial << ",\"evaluation\":" << evaluations(evaluation)
        << ",\"state_before_evaluation_sha256\":\"" << sha(before) << "\",\"state_sha256\":\"" << sha(after)
        << "\",\"checkpoint_bytes\":" << after.size() << ",\"wall_seconds\":" << seconds << "}";
    std::puts(out.str().c_str()); return 0;
  } catch (const std::exception& error) {std::fprintf(stderr,"%s\n",error.what());return 1;}
}
